# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None  # None: the model sent arguments that are not valid JSON
    raw_arguments: str = ""


@dataclass(frozen=True)
class AgentMessage:
    """One message of the conversation. ``tool`` messages exist only inside a turn."""

    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


class ToolSpec(BaseModel):
    """A tool as the model sees it: a name, a one-line description and a JSON schema."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass
class ModelReply:
    """What the model said in one call: text, and the tools it wants to use."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal | None = Decimal(0)
    latency_ms: int = 0
    model: str = ""
