# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recipe of a meal with FakeLLM. Ingredients and times are SYNTHETIC test values."""

import json
from decimal import Decimal

import pytest

from annona_core.domain import Appliance, Equipment, HeatLevel, HobType
from annona_core.llm import FakeLLM, LLMClient, Tier
from annona_core.planner import (
    MealIngredient,
    RecipeContext,
    RecipeDraft,
    generate_recipe,
    render_recipe,
    to_method,
    validate_recipe,
)

MODELS = {Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}


def ingredients():
    return (
        MealIngredient(product_id=1, name="Arroz redondo", amount=Decimal("200"), unit="g"),
        MealIngredient(product_id=2, name="Pechuga de pollo", amount=Decimal("300"), unit="g"),
        MealIngredient(product_id=3, name="Cebolla", amount=Decimal("100"), unit="g"),
    )


def kitchen(**extra):
    return Equipment(household_id=1, hob_type=HobType.INDUCTION, burners=3, **extra)


def context(equipment=None, other_foods=()):
    return RecipeContext(
        title="Arroz con pollo",
        summary="Arroz con pollo y cebolla a fuego medio.",
        ingredients=ingredients(),
        eaters=("Pablo",),
        equipment=equipment or kitchen(),
        other_foods=other_foods,
    )


def step(text, appliance="hob", heat="medium", minutes=10, boil_ml=None):
    return {
        "text": text,
        "appliance": appliance,
        "heat": heat,
        "minutes": minutes,
        "boil_ml": boil_ml,
    }


GOOD = [
    step("Corta {p3} en dados pequeños.", appliance="none", heat="none", minutes=5),
    step("Hierve agua para {p1}.", heat="high", minutes=8, boil_ml=1500),
    step("Cuece {p1} hasta que esté tierno.", minutes=12),
    step("Dora {p2} con {p3}.", minutes=10),
]


def answer(steps):
    return json.dumps({"steps": steps})


def run(ctx, *answers):
    fake = FakeLLM(list(answers))
    return generate_recipe(LLMClient(fake, MODELS), ctx), fake


def codes(draft, ctx):
    return {i.code for i in validate_recipe(RecipeDraft.model_validate_json(answer(draft)), ctx)}


def test_a_valid_recipe_is_accepted_with_one_large_call():
    outcome, fake = run(context(), answer(GOOD))
    assert outcome.accepted and not outcome.repaired and len(fake.requests) == 1
    assert fake.requests[0][0] == "fake/l"
    assert "{pID}" in fake.requests[0][1].system  # the placeholder rule is in the prompt


def test_prompt_lists_ingredients_and_appliances_but_no_oven():
    _, fake = run(context(), answer(GOOD))
    user = fake.requests[0][1].messages[0].text
    assert "1 | Arroz redondo | 200 g" in user
    assert "hob" in user.split("Kitchen appliances:")[1].splitlines()[0]
    assert "oven" not in user.split("Kitchen appliances:")[1].splitlines()[0]


def test_no_oven_means_no_oven_steps_even_after_a_repair():
    """Acceptance criterion: a no-oven kitchen never gets an oven step."""
    ctx = context(kitchen(oven=False))
    baking = [*GOOD[:3], step("Gratina {p2} y {p3} en el horno.", appliance="oven", minutes=20)]
    outcome, fake = run(ctx, answer(baking), answer(baking))  # the repair keeps the oven
    assert outcome.repaired and not outcome.accepted
    assert {i.code for i in outcome.issues} == {"appliance"}
    assert "oven" in fake.requests[1][1].messages[-1].text


def test_oven_words_in_text_are_caught_even_with_another_appliance():
    sneaky = [*GOOD[:3], step("Hornea {p2} y {p3} un rato.", appliance="hob")]
    assert codes(sneaky, context(kitchen(oven=False))) == {"appliance"}
    assert codes(sneaky, context(kitchen(oven=True))) == set()


def test_a_repair_can_fix_the_recipe():
    forgetful = [step("Cuece {p1} y {p2}.")]  # never uses the onion
    outcome, fake = run(context(), answer(forgetful), answer(GOOD))
    assert outcome.repaired and outcome.accepted and len(fake.requests) == 2
    assert "not used in any step" in fake.requests[1][1].messages[-1].text


