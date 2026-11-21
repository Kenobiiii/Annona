# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan a week end to end: optimise the shop for the schedule, draft and verify the meals with
the LLM, and store the accepted plan (generated once, reused until regenerated)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlmodel import Session

from annona_core.domain import (
    MealPlan,
    PlannedMeal,
    PlanStatus,
    Recipe,
    RecipeIngredient,
    RecipeSource,
    Unit,
)
from annona_core.llm import LLMClient
from annona_core.nutrition import daily_targets
from annona_core.optimizer import OptimizerSettings, Result, optimise
from annona_core.planner import (
    Appliance,
    Available,
    MealSchedule,
    Member,
    PlanContext,
    PlanOutcome,
    plan_week,
)

from ..config import load_env
from ..db.repositories import (
    EquipmentRepository,
    MealPlanRepository,
    PlannedMealRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    SqlProductRepository,
    UserProfileRepository,
)
from ..optimize import build_problem


def language() -> str:
    load_env()
    return os.environ.get("ANNONA_LANGUAGE", "es")


@dataclass
class WeekPlan:
    shopping: Result
    outcome: PlanOutcome | None  # None when the shop itself is infeasible
    context: PlanContext | None
    plan_id: int | None = None


def build_context(
    session: Session,
    *,
    household_id: int,
    schedule: MealSchedule,
    shopping: Result,
    on_date: date,
) -> PlanContext:
    members = UserProfileRepository(session).list(household_id=household_id)
    products = SqlProductRepository(session)
    available = []
    for line in shopping.lines:
        product = products.get(line.product_id)
        if product is None or product.nutrition is None:
            continue
        available.append(
            Available(
                product=product,
                basis=line.basis_unit,
                available=line.available,
                intended=line.used_total,
                kcal=product.nutrition.energy_kcal / 100,
                protein=product.nutrition.protein_g / 100,
                not_for=tuple(note.member for note in line.not_for),
            )
        )
    equipment = next(iter(EquipmentRepository(session).list(household_id=household_id)), None)
    planned_members = tuple(Member(profile=m, daily=daily_targets(m, on_date)) for m in members)
    target = sum((m.daily.energy_kcal for m in planned_members), Decimal(0))
    target *= schedule.day_equivalents
    bought = shopping.period_totals.energy_kcal if shopping.period_totals else target
    return PlanContext(
        schedule=schedule,
        members=planned_members,
        energy_scale=(bought / target) if target else Decimal(1),
        available=tuple(available),
        equipment=equipment,
        language=language(),
    )


def plan_and_store(
    session: Session,
    llm: LLMClient,
    *,
    household_id: int,
    store_id: str,
    schedule: MealSchedule,
    on_date: date,
    budget_cents: int | None = None,
    settings: OptimizerSettings | None = None,
) -> WeekPlan:
    problem = build_problem(
        session,
        household_id=household_id,
        store_id=store_id,
        on_date=on_date,
        budget_cents=budget_cents,
        settings=settings,
        schedule=schedule,
    )
    shopping = optimise(problem)
    if shopping.status != "optimal":
        return WeekPlan(shopping=shopping, outcome=None, context=None)
    ctx = build_context(
        session, household_id=household_id, schedule=schedule, shopping=shopping, on_date=on_date
    )
    outcome = plan_week(llm, ctx)
    week = WeekPlan(shopping=shopping, outcome=outcome, context=ctx)
    if outcome.accepted:
        week.plan_id = store_plan(session, household_id, ctx, outcome)
    return week


def existing_plan(session: Session, household_id: int, week_start: date) -> MealPlan | None:
    for plan in MealPlanRepository(session).list(household_id=household_id, week_start=week_start):
        if plan.status == PlanStatus.ACTIVE:
            return plan
    return None


def store_plan(session: Session, household_id: int, ctx: PlanContext, outcome: PlanOutcome) -> int:
    """Store an accepted plan; any previous active plan for that week is archived."""
    plans = MealPlanRepository(session)
    previous = existing_plan(session, household_id, ctx.schedule.week_start)
    if previous is not None:
        plans.update(previous.model_copy(update={"status": PlanStatus.ARCHIVED}))
    plan = plans.add(
        MealPlan(
            household_id=household_id, week_start=ctx.schedule.week_start, status=PlanStatus.ACTIVE
        )
    )
    assert plan.id is not None
    ids = {m.profile.name: m.profile.id for m in ctx.members}
    basis = {a.product.id: a.basis for a in ctx.available}
    recipes, ingredients = RecipeRepository(session), RecipeIngredientRepository(session)
    meals = PlannedMealRepository(session)
    for final in outcome.verification.meals:
        draft = final.draft
        recipe = recipes.add(
            Recipe(
                household_id=household_id,
                title=draft.title,
                servings=1,
                steps=[draft.summary],
                needs_oven=Appliance.OVEN in draft.appliances,
                needs_microwave=Appliance.MICROWAVE in draft.appliances,
                needs_air_fryer=Appliance.AIR_FRYER in draft.appliances,
                source=RecipeSource.LLM,
            )
        )
        assert recipe.id is not None
        # One reference serving with the code-adjusted amounts; each member eats it x servings.
        for product_id, amount in final.base_amounts.items():
            ingredients.add(
                RecipeIngredient(
                    recipe_id=recipe.id,
                    product_id=product_id,
                    amount=max(amount, Decimal("0.1")),
                    unit=Unit(basis[product_id]),
                )
            )
        for portion in final.portions:
            meals.add(
                PlannedMeal(
                    plan_id=plan.id,
                    profile_id=ids[portion.member],
                    day=final.day,
                    slot=draft.slot,
                    recipe_id=recipe.id,
                    servings=max(portion.scale, Decimal("0.01")),
                )
            )
    return plan.id
