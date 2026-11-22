# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weekly meal planning: schedule, LLM draft schema, deterministic portions and verification."""

from .draft import Appliance, DraftIngredient, DraftMeal, PlanDraft
from .planner import TASK, ExtraPurchase, PlanOutcome, TopUp, plan_week
from .prompt import LANGUAGES, build_prompt
from .recipe import (
    MealIngredient,
    RecipeContext,
    RecipeDraft,
    RecipeOutcome,
    RecipeSettings,
    RenderedRecipe,
    RenderedStep,
    generate_recipe,
    render_recipe,
    to_method,
    validate_recipe,
)
from .scale import scale_to_energy
from .schedule import DEFAULT_SLOT_SHARES, MealSchedule, PlannedSlot
from .topup import make_top_up
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
    "ExtraPurchase",
    "FinalMeal",
    "Issue",
    "MealSchedule",
    "Member",
    "PlanContext",
    "PlanDraft",
    "PlanOutcome",
    "PlannedSlot",
    "Portion",
    "TopUp",
    "Verification",
    "available_appliances",
    "build_prompt",
    "make_top_up",
    "plan_week",
    "validate_recipe",
    "to_method",
    "render_recipe",
    "generate_recipe",
    "RenderedStep",
    "RenderedRecipe",
    "RecipeSettings",
    "RecipeOutcome",
    "RecipeDraft",
    "RecipeContext",
    "MealIngredient",
    "scale_to_energy",
    "verify",
]
