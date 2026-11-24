# SPDX-License-Identifier: AGPL-3.0-or-later
"""Using a store plugin from the app. The store is a SYNTHETIC stand-in (no network, invented
products and prices): it only exercises the connection rules, the search and the adding."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from annona_core.domain import Unit
from annona_providers.base import ProviderError, ProviderPrice, ProviderProduct
from annona_providers.mercadona import MercadonaProvider
from annona_server.api import create_app
from annona_server.jobs import InlineExecutor, JobRunner
from annona_server.stores import StoreAccess

from .test_api import AUTH, TOKEN, setup_home

# SYNTHETIC catalogue.
ITEMS = {
    "111": ProviderProduct(
        store_sku="111", name="Tomate triturado", brand="Marca", package_amount=Decimal(400),
        package_unit=Unit.G,
    ),
    "222": ProviderProduct(store_sku="222", name="Tomate frito", brand="Marca"),
}  # fmt: skip


class FakeStore:
    info = MercadonaProvider.info

    def __init__(self, config: dict[str, str], calls: list[tuple[str, str]]) -> None:
        if config.get("postal_code") == "00000":
            raise ProviderError("unknown postal code")
        self.config, self.calls = config, calls
        self.warehouse = "W1"

    @property
    def store_id(self) -> str:
        return "mercadona"

    def search(self, query: str, limit: int = 20):
        self.calls.append(("search", query))
        return [i for i in ITEMS.values() if query.casefold() in i.name.casefold()][:limit]

    def get_product(self, sku: str):
        self.calls.append(("product", sku))
        return ITEMS.get(sku)

    def get_prices(self, skus):
        now = datetime.now(UTC)
        return [
            ProviderPrice(store_sku=s, amount_cents=55, currency="EUR", observed_at=now)
            for s in skus
        ]

    def iter_catalog(self):
        raise AssertionError("never downloads a catalogue")

    def close(self) -> None:
        pass


@pytest.fixture
def calls():
    return []


@pytest.fixture
def client(engine, calls):
    configs: list[dict[str, str]] = []

    def factory(store_id: str, config: dict[str, str]):
        assert store_id == "mercadona"
        configs.append(config)
        return FakeStore(config, calls)

    app = create_app(
        engine=engine,
        runner=JobRunner(engine, InlineExecutor()),
        token=TOKEN,
        store_access=StoreAccess(factory),
        off_factory=lambda session: None,
    )
    with TestClient(app) as c:
        c.configs = configs  # type: ignore[attr-defined]
        setup_home(c)
        yield c


URL = "/api/v1/stores/mercadona"


def connect(client, **body):
    return client.put(f"{URL}/connection", json=body, headers=AUTH)


def test_nothing_reaches_an_opt_in_store_before_its_notice_is_accepted(client, calls):
    state = client.get(f"{URL}/connection", headers=AUTH).json()
    assert state["ready"] is False and state["notice"] and state["opt_in"] is True
    r = client.get(f"{URL}/search", params={"q": "tomate"}, headers=AUTH)
    assert r.status_code == 409 and r.json()["error"]["code"] == "notice_required"
    r = connect(client, postal_code="29003")  # no acceptance
    assert r.status_code == 409 and r.json()["error"]["code"] == "notice_required"
    assert calls == [] and client.configs == []


def test_a_postal_code_is_needed_and_resolved_once(client):
    r = connect(client, accept_notice=True)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_connected"
    r = connect(client, accept_notice=True, postal_code=" 29003 ")
    assert r.status_code == 200
    state = r.json()
    assert state["ready"] is True and state["postal_code"] == "29003"
    assert state["notice_accepted_at"] is not None
    assert client.configs == [{"postal_code": "29003"}]
    # Same postal code again: no new request; the acceptance is kept.
    assert connect(client, postal_code="29003").json()["notice_accepted_at"] is not None
    assert client.configs == [{"postal_code": "29003"}]


def test_an_unknown_postal_code_is_a_clear_error(client):
    r = connect(client, accept_notice=True, postal_code="00000")
    assert r.status_code == 502 and r.json()["error"]["code"] == "store_error"
    assert client.get(f"{URL}/connection", headers=AUTH).json()["ready"] is False


def test_search_is_small_cached_and_marks_stored_products(client, calls):
    connect(client, accept_notice=True, postal_code="29003")
    found = client.get(f"{URL}/search", params={"q": "Tomate"}, headers=AUTH).json()
    assert [f["name"] for f in found] == ["Tomate triturado", "Tomate frito"]
    assert found[0]["package_amount"] == "400" and found[0]["product_id"] is None
    client.get(f"{URL}/search", params={"q": "  tomate "}, headers=AUTH)
    assert calls == [("search", "Tomate")]  # the second one came from the cache
    assert client.get(f"{URL}/search", params={"q": "t"}, headers=AUTH).json() == []


def test_adding_one_product_stores_it_with_its_price(client):
    connect(client, accept_notice=True, postal_code="29003")
    r = client.post(f"{URL}/products", json={"store_sku": "111"}, headers=AUTH)
    assert r.status_code == 201
    out = r.json()
    assert out["product"]["name"] == "Tomate triturado"
    assert out["product"]["store_id"] == "mercadona" and out["product"]["store_sku"] == "111"
    assert out["latest_price_cents"] == 55
    found = client.get(f"{URL}/search", params={"q": "triturado"}, headers=AUTH).json()
    assert found[0]["product_id"] == out["product"]["id"]
    r = client.post(f"{URL}/products", json={"store_sku": "999"}, headers=AUTH)
    assert r.status_code == 404


def test_disconnecting_withdraws_the_notice(client):
    connect(client, accept_notice=True, postal_code="29003")
    assert client.delete(f"{URL}/connection", headers=AUTH).status_code == 204
    state = client.get(f"{URL}/connection", headers=AUTH).json()
    assert state["ready"] is False and state["notice_accepted_at"] is None
    r = client.get(f"{URL}/search", params={"q": "tomate"}, headers=AUTH)
    assert r.json()["error"]["code"] == "notice_required"


def test_an_unknown_store_is_not_found(client):
    assert client.get("/api/v1/stores/nope/connection", headers=AUTH).status_code == 404
