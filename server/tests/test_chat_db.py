# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chat agent end to end over HTTP with a scripted model. SYNTHETIC data. No network."""

import json
from datetime import date
from decimal import Decimal

import pytest

from annona_core.agent import FakeChatModel, ModelReply, ToolCall
from annona_core.llm import Tier
from annona_server.db import repositories as r
from annona_server.planner.recipes import load_meal

from .test_optimize_db import household  # noqa: F401  (fixture)
from .test_planner_db import kitchen  # noqa: F401  (fixture)
from .test_shopping_db import world  # noqa: F401  (fixtures)
from .test_swap_db import DINNER, TUESDAY, replacement


def reply(text="", calls=(), out=10):
    return ModelReply(text=text, tool_calls=list(calls), input_tokens=100, output_tokens=out)


def tool(name, args=None, id_=None):
    return ToolCall(id=id_ or f"c-{name}", name=name, arguments=args or {})


class Factory:
    """The app's chat-model factory: hands out a scripted model and records the tier asked for."""

    def __init__(self, *replies):
        self.model = FakeChatModel(list(replies))
        self.tiers: list[Tier] = []

    def __call__(self, session, tier):
        self.tiers.append(tier)
        return self.model


@pytest.fixture
def make_api(engine, world, session):  # noqa: F811
    from fastapi.testclient import TestClient

    from annona_server.api import create_app

    session.commit()
    clients = []

    def build(factory):
        app = create_app(
            engine=engine,
            token="t",
            llm_factory=lambda s: replacement(),  # what swap_meal asks the large model for
            chat_model_factory=factory,
        )
        client = TestClient(app)
        client.__enter__()
        client.headers["Authorization"] = "Bearer t"
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def sse(response):
    events = []
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def kinds(events):
    return [name for name, _ in events]


def chat(client, message, **extra):
    return client.post("/api/v1/chat", json={"message": message, **extra})


def test_a_question_streams_text_and_shows_what_was_looked_up(make_api):
    factory = Factory(reply("", [tool("get_pantry")]), reply("Tu despensa está vacía."))
    response = chat(make_api(factory), "¿qué tengo en casa?")
    assert response.status_code == 200 and response.headers["content-type"].startswith(
        "text/event-stream"
    )
    events = sse(response)
    assert (
        kinds(events)[0] == "tool_start"
        and "tool_end" in kinds(events)
        and kinds(events)[-1] == "done"
    )
    text = "".join(d["delta"] for n, d in events if n == "text")
    assert text == "Tu despensa está vacía."
    done = events[-1][1]
    assert done["stopped"] == "answered" and done["tool_calls"] == 1 and done["proposals"] == []
    assert done["input_tokens"] == 200


def test_the_model_never_sees_the_confirm_argument(make_api):
    factory = Factory(reply("hola"))
    chat(make_api(factory), "hola")
    _, _, specs = factory.model.calls[0]
    names = {s.name for s in specs}
    assert {"swap_meal", "cook_meal", "update_pantry", "get_plan"} <= names
    cook = next(s for s in specs if s.name == "cook_meal")
    assert (
        "confirm" not in cook.parameters["properties"] and "slot" in cook.parameters["properties"]
    )


def test_swap_thursday_dinner_without_oven_needs_confirmation(make_api, session, world):  # noqa: F811
    """Acceptance: a swap request produces a proposal; the plan changes only after confirming."""
    home = world["household"]
    before = load_meal(session, home.id, TUESDAY, DINNER)
    swap = tool(
        "swap_meal",
        {
            "day": "2026-11-24",
            "slot": "dinner",
            "request": "algo sin horno",
            "avoid_appliances": ["oven"],
        },
    )
    client = make_api(
        Factory(reply("Busco algo.", [swap]), reply("Te propongo un plato nuevo; confírmalo."))
    )
    events = sse(chat(client, "cambia la cena del martes por algo sin horno"))

    actions = [d for n, d in events if n == "action"]
    assert len(actions) == 1 and "Pasta rápida" in actions[0]["summary"]
    assert actions[0]["summary"].startswith("Cambiar la cena del 24/11")
    assert events[-1][1]["proposals"] == [actions[0]["id"]]
    # Proposed only: the menu has not changed.
    assert load_meal(session, home.id, TUESDAY, DINNER).recipe.title == before.recipe.title
    pending = client.get("/api/v1/chat/actions").json()
    assert [(p["id"], p["status"]) for p in pending] == [(actions[0]["id"], "pending")]

    done = client.post(f"/api/v1/chat/actions/{actions[0]['id']}/confirm")
    assert done.status_code == 200 and done.json()["status"] == "confirmed"
    session.expire_all()
    assert load_meal(session, home.id, TUESDAY, DINNER).recipe.title == "Pasta rápida"
    assert client.get("/api/v1/chat/actions").json() == []
    again = client.post(f"/api/v1/chat/actions/{actions[0]['id']}/confirm")
    assert again.status_code == 409 and again.json()["error"]["code"] == "action_closed"


def test_a_pantry_change_is_a_proposal_until_the_person_confirms(make_api, session, world):  # noqa: F811
    home = world["household"]
    rice = next(iter(r.SqlProductRepository(session).list(store_id="demo")))
    args = {"changes": [{"product_id": rice.id, "mode": "add", "amount": 500, "unit": "g"}]}
    client = make_api(Factory(reply("", [tool("update_pantry", args)]), reply("Propuesto.")))
    events = sse(chat(client, "apunta 500 g de arroz"))
    [action] = [d for n, d in events if n == "action"]
    assert (
        action["summary"].startswith("Despensa: añadir 500 g de") and rice.name in action["summary"]
    )
    assert client.get("/api/v1/pantry").json()["items"] == []  # nothing yet

    assert (
        client.post(f"/api/v1/chat/actions/{action['id']}/confirm").json()["status"] == "confirmed"
    )
    items = client.get("/api/v1/pantry").json()["items"]
    assert [(i["product_id"], Decimal(i["amount"])) for i in items] == [(rice.id, 500)]
    assert home is not None


