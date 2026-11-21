# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weekly-planner evals: run scenarios end to end, score them, rate them (human and judge).

Each scenario is optimised (deterministic) and then planned by the LLM with the cache bypassed.
Hard checks come from the verifier; quality metrics are computed by code; "would people want
to eat it" comes from human ratings, and optionally from an LLM judge whose agreement with the
human ratings is measured (a judge is only trusted as far as it agrees with people).
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from annona_core.domain import (
    Equipment,
    NutritionFacts,
    Product,
    Quantity,
    UserProfile,
)
from annona_core.llm import CallStats, LLMClient, LLMRequest, Message, Tier
from annona_core.nutrition import daily_targets, weekly_targets
from annona_core.optimizer import Offer, OptimizerSettings, Problem, optimise
from annona_core.planner import (
    Available,
    MealSchedule,
    Member,
    PlanContext,
    build_prompt,
    plan_week,
)

from ..seed import sample_foods
from .runner import DATASETS, RESULTS, _git_commit

TASK = "plan_week"
EVAL_TASK = "eval:" + TASK
JUDGE_TASK = "eval:plan_judge"
MONDAY = date(2026, 11, 23)  # fixed week so runs are comparable


def load_scenarios() -> dict[str, Any]:
    return json.loads((DATASETS / "plan_scenarios.json").read_text(encoding="utf-8"))


def _offers(catalogue: dict[str, list]) -> list[Offer]:
    foods = {f["key"]: f for f in sample_foods()}
    offers = []
    for pid, (key, (amount, unit, cents)) in enumerate(sorted(catalogue.items()), start=1):
        f = foods[key]
        product = Product(
            id=pid,
            name=f["name"],
            category=f["category"],
            type=f["type"],
            allergens=f["allergens"],
            unit_weight_g=f.get("unit_weight_g"),
            density_g_per_ml=f.get("density_g_per_ml"),
            package_amount=Quantity.parse(amount, unit).amount,
            package_unit=Quantity.parse(amount, unit).unit,
            nutrition=NutritionFacts.model_validate(f["nutrition"]),
        )
        offers.append(Offer(product=product, price_cents=cents))
    return offers


def build_scenario(scenario: dict[str, Any], catalogue: dict[str, list]):
    members = [
        UserProfile(id=i, household_id=1, allergies_confirmed=True, **m)
        for i, m in enumerate(scenario["members"], start=1)
    ]
    sched = scenario["schedule"]
    schedule = MealSchedule.build(
        MONDAY,
        weekdays=sched["weekdays"],
        skip_slots=sched["skip_slots"],
        skip=[tuple(x) for x in sched["skip"]],
    )
    dailies = [daily_targets(m, MONDAY) for m in members]
    problem = Problem(
        offers=_offers(catalogue),
        members=members,
        targets=weekly_targets(dailies, days=schedule.day_equivalents),
        budget_cents=scenario["budget_cents"],
        settings=OptimizerSettings(days=len(schedule.days)),
    )
    equipment = Equipment(household_id=1, **scenario["kitchen"])
    return problem, schedule, members, dailies, equipment


def context_for(problem: Problem, shopping, schedule, members, dailies, equipment) -> PlanContext:
    products = {o.product.id: o.product for o in problem.offers}
    available = tuple(
        Available(
            product=products[line.product_id],
            basis=line.basis_unit,
            available=line.available,
            intended=line.used_total,
            kcal=products[line.product_id].nutrition.energy_kcal / 100,
            protein=products[line.product_id].nutrition.protein_g / 100,
            not_for=tuple(n.member for n in line.not_for),
        )
        for line in shopping.lines
    )
    target = sum((d.energy_kcal for d in dailies), Decimal(0)) * schedule.day_equivalents
    return PlanContext(
        schedule=schedule,
        members=tuple(Member(profile=m, daily=d) for m, d in zip(members, dailies, strict=True)),
        available=available,
        equipment=equipment,
        energy_scale=shopping.period_totals.energy_kcal / target,
    )


