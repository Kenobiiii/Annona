# SPDX-License-Identifier: AGPL-3.0-or-later
"""The supermarket plugin interface.

A provider turns one store (or data source) into the common :class:`ProviderProduct` /
:class:`ProviderPrice` types. The core never imports a specific provider; it only sees this
interface, through the registry.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from annona_core.domain import Price, PriceSource, Product, Unit
from annona_core.domain.money import validate_currency


class ProviderError(Exception):
    """Base class for provider failures."""


class CatalogNotSupportedError(ProviderError):
    """The provider does not offer full-catalogue iteration (e.g. opt-in, personal-use plugins)."""


class NoticeNotAcceptedError(ProviderError):
    """An opt-in provider was created without the user accepting its responsibility notice."""


class TooManyItemsError(ProviderError):
    """A request asked for more items than the provider allows in one call."""


@dataclass(frozen=True)
class ProviderInfo:
    """Static metadata about a provider."""

    id: str  # lowercase slug, e.g. "mercadona"
    name: str
    country: str | None  # ISO 3166-1 alpha-2, None for multi-country sources
    currency: str  # ISO 4217
    supports_postcode: bool = False
    opt_in: bool = False  # disabled by default; needs `notice` to be accepted
    notice: str | None = None
    attribution: str | None = None  # licence / source credit to display
    homepage: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", self.id):
            raise ValueError(f"invalid provider id {self.id!r}")
        if self.country is not None and not re.fullmatch(r"[A-Z]{2}", self.country):
            raise ValueError(f"invalid country code {self.country!r}")
        validate_currency(self.currency)
        if self.opt_in and not self.notice:
            raise ValueError("opt-in providers must define a responsibility notice")


class ProviderProduct(BaseModel):
    """A product as a provider sees it. ``store_sku`` is unique within the provider."""

    model_config = ConfigDict(frozen=True)

    store_sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    brand: str | None = None
    ean: str | None = Field(default=None, pattern=r"^\d{8,14}$")
    package_amount: Decimal | None = Field(default=None, gt=0)
    package_unit: Unit | None = None
    category_path: tuple[str, ...] = ()
    url: str | None = None
    image_url: str | None = None


class ProviderPrice(BaseModel):
    """One observed price for one product (per package, or per kg/l when sold by weight)."""

    model_config = ConfigDict(frozen=True)

    store_sku: str = Field(min_length=1)
    amount_cents: int = Field(ge=0)
    currency: str
    observed_at: AwareDatetime
    unit_price_cents: int | None = Field(default=None, ge=0, description="as published")
    unit_price_per: str | None = None  # "kg", "l", "unit"...
    is_discounted: bool = False


@runtime_checkable
class SupermarketProvider(Protocol):
    info: ProviderInfo

    @property
    def store_id(self) -> str:
        """Id stored on products/prices (provider id plus an optional variant)."""
        ...

    def search(self, query: str, limit: int = 20) -> Sequence[ProviderProduct]: ...

    def get_product(self, store_sku: str) -> ProviderProduct | None: ...

    def iter_catalog(self) -> Iterator[ProviderProduct]:
        """All products. Raises :class:`CatalogNotSupportedError` when not allowed."""
        ...

    def get_prices(self, store_skus: Sequence[str]) -> Sequence[ProviderPrice]: ...

    def close(self) -> None: ...


# ------------------------------------------------------------------------------------ helpers


def euros_to_cents(value: Decimal | str | int) -> int:
    """Exact decimal euros -> integer cents, rounded half-up (never via float)."""
    if isinstance(value, float):
        raise TypeError("convert floats with Decimal(str(value)) first")
    return int((Decimal(value) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_domain_product(item: ProviderProduct, store_id: str) -> Product:
    """Provider product -> core :class:`Product` (nutrition and allergens are filled later)."""
    return Product(
        name=item.name,
        brand=item.brand,
        ean=item.ean,
        store_id=store_id,
        store_sku=item.store_sku,
        package_amount=item.package_amount,
        package_unit=item.package_unit,
    )


def to_domain_price(item: ProviderPrice, product_id: int, store_id: str) -> Price:
    return Price(
        product_id=product_id,
        store_id=store_id,
        amount_cents=item.amount_cents,
        currency=item.currency,
        source=PriceSource.SCRAPE,
        observed_at=item.observed_at,
    )
