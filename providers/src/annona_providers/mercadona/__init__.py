# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mercadona (Spain) — OPT-IN, personal-use provider.

Mercadona has no official API. This plugin uses the undocumented endpoints of its online shop
through the `mercapy <https://github.com/jtayped/mercapy>`_ client (MIT). Those endpoints are
disallowed by the shop's ``robots.txt``, so, following the project rules (CLAUDE.md), the plugin:

* is disabled by default and needs the user to accept :data:`NOTICE`;
* acts only on explicit user requests, for a small number of products at a time
  (:data:`MAX_SKUS_PER_CALL`), with a pause between requests and caching;
* never downloads the whole catalogue (:meth:`MercadonaProvider.iter_catalog` raises).

Prices depend on the warehouse that serves a postcode, so the provider is created with a Spanish
postcode (one request to resolve it) or a known warehouse code.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import mercapy

from annona_core.domain import Quantity, Unit, UnitConversionError

from ..base import (
    CatalogNotSupportedError,
    ProviderError,
    ProviderInfo,
    ProviderPrice,
    ProviderProduct,
    TooManyItemsError,
    euros_to_cents,
)
from ..http import PoliteTransport

MAX_SKUS_PER_CALL = 50
MIN_INTERVAL_SECONDS = 2.0

NOTICE = (
    "The Mercadona plugin queries the undocumented API of Mercadona's online shop, which its "
    "robots.txt disallows. Annona only uses it for your own, personal requests (a few products at "
    "a time, never the whole catalogue), slowly and with caching. Annona is not affiliated with "
    "Mercadona. By enabling it you accept responsibility for complying with Mercadona's terms of "
    "use; the endpoints may change or stop working at any time."
)


