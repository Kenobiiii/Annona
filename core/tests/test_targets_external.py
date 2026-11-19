# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cross-check against worked examples published by independent third parties.

These are not authoritative sources (the authoritative one is Mifflin et al. 1990, already used in
test_targets.py); they check that our implementation agrees with how others apply the same formula.
Pages consulted on 2026-11-19. A page that published arithmetically wrong examples
(primecalcpro.com) was deliberately not used.

Some pages round intermediate terms (e.g. 6.25 x 178 = 1112.5 -> "1,113"), so their totals are
compared with a tolerance of 1 kcal; pages that show exact terms are compared exactly.
"""

from datetime import date
from decimal import Decimal

import pytest

from annona_core.domain import ActivityLevel, Goal, Sex, UserProfile
from annona_core.nutrition import TargetSettings, bmr_mifflin_st_jeor, daily_targets

CALCFYI_F = "https://calcfyi.com/formula/mifflin-st-jeor-female/"
CALCFYI_M = "https://calcfyi.com/formula/mifflin-st-jeor-male/"
ACIBADEM = (
    "https://acibademinternational.com/blog/"
    "how-to-calculate-your-bmr-by-hand-and-what-the-number-actually-changes/"
)

# (source, sex, age, weight kg, height cm, published BMR, tolerance)
PUBLISHED_BMR = [
    (CALCFYI_F, Sex.FEMALE, 28, "62", "165", "1350.25", "0"),
    (CALCFYI_F, Sex.FEMALE, 50, "70", "160", "1289", "0"),
    (CALCFYI_M, Sex.MALE, 30, "80", "175", "1748.75", "0"),
    (CALCFYI_M, Sex.MALE, 45, "95", "180", "1855", "0"),
    (CALCFYI_M, Sex.MALE, 35, "80", "178", "1742", "1"),  # page says "about 1,742" (exact 1742.5)
    (ACIBADEM, Sex.FEMALE, 40, "70", "165", "1370", "1"),  # page rounds 1031.25 -> 1,031
    (ACIBADEM, Sex.MALE, 35, "82", "178", "1763", "1"),  # page rounds 1112.5 -> 1,113
]


@pytest.mark.parametrize(
    ("source", "sex", "age", "weight", "height", "published", "tolerance"), PUBLISHED_BMR
)
def test_bmr_matches_published_examples(source, sex, age, weight, height, published, tolerance):
    ours = bmr_mifflin_st_jeor(sex, Decimal(weight), Decimal(height), age)
    assert abs(ours - Decimal(published)) <= Decimal(tolerance), source


def _profile(sex: Sex, age: int, weight: str, height: str, activity: ActivityLevel) -> UserProfile:
    return UserProfile(
        household_id=1,
        name="Example",
        sex=sex,
        birth_date=date(2026 - age, 1, 1),
        height_cm=Decimal(height),
        weight_kg=Decimal(weight),
        activity=activity,
        goal=Goal.MAINTAIN,
        allergies_confirmed=True,
    )


def test_tee_matches_published_example_with_their_activity_factor():
    """calcfyi: 28 y woman, BMR 1350 x 1.375 (their "lightly active") ~= 1,857 kcal/day.

    Their factor is not one of our defaults, so it is injected through TargetSettings: this checks
    the BMR x factor pipeline, not the choice of factor.
    """
    theirs = TargetSettings(activity_factors={level: Decimal("1.375") for level in ActivityLevel})
    t = daily_targets(
        _profile(Sex.FEMALE, 28, "62", "165", ActivityLevel.LOW_ACTIVE), date(2026, 6, 1), theirs
    )
    assert t.bmr_kcal == 1350
    assert t.tee_kcal == 1857
    assert t.energy_kcal == 1857  # maintain


@pytest.mark.parametrize(
    ("factor", "published"),
    [("1.2", 1645), ("1.375", 1885), ("1.55", 2125), ("1.725", 2365), ("1.9", 2605)],
)
def test_tee_table_matches_published_approximations(factor, published):
    """acibademinternational: BMR 1,370 x factor, published rounded to ~5 kcal ("~1,645")."""
    theirs = TargetSettings(activity_factors={level: Decimal(factor) for level in ActivityLevel})
    t = daily_targets(
        _profile(Sex.FEMALE, 40, "70", "165", ActivityLevel.INACTIVE), date(2026, 6, 1), theirs
    )
    assert abs(t.tee_kcal - published) <= 5
