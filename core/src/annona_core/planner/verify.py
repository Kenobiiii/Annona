# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic portions and verification of an LLM plan draft. No LLM here.

1. Structure: every scheduled (day, slot) has exactly one meal; no extra meals.
2. Ingredients exist; appliances exist in the kitchen (and the summary does not mention an
   oven when there is none); no member eats a product that is not for them.
3. Portions: for each member and day, all of that day's ingredient amounts are multiplied by
   one factor so the day's energy equals the member's target x the day's planned share x
   ``energy_scale`` (the energy actually bought relative to the target). A
   factor outside [min_scale, max_scale] means the draft's portions were unrealistic.
4. Totals: weekly protein per member reaches ``protein_min_ratio`` of the target, and the
   scaled usage of every product stays within what is available (purchase + pantry).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from annona_core.domain import Equipment, HobType, Product, UserProfile
from annona_core.nutrition import DailyTargets

from .draft import Appliance, DraftMeal, PlanDraft
from .schedule import MealSchedule

_OVEN_WORDS = re.compile(r"\b(horno|hornear|hornea|gratinar|oven|bake|baked|roast)\b", re.I)


class Available(BaseModel):
    """A product the plan may use this week."""

    model_config = ConfigDict(frozen=True)

    product: Product
    basis: str  # "g" or "ml"
    available: Decimal  # purchase + pantry, in basis units, whole household
    intended: Decimal  # what the optimiser planned to eat this week
    kcal: Decimal  # per basis unit
    protein: Decimal  # per basis unit
    not_for: tuple[str, ...] = ()  # member names who must not eat it


