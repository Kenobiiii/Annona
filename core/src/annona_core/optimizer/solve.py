# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mixed-integer model of the weekly shop, solved with ``scipy.optimize.milp`` (HiGHS).

Variables, per candidate product i:
    x_i  integer  packs to buy                     (0 .. max_packs_per_product)
    c_i  real     amount consumed this period, in the product's nutrition basis (g or ml)

Constraints:
    c_i <= pantry_i + pack_i * x_i                          (eat only what you have or buy)
    energy_min <= sum kcal_i c_i <= energy_max
    sum protein_i c_i >= protein_min
    fat_min <= sum fat_i c_i <= fat_max
    sum_{fruit/veg} c_i >= fruit_veg_min                    (WHO, potatoes excluded)
    kcal_i c_i <= share * sum_j kcal_j c_j    for every i   (variety)
    sum price_i x_i <= budget
Objective: minimise sum price_i x_i (pantry food is free).

If that is infeasible, the explanation is computed in two exact steps, without the budget:
1. an *elastic* model adds a non-negative slack to every nutrition/variety constraint and
   minimises the weighted, normalised slack: what cannot be met even with unlimited money;
2. keeping that best achievable violation, minimise the cost. If it exceeds the budget, the
   difference is exactly the money needed.
Slacks above half a unit become :class:`Shortfall`s ("protein short by 85 g"). Money in the
result is recomputed with integers from the integral pack counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from .models import Line, Problem, Result, Shortfall, Totals
from .prepare import Candidate, prepare

INF = np.inf
NUTRITION_WEIGHT = 1.0  # per unit of normalised slack (slack / target)
VARIETY_WEIGHT = 0.5

_UNITS = {
    "budget": "cents",
    "energy_min": "kcal",
    "energy_max": "kcal",
    "protein_min": "g",
    "fat_min": "g",
    "fat_max": "g",
    "fruit_veg_min": "g",
    "variety": "kcal",
    "salt_max": "g",
    "saturated_fat_max": "kcal",
}
_DETAILS = {
    "budget": "the cheapest plan that meets every target needs this much more money",
    "energy_min": "calories below the minimum",
    "energy_max": "calories above the maximum",
    "protein_min": "protein below the target",
    "fat_min": "fat below the minimum (20 % of energy)",
    "fat_max": "fat above the maximum (35 % of energy)",
    "fruit_veg_min": "fruit and vegetables below 400 g per person and day (WHO)",
    "variety": "one product would exceed the share of calories allowed per product",
    "salt_max": "salt above 5 g per person and day (WHO; optional health limit)",
    "saturated_fat_max": "saturated fat above 10 % of energy (WHO; optional health limit)",
}


@dataclass(frozen=True)
class _Slack:
    name: str
    scale: float  # the target the slack is normalised by
    weight: float
    index: int | None  # candidate index for per-product constraints