def test_cancelling_changes_nothing_and_cannot_be_undone_twice(make_api):
    args = {"changes": [{"product_id": 1, "mode": "add", "amount": 100, "unit": "g"}]}
    client = make_api(Factory(reply("", [tool("update_pantry", args)]), reply("ok")))
    [action] = [d for n, d in sse(chat(client, "añade")) if n == "action"]
    cancelled = client.post(f"/api/v1/chat/actions/{action['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert client.get("/api/v1/pantry").json()["items"] == []
    assert client.post(f"/api/v1/chat/actions/{action['id']}/confirm").status_code == 409
    assert client.post(f"/api/v1/chat/actions/{action['id']}/cancel").status_code == 409
    assert client.post("/api/v1/chat/actions/999/confirm").status_code == 404


def test_a_model_that_tries_to_confirm_by_itself_only_proposes(make_api, session, world):  # noqa: F811
    """The model passes confirm=true to cook_meal: it is ignored; the meal is not cooked."""
    home = world["household"]
    cook = tool("cook_meal", {"day": "2026-11-24", "slot": "dinner", "confirm": True})
    client = make_api(Factory(reply("", [cook]), reply("Pendiente de tu confirmación.")))
    events = sse(chat(client, "cocina la cena del martes"))
    [action] = [d for n, d in events if n == "action"]
    assert action["summary"].startswith("Marcar como cocinado la cena del 24/11")
    assert all(row.cooked_at is None for row in load_meal(session, home.id, TUESDAY, DINNER).rows)
    stored = client.get("/api/v1/chat/actions").json()
    assert stored[0]["tool"] == "cook_meal"


def test_a_failing_proposal_is_reported_as_failed(make_api):
    args = {"changes": [{"product_id": 99999, "mode": "add", "amount": 100, "unit": "g"}]}
    client = make_api(Factory(reply("", [tool("update_pantry", args)]), reply("ok")))
    [action] = [d for n, d in sse(chat(client, "añade")) if n == "action"]
    result = client.post(f"/api/v1/chat/actions/{action['id']}/confirm").json()
    assert result["status"] == "failed" and "99999" in result["result"]["error"]


def test_the_number_of_tool_rounds_is_capped_over_http(make_api):
    model = FakeChatModel(
        responder=lambda m, t: reply("", [tool("get_pantry")]) if t else reply("Hasta aquí.")
    )
    factory = Factory()
    factory.model = model
    events = sse(chat(make_api(factory), "dame vueltas"))
    assert "notice" in kinds(events)
    done = events[-1][1]
    assert (
        done["stopped"] == "max_iterations" and done["iterations"] == 6 and done["tool_calls"] == 5
    )


def test_a_bigger_model_is_used_only_when_asked_and_the_history_is_windowed(make_api):
    factory = Factory(reply("a"), reply("b"))
    client = make_api(factory)
    chat(client, "uno")
    chat(
        client, "dos", tier="large", history=[{"role": "user", "text": f"m{i}"} for i in range(30)]
    )
    assert factory.tiers == [Tier.SMALL, Tier.LARGE]
    sent = factory.model.calls[1][1]
    assert sent[-1].text == "dos" and len(sent) <= 11 and sent[0].role == "user"


def test_bad_requests_are_refused_before_any_model_call(make_api):
    factory = Factory(reply("nope"))
    client = make_api(factory)
    assert chat(client, "").status_code == 422
    assert chat(client, "x" * 2001).status_code == 422
    assert chat(client, "hola", tier="huge").status_code == 422
    assert (
        client.post(
            "/api/v1/chat", json={"message": "x", "history": [{"role": "tool", "text": "t"}]}
        ).status_code
        == 422
    )
    assert factory.model.calls == []


def test_a_model_error_ends_the_stream_with_an_error_event(make_api):
    def boom(messages, tools):
        raise RuntimeError("provider unavailable")

    factory = Factory()
    factory.model = FakeChatModel(responder=boom)
    events = sse(chat(make_api(factory), "hola"))
    assert kinds(events) == ["error"] and "provider unavailable" in events[0][1]["message"]
    assert date.today() is not None


def test_the_same_change_is_never_queued_twice(make_api):
    """Found by the agent eval: after 'yes, do it' the model proposed the change a second time."""
    args = {"changes": [{"product_id": 1, "mode": "add", "amount": 500, "unit": "g"}]}
    factory = Factory(
        reply("", [tool("update_pantry", args)]),
        reply("Propuesto."),
        reply("", [tool("update_pantry", args, id_="again")]),
        reply("Confírmalo en la app."),
    )
    client = make_api(factory)
    first = sse(chat(client, "apunta 500 g de arroz"))
    second = sse(chat(client, "sí, hazlo"))
    assert [n for n, _ in first].count("action") == 1
    assert "action" not in kinds(second)  # nothing new to confirm
    pending = client.get("/api/v1/chat/actions").json()
    assert len(pending) == 1  # confirming "both" could not double the amount
    told = [m for m in factory.model.calls[3][1] if m.role == "tool"][-1].text
    assert "already pending" in told and "Do not propose it again" in told
