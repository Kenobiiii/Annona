# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from annona_core.domain import MealSlot as S
from annona_core.planner import MealSchedule

MONDAY = date(2026, 11, 23)


def test_full_week():
    s = MealSchedule.build(MONDAY)
    assert len(s.slots) == 28 and len(s.days) == 7
    assert s.day_equivalents == 7


def test_users_example_five_days_without_some_dinners():
    """ "Only 5 days, and Tuesday, Thursday and Friday without dinner"."""
    s = MealSchedule.build(
        MONDAY, weekdays=range(5), skip=[(1, S.DINNER), (3, S.DINNER), (4, S.DINNER)]
    )
    assert len(s.days) == 5 and len(s.slots) == 20 - 3
    assert s.slots_on(date(2026, 11, 24)) == [S.BREAKFAST, S.LUNCH, S.SNACK]
    assert s.day_equivalents == Decimal("4.1")  # 5 - 3 x 0.30


def test_no_snack_all_week():
    s = MealSchedule.build(MONDAY, skip_slots=[S.SNACK])
    assert all(slot.slot != S.SNACK for slot in s.slots)
    assert s.day_equivalents == Decimal("6.3")  # 7 x 0.90


def test_validation():
    with pytest.raises(ValidationError):
        MealSchedule.build(date(2026, 11, 24))  # not a Monday
    with pytest.raises(ValidationError):
        MealSchedule.build(MONDAY, weekdays=[])  # nothing planned
