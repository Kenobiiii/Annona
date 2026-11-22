# SPDX-License-Identifier: AGPL-3.0-or-later
"""Planner tests with FakeLLM. Products and nutrition are SYNTHETIC test values."""

import json
from datetime import date
from decimal import Decimal

import pytest

from annona_core.domain import (
    ActivityLevel,
    Allergen,
    Equipment,
    HobType,
    MealSlot,
    Product,
    Sex,
    UserProfile,
)
from annona_core.llm import FakeLLM, LLMClient, Tier
from annona_core.nutrition import daily_targets
from annona_core.planner import (
    Available,
    MealSchedule,
    Member,
    PlanContext,
    PlanDraft,
    build_prompt,
    plan_week,
    verify,
)
from annona_core.planner.planner import _with_top_up

MONDAY = date(2026, 11, 23)
MODELS = {Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}
S = MealSlot


def person(name="Pablo", allergies=()):
    return UserProfile(
        household_id=1,
        name=name,
        sex=Sex.MALE,
        birth_date=date(2000, 1, 1),
        height_cm=Decimal(180),
        weight_kg=Decimal(80),
        activity=ActivityLevel.ACTIVE,
        allergies=list(allergies),
        allergies_confirmed=True,
    )


def item(pid, name, kcal, protein, available, not_for=()):
    return Available(
        product=Product(id=pid, name=name),
        basis="g",
        available=Decimal(available),
        intended=Decimal(available),
        kcal=Decimal(kcal) / 100,
        protein=Decimal(protein) / 100,
        not_for=tuple(not_for),
    )


AVAILABLE = (
    item(1, "oats", 380, 13, 3000),
    item(2, "milk", 60, 3, 10000),
    item(3, "lentils", 350, 24, 4000),
    item(4, "rice", 360, 7, 4000),
    item(5, "chicken", 120, 22, 4000),
    item(6, "carrots", 40, 1, 4000),
    item(7, "yogurt", 60, 4, 4000),
)
KITCHEN = Equipment(household_id=1, hob_type=HobType.CERAMIC, microwave=True, air_fryer=True)


def context(members=None, schedule=None, available=AVAILABLE, equipment=KITCHEN) -> PlanContext:
    members = members or [person()]
    return PlanContext(
        schedule=schedule or MealSchedule.build(MONDAY, weekdays=[0, 1]),
        members=tuple(Member(profile=m, daily=daily_targets(m, MONDAY)) for m in members),
        available=available,
        equipment=equipment,
    )


MEALS = {  # slot -> (title, appliances, [(product_id, grams per person)])
    S.BREAKFAST: ("Gachas de avena", ["hob"], [(1, 80), (2, 250)]),
    S.LUNCH: ("Lentejas con arroz", ["hob"], [(3, 120), (4, 60), (6, 100)]),
    S.SNACK: ("Yogur", ["none"], [(7, 250)]),
    S.DINNER: ("Pollo a la airfryer con arroz", ["air_fryer"], [(5, 200), (4, 90), (6, 100)]),
}


def draft_json(ctx, *, grams_factor=1, tweak=None) -> str:
    meals = []
    for s in ctx.schedule.slots:
        title, tools, ingredients = MEALS[s.slot]
        meal = {
            "weekday": s.day.weekday(),
            "slot": s.slot,
            "title": title,
            "appliances": tools,
            "ingredients": [{"product_id": p, "amount": g * grams_factor} for p, g in ingredients],
            "summary": "Cocinar a fuego medio.",
        }
        if tweak:
            tweak(meal)
        meals.append(meal)
    return json.dumps({"meals": meals})


def run(ctx, *answers):
    fake = FakeLLM(list(answers))
    return plan_week(LLMClient(fake, MODELS), ctx), fake


def test_valid_plan_is_accepted_and_portions_hit_the_targets():
    ctx = context()
    outcome, fake = run(ctx, draft_json(ctx))
    assert outcome.accepted and not outcome.repaired and len(fake.requests) == 1
    v = outcome.verification
    target = ctx.members[0].daily.energy_kcal
    for day in ctx.schedule.days:
        assert abs(v.kcal_by_member_day[("Pablo", day)] - target) <= 1
    assert all(
        v.usage[pid] <= a.available for a in AVAILABLE for pid in [a.product.id] if pid in v.usage
    )
    assert len(v.meals) == 8 and all(len(m.portions) == 1 for m in v.meals)
    assert fake.requests[0][0] == "fake/l"  # large tier


def test_tiny_portions_are_scaled_by_the_code_not_sent_back_to_the_model():
    ctx = context()
    outcome, fake = run(ctx, draft_json(ctx, grams_factor=0.1))  # ten times too small
    assert outcome.accepted and not outcome.repaired and len(fake.requests) == 1


