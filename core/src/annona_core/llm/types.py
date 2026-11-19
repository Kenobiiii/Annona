# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider-neutral request/response types for the LLM layer."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol


class Tier(StrEnum):
    """``small``: classification, receipts, chat. ``large``: weekly plan, recipes."""

    SMALL = "small"
    LARGE = "large"


@dataclass(frozen=True)
class Image:
    media_type: str  # e.g. "image/jpeg"
    data: bytes

    def b64(self) -> str:
        return base64.standard_b64encode(self.data).decode("ascii")

    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str
    images: tuple[Image, ...] = ()


@dataclass(frozen=True)
class LLMRequest:
    tier: Tier
    task: str  # short label for logs and evals, e.g. "classify_products"
    system: str
    messages: tuple[Message, ...]
    max_tokens: int = 2048


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None  # input tokens served from the provider's cache
    cost_usd: Decimal | None = None  # None = unknown, never guessed
    latency_ms: int | None = None


@dataclass(frozen=True)
class UsageRecord:
    at: datetime
    task: str
    tier: Tier
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    latency_ms: int | None
    cached_input_tokens: int | None = None
    cached: bool = False
    repair: bool = False
    success: bool = True
    error: str | None = None


@dataclass
class CallStats:
    """What one ``complete_json`` call cost, for evals and reports."""

    calls: int = 0
    cached: bool = False
    repaired: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: Decimal | None = Decimal(0)
    latency_ms: int = 0
    records: list[UsageRecord] = field(default_factory=list)

    def add(self, record: UsageRecord) -> None:
        self.records.append(record)
        if record.cached:
            self.cached = True
            return
        self.calls += 1
        self.input_tokens += record.input_tokens or 0
        self.output_tokens += record.output_tokens or 0
        self.cached_input_tokens += record.cached_input_tokens or 0
        self.latency_ms += record.latency_ms or 0
        if record.cost_usd is None or self.cost_usd is None:
            self.cost_usd = None
        else:
            self.cost_usd += record.cost_usd


class LLMBackend(Protocol):
    """Sends one request to a model. Implementations: LiteLLM (server) and FakeLLM (tests)."""

    def complete(self, model: str, request: LLMRequest, *, json_mode: bool) -> Completion: ...


class ResponseCache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, model: str, text: str) -> None: ...


class UsageSink(Protocol):
    def record(self, record: UsageRecord) -> None: ...
