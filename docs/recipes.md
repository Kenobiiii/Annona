# Recipe of the day and "mark as cooked"

Tap a meal on the home screen and get a recipe adapted to what the menu bought and how you cook.

## How a recipe is made

1. The weekly plan already fixes the meal and its ingredients with code-computed amounts per
   person ([planner.md](planner.md)).
2. **The model writes only the steps** (large tier, strict JSON). It refers to every ingredient as
   a placeholder `{p12}`; **the code replaces it with the name and the household's amount**, so
   the model never does arithmetic or writes a quantity.
3. **Code validates** every recipe (`core/planner/recipe.py`):
   - only the meal's ingredients (water, salt, pepper, dried spices are free). A best-effort
     heuristic also flags catalogue products and common staples (oil, vinegar, butter, sugar,
     flour, garlic, lemon, sauces...) that are not in the meal, because they are things you would
     have to buy;
   - no quantities written by the model, no broken placeholders, every ingredient used;
   - only appliances you have: **a kitchen without oven never gets an oven step** (checked on
     the declared appliance and on oven words in the text).
   Loose placeholder spellings (`{{p12}}`, `[p12]`, `{ p12 }`) are rewritten to `{p12}` instead of
   failing the recipe. Other problems go back to the model once, with the exact list (a broken
   placeholder is quoted); if they remain, the recipe is rejected.
4. The recipe is stored (`Recipe.method`) and reused. It is regenerated when you ask, or when the
   stored one no longer fits the kitchen (for example you removed the oven).

## Times and your hob (calibration)

Hobs differ and their power is not looked up by model (CLAUDE.md). In **Tools** you measure how
long 1 L of water takes to boil at a dial level. From that:

- the time of a "bring X ml to the boil" step is `measured minutes x X / 1000`, at the level you
  calibrated (`boil_ml` in the step);
- the time food needs to cook is **never** rescaled; it is the model's estimate and is shown with
  `~`. Boil times show without `~` once calibrated;
- each heat word maps to a dial level only if you told the app how many levels the dial has:
  low = 25 %, medium = 50 %, high = 80 % of the dial (`RecipeSettings.dial_fraction`). These are
  **estimates**, configurable, and dial positions are not linear in power.

## Marking a meal as cooked

`GET /meals/cook-preview` shows what would be taken from the pantry (needed, in pantry, to deduct,
missing). `POST /meals/cook` applies it after you confirm, and never twice. The pantry never goes
negative: what is missing is reported (`not_in_pantry`, `not_enough`, `unit_unknown` when a pantry
item's unit cannot be converted without a weight or density). The item that expires first is used
first. Products can be left out of the deduction.

Ticking an item of the shopping list adds it to the pantry ([shopping.md](shopping.md)); until you
do that (or fill the pantry by hand) most lines will say `not_in_pantry`.

## API and tools

`POST /meals/recipe`, `GET /meals/cook-preview`, `POST /meals/cook`; MCP/chat: `recipe_of_the_day`
(with `slot`) and `cook_meal`. See [mcp.md](mcp.md).

## Weekly servings in short plans

"Meat 3 times a week" is scaled to the days a plan covers (rounded up, at most the weekly figure):
a one-day plan asks for 1, otherwise a short plan could never satisfy the weekly minimum. The
shopping optimiser and the plan verification use the same rule (`UserProfile.servings_for_days`).
