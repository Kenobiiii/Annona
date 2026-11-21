# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic portions for a drafted plan: a small linear programme (scipy/HiGHS).

The LLM proposes, per meal, ingredients and amounts for one reference serving. The code then
chooses a multiplier x_j for every (meal, ingredient) so that:

* each member's energy on each day equals their target for the meals they eat
  (target x the planned slot shares x ``energy_scale``);
* each member's weekly protein reaches ``protein_min_ratio`` of their target;
* the household never uses more of a product than is available (purchase + pantry);
* x_j stays within [min_scale, max_scale] of the drafted amount;
* and the total deviation sum |x_j - 1| is as small as possible: stay close to the LLM's dish.

Members share dishes: member m eats r_m x the reference serving, with r_m = m's daily energy /
the first member's. If no solution exists, an *elastic* version adds a slack to every energy,
protein and stock constraint and minimises the normalised slack; the slacks become precise
issues sent back to the LLM in the repair request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from scipy.optimize import linprog

from annona_core.domain import MealSlot

from .draft import DraftMeal

Key = tuple[date, MealSlot]


@dataclass
class PortionSolution:
    ok: bool
    # (meal key, ingredient index) -> multiplier on the drafted reference amount
    multipliers: dict[tuple[Key, int], Decimal] = field(default_factory=dict)
    ratios: dict[str, Decimal] = field(default_factory=dict)  # member -> r_m
    problems: list[tuple[str, str]] = field(default_factory=list)  # (code, message)
    stock_short: dict[int, Decimal] = field(default_factory=dict)  # product_id -> amount missing


