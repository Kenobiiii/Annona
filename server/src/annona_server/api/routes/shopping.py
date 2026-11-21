# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cheapest weekly shop (deterministic optimiser, fast: no job needed)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from annona_core.optimizer import OptimizerSettings, Result, optimise
from annona_core.planner import MealSchedule

from ...optimize import build_problem
from ..deps import HouseholdDep, SessionDep
from ..schemas import ScheduleIn, ShoppingOptions

router = APIRouter(tags=["shopping"])


class OptimiseIn(ShoppingOptions):
    schedule: ScheduleIn | None = None


class OptimiseOut(BaseModel):
    budget_cents: int
    result: Result


def to_schedule(body: ScheduleIn) -> MealSchedule:
    return MealSchedule.build(
        body.week_start, weekdays=body.weekdays, skip_slots=body.skip_slots, skip=body.skip
    )


@router.post("/shopping/optimise", response_model=OptimiseOut)
def optimise_shop(body: OptimiseIn, session: SessionDep, household: HouseholdDep) -> OptimiseOut:
    """Cheapest purchase meeting the household's targets at one store, or why that is impossible."""
    problem = build_problem(
        session,
        household_id=household.id,
        store_id=body.store_id,
        on_date=body.schedule.week_start if body.schedule else date.today(),
        budget_cents=body.budget_cents,
        settings=OptimizerSettings(variety=body.variety, health_limits=body.health_limits),
        schedule=to_schedule(body.schedule) if body.schedule else None,
    )
    return OptimiseOut(budget_cents=problem.budget_cents, result=optimise(problem))
