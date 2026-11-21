# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optimiser tests. Products, prices and nutrition below are SYNTHETIC test values."""

from datetime import date
from decimal import Decimal

import pytest

from annona_core.domain import (
    ActivityLevel,
    Allergen,
    Category,
    Goal,
    NutritionFacts,
    NutritionSource,
    PantryItem,
    Product,
    Sex,
    Unit,
    UserProfile,
)
from annona_core.nutrition import daily_targets, weekly_targets
from annona_core.optimizer import Offer, OptimizerSettings, Problem, optimise

TODAY = date(2026, 11, 21)


def food(pid, name, category, amount, unit, kcal, p, f, c, *, basis=Unit.G, **extra) -> Product:
    return Product(
        id=pid,
        name=name,
        category=category,
        package_amount=Decimal(amount),
        package_unit=unit,
        allergens=extra.pop("allergens", []),
        nutrition=NutritionFacts(
            basis=basis,
            energy_kcal=Decimal(kcal),
            protein_g=Decimal(p),
            fat_g=Decimal(f),
            carbohydrates_g=Decimal(c),
            source=NutritionSource.MANUAL,
        ),
        **extra,
    )


C = Category
CATALOGUE = [
    (food(1, "rice", C.GRAINS, 1000, Unit.G, 365, "7", "0.7", 80, type="rice"), 120),
    (food(2, "lentils", C.LEGUMES, 1000, Unit.G, 350, 24, 1, 60), 180),
    (
        food(
            3,
            "olive oil",
            C.OILS_FATS,
            1000,
            Unit.ML,
            884,
            0,
            100,
            0,
            density_g_per_ml=Decimal("0.91"),
        ),
        450,
    ),
    (food(4, "chicken", C.MEAT, 1000, Unit.G, 120, 22, "2.6", 0), 600),
    (
        food(
            5,
            "milk",
            C.DAIRY,
            1000,
            Unit.ML,
            61,
            "3.2",
            "3.3",
            "4.8",
            basis=Unit.ML,
            allergens=[Allergen.MILK],
        ),
        90,
    ),
    (
        food(
            6,
            "eggs",
            C.EGGS,
            12,
            Unit.UNIT,
            143,
            "12.6",
            "9.5",
            "0.7",
            unit_weight_g=Decimal(60),
            allergens=[Allergen.EGGS],
        ),
        250,
    ),
    (food(7, "apples", C.FRUIT, 1000, Unit.G, 52, "0.3", "0.2", 14), 200),
    (food(8, "carrots", C.VEGETABLES, 1000, Unit.G, 41, "0.9", "0.2", "9.6"), 120),
    (food(9, "tomatoes", C.VEGETABLES, 1000, Unit.G, 18, "0.9", "0.2", "3.9"), 200),
    (food(10, "bread", C.BAKERY, 500, Unit.G, 266, 9, "3.3", 49, allergens=[Allergen.GLUTEN]), 100),
    (food(11, "oats", C.GRAINS, 500, Unit.G, 379, 13, "6.5", 68, allergens=[Allergen.GLUTEN]), 110),
    (food(12, "potatoes", C.VEGETABLES, 2000, Unit.G, 77, 2, "0.1", 17, type="potato"), 250),
    (
        food(
            13, "peanuts", C.NUTS_SEEDS, 500, Unit.G, 567, 26, 49, 16, allergens=[Allergen.PEANUTS]
        ),
        300,
    ),
]


def member(name="Pablo", allergies=()) -> UserProfile:
    return UserProfile(
        id=1,
        household_id=1,
        name=name,
        sex=Sex.MALE,
        birth_date=date(1996, 1, 1),
        height_cm=Decimal(180),
        weight_kg=Decimal(80),
        activity=ActivityLevel.ACTIVE,
        goal=Goal.MAINTAIN,
        allergies=list(allergies),
        allergies_confirmed=True,
    )


def problem(budget=10_000, members=None, offers=None, pantry=(), **settings) -> Problem:
    members = members or [member()]
    targets = weekly_targets([daily_targets(m, TODAY) for m in members])
    return Problem(
        offers=offers or [Offer(product=p, price_cents=c) for p, c in CATALOGUE],
        members=members,
        pantry=list(pantry),
        targets=targets,
        budget_cents=budget,
        settings=OptimizerSettings(**settings),
    )


