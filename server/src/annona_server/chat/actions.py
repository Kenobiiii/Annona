# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pending actions: create, list, confirm, cancel. The only place a proposed change is executed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from annona_core.domain import Household, PendingAction, PendingActionStatus

from ..db.repositories import PendingActionRepository
from ..planner.recipes import MealNotFound
from ..planner.swap import SwapError, SwapProposal, apply_swap
from ..tools import TOOLS, ToolContext, ToolError


class ActionNotFound(LookupError):
    pass


class ActionClosed(Exception):
    """The action was already confirmed, cancelled or failed."""


def create_pending(
    session: Session,
    household: Household,
    *,
    kind: str,
    tool: str,
    payload: dict[str, Any],
    summary: str,
) -> PendingAction:
    action = PendingActionRepository(session).add(
        PendingAction(
            household_id=household.id, kind=kind, tool=tool, payload=payload, summary=summary
        )
    )
    session.commit()  # visible to the confirm request right away
    return action


def _owned(session: Session, household: Household, action_id: int) -> PendingAction:
    action = PendingActionRepository(session).get(action_id)
    if action is None or action.household_id != household.id:
        raise ActionNotFound(f"action {action_id} not found")
    return action


def list_pending(session: Session, household: Household) -> list[PendingAction]:
    return [
        a
        for a in PendingActionRepository(session).list(household_id=household.id)
        if a.status == PendingActionStatus.PENDING
    ]


def cancel(session: Session, household: Household, action_id: int) -> PendingAction:
    action = _owned(session, household, action_id)
    if action.status != PendingActionStatus.PENDING:
        raise ActionClosed(f"action {action_id} is already {action.status}")
    return PendingActionRepository(session).update(
        action.model_copy(
            update={"status": PendingActionStatus.CANCELLED, "resolved_at": datetime.now(UTC)}
        )
    )


def confirm(
    session: Session, household: Household, ctx: ToolContext, action_id: int
) -> PendingAction:
    """Execute the stored change exactly as it was shown, once."""
    action = _owned(session, household, action_id)
    if action.status != PendingActionStatus.PENDING:
        raise ActionClosed(f"action {action_id} is already {action.status}")
    repo = PendingActionRepository(session)
    try:
        if action.kind == "swap":
            apply_swap(session, household, SwapProposal.model_validate(action.payload))
            result: dict[str, Any] = {"applied": True}
        else:
            tool = TOOLS[action.tool]
            output = tool.run(ctx, action.payload)
            result = output.model_dump(mode="json")
    except (ToolError, SwapError, MealNotFound) as error:
        message = getattr(error, "message", None) or str(error)
        failed = repo.update(
            action.model_copy(
                update={
                    "status": PendingActionStatus.FAILED,
                    "result": {"error": message},
                    "resolved_at": datetime.now(UTC),
                }
            )
        )
        session.commit()
        return failed
    done = repo.update(
        action.model_copy(
            update={
                "status": PendingActionStatus.CONFIRMED,
                "result": result,
                "resolved_at": datetime.now(UTC),
            }
        )
    )
    session.commit()
    return done


__all__ = [
    "ActionClosed",
    "ActionNotFound",
    "cancel",
    "confirm",
    "create_pending",
    "list_pending",
]
