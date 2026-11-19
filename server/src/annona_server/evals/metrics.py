# SPDX-License-Identifier: AGPL-3.0-or-later
"""Metrics for product classification runs. Pure functions over per-item results."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from annona_core.llm import CallStats


@dataclass(frozen=True)
class ItemResult:
    id: str
    name: str
    expected_category: str
    expected_type: str | None
    ambiguous: bool
    predicted_category: str | None  # None = model skipped it / failed batch
    predicted_type: str | None

    @property
    def correct(self) -> bool:
        return self.predicted_category == self.expected_category


def _type_match(expected: str | None, predicted: str | None) -> bool:
    """Lenient: equal, or one contains the other ("oat_drink" vs "oat_milk_drink")."""
    if not expected or not predicted:
        return False
    return expected == predicted or expected in predicted or predicted in expected


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def _percentile(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return int(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1])


def classification_metrics(
    items: Sequence[ItemResult], calls: Sequence[CallStats]
) -> dict[str, Any]:
    clear = [i for i in items if not i.ambiguous]
    typed = [i for i in items if i.expected_type]
    per_category: dict[str, dict[str, Any]] = {}
    for category in sorted({i.expected_category for i in items}):
        group = [i for i in items if i.expected_category == category]
        per_category[category] = {
            "n": len(group),
            "recall": _ratio(sum(i.correct for i in group), len(group)),
        }
    confusions = Counter(
        f"{i.expected_category} -> {i.predicted_category}" for i in items if not i.correct
    )
    costs = [c.cost_usd for c in calls]
    total_cost = None if any(c is None for c in costs) else sum(costs, Decimal(0))
    latencies = [c.latency_ms for c in calls if c.calls]
    return {
        "n": len(items),
        "accuracy": _ratio(sum(i.correct for i in items), len(items)),
        "accuracy_unambiguous": _ratio(sum(i.correct for i in clear), len(clear)),
        "type_accuracy": _ratio(
            sum(_type_match(i.expected_type, i.predicted_type) for i in typed), len(typed)
        ),
        "missing": sum(i.predicted_category is None for i in items),
        "batches": len(calls),
        "valid_first_try_rate": _ratio(sum(not c.repaired for c in calls), len(calls)),
        "repair_rate": _ratio(sum(c.repaired for c in calls), len(calls)),
        "model_calls": sum(c.calls for c in calls),
        "input_tokens": sum(c.input_tokens for c in calls),
        "output_tokens": sum(c.output_tokens for c in calls),
        "cached_input_tokens": sum(c.cached_input_tokens for c in calls),
        "output_tokens_per_item": (
            round(sum(c.output_tokens for c in calls) / len(items), 1) if calls and items else None
        ),
        "cost_usd": None if total_cost is None else str(total_cost),
        "cost_per_item_usd": (
            None if total_cost is None or not items else str(round(total_cost / len(items), 8))
        ),
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "per_category": per_category,
        "top_confusions": confusions.most_common(10),
    }
