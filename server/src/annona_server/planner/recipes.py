# SPDX-License-Identifier: AGPL-3.0-or-later
"""The recipe of a planned meal and "mark as cooked": database side of ``planner.recipe``.

Generated once per meal and stored (``Recipe.method``); reused until the kitchen changes in a way
that makes it invalid, or until the user asks for a new one. Marking a meal as cooked deducts what
it used from the pantry, after the user has seen exactly what would change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlmodel import Session

from annona_core.domain import (
    Appliance,
    Equipment,
    MealSlot,
    PantryItem,
    PlannedMeal,
    Product,
    Recipe,
    RecipeIngredient,
    Unit,
)
from annona_core.domain.models import utc_now
from annona_core.domain.units import Quantity, UnitConversionError
from annona_core.llm import LLMClient
from annona_core.planner import (
    MealIngredient,
    RecipeContext,
    RecipeDraft,
    RenderedRecipe,
    generate_recipe,
    render_recipe,
    to_method,
    validate_recipe,
)
from annona_core.planner.recipe import RecipeStepDraft

from ..db.repositories import (
    EquipmentRepository,
    PlannedMealRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    SqlPantryRepository,
    SqlProductRepository,
    UserProfileRepository,
)
from . import existing_plan, language

_THOUSANDTH = Decimal("0.001")


class MealNotFound(LookupError):
    """No planned meal for that day and slot."""


class AlreadyCooked(Exception):
    """The meal was already marked as cooked (the pantry is never deducted twice)."""


class RecipeRejected(Exception):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


@dataclass
class MealParts:
    recipe: Recipe
    rows: list[PlannedMeal]
    names: dict[int | None, str]
    ingredients: list[RecipeIngredient]
    products: dict[int, Product]
    equipment: Equipment | None

    @property
    def eaters(self) -> list[tuple[str, Decimal]]:
        return [(self.names.get(r.profile_id, "household"), r.servings) for r in self.rows]

    def totals(self) -> tuple[MealIngredient, ...]:
        """What the household uses in this meal: the reference serving x everyone's servings."""
        servings = sum((r.servings for r in self.rows), Decimal(0))
        return tuple(
            MealIngredient(
                product_id=i.product_id,
                name=self.products[i.product_id].name,
                amount=(i.amount * servings).quantize(_THOUSANDTH, rounding=ROUND_HALF_UP),
                unit=str(i.unit),
            )
            for i in self.ingredients
        )

    def portions(self) -> dict[str, list[MealIngredient]]:
        return {
            self.names.get(r.profile_id, "household"): [
                MealIngredient(
                    product_id=i.product_id,
                    name=self.products[i.product_id].name,
                    amount=(i.amount * r.servings).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
                    unit=str(i.unit),
                )
                for i in self.ingredients
            ]
            for r in self.rows
        }


def load_meal(session: Session, household_id: int, day: date, slot: MealSlot) -> MealParts:
    monday = day - timedelta(days=day.weekday())
    plan = existing_plan(session, household_id, monday)
    if plan is None or plan.id is None:
        raise MealNotFound(f"no plan for the week of {monday}")
    rows = [
        r
        for r in PlannedMealRepository(session).list(plan_id=plan.id)
        if r.day == day and r.slot == slot and r.recipe_id is not None
    ]
    if not rows:
        raise MealNotFound(f"no {slot} planned on {day}")
    recipe = RecipeRepository(session).get(rows[0].recipe_id)  # type: ignore[arg-type]
    if recipe is None or recipe.id is None:
        raise MealNotFound(f"no recipe for {slot} on {day}")
    products = {p.id: p for p in SqlProductRepository(session).list() if p.id is not None}
    return MealParts(
        recipe=recipe,
        rows=rows,
        names={
            p.id: p.name for p in UserProfileRepository(session).list(household_id=household_id)
        },
        ingredients=list(RecipeIngredientRepository(session).list(recipe_id=recipe.id)),
        products=products,
        equipment=next(iter(EquipmentRepository(session).list(household_id=household_id)), None),
    )


def recipe_context(parts: MealParts) -> RecipeContext:
    in_meal = {i.product_id for i in parts.ingredients}
    return RecipeContext(
        title=parts.recipe.title,
        summary=parts.recipe.steps[0] if parts.recipe.steps else parts.recipe.title,
        ingredients=parts.totals(),
        eaters=tuple(name for name, _ in parts.eaters),
        equipment=parts.equipment,
        other_foods=tuple(
            p.name for pid, p in parts.products.items() if p.store_id and pid not in in_meal
        ),
        language=language(),
    )


@dataclass
class DetailedRecipe:
    parts: MealParts
    rendered: RenderedRecipe
    generated: bool  # False = reused from the database
    calls: int = 0
    cooked_at: object = None
    issues: list[str] = field(default_factory=list)


def _as_draft(recipe: Recipe) -> RecipeDraft:
    return RecipeDraft(
        steps=[
            RecipeStepDraft(
                text=s.text,
                heat=s.heat,
                minutes=s.minutes,
                boil_ml=s.boil_ml,
                appliance=s.appliance,
            )
            for s in recipe.method
        ]
    )