def _d(value: float, places: str = "0.001") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def solve_portions(meals: dict[Key, DraftMeal], ctx) -> PortionSolution:  # ctx: PlanContext
    by_id = {a.product.id: a for a in ctx.available}
    members = list(ctx.members)
    ref = members[0].daily.energy_kcal
    ratio = {m.profile.name: float(m.daily.energy_kcal / ref) for m in members}

    pairs: list[tuple[Key, int]] = []
    base, kcal, protein, product = [], [], [], []
    for key, meal in sorted(meals.items()):
        for idx, ing in enumerate(meal.ingredients):
            pairs.append((key, idx))
            base.append(float(ing.amount))
            item = by_id[ing.product_id]
            kcal.append(float(item.kcal))
            protein.append(float(item.protein))
            product.append(ing.product_id)
    n = len(pairs)

    def eaters(key: Key) -> list[str]:
        return [m.profile.name for m in members if m.profile.name not in meals[key].skipped_by]

    # Rows: (coefficients over x, lower, upper, slack spec or None)
    rows: list[tuple[dict[int, float], float, float, tuple | None]] = []
    for m in members:
        name = m.profile.name
        total_share = 0.0
        for day in ctx.schedule.days:
            js = [j for j, (key, _) in enumerate(pairs) if key[0] == day and name in eaters(key)]
            share = sum(float(ctx.schedule.shares[key[1]]) for key in {pairs[j][0] for j in js})
            total_share += share
            if not js:
                continue
            target = float(m.daily.energy_kcal * ctx.energy_scale) * share
            coeffs = {j: ratio[name] * base[j] * kcal[j] for j in js}
            spec = ("energy", target, f"{name}|{day.isoformat()}")
            rows.append((coeffs, target, target, spec))
        needed = float(m.daily.protein_g * ctx.protein_min_ratio) * total_share
        js = [j for j, (key, _) in enumerate(pairs) if name in eaters(key)]
        coeffs = {j: ratio[name] * base[j] * protein[j] for j in js}
        rows.append((coeffs, needed, np.inf, ("protein", needed, name)))
    for pid in sorted(set(product)):
        avail = float(by_id[pid].available * (1 + ctx.stock_tolerance))
        coeffs = {
            j: base[j] * sum(ratio[e] for e in eaters(pairs[j][0]))
            for j in range(n)
            if product[j] == pid
        }
        rows.append((coeffs, -np.inf, avail, ("stock", max(avail, 1.0), pid)))

    lo, hi = float(ctx.min_scale), float(ctx.max_scale)

    def build(elastic: bool):
        slacks: list[tuple[str, float, object, int]] = []  # kind, scale, ref, sign
        a_rows, lb, ub = [], [], []
        for coeffs, low, high, spec in rows:
            row = dict(coeffs)
            if elastic and spec is not None:
                kind, scale, ref_ = spec
                if kind == "energy":  # equality: slack in both directions
                    row[("s", len(slacks))] = 1.0
                    slacks.append((kind + "_low", scale, ref_, 1))
                    row[("s", len(slacks))] = -1.0
                    slacks.append((kind + "_high", scale, ref_, -1))
                elif kind == "protein":
                    row[("s", len(slacks))] = 1.0
                    slacks.append((kind, scale, ref_, 1))
                else:  # stock
                    row[("s", len(slacks))] = -1.0
                    slacks.append((kind, scale, ref_, -1))
            a_rows.append(row)
            lb.append(low)
            ub.append(high)
        # deviation: x_j - u_j <= 1 ; -x_j - u_j <= -1
        for j in range(n):
            a_rows.append({j: 1.0, ("u", j): -1.0})
            lb.append(-np.inf)
            ub.append(1.0)
            a_rows.append({j: -1.0, ("u", j): -1.0})
            lb.append(-np.inf)
            ub.append(-1.0)
        nvars = 2 * n + len(slacks)

        def col(key) -> int:
            if isinstance(key, int):
                return key
            kind, i = key
            return n + i if kind == "u" else 2 * n + i

        A = np.zeros((len(a_rows), nvars))
        for r, row in enumerate(a_rows):
            for key, value in row.items():
                A[r, col(key)] = value
        objective = np.zeros(nvars)
        if elastic:
            for i, (_, scale, _, _) in enumerate(slacks):
                objective[2 * n + i] = 1.0 / scale
            objective[n : 2 * n] = 1e-4  # still prefer the drafted amounts
        else:
            objective[n : 2 * n] = 1.0
        bounds = [(lo, hi)] * n + [(0, None)] * (n + len(slacks))
        lb_a, ub_a = np.array(lb), np.array(ub)
        # linprog takes A_ub x <= b_ub and A_eq x = b_eq: split the two-sided rows.
        eq = np.isclose(lb_a, ub_a)
        upper = ~eq & np.isfinite(ub_a)
        lower = ~eq & np.isfinite(lb_a)
        A_ub = np.vstack([A[upper], -A[lower]])
        b_ub = np.concatenate([ub_a[upper], -lb_a[lower]])
        res = linprog(
            objective,
            A_ub=A_ub if len(b_ub) else None,
            b_ub=b_ub if len(b_ub) else None,
            A_eq=A[eq] if eq.any() else None,
            b_eq=lb_a[eq] if eq.any() else None,
            bounds=bounds,
            method="highs",
        )
        return res, slacks

    solution = PortionSolution(ok=False, ratios={k: _d(v) for k, v in ratio.items()})
    res, _ = build(elastic=False)
    if res.status == 0:
        solution.ok = True
        solution.multipliers = {pairs[j]: _d(res.x[j]) for j in range(n)}
        return solution

    res, slacks = build(elastic=True)
    if res.status != 0:
        solution.problems.append(("portions_unsolvable", "portions could not be computed"))
        return solution
    solution.multipliers = {pairs[j]: _d(res.x[j]) for j in range(n)}
    names = {a.product.id: (a.product.name, a.basis, a.available) for a in ctx.available}
    for i, (kind, _scale, ref_, _sign) in enumerate(slacks):
        value = float(res.x[2 * n + i])
        if value <= 0.5:
            continue
        if kind.startswith("energy"):
            name, day = str(ref_).split("|")
            weekday = date.fromisoformat(day).strftime("%A")
            if kind == "energy_low":
                msg = (
                    f"{name}'s meals on {weekday} are {round(value)} kcal short of the target even "
                    f"at {hi:g}x the drafted amounts: add more or more energy-dense ingredients"
                )
            else:
                msg = (
                    f"{name}'s meals on {weekday} are {round(value)} kcal over the target even at "
                    f"{lo:g}x the drafted amounts: use smaller or lighter dishes"
                )
            solution.problems.append(("portions_unrealistic", msg))
        elif kind == "protein":
            solution.problems.append(
                (
                    "protein_low",
                    f"{ref_} would get {round(value)} g too little protein this week: use more "
                    "protein-rich products",
                )
            )
        else:
            pname, basis, available = names[ref_]
            solution.stock_short[int(ref_)] = _d(value, "0.1")
            solution.problems.append(
                (
                    "stock_exceeded",
                    f"{pname}: these meals need at least {round(value)} {basis} more than the "
                    f"{available:.0f} {basis} available: use less of it or another product",
                )
            )
    return solution
