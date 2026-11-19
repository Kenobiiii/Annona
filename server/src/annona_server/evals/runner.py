# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run an eval: load a dataset, classify, score, and write a JSON report.

Real model runs are guarded: the estimated cost is shown first, nothing is spent without
``confirm=True``, and runs stop if the eval budget (``ANNONA_EVAL_BUDGET_USD``, default 1.00)
would be exceeded. Evals bypass the response cache so every run measures the model for real.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlmodel import Session

from annona_core.llm import CallStats, LLMClient, Tier, prompt_schema
from annona_core.llm.client import JSON_INSTRUCTION

from ..ingest.classify import ClassificationInput, RuleClassifier
from ..ingest.llm_classify import PROMPTS, LLMClassifier, schema_for
from ..llm.storage import spent_usd
from .metrics import ItemResult, classification_metrics

REPO = Path(__file__).resolve().parents[4]
DATASETS = REPO / "evals" / "datasets"
RESULTS = REPO / "evals" / "results"
TASK = "product_classification"
EVAL_TASK_PREFIX = "eval:"
CHARS_PER_TOKEN = 3  # conservative (more tokens than reality) for estimates
OUTPUT_TOKENS_PER_ITEM = 30


class BudgetError(RuntimeError):
    pass


def load_dataset(name: str = TASK) -> list[dict[str, Any]]:
    path = DATASETS / f"{name}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate ids")
    return rows


def dataset_hash(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:12]


def budget_usd() -> Decimal:
    return Decimal(os.environ.get("ANNONA_EVAL_BUDGET_USD", "1.00"))


def estimate_cost_usd(
    rows: list[dict[str, Any]], prompt: str, batch_size: int, price_in: Decimal, price_out: Decimal
) -> Decimal:
    """Upper-bound estimate at the given per-token prices (use peak prices)."""
    schema = json.dumps(prompt_schema(schema_for(prompt)), separators=(",", ":"))
    fixed = len(PROMPTS[prompt].system) + len(JSON_INSTRUCTION.format(schema=schema))
    batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]
    chars_in = sum(fixed + sum(len(r["name"]) + 8 for r in b) for b in batches)
    tokens_in = Decimal(chars_in) / CHARS_PER_TOKEN
    tokens_out = Decimal(OUTPUT_TOKENS_PER_ITEM * len(rows))
    return (tokens_in * price_in + tokens_out * price_out).quantize(Decimal("0.000001"))


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
        )
        return out.stdout.strip() or None
    except OSError:
        return None


def run_classification(
    rows: list[dict[str, Any]],
    *,
    classifier: str,
    llm: LLMClient | None = None,
    prompt: str = "v1_plain",
    batch_size: int = 20,
    session: Session | None = None,
    estimated_cost: Decimal | None = None,
) -> dict[str, Any]:
    inputs = [ClassificationInput(r["name"]) for r in rows]
    calls: list[CallStats] = []
    started = datetime.now(UTC)
    if classifier == "rules":
        predictions = [RuleClassifier().classify(x) for x in inputs]
        model = "rules"
    else:
        if llm is None:
            raise ValueError("an LLM client is required for the llm classifier")
        if session is not None and estimated_cost is not None:
            spent = spent_usd(session, EVAL_TASK_PREFIX)
            if spent + estimated_cost > budget_usd():
                raise BudgetError(
                    f"eval budget {budget_usd()} USD would be exceeded "
                    f"(spent {spent}, this run up to {estimated_cost})"
                )
        model = llm.models[Tier.SMALL]
        predictions = LLMClassifier(llm, prompt=prompt, batch_size=batch_size).classify_batch(
            inputs, use_cache=False, stats=calls, task=EVAL_TASK_PREFIX + TASK
        )
    items = [
        ItemResult(
            id=r["id"],
            name=r["name"],
            expected_category=r["expected_category"],
            expected_type=r.get("expected_type"),
            ambiguous=bool(r.get("ambiguous")),
            predicted_category=str(p.category) if p else None,
            predicted_type=p.type if p else None,
        )
        for r, p in zip(rows, predictions, strict=True)
    ]
    return {
        "meta": {
            "task": TASK,
            "dataset_hash": dataset_hash(rows),
            "classifier": classifier,
            "model": model,
            "prompt": prompt if classifier == "llm" else None,
            "batch_size": batch_size if classifier == "llm" else None,
            "started_at": started.isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
            "estimated_cost_usd": None if estimated_cost is None else str(estimated_cost),
        },
        "metrics": classification_metrics(items, calls),
        "items": [_item_json(i) for i in items],
    }


def _item_json(item: ItemResult) -> dict[str, Any]:
    return asdict(item) | {"correct": item.correct, "diet_severity": item.diet_severity}


def save_report(report: dict[str, Any], directory: Path = RESULTS) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    meta = report["meta"]
    stamp = meta["started_at"].replace(":", "").replace("-", "")[:15]
    label = "__".join(
        re.sub(r"[^a-zA-Z0-9.]+", "-", str(x)).strip("-")
        for x in (meta["model"], meta["prompt"] or "na")
    )
    path = directory / f"{stamp}__{meta['task']}__{label}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_reports(directory: Path = RESULTS) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) | {"_file": p.name} for p in sorted(directory.glob("*.json"))]


def rescore(report: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Re-apply the CURRENT dataset labels to a saved run, without calling any model.

    Accuracy fields are recomputed; cost, tokens and latency are kept from the original run.
    """
    by_id = {r["id"]: r for r in rows}
    items = []
    for old in report["items"]:
        row = by_id.get(old["id"])
        if row is None:
            continue  # item removed from the dataset
        items.append(
            ItemResult(
                id=old["id"],
                name=old["name"],
                expected_category=row["expected_category"],
                expected_type=row.get("expected_type"),
                ambiguous=bool(row.get("ambiguous")),
                predicted_category=old["predicted_category"],
                predicted_type=old["predicted_type"],
            )
        )
    fresh = classification_metrics(items, [])
    kept = {k: v for k, v in report["metrics"].items() if k not in fresh or k in _RUN_FIELDS}
    metrics = fresh | kept
    return report | {
        "meta": report["meta"] | {"dataset_hash": dataset_hash(rows), "rescored": True},
        "metrics": metrics,
        "items": [_item_json(i) for i in items],
    }


_RUN_FIELDS = {
    "batches",
    "valid_first_try_rate",
    "repair_rate",
    "model_calls",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "output_tokens_per_item",
    "cost_usd",
    "cost_per_item_usd",
    "latency_ms_p50",
    "latency_ms_p95",
}
