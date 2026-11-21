# Shopping optimiser

Code: `core/src/annona_core/optimizer/` (pure) and `server/src/annona_server/optimize/` (builds the
problem from the database). No LLM: plain mixed-integer programming with `scipy.optimize.milp`
(HiGHS).

```bash
uv run python -m annona_server.optimize --household 1 --store mercadona [--budget 60]
```

## What it decides

For one store and one week: **how many packs of each product to buy** and how much of each product
(bought or already in the pantry) the household eats, so that the purchase is as **cheap as
possible** while meeting every rule below. Turning that into meals per day is the weekly planner's
job (Phase 7); the optimiser reports daily *averages*.

## Rules (all configurable in `OptimizerSettings` / nutrition targets)

| Rule | Default | Source |
|---|---|---|
| Energy | household weekly target ±5 % | [nutrition.md](nutrition.md) |
| Protein | at least the target | ISSN, see nutrition.md |
| Fat | 20-35 % of energy | EFSA |
| Fruit and vegetables | ≥ 400 g per person per day, potatoes and starchy roots excluded | WHO healthy-diet fact sheet |
| Variety | no product above 20 % of the week's calories | project choice |
| Budget | never exceeded | household setting |
| Pantry | stock is used first and costs nothing | — |
| *Optional:* salt | < 5 g per person per day (`--health-limits`) | WHO healthy-diet fact sheet |
| *Optional:* saturated fat | < 10 % of energy (`--health-limits`) | WHO healthy-diet fact sheet |

The health limits are **off by default** (a user choice). Free sugars (WHO < 10 % of energy)
are not limited: labels give *total* sugars, which include the natural sugars of fruit and milk,
so a limit on them would penalise fruit. Products with unknown salt or saturated fat count as 0
and are listed as warnings.

## When the plan is impossible

The result explains why, in two exact steps:

1. what cannot be met **even with unlimited money** (e.g. "fruit and vegetables short by 2800 g":
   the store data has none);
2. with the best achievable nutrition, the cheapest purchase; if it costs more than the budget,
   the difference is the **money needed**.

## Allergies, diets and incomplete data

- A product is excluded only if **no household member** can eat it. Otherwise it may be bought and
  every line says who must not eat it and why (allergen, unknown allergens, diet).
- Products without nutrition, without package size, or sold by the unit without a weight per unit
  are excluded and listed as warnings: add the missing data to include them.
- When a product sold by volume has nutrition per 100 g (or the reverse) and no density, 1 g/ml is
  assumed and the line is flagged **estimated**. The result's `complete` flag stays false until
  such data is fixed, and the CLI prints "INCOMPLETE DATA".
- Store products with no nutrition of their own (fresh produce is rarely in Open Food Facts)
  take the nutrition, weight per unit and density of the generic USDA reference food of the same
  category and type (`source: sample`). Every such line is flagged estimated and listed as
  `nutrition_sample`, until a label scan, Open Food Facts or a manual edit replaces it.
  Allergens are copied only when they add restrictions, never as "contains none".
- Money is recomputed with integer cents from the integer pack counts; the solver's floats never
  reach the bill.
