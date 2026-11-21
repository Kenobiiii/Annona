# Weekly meal planner

Code: `core/src/annona_core/planner/` (pure) and `server/src/annona_server/planner/` (wiring and
storage).

```bash
uv run python -m annona_server.planner --household 1 --store mercadona --week 2026-11-23 \
    --days 0,1,2,3,4 --skip 1:dinner,3:dinner,4:dinner --skip-slot snack \
    [--variety basic|balanced|high] [--health-limits] [--regenerate]
```

## Flow

1. **Schedule** (`MealSchedule`): which days and slots are planned (weekday 0 = Monday; slots
   breakfast, lunch, snack, dinner). Each slot carries a share of daily energy (project default
   25 / 35 / 10 / 30 %, configurable), so "5 days without 3 dinners" = 4.1 day-equivalents.
2. **Shopping**: the optimiser buys for those day-equivalents only ([optimizer.md](optimizer.md)).
3. **Draft (LLM, large tier)**: the model receives only the schedule, people (daily needs,
   diet, allergies, approximate kcal per serving), kitchen appliances and the bought products
   (available and planned amounts, kcal and protein per 100). It returns strict JSON: one meal
   per scheduled slot with ingredient ids, per-person amounts and a one-line summary, in the
   household language (`ANNONA_LANGUAGE`, default `es`).
4. **Verification and portions (code)**:
   - every scheduled slot has exactly one meal, ingredients exist, appliances exist (no oven ->
     no baking, also checked in the text), nobody eats a product that is not for them;
   - a linear programme adjusts every ingredient (0.5x-3x the drafted amount) so each person's
     daily energy matches their target, weekly protein reaches 90 % and stock is respected,
     staying as close as possible to the drafted dish. Shared dishes scale per person.
5. **Fixes**: if only stock is short, whole packs are added to the shopping list within the
   budget ("also buy"); otherwise ONE repair request lists the exact problems. Still failing ->
   rejected with the list.
6. **Storage**: accepted plans are stored (`MealPlan`, `Recipe`, `RecipeIngredient`,
   `PlannedMeal` per member with their serving factor). Generated once; `--regenerate` archives
   the previous one.

## Evals

See [evals.md](evals.md#weekly-planner). Scenarios use the USDA sample foods with synthetic
prices; run with `python -m annona_server.evals plan-run [--variety ...] --yes`.
