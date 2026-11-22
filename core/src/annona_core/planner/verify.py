# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic portions and verification of an LLM plan draft. No LLM here.

1. Structure: every scheduled (day, slot) has exactly one meal; no extra meals.
2. Ingredients exist; appliances exist in the kitchen (and the summary does not mention an
   oven when there is none); no member eats a product that is not for them.
3-4. Portions: a small linear programme (``portions.py``) adjusts every ingredient amount so
   each member's daily energy matches their target, weekly protein is reached and no product is
   used beyond what is available, staying as close as possible to the drafted amounts. When
   that is impossible, the precise reasons become issues for the repair request.
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
from .portions import solve_portions
from .schedule import MealSchedule

SERVING_COUNT_MIN_G = Decimal(50)  # a meal counts as a meat/fish/eggs serving from 50 g
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
    max_scale: Decimal = Decimal("3.0")
    protein_min_ratio: Decimal = Decimal("0.90")
    # Energy actually bought / energy target (the optimiser may land anywhere within +/-5 %);
    # portions are scaled to what was bought so the menu never needs more food than exists.
    energy_scale: Decimal = Decimal(1)
    stock_tolerance: Decimal = Decimal("0.01")
    # Replacing one meal: the weekly servings are a property of the whole week, not of one meal.
    check_servings: bool = True
    replacing: str | None = None  # the title of the meal being replaced
    swap_request: str | None = None  # what the person asked for, in their words


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
    base_amounts: dict[int, Decimal]  # adjusted amounts for one reference serving
    portions: tuple[Portion, ...]  # per member: reference serving x the member's ratio


@dataclass
class Verification:
    issues: list[Issue] = field(default_factory=list)
    meals: list[FinalMeal] = field(default_factory=list)
    usage: dict[int, Decimal] = field(default_factory=dict)  # product_id -> total amount
    kcal_by_member_day: dict[tuple[str, date], Decimal] = field(default_factory=dict)
    protein_by_member: dict[str, Decimal] = field(default_factory=dict)
    ingredient_scales: list[Decimal] = field(default_factory=list)  # adjusted / drafted
    stock_short: dict[int, Decimal] = field(default_factory=dict)  # product_id -> missing

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

    # 3-4. portions (linear programme: energy, protein, stock) - see portions.py
    solution = solve_portions(seen, ctx)
    issues.extend(Issue(code=code, message=message) for code, message in solution.problems)
    result.stock_short = dict(solution.stock_short)
    for key, meal in sorted(seen.items()):
        base = {}
        for idx, ing in enumerate(meal.ingredients):
            multiplier = solution.multipliers.get((key, idx), Decimal(1))
            result.ingredient_scales.append(multiplier)
            amount = ing.amount * multiplier
            base[ing.product_id] = base.get(ing.product_id, Decimal(0)) + amount
        portions = []
        for member in ctx.members:
            name = member.profile.name
            if name in meal.skipped_by:
                continue
            r = solution.ratios[name]
            amounts = {pid: amount * r for pid, amount in base.items()}
            for pid, amount in amounts.items():
                result.usage[pid] = result.usage.get(pid, Decimal(0)) + amount
                kcal = amount * by_id[pid].kcal
                day_key = (name, key[0])
                result.kcal_by_member_day[day_key] = (
                    result.kcal_by_member_day.get(day_key, Decimal(0)) + kcal
                )
                result.protein_by_member[name] = (
                    result.protein_by_member.get(name, Decimal(0)) + amount * by_id[pid].protein
                )
            portions.append(
                Portion(member=name, scale=_q2(r), amounts={k: _q(v) for k, v in amounts.items()})
            )
        result.meals.append(
            FinalMeal(
                day=key[0],
                draft=meal,
                base_amounts={k: _q(v) for k, v in base.items()},
                portions=tuple(portions),
            )
        )
    # 5. weekly servings wanted by each member (a meal counts with >= 50 g of the group)
    for member in ctx.members if ctx.check_servings else ():
        name = member.profile.name
        for group in sorted(member.profile.weekly_servings):
            wanted = member.profile.servings_for_days(group, ctx.schedule.day_equivalents)
            got = 0
            present = 0  # meals that contain the group at all
            for final in result.meals:
                for portion in final.portions:
                    if portion.member != name:
                        continue
                    grams = sum(
                        (
                            amount
                            for pid, amount in portion.amounts.items()
                            if str(by_id[pid].product.category) == group
                        ),
                        Decimal(0),
                    )
                    got += grams >= SERVING_COUNT_MIN_G
                    present += grams > 0
            if got < wanted:
                if present > got:
                    advice = (
                        f"{group} appears in {present} meals but only {got} have at least "
                        f"{SERVING_COUNT_MIN_G} g per serving, and the week's total is limited: "
                        f"use it in {wanted} meals and leave it out of the others"
                    )
                else:
                    advice = f"add {group} to more of {name}'s meals"
                issues.append(
                    Issue(
                        code="servings_missing",
                        message=f"{name} wants {group} at least {wanted} times in this plan but "
                        f"the plan has it {got} times: {advice}",
                    )
                )
    result.kcal_by_member_day = {k: _q(v) for k, v in result.kcal_by_member_day.items()}
    result.protein_by_member = {k: _q(v) for k, v in result.protein_by_member.items()}
    return result


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _label(key: tuple[date, str]) -> str:
    day, slot = key
    return f"{day:%A %d} {slot}"


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
