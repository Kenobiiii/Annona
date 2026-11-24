# Data model

Domain models live in `core/src/annona_core/domain/` (pure Pydantic, no I/O). Their SQLite tables,
migrations and repositories live in `server/src/annona_server/db/`.

## Entities

```
Household 1─N UserProfile          (members: personal nutrition data)
Household 1─1 Equipment            (the shared kitchen)
Household 1─N PantryItem N─1 Product
Household 1─N MealPlan 1─N PlannedMeal N─1 Recipe 1─N RecipeIngredient N─1 Product
Household 1─N ShoppingList 1─N ShoppingItem N─1 Product     (ShoppingList N─1 MealPlan, optional)
Household 1─N Receipt 1─N ReceiptLine ─(optional)─ Product
Product 1─N Price ─(optional)─ ReceiptLine
```

| Entity | Notes |
|---|---|
| `Household` | Owns everything shared: weekly budget (cents + currency), pantry, kitchen, plans, lists, receipts. Today one household with one member; ready for more. |
| `UserProfile` | A member: sex, birth date, height, weight, activity (4 levels, see [nutrition.md](nutrition.md)), goal, diet, allergies (EU 14) and `allergies_confirmed`. |
| `Equipment` | Hob type, burners, power levels, oven/microwave/air fryer, calibration (minutes to boil 1 L at level N). |
| `Product` | Something you can buy. Store products carry `store_id` + `store_sku`; generic foods have neither. Optional `ean` (barcode), package size, weight per unit, density, allergens (`None` = unknown, `[]` = none), nutrition. |
| `NutritionFacts` | Embedded in `Product`. Per 100 g or 100 ml (`basis`). `source` + `source_ref`. |
| `Price` | One observation: product, store, cents + currency, `source` (scrape/receipt/manual), `observed_at` (UTC). Unit prices are computed, never stored. |
| `PantryItem` | Product + quantity in a canonical unit, optional expiry. |
| `Recipe`, `RecipeIngredient` | Steps, servings, equipment needs; ingredients are products + quantities. |
| `MealPlan`, `PlannedMeal` | A week (starting Monday); meals per day/slot, optionally per member. |
| `ShoppingList`, `ShoppingItem` | For one store; packs and a price snapshot. |
| `Receipt`, `ReceiptLine` | Scanned receipts; lines are matched to products with a confidence and need confirmation. |
| `StoreConnection` | Per household and store plugin: the shop's postal code (and the store's own location code resolved from it) and when the person accepted an opt-in plugin's notice (`None` = not accepted). |

## Rules

- **Money:** integer minor units (cents) + ISO 4217 code. Never float.
- **Quantities:** `Decimal` in `g`, `ml` or `unit`. Input in kg, l, cl, dl, mg is normalised.
  Mass↔volume needs the product's density; unit↔mass needs its weight per unit. Missing data raises
  `UnitConversionError` — nothing is guessed.
- **Unit price:** price × reference (1000 g, 1000 ml or 1 unit) ÷ package size, rounded half-up to
  whole cents at the end.
- **Nutrition source priority:** `manual` > `label_scan` > `off` (Open Food Facts) >
  `llm_estimate` > `sample`. Automatic updates never overwrite a higher-priority source.
- **Time:** timezone-aware UTC everywhere.
- **Storage:** decimals are stored as text so they round-trip exactly; foreign keys are enforced.
  Deleting a household deletes its data; a product used by a pantry, recipe or list cannot be deleted.

## Database commands

```bash
uv run python -m annona_server.db upgrade     # create/upgrade the schema (ANNONA_DATABASE_URL)
uv run python -m annona_server.db downgrade   # drop everything (back to base)
uv run python -m annona_server.seed           # upgrade + load the sample foods (idempotent)
```

Changing a table requires a new Alembic revision; `server/tests/test_migrations.py` fails if the
models and migrations drift apart.

## Sample foods

`server/src/annona_server/seed/sample_foods.json` holds 31 generic foods from **USDA FoodData Central,
SR Legacy (2018-04)**, public domain (CC0). They are **sample data** for development (marked
`source: sample`, `source_ref: usda-fdc:<id>`), not products of any store; real store products and
their label nutrition arrive with the supermarket providers and Open Food Facts.

Regenerate with `uv run python scripts/build_usda_seed.py`. Every value comes from the dataset except
two derived ones: `salt_g = sodium_mg × 2.5 / 1000` (EU 1169/2011) and density from USDA's
"1 cup" weight. Spanish BEDCA data is **not** used: its terms do not allow redistribution under an
open licence.
