# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn the model's text into numbers and check them. Pure code: LLM arithmetic is never trusted.

Checks that do not depend on the model being right about anything:

* a line with a quantity and a unit price must satisfy ``quantity x unit price = total``;
* the lines must add up to the printed receipt total (discounts included).

A failed check is reported, never silently "fixed".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from annona_core.domain import Unit
from annona_core.domain.units import Quantity, UnitConversionError

from .draft import ReceiptDraft

_NUMBER = re.compile(r"-?\d[\d.,]*")
_CENT = Decimal("0.01")


def parse_decimal(text: str | None) -> Decimal | None:
    """ "1,15" -> 1.15; "1.234,56" -> 1234.56; "1,234.56" -> 1234.56; "3" -> 3; junk -> None."""
    if not text:
        return None
    match = _NUMBER.search(text.replace(" ", " ").replace("−", "-"))
    if not match:
        return None
    raw = match.group(0)
    sign = -1 if raw.startswith("-") else 1
    digits = raw.lstrip("-").rstrip(".,")
    if "," in digits and "." in digits:
        decimal_sep = "," if digits.rfind(",") > digits.rfind(".") else "."
        thousands = "." if decimal_sep == "," else ","
        digits = digits.replace(thousands, "").replace(decimal_sep, ".")
    elif "," in digits or "." in digits:
        sep = "," if "," in digits else "."
        head, _, tail = digits.rpartition(sep)
        # A lone separator is the decimal mark ("1,15", "0,550", also "1.234"): receipts print
        # prices with 2 decimals and weights with 3, and thousands separators only next to a
        # decimal mark ("1.234,56"), which the branch above handles.
        digits = f"{head.replace(sep, '')}.{tail}"
    try:
        return sign * Decimal(digits)
    except InvalidOperation:
        return None


def parse_cents(text: str | None) -> int | None:
    value = parse_decimal(text)
    return (
        None if value is None else int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    )


def parse_weight(text: str | None) -> Quantity | None:
    """ "0,550 kg" -> 550 g; "250 g" -> 250 g; "1,5 l" -> 1500 ml; no unit -> None."""
    if not text or re.search(r"eur|€|/", text.lower()):
        return None  # "7,70 EUR/kg" is a price per kilo, not a weight
    value = parse_decimal(text)
    unit = re.search(r"(kg|g|gr|l|lt|ml|cl)\b", text.lower())
    if value is None or value <= 0 or unit is None:
        return None
    try:
        return Quantity.parse(value, {"gr": "g", "lt": "l"}.get(unit.group(1), unit.group(1)))
    except UnitConversionError:
        return None


_DATE = re.compile(r"(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{2,4})")


def parse_date(text: str | None) -> date | None:
    """ "12/11/2026", "12-11-26", "2026-11-12" (day first, as in Spain). Invalid -> None."""
    if not text:
        return None
    match = _DATE.search(text)
    if not match:
        return None
    a, b, c = (int(x) for x in match.groups())
    day, month, year = (c, b, a) if len(match.group(1)) == 4 else (a, b, c)
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


@dataclass(frozen=True)
class ParsedLine:
    raw_text: str
    total_cents: int  # may be negative only for discounts (not in ``lines``)
    quantity: Decimal | None  # units, if printed
    weight: Quantity | None  # if printed
    unit_price_cents: int | None
    issues: tuple[str, ...] = ()
    search_name: str | None = None  # AI's plain-words reading, only for searching a shop


@dataclass
class ParsedReceipt:
    store: str | None
    purchased_on: date | None
    total_cents: int | None  # as printed
    lines: list[ParsedLine]  # purchased items
    discounts_cents: int = 0  # sum of negative lines (<= 0)
    postal_code: str | None = None  # the shop's, as printed (shape checked by code)
    skipped: list[str] = field(default_factory=list)  # lines without a readable amount
    issues: list[str] = field(default_factory=list)

    @property
    def lines_total_cents(self) -> int:
        return sum(line.total_cents for line in self.lines) + self.discounts_cents

    @property
    def total_matches(self) -> bool | None:
        """Do the lines add up to the printed total? ``None`` when no total was read."""
        return None if self.total_cents is None else self.lines_total_cents == self.total_cents


