# SPDX-License-Identifier: AGPL-3.0-or-later
"""Daily and weekly calorie/macro targets from a :class:`UserProfile`. Pure functions, no LLM.

Pipeline (defaults and sources in :mod:`annona_core.nutrition.settings`):

1. BMR with Mifflin-St Jeor: ``10*kg + 6.25*cm - 5*age + 5`` (male) or ``... - 161`` (female).
2. Total energy expenditure: ``BMR * activity factor`` (PAL).
3. Goal adjustment: ``TEE * goal factor`` (cut / maintain / bulk).
4. Safety floor: the target is never below the person's BMR; if the goal would push it lower it
   is raised to the BMR and a warning is returned.
5. Protein: ``g/kg * body weight``; fat: a share of energy; carbohydrates: the remaining energy.

Values are informational, not medical advice. Results are rounded half-up to whole kcal / grams
only at the end.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from annona_core.domain.enums import Sex
from annona_core.domain.models import UserProfile

from .settings import (
    ADULT_AGE,
    FORMULA_MAX_AGE,
    FORMULA_MIN_AGE,
    KCAL_PER_G_CARBOHYDRATE,
    KCAL_PER_G_FAT,
    KCAL_PER_G_PROTEIN,
    TargetSettings,
)

DEFAULT_SETTINGS = TargetSettings()
_ONE = Decimal(1)


class TargetWarning(StrEnum):
    """Machine-readable warnings; the app shows a translated message for each."""

    MINOR = "minor"
    AGE_OUTSIDE_FORMULA_RANGE = "age_outside_formula_range"
    RAISED_TO_BMR_FLOOR = "raised_to_bmr_floor"
    CARBS_BELOW_REFERENCE = "carbs_below_reference"
    CARBS_ABOVE_REFERENCE = "carbs_above_reference"
    PROTEIN_AND_FAT_EXCEED_ENERGY = "protein_and_fat_exceed_energy"
    ALLERGIES_NOT_CONFIRMED = "allergies_not_confirmed"


WARNING_MESSAGES: dict[TargetWarning, str] = {
    TargetWarning.MINOR: (
        "You are under 18. These formulas and targets are designed for adults and do not have the "
        "same effect while you are still growing. Talk to a doctor or dietitian."
    ),
    TargetWarning.AGE_OUTSIDE_FORMULA_RANGE: (
        "The BMR formula was validated on adults aged 19-78; your estimate is less certain."
    ),
    TargetWarning.RAISED_TO_BMR_FLOOR: (
        "Your goal would put calories below your resting energy needs, so the target was raised "
        "to that minimum."
    ),
    TargetWarning.CARBS_BELOW_REFERENCE: (
        "Carbohydrates are below the 45-60 % of energy reference range (EFSA)."
    ),
    TargetWarning.CARBS_ABOVE_REFERENCE: (
        "Carbohydrates are above the 45-60 % of energy reference range (EFSA)."
    ),
    TargetWarning.PROTEIN_AND_FAT_EXCEED_ENERGY: (
        "Protein and fat alone exceed the calorie target; carbohydrates were set to zero. "
        "Review your settings."
    ),
    TargetWarning.ALLERGIES_NOT_CONFIRMED: (
        "Please confirm your allergies (or that you have none) before planning meals."
    ),
}


class DailyTargets(BaseModel):
    model_config = ConfigDict(frozen=True)

    bmr_kcal: Decimal
    tee_kcal: Decimal  # total energy expenditure before the goal adjustment
    energy_kcal: Decimal
    energy_kcal_min: Decimal
    energy_kcal_max: Decimal
    protein_g: Decimal
    fat_g: Decimal
    fat_g_min: Decimal
    fat_g_max: Decimal
    carbohydrates_g: Decimal
    warnings: tuple[TargetWarning, ...] = ()


class WeeklyTargets(BaseModel):
    model_config = ConfigDict(frozen=True)

    energy_kcal: Decimal
    energy_kcal_min: Decimal
    energy_kcal_max: Decimal
    protein_g: Decimal
    fat_g: Decimal
    fat_g_min: Decimal
    fat_g_max: Decimal
    carbohydrates_g: Decimal
    warnings: tuple[TargetWarning, ...] = ()


def _round(value: Decimal) -> Decimal:
    return value.quantize(_ONE, rounding=ROUND_HALF_UP)


def bmr_mifflin_st_jeor(sex: Sex, weight_kg: Decimal, height_cm: Decimal, age: int) -> Decimal:
    """Resting energy expenditure in kcal/day (unrounded)."""
    base = Decimal(10) * weight_kg + Decimal("6.25") * height_cm - Decimal(5) * age
    return base + (Decimal(5) if sex == Sex.MALE else Decimal(-161))


def daily_targets(
    profile: UserProfile, on_date: date, settings: TargetSettings = DEFAULT_SETTINGS
) -> DailyTargets:
    """Daily calorie and macro targets for one person on ``on_date`` (age is taken from it)."""
    warnings: list[TargetWarning] = []
    age = profile.age_on(on_date)
    if age < ADULT_AGE:
        warnings.append(TargetWarning.MINOR)
    if not FORMULA_MIN_AGE <= age <= FORMULA_MAX_AGE:
        warnings.append(TargetWarning.AGE_OUTSIDE_FORMULA_RANGE)
    if not profile.allergies_confirmed:
        warnings.append(TargetWarning.ALLERGIES_NOT_CONFIRMED)

    bmr = bmr_mifflin_st_jeor(profile.sex, profile.weight_kg, profile.height_cm, age)
    tee = bmr * settings.activity_factors[profile.activity]
    energy = tee * settings.goal_factors[profile.goal]
    if energy < bmr:
        energy = bmr.quantize(_ONE, rounding=ROUND_CEILING)
        warnings.append(TargetWarning.RAISED_TO_BMR_FLOOR)

    energy_min = max(energy * (_ONE - settings.energy_tolerance), bmr)
    energy_max = energy * (_ONE + settings.energy_tolerance)

    protein = profile.weight_kg * settings.protein_g_per_kg[profile.goal]
    fat = energy * settings.fat_energy_share / KCAL_PER_G_FAT
    carb_energy = energy - protein * KCAL_PER_G_PROTEIN - fat * KCAL_PER_G_FAT
    if carb_energy < 0:
        carb_energy = Decimal(0)
        warnings.append(TargetWarning.PROTEIN_AND_FAT_EXCEED_ENERGY)
    else:
        share = carb_energy / energy
        if share < settings.carbohydrate_energy_share_min:
            warnings.append(TargetWarning.CARBS_BELOW_REFERENCE)
        elif share > settings.carbohydrate_energy_share_max:
            warnings.append(TargetWarning.CARBS_ABOVE_REFERENCE)

    return DailyTargets(
        bmr_kcal=_round(bmr),
        tee_kcal=_round(tee),
        energy_kcal=_round(energy),
        energy_kcal_min=_round(energy_min),
        energy_kcal_max=_round(energy_max),
        protein_g=_round(protein),
        fat_g=_round(fat),
        fat_g_min=_round(energy * settings.fat_energy_share_min / KCAL_PER_G_FAT),
        fat_g_max=_round(energy * settings.fat_energy_share_max / KCAL_PER_G_FAT),
        carbohydrates_g=_round(carb_energy / KCAL_PER_G_CARBOHYDRATE),
        warnings=tuple(warnings),
    )


_SUMMED = (
    "energy_kcal",
    "energy_kcal_min",
    "energy_kcal_max",
    "protein_g",
    "fat_g",
    "fat_g_min",
    "fat_g_max",
    "carbohydrates_g",
)


def weekly_targets(members: list[DailyTargets], days: int | Decimal = 7) -> WeeklyTargets:
    """Targets for one person or a whole household (sum of its members) over ``days``.

    ``days`` may be fractional "day-equivalents" when only some meals are planned (see
    :mod:`annona_core.planner.schedule`); totals are rounded half-up to whole units.
    """
    if not members:
        raise ValueError("at least one member is required")
    factor = Decimal(days)
    totals = {
        name: _round(sum((getattr(m, name) for m in members), Decimal(0)) * factor)
        for name in _SUMMED
    }
    warnings = tuple(dict.fromkeys(w for m in members for w in m.warnings))
    return WeeklyTargets(**totals, warnings=warnings)
