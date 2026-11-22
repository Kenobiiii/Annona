# SPDX-License-Identifier: AGPL-3.0-or-later
"""REST API tests (httpx TestClient). FakeLLM, inline jobs, SYNTHETIC products and prices."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from annona_core.llm import FakeLLM, Tier
from annona_server.api import create_app
from annona_server.jobs import InlineExecutor, JobRunner
from annona_server.llm import make_llm_client
from annona_server.llm.config import LLMSettings

from .test_planner_db import even_split

TOKEN = "secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
MONDAY = date(2026, 11, 23)
PABLO = {
    "name": "Pablo",
    "sex": "male",
    "birth_date": "2005-01-01",
    "height_cm": 185,
    "weight_kg": 85,
    "activity": "active",
    "allergies_confirmed": True,
}


@pytest.fixture
def client(engine):
    app = create_app(
        engine=engine,
        runner=JobRunner(engine, InlineExecutor()),
        token=TOKEN,
        llm_factory=lambda session: make_llm_client(
            session,
            settings=LLMSettings(models={Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}),
            backend=FakeLLM(responder=even_split),
        ),
    )
    with TestClient(app) as c:
        yield c


def setup_home(client):
    client.put(
        "/api/v1/household", json={"name": "Casa", "weekly_budget_cents": 8000}, headers=AUTH
    )
    return client.post("/api/v1/profiles", json=PABLO, headers=AUTH).json()


def test_health_needs_no_token(client):
    assert client.get("/health").json()["status"] == "ok"


def test_token_is_required_and_errors_have_one_format(client):
    r = client.get("/api/v1/stores")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert (
        client.get("/api/v1/stores", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )


def test_unconfigured_token_refuses(engine):
    app = create_app(engine=engine, token="")
    with TestClient(app) as c:
        assert c.get("/api/v1/stores", headers=AUTH).json()["error"]["code"] == "not_configured"


def test_household_setup_and_profiles(client):
    assert client.get("/api/v1/household", headers=AUTH).json()["error"]["code"] == "setup_required"
    created = setup_home(client)
    assert created["targets"]["energy_kcal"]  # daily targets are computed
    assert created["allergy_notice"] is None
    pid = created["profile"]["id"]
    changed = dict(PABLO, allergies=["milk"], weekly_servings={"meat": 3})
    r = client.put(f"/api/v1/profiles/{pid}", json=changed, headers=AUTH).json()
    assert r["profile"]["allergies"] == ["milk"] and r["allergy_notice"]
    assert len(client.get("/api/v1/profiles", headers=AUTH).json()) == 1
    assert client.delete(f"/api/v1/profiles/{pid}", headers=AUTH).status_code == 204


def test_own_protein_target_is_saved_and_changes_the_daily_target(client):
    created = setup_home(client)
    pid = created["profile"]["id"]
    assert created["profile"]["protein_g_per_kg"] is None
    default = float(created["targets"]["protein_g"])
    r = client.put(
        f"/api/v1/profiles/{pid}", json=dict(PABLO, protein_g_per_kg="1.2"), headers=AUTH
    ).json()
    assert Decimal(r["profile"]["protein_g_per_kg"]) == Decimal("1.2")
    assert float(r["targets"]["protein_g"]) < default
    again = client.get("/api/v1/profiles", headers=AUTH).json()[0]
    assert Decimal(again["profile"]["protein_g_per_kg"]) == Decimal("1.2")
    bad = client.put(
        f"/api/v1/profiles/{pid}", json=dict(PABLO, protein_g_per_kg="0.3"), headers=AUTH
    )
    assert bad.status_code == 422
    assert "protein_g_per_kg" in {d["field"] for d in bad.json()["error"]["details"]}


def test_validation_errors_list_the_fields(client):
    setup_home(client)
    r = client.post("/api/v1/profiles", json={"name": "X"}, headers=AUTH)
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"sex", "birth_date"} <= fields


def test_equipment(client):
    setup_home(client)
    assert client.get("/api/v1/equipment", headers=AUTH).json() is None
    body = {"hob_type": "ceramic", "microwave": True, "air_fryer": True}
    assert client.put("/api/v1/equipment", json=body, headers=AUTH).json()["air_fryer"] is True
    body["oven"] = True
    assert client.put("/api/v1/equipment", json=body, headers=AUTH).json()["oven"] is True


def test_products_search_patch_and_pantry(client, shop):
    setup_home(client)
    page = client.get("/api/v1/products", params={"q": "ri", "size": 1}, headers=AUTH).json()
    assert page["total"] >= 1 and len(page["items"]) == 1
    rice = page["items"][0]
    assert rice["product"]["name"] == "rice" and rice["unit_price_per"] == "kg"
    pid = rice["product"]["id"]
    r = client.patch(
        f"/api/v1/products/{pid}", json={"allergens": [], "category": "grains"}, headers=AUTH
    ).json()
    assert r["product"]["allergens"] == [] and r["product"]["allergens_source"] == "manual"
    assert r["product"]["category_source"] == "manual"

    item = client.post(
        "/api/v1/pantry", json={"product_id": pid, "amount": 500, "unit": "g"}, headers=AUTH
    ).json()
    assert client.get("/api/v1/pantry", headers=AUTH).json()["total"] == 1
    upd = client.put(
        f"/api/v1/pantry/{item['id']}",
        json={"product_id": pid, "amount": 200, "unit": "g"},
        headers=AUTH,
    ).json()
    assert Decimal(upd["amount"]) == 200
    assert client.delete(f"/api/v1/pantry/{item['id']}", headers=AUTH).status_code == 204
    assert (
        client.post(
            "/api/v1/pantry", json={"product_id": 999, "amount": 1, "unit": "g"}, headers=AUTH
        ).status_code
        == 404
    )


def test_optimise_endpoint(client, shop):
    setup_home(client)
    r = client.post("/api/v1/shopping/optimise", json={"store_id": "demo"}, headers=AUTH).json()
    assert r["result"]["status"] == "optimal" and r["budget_cents"] == 8000


def test_plan_generation_job_today_and_shopping_list(client, shop):
    setup_home(client)
    body = {"store_id": "demo", "schedule": {"week_start": MONDAY.isoformat(), "weekdays": [0, 1]}}
    accepted = client.post("/api/v1/plans", json=body, headers=AUTH)
    assert accepted.status_code == 202
    job = client.get(accepted.json()["status_url"], headers=AUTH).json()
    assert job["status"] == "done", job
    assert job["result"]["accepted"] is True
    plan_id = job["result"]["plan_id"]

    week = client.get("/api/v1/plans", params={"week": MONDAY.isoformat()}, headers=AUTH).json()
    assert week["plan"]["id"] == plan_id and len(week["meals"]) == 8
    meals = client.get("/api/v1/today", params={"day": MONDAY.isoformat()}, headers=AUTH).json()
    assert [m["slot"] for m in meals] == ["breakfast", "lunch", "snack", "dinner"]
    assert "Pablo" in meals[0]["portions"]

    shopping = client.get(f"/api/v1/plans/{plan_id}/shopping-list", headers=AUTH).json()
    assert shopping["total_cents"] > 0 and shopping["items"]

    again = client.post("/api/v1/plans", json=body, headers=AUTH)
    assert again.status_code == 409 and again.json()["error"]["code"] == "plan_exists"
    usage = client.get("/api/v1/llm/usage", headers=AUTH).json()
    assert usage[0]["task"] == "plan_week" and usage[0]["calls"] >= 1


def test_stores_and_unknown_job(client):
    ids = {s["id"] for s in client.get("/api/v1/stores", headers=AUTH).json()}
    assert {"open_prices", "mercadona"} <= ids
    assert client.get("/api/v1/jobs/nope", headers=AUTH).status_code == 404


def test_pantry_items_carry_name_and_category(client, shop):
    setup_home(client)
    rice = client.get("/api/v1/products", params={"q": "rice"}, headers=AUTH).json()["items"][0]
    pid = rice["product"]["id"]
    made = client.post(
        "/api/v1/pantry", json={"product_id": pid, "amount": 500, "unit": "g"}, headers=AUTH
    ).json()
    assert (made["name"], made["category"]) == ("rice", "grains")
    listed = client.get("/api/v1/pantry", headers=AUTH).json()["items"][0]
    assert (listed["name"], listed["category"]) == ("rice", "grains")


def test_shopping_items_can_be_ticked(client, shop):
    setup_home(client)
    body = {"store_id": "demo", "schedule": {"week_start": MONDAY.isoformat(), "weekdays": [0, 1]}}
    job = client.get(
        client.post("/api/v1/plans", json=body, headers=AUTH).json()["status_url"], headers=AUTH
    ).json()
    items = client.get(
        f"/api/v1/plans/{job['result']['plan_id']}/shopping-list", headers=AUTH
    ).json()["items"]
    first = items[0]
    assert first["checked"] is False
    ticked = client.patch(
        f"/api/v1/shopping-items/{first['id']}", json={"checked": True}, headers=AUTH
    )
    assert ticked.status_code == 200 and ticked.json()["checked"] is True
    assert (
        client.patch(
            "/api/v1/shopping-items/99999", json={"checked": True}, headers=AUTH
        ).status_code
        == 404
    )


def test_llm_settings_never_expose_keys(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-super-secret")
    r = client.get("/api/v1/settings/llm", headers=AUTH)
    assert r.status_code == 200
    assert "sk-super-secret" not in r.text
    data = r.json()
    assert {m["tier"] for m in data["models"]} == {"small", "large"}
    assert all(m["key_configured"] is True for m in data["models"] if m["provider"] == "deepseek")
    assert "spent_usd" in data


def test_catalog_stores_lists_stores_with_products(client, shop):
    stores = client.get("/api/v1/catalog/stores", headers=AUTH).json()
    assert stores == [{"store_id": "demo", "products": 9, "priced": 9}]
