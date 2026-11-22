# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request dependencies: database session, token check and the household."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlmodel import Session

from annona_core.domain import Household

from ..db.repositories import HouseholdRepository
from .errors import APIError


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def require_token(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
    expected = request.app.state.token
    if not expected:
        raise APIError(503, "not_configured", "set ANNONA_API_TOKEN on the server first")
    throttle = request.app.state.auth_throttle
    who = request.client.host if request.client else "unknown"
    if throttle.blocked(who):
        raise APIError(429, "too_many_attempts", "too many wrong tokens: wait a minute and retry")
    scheme, _, given = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(given.strip(), expected):
        throttle.record(who)
        raise APIError(401, "unauthorized", "missing or wrong bearer token")
    throttle.reset(who)


SessionDep = Annotated[Session, Depends(get_session)]


def current_household(session: SessionDep) -> Household:
    """This server serves one household (self-hosted)."""
    household = next(iter(HouseholdRepository(session).list()), None)
    if household is None:
        raise APIError(409, "setup_required", "create the household first: PUT /api/v1/household")
    return household


HouseholdDep = Annotated[Household, Depends(current_household)]
