# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weekly meal planning: schedule, LLM draft schema, deterministic portions and verification."""

from .draft import Appliance, DraftIngredient, DraftMeal, PlanDraft
from .planner import TASK, PlanOutcome, plan_week
from .prompt import LANGUAGES, build_prompt
from .schedule import DEFAULT_SLOT_SHARES, MealSchedule, PlannedSlot
from .verify import (
    Available,
    FinalMeal,
    Issue,
    Member,
    PlanContext,
    Portion,
    Verification,
    available_appliances,
    verify,
)

__all__ = [
    "DEFAULT_SLOT_SHARES",
    "LANGUAGES",
    "TASK",
    "Appliance",
    "Available",
    "DraftIngredient",
    "DraftMeal",
    "FinalMeal",
    "Issue",
    "MealSchedule",
    "Member",
    "PlanContext",
    "PlanDraft",
    "PlanOutcome",
    "PlannedSlot",
    "Portion",
    "Verification",
    "available_appliances",
    "build_prompt",
    "plan_week",
    "verify",
]
