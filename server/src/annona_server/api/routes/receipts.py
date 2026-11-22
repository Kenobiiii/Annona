# SPDX-License-Identifier: AGPL-3.0-or-later
"""Receipt scanning: upload a photo, review the lines, confirm or discard."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from annona_core.domain import ReceiptStatus, Unit

from ...receipts import (
    BadImage,
    Decision,
    LineView,
    NeedsAmount,
    ReceiptClosed,
    ReceiptNotFound,
    ReceiptView,
    confirm_receipt,
    discard_receipt,
    image_file,
    receipts_dir,
    scan_receipt,
    view_receipt,
)
from ..deps import HouseholdDep, SessionDep
from ..errors import APIError

router = APIRouter(tags=["receipts"])


class ProductRef(BaseModel):
    product_id: int
    name: str
    confidence: Decimal | None = None


class ReceiptLineOut(BaseModel):
    id: int
    raw_text: str
    total_cents: int
    quantity: Decimal | None = Field(description="as printed: units, or a weight in g/ml")
    unit: str | None
    product: ProductRef | None = Field(description="the suggested product, if any")
    confidence: Decimal | None
    preselected: bool = Field(description="confident enough to pre-select (still needs confirming)")
    alternatives: list[ProductRef]
    proposed_amount: Decimal | None = Field(
        description="what would go to the pantry; null = unknown"
    )
    proposed_unit: str | None
    proposed_price_cents: int | None = Field(description="per pack of the product")
    notes: list[str] = Field(
        description="assumed_one_pack | unknown_pack_size | price_from_weight | no_price"
    )
    issues: list[str] = Field(description="line_math: quantity x unit price != total")
    status: str


class ReceiptOut(BaseModel):
    id: int
    status: ReceiptStatus
    store_id: str | None
    store_text: str | None
    purchased_on: date | None
    total_cents: int | None
    lines_total_cents: int
    total_matches: bool | None = Field(
        description="do the lines add up to the printed total? null if it could not be read"
    )
    issues: list[str]
    skipped: list[str] = Field(description="lines the AI read without a legible amount")
    lines: list[ReceiptLineOut]
    has_image: bool


def _line_out(view: LineView) -> ReceiptLineOut:
    line, product, effect = view.line, view.product, view.effect
    return ReceiptLineOut(
        id=line.id,  # type: ignore[arg-type]
        raw_text=line.raw_text,
        total_cents=line.total_cents,
        quantity=line.amount,
        unit=str(line.unit) if line.unit else None,
        product=(
            ProductRef(product_id=product.id, name=product.name, confidence=line.confidence)  # type: ignore[arg-type]
            if product
            else None
        ),
        confidence=line.confidence,
        preselected=view.preselected,
        alternatives=[
            ProductRef(product_id=p.id, name=p.name, confidence=c)  # type: ignore[arg-type]
            for p, c in view.alternatives
        ],
        proposed_amount=effect.pantry_amount if effect else None,
        proposed_unit=str(effect.pantry_unit) if effect and effect.pantry_unit else None,
        proposed_price_cents=effect.price_cents if effect else None,
        notes=list(effect.notes) if effect else [],
        issues=view.issues,
        status=str(line.status),
    )


def _out(view: ReceiptView) -> ReceiptOut:
    receipt = view.receipt
    return ReceiptOut(
        id=receipt.id,  # type: ignore[arg-type]
        status=receipt.status,
        store_id=receipt.store_id,
        store_text=view.store_text,
        purchased_on=receipt.purchased_at.date() if receipt.purchased_at else None,
        total_cents=receipt.total_cents,
        lines_total_cents=view.lines_total_cents,
        total_matches=view.total_matches,
        issues=view.issues,
        skipped=view.skipped,
        lines=[_line_out(v) for v in view.lines],
        has_image=bool(receipt.image_path),
    )


@router.post("/receipts", response_model=ReceiptOut, status_code=201)
def upload_receipt(
    request: Request,
    session: SessionDep,
    household: HouseholdDep,
    file: Annotated[
        UploadFile, File(description="a JPEG, PNG or WebP photo of the receipt (max 8 MB)")
    ],
) -> ReceiptOut:
    """Read a receipt photo with the AI (5-20 s). Nothing is applied until you confirm."""
    data = file.file.read(8 * 1024 * 1024 + 1)
    try:
        result = scan_receipt(
            session,
            request.app.state.llm_factory(session),
            household,
            receipts_dir(request.app.state.engine),
            data,
        )
    except BadImage as error:
        raise APIError(422, "bad_image", str(error)) from error
    assert result.receipt.id is not None
    return _out(view_receipt(session, household, result.receipt.id))


@router.get("/receipts/{receipt_id}", response_model=ReceiptOut)
def get_receipt(receipt_id: int, session: SessionDep, household: HouseholdDep) -> ReceiptOut:
    try:
        return _out(view_receipt(session, household, receipt_id))
    except ReceiptNotFound as error:
        raise APIError(404, "not_found", str(error)) from error


@router.get("/receipts/{receipt_id}/image")
def get_receipt_image(
    receipt_id: int, session: SessionDep, household: HouseholdDep
) -> FileResponse:
    """The original photo, from this server's disk."""
    try:
        path = image_file(session, household, receipt_id)
    except ReceiptNotFound as error:
        raise APIError(404, "not_found", str(error)) from error
    if path is None:
        raise APIError(404, "not_found", "this receipt has no stored photo")
    return FileResponse(path)


