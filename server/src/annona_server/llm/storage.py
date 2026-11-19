# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database-backed response cache and usage log for the LLM client."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import Session, col, select

from annona_core.llm import UsageRecord

from ..db.tables import LlmCacheRow, LlmUsageRow


class SqlResponseCache:
    def __init__(self, session: Session, now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.session = session
        self._now = now

    def get(self, key: str) -> str | None:
        row = self.session.get(LlmCacheRow, key)
        return None if row is None else row.response

    def set(self, key: str, model: str, text: str) -> None:
        row = self.session.get(LlmCacheRow, key) or LlmCacheRow(
            key=key, model=model, response=text, created_at=self._now()
        )
        row.response, row.model, row.created_at = text, model, self._now()
        self.session.add(row)
        self.session.flush()


class SqlUsageSink:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, record: UsageRecord) -> None:
        self.session.add(LlmUsageRow(**{**record.__dict__, "tier": str(record.tier)}))
        self.session.flush()


def spent_usd(session: Session, task_prefix: str = "") -> Decimal:
    """Known cost of recorded calls (unknown costs are not included)."""
    rows = session.exec(
        select(LlmUsageRow.cost_usd).where(
            col(LlmUsageRow.cost_usd).is_not(None),
            func.substr(LlmUsageRow.task, 1, len(task_prefix)) == task_prefix,
        )
    )
    return sum((r for r in rows if r is not None), Decimal(0))