def test_repair_request_names_the_gap_and_the_unused_stock():
    """When no scaling can reach the energy (the food bought is too little), the model is told
    exactly how many kcal are missing and which products still have stock."""
    little = tuple(
        a.model_copy(update={"available": a.available / 10, "intended": a.intended / 10})
        for a in AVAILABLE
    )
    ctx = context(available=little)
    outcome, fake = run(ctx, draft_json(ctx), draft_json(ctx))
    assert outcome.repaired and not outcome.accepted
    repair_text = fake.requests[1][1].messages[-1].text
    assert "kcal short of the target" in repair_text
    assert "x the drafted amounts" not in repair_text


def test_unknown_ingredient_is_rejected():
    ctx = context()

    def ghost(meal):
        meal["ingredients"].append({"product_id": 999, "amount": 50})

    bad = draft_json(ctx, tweak=ghost)
    outcome, _ = run(ctx, bad, bad)  # the "repair" keeps the invented ingredient
    assert not outcome.accepted
    assert {i.code for i in outcome.verification.issues} == {"unknown_product"}


def test_no_oven_means_no_baking():
    ctx = context()

    def bake(meal):
        if meal["slot"] == "dinner":
            meal["appliances"] = ["oven"]
            meal["summary"] = "Hornear 20 minutos."

    issues = verify(PlanDraft.model_validate_json(draft_json(ctx, tweak=bake)), ctx).issues
    assert issues and all(i.code == "appliance" for i in issues)
    assert any("oven" in i.message for i in issues)


def test_allergens_need_skipping():
    ana = person("Ana", allergies=[Allergen.MILK])
    available = tuple(
        a.model_copy(update={"not_for": ("Ana",)}) if a.product.name in ("milk", "yogurt") else a
        for a in AVAILABLE
    )
    ctx = context(members=[person(), ana], available=available)
    issues = verify(PlanDraft.model_validate_json(draft_json(ctx)), ctx).issues
    assert {i.code for i in issues} == {"not_allowed"}

    def skip_ana(meal):
        if any(i["product_id"] in (2, 7) for i in meal["ingredients"]):
            meal["skipped_by"] = ["Ana"]

    ok = verify(PlanDraft.model_validate_json(draft_json(ctx, tweak=skip_ana)), ctx)
    assert not [i for i in ok.issues if i.code == "not_allowed"]


def test_stock_is_respected_when_impossible():
    scarce = tuple(
        a.model_copy(update={"available": Decimal(100)}) if a.product.id == 5 else a
        for a in AVAILABLE
    )
    ctx = context(available=scarce)
    issues = verify(PlanDraft.model_validate_json(draft_json(ctx)), ctx).issues
    assert [i.code for i in issues] == ["stock_exceeded"]
    assert "chicken" in issues[0].message


def test_schedule_is_respected():
    """The user's example: no dinner on Tuesday."""
    schedule = MealSchedule.build(MONDAY, weekdays=[0, 1], skip=[(1, S.DINNER)])
    ctx = context(schedule=schedule)
    full_two_days = context()
    issues = verify(PlanDraft.model_validate_json(draft_json(full_two_days)), ctx).issues
    assert [i.code for i in issues] == ["unexpected_meal"]
    assert verify(PlanDraft.model_validate_json(draft_json(ctx)), ctx).ok


def test_missing_meal():
    ctx = context()
    draft = PlanDraft.model_validate_json(draft_json(ctx))
    draft.meals.pop()
    assert [i.code for i in verify(draft, ctx).issues] == ["missing_meal"]


def test_prompt_contains_only_what_is_needed():
    ctx = context()
    system, user = build_prompt(ctx)
    assert "Spanish" in system and "never bake" in system
    assert "1 | oats | other | g | 3000" in user and "weekday 1 (Tue" in user
    assert "- Pablo: breakfast ~" in user and "dinner ~" in user
    assert (
        "air_fryer" in user and "oven" not in user.split("Kitchen appliances:")[1].splitlines()[0]
    )


@pytest.mark.parametrize("language", ["es", "en"])
def test_language_parameter(language):
    ctx = context().model_copy(update={"language": language})
    system, _ = build_prompt(ctx)
    assert ("Spanish" if language == "es" else "English") in system


def test_portions_follow_the_energy_actually_bought():
    """The optimiser may buy 5 % below target; portions then shrink 5 % instead of overdrawing."""
    ctx = context().model_copy(update={"energy_scale": Decimal("0.95")})
    v = verify(PlanDraft.model_validate_json(draft_json(ctx)), ctx)
    target = ctx.members[0].daily.energy_kcal * Decimal("0.95")
    assert all(abs(v.kcal_by_member_day[("Pablo", d)] - target) <= 1 for d in ctx.schedule.days)


def test_ingredients_are_adjusted_individually_to_respect_stock():
    """Scaling a whole day uniformly would overdraw chicken; per-ingredient portions do not."""
    scarce = tuple(
        a.model_copy(update={"available": Decimal(700)}) if a.product.id == 5 else a
        for a in AVAILABLE
    )
    ctx = context(available=scarce)
    v = verify(PlanDraft.model_validate_json(draft_json(ctx)), ctx)
    assert v.ok, v.issues
    assert v.usage[5] <= Decimal("707")  # 700 + 1 % tolerance
    target = ctx.members[0].daily.energy_kcal
    assert all(abs(v.kcal_by_member_day[("Pablo", d)] - target) <= 2 for d in ctx.schedule.days)
    assert min(v.ingredient_scales) >= Decimal("0.5") and max(v.ingredient_scales) <= 3


