# Nutrition targets

Code: `core/src/annona_core/nutrition/`. Pure functions, no AI. **Informational only, not medical
advice.**

## How a daily target is computed

1. **BMR** (resting energy) — Mifflin-St Jeor (1990):
   `10 × kg + 6.25 × cm − 5 × age + 5` (male) or `… − 161` (female).
2. **Total expenditure** — `BMR × activity factor`.
3. **Goal** — `× 0.85` (cut), `× 1.00` (maintain), `× 1.10` (bulk).
4. **Safety floor** — the target is never below the person's own BMR. If the goal would push it
   lower, it is raised to the BMR and a warning is returned. (The common "1200/1500 kcal" floors
   were not used: no authoritative source could be verified for them.)
5. **Macros** — protein `g/kg × weight`; fat 30 % of energy; carbohydrates take the rest
   (4/9/4 kcal per g). Warnings if carbohydrates fall outside 45–60 % of energy.
6. **Range** — ±5 % around the calorie target (never below the BMR), for the optimiser.

Weekly targets are the daily ones × 7; a household's are the sum of its members.

## Defaults and sources

| Value | Default | Source |
|---|---|---|
| BMR formula | Mifflin-St Jeor | Mifflin et al., *Am J Clin Nutr* 1990;51(2):241-7 (adults 19–78) |
| Activity factor | inactive 1.4 · low active 1.6 · active 1.75 · very active 2.05 | National Academies, *DRI for Energy* (2023), Table 7-1; consistent with EFSA (2013): 1.4/1.6/1.8/2.0 |
| Protein | cut 2.0 · maintain 1.6 · bulk 1.8 g/kg | Inside the ISSN range 1.4–2.0 g/kg (Jäger et al., 2017); value per goal is a project choice |
| Fat | 30 % of energy (range 20–35 %) | EFSA (2010) reference intake range; 30 % is a project choice |
| Carbohydrates | remainder; reference 45–60 % | EFSA (2010) |
| Energy per gram | protein 4, carbohydrate 4, fat 9 | Regulation (EU) 1169/2011, Annex XIV |
| Goal adjustment | −15 % / 0 / +10 % | **Project choice** (no single authoritative source) |
| Tolerance | ±5 % | **Project choice** |

Every default lives in `TargetSettings` and can be overridden.

## Warnings

`minor` (under 18: calculated anyway, but formulas are designed for adults and do not have the same
effect while growing), `age_outside_formula_range`, `raised_to_bmr_floor`, `carbs_below_reference`,
`carbs_above_reference`, `protein_and_fat_exceed_energy`, `allergies_not_confirmed`.

## Activity quiz

Two questions suggest one of the four levels; the user can always change it.

1. *What is your work/day like?* sitting · on my feet · physically demanding.
2. *Which day looks most like your usual week?* — the example days from the National Academies
   (2023) Table 7-1 (e.g. "everyday activity + 60–80 min brisk walking" = low active).

The report warns that no validated tool classifies individuals precisely and that its examples fit
low-exertion jobs, so (project rule) a physically demanding job moves the suggestion up one level.

## Allergies and diet

- Each profile must explicitly confirm its allergies (`allergies_confirmed`), so an empty list
  really means "none".
- `Product.allergens = None` means **unknown**. For anyone with allergies, unknown products are
  excluded.
- Diets exclude categories (vegan: meat, fish, eggs, dairy; vegetarian: meat, fish; pescatarian:
  meat) and declared animal allergens (e.g. milk bread for vegans). Meat is not an EU allergen, so
  prepared foods are flagged `diet_uncertain` for vegetarians and vegans.
