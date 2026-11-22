# SPDX-License-Identifier: AGPL-3.0-or-later
"""A scripted chat model for tests: no network, deterministic, records what it was asked."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from .types import AgentMessage, ModelReply, TextDelta, ToolSpec


class FakeChatModel:
    """Replies come from a list (one per call) or from ``responder(messages, tools)``."""

    def __init__(
        self,
        replies: list[ModelReply] | None = None,
        responder: Callable[[list[AgentMessage], list[ToolSpec]], ModelReply] | None = None,
    ) -> None:
        self.replies = list(replies or [])
        self.responder = responder
        self.calls: list[tuple[str, list[AgentMessage], list[ToolSpec]]] = []

    def stream(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec], *, max_tokens: int
    ) -> Iterator[TextDelta | ModelReply]:
        self.calls.append((system, list(messages), list(tools)))
        if self.responder is not None:
            reply = self.responder(messages, tools)
        elif self.replies:
            reply = self.replies.pop(0)
        else:
            raise AssertionError("FakeChatModel ran out of scripted replies")
        for i in range(0, len(reply.text), 8):  # arrives in small pieces, like a real stream
            yield TextDelta(reply.text[i : i + 8])
        yield reply