def test_shared_dishes_scale_per_member():
    big, small = person("Marc"), person("Ana").model_copy(update={"weight_kg": Decimal(55)})
    ctx = context(members=[big, small])
    v = verify(PlanDraft.model_validate_json(draft_json(ctx)), ctx)
    assert v.ok, v.issues
    for d in ctx.schedule.days:
        for m in ctx.members:
            assert abs(v.kcal_by_member_day[(m.profile.name, d)] - m.daily.energy_kcal) <= 2


def _shopping_with_chicken(available: int, budget_left_cents: int):
    from annona_core.optimizer import Line, Result

    line = Line(
        product_id=5,
        name="chicken",
        packs_to_buy=1,
        cost_cents=600,
        pack_amount=Decimal(500),
        pack_unit="g",
        used_from_pantry=Decimal(0),
        used_total=Decimal(available),
        basis_unit="g",
        kcal=Decimal(0),
        available=Decimal(available),
        pack_basis=Decimal(500),
        price_cents=600,
    )
    return Result(status="optimal", lines=[line], total_cost_cents=10_000 - budget_left_cents)


def test_small_stock_shortfall_is_fixed_by_buying_one_more_pack():
    from annona_core.planner import make_top_up

    scarce = tuple(
        a.model_copy(update={"available": Decimal(100)}) if a.product.id == 5 else a
        for a in AVAILABLE
    )
    ctx = context(available=scarce)
    top_up = make_top_up(ctx, _shopping_with_chicken(100, budget_left_cents=2000), 10_000)
    draft = PlanDraft.model_validate_json(draft_json(ctx))
    result, extras = _with_top_up(draft, verify(draft, ctx), top_up)
    assert result.ok
    assert [(e.name, e.packs) for e in extras][0][0] == "chicken"
    assert sum(e.cost_cents for e in extras) <= 2000


def test_top_up_respects_the_budget():
    from annona_core.planner import make_top_up

    scarce = tuple(
        a.model_copy(update={"available": Decimal(100)}) if a.product.id == 5 else a
        for a in AVAILABLE
    )
    ctx = context(available=scarce)
    top_up = make_top_up(ctx, _shopping_with_chicken(100, budget_left_cents=100), 10_000)
    draft = PlanDraft.model_validate_json(draft_json(ctx))
    result, extras = _with_top_up(draft, verify(draft, ctx), top_up)
    assert not result.ok and extras == []


def test_weekly_servings_are_checked_in_the_menu():
    from annona_core.domain import Category

    meat = tuple(
        a.model_copy(update={"product": a.product.model_copy(update={"category": Category.MEAT})})
        if a.product.id == 5
        else a
        for a in AVAILABLE
    )
    wants_three = person().model_copy(update={"weekly_servings": {"meat": 3}})
    ctx = context(members=[wants_three], available=meat)  # 2 days: chicken at 2 dinners
    issues = verify(PlanDraft.model_validate_json(draft_json(ctx)), ctx).issues
    assert [i.code for i in issues] == ["servings_missing"]
    assert "meat at least 3 times" in issues[0].message and "2 times" in issues[0].message

    wants_two = person().model_copy(update={"weekly_servings": {"meat": 2}})
    ctx = context(members=[wants_two], available=meat)
    assert verify(PlanDraft.model_validate_json(draft_json(ctx)), ctx).ok


def test_preferences_reach_the_prompt():
    pablo = person().model_copy(
        update={"food_preferences": {"carrot": "less"}, "weekly_servings": {"meat": 3, "fish": 2}}
    )
    _, user = build_prompt(context(members=[pablo]))
    assert "wants at least these meals this week: fish 2, meat 3" in user
    assert "likes little carrot" in user


def test_servings_message_says_when_the_group_is_spread_too_thin():
    from annona_core.domain import Category

    meat = tuple(
        a.model_copy(update={"product": a.product.model_copy(update={"category": Category.MEAT})})
        if a.product.id == 5
        else a
        for a in AVAILABLE
    )
    wants = person().model_copy(update={"weekly_servings": {"meat": 3}})
    ctx = context(members=[wants], available=meat)

    def a_little_chicken_everywhere(meal):
        if meal["slot"] != "dinner":
            meal["ingredients"].append({"product_id": 5, "amount": 10})

    draft = PlanDraft.model_validate_json(draft_json(ctx, tweak=a_little_chicken_everywhere))
    issues = [i for i in verify(draft, ctx).issues if i.code == "servings_missing"]
    assert issues and "appears in" in issues[0].message
    assert "leave it out of the others" in issues[0].message
