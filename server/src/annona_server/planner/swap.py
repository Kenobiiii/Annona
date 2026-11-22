# SPDX-License-Identifier: AGPL-3.0-or-later
"""Replace ONE planned meal with another dish, using only what the week's shopping left over.

The proposal is made with the same pipeline as a whole week (the model drafts, the code scales and
verifies: appliances, allergies, energy, stock) on a one-slot schedule. Nothing changes until the
proposal is applied, and the proposal can only use products already bought, so the shopping list and
the budget stay as they are. If that is not possible the answer is "not possible", never a
silent purchase.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlmodel import Session

from annona_core.domain import (
    Appliance,
    Household,
    MealSlot,
    Recipe,
    RecipeIngredient,
    RecipeSource,
    Unit,
)
from annona_core.llm import LLMClient
from annona_core.nutrition import check_product, daily_targets
from annona_core.planner import (
    Available,
    MealSchedule,
    Member,
    PlanContext,
    plan_week,
)
from annona_core.planner.schedule import SLOT_ORDER

from ..db.repositories import (
    PlannedMealRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    ShoppingItemRepository,
    ShoppingListRepository,
    SqlPantryRepository,
    UserProfileRepository,
)
from ..shopping import _to_basis
from .recipes import MealParts, load_meal

MIN_LEFTOVER = Decimal(30)  # g or ml: less than this is not worth planning around
TASK = "swap_meal"


class SwapError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class ProposalIngredient(BaseModel):
    product_id: int
    name: str
    amount: Decimal  # one reference serving
    unit: str


class ProposalMember(BaseModel):
    profile_id: int | None
    name: str
    servings: Decimal


class SwapProposal(BaseModel):
    """Everything needed to apply the swap later. Serialisable: it is stored with the action."""

    day: date
    slot: MealSlot
    old_recipe_id: int
    old_title: str
    title: str
    summary: str
    appliances: list[str] = Field(default_factory=list)
    ingredients: list[ProposalIngredient]
    members: list[ProposalMember]
    portions: dict[str, list[ProposalIngredient]] = Field(default_factory=dict)  # for display


def _leftover(session: Session, household: Household, parts: MealParts) -> dict[int, Decimal]:
    """What the week's shopping leaves for this meal: bought + pantry - used by the other meals."""
    plan_id = parts.rows[0].plan_id
    lists = [
        lst for lst in ShoppingListRepository(session).list(plan_id=plan_id) if lst.id is not None
    ]
    stock: dict[int, Decimal] = {}
    if lists:  # the list made with the plan (the first one)
        first = min(lists, key=lambda lst: lst.id or 0)
        for item in ShoppingItemRepository(session).list(list_id=first.id):
            product = parts.products.get(item.product_id)
            if product is None or product.nutrition is None or product.package_amount is None:
                continue
            basis = Unit(str(product.nutrition.basis))
            pack = _to_basis(
                product.package_amount, Unit(str(product.package_unit)), basis, product
            )
            if pack is not None:
                stock[item.product_id] = stock.get(item.product_id, Decimal(0)) + pack * item.packs
    for item in SqlPantryRepository(session).for_household(household.id):
        product = parts.products.get(item.product_id)
        if product is None or product.nutrition is None or item.product_id in stock:
            continue  # on the list: the list already covers it (ticking copies it to the pantry)
        converted = _to_basis(item.amount, item.unit, Unit(str(product.nutrition.basis)), product)
        if converted is not None:
            stock[item.product_id] = stock.get(item.product_id, Decimal(0)) + converted

    ingredients = RecipeIngredientRepository(session)
    here = (parts.rows[0].day, parts.rows[0].slot)
    cache: dict[int, list[RecipeIngredient]] = {}
    for row in PlannedMealRepository(session).list(plan_id=plan_id):
        if row.recipe_id is None or (row.day, row.slot) == here:
            continue
        if row.recipe_id not in cache:
            cache[row.recipe_id] = list(ingredients.list(recipe_id=row.recipe_id))
        for ing in cache[row.recipe_id]:
            if ing.product_id in stock:
                stock[ing.product_id] -= ing.amount * row.servings
    return {pid: amount for pid, amount in stock.items() if amount >= MIN_LEFTOVER}


def _energy(parts: MealParts, profile_id: int | None) -> Decimal:
    """kcal of the current meal for one member."""
    total = Decimal(0)
    for row in parts.rows:
        if row.profile_id != profile_id:
            continue
        for ing in parts.ingredients:
            n = parts.products[ing.product_id].nutrition
            if n is not None:
                total += ing.amount * row.servings * n.energy_kcal / 100
    return total


def _protein(parts: MealParts, profile_id: int | None) -> Decimal:
    """Grams of protein of the current meal for one member."""
    total = Decimal(0)
    for row in parts.rows:
        if row.profile_id != profile_id:
            continue
        for ing in parts.ingredients:
            n = parts.products[ing.product_id].nutrition
            if n is not None:
                total += ing.amount * row.servings * n.protein_g / 100
    return total


