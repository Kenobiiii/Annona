# Evaluations ("evals")

An eval answers one question with data: **is this model/prompt good enough, and is a change an
improvement?** Code: `server/src/annona_server/evals/`. Datasets: `evals/datasets/`. Reports:
`evals/results/` (committed, so history is visible).

```bash
uv run python -m annona_server.evals run --classifier rules                 # free baseline
uv run python -m annona_server.evals run --prompt v1_role                   # shows estimated cost
uv run python -m annona_server.evals run --prompt v1_role --yes             # spends (budgeted)
uv run python -m annona_server.evals run --model deepseek/deepseek-v4-pro --yes   # other model
uv run python -m annona_server.evals compare                                # table of all runs
uv run python -m annona_server.evals rescore    # re-apply fixed labels to old runs, free
```

## The pieces

1. **Golden dataset** (`product_classification.jsonl`): real product names (Open Prices, ODbL)
   with the correct category and type. Each row may have a `note`; rows where reasonable people
   disagree are marked `ambiguous`. *An eval is only as good as its labels*: when a "model error"
   turns out to be a label error, fix the label and `rescore` (no new spend).
2. **Runner**: sends the dataset through the classifier, in batches, **bypassing the response
   cache** (a cached answer would measure nothing). Every call is logged in `llm_usage` with task
   `eval:product_classification`.
3. **Cost guard**: the estimated cost (upper bound, peak prices) is printed first; nothing is
   spent without `--yes`; runs stop when `ANNONA_EVAL_BUDGET_USD` (default 1.00) would be
   exceeded by everything already spent on evals.
4. **Report**: one JSON per run with metadata (model, prompt, dataset hash, git commit), metrics
   and every item's prediction, so any number can be traced back to examples.

## Metrics

| Metric | Meaning | Why it matters |
|---|---|---|
| `accuracy` | correct category / all items | headline quality |
| `accuracy_unambiguous` | same, on items not marked ambiguous | removes label noise |
| `type_accuracy` | lenient match of the type label | secondary detail |
| `missing` | items the model skipped | silent failures |
| `diet_unsafe_errors` | wrong category that would let some diet ALLOW the product (e.g. ham as "prepared" for a vegetarian) | **safety: the most important number** |
| `diet_over_restrictive_errors` | wrong category that would wrongly EXCLUDE it (oat drink as dairy for a vegan) | annoying, not dangerous |
| `valid_first_try_rate` / `repair_rate` | batches valid at once / needing the repair retry | reliability and hidden cost |
| `input_tokens`, `output_tokens`, `cost_usd`, `cost_per_item_usd` | spend | the price of quality |
| `latency_ms_p50` / `p95` | typical / slow-case time per batch | user wait |
| `per_category`, `top_confusions` | where it fails | what to fix next |

## How to read results honestly

- **Always keep a baseline.** Rules alone: ~21 % on names only. The LLM's value is the gap.
- **One run is not a result.** LLMs vary between runs. Repeat (3 runs is a cheap minimum) and
  compare means and spreads; a one-item difference on 87 items (1.1 points) is noise.
- **Look at the errors, not just the number.** Several "errors" were ambiguous items or label
  mistakes.
- **Change one thing at a time** (prompt *or* model *or* batch size), so you know what helped.

## First experiment (2026-11-19, `deepseek/deepseek-flash`, 87 items, 3 runs each)

| Prompt | Accuracy per run | Mean | Type (mean) | Cost per run |
|---|---|---|---|---|
| rules (no LLM) | 20.7 % | 20.7 % | 24.1 % | $0 |
| `v1_plain` | 96.5 / 96.5 / 98.9 % | 97.3 % | 83.2 % | ~$0.0010-0.0012 |
| `v1_role` ("You are an expert in Spanish supermarket products…") | 97.7 / 100 / 100 % | 99.2 % | 87.8 % | ~$0.0010-0.0012 |

`v1_role` won every run at the same cost, so it became the default. Remaining errors: sour gummy
sweets read as a condiment once, and two ambiguous items (protein mousse, canned baked beans).

## Second experiment: cheaper output (2026-11-19, off-peak, 3 runs per variant)

