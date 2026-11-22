# SPDX-License-Identifier: AGPL-3.0-or-later
"""EXTENSION POINT (not implemented): the cheapest basket across several stores.

The goal, from the roadmap: compare the whole-basket cost of each selected store, and how much is
saved by splitting the shop between two of them. The building block already exists:
:func:`annona_core.shopping.price_basket` prices the same needs at any one store, so an
implementation can call it once per store and combine the results. What is missing is the
combination (which products to take from which store, with a minimum saving that justifies a second
trip) and the product decisions around it (how many stores, travel cost).

Add the implementation here; the API route and the app screen are intentionally not built yet.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .basket import Basket


class StoreComparison(BaseModel):
    """What a comparison across stores should return."""

    model_config = ConfigDict(frozen=True)

    baskets: tuple[Basket, ...]  # one per store, cheapest first
    best_single_store: str
    best_split: tuple[str, str] | None  # two stores whose split is cheaper than any single one
    saving_cents: int  # of the best split versus the best single store (0 if none)


def cheapest_split(baskets: list[Basket]) -> StoreComparison:
    """EXTENSION POINT: compare per-store baskets and find the best split between two stores."""
    raise NotImplementedError(
        "cheapest basket across stores is an extension point; see annona_core/shopping/compare.py"
    )
