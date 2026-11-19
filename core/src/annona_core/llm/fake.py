# SPDX-License-Identifier: AGPL-3.0-or-later
"""A scripted backend for tests: no network, no cost."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal

from .types import Completion, LLMRequest


class FakeLLM:
    """Returns scripted answers in order, or computes them with ``responder(request)``.

    Token counts are ``len(text) // 4`` (a rough, deterministic stand-in); cost is
    ``cost_per_call`` per call so tests can check accounting.
    """

    def __init__(
        self,
        answers: Iterable[str] = (),
        *,
        responder: Callable[[LLMRequest], str] | None = None,
        cost_per_call: Decimal | None = Decimal("0.0001"),
    ) -> None:
        self.answers = list(answers)
        self.responder = responder
        self.cost_per_call = cost_per_call
        self.requests: list[tuple[str, LLMRequest]] = []

    def complete(self, model: str, request: LLMRequest, *, json_mode: bool) -> Completion:
        self.requests.append((model, request))
        if self.responder is not None:
            text = self.responder(request)
        elif self.answers:
            text = self.answers.pop(0)
        else:
            raise AssertionError("FakeLLM ran out of scripted answers")
        prompt_chars = len(request.system) + sum(len(m.text) for m in request.messages)
        return Completion(
            text=text,
            model=model,
            input_tokens=prompt_chars // 4,
            output_tokens=len(text) // 4,
            cost_usd=self.cost_per_call,
            latency_ms=1,
        )
