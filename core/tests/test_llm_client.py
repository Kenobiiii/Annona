# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

import pytest
from pydantic import BaseModel, Field

from annona_core.llm import (
    CallStats,
    FakeLLM,
    Image,
    LLMClient,
    LLMOutputError,
    LLMRequest,
    Message,
    Tier,
    parse_json,
)

MODELS = {Tier.SMALL: "fake/small", Tier.LARGE: "fake/large"}


class Answer(BaseModel):
    category: str
    confidence: float = Field(ge=0, le=1)


class DictCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, model, text):
        self.store[key] = text


class ListSink:
    def __init__(self) -> None:
        self.records = []

    def record(self, record):
        self.records.append(record)


def request(text: str = "Leche entera", tier: Tier = Tier.SMALL) -> LLMRequest:
    return LLMRequest(tier=tier, task="test", system="Classify.", messages=(Message("user", text),))


def client(fake, cache=None, usage=None) -> LLMClient:
    return LLMClient(fake, MODELS, cache=cache, usage=usage)


def test_valid_answer_is_parsed_and_logged():
    fake = FakeLLM(['{"category": "dairy", "confidence": 0.9}'])
    sink = ListSink()
    result = client(fake, usage=sink).complete_json(request(), Answer)
    assert result == Answer(category="dairy", confidence=0.9)
    [record] = sink.records
    assert (record.model, record.success, record.repair, record.cached) == (
        "fake/small",
        True,
        False,
        False,
    )
    # The schema and the word "json" reach the model (some providers require it).
    model, sent = fake.requests[0]
    assert model == "fake/small"
    assert "JSON Schema" in sent.system and '"confidence"' in sent.system


def test_tiers_route_to_their_model():
    fake = FakeLLM(['{"category": "x", "confidence": 1}'])
    client(fake).complete_json(request(tier=Tier.LARGE), Answer)
    assert fake.requests[0][0] == "fake/large"


@pytest.mark.parametrize(
    "bad",
    [
        "",  # DeepSeek may return blank content in JSON mode
        "   ",
        "Sure! The category is dairy.",
        '{"category": "dairy", "confidence": 7}',  # schema violation
        '{"category": "dairy"',  # truncated
    ],
)
def test_invalid_answer_is_repaired_once(bad):
    fake = FakeLLM([bad, '{"category": "dairy", "confidence": 0.8}'])
    sink = ListSink()
    stats = CallStats()
    result = client(fake, usage=sink).complete_json(request(), Answer, stats=stats)
    assert result.category == "dairy"
    assert stats.repaired and stats.calls == 2
    assert [r.success for r in sink.records] == [False, True]
    assert [r.repair for r in sink.records] == [False, True]
    # The repair call shows the model its previous answer and the error.
    repair = fake.requests[1][1]
    assert repair.messages[-2].role == "assistant"
    assert "not valid" in repair.messages[-1].text


def test_schema_failure_after_repair_raises_clear_error():
    fake = FakeLLM(["nope", '{"category": 1}'])
    sink = ListSink()
    with pytest.raises(LLMOutputError, match="after one repair") as info:
        client(fake, usage=sink).complete_json(request(), Answer)
    assert info.value.raw == '{"category": 1}'
    assert len(fake.requests) == 2  # exactly one repair, no more
    assert [r.success for r in sink.records] == [False, False]


def test_cache_hit_skips_the_model():
    cache, sink = DictCache(), ListSink()
    fake = FakeLLM(['{"category": "dairy", "confidence": 0.9}'])
    llm = client(fake, cache=cache, usage=sink)
    first = llm.complete_json(request(), Answer)
    stats = CallStats()
    second = llm.complete_json(request(), Answer, stats=stats)
    assert first == second
    assert len(fake.requests) == 1
    assert stats.cached and stats.calls == 0 and stats.cost_usd == 0
    assert sink.records[-1].cached is True


def test_cache_key_depends_on_input_and_can_be_bypassed():
    cache = DictCache()
    fake = FakeLLM(['{"category": "a", "confidence": 1}'] * 3)
    llm = client(fake, cache=cache)
    llm.complete_json(request("Leche"), Answer)
    llm.complete_json(request("Arroz"), Answer)  # different input -> new call
    llm.complete_json(request("Leche"), Answer, use_cache=False)  # evals bypass the cache
    assert len(fake.requests) == 3


def test_invalid_answers_are_never_cached():
    cache = DictCache()
    fake = FakeLLM(["bad", "still bad"])
    with pytest.raises(LLMOutputError):
        client(fake, cache=cache).complete_json(request(), Answer)
    assert cache.store == {}


def test_stats_accumulate_cost_and_tokens():
    fake = FakeLLM(["bad", '{"category": "x", "confidence": 1}'], cost_per_call=Decimal("0.002"))
    stats = CallStats()
    client(fake).complete_json(request(), Answer, stats=stats)
    assert stats.cost_usd == Decimal("0.004")
    assert stats.input_tokens > 0 and stats.output_tokens > 0


def test_unknown_cost_stays_unknown():
    fake = FakeLLM(['{"category": "x", "confidence": 1}'], cost_per_call=None)
    stats = CallStats()
    client(fake).complete_json(request(), Answer, stats=stats)
    assert stats.cost_usd is None


def test_backend_errors_are_logged_and_raised():
    class Broken:
        def complete(self, model, request, *, json_mode):
            raise TimeoutError("slow")

    sink = ListSink()
    with pytest.raises(TimeoutError):
        client(Broken(), usage=sink).complete_json(request(), Answer)
    assert sink.records[0].success is False and "slow" in sink.records[0].error


def test_images_change_the_cache_key():
    cache = DictCache()
    fake = FakeLLM(['{"category": "x", "confidence": 1}'] * 2)
    llm = client(fake, cache=cache)
    for data in (b"photo-1", b"photo-2"):
        req = LLMRequest(
            tier=Tier.SMALL,
            task="receipt",
            system="Read.",
            messages=(Message("user", "What is this?", (Image("image/jpeg", data),)),),
        )
        llm.complete_json(req, Answer)
    assert len(fake.requests) == 2


def test_missing_tier_configuration():
    with pytest.raises(ValueError, match="no model"):
        LLMClient(FakeLLM(), {Tier.SMALL: "x"})


def test_parse_json_accepts_code_fences():
    assert parse_json('```json\n{"category": "x", "confidence": 0}\n```', Answer).category == "x"
