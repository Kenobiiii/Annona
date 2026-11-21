# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan a week end to end with FakeLLM. Products, prices and nutrition are SYNTHETIC."""

import json
import re
from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import select

from annona_core.domain import Equipment, HobType, MealSlot, PlanStatus
from annona_core.llm import FakeLLM, LLMClient, Tier
from annona_core.planner import MealSchedule
from annona_server.db import repositories as r
from annona_server.db.tables import MealPlanRow, PlannedMealRow, RecipeRow
from annona_server.planner import existing_plan, plan_and_store

from .test_optimize_db import household  # noqa: F401  (fixture)

MONDAY = date(2026, 11, 23)
MODELS = {Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}


SHARES = {
    "breakfast": Decimal("0.25"),
    "lunch": Decimal("0.35"),
    "snack": Decimal("0.10"),
    "dinner": Decimal("0.30"),
}


def even_split(request) -> str:
    """A naive 'model': every meal uses every product, splitting the planned amounts by each
    slot's share of daily energy (so the code's portion scaling stays at 1)."""
    text = request.messages[0].text
    products = [
        (int(m.group(1)), Decimal(m.group(2)))
        for m in re.finditer(r"^(\d+) \| [^|]+ \| \w+ \| \d+ \| (\d+) \|", text, re.M)
    ]
    slots = []
    for m in re.finditer(r"^- weekday (\d) \([^)]*\): (.+)$", text, re.M):
        slots += [(int(m.group(1)), s.strip()) for s in m.group(2).split(",")]
    total_share = sum(SHARES[slot] for _, slot in slots)
    meals = [
        {
            "weekday": wd,
            "slot": slot,
            "title": f"Plato {i}",
            "appliances": ["hob"],
            "ingredients": [
                {
                    "product_id": pid,
                    "amount": str(planned * SHARES[slot] / total_share * Decimal("0.97")),
                }
                for pid, planned in products
                if planned > 0
            ][:10],
            "summary": "Cocinar a fuego medio.",
        }
        for i, (wd, slot) in enumerate(slots)
    ]
    return json.dumps({"meals": meals})


@pytest.fixture
def kitchen(session, household):  # noqa: F811
    r.EquipmentRepository(session).add(
        Equipment(
            household_id=household.id, hob_type=HobType.CERAMIC, microwave=True, air_fryer=True
        )
    )
    return household


def test_plan_is_generated_verified_and_stored(session, kitchen):
    schedule = MealSchedule.build(MONDAY, weekdays=range(5), skip=[(1, MealSlot.DINNER)])
    llm = LLMClient(FakeLLM(responder=even_split), MODELS)
    week = plan_and_store(
        session, llm, household_id=kitchen.id, store_id="demo", schedule=schedule, on_date=MONDAY
    )
    assert week.shopping.status == "optimal"
    assert week.outcome.accepted, week.outcome.verification.issues
    assert week.plan_id is not None
    assert len(session.exec(select(RecipeRow)).all()) == len(schedule.slots) == 19
    assert len(session.exec(select(PlannedMealRow)).all()) == 19  # one member
    assert existing_plan(session, kitchen.id, MONDAY).id == week.plan_id

    # Shopping only covers the planned meals: 4.7 day-equivalents, not 7.
    assert schedule.day_equivalents == Decimal("4.7")


def test_regenerating_archives_the_previous_plan(session, kitchen):
    schedule = MealSchedule.build(MONDAY, weekdays=[0, 1])
    llm = LLMClient(FakeLLM(responder=even_split), MODELS)
    first = plan_and_store(
        session, llm, household_id=kitchen.id, store_id="demo", schedule=schedule, on_date=MONDAY
    )
    second = plan_and_store(
        session, llm, household_id=kitchen.id, store_id="demo", schedule=schedule, on_date=MONDAY
    )
    statuses = {p.id: p.status for p in session.exec(select(MealPlanRow)).all()}
    assert statuses[first.plan_id] == PlanStatus.ARCHIVED
    assert statuses[second.plan_id] == PlanStatus.ACTIVE


def test_infeasible_shop_produces_no_menu(session, kitchen):
    llm = LLMClient(FakeLLM([]), MODELS)
    week = plan_and_store(
        session,
        llm,
        household_id=kitchen.id,
        store_id="demo",
        schedule=MealSchedule.build(MONDAY),
        on_date=MONDAY,
        budget_cents=100,
    )
    assert week.outcome is None and week.shopping.status == "infeasible"