def _menu(outcome, ctx: PlanContext) -> list[dict[str, Any]]:
    names = {a.product.id: a.product.name for a in ctx.available}
    meals = []
    for meal in outcome.draft.meals:
        meals.append(
            {
                "weekday": meal.weekday,
                "slot": str(meal.slot),
                "title": meal.title,
                "appliances": [str(a) for a in meal.appliances],
                "summary": meal.summary,
                "skipped_by": meal.skipped_by,
                "ingredients": [
                    f"{names.get(i.product_id, f'UNKNOWN {i.product_id}')} {i.amount}"
                    for i in meal.ingredients
                ],
            }
        )
    return sorted(meals, key=lambda m: (m["weekday"], m["slot"]))


def plan_metrics(outcome, ctx: PlanContext) -> dict[str, Any]:
    v = outcome.verification
    titles = [m.title.strip().lower() for m in outcome.draft.meals]
    repeats = Counter(titles)
    scales = v.ingredient_scales  # code-adjusted amount / LLM-drafted amount
    kcal_by_id = {a.product.id: a.kcal for a in ctx.available}
    intended = sum((a.intended * a.kcal for a in ctx.available), Decimal(0))
    used = sum((amount * kcal_by_id[pid] for pid, amount in v.usage.items()), Decimal(0))
    calls = outcome.calls
    costs = [c.cost_usd for c in calls]
    return {
        "accepted": outcome.accepted,
        "accepted_first_try": not outcome.first_issues,
        "repaired": outcome.repaired,
        "first_issue_codes": dict(Counter(i.code for i in outcome.first_issues)),
        "final_issue_codes": dict(Counter(i.code for i in v.issues)),
        "meals": len(outcome.draft.meals),
        "distinct_titles_ratio": round(len(repeats) / len(titles), 3) if titles else None,
        "most_repeated_title": repeats.most_common(1)[0] if repeats else None,
        "ingredient_scale_min": str(min(scales)) if scales else None,
        "ingredient_scale_max": str(max(scales)) if scales else None,
        "ingredient_scale_mean": (
            str(round(sum(scales, Decimal(0)) / len(scales), 2)) if scales else None
        ),
        "purchase_used_ratio": round(float(used / intended), 3) if intended else None,
        "model_calls": sum(c.calls for c in calls),
        "input_tokens": sum(c.input_tokens for c in calls),
        "output_tokens": sum(c.output_tokens for c in calls),
        "cached_input_tokens": sum(c.cached_input_tokens for c in calls),
        "cost_usd": None if any(c is None for c in costs) else str(sum(costs, Decimal(0))),
        "latency_ms": sum(c.latency_ms for c in calls),
    }


def estimate_plan_cost(ctx: PlanContext, price_in: Decimal, price_out: Decimal) -> Decimal:
    """Upper bound: prompt chars / 3 tokens, 250 output tokens per meal, x2 for a repair."""
    system, user = build_prompt(ctx)
    tokens_in = Decimal(len(system) + len(user) + 3000) / 3
    tokens_out = Decimal(250 * len(ctx.schedule.slots))
    return ((tokens_in * price_in + tokens_out * price_out) * 2).quantize(Decimal("0.000001"))


def prepare_all(scenario_ids: list[str] | None = None):
    data = load_scenarios()
    prepared = []
    for scenario in data["scenarios"]:
        if scenario_ids and scenario["id"] not in scenario_ids:
            continue
        problem, schedule, members, dailies, equipment = build_scenario(scenario, data["catalogue"])
        shopping = optimise(problem)
        ctx = (
            context_for(problem, shopping, schedule, members, dailies, equipment)
            if shopping.status == "optimal"
            else None
        )
        prepared.append((scenario, shopping, ctx))
    return prepared


