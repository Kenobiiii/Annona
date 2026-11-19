# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

import pytest
from pydantic import ValidationError

from annona_core.domain import Quantity, Unit, UnitConversionError


@pytest.mark.parametrize(
    ("amount", "unit", "expected_amount", "expected_unit"),
    [
        (1, "kg", "1000", Unit.G),
        ("0.5", "KG", "500", Unit.G),
        (250, "g", "250", Unit.G),
        (1500, "mg", "1.5", Unit.G),
        (1, "l", "1000", Unit.ML),
        (33, "cl", "330", Unit.ML),
        (2, "dl", "200", Unit.ML),
        (6, "u", "6", Unit.UNIT),
        (12, " Units ", "12", Unit.UNIT),
    ],
)
def test_parse_normalises_to_canonical_units(amount, unit, expected_amount, expected_unit):
    q = Quantity.parse(amount, unit)
    assert q.amount == Decimal(expected_amount)
    assert q.unit == expected_unit


def test_parse_rejects_unknown_unit():
    with pytest.raises(UnitConversionError, match="unknown unit"):
        Quantity.parse(1, "lb")


def test_parse_rejects_float_to_avoid_binary_rounding():
    with pytest.raises(TypeError):
        Quantity.parse(0.1, "kg")


def test_negative_amount_is_invalid():
    with pytest.raises(ValidationError):
        Quantity(amount=Decimal(-1), unit=Unit.G)


def test_same_unit_conversion_is_identity():
    q = Quantity.parse(100, "g")
    assert q.to(Unit.G) is q


def test_volume_to_mass_uses_density():
    oil = Quantity.parse(1, "l")
    assert oil.to(Unit.G, density_g_per_ml=Decimal("0.92")).amount == Decimal("920.00")


def test_mass_to_volume_uses_density():
    assert Quantity.parse(460, "g").to(Unit.ML, density_g_per_ml=Decimal("0.92")).amount == 500


def test_units_to_mass_uses_unit_weight():
    eggs = Quantity.parse(6, "unit")
    assert eggs.to(Unit.G, unit_weight_g=Decimal(60)).amount == 360


def test_mass_to_units_uses_unit_weight():
    assert Quantity.parse(360, "g").to(Unit.UNIT, unit_weight_g=Decimal(60)).amount == 6


def test_units_to_volume_needs_both_factors():
    milk_bricks = Quantity.parse(2, "unit")
    q = milk_bricks.to(Unit.ML, unit_weight_g=Decimal(1030), density_g_per_ml=Decimal("1.03"))
    assert q.amount == 2000


@pytest.mark.parametrize(
    ("source", "target", "kwargs", "missing"),
    [
        (Quantity.parse(1, "l"), Unit.G, {}, "density_g_per_ml"),
        (Quantity.parse(1, "kg"), Unit.ML, {}, "density_g_per_ml"),
        (Quantity.parse(1, "unit"), Unit.G, {}, "unit_weight_g"),
        (Quantity.parse(1, "kg"), Unit.UNIT, {}, "unit_weight_g"),
    ],
)
def test_cross_dimension_without_product_data_raises(source, target, kwargs, missing):
    with pytest.raises(UnitConversionError, match=missing):
        source.to(target, **kwargs)


def test_non_positive_conversion_factor_raises():
    with pytest.raises(UnitConversionError, match="positive"):
        Quantity.parse(1, "l").to(Unit.G, density_g_per_ml=Decimal(0))
