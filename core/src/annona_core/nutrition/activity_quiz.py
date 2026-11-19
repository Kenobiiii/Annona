# SPDX-License-Identifier: AGPL-3.0-or-later
"""A two-question quiz that suggests an :class:`ActivityLevel`. The user can always override it.

Question 2 shows the example days of the National Academies' *Dietary Reference Intakes for Energy*
(2023), Table 7-1. The report itself warns that no valid tool exists to classify an individual
precisely and that its examples suit occupations with little physical exertion; hence question 1.

Project rule (not from the report): a physically demanding job moves the suggestion up one level.
"""

from __future__ import annotations

from enum import StrEnum

from annona_core.domain.enums import ActivityLevel

# "Activities of daily living" in the report: about 30 min of walking plus ~90 min of light to
# moderate activity such as household tasks.
DAILY_LIVING = "everyday activity (about 30 min walking + 90 min of light tasks such as housework)"

TYPICAL_DAY_EXAMPLES: dict[ActivityLevel, str] = {
    ActivityLevel.INACTIVE: f"Only {DAILY_LIVING}",
    ActivityLevel.LOW_ACTIVE: f"{DAILY_LIVING.capitalize()} + 60-80 min brisk walking",
    ActivityLevel.ACTIVE: (
        f"{DAILY_LIVING.capitalize()} + 30-50 min brisk walking + 45 min moderate cycling "
        "+ 40 min of a light sport (e.g. doubles tennis)"
    ),
    ActivityLevel.VERY_ACTIVE: (
        f"{DAILY_LIVING.capitalize()} + 45 min moderate cycling + ~25 min jogging "
        "+ 60 min of a light sport (e.g. doubles tennis)"
    ),
}


class WorkType(StrEnum):
    SEATED = "seated"
    ON_FEET = "on_feet"
    PHYSICAL = "physical"


WORK_TYPE_LABELS: dict[WorkType, str] = {
    WorkType.SEATED: "Mostly sitting (office, studying, driving)",
    WorkType.ON_FEET: "On my feet or moving around (shop, teaching, care work)",
    WorkType.PHYSICAL: "Physically demanding (construction, farming, warehouse, delivery on foot)",
}

_ORDER = list(ActivityLevel)


def suggest_activity_level(typical_day: ActivityLevel, work: WorkType) -> ActivityLevel:
    """The closest example day, one level up for physically demanding work (capped)."""
    if work != WorkType.PHYSICAL:
        return typical_day
    return _ORDER[min(_ORDER.index(typical_day) + 1, len(_ORDER) - 1)]