class MercadonaProvider:
    info = ProviderInfo(
        id="mercadona",
        name="Mercadona",
        country="ES",
        currency="EUR",
        supports_postcode=True,
        opt_in=True,
        notice=NOTICE,
        homepage="https://tienda.mercadona.es",
    )

    def __init__(
        self,
        *,
        postal_code: str | None = None,
        warehouse: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if (postal_code is None) == (warehouse is None):
            raise ValueError("give exactly one of postal_code or warehouse")
        transport = transport or PoliteTransport(
            min_interval=MIN_INTERVAL_SECONDS, robots_exception=True
        )
        try:
            if postal_code is not None:
                self._client = mercapy.Mercadona.from_postal_code(postal_code, transport=transport)
            else:
                self._client = mercapy.Mercadona(warehouse, transport=transport)
        except mercapy.MercapyError as error:
            raise ProviderError(f"Mercadona: {error}") from error

    @property
    def store_id(self) -> str:
        return self.info.id

    @property
    def warehouse(self) -> str:
        return self._client.warehouse

    def close(self) -> None:
        self._client.close()

    # -- interface --
    def search(self, query: str, limit: int = 20) -> Sequence[ProviderProduct]:
        try:
            result = self._client.search_products(query, page_size=min(limit, 50))
        except mercapy.MercapyError as error:
            raise ProviderError(f"Mercadona search failed: {error}") from error
        return [_product(p) for p in result.products[:limit]]

    def get_product(self, store_sku: str) -> ProviderProduct | None:
        full = self._get_full(store_sku)
        return None if full is None else _product(full)

    def get_prices(self, store_skus: Sequence[str]) -> Sequence[ProviderPrice]:
        if len(store_skus) > MAX_SKUS_PER_CALL:
            raise TooManyItemsError(
                f"Mercadona is personal-use only: at most {MAX_SKUS_PER_CALL} products per call"
            )
        prices = []
        for sku in store_skus:
            full = self._get_full(sku)
            if full is not None and (price := _price(full)) is not None:
                prices.append(price)
        return prices

    def iter_catalog(self) -> Iterator[ProviderProduct]:
        raise CatalogNotSupportedError(
            "Mercadona is opt-in and personal-use only: whole-catalogue downloads are not allowed"
        )

    # -- internals --
    def _get_full(self, sku: str) -> mercapy.Product | None:
        try:
            return self._client.get_product(sku)
        except mercapy.NotFoundError:
            return None
        except mercapy.MercapyError as error:
            raise ProviderError(f"Mercadona product {sku} failed: {error}") from error


_MASS_VOLUME = {"kg", "g", "l", "ml"}
_COUNT = {"ud": Decimal(1), "dz": Decimal(12)}  # reference price per unit or per dozen


def _package(
    product: mercapy.Product | mercapy.ProductSummary,
) -> tuple[Decimal | None, Unit | None]:
    """Package size, only when the store's own numbers agree.

    ``unit_size`` is the total size of what is sold (a pack of 6 x 1 l bricks has 6 l; a box of
    24 eggs has 24 ud). It is only trusted when the pack price equals the published reference
    price (per kg, l, unit or dozen) times the size, within one cent of the pack price (prices
    are rounded to cents, sizes may be approximate). Canned food is priced per kg of drained
    weight, so the drained weight is used when it is the one that matches. Otherwise the size
    is left unknown, never guessed.
    """
    price = product.price
    if price.sold_by_weight:
        return Decimal(1000), Unit.G  # priced per kg, see _price
    fmt = (price.size_format or "").lower()
    ref_fmt = (price.reference_format or "").lower()
    if not price.unit_size or price.unit is None or price.reference is None:
        return None, None
    if fmt in _COUNT or fmt == "ud":
        per = _COUNT.get(ref_fmt)
        if per is not None and _matches(price.unit, price.unit_size / per, price.reference):
            return price.unit_size, Unit.UNIT
        return None, None
    if fmt not in _MASS_VOLUME:
        return None, None
    try:
        q = Quantity.parse(price.unit_size, fmt)
    except (UnitConversionError, ValueError):
        return None, None
    if q.amount <= 0:
        return None, None
    if _matches(price.unit, q.amount / 1000, price.reference):
        return q.amount, q.unit
    # Canned food: the store's reference price is per kg of DRAINED weight (what is eaten).
    if price.drained_weight and fmt in ("kg", "g"):
        drained = Quantity.parse(price.drained_weight, fmt)
        if _matches(price.unit, drained.amount / 1000, price.reference):
            return drained.amount, drained.unit
    return None, None


def _matches(pack_price: Decimal, reference_units: Decimal, reference: Decimal) -> bool:
    """pack price == reference price x size (in kg, l, units or dozens), within one cent."""
    return abs(pack_price - reference * reference_units) <= Decimal("0.01")


def _product(product: mercapy.Product | mercapy.ProductSummary) -> ProviderProduct:
    amount, unit = _package(product)
    path: list[str] = []
    if product.categories:
        node = product.categories[0]
        while True:
            path.append(node.name)
            if not node.children:
                break
            node = node.children[0]
    ean = getattr(product, "ean", None)
    return ProviderProduct(
        store_sku=product.id,
        name=product.name,
        brand=product.brand,
        ean=ean if ean and ean.isdigit() and 8 <= len(ean) <= 14 else None,
        package_amount=amount,
        package_unit=unit,
        category_path=tuple(path),
        url=product.share_url,
    )


def _price(product: mercapy.Product) -> ProviderPrice | None:
    price = product.price
    amount = price.reference if price.sold_by_weight else price.unit
    if amount is None:
        return None
    reference_per = (price.reference_format or "").lower() or None
    return ProviderPrice(
        store_sku=product.id,
        amount_cents=euros_to_cents(amount),
        currency="EUR",
        observed_at=datetime.now(UTC),
        unit_price_cents=euros_to_cents(price.reference) if price.reference is not None else None,
        unit_price_per=reference_per,
        is_discounted=price.is_discounted,
    )
