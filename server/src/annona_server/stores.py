# SPDX-License-Identifier: AGPL-3.0-or-later
"""Using a store plugin from the app: connect it, search it, add one product from it.

This is the "explicit user request" path of opt-in plugins (CLAUDE.md, LEGAL/ETHICS): the person
accepts the plugin's notice in the app, says where they shop, and then searches for ONE product at
a time (e.g. a receipt line that is not in the catalogue). Nothing here downloads a catalogue.
Searches are cached for a day, and each store keeps a single polite client, so requests stay
spaced however many screens ask.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from annona_core.domain import Household, Product, StoreConnection
from annona_providers.base import ProviderError, ProviderInfo, SupermarketProvider
from annona_providers.registry import available_providers, create_provider

from .db.repositories import SqlProductRepository, StoreConnectionRepository
from .ingest import ingest

SEARCH_LIMIT = 8
SEARCH_TTL_SECONDS = 24 * 3600
SEARCH_CACHE_SIZE = 500

ProviderFactory = Callable[[str, dict[str, str]], SupermarketProvider]


def default_factory(store_id: str, config: dict[str, str]) -> SupermarketProvider:
    # Only called once the person has accepted the notice (checked by StoreAccess).
    return create_provider(store_id, accept_notice=True, **config)


class StoreNotFound(LookupError):
    pass


class NoticeRequired(Exception):
    """An opt-in plugin is used before the person accepted its notice."""


class NotConnected(Exception):
    """The store needs a postal code (or the notice) before it can be searched."""


class StoreUnavailable(Exception):
    """The store did not answer, or refused the request."""


@dataclass(frozen=True)
class Found:
    store_sku: str
    name: str
    brand: str | None
    package_amount: str | None
    package_unit: str | None
    image_url: str | None
    product_id: int | None  # already in the catalogue


def store_info(store_id: str) -> ProviderInfo:
    for info in available_providers():
        if info.id == store_id:
            return info
    raise StoreNotFound(f"store {store_id!r} is not installed")


def get_connection(session: Session, household: Household, store_id: str) -> StoreConnection | None:
    store_info(store_id)
    return next(
        (
            c
            for c in StoreConnectionRepository(session).list(household_id=household.id)
            if c.store_id == store_id
        ),
        None,
    )


class StoreAccess:
    """Long-lived (one per server): provider clients and the search cache."""

    def __init__(self, factory: ProviderFactory = default_factory) -> None:
        self._factory = factory
        self._providers: dict[tuple[str, str], SupermarketProvider] = {}
        self._cache: OrderedDict[tuple[str, str, str], tuple[float, list[Any]]] = OrderedDict()
        self._lock = threading.Lock()

    # -- connection -------------------------------------------------------------------------

    def connect(
        self,
        session: Session,
        household: Household,
        store_id: str,
        *,
        postal_code: str | None,
        accept_notice: bool,
    ) -> StoreConnection:
        """Save where the household shops and, for opt-in plugins, that the notice was accepted.

        The postal code is resolved once (one request) to the store's own location code, so
        later searches do not repeat it.
        """
        info = store_info(store_id)
        assert household.id is not None
        current = get_connection(session, household, store_id)
        accepted = current.notice_accepted_at if current else None
        if info.opt_in and accepted is None:
            if not accept_notice:
                raise NoticeRequired(info.notice or f"{store_id} needs its notice accepted")
            accepted = datetime.now(UTC)
        code = postal_code.strip().upper() if postal_code else None
        if info.supports_postcode and not code:
            raise NotConnected(f"{info.name} needs a postal code: prices depend on it")
        location = current.location if current and current.postal_code == code else None
        if code and location is None:
            location = self._resolve(store_id, code)
        values = {
            "household_id": household.id,
            "store_id": store_id,
            "postal_code": code,
            "location": location,
            "notice_accepted_at": accepted,
            "updated_at": datetime.now(UTC),
        }
        repo = StoreConnectionRepository(session)
        if current is None:
            return repo.add(StoreConnection(**values))
        return repo.update(current.model_copy(update=values))

    def disconnect(self, session: Session, household: Household, store_id: str) -> None:
        """Forget the postal code and withdraw the accepted notice."""
        current = get_connection(session, household, store_id)
        if current is not None and current.id is not None:
            StoreConnectionRepository(session).delete(current.id)

    def _resolve(self, store_id: str, postal_code: str) -> str | None:
        try:
            provider = self._factory(store_id, {"postal_code": postal_code})
        except (ProviderError, ValueError) as error:
            raise StoreUnavailable(str(error)) from error
        location = getattr(provider, "warehouse", None)
        if location is None:  # a store without location codes: keep this client
            with self._lock:
                self._providers[(store_id, postal_code)] = provider
            return None
        with self._lock:
            self._providers.setdefault((store_id, str(location)), provider)
        return str(location)

    # -- use ---------------------------------------------------------------------------------

    def _provider(self, session: Session, household: Household, store_id: str):
        info = store_info(store_id)
        connection = get_connection(session, household, store_id)
        if info.opt_in and (connection is None or connection.notice_accepted_at is None):
            raise NoticeRequired(info.notice or f"{store_id} needs its notice accepted")
        if info.supports_postcode and (connection is None or not connection.postal_code):
            raise NotConnected(f"{info.name} needs a postal code: prices depend on it")
        key = (
            store_id,
            (connection.location or connection.postal_code or "") if connection else "",
        )
        with self._lock:
            provider = self._providers.get(key)
        if provider is None:
            if connection and connection.location:
                config = {"warehouse": connection.location}
            elif connection and connection.postal_code:
                config = {"postal_code": connection.postal_code}
            else:
                config = {}
            try:
                provider = self._factory(store_id, config)
            except (ProviderError, ValueError) as error:
                raise StoreUnavailable(str(error)) from error
            with self._lock:
                provider = self._providers.setdefault(key, provider)
        return key, provider

    def search(
        self, session: Session, household: Household, store_id: str, query: str
    ) -> list[Found]:
        """One search in the store (cached for a day), marking products already stored."""
        text = " ".join(query.split())
        if len(text) < 2:
            return []
        (store, location), provider = self._provider(session, household, store_id)
        cache_key = (store, location, text.casefold())
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and now - hit[0] < SEARCH_TTL_SECONDS:
                self._cache.move_to_end(cache_key)
                items = hit[1]
            else:
                items = None
        if items is None:
            try:
                items = list(provider.search(text, limit=SEARCH_LIMIT))
            except ProviderError as error:
                raise StoreUnavailable(str(error)) from error
            with self._lock:
                self._cache[cache_key] = (now, items)
                while len(self._cache) > SEARCH_CACHE_SIZE:
                    self._cache.popitem(last=False)
        products = SqlProductRepository(session)
        found = []
        for item in items[:SEARCH_LIMIT]:
            stored = products.get_by_store_sku(store_id, item.store_sku)
            found.append(
                Found(
                    store_sku=item.store_sku,
                    name=item.name,
                    brand=item.brand,
                    package_amount=str(item.package_amount) if item.package_amount else None,
                    package_unit=str(item.package_unit) if item.package_unit else None,
                    image_url=item.image_url,
                    product_id=stored.id if stored else None,
                )
            )
        return found

    def add_product(
        self,
        session: Session,
        household: Household,
        store_id: str,
        store_sku: str,
        *,
        off: Any = None,
    ) -> Product:
        """Store ONE product of the store, with its price and (by barcode) Open Food Facts data."""
        _, provider = self._provider(session, household, store_id)
        try:
            ingest(session, provider, skus=[store_sku], off=off)
        except ProviderError as error:
            raise StoreUnavailable(str(error)) from error
        product = SqlProductRepository(session).get_by_store_sku(store_id, store_sku)
        if product is None:
            raise StoreNotFound(f"{store_id} has no product {store_sku!r}")
        return product
