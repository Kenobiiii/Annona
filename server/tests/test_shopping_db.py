# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shopping list per store, substitutions and the pantry effect of ticking. SYNTHETIC data."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from annona_core.domain import (
    NutritionFacts,
    NutritionSource,
    PantryItem,
    Price,
    PriceSource,
    Product,
    Unit,
)
from annona_core.llm import FakeLLM, LLMClient, Tier
from annona_core.planner import MealSchedule
from annona_server.db import repositories as r
from annona_server.planner import existing_plan, plan_and_store
from annona_server.shopping import (
    UnknownStore,
    build_list,
    find_list,
    plan_needs,
    set_checked,
    view_list,
)

from .test_optimize_db import household  # noqa: F401  (fixture)
from .test_planner_db import even_split, kitchen  # noqa: F401  (fixture)

MONDAY = date(2026, 11, 23)
MODELS = {Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}


def add_to_store(session, base, store, name, pack, cents, *, kcal=None):
    n = base.nutrition
    product = r.SqlProductRepository(session).add(
        Product(
            name=name,
            category=base.category,
            type=base.type,
            store_id=store,
            store_sku=name,
            package_amount=Decimal(pack),
            package_unit=Unit.G,
            allergens=[],
            nutrition=NutritionFacts(
                energy_kcal=Decimal(kcal) if kcal is not None else n.energy_kcal,
                protein_g=n.protein_g,
                fat_g=n.fat_g,
                carbohydrates_g=n.carbohydrates_g,
                source=NutritionSource.MANUAL,
            ),
        )
    )
    r.SqlPriceRepository(session).add(
        Price(
            product_id=product.id,
            store_id=store,
            amount_cents=cents,
            source=PriceSource.MANUAL,
            observed_at=datetime(2026, 11, 20, tzinfo=UTC),
        )
    )
    return product


@pytest.fixture
def world(session, kitchen):  # noqa: F811
    """A plan made at 'demo', and a second store 'other' with different products and packs."""
    products = r.SqlProductRepository(session)
    demo = {p.name: p for p in products.list(store_id="demo")}
    for p in demo.values():  # the type is what makes products equivalent across stores
        products.update(p.model_copy(update={"type": p.name}))
    demo = {p.name: p for p in products.list(store_id="demo")}

    llm = LLMClient(FakeLLM(responder=even_split), MODELS)
    week = plan_and_store(
        session,
        llm,
        household_id=kitchen.id,
        store_id="demo",
        schedule=MealSchedule.build(MONDAY, weekdays=[0, 1]),
        on_date=MONDAY,
    )
    assert week.outcome.accepted

    other = {}
    for name, p in demo.items():
        if name == "peanuts":
            continue  # 'other' does not sell peanuts at all
        other[name] = add_to_store(session, p, "other", f"{name} (otra tienda)", 500, 90)
    other["rice 2"] = add_to_store(
        session, demo["rice"], "other", "arroz bomba", 1000, 260, kcal=350
    )
    other["rice 3"] = add_to_store(
        session, demo["rice"], "other", "arroz integral", 1000, 190, kcal=360
    )
    session.commit()
    return {"household": kitchen, "plan_id": week.plan_id, "demo": demo, "other": other}


def used_names(session, world):
    needs, _ = plan_needs(session, world["household"].id, world["plan_id"])
    return {n.name for n in needs}


def test_the_plan_store_list_is_the_one_made_with_the_plan(session, world):
    home, plan_id = world["household"], world["plan_id"]
    made = find_list(session, plan_id, "demo")
    assert made is not None
    assert build_list(session, home, plan_id, "demo").id == made.id  # not duplicated
    view = view_list(session, home, made)
    assert view.items and all(i.replaces is None for i in view.items)
    assert view.total_cents == sum(i.item.packs * i.item.unit_price_cents for i in view.items) > 0


