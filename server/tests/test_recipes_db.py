# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recipe of the day and 'mark as cooked' against a stored plan. SYNTHETIC products, FakeLLM."""

import json
import re
from datetime import date
from decimal import Decimal

import pytest

from annona_core.domain import MealSlot, PantryItem, Unit
from annona_core.llm import FakeLLM, LLMClient, Tier
from annona_core.planner import MealSchedule
from annona_server.db import repositories as r
from annona_server.planner import plan_and_store
from annona_server.planner.recipes import (
    AlreadyCooked,
    MealNotFound,
    RecipeRejected,
    cook,
    cook_preview,
    detailed_recipe,
    load_meal,
)

from .test_optimize_db import household  # noqa: F401  (fixture)
from .test_planner_db import even_split, kitchen  # noqa: F401  (fixtures)

MONDAY = date(2026, 11, 23)
MODELS = {Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}
LUNCH = MealSlot.LUNCH


def recipe_answer(request, *, oven=False) -> str:
    """A scripted 'model': one hob step per ingredient, referencing it by placeholder."""
    text = request.messages[0].text
    ids = [int(m.group(1)) for m in re.finditer(r"^(\d+) \| [^|]+ \| [\d,.]+ \w+$", text, re.M)]
    steps = [
        {"text": f"Cocina {{p{pid}}}.", "appliance": "hob", "heat": "medium", "minutes": 5}
        for pid in ids
    ]
    if oven:
        steps.append({"text": "Hornea todo.", "appliance": "oven", "heat": "high", "minutes": 20})
    return json.dumps({"steps": steps})


class Llm:
    """Plans with even_split, recipes with recipe_answer; counts calls per task."""

    def __init__(self, *, oven=False):
        self.calls: dict[str, int] = {}
        self.oven = oven

    def __call__(self, request) -> str:
        self.calls[request.task] = self.calls.get(request.task, 0) + 1
        if request.task == "recipe_of_the_day":
            return recipe_answer(request, oven=self.oven)
        return even_split(request)

    def factory(self, session):
        return LLMClient(FakeLLM(responder=self), MODELS)


@pytest.fixture
def planned(session, kitchen):  # noqa: F811
    schedule = MealSchedule.build(MONDAY, weekdays=[0])
    llm = Llm()
    week = plan_and_store(
        session,
        llm.factory(session),
        household_id=kitchen.id,
        store_id="demo",
        schedule=schedule,
        on_date=MONDAY,
    )
    assert week.outcome.accepted
    session.commit()  # so that the API (its own session) sees the plan
    return kitchen


def test_recipe_is_generated_once_and_reused(session, planned):
    llm = Llm()
    first = detailed_recipe(session, llm.factory, planned.id, MONDAY, LUNCH)
    assert first.generated and llm.calls == {"recipe_of_the_day": 1}
    assert first.rendered.steps and all("{" not in s.text for s in first.rendered.steps)
    assert all("(" in s.text and "g)" in s.text for s in first.rendered.steps)  # amounts by code
    again = detailed_recipe(session, llm.factory, planned.id, MONDAY, LUNCH)
    assert not again.generated and llm.calls == {"recipe_of_the_day": 1}  # no second AI call
    assert again.rendered == first.rendered
    forced = detailed_recipe(session, llm.factory, planned.id, MONDAY, LUNCH, regenerate=True)
    assert forced.generated and llm.calls == {"recipe_of_the_day": 2}


def test_the_store_brand_is_left_out_of_the_names_shown(session, planned):
    products = r.SqlProductRepository(session)
    first = load_meal(session, planned.id, MONDAY, LUNCH).ingredients[0].product_id
    product = products.get(first)
    products.update(
        product.model_copy(update={"name": f"{product.name} Hacendado", "brand": "Hacendado"})
    )
    shown = detailed_recipe(session, Llm().factory, planned.id, MONDAY, LUNCH)
    assert all("Hacendado" not in i.name for i in shown.parts.totals())
    assert all("hacendado" not in s.text for s in shown.rendered.steps)


