# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scaling a drafted plan to the energy and products it should use. SYNTHETIC test values."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from annona_core.planner import PlanDraft, scale_to_energy, verify

from .test_planner import AVAILABLE, context, draft_json, run


def day_kcal(draft: PlanDraft, ctx) -> dict[int, Decimal]:
    kcal = {a.product.id: a.kcal for a in ctx.available}
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for meal in draft.meals:
        totals[meal.weekday] += sum((i.amount * kcal[i.product_id] for i in meal.ingredients), 0)
    return totals


def test_a_draft_of_small_home_portions_is_scaled_to_the_persons_energy():
    # The real failure: the model draws ~2,000 kcal-a-day portions for someone who needs more.
    ctx = context()
    raw = PlanDraft.model_validate_json(draft_json(ctx, grams_factor=0.3))
    assert not verify(raw, ctx).ok  # without scaling it is rejected
    scaled = scale_to_energy(raw, ctx)
    wanted = ctx.members[0].daily.energy_kcal * ctx.energy_scale
    for weekday, energy in day_kcal(scaled, ctx).items():
        assert abs(energy - wanted) / wanted < Decimal("0.005"), weekday
    outcome, fake = run(ctx, draft_json(ctx, grams_factor=0.3))
    assert outcome.accepted and not outcome.repaired and len(fake.requests) == 1


def test_scaling_only_rescales_the_models_choices():
    ctx = context()
    raw = PlanDraft.model_validate_json(draft_json(ctx))
    scaled = scale_to_energy(raw, ctx)
    assert len(scaled.meals) == len(raw.meals)
    for before, after in zip(raw.meals, scaled.meals, strict=True):
        assert (before.weekday, before.slot, before.title) == (
            after.weekday,
            after.slot,
            after.title,
        )
        assert [i.product_id for i in before.ingredients] == [
            i.product_id for i in after.ingredients
        ]
        assert all(i.amount > 0 for i in after.ingredients)


def test_scaling_is_deterministic():
    ctx = context()
    raw = PlanDraft.model_validate_json(draft_json(ctx))
    assert scale_to_energy(raw, ctx) == scale_to_energy(raw, ctx)


def test_a_product_the_model_overuses_is_pulled_back_towards_what_was_bought():
    base = context()
    oats = next(a for a in AVAILABLE if a.product.name == "oats")
    stingy = tuple(
        a.model_copy(update={"intended": Decimal(300)}) if a is oats else a for a in AVAILABLE
    )
    ctx = context(available=stingy)
    raw = PlanDraft.model_validate_json(draft_json(ctx))

    def oats_total(draft: PlanDraft) -> Decimal:
        return sum(
            (
                i.amount
                for m in draft.meals
                for i in m.ingredients
                if i.product_id == oats.product.id
            ),
            Decimal(0),
        )

    assert oats_total(scale_to_energy(raw, ctx)) < oats_total(scale_to_energy(raw, base))


def test_days_outside_the_schedule_and_unknown_products_do_not_crash():
    ctx = context()
    raw = PlanDraft.model_validate_json(
        draft_json(ctx, tweak=lambda meal: meal.update(weekday=meal["weekday"]))
    )
    extra = raw.meals[0].model_copy(
        update={"weekday": 5, "ingredients": raw.meals[0].ingredients}
    )  # a day that is not planned
    out = scale_to_energy(PlanDraft.model_construct(meals=[*raw.meals, extra]), ctx)
    assert out.meals[-1].ingredients == extra.ingredients  # left alone
    assert ctx.schedule.week_start + timedelta(days=5) not in ctx.schedule.days
