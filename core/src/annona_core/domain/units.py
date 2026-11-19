# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quantities and unit conversion.

Every quantity is stored in one of three canonical units: grams (``g``), millilitres (``ml``) or
countable pieces (``unit``). Input in other common units (kg, l, cl, ...) is normalised on entry.

Conversions across dimensions are only possible with product-specific data:

* mass <-> volume needs the product's density (g/ml);
* pieces <-> mass/volume needs the product's weight per piece (g).

When that data is missing a :class:`UnitConversionError` is raised; the code never guesses.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class Unit(StrEnum):
    """Canonical storage unit."""

    G = "g"
    ML = "ml"
    UNIT = "unit"


class UnitConversionError(ValueError):
    """Raised when a quantity cannot be converted without missing product data."""


# alias -> (canonical unit, factor to canonical)
_INPUT_UNITS: dict[str, tuple[Unit, Decimal]] = {
    "mg": (Unit.G, Decimal("0.001")),
    "g": (Unit.G, Decimal(1)),
    "kg": (Unit.G, Decimal(1000)),
    "ml": (Unit.ML, Decimal(1)),
    "cl": (Unit.ML, Decimal(10)),
    "dl": (Unit.ML, Decimal(100)),
    "l": (Unit.ML, Decimal(1000)),
    "unit": (Unit.UNIT, Decimal(1)),
    "units": (Unit.UNIT, Decimal(1)),
    "u": (Unit.UNIT, Decimal(1)),
    "pc": (Unit.UNIT, Decimal(1)),
    "pcs": (Unit.UNIT, Decimal(1)),
}


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):
        # Floats carry binary rounding noise (0.1 -> 0.1000000000000000055...).
        raise TypeError("pass quantities as Decimal, int or str, not float")
    return Decimal(value)


class Quantity(BaseModel):
    """An amount in a canonical unit. Immutable."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    unit: Unit

    @field_validator("amount")
    @classmethod
    def _non_negative(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError("quantity amount must be a finite, non-negative number")
        return value

    @classmethod
    def parse(cls, amount: Decimal | int | str, unit: str) -> Quantity:
        """Build a canonical quantity from any supported input unit (case-insensitive)."""
        key = unit.strip().lower()
        if key not in _INPUT_UNITS:
            raise UnitConversionError(f"unknown unit {unit!r}; supported: {sorted(_INPUT_UNITS)}")
        canonical, factor = _INPUT_UNITS[key]
        return cls(amount=_to_decimal(amount) * factor, unit=canonical)

    def to(
        self,
        target: Unit,
        *,
        density_g_per_ml: Decimal | None = None,
        unit_weight_g: Decimal | None = None,
    ) -> Quantity:
        """Convert to another canonical unit, using product data when crossing dimensions."""
        if target == self.unit:
            return self
        grams = self._as_grams(density_g_per_ml, unit_weight_g)
        if target == Unit.G:
            return Quantity(amount=grams, unit=Unit.G)
        if target == Unit.ML:
            return Quantity(
                amount=grams / _require(density_g_per_ml, "density_g_per_ml"), unit=Unit.ML
            )
        return Quantity(amount=grams / _require(unit_weight_g, "unit_weight_g"), unit=Unit.UNIT)

    def _as_grams(self, density: Decimal | None, unit_weight: Decimal | None) -> Decimal:
        if self.unit == Unit.G:
            return self.amount
        if self.unit == Unit.ML:
            return self.amount * _require(density, "density_g_per_ml")
        return self.amount * _require(unit_weight, "unit_weight_g")


def _require(value: Decimal | None, name: str) -> Decimal:
    if value is None:
        raise UnitConversionError(f"{name} is required for this conversion")
    if value <= 0:
        raise UnitConversionError(f"{name} must be positive")
    return value
