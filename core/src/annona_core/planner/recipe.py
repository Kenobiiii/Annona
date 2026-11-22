# SPDX-License-Identifier: AGPL-3.0-or-later
"""The recipe of a planned meal: the LLM writes the steps, the code does everything else.

The model receives the meal's ingredients (already portioned by code) and writes cooking steps
that refer to them as ``{p12}`` placeholders, so it never writes a quantity. The code then:

* validates the steps (only the meal's ingredients, only appliances in the kitchen, no quantities
  written by the model) and asks for ONE repair with the exact problems;
* fills the placeholders with the household's amounts;
* adapts what depends on the hob using the user's calibration: the time to bring a liquid to the
  boil is proportional to its volume (``boil_ml``) and the calibration measure for 1 L, and each
  heat word maps to a dial level (a configurable estimate, see :class:`RecipeSettings`).

The time food needs to cook is never rescaled: only the hob-dependent part is adapted.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

from annona_core.domain import Appliance, Equipment, HeatLevel, RecipeStep
from annona_core.llm import CallStats, LLMClient, LLMRequest, Message, Tier

from .verify import _OVEN_WORDS, Issue, available_appliances

TASK = "recipe_of_the_day"
LANGUAGES = {"es": "Spanish (Spain)", "en": "English"}
_PLACEHOLDER = re.compile(r"\{p(\d+)\}")
_QUANTITY = re.compile(r"\b\d+([.,]\d+)?\s?(g|gr|kg|ml|cl|l|litros?|gramos?)\b", re.IGNORECASE)
# Words that are never a "foreign ingredient": free items, packaging and descriptors.
_FREE_WORDS = frozenset(
    [
        "agua",
        "sal",
        "pimienta",
        "especias",
        "especia",
        "hierbas",
        "aceite",
        "natural",
        "entera",
        "entero",
        "fresco",
        "fresca",
        "hacendado",
        "desnatado",
        "desnatada",
        "semidesnatado",
        "semidesnatada",
        "integral",
        "grande",
        "pequeno",
        "pequena",
        "water",
        "salt",
        "pepper",
        "spices",
        "herbs",
        "para",
        "como",
        "hasta",
        "entre",
        "desde",
        "sobre",
        "cocinar",
        "cocido",
        "cocida",
        "frito",
        "frita",
        "tipo",
        "estilo",
        "sabor",
        "with",
        "from",
        "until",
    ]
)


class RecipeSettings(BaseModel):
    """Estimates, not measurements: dial positions are not linear in power and every hob differs.

    ``dial_fraction``: which part of the dial each heat word means when the user knows how many
    levels the dial has. Project defaults, configurable.
    """

    model_config = ConfigDict(frozen=True)

    dial_fraction: dict[HeatLevel, Decimal] = Field(
        default_factory=lambda: {
            HeatLevel.LOW: Decimal("0.25"),
            HeatLevel.MEDIUM: Decimal("0.5"),
            HeatLevel.HIGH: Decimal("0.8"),
        }
    )


# ---------------------------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------------------------


class RecipeStepDraft(BaseModel):
    text: str = Field(min_length=2, max_length=400)
    heat: HeatLevel = HeatLevel.NONE
    minutes: int | None = Field(default=None, ge=0, le=300)
    boil_ml: int | None = Field(default=None, ge=50, le=10000)
    appliance: Appliance = Appliance.NONE


class RecipeDraft(BaseModel):
    steps: list[RecipeStepDraft] = Field(min_length=1, max_length=12)


# ---------------------------------------------------------------------------------------------
# Context (built by the server from the database; no I/O here)
# ---------------------------------------------------------------------------------------------


class MealIngredient(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: int
    name: str
    amount: Decimal  # the household's total for this meal
    unit: str  # "g", "ml" or "unit"


class RecipeContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    summary: str  # the one-line idea from the weekly plan
    ingredients: tuple[MealIngredient, ...]
    eaters: tuple[str, ...]
    equipment: Equipment | None
    other_foods: tuple[str, ...] = ()  # names of products NOT in this meal (catalogue)
    language: str = "es"


# ---------------------------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------------------------

SYSTEM = """You write the cooking steps of one home meal.

Rules:
- Use ONLY the listed ingredients. Water, salt, pepper and dried spices are free; nothing else.
- Refer to every ingredient as {pID} (for example {p12}) exactly where it is used. The app replaces
  the placeholder with the name and the amount. NEVER write quantities (grams, ml, ...) yourself.
