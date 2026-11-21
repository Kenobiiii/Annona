# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which meals are planned this week, and how much of a day's energy each one carries.

Users choose the days ("only Monday to Friday"), drop a slot for the whole week ("no afternoon
snack") or for some days ("no dinner on Tuesday, Thursday and Friday"). Both the shopping
optimiser and the planner use the resulting *day-equivalents*: the share of daily energy that
the planned meals represent.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from annona_core.domain import MealSlot

# Project choice (configurable; no single authoritative source): Spanish four-meal pattern.
DEFAULT_SLOT_SHARES: dict[MealSlot, Decimal] = {
    MealSlot.BREAKFAST: Decimal("0.25"),
    MealSlot.LUNCH: Decimal("0.35"),
    MealSlot.SNACK: Decimal("0.10"),
    MealSlot.DINNER: Decimal("0.30"),
}
SLOT_ORDER = [MealSlot.BREAKFAST, MealSlot.LUNCH, MealSlot.SNACK, MealSlot.DINNER]


class PlannedSlot(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: date
    slot: MealSlot


class MealSchedule(BaseModel):
    """The planned (day, slot) pairs of one week, starting on Monday."""

    model_config = ConfigDict(frozen=True)

    week_start: date
    slots: tuple[PlannedSlot, ...]
    shares: dict[MealSlot, Decimal] = Field(default_factory=lambda: dict(DEFAULT_SLOT_SHARES))

    @model_validator(mode="after")
    def _check(self) -> MealSchedule:
        if self.week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        end = self.week_start + timedelta(days=6)
        for s in self.slots:
            if not self.week_start <= s.day <= end:
                raise ValueError(f"{s.day} is outside the week of {self.week_start}")
        if len(set(self.slots)) != len(self.slots):
            raise ValueError("duplicate (day, slot)")
        if not self.slots:
            raise ValueError("no meals planned")
        return self

    @classmethod
    def build(
        cls,
        week_start: date,
        *,
        weekdays: Iterable[int] = range(7),  # 0 = Monday
        skip_slots: Iterable[MealSlot] = (),
        skip: Iterable[tuple[int, MealSlot]] = (),  # (weekday, slot)
        shares: dict[MealSlot, Decimal] | None = None,
    ) -> MealSchedule:
        skip_slots, skip = set(skip_slots), set(skip)
        slots = tuple(
            PlannedSlot(day=week_start + timedelta(days=wd), slot=slot)
            for wd in sorted(set(weekdays))
            for slot in SLOT_ORDER
            if slot not in skip_slots and (wd, slot) not in skip
        )
        return cls(week_start=week_start, slots=slots, shares=shares or dict(DEFAULT_SLOT_SHARES))

    @property
    def days(self) -> list[date]:
        return sorted({s.day for s in self.slots})

    def slots_on(self, day: date) -> list[MealSlot]:
        return [s.slot for s in self.slots if s.day == day]

    def day_share(self, day: date) -> Decimal:
        """Share of that day's energy covered by its planned meals (1 = all four)."""
        return sum((self.shares[s] for s in self.slots_on(day)), Decimal(0))

    @property
    def day_equivalents(self) -> Decimal:
        """Sum of day shares: 5 full days without 3 dinners = 5 - 3 x 0.30 = 4.1."""
        return sum((self.day_share(d) for d in self.days), Decimal(0))
