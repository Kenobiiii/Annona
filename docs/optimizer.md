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
- Money is recomputed with integer cents from the integer pack counts; the solver's floats never
  reach the bill.