def _compact(text: str) -> str:
    return re.sub(r"[\s.]", "", text.lower().replace("gr", "g"))


def _purchased_weight(
    weight_text: str | None, raw: str, unit_price: int | None, total: int
) -> tuple[Quantity | None, str | None]:
    """The weight that was *bought*, or None, plus the reason a printed weight was refused.

    Models tend to copy pack sizes out of the product name ("COPOS AVENA 800G", "LECHE 6X1L") into
    the weight field. That is not what was bought and would put the wrong amount in the pantry, so
    a weight is accepted only if it does not appear in the product name and, when a price per
    kg/l is printed, if weight x price agrees with the line total.
    """
    weight = parse_weight(weight_text)
    if weight is None:
        return None, None
    priced = unit_price is not None and weight.unit in (Unit.G, Unit.ML)
    if priced:
        expected = Decimal(unit_price) * weight.amount / 1000
        if abs(expected - Decimal(total)) <= 2:
            return weight, None  # weight x price per kg = the line total: surely what was bought
    if _compact(weight_text or "") in _compact(raw):
        return None, "weight_is_pack_size"
    if priced:
        return None, "weight_math"
    return weight, None


def parse_postal_code(text: str | None) -> str | None:
    """A postal code as printed, if it looks like one (3-10 letters/digits, at least 2 digits)."""
    code = " ".join((text or "").upper().split())
    if (
        re.fullmatch(r"[0-9A-Z][0-9A-Z -]{1,8}[0-9A-Z]", code)
        and sum(c.isdigit() for c in code) >= 2
    ):
        return code
    return None


def _search_name(text: str | None, raw: str) -> str | None:
    name = " ".join((text or "").split())[:80].strip()
    return name if name and name.casefold() != raw.casefold() else None


def parse_receipt(draft: ReceiptDraft) -> ParsedReceipt:
    result = ParsedReceipt(
        store=(draft.store or "").strip() or None,
        purchased_on=parse_date(draft.date),
        total_cents=parse_cents(draft.total),
        lines=[],
        postal_code=parse_postal_code(draft.postal_code),
    )
    for item in draft.lines:
        raw = " ".join(item.raw_text.split())
        total = parse_cents(item.total)
        quantity = parse_decimal(item.quantity)
        quantity = quantity if quantity is not None and quantity > 0 else None
        unit_price = parse_cents(item.unit_price)
        issues: list[str] = []
        if total is None and unit_price is not None and not parse_weight(item.weight):
            # A line printing a single price: that price is the amount (times the quantity).
            total = int(Decimal(unit_price) * (quantity or 1))
            issues.append("total_from_unit_price")
        if not raw or total is None:
            result.skipped.append(raw or "(empty line)")
            continue
        if total < 0:
            result.discounts_cents += total
            continue
        weight, refused = _purchased_weight(item.weight, raw, unit_price, total)
        if refused:
            issues.append(refused)
        line_math_fails = (
            quantity is not None
            and unit_price is not None
            and weight is None
            and abs(quantity * unit_price - total) > 1
        )
        if line_math_fails:
            issues.append("line_math")  # quantity x unit price does not give the total
        result.lines.append(
            ParsedLine(
                raw_text=raw,
                total_cents=total,
                quantity=quantity,
                weight=weight,
                unit_price_cents=unit_price,
                issues=tuple(issues),
                search_name=_search_name(item.search_name, raw),
            )
        )
    if result.total_matches is False:
        diff = result.lines_total_cents - (result.total_cents or 0)
        result.issues.append(f"total_mismatch:{diff}")
    if result.total_cents is None:
        result.issues.append("total_unreadable")
    return result


__all__ = [
    "ParsedLine",
    "ParsedReceipt",
    "Unit",
    "parse_cents",
    "parse_date",
    "parse_decimal",
    "parse_postal_code",
    "parse_receipt",
    "parse_weight",
]
