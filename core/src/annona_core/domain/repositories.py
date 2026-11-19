# SPDX-License-Identifier: AGPL-3.0-or-later
"""Repository interfaces.

``core`` only declares what storage must offer; implementations live outside it (the SQLite one in
``annona_server.db``). Repositories never commit: the caller owns the transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from .models import PantryItem, Price, Product


class Repository[T](Protocol):
    """Basic CRUD for one entity type. ``add``/``update`` return the stored entity."""

    def add(self, entity: T) -> T: ...

    def get(self, entity_id: int) -> T | None: ...

    def list(self, **filters: Any) -> Sequence[T]: ...

    def update(self, entity: T) -> T: ...

    def delete(self, entity_id: int) -> None: ...


class ProductRepository(Repository[Product], Protocol):
    def get_by_store_sku(self, store_id: str, store_sku: str) -> Product | None: ...

    def find_by_ean(self, ean: str) -> Sequence[Product]: ...

    def get_by_nutrition_ref(self, source_ref: str) -> Product | None: ...

    def search(self, text: str, limit: int = 20) -> Sequence[Product]: ...


class PriceRepository(Repository[Price], Protocol):
    def latest(self, product_id: int, store_id: str | None = None) -> Price | None: ...

    def history(self, product_id: int, store_id: str | None = None) -> Sequence[Price]: ...


class PantryRepository(Repository[PantryItem], Protocol):
    def for_household(self, household_id: int) -> Sequence[PantryItem]: ...
