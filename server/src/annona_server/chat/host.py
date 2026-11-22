# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connects the agent loop to the tool registry. Writes are proposals: nothing here runs them."""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session

from annona_core.agent import ToolCall, ToolOutcome, ToolSpec
from annona_core.domain import Household

from ..tools import TOOLS, Tool, ToolContext, ToolError
from .actions import create_pending, list_pending
from .describe import describe_write

# Arguments only the person may set: the model never sees or sends them.
_HIDDEN = {"confirm"}


def tool_spec(tool: Tool) -> ToolSpec:
    schema = tool.input.model_json_schema()

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "title" or isinstance(v, dict)}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    schema = strip(schema)
    for hidden in _HIDDEN:
        schema.get("properties", {}).pop(hidden, None)
    return ToolSpec(name=tool.name, description=tool.description, parameters=schema)


def compact(output: Any) -> str:
    data = (
        output.model_dump(mode="json", exclude_none=True)
        if hasattr(output, "model_dump")
        else output
    )
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


class RegistryHost:
    """Implements :class:`annona_core.agent.ToolHost` over the shared tool registry."""

    def __init__(
        self, session: Session, household: Household, ctx: ToolContext, lang: str = "es"
    ) -> None:
        self.session, self.household, self.ctx, self.lang = session, household, ctx, lang

    def specs(self) -> list[ToolSpec]:
        return [tool_spec(t) for t in TOOLS.values()]

    def is_write(self, name: str) -> bool:
        tool = TOOLS[name]
        return not tool.read_only and not tool.proposes

    def _args(self, tool: Tool, call: ToolCall) -> dict[str, Any]:
        raw = {k: v for k, v in (call.arguments or {}).items() if k not in _HIDDEN}
        return tool.input.model_validate(raw).model_dump(mode="json", exclude_none=True)

    def run(self, call: ToolCall) -> ToolOutcome:
        tool = TOOLS[call.name]
        try:
            args = self._args(tool, call)
            output = tool.run(self.ctx, args)
        except ToolError as error:
            return ToolOutcome(False, f"error: {error}", str(error)[:120])
        except ValueError as error:  # invalid arguments (pydantic)
            return ToolOutcome(False, f"error: invalid arguments: {error}", "invalid arguments")
        action_id = getattr(output, "action_id", None) if tool.proposes else None
        summary = call.name
        if action_id is not None:
            from ..db.repositories import PendingActionRepository

            action = PendingActionRepository(self.session).get(action_id)
            summary = action.summary if action else summary
        return ToolOutcome(True, compact(output), summary, action_id=action_id)

    def propose(self, call: ToolCall) -> ToolOutcome:
        tool = TOOLS[call.name]
        try:
            args = self._args(tool, call)
        except ValueError as error:
            return ToolOutcome(False, f"error: invalid arguments: {error}", "invalid arguments")
        payload = dict(args)
        if "confirm" in tool.input.model_fields:
            payload["confirm"] = True  # set by the confirmation, never by the model
        summary = describe_write(self.session, self.household, call.name, args, self.lang)
        same = next(
            (
                a
                for a in list_pending(self.session, self.household)
                if a.kind == "tool" and a.tool == call.name and a.payload == payload
            ),
            None,
        )
        if same is not None:  # asking twice must not queue the change twice
            return ToolOutcome(
                True,
                f"already pending the person's confirmation (action {same.id}): {same.summary} "
                "Do not propose it again; tell the person to confirm it in the app.",
                same.summary,
                action_id=None,
            )
        action = create_pending(
            self.session,
            self.household,
            kind="tool",
            tool=call.name,
            payload=payload,
            summary=summary,
        )
        return ToolOutcome(
            True,
            f"pending the person's confirmation (action {action.id}): {summary} "
            "Nothing has changed yet. Tell the person to confirm it in the app.",
            summary,
            action_id=action.id,
        )
