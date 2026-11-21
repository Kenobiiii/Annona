# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build an optimiser :class:`Problem` from the database (the core optimiser has no I/O)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlmodel import Session

from annona_core.nutrition import daily_targets, weekly_targets
from annona_core.optimizer import Offer, OptimizerSettings, Problem
from annona_core.planner import MealSchedule

from ..db.repositories import (
    HouseholdRepository,
    NotFoundError,
    SqlPantryRepository,
    SqlPriceRepository,
    SqlProductRepository,
    UserProfileRepository,
)


def build_problem(
    session: Session,
    *,
    household_id: int,
    store_id: str,
    on_date: date,
    budget_cents: int | None = None,
    settings: OptimizerSettings | None = None,
    schedule: MealSchedule | None = None,
) -> Problem:
    """Offers = every product of ``store_id`` with its latest price in the household currency.

    With a ``schedule``, targets cover only the planned meals (its day-equivalents) and the
    fruit-and-vegetable minimum covers its days.
    """
    household = HouseholdRepository(session).get(household_id)
    if household is None:
        raise NotFoundError(f"household {household_id} not found")
    members = list(UserProfileRepository(session).list(household_id=household_id))
    if not members:
        raise ValueError("the household has no members: add a profile first")
    prices = SqlPriceRepository(session)
    offers = []
    for product in SqlProductRepository(session).list(store_id=store_id):
        assert product.id is not None
        price = prices.latest(product.id, store_id)
        if price is not None and price.currency == household.currency:
            offers.append(Offer(product=product, price_cents=price.amount_cents))
    settings = settings or OptimizerSettings()
    days = schedule.day_equivalents if schedule else Decimal(7)
    if schedule:
        settings = settings.model_copy(update={"days": len(schedule.days)})
    targets = weekly_targets([daily_targets(m, on_date) for m in members], days=days)
    return Problem(
        offers=offers,
        pantry=list(SqlPantryRepository(session).for_household(household_id)),
        members=members,
        targets=targets,
        budget_cents=household.weekly_budget_cents if budget_cents is None else budget_cents,
        currency=household.currency,
        settings=settings,
    )