def check_feasible(result, prob):
    t, totals, s = prob.targets, result.period_totals, prob.settings
    assert result.status == "optimal"
    assert t.energy_kcal_min - 1 <= totals.energy_kcal <= t.energy_kcal_max + 1
    assert totals.protein_g >= t.protein_g - 1
    assert t.fat_g_min - 1 <= totals.fat_g <= t.fat_g_max + 1
    assert totals.fruit_veg_g >= s.fruit_veg_g_per_person_day * len(prob.members) * s.days - 1
    assert result.total_cost_cents <= prob.budget_cents
    assert result.total_cost_cents == sum(line.cost_cents for line in result.lines)
    for line in result.lines:
        assert line.kcal <= totals.energy_kcal * s.max_kcal_share_per_product + 2


def test_feasible_plan_meets_every_target():
    prob = problem()
    result = optimise(prob)
    check_feasible(result, prob)
    names = {line.name for line in result.lines}
    assert "potatoes" not in names or result.period_totals.fruit_veg_g >= 2800
    assert result.daily_average.energy_kcal == (result.period_totals.energy_kcal / 7).quantize(
        Decimal("0.1")
    )


def test_potatoes_do_not_count_as_vegetables():
    only_potatoes = [
        o for o in problem().offers if o.product.name not in ("apples", "carrots", "tomatoes")
    ]
    result = optimise(problem(offers=only_potatoes))
    assert result.status == "infeasible"
    assert [s.constraint for s in result.shortfalls] == ["fruit_veg_min"]
    assert result.shortfalls[0].amount == Decimal(2800)


def test_infeasible_budget_reports_the_money_needed():
    cheapest = optimise(problem(budget=1_000_000)).total_cost_cents
    result = optimise(problem(budget=1_000))
    assert result.status == "infeasible"
    [shortfall] = result.shortfalls
    assert shortfall.constraint == "budget"
    assert shortfall.amount == cheapest - 1_000
    assert "more money" in shortfall.detail


def test_pantry_reduces_the_cost():
    base = optimise(problem())
    rice = CATALOGUE[0][0]
    stocked = optimise(
        problem(
            pantry=[PantryItem(household_id=1, product_id=1, amount=Decimal(5000), unit=Unit.G)]
        )
    )
    assert stocked.status == "optimal"
    assert stocked.total_cost_cents <= base.total_cost_cents
    rice_line = next((line for line in stocked.lines if line.product_id == rice.id), None)
    if rice_line:
        assert rice_line.used_from_pantry > 0


def test_allergy_excludes_product_for_a_single_person_household():
    result = optimise(problem(members=[member(allergies=[Allergen.MILK])]))
    assert "milk" not in {line.name for line in result.lines}
    assert any(w.issue == "excluded_nobody_can_eat" and w.name == "milk" for w in result.warnings)


def test_shared_household_may_buy_allergens_but_flags_them():
    members = [member("Ana", allergies=[Allergen.MILK]), member("Pablo")]
    prob = problem(budget=20_000, members=members)
    result = optimise(prob)
    check_feasible(result, prob)
    milk = next((line for line in result.lines if line.name == "milk"), None)
    if milk is not None:
        assert milk.not_for[0].member == "Ana"
        assert milk.not_for[0].reasons == ["contains_allergen: milk"]
    # Every bought allergen product names who must not eat it.
    for line in result.lines:
        if line.name in ("milk",):
            assert line.not_for


def test_sold_by_unit_without_weight_is_excluded_and_reported():
    eggs_no_weight = food(6, "eggs", C.EGGS, 12, Unit.UNIT, 143, "12.6", "9.5", "0.7", allergens=[])
    offers = [Offer(product=p, price_cents=c) for p, c in CATALOGUE if p.id != 6]
    offers.append(Offer(product=eggs_no_weight, price_cents=250))
    result = optimise(problem(offers=offers))
    assert result.status == "optimal"
    assert any(w.issue == "excluded_no_unit_weight" for w in result.warnings)
    assert not result.complete


