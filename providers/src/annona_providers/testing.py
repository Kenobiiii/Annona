# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test helpers for provider authors: recorded fixtures and the provider contract.

* :class:`FixtureTransport` replays recorded HTTP exchanges and fails on anything else, so tests
  never touch the network.
* :class:`RecordingTransport` records real exchanges into a fixture directory (run locally, review
  the files, then commit them).
* :class:`ProviderContract` is a pytest base class with the checks every provider must pass.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest

from annona_core.domain.money import validate_currency

from .base import (
    CatalogNotSupportedError,
    ProviderPrice,
    ProviderProduct,
    SupermarketProvider,
    to_domain_price,
    to_domain_product,
)
from .http import decoded_headers

INDEX = "exchanges.json"
_KEEP_HEADERS = {"content-type", "x-customer-wh"}


def exchange_key(request: httpx.Request) -> str:
    """Stable key: method, URL with sorted query, and a hash of the body."""
    url = request.url.copy_with(params=sorted(request.url.params.multi_items()))
    body = request.read()
    digest = hashlib.sha256(body).hexdigest()[:16] if body else "-"
    return f"{request.method} {url} {digest}"


class FixtureTransport(httpx.BaseTransport):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.index: dict[str, dict[str, Any]] = json.loads((directory / INDEX).read_text())

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        key = exchange_key(request)
        entry = self.index.get(key)
        if entry is None:
            raise AssertionError(f"no recorded fixture for {key}")
        content = (self.directory / entry["file"]).read_bytes() if entry.get("file") else b""
        return httpx.Response(
            entry["status"], headers=entry.get("headers", {}), content=content, request=request
        )


class RecordingTransport(httpx.BaseTransport):
    """Records every exchange passing through ``inner`` into ``directory``."""

    def __init__(self, directory: Path, inner: httpx.BaseTransport) -> None:
        self.directory = directory
        self.inner = inner
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / INDEX
        self.index: dict[str, dict[str, Any]] = (
            json.loads(path.read_text()) if path.exists() else {}
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        content = response.read()
        key = exchange_key(request)
        name = None
        if content:
            name = hashlib.sha256(key.encode()).hexdigest()[:12] + ".json"
            try:  # pretty-print JSON so fixtures are reviewable
                content_out = json.dumps(json.loads(content), indent=2, ensure_ascii=False).encode()
            except ValueError:
                content_out = content
            (self.directory / name).write_bytes(content_out)
        headers = {k: v for k, v in response.headers.items() if k.lower() in _KEEP_HEADERS}
        self.index[key] = {"status": response.status_code, "headers": headers, "file": name}
        (self.directory / INDEX).write_text(json.dumps(self.index, indent=2, sort_keys=True) + "\n")
        return httpx.Response(
            response.status_code,
            headers=decoded_headers(response),
            content=content,
            request=request,
        )

    def close(self) -> None:
        self.inner.close()


class ProviderContract:
    """Subclass in your provider's tests and implement the ``provider`` fixture.

    Class attributes to set: ``search_query`` (returns at least one product), ``known_sku`` and
    ``unknown_sku``.
    """

    search_query: ClassVar[str]
    known_sku: ClassVar[str]
    unknown_sku: ClassVar[str]

    @pytest.fixture
    def provider(self) -> Iterator[SupermarketProvider]:  # pragma: no cover - overridden
        raise NotImplementedError

    def test_implements_protocol(self, provider):
        assert isinstance(provider, SupermarketProvider)
        assert provider.store_id.startswith(provider.info.id)
        validate_currency(provider.info.currency)

    def test_search_returns_products(self, provider):
        results = provider.search(self.search_query, limit=5)
        assert 0 < len(results) <= 5
        assert all(isinstance(p, ProviderProduct) for p in results)
        assert len({p.store_sku for p in results}) == len(results)

    def test_get_known_product(self, provider):
        product = provider.get_product(self.known_sku)
        assert product is not None
        assert product.store_sku == self.known_sku
        domain = to_domain_product(product, provider.store_id)
        assert domain.store_sku == self.known_sku

    def test_get_unknown_product_returns_none(self, provider):
        assert provider.get_product(self.unknown_sku) is None

    def test_prices(self, provider):
        prices = provider.get_prices([self.known_sku])
        assert prices, "expected a price for the known product"
        now = datetime.now(UTC)
        for price in prices:
            assert isinstance(price, ProviderPrice)
            assert price.store_sku == self.known_sku
            assert price.currency == provider.info.currency
            assert price.observed_at <= now + timedelta(minutes=5)
            to_domain_price(price, product_id=1, store_id=provider.store_id)

    def test_catalog_policy(self, provider):
        if provider.info.opt_in:
            # Opt-in, personal-use providers must never download whole catalogues.
            with pytest.raises(CatalogNotSupportedError):
                next(iter(provider.iter_catalog()))
        else:
            try:
                first = next(iter(provider.iter_catalog()), None)
            except CatalogNotSupportedError:
                return
            assert first is None or isinstance(first, ProviderProduct)

    def test_opt_in_providers_have_a_notice(self, provider):
        if provider.info.opt_in:
            assert provider.info.notice and len(provider.info.notice) > 50
