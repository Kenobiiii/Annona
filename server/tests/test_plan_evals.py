# SPDX-License-Identifier: AGPL-3.0-or-later
"""Planner eval harness with FakeLLM (no network, no cost)."""

import json
from decimal import Decimal

from annona_core.llm import FakeLLM, LLMClient, Tier
from annona_server.evals import plans

from .test_planner_db import even_split

MODELS = {Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}


def test_all_scenarios_have_a_feasible_shop():
    for scenario, shopping, ctx, _ in plans.prepare_all():
        assert shopping.status == "optimal", scenario["id"]
        assert ctx is not None and ctx.available


def test_run_metrics_and_menu(tmp_path):
    prepared = plans.prepare_all(["user_example_five_days"])
    report = plans.run_plans(LLMClient(FakeLLM(responder=even_split), MODELS), prepared, "fake/l")
    [entry] = report["scenarios"]
    m = entry["metrics"]
    assert m["accepted"] and m["accepted_first_try"] and m["meals"] == 12
    assert 0.9 <= m["purchase_used_ratio"] <= 1.01
    assert "Mon breakfast" in plans.menu_text(entry)
    path = plans.save(report, tmp_path)
    assert json.loads(path.read_text())["meta"]["model"] == "fake/l"


def test_judge_and_agreement():
    prepared = plans.prepare_all(["user_example_five_days", "vegetarian_woman"])
    report = plans.run_plans(LLMClient(FakeLLM(responder=even_split), MODELS), prepared, "fake/l")
    judge = LLMClient(FakeLLM(['{"score": 2, "reasons": "monotonous"}'] * 2), MODELS)
    plans.judge(judge, report)
    report["human_ratings"] = {
        "user_example_five_days": {"score": 2, "note": ""},
        "vegetarian_woman": {"score": 4, "note": ""},
    }
    agreement = plans.agreement(report)
    assert agreement["n"] == 2 and agreement["exact"] == 0.5 and agreement["within_one"] == 0.5
    assert agreement["mean_abs_diff"] == 1.0


def test_estimate_scales_with_meals():
    prepared = {s["id"]: ctx for s, _, ctx, _ in plans.prepare_all()}
    small = plans.estimate_plan_cost(
        prepared["user_example_five_days"], Decimal("1e-6"), Decimal("2e-6")
    )
    big = plans.estimate_plan_cost(
        prepared["single_active_full_week"], Decimal("1e-6"), Decimal("2e-6")
    )
    assert 0 < small < big
