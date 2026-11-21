# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request and response bodies shared by several routes."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from annona_core.domain import MealSlot


class Page[T](BaseModel):
    items: list[T]
    page: int
    size: int
    total: int


def paginate[T](items: list[T], page: int, size: int) -> Page[T]:
    start = (page - 1) * size
    return Page(items=items[start : start + size], page=page, size=size, total=len(items))


class ScheduleIn(BaseModel):
    """Which meals to plan. weekday 0 = Monday."""

    week_start: date
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)))
    skip_slots: list[MealSlot] = Field(default_factory=list)
    skip: list[tuple[int, MealSlot]] = Field(default_factory=list)


class ShoppingOptions(BaseModel):
    store_id: str
    budget_cents: int | None = Field(default=None, ge=0)
    variety: Literal["basic", "balanced", "high"] = "basic"
    health_limits: bool = False


class JobAccepted(BaseModel):
    job_id: str
    status_url: str
