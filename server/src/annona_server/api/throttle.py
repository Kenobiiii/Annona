# SPDX-License-Identifier: AGPL-3.0-or-later
"""Slow down guessing of the API token, and add safe default response headers.

Failed token attempts are counted per client address in a sliding window; past the limit the address
is refused (HTTP 429) until the window passes, even with the right token, so a guess cannot be
confirmed by speed. In memory, per process: enough for a self-hosted server with one user.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class FailureThrottle:
    def __init__(
        self,
        limit: int = 10,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        failures = self._failures[key]
        while failures and self.clock() - failures[0] > self.window_s:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)
            return deque()
        return failures

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.limit

    def record(self, key: str) -> None:
        self._prune(key)
        self._failures[key].append(self.clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
]


class SecurityHeaders:
    """Adds conservative headers to every response (never overrides one already set)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = [
                    *message.get("headers", []),
                    *((k, v) for k, v in _HEADERS if k not in present),
                ]
            await send(message)

        await self.app(scope, receive, with_headers)
