# SPDX-License-Identifier: AGPL-3.0-or-later
"""Example provider: replace the TODOs with your store's real, public endpoints.

Before writing code: read the store's robots.txt and terms of use. If robots.txt disallows what
you need, the plugin must be opt-in (``opt_in=True`` plus a ``notice``), act only on explicit user
requests for a few items, and refuse whole-catalogue downloads. See CLAUDE.md, "LEGAL/ETHICS".
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from annona_providers.base import (
    ProviderError,
    ProviderInfo,
    ProviderPrice,
    ProviderProduct,
    euros_to_cents,
)
from annona_providers.http import PoliteTransport

API = "https://shop.example/api"  # TODO: the store's real base URL


class ExampleProvider:
    info = ProviderInfo(
        id="example",  # TODO: lowercase slug, equal to the entry point name
        name="Example Store",
        country="ES",  # ISO 3166-1 alpha-2
        currency="EUR",
        homepage="https://shop.example",
    )

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        # Always go through PoliteTransport (robots.txt, rate limit, cache, User-Agent).
        self._client = httpx.Client(transport=transport or PoliteTransport(), timeout=20.0)

    @property
    def store_id(self) -> str:
        return self.info.id

    def close(self) -> None:
        self._client.close()

    def search(self, query: str, limit: int = 20) -> Sequence[ProviderProduct]:
        data = self._get("/search", {"q": query, "size": limit})  # TODO: real endpoint
        return [_product(item) for item in data["items"]][:limit]

    def get_product(self, store_sku: str) -> ProviderProduct | None:
        try:
            return _product(self._get(f"/products/{store_sku}", {}))
        except ProviderError:
            return None  # TODO: only for "not found"; re-raise other errors

    def get_prices(self, store_skus: Sequence[str]) -> Sequence[ProviderPrice]:
        prices = []
        for sku in store_skus:
            item = self._get(f"/products/{sku}", {})
            prices.append(
                ProviderPrice(
                    store_sku=sku,
                    amount_cents=euros_to_cents(Decimal(str(item["price"]))),
                    currency=self.info.currency,
                    observed_at=datetime.now(UTC),
                )
            )
        return prices

    def iter_catalog(self) -> Iterator[ProviderProduct]:
        # Raise CatalogNotSupportedError instead if the store does not allow bulk access.
        yield from self.search("", limit=100)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.get(API + path, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as error:
            raise ProviderError(f"Example request failed: {error}") from error


def _product(item: dict[str, Any]) -> ProviderProduct:
    return ProviderProduct(store_sku=str(item["id"]), name=item["name"])  # TODO: map all fields