def propose_swap(
    session: Session,
    llm: LLMClient,
    household: Household,
    day: date,
    slot: MealSlot,
    request: str,
    *,
    avoid_appliances: list[str] | None = None,
    language: str = "es",
) -> SwapProposal:
    parts = load_meal(session, household.id, day, slot)
    if any(r.cooked_at is not None for r in parts.rows):
        raise SwapError("already_cooked", "that meal was already cooked: it cannot be replaced")
    leftover = _leftover(session, household, parts)
    if not leftover:
        raise SwapError(
            "no_stock",
            "nothing from the week's shopping is left over for another dish: regenerate the menu",
        )

    eaters_ids = {r.profile_id for r in parts.rows}
    profiles = [
        p
        for p in UserProfileRepository(session).list(household_id=household.id)
        if p.id in eaters_ids or None in eaters_ids
    ]
    if not profiles:
        raise SwapError("no_members", "nobody is planned to eat that meal")
    members = tuple(Member(profile=p, daily=daily_targets(p, day)) for p in profiles)

    available = []
    for pid, amount in sorted(leftover.items()):
        product = parts.products[pid]
        n = product.nutrition
        assert n is not None
        not_for = [m.name for m in profiles if not check_product(product, m).allowed]
        not_for += [
            m.name
            for m in profiles
            if product.type and m.food_preferences.get(product.type) == "avoid"
        ]
        if len(set(not_for)) == len(profiles):
            continue  # nobody can eat it
        available.append(
            Available(
                product=product,
                basis=str(n.basis),
                available=amount,
                intended=amount,
                kcal=n.energy_kcal / 100,
                protein=n.protein_g / 100,
                not_for=tuple(sorted(set(not_for))),
            )
        )
    if not available:
        raise SwapError("no_stock", "what is left over cannot be eaten by this household")

    equipment = parts.equipment
    if equipment is not None and avoid_appliances:
        off = {a for a in avoid_appliances if a in ("oven", "microwave", "air_fryer")}
        equipment = equipment.model_copy(update={a: False for a in off})

    monday = day.fromordinal(day.toordinal() - day.weekday())
    schedule = MealSchedule.build(
        monday,
        weekdays=[day.weekday()],
        skip_slots=[s for s in SLOT_ORDER if s != slot],
    )
    first = members[0]
    target = first.daily.energy_kcal * schedule.shares[slot]
    actual = _energy(parts, first.profile.id)
    energy_scale = (
        min(Decimal("1.5"), max(Decimal("0.5"), actual / target))
        if target and actual
        else Decimal(1)
    )
    # The new dish must not lower the protein of the meal it replaces (the week's balance was
    # already planned); it is not asked to reach a whole-week figure on its own.
    daily_protein = first.daily.protein_g * schedule.shares[slot]
    original = _protein(parts, first.profile.id)
    protein_ratio = (
        min(Decimal("0.9"), Decimal("0.9") * original / daily_protein)
        if daily_protein and original
        else Decimal(0)
    )
    ctx = PlanContext(
        schedule=schedule,
        members=members,
        available=tuple(available),
        equipment=equipment,
        language=language,
        energy_scale=energy_scale,
        protein_min_ratio=protein_ratio,
        check_servings=False,
        replacing=parts.recipe.title,
        swap_request=request.strip()[:300],
    )
    outcome = plan_week(llm, ctx, task=TASK)
    if not outcome.accepted or not outcome.verification.meals:
        reasons = "; ".join(i.message for i in outcome.verification.issues[:3])
        raise SwapError("not_possible", f"no valid replacement found ({reasons})")
    final = outcome.verification.meals[0]
    names = {a.product.id: a.product.name for a in available}
    basis = {a.product.id: a.basis for a in available}

    def ingredient(pid: int, amount: Decimal) -> ProposalIngredient:
        return ProposalIngredient(product_id=pid, name=names[pid], amount=amount, unit=basis[pid])

    by_name = {p.name: p for p in profiles}
    return SwapProposal(
        day=day,
        slot=slot,
        old_recipe_id=parts.recipe.id,  # type: ignore[arg-type]
        old_title=parts.recipe.title,
        title=final.draft.title,
        summary=final.draft.summary,
        appliances=[str(a) for a in final.draft.appliances],
        ingredients=[ingredient(pid, amount) for pid, amount in final.base_amounts.items()],
        members=[
            ProposalMember(
                profile_id=by_name[p.member].id,
                name=p.member,
                servings=max(p.scale, Decimal("0.01")),
            )
            for p in final.portions
        ],
        portions={
            p.member: [ingredient(pid, a) for pid, a in p.amounts.items()] for p in final.portions
        },
    )


def apply_swap(session: Session, household: Household, proposal: SwapProposal) -> None:
    """Make the replacement real: a new recipe for that day and slot, same people."""
    parts = load_meal(session, household.id, proposal.day, proposal.slot)
    if parts.recipe.id != proposal.old_recipe_id:
        raise SwapError("stale", "the menu changed since this was proposed")
    if any(r.cooked_at is not None for r in parts.rows):
        raise SwapError("already_cooked", "that meal was already cooked: it cannot be replaced")
    used = {Appliance(a) for a in proposal.appliances}
    recipe = RecipeRepository(session).add(
        Recipe(
            household_id=household.id,
            title=proposal.title,
            servings=1,
            steps=[proposal.summary],
            needs_oven=Appliance.OVEN in used,
            needs_microwave=Appliance.MICROWAVE in used,
            needs_air_fryer=Appliance.AIR_FRYER in used,
            source=RecipeSource.LLM,
        )
    )
    assert recipe.id is not None
    for ing in proposal.ingredients:
        RecipeIngredientRepository(session).add(
            RecipeIngredient(
                recipe_id=recipe.id,
                product_id=ing.product_id,
                amount=max(ing.amount, Decimal("0.1")),
                unit=Unit(ing.unit),
            )
        )
    servings = {m.profile_id: m.servings for m in proposal.members}
    for row in parts.rows:
        PlannedMealRepository(session).update(
            row.model_copy(
                update={
                    "recipe_id": recipe.id,
                    "servings": servings.get(row.profile_id, row.servings),
                }
            )
        )
    RecipeRepository(session).delete(proposal.old_recipe_id)
