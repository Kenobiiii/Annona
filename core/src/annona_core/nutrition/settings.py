# SPDX-License-Identifier: AGPL-3.0-or-later
"""Defaults for nutrition targets, each with its source. All of them can be overridden.

Sources
-------
[MSJ]   Mifflin MD, St Jeor ST, et al. "A new predictive equation for resting energy expenditure in
        healthy individuals." Am J Clin Nutr 1990;51(2):241-7. doi:10.1093/ajcn/51.2.241.
        Validated on 498 healthy adults aged 19-78.
[NASEM] National Academies of Sciences, Engineering, and Medicine. *Dietary Reference Intakes for
        Energy* (2023), Table 7-1: approximate PAL per adult category.
        https://www.nationalacademies.org/read/26818/chapter/9
[EFSA-E] EFSA NDA Panel. Scientific Opinion on Dietary Reference Values for energy.
        EFSA Journal 2013;11(1):3005 (uses PAL 1.4 / 1.6 / 1.8 / 2.0; consistent with NASEM).
[ISSN]  Jäger R, et al. "International Society of Sports Nutrition Position Stand: protein and
        exercise." J Int Soc Sports Nutr 2017;14:20. 1.4-2.0 g/kg/day for exercising individuals.
[EFSA-M] EFSA NDA Panel (2010). Reference intake ranges for adults: fat 20-35 % of energy,
        carbohydrates 45-60 % of energy.
[EU]    Regulation (EU) No 1169/2011, Annex XIV: energy conversion factors (protein 4, carbohydrate
        4, fat 9 kcal/g).

Project choices (no single authoritative source; documented as such):
* the goal adjustments (cut -15 %, bulk +10 %);
* the protein value picked inside the ISSN range for each goal;
* fat at 30 % of energy (inside the EFSA range);
* the +/-5 % tolerance around the calorie target;
* the calorie floor: never recommend less than the person's own BMR.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from annona_core.domain.enums import ActivityLevel, Goal

KCAL_PER_G_PROTEIN = Decimal(4)  # [EU]
KCAL_PER_G_CARBOHYDRATE = Decimal(4)  # [EU]
KCAL_PER_G_FAT = Decimal(9)  # [EU]

# Age range of the Mifflin-St Jeor study population [MSJ].
FORMULA_MIN_AGE = 19
FORMULA_MAX_AGE = 78
ADULT_AGE = 18


class TargetSettings(BaseModel):
    """Tunable defaults. Override with ``TargetSettings(field=...)``."""

    model_config = ConfigDict(frozen=True)

    activity_factors: dict[ActivityLevel, Decimal] = Field(
        default_factory=lambda: {
            ActivityLevel.INACTIVE: Decimal("1.4"),  # [NASEM] ~1.4
            ActivityLevel.LOW_ACTIVE: Decimal("1.6"),  # [NASEM] ~1.6
            ActivityLevel.ACTIVE: Decimal("1.75"),  # [NASEM] ~1.75
            ActivityLevel.VERY_ACTIVE: Decimal("2.05"),  # [NASEM] ~2.05
        }
    )
    goal_factors: dict[Goal, Decimal] = Field(
        default_factory=lambda: {
            Goal.CUT: Decimal("0.85"),  # project choice: -15 %
            Goal.MAINTAIN: Decimal(1),
            Goal.BULK: Decimal("1.10"),  # project choice: +10 %
        }
    )
    protein_g_per_kg: dict[Goal, Decimal] = Field(
        default_factory=lambda: {
            Goal.CUT: Decimal("2.0"),  # [ISSN] upper end helps keep lean mass in a deficit
            Goal.MAINTAIN: Decimal("1.6"),  # [ISSN] middle of 1.4-2.0
            Goal.BULK: Decimal("1.8"),  # [ISSN]
        }
    )
    fat_energy_share: Decimal = Decimal("0.30")  # inside [EFSA-M] 20-35 %
    fat_energy_share_min: Decimal = Decimal("0.20")  # [EFSA-M]
    fat_energy_share_max: Decimal = Decimal("0.35")  # [EFSA-M]
    carbohydrate_energy_share_min: Decimal = Decimal("0.45")  # [EFSA-M]
    carbohydrate_energy_share_max: Decimal = Decimal("0.60")  # [EFSA-M]
    energy_tolerance: Decimal = Decimal("0.05")  # project choice: +/-5 %