def test_a_kitchen_without_oven_never_gets_an_oven_recipe(session, planned):
    llm = Llm(oven=True)  # the 'model' insists on baking, also after the repair
    with pytest.raises(RecipeRejected) as error:
        detailed_recipe(session, llm.factory, planned.id, MONDAY, LUNCH)
    assert any("oven" in message for message in error.value.issues)
    assert load_meal(session, planned.id, MONDAY, LUNCH).recipe.method == []  # nothing stored
    assert llm.calls == {"recipe_of_the_day": 2}  # one call + one repair


def test_a_stored_recipe_is_replaced_when_the_kitchen_no_longer_fits(session, planned):
    equipment = r.EquipmentRepository(session).list(household_id=planned.id)[0]
    r.EquipmentRepository(session).update(equipment.model_copy(update={"oven": True}))
    baking = Llm(oven=True)
    with_oven = detailed_recipe(session, baking.factory, planned.id, MONDAY, LUNCH)
    assert any(s.appliance == "oven" for s in with_oven.rendered.steps)

    r.EquipmentRepository(session).update(equipment.model_copy(update={"oven": False}))
    plain = Llm()
    now = detailed_recipe(session, plain.factory, planned.id, MONDAY, LUNCH)
    assert now.generated and plain.calls == {"recipe_of_the_day": 1}
    assert all(s.appliance != "oven" for s in now.rendered.steps)


def test_calibration_changes_the_boil_time_without_a_new_ai_call(session, planned):
    llm = Llm()
    detailed_recipe(session, llm.factory, planned.id, MONDAY, LUNCH)
    stored = r.EquipmentRepository(session).list(household_id=planned.id)[0]
    r.EquipmentRepository(session).update(
        stored.model_copy(
            update={
                "power_levels": 9,
                "calibration_level": 6,
                "calibration_boil_1l_minutes": Decimal(7),
            }
        )
    )
    again = detailed_recipe(session, llm.factory, planned.id, MONDAY, LUNCH)
    assert not again.generated and again.rendered.calibrated
    assert all(s.dial_level is not None for s in again.rendered.steps)


def test_unknown_meal(session, planned):
    with pytest.raises(MealNotFound):
        detailed_recipe(session, Llm().factory, planned.id, date(2026, 11, 24), LUNCH)
    with pytest.raises(MealNotFound):
        cook_preview(session, planned.id, date(2030, 1, 7), LUNCH)


# ------------------------------------------------------------------------------ cooked


def stock(session, household_id, product_id, amount, *, unit=Unit.G, expires=None, added=None):
    return r.SqlPantryRepository(session).add(
        PantryItem(
            household_id=household_id,
            product_id=product_id,
            amount=Decimal(amount),
            unit=unit,
            expires_at=expires,
            **({"added_at": added} if added else {}),
        )
    )


def test_preview_with_an_empty_pantry_deducts_nothing_and_says_why(session, planned):
    preview = cook_preview(session, planned.id, MONDAY, LUNCH)
    assert preview.lines and not preview.already_cooked
    assert all(ln.deduct == 0 and ln.note == "not_in_pantry" for ln in preview.lines)
    assert all(ln.missing == ln.needed for ln in preview.lines)


def test_cooking_deducts_the_pantry_once_and_never_goes_negative(session, planned):
    preview = cook_preview(session, planned.id, MONDAY, LUNCH)
    plenty, short, none = preview.lines[0], preview.lines[1], preview.lines[2]
    stock(session, planned.id, plenty.product_id, plenty.needed + 500)
    stock(session, planned.id, short.product_id, short.needed / 2)
    pantry = r.SqlPantryRepository(session)

    result = cook(session, planned.id, MONDAY, LUNCH)
    by_id = {ln.product_id: ln for ln in result.lines}
    assert (
        by_id[plenty.product_id].deduct == plenty.needed and by_id[plenty.product_id].note is None
    )
    assert by_id[short.product_id].note == "not_enough"
    assert by_id[none.product_id].note == "not_in_pantry"

    left = {i.product_id: i.amount for i in pantry.for_household(planned.id)}
    assert left[plenty.product_id] == Decimal(500)  # exactly what was not needed
    assert short.product_id not in left  # used up: the empty row is removed
    assert none.product_id not in left  # and no negative stock was created

    assert all(
        row.cooked_at is not None for row in load_meal(session, planned.id, MONDAY, LUNCH).rows
    )
    with pytest.raises(AlreadyCooked):
        cook(session, planned.id, MONDAY, LUNCH)
    assert cook_preview(session, planned.id, MONDAY, LUNCH).already_cooked