class _Model:
    """Sparse rows over columns [x_0..x_{n-1}, c_0..c_{n-1}, slacks...]."""

    def __init__(
        self,
        cands: list[Candidate],
        problem: Problem,
        *,
        elastic: bool,
        with_budget: bool,
        max_violation: float | None = None,
    ) -> None:
        self.cands, self.problem = cands, problem
        self.elastic, self.with_budget, self.max_violation = elastic, with_budget, max_violation
        self.n = len(cands)
        self.rows: list[dict[int, float]] = []
        self.lb: list[float] = []
        self.ub: list[float] = []
        self.slacks: list[_Slack] = []
        self._build()

    def _slack_col(self, j: int) -> int:
        return 2 * self.n + j

    def _row(
        self, coeffs: dict[int, float], lb: float, ub: float, slack: tuple | None = None
    ) -> None:
        """``slack`` = (name, scale, weight, sign, index); only used in elastic models."""
        if slack is not None and self.elastic:
            name, scale, weight, sign, index = slack
            coeffs = {**coeffs, self._slack_col(len(self.slacks)): sign}
            self.slacks.append(_Slack(name, max(scale, 1.0), weight, index))
        self.rows.append(coeffs)
        self.lb.append(lb)
        self.ub.append(ub)

    def _build(self) -> None:
        n, t, s = self.n, self.problem.targets, self.problem.settings
        cands = self.cands
        k = [float(x.kcal) for x in cands]
        p = [float(x.protein) for x in cands]
        f = [float(x.fat) for x in cands]
        con = [n + i for i in range(n)]  # consumption columns

        for i, cand in enumerate(cands):  # availability (always hard)
            self._row({con[i]: 1.0, i: -float(cand.pack_basis)}, -INF, float(cand.stock_basis))

        e_min, e_max = float(t.energy_kcal_min), float(t.energy_kcal_max)
        kcal = {con[i]: k[i] for i in range(n)}
        self._row(kcal, e_min, INF, ("energy_min", e_min, NUTRITION_WEIGHT, 1.0, None))
        self._row(kcal, -INF, e_max, ("energy_max", e_max, NUTRITION_WEIGHT, -1.0, None))
        p_min = float(t.protein_g)
        protein = {con[i]: p[i] for i in range(n)}
        self._row(protein, p_min, INF, ("protein_min", p_min, NUTRITION_WEIGHT, 1.0, None))
        f_min, f_max = float(t.fat_g_min), float(t.fat_g_max)
        fat = {con[i]: f[i] for i in range(n)}
        self._row(fat, f_min, INF, ("fat_min", f_min, NUTRITION_WEIGHT, 1.0, None))
        self._row(fat, -INF, f_max, ("fat_max", f_max, NUTRITION_WEIGHT, -1.0, None))
        people = max(len(self.problem.members), 1)
        fv_min = float(s.fruit_veg_g_per_person_day * people * s.days)
        fruit_veg = {con[i]: 1.0 for i in range(n) if cands[i].fruit_veg}
        self._row(fruit_veg, fv_min, INF, ("fruit_veg_min", fv_min, NUTRITION_WEIGHT, 1.0, None))

        if s.health_limits:  # optional, WHO: salt < 5 g/person/day, saturated fat < 10 % kcal
            salt_max = float(s.salt_g_per_person_day * people * s.days)
            salt = {con[i]: float(cands[i].salt or 0) for i in range(n)}
            self._row(salt, -INF, salt_max, ("salt_max", salt_max, NUTRITION_WEIGHT, -1.0, None))
            sf_share = float(s.saturated_fat_energy_share)
            sat_fat = {
                con[i]: 9.0 * float(cands[i].saturated_fat or 0) - sf_share * k[i] for i in range(n)
            }
            self._row(
                sat_fat, -INF, 0.0, ("saturated_fat_max", e_max, NUTRITION_WEIGHT, -1.0, None)
            )

        share = float(s.max_kcal_share_per_product)
        for i in range(n):
            coeffs = {con[j]: -share * k[j] for j in range(n)}
            coeffs[con[i]] += k[i]
            self._row(coeffs, -INF, 0.0, ("variety", e_max, VARIETY_WEIGHT, -1.0, i))

        if self.with_budget:
            prices = {i: float(cands[i].price_cents) for i in range(n)}
            self._row(prices, -INF, float(self.problem.budget_cents))
        if self.elastic and self.max_violation is not None:
            self._row(self.violation_coeffs(), -INF, self.max_violation)

    def violation_coeffs(self) -> dict[int, float]:
        return {self._slack_col(j): s.weight / s.scale for j, s in enumerate(self.slacks)}

    def solve(self, minimise: str):
        """``minimise`` is "cost" or "violation" (weighted, normalised slacks)."""
        n, s = self.n, self.problem.settings
        nvars = 2 * n + len(self.slacks)
        A = np.zeros((len(self.rows), nvars))
        for r, coeffs in enumerate(self.rows):
            for col, value in coeffs.items():
                A[r, col] = value
        objective = np.zeros(nvars)
        if minimise == "cost":
            objective[:n] = [float(x.price_cents) for x in self.cands]
        else:
            for col, value in self.violation_coeffs().items():
                objective[col] = value
        upper = np.full(nvars, INF)
        upper[:n] = float(s.max_packs_per_product)
        integrality = np.zeros(nvars)
        integrality[:n] = 1
        return milp(
            objective,
            integrality=integrality,
            bounds=Bounds(np.zeros(nvars), upper),
            constraints=LinearConstraint(A, np.array(self.lb), np.array(self.ub)),
            options={"time_limit": s.time_limit_s, "disp": False, "mip_rel_gap": 1e-9},
        )


