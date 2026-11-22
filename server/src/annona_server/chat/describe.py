# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a proposed change will do, in words. Written by code from the exact arguments that will be
executed, never by the model: the person confirms what they read here."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlmodel import Session

from annona_core.domain import Household, MealSlot

from ..db.repositories import SqlProductRepository
from ..planner.recipes import MealNotFound, cook_preview
from ..planner.swap import SwapProposal

_SLOTS = {
    "es": {
        "breakfast": "el desayuno",
        "lunch": "la comida",
        "snack": "la merienda",
        "dinner": "la cena",
    },
    "en": {"breakfast": "breakfast", "lunch": "lunch", "snack": "snack", "dinner": "dinner"},
}


def _n(value: Any) -> str:
    return f"{Decimal(str(value)).quantize(Decimal(1))}" if value is not None else "?"


def _say(lang: str, es: str, en: str) -> str:
    return es if lang == "es" else en


def describe_swap(proposal: SwapProposal, lang: str = "es") -> str:
    slot = _SLOTS.get(lang, _SLOTS["en"])[str(proposal.slot)]
    what = ", ".join(f"{i.name} ({_n(i.amount)} {i.unit})" for i in proposal.ingredients)
    return _say(
        lang,
        f"Cambiar {slot} del {proposal.day:%d/%m}: «{proposal.old_title}» por «{proposal.title}» "
        f"con {what}.",
        f"Replace {slot} on {proposal.day:%d/%m}: '{proposal.old_title}' with '{proposal.title}' "
        f"using {what}.",
    )


def describe_write(
    session: Session, household: Household, tool: str, args: dict[str, Any], lang: str = "es"
) -> str:
    products = SqlProductRepository(session)

    def name(pid: int) -> str:
        product = products.get(pid)
        return product.name if product else f"#{pid}"

    if tool == "update_pantry":
        parts = []
        for c in args.get("changes", []):
            amount = f"{_n(c.get('amount'))} {c.get('unit', 'g')}"
            who = name(c["product_id"])
            mode = c.get("mode")
            if mode == "add":
                parts.append(_say(lang, f"añadir {amount} de {who}", f"add {amount} of {who}"))
            elif mode == "set":
                parts.append(_say(lang, f"dejar {who} en {amount}", f"set {who} to {amount}"))
            else:
                parts.append(_say(lang, f"quitar {who}", f"remove {who}"))
        return _say(lang, "Despensa: ", "Pantry: ") + "; ".join(parts)
    if tool == "build_weekly_plan":
        again = args.get("regenerate")
        return _say(
            lang,
            f"Generar el menú de la semana del {args.get('week_start')} en {args.get('store_id')}"
            + (" (sustituye el actual)" if again else ""),
            f"Build the menu for the week of {args.get('week_start')} at {args.get('store_id')}"
            + (" (replaces the current one)" if again else ""),
        )
    if tool == "cook_meal":
        day = args.get("day") or date.today()
        day = date.fromisoformat(day) if isinstance(day, str) else day
        slot = MealSlot(args["slot"])
        label = _SLOTS.get(lang, _SLOTS["en"])[str(slot)]
        try:
            lines = [
                ln
                for ln in cook_preview(session, household.id, day, slot).lines
                if ln.deduct > 0 and ln.product_id not in args.get("skip_products", [])
            ]
        except MealNotFound:
            lines = []
        what = ", ".join(f"{_n(ln.deduct)} {ln.unit} {ln.name}" for ln in lines)
        return _say(
            lang,
            f"Marcar como cocinado {label} del {day:%d/%m}"
            + (
                f" y descontar de la despensa: {what}"
                if what
                else " (no hay nada en la despensa que descontar)"
            ),
            f"Mark {label} on {day:%d/%m} as cooked"
            + (
                f" and deduct from the pantry: {what}"
                if what
                else " (nothing in the pantry to deduct)"
            ),
        )
    return f"{tool} {args}"
