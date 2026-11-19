# SPDX-License-Identifier: AGPL-3.0-or-later
"""Money and unit prices.

Money is always an integer number of minor units (cents) plus an ISO 4217 currency code; floats are
never used. Unit prices are rounded half-up to whole cents only at the end of the calculation.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from .units import Quantity, Unit

# Reference amount for unit prices: per kg, per litre, per piece.
_REFERENCE: dict[Unit, tuple[Decimal, str]] = {
    Unit.G: (Decimal(1000), "kg"),
    Unit.ML: (Decimal(1000), "l"),
    Unit.UNIT: (Decimal(1), "unit"),
}


def validate_currency(code: str) -> str:
    """Validate an ISO 4217 alphabetic code (format only) and return it upper-cased."""
    code = code.strip().upper()
    if len(code) != 3 or not code.isalpha() or not code.isascii():
        raise ValueError(f"invalid ISO 4217 currency code: {code!r}")
    return code


class Money(BaseModel):
    """An amount in minor units (e.g. cents) of a currency. Immutable."""

    model_config = ConfigDict(frozen=True)

    amount_cents: int
    currency: str

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return validate_currency(value)


class UnitPrice(BaseModel):
    """Price per reference amount: per ``kg``, per ``l`` or per ``unit``."""

    model_config = ConfigDict(frozen=True)

    amount_cents: int
    currency: str
    per: str


def unit_price(price: Money, package: Quantity) -> UnitPrice:
    """Price per kg / l / unit for a package of the given size.

    >>> unit_price(Money(amount_cents=129, currency="EUR"), Quantity.parse(400, "g")).amount_cents
    323
    """
    if price.amount_cents < 0:
        raise ValueError("price must not be negative")
    if package.amount <= 0:
        raise ValueError("package size must be positive to compute a unit price")
    reference, label = _REFERENCE[package.unit]
    exact = Decimal(price.amount_cents) * reference / package.amount
    cents = int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return UnitPrice(amount_cents=cents, currency=price.currency, per=label)
