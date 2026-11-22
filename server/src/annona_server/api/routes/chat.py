# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chat: a streamed turn with the agent, and the confirmation of what it proposed."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from annona_core.agent import (
    ActionProposed,
    AgentMessage,
    Notice,
    TextDelta,
    ToolFinished,
    ToolStarted,
    TurnDone,
)
from annona_core.domain import PendingActionStatus
from annona_core.llm import Tier

from ...chat.actions import (
    ActionClosed,
    ActionNotFound,
    cancel,
    confirm,
    list_pending,
)
from ...chat.service import chat_turn
from ...tools import ToolContext
from ..deps import HouseholdDep, SessionDep
from ..errors import APIError

router = APIRouter(tags=["chat"])

MAX_MESSAGE_CHARS = 2000
MAX_HISTORY = 40


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=MAX_MESSAGE_CHARS)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    history: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=MAX_HISTORY,
        description="earlier turns (text only); the server keeps a rolling window of them",
    )
    tier: Literal["small", "large"] = Field(
        default="small", description="large = a more careful (and costlier) model"
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat", response_class=StreamingResponse)
def chat(body: ChatIn, request: Request, household: HouseholdDep) -> StreamingResponse:
    """One chat turn, streamed as server-sent events.

    Events: ``text`` (a piece of the answer), ``tool_start``/``tool_end`` (what is being looked up),
    ``action`` (a change proposed and waiting for confirmation), ``notice`` (a limit was reached),
    ``done`` (the end, with the totals) and ``error``.
    """
    state = request.app.state
    history = [AgentMessage(m.role, m.text) for m in body.history]

    def events() -> Iterator[str]:
        try:
            for event in chat_turn(
                state.engine,
                model_factory=state.chat_model_factory,
                llm_factory=state.llm_factory,
                runner=state.runner,
                history=history,
                text=body.message,
                tier=Tier(body.tier),
            ):
                if isinstance(event, TextDelta):
                    yield _sse("text", {"delta": event.text})
                elif isinstance(event, ToolStarted):
                    yield _sse("tool_start", {"id": event.call_id, "name": event.name})
                elif isinstance(event, ToolFinished):
                    yield _sse(
                        "tool_end",
                        {
                            "id": event.call_id,
                            "name": event.name,
                            "ok": event.ok,
                            "summary": event.summary,
                        },
                    )
                elif isinstance(event, ActionProposed):
                    yield _sse(
                        "action",
                        {"id": event.action_id, "tool": event.name, "summary": event.summary},
                    )
                elif isinstance(event, Notice):
                    yield _sse("notice", {"code": event.text})
                elif isinstance(event, TurnDone):
                    r = event.result
                    yield _sse(
                        "done",
                        {
                            "text": r.text,
                            "stopped": r.stopped,
                            "iterations": r.iterations,
                            "tool_calls": len(r.tool_calls),
                            "proposals": r.proposals,
                            "input_tokens": r.input_tokens,
                            "output_tokens": r.output_tokens,
                        },
                    )
        except Exception as error:  # the stream must end with something the app can show
            yield _sse("error", {"message": f"{type(error).__name__}: {error}"[:300]})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ActionOut(BaseModel):
    id: int
    tool: str
    summary: str
    status: PendingActionStatus
    result: dict | None = None


def _out(action) -> ActionOut:
    return ActionOut(
        id=action.id,
        tool=action.tool,
        summary=action.summary,
        status=action.status,
        result=action.result,
    )


@router.get("/chat/actions", response_model=list[ActionOut])
def pending_actions(session: SessionDep, household: HouseholdDep) -> list[ActionOut]:
    """Changes the agent proposed that still wait for a decision."""
    return [_out(a) for a in list_pending(session, household)]


@router.post("/chat/actions/{action_id}/confirm", response_model=ActionOut)
def confirm_action(
    action_id: int, request: Request, session: SessionDep, household: HouseholdDep
) -> ActionOut:
    """Execute the proposed change, exactly as it was described. Once."""
    state = request.app.state
    ctx = ToolContext(
        session=session,
        household=household,
        llm_factory=state.llm_factory,
        runner=state.runner,
        today=date.today(),
    )
    try:
        return _out(confirm(session, household, ctx, action_id))
    except ActionNotFound as error:
        raise APIError(404, "not_found", str(error)) from error
    except ActionClosed as error:
        raise APIError(409, "action_closed", str(error)) from error


@router.post("/chat/actions/{action_id}/cancel", response_model=ActionOut)
def cancel_action(action_id: int, session: SessionDep, household: HouseholdDep) -> ActionOut:
    try:
        return _out(cancel(session, household, action_id))
    except ActionNotFound as error:
        raise APIError(404, "not_found", str(error)) from error
    except ActionClosed as error:
        raise APIError(409, "action_closed", str(error)) from error
