# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open Food Facts client against REAL responses recorded on 2026-11-19 (ODbL 1.0)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx

from annona_core.domain import Allergen, NutritionSource, Unit
from annona_providers.testing import FixtureTransport
from annona_server.db.tables import OffCacheRow
from annona_server.ingest.off import OpenFoodFactsClient, off_user_agent

FIXTURES = Path(__file__).parent / "fixtures" / "off"


class Counting(httpx.BaseTransport):
    def __init__(self) -> None:
        self.inner = FixtureTransport(FIXTURES)
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return self.inner.handle_request(request)


def test_found_product_with_nutrition_and_allergens(session):
    off = OpenFoodFactsClient(session, transport=FixtureTransport(FIXTURES))
    p = off.lookup("8480000229670")
    assert p.name == "Batido cacao 0% azúcares añadidos"
    assert p.allergens == [Allergen.MILK]
    n = p.nutrition
    assert (n.basis, n.energy_kcal, n.protein_g, n.salt_g) == (
        Unit.ML,
        Decimal(37),
        Decimal("2.3"),
        Decimal("0.1975"),
    )
    assert n.source == NutritionSource.OFF and n.source_ref == "off:8480000229670"


def test_not_found_is_cached_and_not_asked_again(session):
    transport = Counting()
    off = OpenFoodFactsClient(session, transport=transport)
    assert off.lookup("8402001002090") is None
    assert off.lookup("8402001002090") is None
    assert transport.calls == 1
    assert session.get(OffCacheRow, "8402001002090").found is False


def test_cache_expires_after_30_days(session):
    transport = Counting()
    now = [datetime(2026, 11, 19, tzinfo=UTC)]
    off = OpenFoodFactsClient(session, transport=transport, now=lambda: now[0])
    off.lookup("8480000340245")
    now[0] += timedelta(days=29)
    off.lookup("8480000340245")
    assert transport.calls == 1
    now[0] += timedelta(days=2)
    off.lookup("8480000340245")
    assert transport.calls == 2


def test_user_agent_uses_contact_email_from_env(monkeypatch):
    monkeypatch.setenv("ANNONA_CONTACT_EMAIL", "someone@example.org")
    assert off_user_agent().endswith("(someone@example.org)")
    monkeypatch.setenv("ANNONA_CONTACT_EMAIL", "")
    assert "github.com" in off_user_agent()