Hypothesis: output tokens are ~90 % of the cost, so an ordered `[category, type]` format
(`v2_compact`) should halve cost without hurting accuracy. Schemas sent to the model were also
cleaned (no titles/docstrings), so `v1_role` was re-run as the control.

| Variant | Accuracy per run | Mean | Clear items | Output tokens/item | Cost/run |
|---|---|---|---|---|---|
| `v1_role`, batch 20 (control) | 97.7 / 96.5 / 98.9 % | 97.7 % | 98.3 % | 16.4 | $0.00107 |
| `v2_compact`, batch 20 | 95.4 / 95.4 / 96.5 % | 95.8 % | 98.7 % | 8.4 | $0.00065 (-39 %) |
| `v2_compact`, batch 40 | 97.7 / 95.4 / 97.7 % | 96.9 % | 98.7 % | 8.9 | $0.00058 (-46 %) |

Findings:

- Output tokens halved as expected; cost fell 39-46 %. DeepSeek served ~2/3 of input tokens from
  its prompt cache in every variant.
- On clear items the variants are equal; the overall gap comes from ambiguous items (baked beans,
  protein mousse, marinated chicken), within run-to-run noise (the control itself moved from a
  99.2 % mean earlier to 97.7 % now).
- Correction: a plant-based coconut yogurt classified as dairy (once, `v2_compact`) only hides
  it from vegans (over-restrictive), it is not dangerous. The diet-severity metric added
  afterwards found the real risk: `v2_compact` classified marinated chicken as "prepared" in 2
  of 6 runs, which would let a vegetarian get meat; `v1_role` never did.
- Absolute savings are tiny at today's volume (~$0.0005 per 87 products).

Decision: keep `v1_role` as the default for now (quality and diet safety over a negligible
saving); revisit `v2_compact` when volumes grow, with a larger dataset that has more diet traps.

## Diet-severity metric (added after the second experiment, rescored for free)

| Prompt | Unsafe diet errors over 6 runs |
|---|---|
| `v1_role` | protein mousse (dairy) -> other: 3 |
| `v2_compact` | protein mousse -> other: 5; marinated chicken (meat) -> prepared: 2 |
| rules only (1 run) | 17 |

Note: categories `prepared` and `other` exclude nothing for any diet, so a meat-containing ready
meal is only caught by its declared allergens or by the `diet_uncertain` flag. Unsafe errors into
those two categories are the ones to watch.

## Weekly planner

```bash
uv run python -m annona_server.evals plan-run [--variety basic|balanced|high] --yes
uv run python -m annona_server.evals plan-show <file> [--scenario id]
uv run python -m annona_server.evals plan-rate <file> <scenario> <1-5> [--note "..."]
uv run python -m annona_server.evals plan-judge <file> --yes     # LLM judge + agreement
uv run python -m annona_server.evals plan-compare
```

Four scenarios (`evals/datasets/plan_scenarios.json`): one active man for a full week, the
owner's 5-day example, a vegetarian woman cutting, and a couple where one is allergic to milk.

Hard checks come from the verifier (schedule, ingredients, kitchen, allergies, protein, stock).
Metrics: accepted, accepted at first try, issue codes before/after the repair, distinct dish
titles, ingredient multipliers (how far the model's portions were), share of the purchase used,
extra packs bought, tokens, cost and latency. Whether people *want* to eat it is rated by a
human (1-5); an LLM judge is only trusted as far as it agrees with those ratings.

### Iterations (2026-11-21, `deepseek-v4-pro`, one run per scenario)

| Run | Change | Accepted |
|---|---|---|
| 1 | first version: one portion factor per day, 0.5x-2x | 0/4 (portions 2-2.6x too small; stock overdrawn) |
| 2 | linear programme per ingredient (0.5x-3x) | 1/4 |
| 3 | approximate kcal per serving in the prompt | 2/4 |
| 4 | buy one more pack for small stock shortfalls | 3/4 (2 thanks to extra packs) |
| 4b | same, `--variety balanced` | 1/4 (drafts still short of energy) |

Lessons: the model drafts "ordinary" portions for people needing 1900-3400 kcal, so exact
portions must come from code; the cheapest shop (7 products) makes menus valid but monotonous,
hence the optional variety levels; and one run per scenario is too noisy to compare variants
reliably (repeat runs before deciding).
