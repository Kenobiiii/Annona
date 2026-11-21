# SPDX-License-Identifier: AGPL-3.0-or-later
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from annona_server.db import migrate
from annona_server.db.engine import make_engine


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    """A fresh database built through the real migrations (not ``create_all``)."""
    migrate.upgrade(db_url)
    eng = make_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture
def shop(engine):
    """SYNTHETIC store "demo": the foods of test_optimize_db with manual prices."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from annona_core.domain import (
        NutritionFacts,
        NutritionSource,
        Price,
        PriceSource,
        Product,
        Unit,
    )
    from annona_server.db.engine import session_scope
    from annona_server.db.repositories import SqlPriceRepository, SqlProductRepository

    from .test_optimize_db import FOODS

    with session_scope(engine) as s:
        products, prices = SqlProductRepository(s), SqlPriceRepository(s)
        for i, (name, cat, grams, kcal, p, f, c, cents) in enumerate(FOODS):
            prod = products.add(
                Product(
                    name=name,
                    category=cat,
                    store_id="demo",
                    store_sku=str(i),
                    package_amount=Decimal(grams),
                    package_unit=Unit.G,
                    allergens=[],
                    nutrition=NutritionFacts(
                        energy_kcal=Decimal(kcal),
                        protein_g=Decimal(p),
                        fat_g=Decimal(f),
                        carbohydrates_g=Decimal(c),
                        source=NutritionSource.MANUAL,
                    ),
                )
            )
            prices.add(
                Price(
                    product_id=prod.id,
                    store_id="demo",
                    amount_cents=cents,
                    source=PriceSource.MANUAL,
                    observed_at=datetime(2026, 11, 20, tzinfo=UTC),
                )
            )
