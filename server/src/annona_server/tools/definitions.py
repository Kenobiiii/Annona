# SPDX-License-Identifier: AGPL-3.0-or-later
"""The eleven tools. Descriptions are deliberately one line: they are sent on every model turn."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import col, select

from annona_core.domain import MealSlot, PantryItem, PlanStatus, Unit
from annona_core.nutrition import daily_targets
from annona_core.planner import available_appliances

from ..db.repositories import (
    EquipmentRepository,
    PlannedMealRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    ShoppingItemRepository,
    ShoppingListRepository,
    SqlPantryRepository,
    SqlPriceRepository,
    SqlProductRepository,
    UserProfileRepository,
)
from ..db.tables import JobRow
from ..planner import existing_plan
from ..planner.jobs import KIND as PLAN_JOB
from ..planner.jobs import plan_job
from ..planner.recipes import (
    AlreadyCooked,
    MealNotFound,
    RecipeRejected,
    cook,
    cook_preview,
    detailed_recipe,
)
from ..planner.swap import SwapError, propose_swap
from .registry import Tool, ToolContext, ToolError, register

Detail = Literal["concise", "full"]
SLOT_ORDER = {s: i for i, s in enumerate(["breakfast", "lunch", "snack", "dinner"])}


def _money(cents: int | None) -> str | None:
    return None if cents is None else f"{Decimal(cents) / 100:.2f}"


def _monday(day: date) -> date:
    return date.fromordinal(day.toordinal() - day.weekday())


def _member(ctx: ToolContext, name: str | None):
    members = list(UserProfileRepository(ctx.session).list(household_id=ctx.household.id))
    if not members:
        raise ToolError("the household has no members yet: create a profile in the app first")
    if name is None:
        return members[0]
    for m in members:
        if m.name.lower() == name.lower():
            return m
    raise ToolError(f"unknown member {name!r}; members: {', '.join(m.name for m in members)}")


# ------------------------------------------------------------------------------- get_profile


class NoInput(BaseModel):
    pass


class MemberOut(BaseModel):
    name: str
    daily_kcal: Decimal
    protein_g: Decimal
    fat_g: Decimal
    carbs_g: Decimal
    goal: str
    diet: str
    allergies: list[str]
    allergies_confirmed: bool
    food_preferences: dict[str, str]
    weekly_servings: dict[str, int]


class ProfileOut(BaseModel):
    household: str
    weekly_budget: str
    currency: str
    members: list[MemberOut]
    kitchen: list[str]


def get_profile(ctx: ToolContext, _: NoInput) -> ProfileOut:
    members = []
    for m in UserProfileRepository(ctx.session).list(household_id=ctx.household.id):
        t = daily_targets(m, ctx.today)
        members.append(
            MemberOut(
                name=m.name,
                daily_kcal=t.energy_kcal,
                protein_g=t.protein_g,
                fat_g=t.fat_g,
                carbs_g=t.carbohydrates_g,
                goal=str(m.goal),
                diet=str(m.diet),
                allergies=[str(a) for a in m.allergies],
                allergies_confirmed=m.allergies_confirmed,
                food_preferences=dict(m.food_preferences),
                weekly_servings={str(k): v for k, v in m.weekly_servings.items()},
            )
        )
    equipment = next(
        iter(EquipmentRepository(ctx.session).list(household_id=ctx.household.id)), None
    )
    tools = sorted(a.value for a in available_appliances(equipment) if a.value != "none")
    return ProfileOut(
        household=ctx.household.name,
        weekly_budget=_money(ctx.household.weekly_budget_cents) or "0",
        currency=ctx.household.currency,
        members=members,
        kitchen=tools,
    )


register(
    Tool(
        name="get_profile",
        title="Household profile",
        description="Household members with daily calorie/macro targets, diet, allergies, "
        "food preferences, weekly budget and kitchen appliances.",
        input=NoInput,
        output=ProfileOut,
        handler=get_profile,
    )
)

# -------------------------------------------------------------------------------- get_pantry


class PantryIn(BaseModel):
    query: str | None = Field(default=None, description="filter by product name")
    limit: int = Field(default=50, ge=1, le=200)


class PantryLine(BaseModel):
    product_id: int
    name: str
    category: str
    amount: Decimal
    unit: str
    expires_at: date | None


class PantryOut(BaseModel):
    total: int
    items: list[PantryLine]


def _pantry_lines(ctx: ToolContext) -> list[PantryLine]:
    products = SqlProductRepository(ctx.session)
    lines = []
    for item in SqlPantryRepository(ctx.session).for_household(ctx.household.id):
        product = products.get(item.product_id)
        lines.append(
            PantryLine(
                product_id=item.product_id,
                name=product.name if product else "?",
                category=str(product.category) if product else "other",
                amount=item.amount,
                unit=str(item.unit),
                expires_at=item.expires_at,
            )
        )
    return lines


def get_pantry(ctx: ToolContext, args: PantryIn) -> PantryOut:
    lines = _pantry_lines(ctx)
    if args.query:
        lines = [x for x in lines if args.query.lower() in x.name.lower()]
    return PantryOut(total=len(lines), items=lines[: args.limit])


register(
    Tool(
        name="get_pantry",
        title="Pantry",
        description="What the household has at home (amount, unit, expiry), optionally filtered.",
        input=PantryIn,
        output=PantryOut,
        handler=get_pantry,
    )
)

# ----------------------------------------------------------------------------- update_pantry


class PantryChange(BaseModel):
    product_id: int
    mode: Literal["set", "add", "remove"] = Field(
        description="set: replace the amount; add: increase (or create); remove: delete the item"
    )
    amount: Decimal = Field(default=Decimal(0), ge=0)
    unit: Unit = Unit.G
    expires_at: date | None = None


class UpdatePantryIn(BaseModel):
    changes: list[PantryChange] = Field(min_length=1, max_length=20)


def update_pantry(ctx: ToolContext, args: UpdatePantryIn) -> PantryOut:
    pantry, products = SqlPantryRepository(ctx.session), SqlProductRepository(ctx.session)
    items = {i.product_id: i for i in pantry.for_household(ctx.household.id)}
    for change in args.changes:
        if products.get(change.product_id) is None:
            raise ToolError(f"product {change.product_id} does not exist: use search_products")
        current = items.get(change.product_id)
        if change.mode == "remove":
            if current is not None and current.id is not None:
                pantry.delete(current.id)
                items.pop(change.product_id)
            continue
        if current is not None and current.unit != change.unit and change.mode == "add":
            raise ToolError(
                f"product {change.product_id} is stored in {current.unit}; add in that unit"
            )
        amount = change.amount + (current.amount if current and change.mode == "add" else 0)
        if current is None:
            items[change.product_id] = pantry.add(
                PantryItem(
                    household_id=ctx.household.id,
                    product_id=change.product_id,
                    amount=amount,
                    unit=change.unit,
                    expires_at=change.expires_at,
                )
            )
        else:
            items[change.product_id] = pantry.update(
                current.model_copy(
                    update={
                        "amount": amount,
                        "unit": change.unit,
                        "expires_at": change.expires_at or current.expires_at,
                    }
                )
            )
    changed = {c.product_id for c in args.changes}
    lines = [x for x in _pantry_lines(ctx) if x.product_id in changed]
    return PantryOut(total=len(lines), items=lines)


register(
    Tool(
        name="update_pantry",
        title="Update pantry",
        description="Set, add or remove pantry items in one call (up to 20 changes).",
        input=UpdatePantryIn,
        output=PantryOut,
        handler=update_pantry,
        read_only=False,
        destructive=True,
        idempotent=False,
    )
)

# --------------------------------------------------------------------------- search_products


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    store: str | None = Field(default=None, description="store id, e.g. mercadona")
    limit: int = Field(default=8, ge=1, le=20)
    detail: Detail = "concise"


class ProductLine(BaseModel):
    id: int
    name: str
    store: str | None
    price: str | None
    unit_price: str | None  # e.g. "4.10/l"
    # full detail only:
    package: str | None = None
    per_100: dict[str, Decimal] | None = None
    nutrition_source: str | None = None
    allergens: list[str] | None = None


class SearchOut(BaseModel):
    total: int
    items: list[ProductLine]


def _product_line(ctx: ToolContext, product, detail: Detail) -> ProductLine:
    price = (
        SqlPriceRepository(ctx.session).latest(product.id, product.store_id)
        if product.store_id
        else None
    )
    unit = price.unit_price(product) if price is not None and product.package else None
    line = ProductLine(
        id=product.id,
        name=product.name,
        store=product.store_id,
        price=_money(price.amount_cents) if price else None,
        unit_price=f"{_money(unit.amount_cents)}/{unit.per}" if unit else None,
    )
    if detail == "full":
        n = product.nutrition
        line.package = (
            f"{product.package_amount} {product.package_unit}" if product.package else None
        )
        line.per_100 = (
            {
                "kcal": n.energy_kcal,
                "protein_g": n.protein_g,
                "fat_g": n.fat_g,
                "carbs_g": n.carbohydrates_g,
            }
            if n
            else None
        )
        line.nutrition_source = str(n.source) if n else None
        line.allergens = None if product.allergens is None else [str(a) for a in product.allergens]
    return line


def search_products(ctx: ToolContext, args: SearchIn) -> SearchOut:
    found = SqlProductRepository(ctx.session).search(args.query, limit=500)
    if args.store:
        found = [p for p in found if p.store_id == args.store]
    return SearchOut(
        total=len(found),
        items=[_product_line(ctx, p, args.detail) for p in found[: args.limit]],
    )


register(
    Tool(
        name="search_products",
        title="Search products",
        description="Find products by name (ids, prices, unit prices); detail=full adds "
        "nutrition and allergens.",
        input=SearchIn,
        output=SearchOut,
        handler=search_products,
    )
)

# -------------------------------------------------------------------------------- get_prices


class PricesIn(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=20)
    history: int = Field(default=0, ge=0, le=10, description="previous observations to include")


class PricePoint(BaseModel):
    price: str
    observed: date


class PriceOut(BaseModel):
    product_id: int
    name: str
    store: str | None
    latest: PricePoint | None
    unit_price: str | None
    history: list[PricePoint]


class PricesOut(BaseModel):
    items: list[PriceOut]


def get_prices(ctx: ToolContext, args: PricesIn) -> PricesOut:
    products, prices = SqlProductRepository(ctx.session), SqlPriceRepository(ctx.session)
    out = []
    for pid in args.product_ids:
        product = products.get(pid)
        if product is None:
            raise ToolError(f"product {pid} does not exist: use search_products")
        history = list(prices.history(pid, product.store_id)) if product.store_id else []
        latest = history[-1] if history else None
        unit = latest.unit_price(product) if latest is not None and product.package else None
        out.append(
            PriceOut(
                product_id=pid,
                name=product.name,
                store=product.store_id,
                latest=PricePoint(
                    price=_money(latest.amount_cents) or "", observed=latest.observed_at.date()
                )
                if latest
                else None,
                unit_price=f"{_money(unit.amount_cents)}/{unit.per}" if unit else None,
                history=[
                    PricePoint(price=_money(p.amount_cents) or "", observed=p.observed_at.date())
                    for p in history[-(args.history + 1) : -1]
                ]
                if args.history
                else [],
            )
        )
    return PricesOut(items=out)


register(
    Tool(
        name="get_prices",
        title="Prices",
        description="Latest price, unit price and optional price history for up to 20 product ids.",
        input=PricesIn,
        output=PricesOut,
        handler=get_prices,
    )
)

# ------------------------------------------------------------------------ build_weekly_plan


class BuildPlanIn(BaseModel):
    week_start: date = Field(description="Monday of the week")
    store_id: str = Field(description="store to buy from, e.g. mercadona")
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), description="0=Monday")
    skip_slots: list[MealSlot] = Field(default_factory=list, description="slots skipped all week")
    skip: list[tuple[int, MealSlot]] = Field(
        default_factory=list, description="[weekday, slot] pairs to skip"
    )
    variety: Literal["basic", "balanced", "high"] = "basic"
    health_limits: bool = False
    budget_cents: int | None = Field(default=None, ge=0)
    regenerate: bool = False


class BuildPlanOut(BaseModel):
    status: Literal["started", "exists"]
    job_id: str | None
    message: str


def build_weekly_plan(ctx: ToolContext, args: BuildPlanIn) -> BuildPlanOut:
    if args.week_start.weekday() != 0:
        raise ToolError(f"week_start must be a Monday, e.g. {_monday(args.week_start)}")
    if existing_plan(ctx.session, ctx.household.id, args.week_start) and not args.regenerate:
        return BuildPlanOut(
            status="exists",
            job_id=None,
            message="this week already has a plan: call get_plan, or regenerate=true to replace it",
        )
    params = {
        "schedule": {
            "week_start": args.week_start.isoformat(),
            "weekdays": args.weekdays,
            "skip_slots": [str(s) for s in args.skip_slots],
            "skip": [[d, str(s)] for d, s in args.skip],
        },
        "store_id": args.store_id,
        "variety": args.variety,
        "health_limits": args.health_limits,
        "budget_cents": args.budget_cents,
    }
    ctx.session.commit()  # the job runs in its own session
    job_id = ctx.runner.submit(PLAN_JOB, params, plan_job(ctx.llm_factory, ctx.household.id))
    return BuildPlanOut(
        status="started",
        job_id=job_id,
        message="generating (usually 30-90 s): call get_plan with the same week_start",
    )


register(
    Tool(
        name="build_weekly_plan",
        title="Build weekly plan",
        description="Optimise the shop and generate the week's menu in the background; then "
        "call get_plan.",
        input=BuildPlanIn,
        output=BuildPlanOut,
        handler=build_weekly_plan,
        read_only=False,
        idempotent=False,
    )
)

# --------------------------------------------------------------------------------- get_plan


class GetPlanIn(BaseModel):
    week_start: date
    detail: Detail = "concise"
    member: str | None = Field(default=None, description="portions for this member (full)")


class Ingredient(BaseModel):
    name: str
    amount: Decimal
    unit: str


class PlannedMealOut(BaseModel):
    day: date
    slot: str
    title: str
    summary: str | None = None
    appliances: list[str] | None = None
    ingredients: list[Ingredient] | None = None


class GetPlanOut(BaseModel):
    status: Literal["none", "generating", "failed", "rejected", "ready"]
    message: str | None = None
    issues: list[str] = Field(default_factory=list)
    meals: list[PlannedMealOut] = Field(default_factory=list)


def _latest_job(ctx: ToolContext, week: date) -> JobRow | None:
    rows = ctx.session.exec(
        select(JobRow).where(JobRow.kind == PLAN_JOB).order_by(col(JobRow.created_at).desc())
    )
    for row in rows:
        if str(row.params.get("schedule", {}).get("week_start")) == week.isoformat():
            return row
    return None


def _meals(
    ctx: ToolContext, plan_id: int, *, day: date | None, member_id: int | None, detail: Detail
) -> list[PlannedMealOut]:
    recipes, ingredients = RecipeRepository(ctx.session), RecipeIngredientRepository(ctx.session)
    products = SqlProductRepository(ctx.session)
    seen: dict[tuple[date, str], PlannedMealOut] = {}
    for planned in PlannedMealRepository(ctx.session).list(plan_id=plan_id):
        if day and planned.day != day:
            continue
        if member_id is not None and planned.profile_id != member_id:
            continue
        key = (planned.day, str(planned.slot))
        recipe = recipes.get(planned.recipe_id) if planned.recipe_id else None
        if recipe is None or key in seen:
            continue
        meal = PlannedMealOut(day=planned.day, slot=str(planned.slot), title=recipe.title)
        if detail == "full":
            meal.summary = " ".join(recipe.steps)
            meal.appliances = [
                n
                for n, flag in (
                    ("oven", recipe.needs_oven),
                    ("microwave", recipe.needs_microwave),
                    ("air_fryer", recipe.needs_air_fryer),
                )
                if flag
            ]
            meal.ingredients = [
                Ingredient(
                    name=getattr(products.get(i.product_id), "name", "?"),
                    amount=(i.amount * planned.servings).quantize(Decimal(1)),
                    unit=str(i.unit),
                )
                for i in ingredients.list(recipe_id=recipe.id)
            ]
        seen[key] = meal
    return sorted(seen.values(), key=lambda m: (m.day, SLOT_ORDER.get(m.slot, 9)))


def get_plan(ctx: ToolContext, args: GetPlanIn) -> GetPlanOut:
    plan = existing_plan(ctx.session, ctx.household.id, args.week_start)
    job = _latest_job(ctx, args.week_start)
    if job is not None and job.status in ("queued", "running"):
        return GetPlanOut(status="generating", message="still generating: try again shortly")
    if plan is None:
        if job is not None and job.status == "failed":
            return GetPlanOut(status="failed", message=job.error)
        if job is not None and job.result and not job.result.get("accepted", True):
            return GetPlanOut(
                status="rejected",
                message="the AI menu did not pass the checks: call build_weekly_plan again",
                issues=list(job.result.get("issues", [])),
            )
        if job is not None and job.result and job.result.get("shopping_status") != "optimal":
            return GetPlanOut(
                status="rejected",
                message="the shopping list is not feasible",
                issues=[s["detail"] for s in job.result.get("shortfalls", [])],
            )
        return GetPlanOut(status="none", message="no plan for this week: call build_weekly_plan")
    member = _member(ctx, args.member) if args.detail == "full" else None
    meals = _meals(
        ctx, plan.id, day=None, member_id=member.id if member else None, detail=args.detail
    )
    return GetPlanOut(status="ready", meals=meals)


register(
    Tool(
        name="get_plan",
        title="Weekly plan",
        description="The week's menu or its generation status; detail=full adds steps and one "
        "member's portions.",
        input=GetPlanIn,
        output=GetPlanOut,
        handler=get_plan,
    )
)

# ------------------------------------------------------------------------ recipe_of_the_day


class TodayIn(BaseModel):
    day: date | None = Field(default=None, description="default: today")
    member: str | None = None
    slot: MealSlot | None = Field(
        default=None, description="give it to get that meal's detailed recipe (steps, times)"
    )


class RecipeDetail(BaseModel):
    title: str
    total_minutes: int
    boil_times_calibrated: bool
    ingredients: list[Ingredient]  # the household's totals
    steps: list[str]  # "text [appliance, heat, dial level, minutes]"
    cooked: bool


class TodayOut(BaseModel):
    day: date
    member: str
    meals: list[PlannedMealOut]
    recipe: RecipeDetail | None = None


def _step_line(n: int, step) -> str:
    bits = [str(step.appliance)] if str(step.appliance) != "none" else []
    if str(step.heat) != "none":
        bits.append(str(step.heat))
    if step.dial_level is not None:
        bits.append(f"dial {step.dial_level}")
    if step.minutes is not None:
        bits.append(f"{'~' if step.minutes_estimated else ''}{step.minutes} min")
    return f"{n}. {step.text}" + (f" [{', '.join(bits)}]" if bits else "")


def recipe_of_the_day(ctx: ToolContext, args: TodayIn) -> TodayOut:
    day = args.day or ctx.today
    member = _member(ctx, args.member)
    plan = existing_plan(ctx.session, ctx.household.id, _monday(day))
    if plan is None or plan.status != PlanStatus.ACTIVE:
        raise ToolError(f"no plan for the week of {_monday(day)}: call build_weekly_plan")
    meals = _meals(ctx, plan.id, day=day, member_id=member.id, detail="full")
    recipe = None
    if args.slot is not None:
        ctx.session.commit()
        try:
            found = detailed_recipe(ctx.session, ctx.llm_factory, ctx.household.id, day, args.slot)
        except MealNotFound as error:
            raise ToolError(f"{error}: check get_plan") from error
        except RecipeRejected as error:
            raise ToolError(
                "the AI recipe failed the checks (" + "; ".join(error.issues[:3]) + "): try again"
            ) from error
        recipe = RecipeDetail(
            title=found.parts.recipe.title,
            total_minutes=found.rendered.total_minutes,
            boil_times_calibrated=found.rendered.calibrated,
            ingredients=[
                Ingredient(name=i.name, amount=i.amount.quantize(Decimal(1)), unit=i.unit)
                for i in found.parts.totals()
            ],
            steps=[_step_line(n, s) for n, s in enumerate(found.rendered.steps, start=1)],
            cooked=found.cooked_at is not None,
        )
    return TodayOut(day=day, member=member.name, meals=meals, recipe=recipe)


register(
    Tool(
        name="recipe_of_the_day",
        title="Today's meals",
        description="A day's meals and portions; with slot, that meal's detailed recipe.",
        input=TodayIn,
        output=TodayOut,
        handler=recipe_of_the_day,
    )
)

# ---------------------------------------------------------------------------------- cook_meal


class CookIn(BaseModel):
    day: date | None = Field(default=None, description="default: today")
    slot: MealSlot
    confirm: bool = Field(
        default=False, description="false: only show what would change; true: apply it"
    )
    skip_products: list[int] = Field(default_factory=list, max_length=20)


class CookLineTool(BaseModel):
    name: str
    needed: str
    deduct: str
    missing: str | None = None  # amount not in the pantry
    note: str | None = None


class CookOut(BaseModel):
    status: Literal["preview", "cooked", "already_cooked"]
    lines: list[CookLineTool]
    message: str


def _cook_lines(lines) -> list[CookLineTool]:
    return [
        CookLineTool(
            name=ln.name,
            needed=f"{ln.needed.quantize(Decimal(1))} {ln.unit}",
            deduct=f"{ln.deduct.quantize(Decimal(1))} {ln.unit}",
            missing=f"{ln.missing.quantize(Decimal(1))} {ln.unit}" if ln.missing > 0 else None,
            note=ln.note,
        )
        for ln in lines
    ]


def cook_meal(ctx: ToolContext, args: CookIn) -> CookOut:
    day = args.day or ctx.today
    try:
        preview = cook_preview(ctx.session, ctx.household.id, day, args.slot)
        if preview.already_cooked:
            return CookOut(
                status="already_cooked",
                lines=_cook_lines(preview.lines),
                message="this meal was already marked as cooked; nothing changed",
            )
        if not args.confirm:
            return CookOut(
                status="preview",
                lines=_cook_lines(preview.lines),
                message="nothing changed yet: ask the user, then call again with confirm=true",
            )
        done = cook(
            ctx.session,
            ctx.household.id,
            day,
            args.slot,
            skip_products=frozenset(args.skip_products),
        )
    except MealNotFound as error:
        raise ToolError(f"{error}: check get_plan") from error
    except AlreadyCooked as error:
        raise ToolError(str(error)) from error
    return CookOut(
        status="cooked", lines=_cook_lines(done.lines), message="pantry updated, meal marked cooked"
    )


register(
    Tool(
        name="cook_meal",
        title="Mark a meal as cooked",
        description="Preview, then (confirm=true) mark a meal cooked and deduct the pantry.",
        input=CookIn,
        output=CookOut,
        handler=cook_meal,
        read_only=False,
        destructive=True,
        idempotent=False,
    )
)

# ---------------------------------------------------------------------------------- swap_meal


class SwapIn(BaseModel):
    day: date | None = Field(default=None, description="default: today")
    slot: MealSlot
    request: str = Field(
        max_length=300, description="what the person wants instead, in their words"
    )
    avoid_appliances: list[Literal["oven", "microwave", "air_fryer"]] = Field(
        default_factory=list, description="appliances the new dish must NOT use"
    )


class SwapOut(BaseModel):
    status: Literal["proposed"]
    action_id: int
    old_title: str
    new_title: str
    appliances: list[str]
    ingredients: list[str]
    message: str


def swap_meal(ctx: ToolContext, args: SwapIn) -> SwapOut:
    from ..chat.actions import create_pending
    from ..chat.describe import describe_swap

    day = args.day or ctx.today
    ctx.session.commit()
    try:
        proposal = propose_swap(
            ctx.session,
            ctx.llm_factory(ctx.session),
            ctx.household,
            day,
            args.slot,
            args.request,
            avoid_appliances=list(args.avoid_appliances),
        )
    except MealNotFound as error:
        raise ToolError(f"{error}: check get_plan") from error
    except SwapError as error:
        raise ToolError(error.message) from error
    action = create_pending(
        ctx.session,
        ctx.household,
        kind="swap",
        tool="swap_meal",
        payload=proposal.model_dump(mode="json"),
        summary=describe_swap(proposal),
    )
    return SwapOut(
        status="proposed",
        action_id=action.id,  # type: ignore[arg-type]
        old_title=proposal.old_title,
        new_title=proposal.title,
        appliances=proposal.appliances,
        ingredients=[
            f"{i.name} {i.amount.quantize(Decimal(1))} {i.unit}" for i in proposal.ingredients
        ],
        message="proposed only: nothing changed until the person confirms it in the app",
    )


register(
    Tool(
        name="swap_meal",
        title="Propose a different dish",
        description="Propose swapping one planned meal for another dish; the person confirms.",
        input=SwapIn,
        output=SwapOut,
        handler=swap_meal,
        read_only=False,
        destructive=False,
        idempotent=False,
        proposes=True,
    )
)

# ----------------------------------------------------------------------------- shopping_list


class ShoppingIn(BaseModel):
    week_start: date


class ShoppingLine(BaseModel):
    name: str
    packs: int
    price: str | None
    checked: bool


class ShoppingOut(BaseModel):
    store: str
    total: str
    items: list[ShoppingLine]


def shopping_list(ctx: ToolContext, args: ShoppingIn) -> ShoppingOut:
    plan = existing_plan(ctx.session, ctx.household.id, args.week_start)
    if plan is None:
        raise ToolError("no plan for this week: call build_weekly_plan first")
    lists = ShoppingListRepository(ctx.session).list(plan_id=plan.id)
    if not lists:
        raise ToolError("this plan has no shopping list")
    products = SqlProductRepository(ctx.session)
    items = ShoppingItemRepository(ctx.session).list(list_id=lists[-1].id)
    total = sum(i.packs * (i.unit_price_cents or 0) for i in items)
    return ShoppingOut(
        store=lists[-1].store_id,
        total=_money(total) or "0",
        items=[
            ShoppingLine(
                name=getattr(products.get(i.product_id), "name", "?"),
                packs=i.packs,
                price=_money(i.unit_price_cents),
                checked=i.checked,
            )
            for i in items
        ],
    )


register(
    Tool(
        name="shopping_list",
        title="Shopping list",
        description="The week's shopping list for its store with packs, prices and total.",
        input=ShoppingIn,
        output=ShoppingOut,
        handler=shopping_list,
    )
)
