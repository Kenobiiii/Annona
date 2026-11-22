# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tools through the registry, MCP round trips (in-memory client) and the HTTP transport."""

from datetime import date
from decimal import Decimal

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client import Client

from annona_core.domain import Household, UserProfile
from annona_core.llm import FakeLLM, Tier
from annona_server.api import create_app
from annona_server.db.engine import session_scope
from annona_server.db.repositories import HouseholdRepository, UserProfileRepository
from annona_server.jobs import InlineExecutor, JobRunner
from annona_server.llm import make_llm_client
from annona_server.llm.config import LLMSettings
from annona_server.mcp_server import build_server
from annona_server.tools import TOOLS

from .test_planner_db import even_split
from .test_recipes_db import recipe_answer

MONDAY = date(2026, 11, 23)
EXPECTED = {
    "get_profile",
    "get_pantry",
    "update_pantry",
    "search_products",
    "get_prices",
    "build_weekly_plan",
    "get_plan",
    "recipe_of_the_day",
    "cook_meal",
    "shopping_list",
}


@pytest.fixture
def home(engine):
    with session_scope(engine) as s:
        h = HouseholdRepository(s).add(Household(name="Casa", weekly_budget_cents=8000))
        UserProfileRepository(s).add(
            UserProfile(
                household_id=h.id,
                name="Pablo",
                sex="male",
                birth_date=date(2005, 1, 1),
                height_cm=Decimal(185),
                weight_kg=Decimal(85),
                activity="active",
                allergies_confirmed=True,
                weekly_servings={"meat": 1},
            )
        )


def fake_factory(session):
    return make_llm_client(
        session,
        settings=LLMSettings(models={Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}),
        backend=FakeLLM(
            responder=lambda r: recipe_answer(r) if r.task == "recipe_of_the_day" else even_split(r)
        ),
    )


def server(engine):
    return build_server(
        engine, llm_factory=fake_factory, runner=JobRunner(engine, InlineExecutor())
    )


def call(engine, name, args=None):
    async def go():
        async with Client(server(engine)) as client:
            return await client.call_tool(name, args or {})

    return anyio.run(go)


def test_registry_has_the_ten_tools_with_short_descriptions():
    assert set(TOOLS) == EXPECTED
    for tool in TOOLS.values():
        assert len(tool.description) <= 130, tool.name  # sent to the model on every turn
    writers = {n for n, t in TOOLS.items() if not t.read_only}
    assert writers == {"update_pantry", "build_weekly_plan", "cook_meal"}


def test_mcp_lists_tools_with_annotations_and_lean_schemas(engine):
    async def go():
        async with Client(server(engine)) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in anyio.run(go)}
    assert set(tools) == EXPECTED
    assert tools["get_profile"].annotations.read_only_hint is True
    assert tools["update_pantry"].annotations.destructive_hint is True
    assert '"title"' not in str(tools["search_products"].input_schema).replace("'", '"')
    assert tools["get_plan"].output_schema  # structured output


def test_round_trip_profile_search_and_pantry(engine, home, shop):
    profile = call(engine, "get_profile").structured_content
    assert profile["members"][0]["name"] == "Pablo" and profile["members"][0]["daily_kcal"]

    found = call(engine, "search_products", {"query": "rice"}).structured_content
    rice = found["items"][0]
    assert rice["unit_price"].endswith("/kg") and rice.get("per_100") is None  # concise
    full = call(engine, "search_products", {"query": "rice", "detail": "full"}).structured_content
    assert full["items"][0]["per_100"]["kcal"]

    changed = call(
        engine,
        "update_pantry",
        {"changes": [{"product_id": rice["id"], "mode": "add", "amount": 500, "unit": "g"}]},
    ).structured_content
    assert Decimal(changed["items"][0]["amount"]) == 500
    pantry = call(engine, "get_pantry").structured_content
    assert pantry["total"] == 1
    prices = call(engine, "get_prices", {"product_ids": [rice["id"]]}).structured_content
    assert prices["items"][0]["latest"]["price"]


def test_plan_workflow_through_mcp(engine, home, shop):
    week = MONDAY.isoformat()
    assert call(engine, "get_plan", {"week_start": week}).structured_content["status"] == "none"
    started = call(
        engine, "build_weekly_plan", {"week_start": week, "store_id": "demo", "weekdays": [0]}
    ).structured_content
    assert started["status"] == "started"
    plan = call(engine, "get_plan", {"week_start": week}).structured_content
    assert plan["status"] == "ready", plan
    if plan["status"] == "ready":
        assert len(plan["meals"]) == 4 and plan["meals"][0].get("ingredients") is None
        today = call(engine, "recipe_of_the_day", {"day": week}).structured_content
        assert today["member"] == "Pablo" and today["meals"][0]["ingredients"]
        shopping = call(engine, "shopping_list", {"week_start": week}).structured_content
        assert shopping["items"] and shopping["total"]
        lunch = call(engine, "recipe_of_the_day", {"day": week, "slot": "lunch"}).structured_content
        assert (
            lunch["recipe"]["steps"][0].startswith("1. Cocina ")
            and lunch["recipe"]["cooked"] is False
        )
        cook = {"day": week, "slot": "lunch"}
        preview = call(engine, "cook_meal", cook).structured_content
        assert preview["status"] == "preview" and "confirm=true" in preview["message"]
        done = call(engine, "cook_meal", {**cook, "confirm": True}).structured_content
        assert done["status"] == "cooked"
        assert call(engine, "cook_meal", cook).structured_content["status"] == "already_cooked"
    again = call(engine, "build_weekly_plan", {"week_start": week, "store_id": "demo"})
    if plan["status"] == "ready":
        assert again.structured_content["status"] == "exists"


def test_errors_tell_what_to_do(engine, home):
    result = call(engine, "recipe_of_the_day", {"day": "2026-11-23", "member": "Nobody"})
    assert result.is_error and "members: Pablo" in str(result.content)
    result = call(engine, "build_weekly_plan", {"week_start": "2026-11-24", "store_id": "demo"})
    assert result.is_error and "Monday" in str(result.content)


def test_http_transport_needs_the_token(engine):
    app = create_app(engine=engine, token="t", llm_factory=fake_factory)
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    with TestClient(app) as c:
        assert c.post("/mcp/", json=init, headers=headers).status_code == 401
        for path in ("/mcp", "/mcp/"):  # both work, no redirect
            r = c.post(path, json=init, headers=headers | {"Authorization": "Bearer t"})
            assert r.status_code == 200 and r.json()["result"]["serverInfo"]["name"] == "annona"