class Member(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: UserProfile
    daily: DailyTargets


class PlanContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    schedule: MealSchedule
    members: tuple[Member, ...]
    available: tuple[Available, ...]
    equipment: Equipment | None
    language: str = "es"
    min_scale: Decimal = Decimal("0.5")
    max_scale: Decimal = Decimal("2.0")
    protein_min_ratio: Decimal = Decimal("0.90")
    # Energy actually bought / energy target (the optimiser may land anywhere within +/-5 %);
    # portions are scaled to what was bought so the menu never needs more food than exists.
    energy_scale: Decimal = Decimal(1)
    stock_tolerance: Decimal = Decimal("0.01")


class Issue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str  # written for the model too: it is sent back in the repair request


class Portion(BaseModel):
    model_config = ConfigDict(frozen=True)

    member: str
    scale: Decimal
    amounts: dict[int, Decimal]  # product_id -> amount for this member


class FinalMeal(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: date
    draft: DraftMeal
    portions: tuple[Portion, ...]


@dataclass
class Verification:
    issues: list[Issue] = field(default_factory=list)
    meals: list[FinalMeal] = field(default_factory=list)
    usage: dict[int, Decimal] = field(default_factory=dict)  # product_id -> total amount
    kcal_by_member_day: dict[tuple[str, date], Decimal] = field(default_factory=dict)
    protein_by_member: dict[str, Decimal] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues


def available_appliances(equipment: Equipment | None) -> set[Appliance]:
    if equipment is None:
        return {Appliance.NONE, Appliance.HOB}
    tools = {Appliance.NONE}
    if equipment.hob_type != HobType.NONE and equipment.burners > 0:
        tools.add(Appliance.HOB)
    if equipment.oven:
        tools.add(Appliance.OVEN)
    if equipment.microwave:
        tools.add(Appliance.MICROWAVE)
    if equipment.air_fryer:
        tools.add(Appliance.AIR_FRYER)
    return tools


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def verify(draft: PlanDraft, ctx: PlanContext) -> Verification:
    result = Verification()
    issues = result.issues
    by_id = {a.product.id: a for a in ctx.available}
    names = {m.profile.name for m in ctx.members}
    tools = available_appliances(ctx.equipment)
    week = ctx.schedule.week_start

    # 1. structure
    expected = {(s.day, s.slot) for s in ctx.schedule.slots}
    seen: dict[tuple[date, str], DraftMeal] = {}
    for meal in draft.meals:
        key = (week + timedelta(days=meal.weekday), meal.slot)
        if key not in expected:
            issues.append(
                Issue(code="unexpected_meal", message=f"{_label(key)} is not planned: remove it")
            )
        elif key in seen:
            issues.append(Issue(code="duplicate_meal", message=f"{_label(key)} appears twice"))
        else:
            seen[key] = meal
    for key in sorted(expected - set(seen)):
        issues.append(Issue(code="missing_meal", message=f"{_label(key)} is missing"))

    # 2. ingredients, appliances, people
    for key, meal in sorted(seen.items()):
        where = f"{_label(key)} '{meal.title}'"
        for tool in meal.appliances:
            if tool not in tools:
                issues.append(
                    Issue(code="appliance", message=f"{where} uses {tool}, not in the kitchen")
                )
        if Appliance.OVEN not in tools and _OVEN_WORDS.search(meal.summary + " " + meal.title):
            issues.append(
                Issue(code="appliance", message=f"{where} mentions an oven; there is none")
            )
        for name in meal.skipped_by:
            if name not in names:
                issues.append(
                    Issue(code="unknown_member", message=f"{where}: unknown member {name}")
                )
        eaters = [m for m in ctx.members if m.profile.name not in meal.skipped_by]
        if not eaters:
            issues.append(Issue(code="nobody_eats", message=f"{where} is skipped by everyone"))
        for ing in meal.ingredients:
            item = by_id.get(ing.product_id)
            if item is None:
                issues.append(
                    Issue(
                        code="unknown_product",
                        message=f"{where} uses product {ing.product_id}, which is not available",
                    )
                )
                continue
            for m in eaters:
                if m.profile.name in item.not_for:
                    issues.append(
                        Issue(
                            code="not_allowed",
                            message=f"{where}: {m.profile.name} must not eat {item.product.name}; "
                            f"list {m.profile.name} in skipped_by or change the ingredient",
                        )
                    )
    if any(i.code in ("unknown_product", "missing_meal") for i in issues):
        return result  # portions are meaningless without valid ingredients and slots

    # 3. portions per member and day
    for member in ctx.members:
        name = member.profile.name
        protein = Decimal(0)
        for day in ctx.schedule.days:
            meals = [
                (key, meal)
                for key, meal in sorted(seen.items())
                if key[0] == day and name not in meal.skipped_by
            ]
            drafted = sum(
                (
                    ing.amount * by_id[ing.product_id].kcal
                    for _, meal in meals
                    for ing in meal.ingredients
                ),
                Decimal(0),
            )
            share = sum((ctx.schedule.shares[k[1]] for k, _ in meals), Decimal(0))
            target = member.daily.energy_kcal * share * ctx.energy_scale
            if drafted <= 0:
                if target > 0:
                    issues.append(
                        Issue(code="empty_day", message=f"{name} has no food on {day:%a %d}")
                    )
                continue
            scale = target / drafted
            if not ctx.min_scale <= scale <= ctx.max_scale:
                direction = "too small" if scale > 1 else "too large"
                issues.append(
                    Issue(
                        code="portions_unrealistic",
                        message=f"{name}'s portions on {day:%A} are {direction}: the drafted meals "
                        f"give {_q(drafted)} kcal for a target of {_q(target)} kcal",
                    )
                )
            result.kcal_by_member_day[(name, day)] = _q(drafted * scale)
            for key, meal in meals:
                amounts = {}
                for ing in meal.ingredients:
                    amount = ing.amount * scale
                    amounts[ing.product_id] = amounts.get(ing.product_id, Decimal(0)) + amount
                    result.usage[ing.product_id] = (
                        result.usage.get(ing.product_id, Decimal(0)) + amount
                    )
                    protein += amount * by_id[ing.product_id].protein
                _add_portion(
                    result,
                    key,
                    meal,
                    Portion(
                        member=name,
                        scale=_q2(scale),
                        amounts={k: _q(v) for k, v in amounts.items()},
                    ),
                )
        result.protein_by_member[name] = _q(protein)
        needed = member.daily.protein_g * ctx.schedule.day_equivalents
        if protein < needed * ctx.protein_min_ratio:
            issues.append(
                Issue(
                    code="protein_low",
                    message=f"{name} gets {_q(protein)} g protein this week; at least "
                    f"{_q(needed * ctx.protein_min_ratio)} g is needed: "
                    "use more protein-rich products",
                )
            )

    # 4. stock
    for pid, used in sorted(result.usage.items()):
        item = by_id[pid]
        if used > item.available * (1 + ctx.stock_tolerance):
            issues.append(
                Issue(
                    code="stock_exceeded",
                    message=f"{item.product.name}: the plan uses {_q(used)} {item.basis} but only "
                    f"{_q(item.available)} {item.basis} are available",
                )
            )
    return result


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _label(key: tuple[date, str]) -> str:
    day, slot = key
    return f"{day:%A %d} {slot}"


def _add_portion(result: Verification, key, meal: DraftMeal, portion: Portion) -> None:
    for i, final in enumerate(result.meals):
        if (final.day, final.draft.slot) == key:
            result.meals[i] = final.model_copy(update={"portions": (*final.portions, portion)})
            return
    result.meals.append(FinalMeal(day=key[0], draft=meal, portions=(portion,)))


__all__ = [
    "Available",
    "FinalMeal",
    "Issue",
    "Member",
    "PlanContext",
    "Portion",
    "Verification",
    "available_appliances",
    "verify",
]