def test_missing_density_is_estimated_and_flagged():
    oil = food(3, "olive oil", C.OILS_FATS, 1000, Unit.ML, 884, 0, 100, 0)  # no density
    offers = [Offer(product=p, price_cents=c) for p, c in CATALOGUE if p.id != 3]
    offers.append(Offer(product=oil, price_cents=450))
    result = optimise(problem(offers=offers))
    assert any(w.issue == "density_estimated" and w.name == "olive oil" for w in result.warnings)
    for line in result.lines:
        assert line.estimated == (line.name == "olive oil")


def test_no_nutrition_is_excluded():
    bare = Product(id=99, name="mystery", package_amount=Decimal(1), package_unit=Unit.G)
    result = optimise(problem(offers=[Offer(product=bare, price_cents=100)]))
    assert result.status == "no_candidates"
    assert result.warnings[0].issue == "excluded_no_nutrition"


def test_variety_limits_each_product():
    prob = problem(max_kcal_share_per_product=Decimal("0.15"))
    check_feasible(optimise(prob), prob)


def test_deterministic():
    first, second = optimise(problem()), optimise(problem())
    assert first.model_dump() == second.model_dump()


@pytest.mark.parametrize("budget", [3_000, 5_000, 8_000])
def test_budget_is_never_exceeded(budget):
    result = optimise(problem(budget=budget))
    if result.status == "optimal":
        assert result.total_cost_cents <= budget
    else:
        assert result.shortfalls and result.shortfalls[0].constraint == "budget"


def salty_crisps() -> Product:
    """SYNTHETIC: very cheap calories, very salty and high in saturated fat."""
    p = food(20, "crisps", C.OTHER, 300, Unit.G, 530, 6, 33, 50)
    nutrition = p.nutrition.model_copy(
        update={"salt_g": Decimal("1.5"), "saturated_fat_g": Decimal(15)}
    )
    return p.model_copy(update={"nutrition": nutrition})


def with_crisps(**settings) -> Problem:
    offers = [Offer(product=p, price_cents=c) for p, c in CATALOGUE]
    offers.append(Offer(product=salty_crisps(), price_cents=60))
    return problem(offers=offers, **settings)


def test_health_limits_are_off_by_default():
    prob = with_crisps()
    result = optimise(prob)
    assert not prob.settings.health_limits
    assert not any(w.issue == "salt_unknown" for w in result.warnings)


def test_health_limits_cap_salt_and_saturated_fat():
    prob = with_crisps(health_limits=True)
    result = optimise(prob)
    assert result.status == "optimal"
    totals = result.period_totals
    assert totals.salt_g <= Decimal(5) * 7 + Decimal("0.1")
    assert totals.saturated_fat_g * 9 <= totals.energy_kcal * Decimal("0.10") + 1
    # Products without salt data are flagged: the limit may be underestimated.
    assert any(w.issue == "salt_unknown" for w in result.warnings)


def test_health_limits_explain_when_impossible():
    """Only crisps: the calories needed bring far more than 35 g of salt a week.

    The explanation is a trade-off (eat less, or exceed the salt/saturated-fat limits); with
    other foods available it would instead pick them (see the test above).
    """
    only_crisps = [Offer(product=salty_crisps(), price_cents=60)]
    result = optimise(
        problem(
            offers=only_crisps,
            health_limits=True,
            max_kcal_share_per_product=Decimal(1),
            fruit_veg_g_per_person_day=Decimal(0),
        )
    )
    assert result.status == "infeasible"
    constraints = {s.constraint for s in result.shortfalls}
    assert constraints & {"salt_max", "saturated_fat_max", "energy_min"}


def test_sample_nutrition_on_store_products_is_flagged():
    rice = CATALOGUE[0][0]
    sample = rice.model_copy(
        update={
            "store_id": "shop",
            "store_sku": "1",
            "nutrition": rice.nutrition.model_copy(update={"source": NutritionSource.SAMPLE}),
        }
    )
    offers = [Offer(product=p, price_cents=c) for p, c in CATALOGUE if p.id != 1]
    offers.append(Offer(product=sample, price_cents=120))
    result = optimise(problem(offers=offers))
    assert any(w.issue == "nutrition_sample" and w.name == "rice" for w in result.warnings)
    for line in result.lines:
        if line.name == "rice":
            assert line.estimated