def test_products_the_person_skips_are_not_deducted(session, planned):
    line = cook_preview(session, planned.id, MONDAY, LUNCH).lines[0]
    stock(session, planned.id, line.product_id, line.needed + 100)
    cook(session, planned.id, MONDAY, LUNCH, skip_products=frozenset({line.product_id}))
    [item] = [
        i
        for i in r.SqlPantryRepository(session).for_household(planned.id)
        if i.product_id == line.product_id
    ]
    assert item.amount == line.needed + 100


def test_the_item_that_expires_first_is_used_first(session, planned):
    line = cook_preview(session, planned.id, MONDAY, LUNCH).lines[0]
    soon = stock(session, planned.id, line.product_id, line.needed, expires=date(2026, 11, 25))
    later = stock(session, planned.id, line.product_id, 1000, expires=date(2027, 3, 1))
    cook(session, planned.id, MONDAY, LUNCH)
    left = {
        i.id: i.amount
        for i in r.SqlPantryRepository(session).for_household(planned.id)
        if i.product_id == line.product_id
    }
    assert soon.id not in left and left[later.id] == Decimal(1000)  # the nearer date went first


def test_an_amount_that_cannot_be_converted_is_reported(session, planned):
    """An amount in 'unit' cannot be converted to grams without a weight: say so, don't guess."""
    line = cook_preview(session, planned.id, MONDAY, LUNCH).lines[0]
    stock(session, planned.id, line.product_id, 3, unit=Unit.UNIT)
    again = cook_preview(session, planned.id, MONDAY, LUNCH).lines[0]
    assert again.deduct == 0 and again.note == "unit_unknown"


# ------------------------------------------------------------------------------ the API


@pytest.fixture
def api(engine):
    from fastapi.testclient import TestClient

    from annona_server.api import create_app
    from annona_server.jobs import InlineExecutor, JobRunner

    llm = Llm()
    app = create_app(
        engine=engine,
        runner=JobRunner(engine, InlineExecutor()),
        token="t",
        llm_factory=llm.factory,
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer t"
        client.llm = llm
        yield client


def test_recipe_and_cook_endpoints(api, session, planned):
    body = {"day": MONDAY.isoformat(), "slot": "lunch"}
    first = api.post("/api/v1/meals/recipe", json=body)
    assert first.status_code == 200, first.text
    recipe = first.json()
    assert recipe["generated"] and recipe["steps"] and recipe["cooked_at"] is None
    assert recipe["eaters"][0]["name"] == "Me" and recipe["ingredients"]
    assert recipe["portions"]["Me"]
    assert api.post("/api/v1/meals/recipe", json=body).json()["generated"] is False

    preview = api.get("/api/v1/meals/cook-preview", params=body).json()
    assert preview["already_cooked"] is False and preview["lines"]
    assert {ln["note"] for ln in preview["lines"]} == {"not_in_pantry"}

    line = preview["lines"][0]
    api.post(
        "/api/v1/pantry",
        json={"product_id": line["product_id"], "amount": "5000", "unit": "g"},
    )
    cooked = api.post("/api/v1/meals/cook", json=body)
    assert cooked.status_code == 200 and cooked.json()["already_cooked"] is True
    pantry = api.get("/api/v1/pantry").json()["items"]
    assert Decimal(pantry[0]["amount"]) == Decimal(5000) - Decimal(line["needed"])

    again = api.post("/api/v1/meals/cook", json=body)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_cooked"
    assert api.post("/api/v1/meals/recipe", json=body).json()["cooked_at"] is not None


def test_endpoint_errors(api, planned):
    missing = {"day": "2030-01-07", "slot": "lunch"}
    assert api.post("/api/v1/meals/recipe", json=missing).status_code == 404
    assert api.get("/api/v1/meals/cook-preview", params=missing).status_code == 404
    assert api.post("/api/v1/meals/cook", json=missing).status_code == 404
    api.llm.oven = True
    rejected = api.post("/api/v1/meals/recipe", json={"day": MONDAY.isoformat(), "slot": "lunch"})
    assert rejected.status_code == 422
    error = rejected.json()["error"]
    assert error["code"] == "recipe_rejected" and any("oven" in m for m in error["details"])
