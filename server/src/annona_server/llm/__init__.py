# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wires the core LLM client to LiteLLM, the database cache and the usage log."""

from __future__ import annotations

from sqlmodel import Session

from annona_core.llm import LLMBackend, LLMClient

from .config import LLMSettings, llm_settings
from .storage import SqlResponseCache, SqlUsageSink


def make_llm_client(
    session: Session, *, settings: LLMSettings | None = None, backend: LLMBackend | None = None
) -> LLMClient:
    settings = settings or llm_settings()
    if backend is None:
        from ..demo import demo_backend, fake_llm_enabled

        if fake_llm_enabled():  # demo mode: no AI provider is called
            backend = demo_backend()
    if backend is None:
        from .litellm_backend import LiteLLMBackend  # imported lazily: LiteLLM is heavy

        backend = LiteLLMBackend(timeout_s=settings.timeout_s, thinking=settings.thinking)
    return LLMClient(
        backend, settings.models, cache=SqlResponseCache(session), usage=SqlUsageSink(session)
    )
