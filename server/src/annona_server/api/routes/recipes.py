# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recipe of a planned meal and "mark as cooked"."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from annona_core.domain import MealSlot
from annona_core.planner import RenderedStep

from ...planner.recipes import (
    AlreadyCooked,
    CookPreview,
    MealNotFound,
    RecipeRejected,
    cook,
    cook_preview,
    detailed_recipe,
)
from ..deps import HouseholdDep, SessionDep
from ..errors import APIError

router = APIRouter(tags=["recipes"])


class RecipeIn(BaseModel):
    day: date
    slot: MealSlot
    regenerate: bool = False


class AmountOut(BaseModel):
    product_id: int
    name: str
    amount: Decimal
    unit: str


class Eater(BaseModel):
    name: str
    servings: Decimal


class RecipeOut(BaseModel):
    day: date
    slot: MealSlot
    title: str
    eaters: list[Eater]
    ingredients: list[AmountOut] = Field(description="the household's total for this meal")
    portions: dict[str, list[AmountOut]] = Field(description="each person's own amounts")
    steps: list[RenderedStep]
    total_minutes: int
    calibrated: bool = Field(description="boil times come from the user's hob measurement")
    cooked_at: datetime | None
    generated: bool = Field(description="false when a stored recipe was reused")


@router.post("/meals/recipe", response_model=RecipeOut)
def meal_recipe(
    body: RecipeIn, request: Request, session: SessionDep, household: HouseholdDep
) -> RecipeOut:
    """The detailed recipe of a planned meal (10-30 s the first time, then stored)."""
    try:
        result = detailed_recipe(
            session,
            request.app.state.llm_factory,
            household.id,
            body.day,
            body.slot,
            regenerate=body.regenerate,
        )
    except MealNotFound as error:
        raise APIError(404, "not_found", str(error)) from error
    except RecipeRejected as error:
        raise APIError(
            422,
            "recipe_rejected",
            "the AI recipe did not pass the checks; try again",
            details=error.issues,
        ) from error
    except APIError:
        raise
    except Exception as error:  # the AI provider failed (down, bad key, demo mode...)
        raise APIError(502, "ai_error", f"{type(error).__name__}: {error}"[:300]) from error
    parts = result.parts
    return RecipeOut(
        day=body.day,
        slot=body.slot,
        title=parts.recipe.title,
        eaters=[Eater(name=n, servings=s) for n, s in parts.eaters],
        ingredients=[AmountOut(**i.model_dump()) for i in parts.totals()],
        portions={
            name: [AmountOut(**i.model_dump()) for i in items]
            for name, items in parts.portions().items()
        },
        steps=list(result.rendered.steps),
        total_minutes=result.rendered.total_minutes,
        calibrated=result.rendered.calibrated,
        cooked_at=result.cooked_at,  # type: ignore[arg-type]
        generated=result.generated,
    )


class CookLineOut(BaseModel):
    product_id: int
    name: str
    unit: str
    needed: Decimal
    in_pantry: Decimal
    deduct: Decimal
    missing: Decimal
    note: str | None = Field(description="not_in_pantry | not_enough | unit_unknown | null")


class CookOut(BaseModel):
    already_cooked: bool
    lines: list[CookLineOut]


def _out(preview: CookPreview) -> CookOut:
    return CookOut(
        already_cooked=preview.already_cooked,
        lines=[
            CookLineOut(
                product_id=ln.product_id,
                name=ln.name,
                unit=ln.unit,
                needed=ln.needed,
                in_pantry=ln.in_pantry,
                deduct=ln.deduct,
                missing=ln.missing,
                note=ln.note,
            )
            for ln in preview.lines
        ],
    )


@router.get("/meals/cook-preview", response_model=CookOut)
def meal_cook_preview(
    session: SessionDep,
    household: HouseholdDep,
    day: date,
    slot: MealSlot,
) -> CookOut:
    """What marking this meal as cooked would take from the pantry. Changes nothing."""
    try:
        return _out(cook_preview(session, household.id, day, slot))
    except MealNotFound as error:
        raise APIError(404, "not_found", str(error)) from error


class CookIn(BaseModel):
    day: date
    slot: MealSlot
    skip_products: list[int] = Field(
        default_factory=list, description="products to leave out of the deduction"
    )


@router.post("/meals/cook", response_model=CookOut)
def meal_cook(body: CookIn, session: SessionDep, household: HouseholdDep) -> CookOut:
    """Mark the meal as cooked and deduct it from the pantry (once)."""
    try:
        return _out(
            cook(
                session,
                household.id,
                body.day,
                body.slot,
                skip_products=frozenset(body.skip_products),
            )
        )
    except MealNotFound as error:
        raise APIError(404, "not_found", str(error)) from error
    except AlreadyCooked as error:
        raise APIError(409, "already_cooked", str(error)) from error
