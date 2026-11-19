# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server side of the LLM layer. No network: LiteLLM's own ``mock_response`` is used."""

from decimal import Decimal

import pytest
from pydantic import BaseModel

from annona_core.llm import FakeLLM, Image, LLMRequest, Message, Tier
from annona_server.db.tables import LlmUsageRow
from annona_server.llm import make_llm_client
from annona_server.llm.config import DEFAULT_MODELS, LLMSettings, llm_settings
from annona_server.llm.storage import spent_usd

litellm_backend = pytest.importorskip("annona_server.llm.litellm_backend")


class Answer(BaseModel):
    category: str


def req(images=()) -> LLMRequest:
    return LLMRequest(
        tier=Tier.SMALL,
        task="test",
        system="sys",
        messages=(Message("user", "hello", tuple(images)),),
        max_tokens=100,
    )


def test_kwargs_for_deepseek_json_and_images():
    backend = litellm_backend.LiteLLMBackend(timeout_s=5)
    kwargs = backend.build_kwargs(
        "deepseek/deepseek-flash", req([Image("image/png", b"\x89PNG")]), json_mode=True
    )
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    parts = kwargs["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "hello"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_thinking_switch_and_other_providers():
    on = litellm_backend.LiteLLMBackend(thinking=True)
    assert on.build_kwargs("deepseek/deepseek-flash", req(), json_mode=False)["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    other = litellm_backend.LiteLLMBackend().build_kwargs("openai/x", req(), json_mode=False)
    assert "extra_body" not in other and "response_format" not in other


def test_complete_parses_text_usage_and_cost(monkeypatch):
    real = litellm_backend.litellm.completion

    def mocked(**kwargs):
        return real(**kwargs, mock_response='{"category": "dairy"}')

    monkeypatch.setattr(litellm_backend.litellm, "completion", mocked)
    completion = litellm_backend.LiteLLMBackend().complete(
        "deepseek/deepseek-flash", req(), json_mode=True
    )
    assert completion.text == '{"category": "dairy"}'
    assert completion.input_tokens and completion.output_tokens
    assert completion.cost_usd is not None and completion.cost_usd > 0
    assert completion.latency_ms is not None


def test_settings_defaults_and_env(monkeypatch):
    monkeypatch.delenv("ANNONA_LLM_MODEL_SMALL", raising=False)
    monkeypatch.setenv("ANNONA_LLM_MODEL_LARGE", "openai/some-model")
    s = llm_settings()
    assert s.models[Tier.SMALL] == DEFAULT_MODELS[Tier.SMALL]
    assert s.models[Tier.LARGE] == "openai/some-model"
    assert s.thinking is False


def test_db_cache_and_usage_log(session):
    settings = LLMSettings(models={Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"})
    fake = FakeLLM(['{"category": "dairy"}'], cost_per_call=Decimal("0.0005"))
    llm = make_llm_client(session, settings=settings, backend=fake)
    llm.complete_json(req(), Answer)
    llm.complete_json(req(), Answer)  # served from the DB cache
    assert len(fake.requests) == 1
    rows = session.exec(__import__("sqlmodel").select(LlmUsageRow)).all()
    assert [(r.cached, r.model) for r in rows] == [(False, "fake/s"), (True, "fake/s")]
    assert spent_usd(session) == Decimal("0.0005")
    assert spent_usd(session, "eval:") == 0


def test_cached_tokens_are_read_from_usage_details():
    from types import SimpleNamespace

    usage = SimpleNamespace(prompt_tokens_details=SimpleNamespace(cached_tokens=766))
    assert litellm_backend._cached_tokens(usage) == 766
    assert litellm_backend._cached_tokens(SimpleNamespace()) is None
