# SPDX-License-Identifier: AGPL-3.0-or-later
"""The provider-agnostic LLM client.

``complete_json`` returns data validated against a Pydantic schema, never raw model text:

1. A short JSON instruction with the schema is appended to the system prompt (some providers,
   such as DeepSeek, also require the word "json" and an example in the prompt).
2. A cached answer for the same model + prompt + schema is returned without calling the model.
3. The answer is parsed and validated. On failure the model gets ONE repair attempt that shows it
   its previous answer and the validation error. A second failure raises :class:`LLMOutputError`.
4. Every model call (and cache hit) is reported to the usage sink with tokens, cost and latency.

Numbers inside LLM answers must still be recomputed by code by the caller (CLAUDE.md).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError

from .types import (
    CallStats,
    Completion,
    LLMBackend,
    LLMRequest,
    Message,
    ResponseCache,
    Tier,
    UsageRecord,
    UsageSink,
)


class LLMError(Exception):
    """Base class for LLM layer failures."""


class LLMOutputError(LLMError):
    """The model did not return valid data after one repair attempt."""

    def __init__(self, message: str, raw: str) -> None:
        super().__init__(message)
        self.raw = raw


JSON_INSTRUCTION = (
    "Respond with a single JSON object only (no prose, no code fences) that validates against "
    "this JSON Schema:\n{schema}"
)
REPAIR_INSTRUCTION = (
    "Your previous answer was not valid: {error}\n"
    "Reply again with the corrected JSON object only, following the same JSON Schema."
)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_json(text: str, schema: type[BaseModel]) -> BaseModel:
    """Parse a model answer into ``schema``; raises ``ValueError`` with a short reason."""
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("the answer was empty")
    match = _FENCE.match(cleaned)
    if match:
        cleaned = match.group(1)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON ({error.msg} at position {error.pos})") from error
    try:
        return schema.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or '(root)'}: {e['msg']}" for e in error.errors()[:5]
        )
        raise ValueError(f"schema validation failed: {problems}") from error


def cache_key(model: str, request: LLMRequest, schema: type[BaseModel] | None) -> str:
    payload = {
        "model": model,
        "system": request.system,
        "max_tokens": request.max_tokens,
        "messages": [
            {"role": m.role, "text": m.text, "images": [i.digest() for i in m.images]}
            for m in request.messages
        ],
        "schema": schema.model_json_schema() if schema else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class LLMClient:
    def __init__(
        self,
        backend: LLMBackend,
        models: dict[Tier, str],
        *,
        cache: ResponseCache | None = None,
        usage: UsageSink | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        missing = [t for t in Tier if t not in models]
        if missing:
            raise ValueError(f"no model configured for tiers {missing}")
        self.backend = backend
        self.models = models
        self.cache = cache
        self.usage = usage
        self._now = now

    def complete_json[T: BaseModel](
        self,
        request: LLMRequest,
        schema: type[T],
        *,
        use_cache: bool = True,
        stats: CallStats | None = None,
    ) -> T:
        stats = stats if stats is not None else CallStats()
        model = self.models[request.tier]
        schema_json = json.dumps(schema.model_json_schema(), separators=(",", ":"))
        system = f"{request.system}\n\n{JSON_INSTRUCTION.format(schema=schema_json)}".strip()
        prepared = LLMRequest(
            tier=request.tier,
            task=request.task,
            system=system,
            messages=request.messages,
            max_tokens=request.max_tokens,
        )
        key = cache_key(model, prepared, schema)

        if use_cache and self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                try:
                    result = parse_json(hit, schema)
                except ValueError:
                    pass  # stale or corrupt entry: ask the model again
                else:
                    self._record(stats, request, model, None, cached=True)
                    return result  # type: ignore[return-value]

        first = self._call(request, model, prepared, stats=stats)
        try:
            result = parse_json(first.text, schema)
        except ValueError as error:
            self._record(stats, request, model, first, error=str(error))
            repair_request = LLMRequest(
                tier=prepared.tier,
                task=prepared.task,
                system=prepared.system,
                messages=(
                    *prepared.messages,
                    Message("assistant", first.text or "(empty)"),
                    Message("user", REPAIR_INSTRUCTION.format(error=error)),
                ),
                max_tokens=prepared.max_tokens,
            )
            stats.repaired = True
            second = self._call(request, model, repair_request, stats=stats, repair=True)
            try:
                result = parse_json(second.text, schema)
            except ValueError as final_error:
                self._record(stats, request, model, second, repair=True, error=str(final_error))
                raise LLMOutputError(
                    f"{request.task}: invalid answer after one repair: {final_error}", second.text
                ) from final_error
            self._record(stats, request, model, second, repair=True)
            final_text = second.text
        else:
            self._record(stats, request, model, first)
            final_text = first.text

        if self.cache is not None:
            self.cache.set(key, model, final_text)
        return result  # type: ignore[return-value]

    # -- internals --
    def _call(
        self,
        request: LLMRequest,
        model: str,
        prepared: LLMRequest,
        *,
        stats: CallStats,
        repair: bool = False,
    ) -> Completion:
        try:
            return self.backend.complete(model, prepared, json_mode=True)
        except Exception as error:
            self._record(stats, request, model, None, repair=repair, error=repr(error))
            raise

    def _record(
        self,
        stats: CallStats,
        request: LLMRequest,
        model: str,
        completion: Completion | None,
        *,
        cached: bool = False,
        repair: bool = False,
        error: str | None = None,
    ) -> None:
        record = UsageRecord(
            at=self._now(),
            task=request.task,
            tier=request.tier,
            model=model,
            input_tokens=completion.input_tokens if completion else (0 if cached else None),
            output_tokens=completion.output_tokens if completion else (0 if cached else None),
            cost_usd=completion.cost_usd if completion else None,
            latency_ms=completion.latency_ms if completion else None,
            cached=cached,
            repair=repair,
            success=error is None,  # False: transport error or invalid answer
            error=error,
        )
        stats.add(record)
        if self.usage is not None:
            self.usage.record(record)
