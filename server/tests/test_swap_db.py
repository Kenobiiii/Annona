# SPDX-License-Identifier: AGPL-3.0-or-later
"""Replacing one meal: proposal (no changes), verification and applying. SYNTHETIC data, FakeLLM."""

import json
import re
from datetime import date
from decimal import Decimal

import pytest

from annona_core.domain import MealSlot
from annona_core.llm import FakeLLM, LLMClient
from annona_server.db import repositories as r
from annona_server.planner.recipes import load_meal
from annona_server.planner.swap import SwapError, SwapProposal, apply_swap, propose_swap

from .test_optimize_db import household  # noqa: F401  (fixture)
from .test_planner_db import kitchen  # noqa: F401  (fixture)
from .test_shopping_db import MODELS, MONDAY, world  # noqa: F401  (fixtures)

TUESDAY = date(2026, 11, 24)
DINNER = MealSlot.DINNER


def replacement(*, oven=False, title="Pasta rápida"):
    """A scripted 'model': one dish for the single slot, from the first two leftover products."""

    def respond(request):
        text = request.messages[0].text
        products = [
            (int(m.group(1)), Decimal(m.group(2)))
            for m in re.finditer(r"^(\d+) \| [^|]+ \| \w+ \| \w+ \| (\d+) \|", text, re.M)
        ][:2]
        day = int(re.search(r"^- weekday (\d)", text, re.M).group(1))
        slot = re.search(r"^- weekday \d \([^)]*\): (\w+)", text, re.M).group(1)
        return json.dumps(
            {
                "meals": [
                    {
                        "weekday": day,
                        "slot": slot,
                        "title": title,
                        "appliances": ["oven"] if oven else ["hob"],
                        "ingredients": [
                            {"product_id": pid, "amount": str(min(amount / 4, Decimal(150)))}
                            for pid, amount in products
                        ],
                        "summary": "Hornear 20 minutos." if oven else "Cocinar a fuego medio.",
                    }
                ]
            }
        )

    return LLMClient(FakeLLM(responder=respond), MODELS)


def planned(session, world, day=TUESDAY, slot=DINNER):  # noqa: F811
    return load_meal(session, world["household"].id, day, slot)


def test_a_swap_is_only_a_proposal_until_it_is_applied(session, world):  # noqa: F811
    home = world["household"]
    before = planned(session, world)
    proposal = propose_swap(
        session, replacement(), home, TUESDAY, DINNER, "algo rápido", avoid_appliances=["oven"]
    )
    assert proposal.title == "Pasta rápida" and proposal.old_title == before.recipe.title
    assert proposal.appliances == ["hob"] and proposal.ingredients and proposal.members
    after = planned(session, world)
    assert (
        after.recipe.id == before.recipe.id and after.recipe.title == before.recipe.title
    )  # untouched
    assert {r.recipe_id for r in after.rows} == {before.recipe.id}


def test_the_replacement_only_uses_products_that_were_already_bought(session, world):  # noqa: F811
    home = world["household"]
    proposal = propose_swap(session, replacement(), home, TUESDAY, DINNER, "otra cosa")
    bought = {
        i.product_id
        for lst in r.ShoppingListRepository(session).list(plan_id=world["plan_id"])
        for i in r.ShoppingItemRepository(session).list(list_id=lst.id)
    }
    assert {i.product_id for i in proposal.ingredients} <= bought


def test_a_requested_oven_free_dish_never_has_an_oven_step(session, world):  # noqa: F811
    """Acceptance: 'without oven' is enforced by code even when the kitchen has an oven."""
    home = world["household"]
    equipment = r.EquipmentRepository(session).list(household_id=home.id)[0]
    r.EquipmentRepository(session).update(equipment.model_copy(update={"oven": True}))
    with pytest.raises(SwapError) as error:
        propose_swap(  # the 'model' insists on baking, also after the repair
            session,
            replacement(oven=True),
            home,
            TUESDAY,
            DINNER,
            "sin horno",
            avoid_appliances=["oven"],
        )
    assert error.value.code == "not_possible" and "oven" in error.value.message
    allowed = propose_swap(session, replacement(oven=True), home, TUESDAY, DINNER, "con horno")
    assert allowed.appliances == ["oven"]  # without the restriction the oven is fine


def test_applying_replaces_that_meal_and_nothing_else(session, world):  # noqa: F811
    home = world["household"]
    monday_dinner = planned(session, world, MONDAY, DINNER)
    shopping = [
        (i.product_id, i.packs)
        for lst in r.ShoppingListRepository(session).list(plan_id=world["plan_id"])
        for i in r.ShoppingItemRepository(session).list(list_id=lst.id)
    ]
    proposal = propose_swap(
        session, replacement(), home, TUESDAY, DINNER, "cambia", avoid_appliances=["oven"]
    )
    apply_swap(session, home, proposal)

    now = planned(session, world)
    assert now.recipe.title == "Pasta rápida" and now.recipe.id != proposal.old_recipe_id
    assert {i.product_id for i in now.ingredients} == {i.product_id for i in proposal.ingredients}
    assert all(row.recipe_id == now.recipe.id for row in now.rows)
    assert r.RecipeRepository(session).get(proposal.old_recipe_id) is None  # the old one is gone
    assert (
        planned(session, world, MONDAY, DINNER).recipe.id == monday_dinner.recipe.id
    )  # others intact
    assert shopping == [  # the shopping list did not change
        (i.product_id, i.packs)
        for lst in r.ShoppingListRepository(session).list(plan_id=world["plan_id"])
        for i in r.ShoppingItemRepository(session).list(list_id=lst.id)
    ]


def test_a_proposal_cannot_be_applied_twice_or_after_the_menu_changed(session, world):  # noqa: F811
    home = world["household"]
    proposal = propose_swap(session, replacement(), home, TUESDAY, DINNER, "cambia")
    apply_swap(session, home, proposal)
    with pytest.raises(SwapError) as error:
        apply_swap(session, home, proposal)
    assert error.value.code == "stale"


def test_a_cooked_meal_cannot_be_replaced(session, world):  # noqa: F811
    from datetime import UTC, datetime

    home = world["household"]
    for row in planned(session, world).rows:
        r.PlannedMealRepository(session).update(
            row.model_copy(update={"cooked_at": datetime.now(UTC)})
        )
    with pytest.raises(SwapError) as error:
        propose_swap(session, replacement(), home, TUESDAY, DINNER, "cambia")
    assert error.value.code == "already_cooked"


def test_with_nothing_left_over_it_says_so_instead_of_buying(session, world):  # noqa: F811
    home = world["household"]
    for lst in r.ShoppingListRepository(session).list(plan_id=world["plan_id"]):
        for item in r.ShoppingItemRepository(session).list(list_id=lst.id):
            r.ShoppingItemRepository(session).delete(item.id)
    with pytest.raises(SwapError) as error:
        propose_swap(session, replacement(), home, TUESDAY, DINNER, "cambia")
    assert error.value.code == "no_stock"


def test_a_meal_that_is_not_planned_is_not_found(session, world):  # noqa: F811
    from annona_server.planner.recipes import MealNotFound

    with pytest.raises(MealNotFound):
        propose_swap(session, replacement(), world["household"], date(2030, 1, 7), DINNER, "x")


def test_the_proposal_survives_being_stored_as_json(session, world):  # noqa: F811
    home = world["household"]
    proposal = propose_swap(session, replacement(), home, TUESDAY, DINNER, "cambia")
    restored = SwapProposal.model_validate(json.loads(proposal.model_dump_json()))
    assert restored == proposal
    apply_swap(session, home, restored)