def run_plans(llm: LLMClient, prepared, model: str) -> dict[str, Any]:
    results = []
    for scenario, shopping, ctx in prepared:
        entry: dict[str, Any] = {
            "id": scenario["id"],
            "description": scenario["description"],
            "shopping_status": shopping.status,
            "shopping_cost_cents": shopping.total_cost_cents,
        }
        if ctx is None:
            entry["error"] = "shopping not feasible"
        else:
            started = time.perf_counter()
            try:
                outcome = plan_week(llm, ctx, task=EVAL_TASK, use_cache=False)
            except Exception as error:  # schema failure after repair, provider error...
                entry["error"] = repr(error)
            else:
                entry["metrics"] = plan_metrics(outcome, ctx)
                entry["issues"] = [i.message for i in outcome.verification.issues]
                entry["first_issues"] = [i.message for i in outcome.first_issues]
                entry["menu"] = _menu(outcome, ctx)
            entry["wall_ms"] = int((time.perf_counter() - started) * 1000)
        results.append(entry)
    return {
        "meta": {
            "task": TASK,
            "model": model,
            "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
            "dataset": "plan_scenarios.json",
        },
        "scenarios": results,
        "human_ratings": {},
        "judge": {},
    }


def save(report: dict[str, Any], directory: Path = RESULTS) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report["meta"]["started_at"].replace(":", "").replace("-", "")[:15]
    model = re.sub(r"[^a-zA-Z0-9.]+", "-", report["meta"]["model"])
    path = directory / f"{stamp}__{TASK}__{model}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def menu_text(entry: dict[str, Any]) -> str:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    lines = [f"{entry['id']}: {entry['description']}"]
    for meal in entry.get("menu", []):
        skipped = f" (not for {', '.join(meal['skipped_by'])})" if meal["skipped_by"] else ""
        lines.append(f"- {days[meal['weekday']]} {meal['slot']}: {meal['title']}{skipped}")
        lines.append(f"    {meal['summary']}")
        lines.append(f"    per person: {'; '.join(meal['ingredients'])}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------- judge


class JudgeVerdict(BaseModel):
    score: int = Field(ge=1, le=5)
    reasons: str = Field(max_length=600)


JUDGE_SYSTEM = (
    "You review weekly home-cooking menus for a household in Spain. Rate how much people would "
    "actually want to eat and cook this week, from 1 (would not follow it) to 5 (would happily "
    "follow it). Consider: appetising and coherent dishes, variety without being impractical, "
    "realistic portions and combinations for Spanish home cooking, and simple preparation. Do "
    "not rate nutrition or price: they are checked elsewhere. Be strict and consistent. Give "
    "short reasons."
)


def judge(llm: LLMClient, report: dict[str, Any], tier: Tier = Tier.SMALL) -> None:
    for entry in report["scenarios"]:
        if "menu" not in entry:
            continue
        stats = CallStats()
        verdict = llm.complete_json(
            LLMRequest(
                tier=tier,
                task=JUDGE_TASK,
                system=JUDGE_SYSTEM,
                messages=(Message("user", menu_text(entry)),),
                max_tokens=400,
            ),
            JudgeVerdict,
            use_cache=False,
            stats=stats,
        )
        report["judge"][entry["id"]] = {
            "model": llm.models[tier],
            "score": verdict.score,
            "reasons": verdict.reasons,
            "cost_usd": None if stats.cost_usd is None else str(stats.cost_usd),
        }


def agreement(report: dict[str, Any]) -> dict[str, Any]:
    pairs = [
        (report["human_ratings"][sid]["score"], report["judge"][sid]["score"])
        for sid in report["human_ratings"]
        if sid in report["judge"]
    ]
    if not pairs:
        return {"n": 0}
    diffs = [abs(h - j) for h, j in pairs]
    return {
        "n": len(pairs),
        "mean_abs_diff": round(sum(diffs) / len(diffs), 2),
        "exact": round(sum(d == 0 for d in diffs) / len(diffs), 2),
        "within_one": round(sum(d <= 1 for d in diffs) / len(diffs), 2),
        "pairs": pairs,
    }