- Every listed ingredient must appear in at least one step.
- 3 to 8 short steps: preparation (wash, cut) and cooking, in order.
- For each step set: appliance (hob, oven, microwave, air_fryer or none), heat (low, medium, high
  or none; never hob power numbers) and minutes (how long the step takes; 0 or omit if instant).
- Use only the kitchen appliances listed. If there is no oven, never bake, roast or gratinate.
- To bring water or another liquid to the boil on the hob, set boil_ml (millilitres) and appliance
  hob; the app computes that time itself.
- Do not rescale the dish: the amounts are already right for the people eating."""


def build_recipe_prompt(ctx: RecipeContext) -> tuple[str, str]:
    language = LANGUAGES.get(ctx.language, ctx.language)
    system = f"{SYSTEM}\n- Write the steps in {language}."
    tools = sorted(t.value for t in available_appliances(ctx.equipment) if t.value != "none")
    lines = [
        f"Meal: {ctx.title}",
        f"Idea: {ctx.summary}",
        f"Eaten by: {', '.join(ctx.eaters)}",
        f"Kitchen appliances: {', '.join(tools) or 'none (no cooking)'}",
        "Ingredients (id | name | total amount for everyone):",
    ]
    for i in ctx.ingredients:
        lines.append(f"{i.product_id} | {i.name} | {_amount(i.amount, i.unit)}")
    return system, "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _stem(word: str) -> str:
    return word[:-2] if word.endswith("es") and len(word) > 5 else word.rstrip("s")


def _tokens(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]{4,}", _plain(text))}


def validate_recipe(draft: RecipeDraft, ctx: RecipeContext) -> list[Issue]:
    issues: list[Issue] = []
    known = {i.product_id for i in ctx.ingredients}
    tools = available_appliances(ctx.equipment)
    used: set[int] = set()
    mine = set().union(*(_tokens(i.name) for i in ctx.ingredients)) | {
        _stem(w) for w in _FREE_WORDS
    }
    foreign = (
        set().union(*(_tokens(n) for n in ctx.other_foods)) - mine if ctx.other_foods else set()
    )

    for n, step in enumerate(draft.steps, start=1):
        where = f"step {n}"
        ids = {int(m) for m in _PLACEHOLDER.findall(step.text)}
        used |= ids
        for pid in sorted(ids - known):
            issues.append(
                Issue(code="unknown_ingredient", message=f"{where} uses {{p{pid}}}, not listed")
            )
        if "{" in _PLACEHOLDER.sub("", step.text) or "}" in _PLACEHOLDER.sub("", step.text):
            issues.append(Issue(code="bad_placeholder", message=f"{where} has a broken {{pID}}"))
        if _QUANTITY.search(step.text):
            issues.append(
                Issue(
                    code="quantity_in_text",
                    message=f"{where} writes a quantity; use the {{pID}} placeholder instead",
                )
            )
        if step.appliance not in tools:
            issues.append(
                Issue(
                    code="appliance",
                    message=f"{where} uses {step.appliance}, which is not in the kitchen",
                )
            )
        if Appliance.OVEN not in tools and _OVEN_WORDS.search(step.text):
            issues.append(
                Issue(code="appliance", message=f"{where} mentions an oven; there is none")
            )
        if step.boil_ml is not None and step.appliance != Appliance.HOB:
            issues.append(
                Issue(code="boil_needs_hob", message=f"{where} sets boil_ml: use appliance hob")
            )
        text_tokens = _tokens(_PLACEHOLDER.sub(" ", step.text))
        for word in sorted(text_tokens & foreign):
            issues.append(
                Issue(
                    code="foreign_food",
                    message=f"{where} mentions '{word}', which is not an ingredient of this meal",
                )
            )
    for pid in sorted(known - used):
        name = next(i.name for i in ctx.ingredients if i.product_id == pid)
        issues.append(
            Issue(
                code="ingredient_unused",
                message=f"{{p{pid}}} ({name}) is not used in any step: add it where it belongs",
            )
        )
    return issues


# ---------------------------------------------------------------------------------------------
# Generation (one call + at most one repair)
# ---------------------------------------------------------------------------------------------

REPAIR = (
    "The recipe has these problems:\n{issues}\n"
    "Return the complete corrected recipe, fixing every problem."
)


@dataclass
class RecipeOutcome:
    accepted: bool
    draft: RecipeDraft
    issues: list[Issue]
    repaired: bool
    calls: list[CallStats] = field(default_factory=list)


def generate_recipe(
    llm: LLMClient, ctx: RecipeContext, *, task: str = TASK, use_cache: bool = True
) -> RecipeOutcome:
    system, user = build_recipe_prompt(ctx)
    request = LLMRequest(
        tier=Tier.LARGE,
        task=task,
        system=system,
        messages=(Message("user", user),),
        max_tokens=1500,
    )
    first_stats = CallStats()
    draft = llm.complete_json(request, RecipeDraft, use_cache=use_cache, stats=first_stats)
    issues = validate_recipe(draft, ctx)
    if not issues:
        return RecipeOutcome(True, draft, [], False, [first_stats])
    repair = LLMRequest(
        tier=Tier.LARGE,
        task=task,
        system=system,
        messages=(
            Message("user", user),
            Message("assistant", draft.model_dump_json()),
            Message("user", REPAIR.format(issues="\n".join(f"- {i.message}" for i in issues))),
        ),
        max_tokens=1500,
    )
    second_stats = CallStats()
    fixed = llm.complete_json(repair, RecipeDraft, use_cache=use_cache, stats=second_stats)
    remaining = validate_recipe(fixed, ctx)
    return RecipeOutcome(not remaining, fixed, remaining, True, [first_stats, second_stats])


def to_method(draft: RecipeDraft) -> list[RecipeStep]:
    """The stored form. Heat only means something when an appliance is used."""
    steps = []
    for s in draft.steps:
        heat = s.heat if s.appliance != Appliance.NONE else HeatLevel.NONE
        steps.append(
            RecipeStep(
                text=s.text,
                heat=heat,
                minutes=s.minutes,
                boil_ml=s.boil_ml,
                appliance=s.appliance,
            )
        )
    return steps


# ---------------------------------------------------------------------------------------------
# Rendering: amounts and hob-dependent times
# ---------------------------------------------------------------------------------------------


def _amount(value: Decimal, unit: str) -> str:
    if unit == "unit":
        return f"{value.quantize(Decimal(1), rounding=ROUND_HALF_UP)} ud"
    step = Decimal(5) if value >= 50 else Decimal(1)
    rounded = (value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
    if unit == "ml" and rounded >= 1000:
        litres = (rounded / 1000).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return f"{litres.normalize():f} l".replace(".", ",")
    if unit == "g" and rounded >= 1000:
        kilos = (rounded / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{kilos.normalize():f} kg".replace(".", ",")
    return f"{rounded.normalize():f} {unit}"


class RenderedStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    appliance: Appliance
    heat: HeatLevel
    dial_level: int | None  # on the user's dial, when known (an estimate)
    minutes: int | None
    minutes_estimated: bool  # True = the model's guess; False = from the calibration


class RenderedRecipe(BaseModel):
    model_config = ConfigDict(frozen=True)

    steps: tuple[RenderedStep, ...]
    total_minutes: int
    calibrated: bool  # the boil times came from the user's measurement


def render_recipe(
    method: list[RecipeStep],
    ingredients: tuple[MealIngredient, ...],
    equipment: Equipment | None,
    settings: RecipeSettings | None = None,
) -> RenderedRecipe:
    settings = settings or RecipeSettings()
    by_id = {i.product_id: i for i in ingredients}
    calibration = (
        equipment.calibration_boil_1l_minutes
        if equipment and equipment.calibration_level is not None
        else None
    )

    def fill(match: re.Match[str]) -> str:
        item = by_id.get(int(match.group(1)))
        return f"{item.name.lower()} ({_amount(item.amount, item.unit)})" if item else "?"

    steps: list[RenderedStep] = []
    for s in method:
        minutes, estimated = s.minutes, True
        level: int | None = None
        if s.appliance == Appliance.HOB and equipment is not None:
            if s.boil_ml is not None and calibration is not None:
                minutes = max(1, math.ceil(calibration * Decimal(s.boil_ml) / 1000))
                estimated = False
                level = equipment.calibration_level
            elif equipment.power_levels and s.heat in settings.dial_fraction:
                fraction = settings.dial_fraction[s.heat]
                level = max(1, int((fraction * equipment.power_levels).to_integral_value()))
        steps.append(
            RenderedStep(
                text=_PLACEHOLDER.sub(fill, s.text),
                appliance=s.appliance,
                heat=s.heat,
                dial_level=level,
                minutes=minutes,
                minutes_estimated=estimated if minutes is not None else False,
            )
        )
    total = sum(s.minutes or 0 for s in steps)
    return RenderedRecipe(
        steps=tuple(steps), total_minutes=total, calibrated=calibration is not None
    )