def test_switching_store_builds_another_list_with_substitutes(session, world):
    home, plan_id = world["household"], world["plan_id"]
    made = build_list(session, home, plan_id, "other")
    assert made.store_id == "other"
    view = view_list(session, home, made)
    names = {i.name for i in view.items}
    # Every product of the menu has an equivalent here, so all are substitutes.
    assert view.items and all(i.replaces for i in view.items)
    assert all("(otra tienda)" in n or n.startswith("arroz") for n in names)
    assert view.total_cents == sum(i.item.packs * i.item.unit_price_cents for i in view.items)
    assert {find_list(session, plan_id, s).store_id for s in ("demo", "other")} == {"demo", "other"}


def test_the_cheapest_equivalent_is_suggested_and_the_others_are_alternatives(session, world):
    home, plan_id = world["household"], world["plan_id"]
    view = view_list(session, home, build_list(session, home, plan_id, "other"))
    rice = next(i for i in view.items if i.replaces == "rice")
    assert rice.name == "rice (otra tienda)"  # 90 per 500 g pack is the cheapest for the need
    assert {a.name for a in rice.alternatives} == {"arroz bomba", "arroz integral"}
    integral = next(a for a in rice.alternatives if a.name == "arroz integral")
    assert integral.extra_cost_cents > 0 and integral.kcal_diff_pct is not None


def test_a_product_the_store_does_not_sell_is_reported_not_invented(session, world):
    home, plan_id = world["household"], world["plan_id"]
    needs, _ = plan_needs(session, home.id, plan_id)
    assert "peanuts" in {n.name for n in needs}, "the demo plan is expected to use peanuts"
    view = view_list(session, home, build_list(session, home, plan_id, "other"))
    assert [u.name for u in view.unavailable] == ["peanuts"]
    assert view.unavailable[0].reason == "not_sold" and view.unavailable[0].amount > 0
    assert all(i.name != "peanuts" for i in view.items)


def test_what_the_pantry_holds_is_not_bought(session, world):
    home, plan_id = world["household"], world["plan_id"]
    needs, _ = plan_needs(session, home.id, plan_id)
    oats = next(n for n in needs if n.name == "oats")
    r.SqlPantryRepository(session).add(
        PantryItem(
            household_id=home.id,
            product_id=oats.product_id,
            amount=oats.amount,
            unit=Unit.G,
        )
    )
    view = view_list(session, home, build_list(session, home, plan_id, "other"))
    assert all(i.replaces != "oats" for i in view.items)  # fully covered by the pantry


def test_an_unknown_store_is_refused(session, world):
    with pytest.raises(UnknownStore):
        build_list(session, world["household"], world["plan_id"], "nowhere")


def test_rebuilding_replaces_the_list_and_forgets_the_ticks(session, world):
    home, plan_id = world["household"], world["plan_id"]
    first = build_list(session, home, plan_id, "other")
    item = r.ShoppingItemRepository(session).list(list_id=first.id)[0]
    set_checked(session, home, item, True)
    again = build_list(session, home, plan_id, "other")
    assert again.id == first.id  # the same list, kept
    rebuilt = build_list(session, home, plan_id, "other", refresh=True)
    assert all(not i.checked for i in r.ShoppingItemRepository(session).list(list_id=rebuilt.id))


# ------------------------------------------------------------------ ticking and the pantry


def first_item(session, world, store="demo"):
    shopping_list = find_list(session, world["plan_id"], store) or build_list(
        session, world["household"], world["plan_id"], store
    )
    return r.ShoppingItemRepository(session).list(list_id=shopping_list.id)[0]


def pantry_amount(session, world, product_id):
    return sum(
        (
            i.amount
            for i in r.SqlPantryRepository(session).for_household(world["household"].id)
            if i.product_id == product_id
        ),
        Decimal(0),
    )


