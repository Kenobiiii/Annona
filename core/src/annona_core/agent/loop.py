# SPDX-License-Identifier: AGPL-3.0-or-later
"""The agent loop: model -> tools -> model, with hard limits and no way to change data.

Safety is structural, not a matter of asking the model nicely:

* a tool that *writes* is never executed by the loop: the host turns the call into a pending
  proposal and the model is told it awaits confirmation. Execution exists only behind the person's
  confirmation, outside this module;
* tool results are data: they are fed back as ``tool`` messages and truncated;
* the number of model calls, tool calls and output tokens per turn are capped.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from .types import AgentMessage, ModelReply, TextDelta, ToolCall, ToolSpec


@dataclass(frozen=True)
class AgentCaps:
    max_iterations: int = 5  # model calls that may ask for tools in one turn
    max_output_tokens: int = 3000  # total completion tokens over the turn
    max_tool_chars: int = 6000  # a tool result is cut to this (~1,500 tokens)
    max_tool_calls_per_step: int = 4
    window_messages: int = 10  # rolling window of the conversation sent to the model
    max_tokens_per_call: int = 1200


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    content: str  # what the model sees
    summary: str = ""  # one line for the person ("3 items in the pantry")
    action_id: int | None = None  # set when the call created a pending proposal


class ToolHost(Protocol):
    def specs(self) -> list[ToolSpec]: ...

    def is_write(self, name: str) -> bool: ...

    def run(self, call: ToolCall) -> ToolOutcome:
        """Execute a read-only tool. Must not change data."""
        ...

    def propose(self, call: ToolCall) -> ToolOutcome:
        """Turn a write tool call into a pending proposal. Must not change data."""
        ...


class ChatModel(Protocol):
    def stream(
        self,
        system: str,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
        *,
        max_tokens: int,
    ) -> Iterator[TextDelta | ModelReply]:
        """Yield text deltas as they arrive, then one final :class:`ModelReply`."""
        ...


@dataclass(frozen=True)
class ToolStarted:
    call_id: str
    name: str


@dataclass(frozen=True)
class ToolFinished:
    call_id: str
    name: str
    ok: bool
    summary: str


@dataclass(frozen=True)
class ActionProposed:
    action_id: int
    name: str
    summary: str


@dataclass(frozen=True)
class Notice:
    text: str  # a limit was reached, in plain words for the app to show


@dataclass
class TurnResult:
    text: str  # the final assistant text of the turn
    stopped: str  # "answered" | "max_iterations" | "max_tokens"
    iterations: int = 0
    tool_calls: list[tuple[str, dict | None, bool]] = field(default_factory=list)
    proposals: list[int] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal | None = Decimal(0)
    latency_ms: int = 0


@dataclass(frozen=True)
class TurnDone:
    result: TurnResult


Event = TextDelta | ToolStarted | ToolFinished | ActionProposed | Notice | TurnDone


def window(history: list[AgentMessage], size: int) -> list[AgentMessage]:
    """The last ``size`` messages, starting at a user message (never with an orphan reply)."""
    kept = history[-size:] if size > 0 else []
    while kept and kept[0].role != "user":
        kept = kept[1:]
    return kept


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... cut: {len(text) - limit} more characters]"


def _add(total: Decimal | None, more: Decimal | None) -> Decimal | None:
    return None if total is None or more is None else total + more


def run_turn(
    model: ChatModel,
    host: ToolHost,
    history: list[AgentMessage],
    user_text: str,
    *,
    system: str,
    caps: AgentCaps = AgentCaps(),
) -> Iterator[Event]:
    """One user turn: yields events (streamed text, tool progress, proposals), then TurnDone."""
    messages = [*window(history, caps.window_messages), AgentMessage("user", user_text)]
    specs = host.specs()
    known = {s.name for s in specs}
    result = TurnResult(text="", stopped="answered")
    tools_allowed = True
    reply = ModelReply()

    for step in range(caps.max_iterations + 1):
        tools_allowed = step < caps.max_iterations and result.output_tokens < caps.max_output_tokens
        if not tools_allowed and step > 0:
            result.stopped = (
                "max_tokens" if result.output_tokens >= caps.max_output_tokens else "max_iterations"
            )
            messages.append(
                AgentMessage(
                    "user", "Answer now with what you already know; do not use any more tools."
                )
            )
        reply = ModelReply()
        for item in model.stream(
            system, messages, specs if tools_allowed else [], max_tokens=caps.max_tokens_per_call
        ):
            if isinstance(item, TextDelta):
                yield item
            else:
                reply = item
        result.iterations += 1
        result.input_tokens += reply.input_tokens
        result.output_tokens += reply.output_tokens
        result.latency_ms += reply.latency_ms
        result.cost_usd = _add(result.cost_usd, reply.cost_usd)
        result.text = reply.text
        if not reply.tool_calls or not tools_allowed:
            break
        messages.append(AgentMessage("assistant", reply.text, tuple(reply.tool_calls)))
        for call in reply.tool_calls[: caps.max_tool_calls_per_step]:
            yield ToolStarted(call.id, call.name)
            outcome = _execute(host, call, known)
            result.tool_calls.append((call.name, call.arguments, outcome.ok))
            if outcome.action_id is not None:
                result.proposals.append(outcome.action_id)
                yield ActionProposed(outcome.action_id, call.name, outcome.summary)
            yield ToolFinished(call.id, call.name, outcome.ok, outcome.summary)
            messages.append(
                AgentMessage(
                    "tool",
                    _clip(outcome.content, caps.max_tool_chars),
                    tool_call_id=call.id,
                    name=call.name,
                )
            )
        for call in reply.tool_calls[caps.max_tool_calls_per_step :]:
            messages.append(
                AgentMessage(
                    "tool",
                    "skipped: too many tool calls at once; ask again if needed",
                    tool_call_id=call.id,
                    name=call.name,
                )
            )
    if result.stopped != "answered":
        yield Notice("limit")
    yield TurnDone(result)


def _execute(host: ToolHost, call: ToolCall, known: set[str]) -> ToolOutcome:
    if call.name not in known:
        return ToolOutcome(False, f"error: there is no tool called {call.name!r}", "unknown tool")
    if call.arguments is None:
        return ToolOutcome(
            False,
            "error: the arguments were not valid JSON; call the tool again with a JSON object",
            "bad arguments",
        )
    try:
        if host.is_write(call.name):
            return host.propose(call)  # a proposal, never an execution
        return host.run(call)
    except Exception as error:  # a failing tool is information for the model, not a crash
        return ToolOutcome(False, f"error: {error}", "failed")


def parse_arguments(raw: str) -> dict | None:
    """Tool arguments as sent by a model: a JSON object, or None if they cannot be parsed."""
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
