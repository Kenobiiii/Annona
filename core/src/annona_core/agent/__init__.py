# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chat agent: a bounded tool-use loop. Pure logic; the model and the tools are injected."""

from .fake import FakeChatModel
from .loop import (
    ActionProposed,
    AgentCaps,
    ChatModel,
    Notice,
    ToolFinished,
    ToolHost,
    ToolOutcome,
    ToolStarted,
    TurnDone,
    TurnResult,
    run_turn,
    window,
)
from .prompt import system_prompt
from .types import AgentMessage, ModelReply, TextDelta, ToolCall, ToolSpec

__all__ = [
    "ActionProposed",
    "AgentCaps",
    "AgentMessage",
    "ChatModel",
    "FakeChatModel",
    "ModelReply",
    "Notice",
    "TextDelta",
    "ToolCall",
    "ToolFinished",
    "ToolHost",
    "ToolOutcome",
    "ToolSpec",
    "ToolStarted",
    "TurnDone",
    "TurnResult",
    "run_turn",
    "system_prompt",
    "window",
]
