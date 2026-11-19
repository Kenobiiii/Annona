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
- One safety-relevant error appeared only with `v2_compact` (1 of 6 runs): a plant-based coconut
  yogurt classified as dairy, which matters for vegan diets.
- Absolute savings are tiny at today's volume (~$0.0005 per 87 products).

Decision: keep `v1_role` as the default for now (quality and diet safety over a negligible
saving); revisit `v2_compact` when volumes grow, with a larger dataset that has more diet traps.
