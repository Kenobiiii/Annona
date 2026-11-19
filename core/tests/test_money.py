# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

import pytest
from pydantic import ValidationError

from annona_core.domain import Money, Quantity, unit_price


def eur(cents: int) -> Money:
    return Money(amount_cents=cents, currency="EUR")


@pytest.mark.parametrize(
    ("cents", "amount", "unit", "expected_cents", "per"),
    [
        (129, 400, "g", 323, "kg"),  # 322.5 rounds half-up
        (100, 1, "kg", 100, "kg"),
        (85, 500, "g", 170, "kg"),
        (99, 1, "l", 99, "l"),
        (75, 33, "cl", 227, "l"),  # 227.27...
        (240, 12, "unit", 20, "unit"),
        (0, 1, "kg", 0, "kg"),
        (1, 3, "kg", 0, "kg"),  # 0.33 cents
    ],
)
def test_unit_price(cents, amount, unit, expected_cents, per):
    result = unit_price(eur(cents), Quantity.parse(amount, unit))
    assert result.amount_cents == expected_cents
    assert result.per == per
    assert result.currency == "EUR"


def test_unit_price_with_decimal_package():
    assert unit_price(eur(199), Quantity.parse(Decimal("1.5"), "kg")).amount_cents == 133


def test_unit_price_rejects_empty_package():
    with pytest.raises(ValueError, match="positive"):
        unit_price(eur(100), Quantity.parse(0, "g"))


def test_money_upper_cases_currency():
    assert Money(amount_cents=1, currency="eur").currency == "EUR"


@pytest.mark.parametrize("code", ["EU", "EURO", "€UR", "12A", ""])
def test_money_rejects_bad_currency(code):
    with pytest.raises(ValidationError):
        Money(amount_cents=1, currency=code)


def test_money_rejects_float_amount():
    with pytest.raises(ValidationError):
        Money(amount_cents=1.5, currency="EUR")
