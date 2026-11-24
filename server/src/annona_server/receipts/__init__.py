# SPDX-License-Identifier: AGPL-3.0-or-later
"""Receipts: scan a photo, review the lines, confirm to update the pantry and prices.

Privacy: the photo is stored only on this server (next to the database) and goes nowhere except the
configured AI provider, once, to be read. Nothing from a receipt reaches the pantry or the prices
until the person confirms each line.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from annona_core.domain import (
    Household,
    PantryItem,
    Price,
    PriceSource,
    Product,
    Receipt,
    ReceiptAlias,
    ReceiptLine,
    ReceiptLineStatus,
    ReceiptStatus,
    Unit,
)
from annona_core.llm import CallStats, Image, LLMClient
from annona_core.receipts import (
    Candidate,
    LineEffect,
    ParsedLine,
    line_effect,
    match_line,
    normalise,
    parse_receipt,
    read_receipt,
)
from annona_core.receipts.parse import ParsedReceipt

from ..db.repositories import (
    ReceiptAliasRepository,
    ReceiptLineRepository,
    ReceiptRepository,
    SqlPantryRepository,
    SqlPriceRepository,
    SqlProductRepository,
)
from ..planner import language

MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAGIC = {
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
}


class BadImage(ValueError):
    """The upload is not a usable photo."""


class ReceiptNotFound(LookupError):
    pass


class ReceiptClosed(Exception):
    """The receipt was already confirmed or discarded."""


class NeedsAmount(Exception):
    def __init__(self, line_ids: list[int]) -> None:
        super().__init__(f"amount needed for lines {line_ids}")
        self.line_ids = line_ids


def receipts_dir(engine: Engine) -> Path:
    """Where photos live: ``ANNONA_RECEIPTS_DIR`` or ``receipts/`` next to the SQLite file."""
    configured = os.environ.get("ANNONA_RECEIPTS_DIR")
    if configured:
        return Path(configured)
    database = engine.url.database
    if engine.dialect.name == "sqlite" and database and database != ":memory:":
        return Path(database).parent / "receipts"
    return Path("data/receipts")


def check_image(data: bytes) -> tuple[str, str]:
    """(media type, extension) from the file's own bytes, not from what the client claims."""
    if not data:
        raise BadImage("the image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise BadImage(f"the image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    for magic, kind in _MAGIC.items():
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise BadImage("only JPEG, PNG or WebP photos are accepted")


def _sidecar(image_path: str | None) -> Path | None:
    return Path(image_path).with_suffix(".json") if image_path else None


def _store_from_text(text: str | None, known: set[str]) -> str | None:
    """The catalogue store a printed name refers to ("MERCADONA S.A." -> "mercadona")."""
    if not text:
        return None
    low = text.lower()
    return next((s for s in sorted(known) if s.lower() in low), None)


@dataclass
class ScanResult:
    receipt: Receipt
    stats: CallStats
    parsed: ParsedReceipt
    lines: list[ReceiptLine] = field(default_factory=list)


def _candidates(session: Session) -> list[Candidate]:
    return [
        Candidate(p.id, p.name, p.store_id, p.brand)
        for p in SqlProductRepository(session).list()
        if p.id is not None
    ]


def _aliases(session: Session, household_id: int, store_id: str | None) -> dict[str, int]:
    return {
        a.normalized_text: a.product_id
        for a in ReceiptAliasRepository(session).list(household_id=household_id)
        if a.store_id == store_id
    }


def scan_receipt(
    session: Session,
    llm: LLMClient,
    household: Household,
    folder: Path,
    data: bytes,
) -> ScanResult:
    """Read a receipt photo: store it, extract the lines with the AI, parse, check and match."""
    media_type, extension = check_image(data)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.{extension}"
    path.write_bytes(data)
    try:
        draft, stats = read_receipt(llm, Image(media_type, data), language=language())
    except Exception:
        path.unlink(missing_ok=True)  # nothing was read: do not keep an orphan photo
        raise
    parsed = parse_receipt(draft)

    candidates = _candidates(session)
    stores = {c.store_id for c in candidates if c.store_id}
    store_id = _store_from_text(parsed.store, stores)
    aliases = _aliases(session, household.id, store_id)
    when = (
        datetime(
            parsed.purchased_on.year,
            parsed.purchased_on.month,
            parsed.purchased_on.day,
            12,
            tzinfo=UTC,
        )
        if parsed.purchased_on
        else None
    )
    receipt = ReceiptRepository(session).add(
        Receipt(
            household_id=household.id,
            store_id=store_id,
            purchased_at=when,
            total_cents=parsed.total_cents,
            currency=household.currency,
            image_path=str(path),
        )
    )
    assert receipt.id is not None
    lines: list[ReceiptLine] = []
    details: list[dict[str, Any]] = []
    for item in parsed.lines:
        match = match_line(item.raw_text, candidates, aliases, store_id=store_id)
        amount, unit = (
            (item.weight.amount, item.weight.unit)
            if item.weight is not None
            else (item.quantity, Unit.UNIT if item.quantity is not None else None)
        )
        line = ReceiptLineRepository(session).add(
            ReceiptLine(
                receipt_id=receipt.id,
                raw_text=item.raw_text,
                amount=amount,
                unit=unit,
                total_cents=item.total_cents,
                matched_product_id=match.product_id,
                confidence=match.confidence,
                status=(
                    ReceiptLineStatus.SUGGESTED if match.product_id else ReceiptLineStatus.UNMATCHED
                ),
            )
        )
        lines.append(line)
        details.append(
            {
                "line_id": line.id,
                "alternatives": [[pid, str(c)] for pid, c in match.alternatives],
                "source": match.source,
                "issues": list(item.issues),
                "unit_price_cents": item.unit_price_cents,
                "weight": (
                    {"amount": str(item.weight.amount), "unit": str(item.weight.unit)}
                    if item.weight
                    else None
                ),
                "quantity": str(item.quantity) if item.quantity is not None else None,
            }
        )
    sidecar = _sidecar(str(path))
    assert sidecar is not None
    sidecar.write_text(
        json.dumps(
            {
                "store_text": parsed.store,
                "discounts_cents": parsed.discounts_cents,
                "skipped": parsed.skipped,
                "issues": parsed.issues,
                "lines": details,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return ScanResult(receipt=receipt, stats=stats, parsed=parsed, lines=lines)


# ---------------------------------------------------------------------------------------------
# Reading a stored receipt for the review screen
# ---------------------------------------------------------------------------------------------


@dataclass
class LineView:
    line: ReceiptLine
    product: Product | None
    alternatives: list[tuple[Product, Decimal]]
    effect: LineEffect | None
    issues: list[str]
    preselected: bool


@dataclass
class ReceiptView:
    receipt: Receipt
    lines: list[LineView]
    store_text: str | None
    skipped: list[str]
    discounts_cents: int
    issues: list[str]

    @property
    def lines_total_cents(self) -> int:
        return sum(v.line.total_cents for v in self.lines) + self.discounts_cents

    @property
    def total_matches(self) -> bool | None:
        total = self.receipt.total_cents
        return None if total is None else self.lines_total_cents == total


def _owned(session: Session, household: Household, receipt_id: int) -> Receipt:
    receipt = ReceiptRepository(session).get(receipt_id)
    if receipt is None or receipt.household_id != household.id:
        raise ReceiptNotFound(f"receipt {receipt_id} not found")
    return receipt


def _load_sidecar(receipt: Receipt) -> dict[str, Any]:
    path = _sidecar(receipt.image_path)
    if path is not None and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"store_text": None, "discounts_cents": 0, "skipped": [], "issues": [], "lines": []}


def _parsed_line(line: ReceiptLine, detail: dict[str, Any]) -> ParsedLine:
    from annona_core.domain.units import Quantity

    weight = detail.get("weight")
    quantity = detail.get("quantity")
    return ParsedLine(
        raw_text=line.raw_text,
        total_cents=line.total_cents,
        quantity=Decimal(quantity) if quantity else None,
        weight=Quantity(amount=Decimal(weight["amount"]), unit=Unit(weight["unit"]))
        if weight
        else None,
        unit_price_cents=detail.get("unit_price_cents"),
        issues=tuple(detail.get("issues", ())),
    )


def view_receipt(session: Session, household: Household, receipt_id: int) -> ReceiptView:
    from annona_core.receipts import AUTO_SELECT_CONFIDENCE

    receipt = _owned(session, household, receipt_id)
    side = _load_sidecar(receipt)
    by_line = {d["line_id"]: d for d in side["lines"]}
    products = SqlProductRepository(session)
    views = []
    for line in ReceiptLineRepository(session).list(receipt_id=receipt_id):
        detail = by_line.get(line.id, {})
        product = products.get(line.matched_product_id) if line.matched_product_id else None
        alternatives = [
            (p, Decimal(c))
            for pid, c in detail.get("alternatives", [])
            if (p := products.get(pid)) is not None
        ]
        effect = line_effect(_parsed_line(line, detail), product) if product else None
        confident = (
            product is not None
            and line.confidence is not None
            and line.confidence >= AUTO_SELECT_CONFIDENCE
            and line.status != ReceiptLineStatus.IGNORED
        )
        views.append(
            LineView(
                line=line,
                product=product,
                alternatives=alternatives,
                effect=effect,
                issues=list(detail.get("issues", [])),
                preselected=bool(confident),
            )
        )
    return ReceiptView(
        receipt=receipt,
        lines=views,
        store_text=side["store_text"],
        skipped=side["skipped"],
        discounts_cents=side["discounts_cents"],
        issues=side["issues"],
    )


# ---------------------------------------------------------------------------------------------
# Confirming: the only place where a receipt changes the pantry and the prices
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    line_id: int
    product_id: int | None = None  # the product the person chose or accepted for the line
    ignore: bool = False
    amount: Decimal | None = None  # overrides the proposed amount
    unit: Unit | None = None


@dataclass
class Applied:
    line_id: int
    product_id: int
    name: str
    amount: Decimal
    unit: str
    price_cents: int | None
    notes: tuple[str, ...]


def confirm_receipt(
    session: Session, household: Household, receipt_id: int, decisions: list[Decision]
) -> list[Applied]:
    """Apply exactly the lines the person confirmed; everything else is ignored.

    A line is applied only if the request names its product (so it was seen and chosen). Lines
    whose amount cannot be known (no weight, no pack size) must come with an amount, or the whole
    request is refused before anything changes.
    """
    receipt = _owned(session, household, receipt_id)
    if receipt.status != ReceiptStatus.PENDING_REVIEW:
        raise ReceiptClosed(f"receipt {receipt_id} is already {receipt.status}")
    side = _load_sidecar(receipt)
    by_line = {d["line_id"]: d for d in side["lines"]}
    lines = {ln.id: ln for ln in ReceiptLineRepository(session).list(receipt_id=receipt_id)}
    products = SqlProductRepository(session)

    plan: list[tuple[ReceiptLine, Product, Decimal, Unit, LineEffect]] = []
    missing: list[int] = []
    for decision in decisions:
        line = lines.get(decision.line_id)
        if line is None:
            raise ReceiptNotFound(f"line {decision.line_id} is not in receipt {receipt_id}")
        if decision.ignore or decision.product_id is None:
            continue
        product = products.get(decision.product_id)
        if product is None:
            raise ReceiptNotFound(f"product {decision.product_id} not found")
        effect = line_effect(_parsed_line(line, by_line.get(line.id, {})), product)
        amount = decision.amount if decision.amount is not None else effect.pantry_amount
        unit = decision.unit or effect.pantry_unit
        if amount is None or unit is None or amount <= 0:
            missing.append(line.id)  # type: ignore[arg-type]
            continue
        plan.append((line, product, amount, unit, effect))
    if missing:
        raise NeedsAmount(missing)

    pantry, prices = SqlPantryRepository(session), SqlPriceRepository(session)
    aliases = ReceiptAliasRepository(session)
    known = {(a.store_id, a.normalized_text): a for a in aliases.list(household_id=household.id)}
    observed = receipt.purchased_at or datetime.now(UTC)
    applied: list[Applied] = []
    applied_ids: set[int] = set()
    for line, product, amount, unit, effect in plan:
        assert product.id is not None and line.id is not None
        existing = [
            i
            for i in pantry.for_household(household.id)
            if i.product_id == product.id and i.unit == unit
        ]
        if existing:
            pantry.update(existing[0].model_copy(update={"amount": existing[0].amount + amount}))
        else:
            pantry.add(
                PantryItem(
                    household_id=household.id, product_id=product.id, amount=amount, unit=unit
                )
            )
        store = receipt.store_id or product.store_id
        if effect.price_cents is not None and store:
            prices.add(
                Price(
                    product_id=product.id,
                    store_id=store,
                    amount_cents=effect.price_cents,
                    currency=receipt.currency,
                    source=PriceSource.RECEIPT,
                    observed_at=observed,
                    receipt_line_id=line.id,
                )
            )
        key = (receipt.store_id, normalise(line.raw_text))
        if key[1] and key not in known:
            known[key] = aliases.add(
                ReceiptAlias(
                    household_id=household.id,
                    store_id=receipt.store_id,
                    normalized_text=key[1],
                    product_id=product.id,
                )
            )
        elif key[1] and known[key].product_id != product.id:
            known[key] = aliases.update(known[key].model_copy(update={"product_id": product.id}))
        ReceiptLineRepository(session).update(
            line.model_copy(
                update={"matched_product_id": product.id, "status": ReceiptLineStatus.CONFIRMED}
            )
        )
        applied_ids.add(line.id)
        applied.append(
            Applied(
                line.id,
                product.id,
                product.name,
                amount,
                str(unit),
                effect.price_cents,
                effect.notes,
            )
        )
    for line in lines.values():
        if line.id not in applied_ids:
            ReceiptLineRepository(session).update(
                line.model_copy(update={"status": ReceiptLineStatus.IGNORED})
            )
    ReceiptRepository(session).update(
        receipt.model_copy(update={"status": ReceiptStatus.CONFIRMED})
    )
    return applied


def discard_receipt(session: Session, household: Household, receipt_id: int) -> None:
    """Throw a scan away: nothing is applied and the photo is deleted from the server."""
    receipt = _owned(session, household, receipt_id)
    if receipt.status != ReceiptStatus.PENDING_REVIEW:
        raise ReceiptClosed(f"receipt {receipt_id} is already {receipt.status}")
    for path in (receipt.image_path, _sidecar(receipt.image_path)):
        if path:
            Path(path).unlink(missing_ok=True)
    ReceiptRepository(session).update(
        receipt.model_copy(update={"status": ReceiptStatus.DISCARDED, "image_path": None})
    )


def image_file(session: Session, household: Household, receipt_id: int) -> Path | None:
    receipt = _owned(session, household, receipt_id)
    path = Path(receipt.image_path) if receipt.image_path else None
    return path if path and path.exists() else None


__all__ = [
    "Applied",
    "BadImage",
    "Decision",
    "NeedsAmount",
    "ReceiptClosed",
    "ReceiptNotFound",
    "ScanResult",
    "check_image",
    "confirm_receipt",
    "discard_receipt",
    "image_file",
    "receipts_dir",
    "scan_receipt",
    "view_receipt",
]
