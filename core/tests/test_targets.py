# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nutrition targets: hand-checked examples + property tests.

Hand calculation for case "male_active_maintain" (30 y, 80 kg, 180 cm, active, maintain):
    BMR = 10*80 + 6.25*180 - 5*30 + 5 = 1780
    TEE = 1780 * 1.75 = 3115  -> maintain -> 3115 kcal (range 2959.25-3270.75)
    protein = 1.6 * 80 = 128 g; fat = 3115 * 0.30 / 9 = 103.8 g
    carbs = (3115 - 128*4 - 103.83*9) / 4 = 417.1 g
"""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from annona_core.domain import ActivityLevel, Goal, Sex, UserProfile
from annona_core.nutrition import (
    WARNING_MESSAGES,
    TargetSettings,
    TargetWarning,
    bmr_mifflin_st_jeor,
    daily_targets,
    weekly_targets,
)

TODAY = date(2026, 11, 19)
W = TargetWarning


def person(
    sex: str,
    birth: date,
    height: int,
    weight: int,
    activity: str,
    goal: str,
    *,
    confirmed: bool = True,
) -> UserProfile:
    return UserProfile(
        household_id=1,
        name="Test",
        sex=Sex(sex),
        birth_date=birth,
        height_cm=Decimal(height),
        weight_kg=Decimal(weight),
        activity=ActivityLevel(activity),
        goal=Goal(goal),
        allergies_confirmed=confirmed,
    )


# (id, profile, kcal, kcal_min, kcal_max, protein, fat, carbs, warnings) - all hand-checked.
CASES = [
    (
        "male_active_maintain",
        person("male", date(1996, 6, 1), 180, 80, "active", "maintain"),
        (1780, 3115, 3115, 2959, 3271, 128, 104, 417),
        (),
    ),
    (
        # BMR = 600 + 1031.25 - 125 - 161 = 1345.25; *1.4 = 1883.35; *0.85 = 1600.85
        # carbs = (1600.85 - 480 - 480.25)/4 = 160.1 g = 40 % of energy -> below EFSA 45 %
        "female_inactive_cut",
        person("female", date(2001, 1, 1), 165, 60, "inactive", "cut"),
        (1345, 1883, 1601, 1521, 1681, 120, 53, 160),
        (W.CARBS_BELOW_REFERENCE,),
    ),
    (
        # BMR = 950 + 1156.25 - 200 + 5 = 1911.25; *2.05 = 3918.06; *1.10 = 4309.87
        "male_very_active_bulk",
        person("male", date(1986, 1, 1), 185, 95, "very_active", "bulk"),
        (1911, 3918, 4310, 4094, 4525, 171, 144, 583),
        (),
    ),
    (
        # 16 years old: BMR = 600 + 1062.5 - 80 + 5 = 1587.5; *1.75 = 2778.1
        "minor_still_calculated_with_warning",
        person("male", date(2010, 1, 1), 170, 60, "active", "maintain"),
        (1588, 2778, 2778, 2639, 2917, 96, 93, 390),
        (W.MINOR, W.AGE_OUTSIDE_FORMULA_RANGE),
    ),
]


@pytest.mark.parametrize(
    ("case", "profile", "expected", "warnings"), CASES, ids=[c[0] for c in CASES]
)
def test_hand_checked_examples(case, profile, expected, warnings):
    t = daily_targets(profile, TODAY)
    got = (
        t.bmr_kcal,
        t.tee_kcal,
        t.energy_kcal,
        t.energy_kcal_min,
        t.energy_kcal_max,
        t.protein_g,
        t.fat_g,
        t.carbohydrates_g,
    )
    assert got == tuple(Decimal(v) for v in expected)
    assert t.warnings == warnings


def test_bmr_formula_matches_paper():
    # Mifflin et al. 1990: 10*70 + 6.25*175 - 5*40 = 1593.75; male +5, female -161.
    assert bmr_mifflin_st_jeor(Sex.MALE, Decimal(70), Decimal(175), 40) == Decimal("1598.75")
    assert bmr_mifflin_st_jeor(Sex.FEMALE, Decimal(70), Decimal(175), 40) == Decimal("1432.75")


def test_floor_raises_target_to_bmr_and_warns():
    # A very aggressive cut (-40 %) on a small, inactive 70-year-old woman:
    # BMR = 500 + 937.5 - 350 - 161 = 926.5; TEE = 1297.1; *0.6 = 778.3 < BMR -> 927
    aggressive = TargetSettings(
        goal_factors={
            Goal.CUT: Decimal("0.6"),
            Goal.MAINTAIN: Decimal(1),
            Goal.BULK: Decimal("1.1"),
        }
    )
    profile = person("female", date(1956, 1, 1), 150, 50, "inactive", "cut")
    t = daily_targets(profile, TODAY, aggressive)
    assert t.energy_kcal == Decimal(927)
    assert t.energy_kcal_min == Decimal(927)
    assert W.RAISED_TO_BMR_FLOOR in t.warnings


def test_unconfirmed_allergies_warn():
    profile = person("male", date(1990, 1, 1), 180, 80, "active", "maintain", confirmed=False)
    assert W.ALLERGIES_NOT_CONFIRMED in daily_targets(profile, TODAY).warnings


def test_protein_and_fat_above_energy_sets_carbs_to_zero():
    extreme = TargetSettings(
        protein_g_per_kg={Goal.CUT: Decimal(6), Goal.MAINTAIN: Decimal(6), Goal.BULK: Decimal(6)}
    )
    t = daily_targets(
        person("female", date(1990, 1, 1), 160, 50, "inactive", "cut"), TODAY, extreme
    )
    assert t.carbohydrates_g == 0
    assert W.PROTEIN_AND_FAT_EXCEED_ENERGY in t.warnings


def test_every_warning_has_a_message():
    assert set(WARNING_MESSAGES) == set(TargetWarning)


def test_weekly_targets_for_household():
    a = daily_targets(person("male", date(1996, 6, 1), 180, 80, "active", "maintain"), TODAY)
    b = daily_targets(person("female", date(2001, 1, 1), 165, 60, "inactive", "cut"), TODAY)
    solo = weekly_targets([a])
    assert solo.energy_kcal == 3115 * 7
    home = weekly_targets([a, b])
    assert home.energy_kcal == (3115 + 1601) * 7
    assert home.protein_g == (128 + 120) * 7
    assert home.warnings == (W.CARBS_BELOW_REFERENCE,)
    with pytest.raises(ValueError):
        weekly_targets([])


# ------------------------------------------------------------------------------------ properties

profiles = st.builds(
    lambda sex, age, height, weight, activity, goal: person(
        sex, date(TODAY.year - age, 1, 1), height, weight, activity, goal
    ),
    sex=st.sampled_from(["male", "female"]),
    age=st.integers(min_value=19, max_value=78),
    height=st.integers(min_value=140, max_value=210),
    weight=st.integers(min_value=40, max_value=200),
    activity=st.sampled_from(list(ActivityLevel)),
    goal=st.sampled_from(list(Goal)),
)
LEVELS = list(ActivityLevel)


@given(profiles)
def test_more_activity_never_lowers_calories(profile):
    energies = [
        daily_targets(profile.model_copy(update={"activity": level}), TODAY).energy_kcal
        for level in LEVELS
    ]
    assert energies == sorted(energies)


@given(profiles, st.integers(min_value=1, max_value=50))
def test_more_weight_never_lowers_calories(profile, extra):
    heavier = profile.model_copy(update={"weight_kg": profile.weight_kg + extra})
    assert daily_targets(heavier, TODAY).energy_kcal >= daily_targets(profile, TODAY).energy_kcal


@given(profiles, st.integers(min_value=1, max_value=20))
def test_getting_older_never_raises_calories(profile, years):
    later = date(TODAY.year + years, TODAY.month, TODAY.day)
    assert daily_targets(profile, later).energy_kcal <= daily_targets(profile, TODAY).energy_kcal


@given(profiles)
def test_invariants(profile):
    t = daily_targets(profile, TODAY)
    assert t.energy_kcal >= t.bmr_kcal  # safety floor
    assert t.energy_kcal_min <= t.energy_kcal <= t.energy_kcal_max
    assert t.fat_g_min <= t.fat_g <= t.fat_g_max
    assert t.carbohydrates_g >= 0
    # Macros add up to the target (rounding each to whole grams costs at most ~9 kcal).
    macro_kcal = t.protein_g * 4 + t.fat_g * 9 + t.carbohydrates_g * 4
    if W.PROTEIN_AND_FAT_EXCEED_ENERGY not in t.warnings:
        assert abs(macro_kcal - t.energy_kcal) <= 9


def test_own_protein_target_replaces_the_goal_default():
    # 85 kg on a cut: default 2.0 g/kg = 170 g; own 1.5 g/kg = 127.5 -> 128 g (half-up).
    profile = person("male", date(2005, 1, 1), 185, 85, "active", "cut")
    assert daily_targets(profile, TODAY).protein_g == Decimal(170)
    own = profile.model_copy(update={"protein_g_per_kg": Decimal("1.5")})
    t = daily_targets(own, TODAY)
    assert t.protein_g == Decimal(128)
    assert t.energy_kcal == daily_targets(profile, TODAY).energy_kcal  # energy is unaffected


@pytest.mark.parametrize("value", ["0.5", "0.79", "3.1", "10"])
def test_own_protein_target_must_stay_in_a_sensible_range(value):
    data = person("male", date(2005, 1, 1), 185, 85, "active", "cut").model_dump()
    with pytest.raises(ValueError):
        UserProfile.model_validate({**data, "protein_g_per_kg": value})
