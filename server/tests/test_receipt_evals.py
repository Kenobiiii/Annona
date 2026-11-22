# SPDX-License-Identifier: AGPL-3.0-or-later
"""The receipt eval itself: generator, scorer and the regressions it found. No LLM, no network."""

from decimal import Decimal

import pytest

from annona_core.receipts import DraftLine, ReceiptDraft
from annona_server.evals.receipt_synth import (
    PRODUCTS,
    make_receipts,
    receipt_lines,
    render,
)
from annona_server.evals.receipts import (
    aggregate,
    draft_from_truth,
    run_matching_only,
    score_receipt,
)
from annona_server.receipts import check_image


def test_receipts_are_reproducible_and_internally_consistent():
    a, b = make_receipts(9, seed=3), make_receipts(9, seed=3)
    assert [r.spec() for r in a] == [r.spec() for r in b]
    assert [r.difficulty for r in a] == ["clean", "noisy", "hard"] * 3
    for r in a:
        assert r.total_cents == sum(ln.total_cents for ln in r.lines) + r.discount_cents
        assert any("TOTAL" in row for row in receipt_lines(r))
    assert make_receipts(9, seed=4)[0].spec() != a[0].spec()


def test_the_synthetic_catalogue_is_marked_as_invented():
    assert len({pid for pid, *_ in PRODUCTS}) == len(PRODUCTS)


def test_photos_are_valid_jpegs_that_differ_by_difficulty_but_not_between_runs():
    clean, noisy, hard = make_receipts(3, seed=7)
    photos = [render(r) for r in (clean, noisy, hard)]
    for data in photos:
        assert check_image(data)[0] == "image/jpeg" and len(data) < 8 * 1024 * 1024
    assert len(set(photos)) == 3
    assert render(clean) == photos[0]  # the same seed gives the same photo


def truth_and_draft(index=0):
    truth = make_receipts(3, seed=7)[index]
    return truth, draft_from_truth(truth)


def test_a_perfect_reading_has_no_errors():
    for i in range(3):
        truth, draft = truth_and_draft(i)
        score = score_receipt(truth, draft)
        assert not score.any_error and score.checksum_ok is True and score.total_ok
        assert all(
            ln.found and ln.total_ok and ln.weight_ok and ln.quantity_ok for ln in score.lines
        )


def test_a_missed_line_is_an_error_and_the_sum_check_catches_it():
    truth, draft = truth_and_draft()
    gone = draft.model_copy(update={"lines": draft.lines[1:]})
    score = score_receipt(truth, gone)
    assert score.any_error and score.caught_error and not score.silent_error
    assert [ln.found for ln in score.lines].count(False) == 1


def test_a_wrong_quantity_is_invisible_to_the_sum_check():
    """Amounts add up, yet the pantry would get the wrong number of packs: a silent error."""
    truth, draft = truth_and_draft()
    index = next(i for i, ln in enumerate(truth.lines) if ln.quantity)
    lines = list(draft.lines)
    lines[index] = lines[index].model_copy(update={"quantity": "1"})
    score = score_receipt(truth, draft.model_copy(update={"lines": lines}))
    assert score.checksum_ok is True and score.any_error and score.silent_error


def test_a_pack_size_copied_into_the_weight_no_longer_corrupts_the_amount():
    """The bug the first eval found: '800G' in the name was taken as the weight bought."""
    truth, draft = truth_and_draft()
    index = next(
        i for i, ln in enumerate(truth.lines) if ln.printed.endswith(("500G", "800G", "1KG"))
    )
    lines = list(draft.lines)
    size = truth.lines[index].printed.split()[-1]
    lines[index] = lines[index].model_copy(update={"weight": size})
    score = score_receipt(truth, draft.model_copy(update={"lines": lines}))
    assert score.lines[index].weight_ok and not score.any_error


def test_a_rewritten_name_with_the_same_amount_is_a_text_change_not_a_lost_line():
    truth, draft = truth_and_draft()
    lines = list(draft.lines)
    lines[0] = lines[0].model_copy(update={"raw_text": "XYZZY QQQ"})
    score = score_receipt(truth, draft.model_copy(update={"lines": lines}))
    assert score.lines[0].found and score.lines[0].name_changed and not score.any_error
    assert aggregate([score], [])["lines_text_changed"] == 1


def test_a_confident_wrong_match_is_counted():
    # Same amount as an olive-oil line, but a name that points firmly at another product.
    truth = next(
        r for r in make_receipts(30, seed=7) if any(ln.printed == "AOVE 1L" for ln in r.lines)
    )
    draft = draft_from_truth(truth)
    lines = [
        ln.model_copy(update={"raw_text": "COPOS AVENA 800G"}) if ln.raw_text == "AOVE 1L" else ln
        for ln in draft.lines
    ]
    score = score_receipt(truth, draft.model_copy(update={"lines": lines}))
    assert aggregate([score], [])["confident_wrong"] == 1


def test_matching_with_a_perfect_reading_is_safe_and_useful():
    """Regression gate for the matcher (free): never confidently wrong, mostly pre-selected."""
    metrics = run_matching_only(60, seed=7)
    assert metrics["confident_wrong"] == 0
    assert metrics["product_accuracy"] >= 0.93
    assert metrics["preselected_rate"] >= 0.85
    assert metrics["line_recall"] == 1.0 and metrics["silent_errors"] == 0


def test_aggregate_handles_no_calls_and_counts_receipts():
    truth, draft = truth_and_draft()
    metrics = aggregate([score_receipt(truth, draft)], [])
    assert metrics["receipts"] == 1 and metrics["cost_usd"] == "0"
    assert Decimal(metrics["cost_per_receipt_usd"]) == 0 and metrics["latency_ms_p50"] is None


@pytest.mark.parametrize("field", ["total", "date", "store"])
def test_a_receipt_header_that_could_not_be_read_is_flagged(field):
    truth, draft = truth_and_draft()
    blank = draft.model_copy(update={field: None})
    score = score_receipt(truth, blank)
    if field == "total":
        assert score.total_read is False and score.checksum_ok is None and score.any_error
        assert score.caught_error  # an unreadable total is flagged too
    else:
        assert not score.any_error  # a missing store or date is not an amount error


def test_draft_lines_are_plain_strings_as_printed():
    _, draft = truth_and_draft()
    assert all(isinstance(ln, DraftLine) and isinstance(ln.total, str) for ln in draft.lines)
    assert isinstance(draft, ReceiptDraft)
