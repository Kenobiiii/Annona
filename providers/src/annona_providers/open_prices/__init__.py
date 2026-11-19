# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open Prices (Open Food Facts): crowdsourced prices from receipts and shelf photos.

API: https://prices.openfoodfacts.org/api/docs (schema at ``/api/schema``). Data licence: ODbL 1.0;
credit the source when displaying prices. Products are identified by barcode (EAN), so
``store_sku`` is the EAN.

One provider instance follows one store brand (e.g. ``brand="Mercadona"``) in one country, by
looking up the brand's OpenStreetMap locations and reading the prices recorded there. Coverage
depends entirely on volunteers and can be sparse or old.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any

import httpx

from annona_core.domain import Quantity, UnitConversionError

from ..base import (
    ProviderError,
    ProviderInfo,
    ProviderPrice,
    ProviderProduct,
    TooManyItemsError,
    euros_to_cents,
)
from ..http import PoliteTransport

API = "https://prices.openfoodfacts.org/api/v1"
MAX_SKUS_PER_CALL = 100
_PAGE_SIZE = 100


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class OpenPricesProvider:
    info = ProviderInfo(
        id="open_prices",
        name="Open Prices (Open Food Facts)",
        country=None,
        currency="EUR",
        attribution="Prices from Open Prices by Open Food Facts contributors, ODbL 1.0",
        homepage="https://prices.openfoodfacts.org",
    )

    def __init__(
        self,
        *,
        brand: str,
        country: str = "España",
        currency: str = "EUR",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.brand = brand
        self.country = country
        self.currency = currency
        self._client = httpx.Client(
            transport=transport or PoliteTransport(min_interval=1.0), timeout=20.0
        )
        self._location_ids: list[int] | None = None

    @property
    def store_id(self) -> str:
        return f"{self.info.id}:{_slug(self.brand)}"

    def close(self) -> None:
        self._client.close()

    # -- interface --
    def search(self, query: str, limit: int = 20) -> Sequence[ProviderProduct]:
        data = self._get(
            "/products",
            {"product_name__like": query, "price_count__gte": 1, "size": limit, "page": 1},
        )
        return [p for item in data["items"] if (p := _product(item)) is not None][:limit]

    def get_product(self, store_sku: str) -> ProviderProduct | None:
        data = self._get("/products", {"code": store_sku, "size": 1, "page": 1})
        items = [p for item in data["items"] if (p := _product(item)) is not None]
        return items[0] if items else None

    def get_prices(self, store_skus: Sequence[str]) -> Sequence[ProviderPrice]:
        """Latest price per product at this brand's locations."""
        if len(store_skus) > MAX_SKUS_PER_CALL:
            raise TooManyItemsError(f"at most {MAX_SKUS_PER_CALL} products per call")
        locations = self._locations()
        if not store_skus or not locations:
            return []
        data = self._get(
            "/prices",
            {
                "product_code__in": ",".join(store_skus),
                "location_id__in": ",".join(map(str, locations)),
                "currency": self.currency,
                "type": "PRODUCT",
                "order_by": "-date",
                "size": _PAGE_SIZE,
                "page": 1,
            },
        )
        latest: dict[str, ProviderPrice] = {}
        for item in data["items"]:
            code = item.get("product_code")
            if code and code not in latest and item.get("price") is not None:
                latest[code] = _price(item)
        return [latest[s] for s in store_skus if s in latest]

    def iter_catalog(self) -> Iterator[ProviderProduct]:
        """Products with at least one price at this brand (open data, so bulk is fine)."""
        locations = self._locations()
        if not locations:
            return
        seen: set[str] = set()
        page = 1
        while True:
            data = self._get(
                "/prices",
                {
                    "location_id__in": ",".join(map(str, locations)),
                    "type": "PRODUCT",
                    "order_by": "-date",
                    "size": _PAGE_SIZE,
                    "page": page,
                },
            )
            for item in data["items"]:
                code = item.get("product_code")
                product = _product(item.get("product") or {})
                if code and code not in seen and product is not None:
                    seen.add(code)
                    yield product
            if page >= data.get("pages", 1):
                return
            page += 1

    # -- internals --
    def _locations(self) -> list[int]:
        if self._location_ids is None:
            data = self._get(
                "/locations",
                {
                    "osm_name__like": self.brand,
                    "osm_address_country__like": self.country,
                    "price_count__gte": 1,
                    "size": _PAGE_SIZE,
                    "page": 1,
                },
            )
            self._location_ids = sorted(item["id"] for item in data["items"])
        return self._location_ids

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.get(API + path, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as error:
            raise ProviderError(f"Open Prices request failed: {error}") from error


def _product(item: dict[str, Any]) -> ProviderProduct | None:
    code = item.get("code")
    name = item.get("product_name")
    if not code or not name or not re.fullmatch(r"\d{8,14}", code):
        return None
    amount, unit = _package(item.get("product_quantity"), item.get("product_quantity_unit"))
    return ProviderProduct(
        store_sku=code,
        name=name.strip(),
        brand=(item.get("brands") or "").split(",")[0].strip() or None,
        ean=code,
        package_amount=amount,
        package_unit=unit,
        image_url=item.get("image_url"),
        url=f"https://world.openfoodfacts.org/product/{code}",
    )


def _package(amount: Any, unit: Any) -> tuple[Decimal | None, Any]:
    if amount is None or not unit:
        return None, None
    try:
        q = Quantity.parse(Decimal(str(amount)), str(unit))
    except (UnitConversionError, ArithmeticError, ValueError):
        return None, None
    return (q.amount, q.unit) if q.amount > 0 else (None, None)


def _price(item: dict[str, Any]) -> ProviderPrice:
    day = datetime.fromisoformat(item["date"]).date()
    return ProviderPrice(
        store_sku=item["product_code"],
        amount_cents=euros_to_cents(Decimal(str(item["price"]))),
        currency=item["currency"],
        observed_at=datetime.combine(day, time(12), tzinfo=UTC),  # API gives a date only
        is_discounted=bool(item.get("price_is_discounted")),
    )
