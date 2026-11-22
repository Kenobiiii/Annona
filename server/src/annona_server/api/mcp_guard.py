# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bearer-token check in front of the mounted MCP app (same token as the REST API)."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send


class BearerGuard:
    def __init__(self, app: ASGIApp, token: Callable[[], str], throttle: Any = None) -> None:
        self.app, self.token, self.throttle = app, token, throttle

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        expected = self.token()
        who = (scope.get("client") or ("unknown", 0))[0]
        if self.throttle is not None and self.throttle.blocked(who):
            await _reply(send, 429, "too_many_attempts", "too many wrong tokens: wait a minute")
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        scheme, _, given = headers.get("authorization", "").partition(" ")
        if (
            expected
            and scheme.lower() == "bearer"
            and secrets.compare_digest(given.strip(), expected)
        ):
            if self.throttle is not None:
                self.throttle.reset(who)
            await self.app(scope, receive, send)
            return
        if self.throttle is not None and expected:
            self.throttle.record(who)
        code, status = ("not_configured", 503) if not expected else ("unauthorized", 401)
        await _reply(send, status, code, "bearer token required")


async def _reply(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class McpPathAlias:
    """Serve ``/mcp`` like ``/mcp/`` (no redirect: some clients drop headers on redirects)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = dict(scope, path="/mcp/", raw_path=b"/mcp/")
        await self.app(scope, receive, send)
