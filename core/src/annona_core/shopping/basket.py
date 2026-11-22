# SPDX-License-Identifier: AGPL-3.0-or-later
"""Price what a plan needs at one store. Pure functions, no LLM, no I/O.

* The need of each product is what the plan uses minus what the pantry already holds.
* If the store sells that very product it is used. Otherwise the cheapest *equivalent* is used
  (same category AND same type, e.g. "grains / rice", and the same unit basis); the other
  equivalents come back as alternatives with their price and nutrition difference.
* A product with no equivalent in the store is reported as unavailable, never guessed.
* Amounts are rounded up to whole packs, because that is what is bought.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

MAX_ALTERNATIVES = 3
_ZERO = Decimal(0)


class Need(BaseModel):
    """A product the plan uses, in its basis unit ("g" or "ml") for the whole household."""

    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    category: str
    type: str | None
    basis: str
    amount: Decimal = Field(ge=0)
    in_pantry: Decimal = Field(default=_ZERO, ge=0)  # the same product, already at home


class StoreProduct(BaseModel):
    """A product a store sells, with its latest price and pack size in the basis unit."""

    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    category: str
    type: str | None
    basis: str
    pack_amount: Decimal = Field(gt=0)
    price_cents: int = Field(ge=0)
    kcal_per_100: Decimal | None = None
    protein_per_100: Decimal | None = None


class Alternative(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    packs: int
    pack_amount: Decimal
    price_cents: int  # per pack
    cost_cents: int  # for the packs needed
    extra_cost_cents: int  # versus the product chosen for the line (negative = cheaper)
    kcal_diff_pct: Decimal | None  # per 100 g/ml versus what the plan used; None if unknown
    protein_diff_pct: Decimal | None


class BasketLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    need_product_id: int
    product_id: int  # what to buy (the need itself, or its substitute)
    name: str
    packs: int
    unit_price_cents: int
    cost_cents: int
    replaces_product_id: int | None  # set when this is a substitute
    alternatives: tuple[Alternative, ...] = ()  # only for substitutes


class Unavailable(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    amount: Decimal  # still needed, in basis units
    basis: str
    reason: str  # "not_sold" (no equivalent) | "no_type" (the product has no type to match on)


class Basket(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: str
    lines: tuple[BasketLine, ...]
    unavailable: tuple[Unavailable, ...]
    already_have: tuple[int, ...]  # needs fully covered by the pantry
    total_cents: int


def _packs(amount: Decimal, pack: Decimal) -> int:
    return max(1, math.ceil(amount / pack))


def _pct(new: Decimal | None, old: Decimal | None) -> Decimal | None:
    if new is None or old is None or old == 0:
        return None
    return ((new - old) / old * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def price_basket(
    needs: list[Need],
    products: list[StoreProduct],
    *,
    store_id: str,
    nutrition: dict[int, tuple[Decimal | None, Decimal | None]] | None = None,
) -> Basket:
    """The shopping list of ``needs`` at the store that sells ``products``.

    ``nutrition`` maps a need's product id to its (kcal, protein) per 100 g/ml, so substitutes can
    show how different they are.
    """
    nutrition = nutrition or {}
    by_id = {p.product_id: p for p in products}
    lines: list[BasketLine] = []
    unavailable: list[Unavailable] = []
    have: list[int] = []
    for need in needs:
        missing = max(need.amount - need.in_pantry, _ZERO)
        if missing == 0:
            have.append(need.product_id)
            continue
        same = by_id.get(need.product_id)
        if same is not None and same.basis == need.basis:
            lines.append(_line(need, same, missing, replaces=None, alternatives=()))
            continue
        if not need.type:
            unavailable.append(
                Unavailable(
                    product_id=need.product_id,
                    name=need.name,
                    amount=missing,
                    basis=need.basis,
                    reason="no_type",
                )
            )
            continue
        candidates = sorted(
            (
                p
                for p in products
                if p.category == need.category and p.type == need.type and p.basis == need.basis
            ),
            key=lambda p: (_packs(missing, p.pack_amount) * p.price_cents, p.price_cents, p.name),
        )
        if not candidates:
            unavailable.append(
                Unavailable(
                    product_id=need.product_id,
                    name=need.name,
                    amount=missing,
                    basis=need.basis,
                    reason="not_sold",
                )
            )
            continue
        chosen = candidates[0]
        chosen_cost = _packs(missing, chosen.pack_amount) * chosen.price_cents
        kcal, protein = nutrition.get(need.product_id, (None, None))
        alternatives = tuple(
            Alternative(
                product_id=p.product_id,
                name=p.name,
                packs=_packs(missing, p.pack_amount),
                pack_amount=p.pack_amount,
                price_cents=p.price_cents,
                cost_cents=_packs(missing, p.pack_amount) * p.price_cents,
                extra_cost_cents=_packs(missing, p.pack_amount) * p.price_cents - chosen_cost,
                kcal_diff_pct=_pct(p.kcal_per_100, kcal),
                protein_diff_pct=_pct(p.protein_per_100, protein),
            )
            for p in candidates[1 : 1 + MAX_ALTERNATIVES]
        )
        lines.append(
            _line(need, chosen, missing, replaces=need.product_id, alternatives=alternatives)
        )
    return Basket(
        store_id=store_id,
        lines=tuple(lines),
        unavailable=tuple(unavailable),
        already_have=tuple(have),
        total_cents=sum(line.cost_cents for line in lines),
    )


def _line(
    need: Need,
    product: StoreProduct,
    missing: Decimal,
    *,
    replaces: int | None,
    alternatives: tuple[Alternative, ...],
) -> BasketLine:
    packs = _packs(missing, product.pack_amount)
    return BasketLine(
        need_product_id=need.product_id,
        product_id=product.product_id,
        name=product.name,
        packs=packs,
        unit_price_cents=product.price_cents,
        cost_cents=packs * product.price_cents,
        replaces_product_id=replaces,
        alternatives=alternatives,
    )