def detailed_recipe(
    session: Session,
    llm_factory: Callable[[Session], LLMClient],
    household_id: int,
    day: date,
    slot: MealSlot,
    *,
    regenerate: bool = False,
) -> DetailedRecipe:
    parts = load_meal(session, household_id, day, slot)
    ctx = recipe_context(parts)
    recipe, generated, calls = parts.recipe, False, 0
    # A stored recipe is reused only while it is still valid for the kitchen (e.g. no oven now).
    stale = regenerate or not recipe.method or validate_recipe(_as_draft(recipe), ctx)
    if stale:
        outcome = generate_recipe(llm_factory(session), ctx, use_cache=not regenerate)
        if not outcome.accepted:
            raise RecipeRejected([i.message for i in outcome.issues])
        method = to_method(outcome.draft)
        used = {s.appliance for s in method}
        recipe = RecipeRepository(session).update(
            recipe.model_copy(
                update={
                    "method": method,
                    "needs_oven": Appliance.OVEN in used,
                    "needs_microwave": Appliance.MICROWAVE in used,
                    "needs_air_fryer": Appliance.AIR_FRYER in used,
                }
            )
        )
        generated, calls = True, len(outcome.calls)
    rendered = render_recipe(recipe.method, ctx.ingredients, parts.equipment)
    cooked = [r.cooked_at for r in parts.rows if r.cooked_at is not None]
    return DetailedRecipe(
        parts=parts,
        rendered=rendered,
        generated=generated,
        calls=calls,
        cooked_at=max(cooked) if len(cooked) == len(parts.rows) else None,
    )


# ---------------------------------------------------------------------------------------------
# Marking a meal as cooked
# ---------------------------------------------------------------------------------------------


@dataclass
class CookLine:
    product_id: int
    name: str
    unit: str  # the unit of the amounts below (the recipe's)
    needed: Decimal
    in_pantry: Decimal
    deduct: Decimal
    note: str | None = None  # why something is missing ("not in the pantry", "unit")

    @property
    def missing(self) -> Decimal:
        return max(self.needed - self.deduct, Decimal(0))


@dataclass
class CookPreview:
    lines: list[CookLine]
    already_cooked: bool


def _items(session: Session, household_id: int, product_id: int) -> list[PantryItem]:
    items = [
        i
        for i in SqlPantryRepository(session).for_household(household_id)
        if i.product_id == product_id
    ]
    # Use what expires first, then the oldest.
    return sorted(items, key=lambda i: (i.expires_at is None, i.expires_at or date.max, i.added_at))


def _in_basis(item: PantryItem, unit: Unit, product: Product) -> Decimal | None:
    try:
        return (
            Quantity(amount=item.amount, unit=item.unit)
            .to(
                unit,
                density_g_per_ml=product.density_g_per_ml,
                unit_weight_g=product.unit_weight_g,
            )
            .amount
        )
    except UnitConversionError:
        return None


def cook_preview(session: Session, household_id: int, day: date, slot: MealSlot) -> CookPreview:
    parts = load_meal(session, household_id, day, slot)
    lines = []
    for need in parts.totals():
        product = parts.products[need.product_id]
        unit = Unit(need.unit)
        have, skipped = Decimal(0), False
        for item in _items(session, household_id, need.product_id):
            basis = _in_basis(item, unit, product)
            if basis is None:
                skipped = True
            else:
                have += basis
        deduct = min(need.amount, have)
        note = None
        if have == 0:
            note = "unit_unknown" if skipped else "not_in_pantry"
        elif deduct < need.amount:
            note = "not_enough"
        lines.append(
            CookLine(
                product_id=need.product_id,
                name=need.name,
                unit=need.unit,
                needed=need.amount,
                in_pantry=have.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP),
                deduct=deduct.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP),
                note=note,
            )
        )
    return CookPreview(lines=lines, already_cooked=any(r.cooked_at is not None for r in parts.rows))


def cook(
    session: Session,
    household_id: int,
    day: date,
    slot: MealSlot,
    *,
    skip_products: frozenset[int] = frozenset(),
) -> CookPreview:
    """Deduct the previewed amounts (except the skipped products) and mark the meal as cooked."""
    parts = load_meal(session, household_id, day, slot)
    if any(r.cooked_at is not None for r in parts.rows):
        raise AlreadyCooked(f"{slot} on {day} was already marked as cooked")
    preview = cook_preview(session, household_id, day, slot)
    pantry = SqlPantryRepository(session)
    for line in preview.lines:
        if line.product_id in skip_products or line.deduct <= 0:
            continue
        product, unit = parts.products[line.product_id], Unit(line.unit)
        remaining = line.deduct
        for item in _items(session, household_id, line.product_id):
            basis = _in_basis(item, unit, product)
            if basis is None or remaining <= 0 or item.id is None:
                continue
            used = min(remaining, basis)
            left = basis - used
            remaining -= used
            if left <= 0:
                pantry.delete(item.id)
                continue
            back = (
                Quantity(amount=left, unit=unit)
                .to(
                    item.unit,
                    density_g_per_ml=product.density_g_per_ml,
                    unit_weight_g=product.unit_weight_g,
                )
                .amount
            )
            pantry.update(
                item.model_copy(
                    update={"amount": back.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP)}
                )
            )
    now = utc_now()
    meals = PlannedMealRepository(session)
    for row in parts.rows:
        meals.update(row.model_copy(update={"cooked_at": now}))
    return CookPreview(
        lines=[ln for ln in preview.lines if ln.product_id not in skip_products],
        already_cooked=True,
    )
