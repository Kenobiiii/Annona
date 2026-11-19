# SPDX-License-Identifier: AGPL-3.0-or-later
"""LLM settings from the environment (``.env``). Provider keys use each provider's own variable
(e.g. ``DEEPSEEK_API_KEY``); LiteLLM reads them. Model ids follow LiteLLM's ``provider/model``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from annona_core.llm import Tier

from ..config import load_env

DEFAULT_MODELS = {
    Tier.SMALL: "deepseek/deepseek-flash",
    Tier.LARGE: "deepseek/deepseek-v4-pro",
}


@dataclass(frozen=True)
class LLMSettings:
    models: dict[Tier, str]
    timeout_s: float = 60.0
    thinking: bool = False  # provider "thinking"/reasoning mode, off by default (cost)


def llm_settings() -> LLMSettings:
    load_env()
    models = {
        Tier.SMALL: os.environ.get("ANNONA_LLM_MODEL_SMALL") or DEFAULT_MODELS[Tier.SMALL],
        Tier.LARGE: os.environ.get("ANNONA_LLM_MODEL_LARGE") or DEFAULT_MODELS[Tier.LARGE],
    }
    return LLMSettings(
        models=models,
        timeout_s=float(os.environ.get("ANNONA_LLM_TIMEOUT_S", "60")),
        thinking=os.environ.get("ANNONA_LLM_THINKING", "off").lower() in ("1", "on", "true"),
    )
