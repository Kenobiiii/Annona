# SPDX-License-Identifier: AGPL-3.0-or-later
"""The LiteLLM backend. This is the ONLY module that imports LiteLLM or knows provider quirks.

Security: LiteLLM is pinned to an exact version in ``server/pyproject.toml`` and ``uv.lock``
verifies package hashes (versions 1.82.7/1.82.8 were malicious in March 2026). Prices come from
LiteLLM's bundled price map; we disable its remote price-map download at import time.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal
from typing import Any

from annona_core.llm import Completion, LLMRequest

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # no network fetch on import

import litellm  # noqa: E402

litellm.suppress_debug_info = True  # no promotional/debug prints


class LiteLLMBackend:
    def __init__(self, *, timeout_s: float = 60.0, thinking: bool = False) -> None:
        self.timeout_s = timeout_s
        self.thinking = thinking

    def complete(self, model: str, request: LLMRequest, *, json_mode: bool) -> Completion:
        kwargs = self.build_kwargs(model, request, json_mode=json_mode)
        started = time.perf_counter()
        response = litellm.completion(**kwargs)
        latency_ms = int((time.perf_counter() - started) * 1000)
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        return Completion(
            text=text,
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            cached_input_tokens=_cached_tokens(usage),
            cost_usd=_cost(response),
            latency_ms=latency_ms,
        )

    def build_kwargs(self, model: str, request: LLMRequest, *, json_mode: bool) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
        for message in request.messages:
            if message.images:
                content: Any = [{"type": "text", "text": message.text}] + [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{img.media_type};base64,{img.b64()}"},
                    }
                    for img in message.images
                ]
            else:
                content = message.text
            messages.append({"role": message.role, "content": content})
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "timeout": self.timeout_s,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if model.startswith("deepseek/"):
            # DeepSeek: thinking is on by default; https://api-docs.deepseek.com/guides/thinking_mode
            kwargs["extra_body"] = {
                "thinking": {"type": "enabled" if self.thinking else "disabled"}
            }
        return kwargs


def _cost(response: Any) -> Decimal | None:
    try:
        value = litellm.completion_cost(completion_response=response)
    except Exception:  # unknown model price: report unknown, never guess
        return None
    return Decimal(str(value)) if value is not None else None


def _cached_tokens(usage: Any) -> int | None:
    """Input tokens the provider served from its prompt cache (OpenAI-style usage details)."""
    details = getattr(usage, "prompt_tokens_details", None)
    value = getattr(details, "cached_tokens", None) if details is not None else None
    return int(value) if value is not None else None


def key_configured(model: str) -> bool | None:
    """Whether the environment holds the API key this model's provider needs (None: unknown)."""
    try:
        litellm.get_llm_provider(model)  # raises for providers LiteLLM does not know
        status = litellm.validate_environment(model=model)
    except Exception:
        return None
    return bool(status.get("keys_in_environment"))
