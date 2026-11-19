# SPDX-License-Identifier: AGPL-3.0-or-later
"""The eval harness, exercised with FakeLLM (no network, no cost)."""

import json
import re
from decimal import Decimal

import pytest

from annona_core.llm import CallStats, FakeLLM, LLMClient, Tier
from annona_server.evals.metrics import ItemResult, classification_metrics
from annona_server.evals.runner import (
    BudgetError,
    estimate_cost_usd,
    load_dataset,
    load_reports,
    run_classification,
    save_report,
)
from annona_server.ingest.classify import ClassificationInput
from annona_server.ingest.llm_classify import LLMClassifier
from annona_server.llm.storage import SqlUsageSink

ROWS = load_dataset()
MODELS = {Tier.SMALL: "fake/small", Tier.LARGE: "fake/large"}


def oracle(request) -> str:
    """Answers with the dataset's expected labels (a perfect model)."""
    by_name = {r["name"]: r for r in ROWS}
    lines = request.messages[-1].text.splitlines()
    items = []
    for line in lines:
        index, name = re.match(r"(\d+): (.*)", line).groups()
        row = by_name[name]
        items.append(
            {
                "index": int(index),
                "category": row["expected_category"],
                "type": row["expected_type"],
            }
        )
    return json.dumps({"items": items})


def test_dataset_is_valid():
    assert len(ROWS) >= 60
    from annona_core.domain import Category

    for row in ROWS:
        Category(row["expected_category"])
        assert row["name"] and row["source"].startswith("open_prices:")


def test_perfect_model_scores_100_percent(session):
    llm = LLMClient(FakeLLM(responder=oracle), MODELS, usage=SqlUsageSink(session))
    report = run_classification(ROWS, classifier="llm", llm=llm, batch_size=20)
    m = report["metrics"]
    assert m["accuracy"] == 1.0 and m["type_accuracy"] == 1.0 and m["missing"] == 0
    assert m["batches"] == 5 and m["repair_rate"] == 0.0
    assert Decimal(m["cost_usd"]) == Decimal("0.0005")  # 5 calls x FakeLLM's 0.0001
    assert report["meta"]["model"] == "fake/small"


def test_skipped_and_out_of_range_indexes_count_as_missing():
    fake = FakeLLM(
        ['{"items": [{"index": 0, "category": "dairy"}, {"index": 9, "category": "fish"}]}']
    )
    llm = LLMClient(fake, MODELS)
    result = LLMClassifier(llm).classify_batch(
        [ClassificationInput("Leche"), ClassificationInput("Arroz")]
    )
    assert result[0].category == "dairy" and result[1] is None


def test_budget_guard(session, monkeypatch):
    monkeypatch.setenv("ANNONA_EVAL_BUDGET_USD", "0.001")
    llm = LLMClient(FakeLLM(responder=oracle), MODELS, usage=SqlUsageSink(session))
    with pytest.raises(BudgetError):
        run_classification(
            ROWS, classifier="llm", llm=llm, session=session, estimated_cost=Decimal("0.01")
        )


def test_estimate_is_positive_and_scales_with_prices():
    cheap = estimate_cost_usd(ROWS, "v1_plain", 20, Decimal("1e-7"), Decimal("1e-6"))
    pricey = estimate_cost_usd(ROWS, "v1_plain", 20, Decimal("1e-6"), Decimal("1e-5"))
    assert 0 < cheap < pricey


def test_metrics_details():
    items = [
        ItemResult("1", "a", "dairy", "milk", False, "dairy", "whole_milk"),
        ItemResult("2", "b", "beverages", "oat_drink", False, "dairy", "oat_milk"),
        ItemResult("3", "c", "other", None, True, None, None),
    ]
    calls = [CallStats(calls=2, repaired=True, cost_usd=Decimal("0.01"), latency_ms=100)]
    m = classification_metrics(items, calls)
    assert m["accuracy"] == round(1 / 3, 4)
    assert m["accuracy_unambiguous"] == 0.5
    assert m["type_accuracy"] == 0.5  # "milk" in "whole_milk"; oat_drink vs oat_milk fails
    assert m["missing"] == 1 and m["repair_rate"] == 1.0
    assert m["top_confusions"][0] == ("beverages -> dairy", 1)


def test_rules_baseline_and_report_files(tmp_path):
    report = run_classification(ROWS, classifier="rules")
    path = save_report(report, tmp_path)
    [loaded] = load_reports(tmp_path)
    assert loaded["_file"] == path.name
    assert 0 < loaded["metrics"]["accuracy"] < 1
