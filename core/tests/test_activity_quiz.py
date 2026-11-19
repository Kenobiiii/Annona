# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from annona_core.domain import ActivityLevel as A
from annona_core.nutrition import TYPICAL_DAY_EXAMPLES, WorkType, suggest_activity_level
from annona_core.nutrition.activity_quiz import WORK_TYPE_LABELS


def test_every_level_and_work_type_has_text():
    assert set(TYPICAL_DAY_EXAMPLES) == set(A)
    assert set(WORK_TYPE_LABELS) == set(WorkType)


@pytest.mark.parametrize(
    ("day", "work", "expected"),
    [
        (A.INACTIVE, WorkType.SEATED, A.INACTIVE),
        (A.LOW_ACTIVE, WorkType.ON_FEET, A.LOW_ACTIVE),
        (A.INACTIVE, WorkType.PHYSICAL, A.LOW_ACTIVE),
        (A.ACTIVE, WorkType.PHYSICAL, A.VERY_ACTIVE),
        (A.VERY_ACTIVE, WorkType.PHYSICAL, A.VERY_ACTIVE),  # capped
    ],
)
def test_suggestion(day, work, expected):
    assert suggest_activity_level(day, work) == expected
