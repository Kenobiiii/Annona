# SPDX-License-Identifier: AGPL-3.0-or-later
"""Receipt-reading evals: score what the vision model read against a known ground truth.

What is measured (all by code, no LLM judge):

* did it find every line (recall) and invent none (precision)?
* are the line amounts, quantities and weights exactly right?
* is the receipt total right, and **does the sum check catch the errors?** A receipt whose lines
  do not add up to the printed total is flagged; ``silent_errors`` counts receipts that are wrong
  but pass the check (the dangerous ones);
* matched to the catalogue, how often is the product right, and how often is a *wrong* product
  pre-selected (``confident_wrong``: the line the app would let through with one tap)?
* cost and time per receipt.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz

from annona_core.llm import CallStats, Image, LLMClient, Tier
from annona_core.receipts import (
    Candidate,
    ReceiptDraft,
    match_line,
    normalise,
    parse_receipt,
    read_receipt,
)
from annona_core.receipts.draft import DraftLine
from annona_core.receipts.parse import ParsedReceipt

from .receipt_synth import (
    CATALOGUE_NAMES,
    POSTAL_CODE,
    RENDERER_VERSION,
    SyntheticReceipt,
    TrueLine,
    make_receipts,
    money,
    render,
)
from .runner import RESULTS, _git_commit

TASK = "receipt_scan"
EVAL_TASK = "eval:" + TASK
MIN_NAME_SIMILARITY = 60  # a predicted line is "the same line" above this (rapidfuzz ratio)
WEIGHT_TOLERANCE_G = 5

CATALOGUE = [Candidate(pid, name, "eval") for pid, name in CATALOGUE_NAMES.items()]


@dataclass
class LineScore:
    printed: str
    found: bool
    total_ok: bool = False
    quantity_ok: bool = False
    weight_ok: bool = False
    name_changed: bool = False  # found by its amount, but the model rewrote the printed text
    predicted_product: int | None = None
    expected_product: int | None = None
    product_ok: bool = False
    preselected: bool = False
    confident_wrong: bool = False
    search_name: str | None = None  # the AI's plain-words reading (only used to search a shop)
    search_name_ok: bool = False  # it leads the matcher to the right product


@dataclass
class ReceiptScore:
    id: str
    difficulty: str
    lines: list[LineScore]
    spurious: list[str]
    total_read: bool
    total_ok: bool
    checksum_ok: bool | None  # None: the total could not be read
    any_error: bool
    silent_error: bool  # wrong, yet the sum check passed
    caught_error: bool  # wrong, and the sum check flagged it
    postal_code_ok: bool = False


def _quantity_ok(true: TrueLine, predicted) -> bool:
    if true.weight_g is not None:
        return True  # weighed lines are judged by their weight
    expected = true.quantity or 1
    return predicted.quantity in (None, Decimal(expected)) or (
        true.quantity is None and predicted.quantity == 1
    )


def _weight_ok(true: TrueLine, predicted) -> bool:
    if true.weight_g is None:
        return predicted.weight is None
    return (
        predicted.weight is not None
        and abs(predicted.weight.amount - Decimal(true.weight_g)) <= WEIGHT_TOLERANCE_G
    )


def score_receipt(truth: SyntheticReceipt, draft: ReceiptDraft) -> ReceiptScore:
    parsed: ParsedReceipt = parse_receipt(draft)
    free = list(range(len(parsed.lines)))
    pairs: list[tuple[TrueLine, int | None, bool]] = []
    for true in truth.lines:
        best, best_i = 0.0, None
        for i in free:
            sim = fuzz.ratio(normalise(true.printed), normalise(parsed.lines[i].raw_text))
            if sim > best:
                best, best_i = sim, i
        if best_i is not None and best >= MIN_NAME_SIMILARITY:
            free.remove(best_i)
            pairs.append((true, best_i, False))
        else:
            pairs.append((true, None, False))
    # Second pass: a line whose text was rewritten ("AOVE 1L" -> "ACEITE 1L") is still the same
    # line if its amount is identical. It counts as found and is reported as a text change.
    for k, (true, index, _) in enumerate(pairs):
        if index is not None:
            continue
        same_amount = [i for i in free if parsed.lines[i].total_cents == true.total_cents]
        if len(same_amount) == 1:
            free.remove(same_amount[0])
            pairs[k] = (true, same_amount[0], True)
    scores: list[LineScore] = []
    for true, best_i, renamed in pairs:
        if best_i is None:
            scores.append(
                LineScore(printed=true.printed, found=False, expected_product=true.product_id)
            )
            continue
        predicted = parsed.lines[best_i]
        match = match_line(predicted.raw_text, CATALOGUE, store_id="eval")
        wrong = match.product_id is not None and match.product_id != true.product_id
        by_name = (
            match_line(predicted.search_name, CATALOGUE, store_id="eval")
            if predicted.search_name
            else match
        )
        scores.append(
            LineScore(
                printed=true.printed,
                found=True,
                name_changed=renamed,
                total_ok=predicted.total_cents == true.total_cents,
                quantity_ok=_quantity_ok(true, predicted),
                weight_ok=_weight_ok(true, predicted),
                predicted_product=match.product_id,
                expected_product=true.product_id,
                product_ok=match.product_id == true.product_id,
                preselected=match.preselected,
                confident_wrong=match.preselected and wrong,
                search_name=predicted.search_name,
                search_name_ok=by_name.product_id == true.product_id,
            )
        )
    total_read = parsed.total_cents is not None
    total_ok = parsed.total_cents == truth.total_cents
    line_errors = any(
        not s.found or not (s.total_ok and s.quantity_ok and s.weight_ok) for s in scores
    )
    any_error = line_errors or bool(free) or not total_ok
    checksum_ok = parsed.total_matches
    flagged = checksum_ok is not True  # mismatch or unreadable total both raise a flag
    return ReceiptScore(
        id=truth.id,
        difficulty=truth.difficulty,
        lines=scores,
        spurious=[parsed.lines[i].raw_text for i in free],
        total_read=total_read,
        total_ok=total_ok,
        checksum_ok=checksum_ok,
        any_error=any_error,
        silent_error=any_error and not flagged,
        caught_error=any_error and flagged,
        postal_code_ok=parsed.postal_code == POSTAL_CODE,
    )


def _rate(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 4)


def aggregate(scores: list[ReceiptScore], calls: list[CallStats]) -> dict[str, Any]:
    lines = [ln for s in scores for ln in s.lines]
    found = [ln for ln in lines if ln.found]
    spurious = sum(len(s.spurious) for s in scores)
    expected_products = [ln for ln in found if ln.expected_product is not None]
    errors = [s for s in scores if s.any_error]
    latencies = sorted(c.latency_ms for c in calls if c.latency_ms)
    cost = sum((c.cost_usd or Decimal(0) for c in calls), Decimal(0))
    return {
        "receipts": len(scores),
        "lines_expected": len(lines),
        "line_recall": _rate(len(found), len(lines)),
        "line_precision": _rate(len(found), len(found) + spurious),
        "amount_exact": _rate(sum(ln.total_ok for ln in found), len(found)),
        "quantity_exact": _rate(sum(ln.quantity_ok for ln in found), len(found)),
        "weight_exact": _rate(sum(ln.weight_ok for ln in found), len(found)),
        "total_exact": _rate(sum(s.total_ok for s in scores), len(scores)),
        "lines_text_changed": sum(ln.name_changed for ln in found),
        "receipts_with_errors": len(errors),
        "errors_caught_by_sum_check": sum(s.caught_error for s in scores),
        "silent_errors": sum(s.silent_error for s in scores),
        "false_alarms": sum((not s.any_error) and s.checksum_ok is not True for s in scores),
        "product_accuracy": _rate(
            sum(ln.product_ok for ln in expected_products), len(expected_products)
        ),
        "preselected_rate": _rate(sum(ln.preselected for ln in found), len(found)),
        "confident_wrong": sum(ln.confident_wrong for ln in found),
        "postal_code_exact": _rate(sum(s.postal_code_ok for s in scores), len(scores)),
        "search_name_given": _rate(sum(ln.search_name is not None for ln in found), len(found)),
        # Would searching by the AI's plain-words name find the right product? (vs raw text)
        "search_name_product_accuracy": _rate(
            sum(ln.search_name_ok for ln in expected_products), len(expected_products)
        ),
        "cost_usd": str(cost),
        "cost_per_receipt_usd": str((cost / len(scores)).quantize(Decimal("0.000001")))
        if scores
        else None,
        "input_tokens": sum(c.input_tokens for c in calls),
        "output_tokens": sum(c.output_tokens for c in calls),
        "latency_ms_p50": int(statistics.median(latencies)) if latencies else None,
        "latency_ms_p95": latencies[int(0.95 * (len(latencies) - 1))] if latencies else None,
    }


def by_difficulty(scores: list[ReceiptScore], calls: list[CallStats]) -> dict[str, dict[str, Any]]:
    out = {}
    for level in ("clean", "noisy", "hard"):
        picked = [(s, c) for s, c in zip(scores, calls, strict=True) if s.difficulty == level]
        if picked:
            out[level] = aggregate([s for s, _ in picked], [c for _, c in picked])
    return out


def draft_from_truth(truth: SyntheticReceipt) -> ReceiptDraft:
    """A perfect transcription (what an ideal reader returns). Used for free, offline checks."""
    lines = [
        DraftLine(
            raw_text=ln.printed,
            quantity=str(ln.quantity) if ln.quantity else None,
            weight=f"{ln.weight_g / 1000:.3f} kg".replace(".", ",") if ln.weight_g else None,
            unit_price=money(ln.unit_price_cents) if ln.unit_price_cents else None,
            total=money(ln.total_cents),
        )
        for ln in truth.lines
    ]
    if truth.discount_cents:
        lines.append(DraftLine(raw_text="DESCUENTO", total=money(truth.discount_cents)))
    return ReceiptDraft(
        store=truth.store,
        postal_code=POSTAL_CODE,
        date=truth.purchased_on.strftime("%d/%m/%Y"),
        total=money(truth.total_cents),
        lines=lines,
    )


def run_matching_only(n: int = 40, seed: int = 7) -> dict[str, Any]:
    """Free: how well does the matcher do when the text is read perfectly?"""
    truths = make_receipts(n, seed)
    scores = [score_receipt(t, draft_from_truth(t)) for t in truths]
    return aggregate(scores, [])


def estimate_cost_usd(n: int, price_in: Decimal, price_out: Decimal) -> Decimal:
    """Upper bound: ~2,500 input tokens (prompt, schema and a photo) and ~700 output per receipt."""
    return (n * (Decimal(2500) * price_in + Decimal(700) * price_out)).quantize(Decimal("0.000001"))


def run_receipts(
    llm: LLMClient,
    *,
    n: int = 12,
    seed: int = 7,
    save_images: str | None = None,
) -> dict[str, Any]:
    truths = make_receipts(n, seed)
    scores: list[ReceiptScore] = []
    calls: list[CallStats] = []
    details: list[dict[str, Any]] = []
    started = datetime.now(UTC)
    for truth in truths:
        photo = render(truth)
        if save_images:
            from pathlib import Path

            folder = Path(save_images)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{truth.id}_{truth.difficulty}.jpg").write_bytes(photo)
        began = time.monotonic()
        try:
            draft, stats = read_receipt(
                llm, Image("image/jpeg", photo), use_cache=False, task=EVAL_TASK
            )
        except Exception as error:  # a failed read is a result, not a crash of the whole eval
            draft, stats = (
                ReceiptDraft(lines=[]),
                CallStats(latency_ms=int((time.monotonic() - began) * 1000)),
            )
            details.append({"id": truth.id, "error": f"{type(error).__name__}: {error}"[:300]})
        scores.append(score_receipt(truth, draft))
        calls.append(stats)
        details.append(
            {
                "id": truth.id,
                "difficulty": truth.difficulty,
                "truth": truth.spec(),
                "prediction": draft.model_dump(),
                "score": {
                    "any_error": scores[-1].any_error,
                    "silent_error": scores[-1].silent_error,
                    "total_ok": scores[-1].total_ok,
                    "missed": [ln.printed for ln in scores[-1].lines if not ln.found],
                    "spurious": scores[-1].spurious,
                    "wrong_amounts": [
                        ln.printed for ln in scores[-1].lines if ln.found and not ln.total_ok
                    ],
                    "confident_wrong": [
                        ln.printed for ln in scores[-1].lines if ln.confident_wrong
                    ],
                },
            }
        )
    spec_hash = (
        __import__("hashlib")
        .sha256(json.dumps([t.spec() for t in truths], sort_keys=True).encode())
        .hexdigest()[:12]
    )
    return {
        "meta": {
            "task": TASK,
            "model": llm.models[Tier.SMALL],
            "n": n,
            "seed": seed,
            "dataset_hash": spec_hash,
            "renderer_version": RENDERER_VERSION,
            "started_at": started.isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
        },
        "metrics": aggregate(scores, calls),
        "by_difficulty": by_difficulty(scores, calls),
        "items": details,
    }


def save_report(report: dict[str, Any]) -> Any:
    meta = report["meta"]
    stamp = meta["started_at"].replace("-", "").replace(":", "")
    model = meta["model"].replace("/", "-")
    path = RESULTS / f"{stamp}__receipts__{model}__s{meta['seed']}n{meta['n']}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
