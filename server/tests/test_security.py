# SPDX-License-Identifier: AGPL-3.0-or-later
"""Failed-token throttle, security headers and weak-token warning."""

import logging

from fastapi.testclient import TestClient

from annona_server.api import create_app
from annona_server.api.throttle import FailureThrottle

TOKEN = "t" * 32


def make_client(engine, token=TOKEN):
    return TestClient(create_app(engine=engine, token=token))


def test_throttle_blocks_after_limit_and_recovers() -> None:
    now = [0.0]
    t = FailureThrottle(limit=3, window_s=60, clock=lambda: now[0])
    for _ in range(3):
        assert not t.blocked("a")
        t.record("a")
    assert t.blocked("a")
    assert not t.blocked("b")
    now[0] = 61
    assert not t.blocked("a")


def test_rest_blocks_guessing_even_with_right_token_afterwards(engine) -> None:
    with make_client(engine) as c:
        for _ in range(10):
            assert c.get("/api/v1/stores", headers={"Authorization": "Bearer x"}).status_code == 401
        right = {"Authorization": f"Bearer {TOKEN}"}
        r = c.get("/api/v1/stores", headers=right)
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "too_many_attempts"


def test_mcp_shares_the_throttle(engine) -> None:
    with make_client(engine) as c:
        for _ in range(10):
            assert c.post("/mcp/", headers={"Authorization": "Bearer x"}).status_code == 401
        assert (
            c.get("/api/v1/stores", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 429
        )
        assert c.post("/mcp/", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 429


def test_good_token_resets_the_count(engine) -> None:
    with make_client(engine) as c:
        for _ in range(9):
            c.get("/api/v1/stores", headers={"Authorization": "Bearer x"})
        assert (
            c.get("/api/v1/stores", headers={"Authorization": f"Bearer {TOKEN}"}).status_code != 401
        )
        for _ in range(9):
            assert c.get("/api/v1/stores", headers={"Authorization": "Bearer x"}).status_code == 401


def test_security_headers_on_every_response(engine) -> None:
    with make_client(engine) as c:
        r = c.get("/health")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "no-referrer"


def test_short_token_warns(engine, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="annona"):
        create_app(engine=engine, token="short")
    assert "shorter than" in caplog.text


def test_long_token_does_not_warn(engine, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="annona"):
        create_app(engine=engine, token=TOKEN)
    assert "shorter than" not in caplog.text
