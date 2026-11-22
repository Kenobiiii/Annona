# SPDX-License-Identifier: AGPL-3.0-or-later
"""The single tool registry shared by the MCP server and (Phase 14) the in-app chat agent.

Design, following current agent-tool guidance (Anthropic "writing tools for agents", Cloudflare
"Code Mode"): few tools that each complete a workflow instead of thin CRUD calls; one-line
descriptions (they are sent to the model on every turn); compact, paginated results with a
``detail`` switch; deterministic work done server-side; read-only / destructive hints; errors
that say what to do next. With 9 tools the whole list costs about a thousand tokens, so a
"search + execute" code mode (worth it for hundreds of endpoints) is not needed; the registry
keeps that option open if the tool count grows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlmodel import Session

from annona_core.domain import Household
from annona_core.llm import LLMClient

from ..jobs import JobRunner


class ToolError(Exception):
    """A user-fixable problem; the message tells the model what to do next."""


@dataclass
class ToolContext:
    session: Session
    household: Household
    llm_factory: Callable[[Session], LLMClient]
    runner: JobRunner
    today: date


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str  # one line: what it does and when to use it
    input: type[BaseModel]
    output: type[BaseModel]
    handler: Callable[[ToolContext, Any], BaseModel]
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True
    # True: the tool only creates a pending proposal (its output carries ``action_id``); the change
    # happens when the person confirms it. The chat agent may call such a tool directly.
    proposes: bool = False

    def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> BaseModel:
        try:
            args = self.input.model_validate(arguments or {})
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or '(input)'}: {e['msg']}" for e in error.errors()
            )
            raise ToolError(f"invalid arguments for {self.name}: {problems}") from error
        return self.handler(ctx, args)


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    if tool.name in TOOLS:
        raise ValueError(f"duplicate tool {tool.name}")
    TOOLS[tool.name] = tool
    return tool
