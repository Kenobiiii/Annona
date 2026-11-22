# SPDX-License-Identifier: AGPL-3.0-or-later
"""What confirming a receipt line does: pantry amount and price. Pure code, unknowns explicit.

Receipts often print no weight: then nothing is assumed silently. The effect says what is known,
what was assumed (one pack when no quantity is printed) and what is missing (no pack size).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from annona_core.domain import Product, Unit
from annona_core.domain.units import Quantity, UnitConversionError

from .parse import ParsedLine

_THOUSANDTH = Decimal("0.001")


@dataclass(frozen=True)
class LineEffect:
    pantry_amount: Decimal | None  # in ``pantry_unit``; None = unknown, the person must say
    pantry_unit: Unit | None
    price_cents: int | None  # per pack of the product (what Price stores); None = not derivable
    notes: tuple[str, ...] = field(default=())
    # notes: "assumed_one_pack" | "unknown_pack_size" | "price_from_weight" | "no_price"


def _convert(q: Quantity, unit: Unit, product: Product) -> Quantity | None:
    try:
        return q.to(unit, density_g_per_ml=product.density_g_per_ml, unit_weight_g=product.unit_weight_g)
    except UnitConversionError:
        return None


def line_effect(line: ParsedLine, product: Product) -> LineEffect:
    """Pantry amount and per-pack price for a confirmed (line, product) pair."""
    pack_amount, pack_unit = product.package_amount, product.package_unit
    notes: list[str] = []

    # 1. A printed weight is the best information: it is exactly what was bought.
    if line.weight is not None:
        target = Unit(str(pack_unit)) if pack_unit is not None else line.weight.unit
        bought = _convert(line.weight, target, product)
        if bought is not None and bought.amount > 0:
            price = None
            if pack_amount:
                price = int(
                    (Decimal(line.total_cents) * Decimal(pack_amount) / bought.amount).quantize(
                        Decimal(1), rounding=ROUND_HALF_UP
                    )
                )
                notes.append("price_from_weight")  # derived from price per weight, not printed
            else:
                notes.append("no_price")
            return LineEffect(
                bought.amount.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP), target, price, tuple(notes)
            )

    # 2. Packs: the printed quantity, or one pack when nothing is printed (said out loud).
    quantity = line.quantity
    if quantity is None:
        quantity = Decimal(1)
        notes.append("assumed_one_pack")
    price = int((Decimal(line.total_cents) / quantity).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if not pack_amount or pack_unit is None:
        notes.append("unknown_pack_size")
        return LineEffect(None, None, price, tuple(notes))
    return LineEffect(
        (Decimal(pack_amount) * quantity).quantize(_THOUSANDTH, rounding=ROUND_HALF_UP),
        Unit(str(pack_unit)),
        price,
        tuple(notes),
    )
