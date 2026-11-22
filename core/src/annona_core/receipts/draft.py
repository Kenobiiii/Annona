# SPDX-License-Identifier: AGPL-3.0-or-later
"""The JSON the vision model returns for a receipt photo.

Every value is a string exactly as printed: the model only reads, it never computes. Numbers,
weights and dates are parsed and cross-checked by :mod:`annona_core.receipts.parse`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from annona_core.llm import CallStats, Image, LLMClient, LLMRequest, Message, Tier

TASK = "receipt_scan"


class DraftLine(BaseModel):
    raw_text: str = Field(description="the product name as printed, without prices")
    quantity: str | None = Field(default=None, description="units bought if printed, e.g. '2'")
    weight: str | None = Field(
        default=None, description="weight or volume if printed on this line, e.g. '0,550 kg'"
    )
    unit_price: str | None = Field(default=None, description="price per unit/kg if printed")
    total: str | None = Field(default=None, description="the line amount as printed, e.g. '9,96'")


class ReceiptDraft(BaseModel):
    store: str | None = None
    date: str | None = Field(default=None, description="purchase date as printed")
    total: str | None = Field(default=None, description="the receipt total as printed")
    lines: list[DraftLine] = Field(max_length=120)


SYSTEM = """You read a photo of a supermarket receipt and transcribe it. You only read; you never
calculate, correct or guess.

Rules:
- Return one entry per purchased line, in order, with the product name exactly as printed
  (abbreviations included) and WITHOUT the price or the quantity in it.
- quantity: the number of units if the line prints it (for example the leading "2" in
  "2 LECHE SEMI"), otherwise null.
- weight: ONLY a weight or volume that the receipt prints for this purchase, normally on its own
  line under the product with a price per kg ("0,550 kg   7,70 EUR/kg"). NEVER copy a size that
  is part of the product name ("800G", "6X1L", "1KG", "30"): that is the pack size, not a weight.
  Otherwise null.
- total: the line's final amount, the number in the right-hand column. If the line prints only
  one price, that price is the total (and the unit_price is null).
- unit_price: only if the line prints both a unit price and an amount.
- Copy numbers as text, keeping the decimal comma or point. Discounts are lines with a negative
  total.
- Do NOT include the grand total, payment, tax, change or loyalty lines as products.
- store, date and the grand total of the receipt go in their own fields.
- If a value is not legible, use null. Never invent a value."""


def build_receipt_prompt(language: str = "es") -> tuple[str, str]:
    return SYSTEM, f"Read this receipt. Receipt language: {language}."


def read_receipt(
    llm: LLMClient,
    image: Image,
    *,
    language: str = "es",
    use_cache: bool = True,
    task: str = TASK,
) -> tuple[ReceiptDraft, CallStats]:
    """One vision call (small tier) returning the validated draft."""
    system, user = build_receipt_prompt(language)
    stats = CallStats()
    request = LLMRequest(
        tier=Tier.SMALL,
        task=task,
        system=system,
        messages=(Message("user", user, images=(image,)),),
        max_tokens=3000,
    )
    draft = llm.complete_json(request, ReceiptDraft, use_cache=use_cache, stats=stats)
    return draft, stats
