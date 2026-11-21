# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plan-generation job, shared by the REST API and the tool registry (MCP / chat)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from sqlmodel import Session

from annona_core.domain import MealSlot
from annona_core.llm import LLMClient
from annona_core.optimizer import OptimizerSettings
from annona_core.planner import MealSchedule

from . import plan_and_store

KIND = "plan_week"


def schedule_from(params: dict[str, Any]) -> MealSchedule:
    s = params["schedule"]
    return MealSchedule.build(
        date.fromisoformat(str(s["week_start"])),
        weekdays=s.get("weekdays") or list(range(7)),
        skip_slots=[MealSlot(x) for x in s.get("skip_slots") or []],
        skip=[(int(d), MealSlot(slot)) for d, slot in s.get("skip") or []],
    )


def plan_job(
    llm_factory: Callable[[Session], LLMClient], household_id: int
) -> Callable[[Session, dict[str, Any]], dict[str, Any]]:
    def run(session: Session, params: dict[str, Any]) -> dict[str, Any]:
        schedule = schedule_from(params)
        week = plan_and_store(
            session,
            llm_factory(session),
            household_id=household_id,
            store_id=params["store_id"],
            schedule=schedule,
            on_date=schedule.week_start,
            budget_cents=params.get("budget_cents"),
            settings=OptimizerSettings(
                variety=params.get("variety", "basic"),
                health_limits=bool(params.get("health_limits")),
            ),
        )
        result: dict[str, Any] = {
            "plan_id": week.plan_id,
            "shopping_status": week.shopping.status,
            "shortfalls": [s.model_dump(mode="json") for s in week.shopping.shortfalls],
        }
        if week.outcome is not None:
            result |= {
                "accepted": week.outcome.accepted,
                "issues": [i.message for i in week.outcome.verification.issues],
                "extra_purchases": [e.__dict__ for e in week.outcome.extra_purchases],
            }
        return result

    return run
