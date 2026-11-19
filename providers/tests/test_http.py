# SPDX-License-Identifier: AGPL-3.0-or-later
import httpx
import pytest

from annona_providers.http import DEFAULT_USER_AGENT, PoliteTransport, RobotsDisallowedError

ROBOTS = "User-agent: *\nDisallow: /api\nAllow: /\n"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def server(robots_status: int = 200, robots: str = ROBOTS):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(robots_status, text=robots)
        return httpx.Response(200, json={"path": request.url.path})

    return httpx.MockTransport(handler), calls


def client(inner, **kwargs) -> tuple[httpx.Client, FakeClock]:
    clock = FakeClock()
    transport = PoliteTransport(inner=inner, clock=clock, sleep=clock.sleep, **kwargs)
    return httpx.Client(transport=transport), clock


def test_identifies_itself():
    inner, calls = server()
    c, _ = client(inner)
    c.get("https://shop.test/products")
    assert all(r.headers["User-Agent"] == DEFAULT_USER_AGENT for r in calls)
    assert "Annona/" in DEFAULT_USER_AGENT and "github.com" in DEFAULT_USER_AGENT


def test_refuses_urls_disallowed_by_robots():
    inner, calls = server()
    c, _ = client(inner)
    with pytest.raises(RobotsDisallowedError):
        c.get("https://shop.test/api/products/1")
    assert [r.url.path for r in calls] == ["/robots.txt"]  # the API was never called


def test_opt_in_exception_allows_and_logs(caplog):
    inner, calls = server()
    c, _ = client(inner, robots_exception=True)
    with caplog.at_level("INFO"):
        assert c.get("https://shop.test/api/products/1").status_code == 200
    assert "opt-in personal-use" in caplog.text


@pytest.mark.parametrize(("status", "allowed"), [(404, True), (403, False), (401, False)])
def test_missing_or_forbidden_robots(status, allowed):
    inner, _ = server(robots_status=status)
    c, _ = client(inner)
    if allowed:
        assert c.get("https://shop.test/api/x").status_code == 200
    else:
        with pytest.raises(RobotsDisallowedError):
            c.get("https://shop.test/anything")


def test_waits_between_requests_to_the_same_host():
    inner, _ = server()
    c, clock = client(inner, min_interval=2.0, cache_ttl=0)
    c.get("https://shop.test/a")  # robots.txt + /a
    c.get("https://shop.test/b")
    # robots.txt at t=1000, then /a must wait 2 s, then /b another 2 s
    assert clock.slept == [2.0, 2.0]


def test_caches_successful_responses():
    inner, calls = server()
    c, clock = client(inner, cache_ttl=60)
    c.get("https://shop.test/a")
    c.get("https://shop.test/a")
    assert [r.url.path for r in calls] == ["/robots.txt", "/a"]
    clock.now += 61
    c.get("https://shop.test/a")
    assert [r.url.path for r in calls][-1] == "/a" and len(calls) == 3


def test_does_not_cache_writes():
    inner, calls = server()
    c, _ = client(inner)
    c.put("https://shop.test/x", json={})
    c.put("https://shop.test/x", json={})
    assert len([r for r in calls if r.method == "PUT"]) == 2
