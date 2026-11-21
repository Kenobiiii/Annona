# Architecture

A contributor-oriented summary of how Annona is built. The authoritative project brief is
[`CLAUDE.md`](../CLAUDE.md).

## What it does

Annona turns **budget + real supermarket prices + pantry + goal + activity** into a weekly purchase
list and meal plan, then helps you cook it (recipe of the day), shop for it and keep the pantry up
to date (receipt scanning).

## Principles

1. **Deterministic core, AI at the edges.** Calories, macros, money, quantities and optimisation
   are plain, unit-tested Python. LLMs only do language/vision work.
2. **Verify LLM output.** Data-bearing LLM answers are strict JSON validated against Pydantic
   schemas; numbers are recomputed by code. Invalid output gets one repair retry, then a clear error.
3. **Provider-agnostic AI.** A single `LLMClient` interface (LiteLLM underneath) with two
   configurable tiers: `small` (classification, receipts, chat) and `large` (weekly plan, recipes).
   Responses are cached by input hash and token usage is logged.
4. **Cost-conscious.** The weekly plan is generated once and stored; prompts only carry the context
   they need.
5. **Pluggable supermarkets.** Each store is a plugin returning the common `Product`/`Price` types.
6. **One tool registry.** Features exposed to AI are defined once and served both to the in-app chat
   agent and to the MCP server.
7. **Privacy.** Everything stays on the user's server. No telemetry.

## Components

```
                 ┌──────────────────────────────┐
                 │  app/  (Expo, Android)       │
                 │  drawer UI, camera, chat     │
                 └──────────────┬───────────────┘
                                │ REST (token auth)
   MCP clients ───────────┐     │
   (desktop / web)        ▼     ▼
                 ┌──────────────────────────────┐
                 │  server/  FastAPI + MCP      │
                 │  SQLite (SQLModel/Alembic)   │
                 │  tool registry, LLM adapter  │
                 └───────┬──────────────┬───────┘
                         │              │
              ┌──────────▼───┐   ┌──────▼────────────┐
              │ core/        │   │ providers/        │
              │ domain,      │   │ SupermarketProvider│
              │ nutrition,   │   │ interface, registry│
              │ optimiser    │   │ store plugins      │
              │ (no I/O)     │   └────────────────────┘
              └──────────────┘
```

| Package      | Distribution       | Import name        | Depends on            |
|--------------|--------------------|--------------------|-----------------------|
| `core/`      | `annona-core`      | `annona_core`      | —                     |
| `providers/` | `annona-providers` | `annona_providers` | core                  |
| `server/`    | `annona-server`    | `annona_server`    | core, providers       |
| `app/`       | `annona-app` (npm) | —                  | server (over HTTP)    |

`core` must stay free of network, disk and database access so it can be tested exhaustively.
It declares repository *interfaces*; the SQLite implementation (SQLModel + Alembic) lives in
`server/annona_server/db/`.

## Key technical choices

- **Python 3.12**, `uv` workspace, `ruff` (lint + format), `pytest` (warnings are errors).
- **Optimiser:** mixed-integer programming with `scipy.optimize.milp` (HiGHS); integer pack counts,
  minimise cost subject to nutrition ranges, budget and variety constraints. See [optimizer.md](optimizer.md).
- **Nutrition targets:** Mifflin-St Jeor BMR × activity factor, adjusted by goal; protein in g/kg.
  All defaults configurable and documented with sources in [nutrition.md](nutrition.md).
- **Nutrition data:** Open Food Facts by barcode; otherwise an LLM estimate flagged `estimated`.
- **Money** is never a float (integer cents or `Decimal`). Units are normalised to g, ml or unit.
- **Cooking equipment:** no hob-power lookups by model. A user equipment profile plus a one-time
  calibration adapts cooking times; recipes speak in low/medium/high heat.
- **App:** Expo + TypeScript, expo-router (drawer), expo-camera, expo-secure-store, TanStack Query;
  `eslint`, `tsc`, `jest`.
- **CI:** GitHub Actions runs lint, format check and tests for Python and the app.

## AI layer

`annona_core.llm` defines a provider-agnostic `LLMClient` (tiers `small`/`large`, JSON answers
validated with Pydantic and one repair attempt, caching and usage hooks, `FakeLLM` for tests).
`annona_server.llm` wires it to LiteLLM (the only module importing it, pinned exact version), a
database response cache and a usage log with tokens and cost. Quality is measured with evals:
see [evals.md](evals.md).

## Weekly planner

The LLM drafts meals; code verifies them and computes exact portions with a linear
programme. See [planner.md](planner.md).

## REST API

FastAPI under `/api/v1` with a bearer token; slow operations (plan generation, price
refresh) are background jobs polled at `/api/v1/jobs/{id}`; a separate scheduler process
refreshes prices daily. See [self-hosting.md](self-hosting.md) and the live docs at `/docs`.

## Domain model

A `Household` owns the shared things (budget, pantry, kitchen, plans, shopping lists, receipts) and
has one or more `UserProfile` members. See [data-model.md](data-model.md) for entities, relations
and rules.

## Legal and safety

- Scrapers are optional plugins: respect `robots.txt` and rate limits, identify the client, cache.
  Users are responsible for each store's terms.
- Nutrition output is informational, not medical advice.
- Licence: AGPL-3.0-or-later; every source file carries an SPDX header.
