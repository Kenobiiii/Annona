# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stores, background jobs, price refresh and AI usage."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request, status
from pydantic import BaseModel
from sqlmodel import select

from annona_providers.registry import available_providers

from ...db.tables import JobRow, LlmUsageRow
from ...refresh import refresh
from ..deps import SessionDep
from ..errors import APIError
from ..schemas import JobAccepted

router = APIRouter(tags=["system"])


class StoreOut(BaseModel):
    id: str
    name: str
    country: str | None
    currency: str
    opt_in: bool
    notice: str | None
    attribution: str | None


@router.get("/stores", response_model=list[StoreOut])
def stores() -> list[StoreOut]:
    """Installed supermarket providers. Opt-in ones show the notice the user must accept."""
    return [
        StoreOut(
            id=i.id,
            name=i.name,
            country=i.country,
            currency=i.currency,
            opt_in=i.opt_in,
            notice=i.notice,
            attribution=i.attribution,
        )
        for i in available_providers()
    ]


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    result: dict[str, Any] | None
    error: str | None


@router.get("/jobs/{job_id}", response_model=JobOut)
def job(job_id: str, session: SessionDep) -> JobOut:
    row = session.get(JobRow, job_id)
    if row is None:
        raise APIError(404, "not_found", f"job {job_id} not found")
    return JobOut(id=row.id, kind=row.kind, status=row.status, result=row.result, error=row.error)


@router.post("/prices/refresh", status_code=status.HTTP_202_ACCEPTED, response_model=JobAccepted)
def refresh_prices(request: Request) -> JobAccepted:
    """Refresh prices now with the providers in ANNONA_REFRESH_PROVIDERS (also runs daily)."""
    job_id = request.app.state.runner.submit("price_refresh", {}, lambda s, _: refresh(s))
    return JobAccepted(job_id=job_id, status_url=f"/api/v1/jobs/{job_id}")


class UsageRow(BaseModel):
    task: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


@router.get("/llm/usage", response_model=list[UsageRow])
def llm_usage(session: SessionDep) -> list[UsageRow]:
    """AI calls and known cost per task and model (cache hits excluded)."""
    totals: dict[tuple[str, str], UsageRow] = {}
    for row in session.exec(select(LlmUsageRow).where(LlmUsageRow.cached == False)):  # noqa: E712
        key = (row.task, row.model)
        acc = totals.setdefault(
            key,
            UsageRow(
                task=row.task,
                model=row.model,
                calls=0,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal(0),
            ),
        )
        acc.calls += 1
        acc.input_tokens += row.input_tokens or 0
        acc.output_tokens += row.output_tokens or 0
        acc.cost_usd += row.cost_usd or Decimal(0)
    return sorted(totals.values(), key=lambda r: (r.task, r.model))
