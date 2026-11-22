# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cheapest basket across stores: each store alone, and the best split between two.

Pure code on top of :func:`annona_core.shopping.price_basket`: the same needs are priced at every
selected store, then compared. A basket that cannot supply everything is ranked after the ones
that can (a basket missing items is not "cheaper"). For a split, every need is bought where its
packs cost least among the two stores, and it only counts if the saving over the best single store
is at least ``min_saving_cents``: a second trip has to be worth it.
"""

from __future__ import annotations

from itertools import combinations

from pydantic import BaseModel, ConfigDict

from .basket import Basket, BasketLine

DEFAULT_MIN_SAVING_CENTS = 100  # project choice (configurable): less than 1 EUR is not worth a trip


class SplitPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    stores: tuple[str, str]
    assignments: dict[str, tuple[BasketLine, ...]]  # store -> what to buy there
    totals: dict[str, int]  # store -> cents
    total_cents: int


class StoreComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    baskets: tuple[Basket, ...]  # one per store, complete baskets first, then cheapest
    best_single_store: str | None  # None when no store can supply everything
    best_single_cents: int | None
    split: SplitPlan | None  # a split that saves at least ``min_saving_cents``
    saving_cents: int  # of the split over the best single store (0 if there is none)


def _key(basket: Basket) -> tuple[int, int, str]:
    return (len(basket.unavailable), basket.total_cents, basket.store_id)


def _by_need(basket: Basket) -> dict[int, BasketLine]:
    return {line.need_product_id: line for line in basket.lines}


def _split(first: Basket, second: Basket, universe: set[int]) -> SplitPlan | None:
    """Buy each need where its packs cost least among the two stores (ties: the first store)."""
    lines_a, lines_b = _by_need(first), _by_need(second)
    if not universe <= set(lines_a) | set(lines_b):
        return None  # this pair cannot supply everything
    picked: dict[str, list[BasketLine]] = {first.store_id: [], second.store_id: []}
    for need in sorted(universe):
        a, b = lines_a.get(need), lines_b.get(need)
        if a is not None and (b is None or a.cost_cents <= b.cost_cents):
            picked[first.store_id].append(a)
        elif b is not None:
            picked[second.store_id].append(b)
    if not all(picked.values()):
        return None  # one store would sell nothing: that is just a single-store basket
    totals = {s: sum(line.cost_cents for line in ls) for s, ls in picked.items()}
    return SplitPlan(
        stores=(first.store_id, second.store_id),
        assignments={s: tuple(ls) for s, ls in picked.items()},
        totals=totals,
        total_cents=sum(totals.values()),
    )


def compare_baskets(
    baskets: list[Basket], *, min_saving_cents: int = DEFAULT_MIN_SAVING_CENTS
) -> StoreComparison:
    """Compare per-store baskets of the SAME needs."""
    if not baskets:
        raise ValueError("at least one basket is required")
    ranked = sorted(baskets, key=_key)
    best = next((b for b in ranked if not b.unavailable), None)
    universe = {line.need_product_id for b in ranked for line in b.lines} | {
        u.product_id for b in ranked for u in b.unavailable
    }
    split: SplitPlan | None = None
    for first, second in combinations(ranked, 2):
        plan = _split(first, second, universe)
        if plan is None:
            continue
        if best is not None and best.total_cents - plan.total_cents < min_saving_cents:
            continue  # not worth a second trip
        if split is None or plan.total_cents < split.total_cents:
            split = plan
    return StoreComparison(
        baskets=tuple(ranked),
        best_single_store=best.store_id if best else None,
        best_single_cents=best.total_cents if best else None,
        split=split,
        saving_cents=best.total_cents - split.total_cents if best and split else 0,
    )
