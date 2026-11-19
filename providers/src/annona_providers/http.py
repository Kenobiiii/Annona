# SPDX-License-Identifier: AGPL-3.0-or-later
"""A polite HTTP layer shared by all providers.

:class:`PoliteTransport` wraps any ``httpx`` transport and

* identifies the client with a descriptive User-Agent;
* checks ``robots.txt`` before every request and refuses disallowed URLs, unless the provider is an
  opt-in, personal-use plugin (``robots_exception=True``; see CLAUDE.md), in which case the
  exception is logged;
* waits a minimum interval between requests to the same host;
* caches successful GET/POST responses in memory for ``cache_ttl`` seconds.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from . import __version__
from .base import ProviderError

log = logging.getLogger(__name__)

PROJECT_URL = "https://github.com/Kenobiiii/Annona"
DEFAULT_USER_AGENT = f"Annona/{__version__} (+{PROJECT_URL})"


def user_agent() -> str:
    return os.environ.get("ANNONA_HTTP_USER_AGENT") or DEFAULT_USER_AGENT


class RobotsDisallowedError(ProviderError):
    """robots.txt forbids this URL for our User-Agent."""


@dataclass
class _CacheEntry:
    expires: float
    status: int
    headers: list[tuple[str, str]]
    content: bytes


@dataclass
class PoliteTransport(httpx.BaseTransport):
    inner: httpx.BaseTransport = field(default_factory=httpx.HTTPTransport)
    min_interval: float = 1.0  # seconds between requests to one host
    cache_ttl: float = 3600.0
    robots_exception: bool = False
    agent: str = field(default_factory=user_agent)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _robots: dict[str, urllib.robotparser.RobotFileParser] = field(default_factory=dict)
    _last_request: dict[str, float] = field(default_factory=dict)
    _cache: dict[str, _CacheEntry] = field(default_factory=dict)

    # -- httpx.BaseTransport --
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.headers["User-Agent"] = self.agent
        self._check_robots(request.url)
        key = self._cache_key(request)
        if key is not None:
            cached = self._cache.get(key)
            if cached is not None and cached.expires > self.clock():
                return httpx.Response(
                    cached.status, headers=cached.headers, content=cached.content, request=request
                )
        response = self._send(request)
        if key is not None and response.status_code == 200:
            content = response.read()
            headers = decoded_headers(response)
            self._cache[key] = _CacheEntry(self.clock() + self.cache_ttl, 200, headers, content)
            return httpx.Response(200, headers=headers, content=content, request=request)
        return response

    def close(self) -> None:
        self.inner.close()

    # -- internals --
    def _send(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = self.clock()
        return self.inner.handle_request(request)

    def _check_robots(self, url: httpx.URL) -> None:
        if url.path == "/robots.txt":
            return
        origin = f"{url.scheme}://{url.netloc.decode()}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = self._load_robots(origin)
            self._robots[origin] = parser
        if parser.can_fetch(self.agent, str(url)):
            return
        if self.robots_exception:
            log.info("robots.txt disallows %s; allowed as an opt-in personal-use request", url)
            return
        raise RobotsDisallowedError(f"robots.txt disallows {url}")

    def _load_robots(self, origin: str) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser()
        request = httpx.Request("GET", f"{origin}/robots.txt", headers={"User-Agent": self.agent})
        try:
            response = self._send(request)
            response.read()
        except httpx.HTTPError:
            # Unreachable robots.txt: be conservative and allow nothing.
            parser.disallow_all = True
            return parser
        if response.status_code in (401, 403):
            parser.disallow_all = True
        elif response.status_code >= 400:
            parser.allow_all = True  # no robots.txt: everything is allowed
        else:
            parser.parse(response.text.splitlines())
        return parser

    def _cache_key(self, request: httpx.Request) -> str | None:
        if request.method not in ("GET", "POST") or self.cache_ttl <= 0:
            return None
        body = request.read()
        digest = hashlib.sha256(body).hexdigest() if body else ""
        return f"{request.method} {request.url} {digest}"


def decoded_headers(response: httpx.Response) -> list[tuple[str, str]]:
    """Headers for a rebuilt response whose body was already read (and decompressed)."""
    drop = {"content-encoding", "content-length", "transfer-encoding"}
    return [(k, v) for k, v in response.headers.multi_items() if k.lower() not in drop]


def polite_client(**kwargs: object) -> httpx.Client:
    """An ``httpx.Client`` using :class:`PoliteTransport` (kwargs go to the transport)."""
    return httpx.Client(transport=PoliteTransport(**kwargs), timeout=20.0)  # type: ignore[arg-type]
