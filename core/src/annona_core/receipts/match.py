# SPDX-License-Identifier: AGPL-3.0-or-later
"""Match what a receipt printed with a product of the catalogue. Pure code (rapidfuzz).

Receipts abbreviate ("LECHE SEMI 6X1L", "FILETE PECHUGA POLLO"), so a plain string ratio fails.
The score compares word by word: a printed word counts as found in a product name when it is a
prefix of one of its words ("SEMI" -> "semidesnatada") or very similar to it. It combines the share
of the printed text that was found (recall) with the share of the product name covered (precision).

The result is a *suggestion with a confidence*. Nothing is applied from it automatically: only an
alias the person confirmed before reaches confidence 1.0, and even that line needs the person's
confirmation of the receipt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz import fuzz

AUTO_SELECT_CONFIDENCE = Decimal("0.85")  # the app pre-selects lines at or above this
SUGGEST_CONFIDENCE = Decimal("0.50")  # below this there is no suggestion at all
MIN_MARGIN = Decimal("0.08")  # a clear winner: ahead of the runner-up by at least this
_STOP = frozenset(
    {
        # function words
        "DE", "DEL", "LA", "EL", "LOS", "LAS", "CON", "SIN", "Y", "EN", "AL", "A",
        # packaging and presentation words printed on receipts, rarely part of a product name
        "BANDEJA", "MALLA", "BOLSA", "PACK", "PAQ", "PAQUETE", "CAJA", "TARRINA", "BOTELLA",
        "LATA", "BRICK", "ENVASE", "UNIDAD", "UNID", "GRANDE", "GRANDES", "MEDIANO", "MEDIANOS",
        "CLASICA", "CLASICAS", "CLASICO", "CLASICOS", "MESA",
    }
)  # fmt: skip
_UNIT_TOKENS = frozenset({"KG", "G", "GR", "L", "LT", "ML", "CL", "UD", "UDS", "X", "EUR", "E"})


def normalise(text: str) -> str:
    """Upper case, no accents, no prices, quantities or unit words: "2 Leche semi 6x1L 4,98"
    -> "LECHE SEMI"."""
    folded = unicodedata.normalize("NFKD", text.upper())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r"\d+[.,]\d+", " ", folded)  # prices and weights
    folded = re.sub(r"\d+\s*[X*]\s*\d+\s*[A-Z]*", " ", folded)  # "6X1L"
    folded = re.sub(r"\b\d+\s*(KG|GR|G|ML|CL|LT|L|UD|UDS)\b", " ", folded)
    folded = re.sub(r"\b\d+\b", " ", folded)
    words = [w for w in re.findall(r"[A-Z]+", folded) if w not in _UNIT_TOKENS]
    return " ".join(words)


def _tokens(text: str) -> list[str]:
    return [w for w in normalise(text).split() if w not in _STOP and len(w) > 1]


def _found(word: str, candidate_words: list[str]) -> tuple[float, str | None]:
    """How well a printed word is found among the product's words, and which one matched."""
    best, which = 0.0, None
    for c in candidate_words:
        if len(word) >= 3 and c.startswith(word):
            # An abbreviation: "SEMI" in "SEMIDESNATADA". Four letters or more are convincing;
            # three are weak ("AVE", a misread "AOVE", is a prefix of "AVENA"); fewer do not count.
            score = 1.0 if len(word) >= 4 else 0.5
        else:
            ratio = fuzz.ratio(word, c) / 100
            score = ratio if ratio >= 0.8 else 0.0
        if score > best:
            best, which = score, c
    return best, which


def _score(printed: list[str], candidate: list[str]) -> float:
    if not printed or not candidate:
        return 0.0
    found = [(word, *_found(word, candidate)) for word in printed]
    # A three-letter abbreviation is weak alone, but credible when another, longer word of the
    # same line also matches this product ("YOGUR" + "NAT" -> "Yogur natural").
    corroborated = any(len(word) >= 4 and score >= 0.95 for word, score, _ in found)
    found_chars = total_chars = 0.0
    covered: set[str] = set()
    for word, score, which in found:
        if len(word) == 3 and score == 0.5 and corroborated:
            score = 1.0
        found_chars += len(word) * score
        total_chars += len(word)
        if which is not None:
            covered.add(which)
    recall = found_chars / total_chars
    precision = sum(len(c) for c in covered) / sum(len(c) for c in candidate)
    # An abbreviation covers little of a long name by design: precision only breaks ties.
    return 0.9 * recall + 0.1 * precision


@dataclass(frozen=True)
class Candidate:
    product_id: int
    name: str
    store_id: str | None = None
    brand: str | None = None


@dataclass(frozen=True)
class LineMatch:
    product_id: int | None
    confidence: Decimal  # 0..1
    source: str  # "alias" | "fuzzy" | "none"
    runner_up_id: int | None = None
    alternatives: tuple[tuple[int, Decimal], ...] = ()  # best other candidates (id, confidence)

    @property
    def preselected(self) -> bool:
        """Safe to pre-select in the review screen (the person still confirms the receipt)."""
        return self.product_id is not None and self.confidence >= AUTO_SELECT_CONFIDENCE


def _q(value: float) -> Decimal:
    return Decimal(str(round(max(0.0, min(1.0, value)), 3)))


def match_line(
    raw_text: str,
    candidates: list[Candidate],
    aliases: dict[str, int] | None = None,
    *,
    store_id: str | None = None,
) -> LineMatch:
    """The best catalogue product for a printed line, with a confidence in [0, 1]."""
    key = normalise(raw_text)
    if aliases and key in aliases:
        return LineMatch(product_id=aliases[key], confidence=Decimal(1), source="alias")
    printed = _tokens(raw_text)
    # Store products first: a receipt names what a shop sells. Generic foods (no store, e.g.
    # "Banana") are only a fallback, so "QUESO FRESCO" keeps its shop product over a generic one.
    in_store = [c for c in candidates if c.store_id is not None]
    match = _fuzzy(printed, in_store, store_id)
    if match.product_id is None:
        generic = _fuzzy(printed, [c for c in candidates if c.store_id is None], store_id)
        if generic.product_id is not None:
            return generic
    return match


def _fuzzy(printed: list[str], candidates: list[Candidate], store_id: str | None) -> LineMatch:
    scored = []
    for c in candidates:
        name = c.name
        if c.brand and name.lower().endswith(c.brand.lower()):
            name = name[: -len(c.brand)]
        own_store = 0 if store_id is not None and c.store_id == store_id else 1
        scored.append((_score(printed, _tokens(name)), c.product_id, own_store))
    # A tie goes to the receipt's own store, then to the lowest id (deterministic).
    scored.sort(key=lambda x: (-round(x[0], 6), x[2], x[1]))
    if not scored or scored[0][0] < float(SUGGEST_CONFIDENCE):
        return LineMatch(
            product_id=None, confidence=_q(scored[0][0]) if scored else Decimal(0), source="none"
        )
    best = scored[0]
    others = tuple((pid, _q(s)) for s, pid, _ in scored[1:4] if s >= float(SUGGEST_CONFIDENCE))
    confidence = _q(best[0])
    if len(scored) > 1 and best[0] - scored[1][0] < float(MIN_MARGIN):
        # An unclear winner is not trusted as much: cap it below the pre-selection level.
        confidence = min(confidence, AUTO_SELECT_CONFIDENCE - Decimal("0.01"))
    return LineMatch(
        product_id=best[1],
        confidence=confidence,
        source="fuzzy",
        runner_up_id=scored[1][1] if len(scored) > 1 else None,
        alternatives=others,
    )
