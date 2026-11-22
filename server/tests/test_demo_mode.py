# SPDX-License-Identifier: AGPL-3.0-or-later
"""Demo mode: an invented store and a scripted AI (ANNONA_FAKE_LLM), end to end over HTTP."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from annona_server.api import create_app
from annona_server.db import repositories as r
from annona_server.demo import CATALOGUE, STORE, load_demo_store
from annona_server.jobs import InlineExecutor, JobRunner

AUTH = {"Authorization": "Bearer t"}
MONDAY = date(2026, 11, 23)
PHOTO = b"\x89PNG\r\n\x1a\n" + b"synthetic"


def test_the_demo_store_is_loaded_once(session):
    assert load_demo_store(session) == len(CATALOGUE)
    assert load_demo_store(session) == 0  # idempotent
    products = r.SqlProductRepository(session).list(store_id=STORE)
    assert len(products) == len(CATALOGUE)
    prices = r.SqlPriceRepository(session)
    assert all(prices.latest(p.id, STORE).currency == "EUR" for p in products)


@pytest.fixture
def client(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("ANNONA_FAKE_LLM", "1")
    monkeypatch.setenv("ANNONA_RECEIPTS_DIR", str(tmp_path / "photos"))
    app = create_app(engine=engine, runner=JobRunner(engine, InlineExecutor()), token="t")
    with TestClient(app) as c:
        c.headers.update(AUTH)
        yield c


def test_a_fresh_install_can_plan_a_week_without_a_key_or_a_real_store(client, session, engine):
    """The README path, minus the phone: household -> people -> kitchen -> demo store -> menu."""
    assert (
        client.put(
            "/api/v1/household", json={"name": "Casa", "weekly_budget_cents": 8000}
        ).status_code
        == 200
    )
    person = client.post(
        "/api/v1/profiles",
        json={
            "name": "Sam",
            "sex": "female",
            "birth_date": "1990-01-01",
            "height_cm": 165,
            "weight_kg": 60,
            "activity": "active",
            "allergies_confirmed": True,
        },
    )
    assert person.status_code == 201, person.text
    assert (
        client.put("/api/v1/equipment", json={"hob_type": "ceramic", "oven": True}).status_code
        == 200
    )
    with session.bind.connect() as conn:  # the seed command, as the README runs it
        from sqlmodel import Session

        with Session(conn) as s:
            load_demo_store(s)
            s.commit()

    stores = client.get("/api/v1/catalog/stores").json()
    assert STORE in {s["store_id"] for s in stores}

    body = {
        "store_id": STORE,
        "schedule": {"week_start": MONDAY.isoformat(), "weekdays": [0, 1, 2]},
    }
    started = client.post("/api/v1/plans", json=body)
    assert started.status_code == 202
    job = client.get(started.json()["status_url"]).json()
    assert job["status"] == "done" and job["result"]["accepted"] is True, job
    plan_id = job["result"]["plan_id"]

    week = client.get("/api/v1/plans", params={"week": MONDAY.isoformat()}).json()
    assert week["plan"]["id"] == plan_id and len(week["meals"]) == 12  # 3 days x 4 meals
    shopping = client.get(f"/api/v1/plans/{plan_id}/shopping-list").json()
    assert shopping["store_id"] == STORE and shopping["total_cents"] > 0 and shopping["items"]

    recipe = client.post("/api/v1/meals/recipe", json={"day": MONDAY.isoformat(), "slot": "lunch"})
    assert recipe.status_code == 200 and recipe.json()["steps"]


def test_the_chat_says_it_needs_a_real_ai_in_demo_mode(client):
    client.put("/api/v1/household", json={"name": "Casa", "weekly_budget_cents": 8000})
    response = client.post("/api/v1/chat", json={"message": "hola"})
    assert response.status_code == 200
    assert "Modo demo" in response.text and "event: done" in response.text


def test_what_needs_a_real_model_is_refused_clearly_not_with_a_crash(client):
    client.put("/api/v1/household", json={"name": "Casa", "weekly_budget_cents": 8000})
    response = client.post("/api/v1/receipts", files={"file": ("t.png", PHOTO, "image/png")})
    assert response.status_code == 502, response.text
    error = response.json()["error"]
    assert error["code"] == "ai_error" and "ANNONA_FAKE_LLM" in error["message"]
