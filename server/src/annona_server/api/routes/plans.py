# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weekly plans: generate (background job), read, today's meals and the plan's shopping list."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Request, status
from pydantic import BaseModel
from sqlmodel import Session

from annona_core.domain import MealPlan, MealSlot, PlanStatus

from ...db.repositories import (
    MealPlanRepository,
    PlannedMealRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    ShoppingItemRepository,
    ShoppingListRepository,
    SqlProductRepository,
    UserProfileRepository,
)
from ...planner import existing_plan
from ...planner.jobs import plan_job
from ..deps import HouseholdDep, SessionDep
from ..errors import APIError
from ..schemas import JobAccepted, ScheduleIn, ShoppingOptions
from .shopping import to_schedule

router = APIRouter(tags=["plans"])

_SLOT_ORDER = {
    s: i
    for i, s in enumerate([MealSlot.BREAKFAST, MealSlot.LUNCH, MealSlot.SNACK, MealSlot.DINNER])
}


class PlanIn(ShoppingOptions):
    schedule: ScheduleIn
    regenerate: bool = False


@router.post("/plans", status_code=status.HTTP_202_ACCEPTED, response_model=JobAccepted)
def generate_plan(
    body: PlanIn, request: Request, session: SessionDep, household: HouseholdDep
) -> JobAccepted:
    """Optimise the shop and draft the week with the AI (25-90 s): poll the returned job."""
    if existing_plan(session, household.id, body.schedule.week_start) and not body.regenerate:
        raise APIError(409, "plan_exists", "this week already has a plan; send regenerate=true")
    to_schedule(body.schedule)  # validate now, not inside the job
    params = body.model_dump(mode="json")
    run = plan_job(request.app.state.llm_factory, household.id)
    job_id = request.app.state.runner.submit("plan_week", params, run)
    return JobAccepted(job_id=job_id, status_url=f"/api/v1/jobs/{job_id}")


class Ingredient(BaseModel):
    product_id: int
    name: str
    amount: Decimal
    unit: str


class MealOut(BaseModel):
    day: date
    slot: MealSlot
    title: str
    steps: list[str]
    needs: list[str]
    portions: dict[str, list[Ingredient]]  # member name -> their ingredients


class PlanOut(BaseModel):
    plan: MealPlan
    meals: list[MealOut]


def _plan_out(
    session: Session, plan: MealPlan, day: date | None = None, profile_id: int | None = None
) -> PlanOut:
    names = {
        p.id: p.name for p in UserProfileRepository(session).list(household_id=plan.household_id)
    }
    products = SqlProductRepository(session)
    recipes = RecipeRepository(session)
    ingredients = RecipeIngredientRepository(session)
    grouped: dict[tuple[date, MealSlot], MealOut] = {}
    for planned in PlannedMealRepository(session).list(plan_id=plan.id):
        if (day and planned.day != day) or (profile_id and planned.profile_id != profile_id):
            continue
        recipe = recipes.get(planned.recipe_id) if planned.recipe_id else None
        if recipe is None:
            continue
        key = (planned.day, planned.slot)
        meal = grouped.setdefault(
            key,
            MealOut(
                day=planned.day,
                slot=planned.slot,
                title=recipe.title,
                steps=recipe.steps,
                needs=[
                    n
                    for n, flag in (
                        ("oven", recipe.needs_oven),
                        ("microwave", recipe.needs_microwave),
                        ("air_fryer", recipe.needs_air_fryer),
                    )
                    if flag
                ],
                portions={},
            ),
        )
        meal.portions[names.get(planned.profile_id, "household")] = [
            Ingredient(
                product_id=ing.product_id,
                name=(products.get(ing.product_id) or type("P", (), {"name": "?"})).name,
                amount=(ing.amount * planned.servings).quantize(Decimal("0.1")),
                unit=str(ing.unit),
            )
            for ing in ingredients.list(recipe_id=recipe.id)
        ]
    meals = sorted(grouped.values(), key=lambda m: (m.day, _SLOT_ORDER[m.slot]))
    return PlanOut(plan=plan, meals=meals)


def _plan(session: Session, household_id: int, plan_id: int) -> MealPlan:
    plan = MealPlanRepository(session).get(plan_id)
    if plan is None or plan.household_id != household_id:
        raise APIError(404, "not_found", f"plan {plan_id} not found")
    return plan


@router.get("/plans", response_model=PlanOut | None)
def plan_for_week(week: date, session: SessionDep, household: HouseholdDep) -> PlanOut | None:
    """The active plan of the week starting on ``week`` (a Monday), or null."""
    plan = existing_plan(session, household.id, week)
    return _plan_out(session, plan) if plan else None


@router.get("/plans/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int, session: SessionDep, household: HouseholdDep) -> PlanOut:
    return _plan_out(session, _plan(session, household.id, plan_id))


@router.get("/today", response_model=list[MealOut])
def today(
    session: SessionDep,
    household: HouseholdDep,
    day: date | None = None,
    profile_id: int | None = None,
) -> list[MealOut]:
    """Meals planned for a day (default today) in the active plan: the base of the home screen."""
    day = day or date.today()
    monday = date.fromordinal(day.toordinal() - day.weekday())
    plan = existing_plan(session, household.id, monday)
    if plan is None or plan.status != PlanStatus.ACTIVE:
        return []
    return _plan_out(session, plan, day=day, profile_id=profile_id).meals


class ShoppingItemOut(BaseModel):
    product_id: int
    name: str
    packs: int
    unit_price_cents: int | None
    checked: bool


class ShoppingListOut(BaseModel):
    store_id: str
    total_cents: int
    items: list[ShoppingItemOut]


@router.get("/plans/{plan_id}/shopping-list", response_model=ShoppingListOut)
def shopping_list(plan_id: int, session: SessionDep, household: HouseholdDep) -> ShoppingListOut:
    _plan(session, household.id, plan_id)
    lists = ShoppingListRepository(session).list(plan_id=plan_id)
    if not lists:
        raise APIError(404, "not_found", f"plan {plan_id} has no shopping list")
    current = lists[-1]
    products = SqlProductRepository(session)
    items = [
        ShoppingItemOut(
            product_id=i.product_id,
            name=getattr(products.get(i.product_id), "name", "?"),
            packs=i.packs,
            unit_price_cents=i.unit_price_cents,
            checked=i.checked,
        )
        for i in ShoppingItemRepository(session).list(list_id=current.id)
    ]
    total = sum(i.packs * (i.unit_price_cents or 0) for i in items)
    return ShoppingListOut(store_id=current.store_id, total_cents=total, items=items)
