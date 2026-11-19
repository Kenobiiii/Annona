# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider-agnostic LLM layer: interface, JSON validation with one repair, caching hooks,
usage accounting and a fake backend for tests. No I/O here; backends live in the server."""

from .client import LLMClient, LLMError, LLMOutputError, cache_key, parse_json, prompt_schema
from .fake import FakeLLM
from .types import (
    CallStats,
    Completion,
    Image,
    LLMBackend,
    LLMRequest,
    Message,
    ResponseCache,
    Tier,
    UsageRecord,
    UsageSink,
)

__all__ = [
    "CallStats",
    "Completion",
    "FakeLLM",
    "Image",
    "LLMBackend",
    "LLMClient",
    "LLMError",
    "LLMOutputError",
    "LLMRequest",
    "Message",
    "ResponseCache",
    "Tier",
    "UsageRecord",
    "UsageSink",
    "cache_key",
    "parse_json",
    "prompt_schema",
]
