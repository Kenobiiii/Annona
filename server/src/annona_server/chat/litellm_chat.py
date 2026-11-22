# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chat model over LiteLLM: streaming, native tool calling, usage and cost accounting."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from annona_core.agent import AgentMessage, ModelReply, TextDelta, ToolCall, ToolSpec
from annona_core.agent.loop import parse_arguments
from annona_core.llm import Tier, UsageRecord

from ..llm.litellm_backend import _cached_tokens, _cost, litellm
from ..llm.storage import SqlUsageSink


def to_provider_messages(system: str, messages: list[AgentMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.text})
        elif m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.text or "",
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.name,
                                "arguments": c.raw_arguments or json.dumps(c.arguments or {}),
                            },
                        }
                        for c in m.tool_calls
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": m.text})
    return out


def to_provider_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


class LiteChatModel:
    """Implements :class:`annona_core.agent.ChatModel` with LiteLLM streaming."""

    def __init__(
        self,
        model: str,
        *,
        tier: Tier,
        usage: SqlUsageSink | None = None,
        timeout_s: float = 60.0,
        thinking: bool = False,
    ) -> None:
        self.model, self.tier, self.usage = model, tier, usage
        self.timeout_s, self.thinking = timeout_s, thinking

    def stream(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec], *, max_tokens: int
    ) -> Iterator[TextDelta | ModelReply]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": to_provider_messages(system, messages),
            "max_tokens": max_tokens,
            "timeout": self.timeout_s,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = to_provider_tools(tools)
        if self.model.startswith("deepseek/"):
            kwargs["extra_body"] = {
                "thinking": {"type": "enabled" if self.thinking else "disabled"}
            }
        started = time.perf_counter()
        text = ""
        pieces: dict[int, dict[str, str]] = {}
        chunks: list[Any] = []
        usage: Any = None
        error: str | None = None
        try:
            for chunk in litellm.completion(**kwargs):
                chunks.append(chunk)
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text += delta.content
                    yield TextDelta(delta.content)
                for tc in delta.tool_calls or []:
                    slot = pieces.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
            self._record(None, None, None, None, int((time.perf_counter() - started) * 1000), error)
            raise
        latency = int((time.perf_counter() - started) * 1000)
        cost = None
        try:
            built = litellm.stream_chunk_builder(chunks, messages=kwargs["messages"])
            cost = _cost(built)
        except Exception:
            cost = None
        calls = [
            ToolCall(
                id=p["id"] or f"call_{i}",
                name=p["name"],
                arguments=parse_arguments(p["args"]),
                raw_arguments=p["args"],
            )
            for i, p in sorted(pieces.items())
            if p["name"]
        ]
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0
        self._record(tokens_in, tokens_out, _cached_tokens(usage), cost, latency, None)
        yield ModelReply(
            text=text,
            tool_calls=calls,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=cost,
            latency_ms=latency,
            model=self.model,
        )

    def _record(
        self,
        tokens_in: int | None,
        tokens_out: int | None,
        cached: int | None,
        cost: Decimal | None,
        latency: int,
        error: str | None,
    ) -> None:
        if self.usage is None:
            return
        self.usage.record(
            UsageRecord(
                at=datetime.now(UTC),
                task="chat",
                tier=self.tier,
                model=self.model,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                cost_usd=cost,
                latency_ms=latency,
                cached_input_tokens=cached,
                success=error is None,
                error=error,
            )
        )
