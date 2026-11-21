# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prompt for the weekly planner: only the context the model needs (CLAUDE.md, cost-conscious).

Instructions are in English; the output language is a parameter so more languages can be added
by extending :data:`LANGUAGES`.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from annona_core.domain import Allergen

from .verify import PlanContext, available_appliances

LANGUAGES = {"es": "Spanish (Spain)", "en": "English"}

SYSTEM = """You are a home cook and dietitian planning a week of practical home meals.

Rules:
- Use ONLY the listed products, referenced by their id. Do not invent ingredients (water, salt and
  common spices are free and need no id).
- Plan exactly one meal for each scheduled day and slot, nothing else.
- Respect the kitchen: use only the listed appliances. If there is no oven, never bake, roast or
  gratinate.
- Respect people: if a product is marked "not for" someone, either avoid it in meals they eat or
  list them in skipped_by for that meal.
- Ingredient amounts are PER PERSON for one serving, in the product's unit (g or ml). Use realistic
  portions; the app rescales them to each person's calorie needs, so do not do calorie arithmetic.
- Try to use the "planned" amounts of each product over the week and never more than "available".
- Make it varied, simple and appetising: typical home cooking, leftovers can be reused across
  days, breakfasts and snacks can repeat with small changes.
- weekday: 0 = Monday ... 6 = Sunday. slot: breakfast, lunch, snack (afternoon), dinner.
- summary: one or two short sentences on how to prepare it, using low/medium/high heat (no hob
  power numbers)."""

_SLOT_NAMES = {"breakfast": "breakfast", "lunch": "lunch", "snack": "snack", "dinner": "dinner"}


def _n(value: Decimal) -> str:
    return str(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def build_prompt(ctx: PlanContext) -> tuple[str, str]:
    language = LANGUAGES.get(ctx.language, ctx.language)
    system = f"{SYSTEM}\n- Write titles and summaries in {language}."

    lines = ["Schedule:"]
    for day in ctx.schedule.days:
        slots = ", ".join(_SLOT_NAMES[s] for s in ctx.schedule.slots_on(day))
        lines.append(f"- weekday {day.weekday()} ({day:%a %d %b}): {slots}")

    lines.append("\nPeople (daily needs):")
    for m in ctx.members:
        p = m.profile
        allergies = ", ".join(Allergen(a).value for a in p.allergies) or "none"
        lines.append(
            f"- {p.name}: {m.daily.energy_kcal} kcal, protein {m.daily.protein_g} g, "
            f"diet {p.diet}, allergies {allergies}"
        )

    lines.append(
        "\nApproximate energy per serving (portions are rescaled exactly by the app; aim close to"
        " these so dishes stay realistic):"
    )
    for m in ctx.members:
        per_slot = ", ".join(
            f"{slot} ~{_n(m.daily.energy_kcal * ctx.energy_scale * share)} kcal"
            for slot, share in ctx.schedule.shares.items()
            if any(s.slot == slot for s in ctx.schedule.slots)
        )
        lines.append(f"- {m.profile.name}: {per_slot}")

    tools = sorted(t.value for t in available_appliances(ctx.equipment) if t.value != "none")
    lines.append(f"\nKitchen appliances: {', '.join(tools) or 'none (no cooking)'}")

    lines.append(
        "\nProducts (id | name | unit | available | planned | kcal/100 | protein/100 | not for):"
    )
    for a in ctx.available:
        not_for = ", ".join(a.not_for) or "-"
        lines.append(
            f"{a.product.id} | {a.product.name} | {a.basis} | {_n(a.available)} | {_n(a.intended)}"
            f" | {_n(a.kcal * 100)} | {_n(a.protein * 100)} | {not_for}"
        )
    return system, "\n".join(lines)