def test_ticking_adds_the_packs_to_the_pantry_and_unticking_takes_them_back(session, world):
    home = world["household"]
    item = first_item(session, world)
    pack = r.SqlProductRepository(session).get(item.product_id).package_amount
    assert pantry_amount(session, world, item.product_id) == 0

    ticked, effect = set_checked(session, home, item, True)
    assert ticked.checked and effect.direction == "added"
    assert effect.amount == pack * item.packs == pantry_amount(session, world, item.product_id)

    again, none = set_checked(session, home, ticked, True)  # repeating changes nothing
    assert none is None and pantry_amount(session, world, item.product_id) == pack * item.packs

    unticked, back = set_checked(session, home, ticked, False)
    assert not unticked.checked and back.direction == "removed"
    assert pantry_amount(session, world, item.product_id) == 0


def test_unticking_never_makes_the_pantry_negative(session, world):
    home = world["household"]
    item = first_item(session, world)
    ticked, _ = set_checked(session, home, item, True)
    [row] = [
        i
        for i in r.SqlPantryRepository(session).for_household(home.id)
        if i.product_id == item.product_id
    ]
    r.SqlPantryRepository(session).update(row.model_copy(update={"amount": Decimal(10)}))  # cooked
    set_checked(session, home, ticked, False)
    assert pantry_amount(session, world, item.product_id) == 0


def test_ticking_adds_to_an_existing_pantry_item(session, world):
    home = world["household"]
    item = first_item(session, world)
    r.SqlPantryRepository(session).add(
        PantryItem(
            household_id=home.id, product_id=item.product_id, amount=Decimal(40), unit=Unit.G
        )
    )
    _, effect = set_checked(session, home, item, True)
    rows = [
        i
        for i in r.SqlPantryRepository(session).for_household(home.id)
        if i.product_id == item.product_id
    ]
    assert len(rows) == 1 and rows[0].amount == 40 + effect.amount


def test_each_store_list_keeps_its_own_ticks(session, world):
    home = world["household"]
    demo_item = first_item(session, world, "demo")
    other_item = first_item(session, world, "other")
    set_checked(session, home, other_item, True)
    assert not r.ShoppingItemRepository(session).get(demo_item.id).checked
    assert r.ShoppingItemRepository(session).get(other_item.id).checked
    assert existing_plan(session, home.id, MONDAY) is not None


# ------------------------------------------------------------------------------ the API


@pytest.fixture
def api(engine, world, session):
    from fastapi.testclient import TestClient

    from annona_server.api import create_app

    session.commit()
    app = create_app(engine=engine, token="t")
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer t"
        yield client


def test_api_store_switching_and_ticking(api, world):
    plan_id = world["plan_id"]
    url = f"/api/v1/plans/{plan_id}/shopping-list"
    demo = api.get(url).json()
    assert demo["store_id"] == "demo" and demo["items"] and demo["unavailable"] == []

    assert api.get(url, params={"store_id": "other"}).status_code == 404  # not built yet
    other = api.post(url, json={"store_id": "other"})
    assert other.status_code == 200
    body = other.json()
    assert body["store_id"] == "other" and body["total_cents"] > 0
    assert [u["name"] for u in body["unavailable"]] == ["peanuts"]
    rice = next(i for i in body["items"] if i["replaces"] == "rice")
    assert rice["alternatives"] and rice["alternatives"][0]["extra_cost_cents"] > 0

    assert api.get(url, params={"store_id": "demo"}).json()["store_id"] == "demo"
    assert api.get(url).json()["store_id"] == "other"  # the latest one by default
    assert api.post(url, json={"store_id": "nowhere"}).status_code == 404

    item = body["items"][0]
    ticked = api.patch(f"/api/v1/shopping-items/{item['id']}", json={"checked": True}).json()
    assert ticked["checked"] and ticked["pantry_effect"]["direction"] == "added"
    pantry = api.get("/api/v1/pantry").json()["items"]
    assert any(p["product_id"] == item["product_id"] for p in pantry)
    undone = api.patch(f"/api/v1/shopping-items/{item['id']}", json={"checked": False}).json()
    assert undone["pantry_effect"]["direction"] == "removed"
    assert api.get("/api/v1/pantry").json()["items"] == []
