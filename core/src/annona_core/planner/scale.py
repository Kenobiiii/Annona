# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bring a drafted plan to the right order of magnitude before it is verified. No LLM here.

Language models draw "typical home portions" (about 2,000 kcal a day), not the energy a particular
person needs, and they ignore how much of each product was bought. Asking the model to do that
arithmetic is unreliable (CLAUDE.md: never trust LLM arithmetic), so the code rescales the draft:
the model chooses the dishes and their proportions, the code decides how much of each.

The rescaling is a biproportional fit (iterative proportional fitting): it alternately scales
every product so the week's total matches what the shopping optimiser decided to use, and every
day so the first member's energy matches their target. It keeps the draft's structure (each
amount is only ever multiplied) and converges to the amounts closest to the draft that satisfy
both margins. The linear programme in ``portions.py`` then fine-tunes energy, protein and stock
exactly, within a narrow range of these amounts.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from .draft import DraftIngredient, PlanDraft
from .verify import PlanContext

ROUNDS = 40
PRODUCT_STEP = (0.25, 4.0)  # one product pass never changes an amount by more than this factor
DAY_STEP = (0.4, 6.0)  # likewise for a day pass
FINAL_DAY_STEP = (0.05, 20.0)  # the closing day pass: energy is the hard requirement
_TENTH = Decimal("0.1")


def scale_to_energy(draft: PlanDraft, ctx: PlanContext) -> PlanDraft:
    """Rescale the draft so each product's week total and each day's energy are on target.

    Product targets are the optimiser's planned use (``Available.intended``); the day target is the
    first member's energy for the meals they eat (as in the portions programme the other members
    are ratios of them). Products missing from the draft stay missing: the verifier reports what
    that costs.
    """
    members = list(ctx.members)
    ref_name = members[0].profile.name
    ref_energy = float(members[0].daily.energy_kcal)
    ratios = {m.profile.name: float(m.daily.energy_kcal) / ref_energy for m in members}
    info = {a.product.id: a for a in ctx.available}
    shares = {slot: float(share) for slot, share in ctx.schedule.shares.items()}
    energy_target = ref_energy * float(ctx.energy_scale)

    # one entry per (meal, ingredient): amount, kcal/unit, who eats (sum of ratios), day, ref eats
    entries = []
    for mi, meal in enumerate(draft.meals):
        day = ctx.schedule.week_start + timedelta(days=meal.weekday)
        if day not in ctx.schedule.days:
            continue  # not planned: the verifier rejects it, nothing to scale
        weight = sum(r for name, r in ratios.items() if name not in meal.skipped_by)
        ref_eats = ref_name not in meal.skipped_by
        for ii, ing in enumerate(meal.ingredients):
            item = info.get(ing.product_id)
            entries.append(
                {
                    "mi": mi,
                    "ii": ii,
                    "pid": ing.product_id,
                    "x": float(ing.amount),
                    "kcal": float(item.kcal) if item else 0.0,
                    "w": weight,
                    "day": meal.weekday,
                    "ref": ref_eats,
                    "slot": meal.slot,
                }
            )

    day_target = {}
    for weekday in {e["day"] for e in entries if e["day"] is not None}:
        seen = {(e["mi"]) for e in entries if e["day"] == weekday and e["ref"]}
        share = sum(shares[draft.meals[mi].slot] for mi in seen)
        if share > 0:
            day_target[weekday] = energy_target * share
    product_target = {}
    for pid, item in info.items():
        planned = float(item.intended) if item.intended > 0 else float(item.available)
        product_target[pid] = min(planned, float(item.available))

    def clamp(value: float, bounds: tuple[float, float]) -> float:
        return min(bounds[1], max(bounds[0], value))

    def day_pass(bounds: tuple[float, float]) -> None:
        energy: dict[int, float] = {}
        for e in entries:
            if e["ref"] and e["day"] in day_target:
                energy[e["day"]] = energy.get(e["day"], 0.0) + e["x"] * e["kcal"]
        for e in entries:
            have = energy.get(e["day"], 0.0)
            if have > 0 and e["day"] in day_target:
                e["x"] *= clamp(day_target[e["day"]] / have, bounds)

    for _ in range(ROUNDS):
        use: dict[int, float] = {}
        for e in entries:
            use[e["pid"]] = use.get(e["pid"], 0.0) + e["x"] * e["w"]
        for e in entries:
            used = use.get(e["pid"], 0.0)
            if used > 0 and e["pid"] in product_target:
                e["x"] *= clamp(product_target[e["pid"]] / used, PRODUCT_STEP)
        day_pass(DAY_STEP)
    day_pass(FINAL_DAY_STEP)  # energy is a hard requirement, stock a guide: always end on energy

    amounts = {(e["mi"], e["ii"]): e["x"] for e in entries}
    meals = []
    for mi, meal in enumerate(draft.meals):
        if (mi, 0) not in amounts:
            meals.append(meal)  # a meal on a day that is not planned stays as it is
            continue
        ingredients = [
            DraftIngredient.model_construct(
                product_id=ing.product_id,
                amount=Decimal(str(amounts[(mi, ii)])).quantize(_TENTH, rounding=ROUND_HALF_UP),
            )
            for ii, ing in enumerate(meal.ingredients)
        ]
        meals.append(meal.model_copy(update={"ingredients": ingredients}))
    return PlanDraft.model_construct(meals=meals)