@pytest.mark.parametrize(
    ("steps", "code"),
    [
        ([*GOOD, step("Añade {p9}.")], "unknown_ingredient"),
        ([*GOOD, step("Añade {p1 y sal.")], "bad_placeholder"),
        ([*GOOD, step("Añade 200 g de sal.")], "quantity_in_text"),
        ([*GOOD, step("Añade 1,5 litros de agua.")], "quantity_in_text"),
        ([step("Cuece {p1} y {p2}.")], "ingredient_unused"),
        ([*GOOD[:3], step("Hierve agua.", appliance="none", boil_ml=500)], "boil_needs_hob"),
        ([*GOOD, step("Sirve en el microondas.", appliance="microwave")], "appliance"),
    ],
)
def test_each_kind_of_problem_is_reported(steps, code):
    assert code in codes(steps, context())


def test_foods_that_are_not_in_the_meal_are_caught():
    ctx = context(other_foods=("Nata para cocinar Hacendado", "Queso rallado"))
    assert codes([*GOOD, step("Añade un poco de nata y remueve.")], ctx) == {"foreign_food"}
    assert codes([*GOOD, step("Añade un poco de sal y agua.")], ctx) == set()  # free items
    assert codes(GOOD, ctx) == set()  # its own ingredients are fine


def test_amounts_are_filled_in_by_code_not_written_by_the_model():
    method = to_method(RecipeDraft.model_validate_json(answer(GOOD)))
    shown = render_recipe(method, ingredients(), kitchen())
    assert shown.steps[0].text == "Corta cebolla (100 g) en dados pequeños."
    assert shown.steps[3].text == "Dora pechuga de pollo (300 g) con cebolla (100 g)."
    assert all("{" not in s.text for s in shown.steps)


def test_boil_time_follows_the_calibration_in_proportion_to_the_volume():
    method = to_method(RecipeDraft.model_validate_json(answer(GOOD)))
    # 1 L took 7 minutes at level 6: 1.5 L takes 10.5 -> 11 minutes, at level 6.
    equipment = kitchen(power_levels=9, calibration_level=6, calibration_boil_1l_minutes=Decimal(7))
    shown = render_recipe(method, ingredients(), equipment)
    boil = shown.steps[1]
    assert (boil.minutes, boil.minutes_estimated, boil.dial_level) == (11, False, 6)
    assert shown.calibrated
    # The food's own cooking time is never rescaled.
    assert shown.steps[2].minutes == 12 and shown.steps[2].minutes_estimated


def test_without_calibration_times_are_the_models_estimate():
    method = to_method(RecipeDraft.model_validate_json(answer(GOOD)))
    shown = render_recipe(method, ingredients(), kitchen())
    assert shown.steps[1].minutes == 8 and shown.steps[1].minutes_estimated
    assert not shown.calibrated
    assert shown.total_minutes == 5 + 8 + 12 + 10


def test_heat_words_map_to_dial_levels_only_when_the_dial_is_known():
    method = to_method(RecipeDraft.model_validate_json(answer(GOOD)))
    with_dial = render_recipe(method, ingredients(), kitchen(power_levels=10))
    assert with_dial.steps[2].dial_level == 5  # medium = half of 10 (estimate)
    no_dial = render_recipe(method, ingredients(), kitchen())
    assert no_dial.steps[2].dial_level is None
    assert with_dial.steps[0].dial_level is None  # no hob in that step


def test_heat_is_dropped_when_no_appliance_is_used():
    method = to_method(
        RecipeDraft.model_validate_json(
            answer([step("Mezcla {p1}.", appliance="none", heat="high")])
        )
    )
    assert method[0].heat == HeatLevel.NONE and method[0].appliance == Appliance.NONE


@pytest.mark.parametrize(("ml", "text"), [(1500, "1,5 l"), (250, "250 ml"), (30, "30 ml")])
def test_amount_formatting(ml, text):
    item = MealIngredient(product_id=1, name="Leche", amount=Decimal(ml), unit="ml")
    method = to_method(RecipeDraft.model_validate_json(answer([step("Calienta {p1}.")])))
    assert text in render_recipe(method, (item,), kitchen()).steps[0].text
