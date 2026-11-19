# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nutrition targets, diet/allergy filtering and the activity quiz. Pure functions, no LLM.

Informational only; not medical advice.
"""

from .activity_quiz import TYPICAL_DAY_EXAMPLES, WorkType, suggest_activity_level
from .diet import ExclusionReason, ProductDecision, check_product, is_product_allowed
from .settings import TargetSettings
from .targets import (
    WARNING_MESSAGES,
    DailyTargets,
    TargetWarning,
    WeeklyTargets,
    bmr_mifflin_st_jeor,
    daily_targets,
    weekly_targets,
)

__all__ = [
    "TYPICAL_DAY_EXAMPLES",
    "WARNING_MESSAGES",
    "DailyTargets",
    "ExclusionReason",
    "ProductDecision",
    "TargetSettings",
    "TargetWarning",
    "WeeklyTargets",
    "WorkType",
    "bmr_mifflin_st_jeor",
    "check_product",
    "daily_targets",
    "is_product_allowed",
    "suggest_activity_level",
    "weekly_targets",
]