class DecisionIn(BaseModel):
    line_id: int
    product_id: int | None = Field(
        default=None, description="the product the person chose (or accepted) for this line"
    )
    ignore: bool = False
    amount: Decimal | None = Field(default=None, gt=0, description="overrides the proposed amount")
    unit: Unit | None = None


class ConfirmIn(BaseModel):
    lines: list[DecisionIn] = Field(
        description="only the lines named here with a product are applied; the rest are ignored"
    )


class AppliedOut(BaseModel):
    line_id: int
    product_id: int
    name: str
    amount: Decimal
    unit: str
    price_cents: int | None
    notes: list[str]


class ConfirmOut(BaseModel):
    applied: list[AppliedOut]
    ignored: int


@router.post("/receipts/{receipt_id}/confirm", response_model=ConfirmOut)
def confirm(
    receipt_id: int, body: ConfirmIn, session: SessionDep, household: HouseholdDep
) -> ConfirmOut:
    """Add the confirmed lines to the pantry and save their prices (source=receipt)."""
    decisions = [Decision(d.line_id, d.product_id, d.ignore, d.amount, d.unit) for d in body.lines]
    try:
        applied = confirm_receipt(session, household, receipt_id, decisions)
        total = len(view_receipt(session, household, receipt_id).lines)
    except ReceiptNotFound as error:
        raise APIError(404, "not_found", str(error)) from error
    except ReceiptClosed as error:
        raise APIError(409, "receipt_closed", str(error)) from error
    except NeedsAmount as error:
        raise APIError(
            422,
            "amount_required",
            "these lines have no known amount: say how much was bought",
            details=error.line_ids,
        ) from error
    return ConfirmOut(
        applied=[AppliedOut(**{**a.__dict__, "notes": list(a.notes)}) for a in applied],
        ignored=total - len(applied),
    )


@router.post("/receipts/{receipt_id}/discard", status_code=204)
def discard(receipt_id: int, session: SessionDep, household: HouseholdDep) -> None:
    """Throw the scan away: nothing is applied and the photo is deleted."""
    try:
        discard_receipt(session, household, receipt_id)
    except ReceiptNotFound as error:
        raise APIError(404, "not_found", str(error)) from error
    except ReceiptClosed as error:
        raise APIError(409, "receipt_closed", str(error)) from error