def _dec(value: float, places: str = "0.1") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _lines_and_totals(cands: list[Candidate], x: np.ndarray, problem: Problem):
    n = len(cands)
    lines: list[Line] = []
    sums = dict.fromkeys(("kcal", "p", "f", "c", "fv", "salt", "sf"), Decimal(0))
    for i, cand in enumerate(cands):
        packs = int(round(x[i]))
        available = cand.stock_basis + cand.pack_basis * packs
        used = min(max(_dec(x[n + i]), Decimal(0)), available)
        if packs == 0 and used == 0:
            continue
        kcal = used * cand.kcal
        sums["kcal"] += kcal
        sums["p"] += used * cand.protein
        sums["f"] += used * cand.fat
        sums["c"] += used * cand.carbs
        if cand.fruit_veg:
            sums["fv"] += used
        sums["salt"] += used * (cand.salt or 0)
        sums["sf"] += used * (cand.saturated_fat or 0)
        product = cand.product
        lines.append(
            Line(
                product_id=product.id or 0,
                name=product.name,
                packs_to_buy=packs,
                cost_cents=packs * cand.price_cents,
                pack_amount=product.package_amount or Decimal(0),
                pack_unit=str(product.package_unit),
                used_from_pantry=min(used, cand.stock_basis),
                used_total=used,
                available=available,
                basis_unit=str(cand.basis),
                kcal=kcal.quantize(Decimal(1)),
                estimated=cand.estimated,
                not_for=cand.not_for,
            )
        )

    def q(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    period = Totals(
        energy_kcal=q(sums["kcal"]),
        protein_g=q(sums["p"]),
        fat_g=q(sums["f"]),
        carbohydrates_g=q(sums["c"]),
        fruit_veg_g=q(sums["fv"]),
        salt_g=q(sums["salt"]),
        saturated_fat_g=q(sums["sf"]),
    )
    days = Decimal(problem.settings.days)
    daily = Totals(
        **{key: q(value / days) for key, value in period.model_dump().items() if value is not None}
    )
    return lines, period, daily


def optimise(problem: Problem) -> Result:
    """The cheapest purchase meeting every target, or an explanation of what cannot be met."""
    cands, warnings = prepare(problem)
    base = Result(status="no_candidates", currency=problem.currency, warnings=warnings)
    if not cands:
        return base

    res = _Model(cands, problem, elastic=False, with_budget=True).solve("cost")
    if res.status == 0 and res.x is not None:
        lines, period, daily = _lines_and_totals(cands, res.x, problem)
        return base.model_copy(
            update={
                "status": "optimal",
                "lines": lines,
                "total_cost_cents": sum(line.cost_cents for line in lines),
                "period_totals": period,
                "daily_average": daily,
            }
        )
    if res.status != 2:  # not "infeasible": time limit or solver failure
        return base.model_copy(update={"status": "solver_error"})

    # Step 1: least violation of nutrition/variety targets with unlimited money.
    step1 = _Model(cands, problem, elastic=True, with_budget=False)
    res1 = step1.solve("violation")
    if res1.status != 0 or res1.x is None:
        return base.model_copy(update={"status": "solver_error"})
    # Step 2: the cheapest plan keeping that violation (tiny tolerance for float noise).
    limit = float(res1.fun) * (1 + 1e-7) + 1e-9
    step2 = _Model(cands, problem, elastic=True, with_budget=False, max_violation=limit)
    res2 = step2.solve("cost")
    model, x = (step2, res2.x) if res2.status == 0 and res2.x is not None else (step1, res1.x)

    shortfalls = []
    for j, slack in enumerate(model.slacks):
        value = float(x[model._slack_col(j)])
        if value <= 0.5:  # below half a kcal or gram: numerical noise
            continue
        detail = _DETAILS[slack.name]
        if slack.index is not None:
            detail = f"{cands[slack.index].product.name}: {detail}"
        shortfalls.append(
            Shortfall(
                constraint=slack.name, amount=_dec(value), unit=_UNITS[slack.name], detail=detail
            )
        )
    lines, period, daily = _lines_and_totals(cands, x, problem)
    cost = sum(line.cost_cents for line in lines)
    if cost > problem.budget_cents:
        shortfalls.append(
            Shortfall(
                constraint="budget",
                amount=Decimal(cost - problem.budget_cents),
                unit="cents",
                detail=_DETAILS["budget"],
            )
        )
    return base.model_copy(
        update={
            "status": "infeasible",
            "shortfalls": shortfalls,
            "lines": lines,
            "total_cost_cents": cost,
            "period_totals": period,
            "daily_average": daily,
        }
    )
