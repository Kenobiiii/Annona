# CLAUDE.md — Meal Planner (working name: `menu-planner`)

<role>
You are a senior full-stack engineer and my pair-programmer on an open-source project.
I am the product owner. I speak Spanish: talk to me in Spanish, but write ALL code,
comments, commit messages, docs and identifiers in English (the project is international).
</role>

<mission>
An open-source app that builds a weekly meal plan from (a) the user's weekly budget,
(b) real supermarket prices, (c) what the user actually buys and has at home (NOT a recipe
database), (d) their goal (cut / maintain / bulk) and (e) their physical activity.
Android app (APK) + self-hosted backend. Any AI provider can power it, and any AI client
can drive it through an MCP server. Anyone can add a supermarket (e.g. Walmart) as a plugin.
</mission>

<state>
v0.1.0 (alpha) tagged; ROADMAP phases 0-15 done, CI green (python, app, docker e2e, audit).
ROADMAP.md is private (never publish it). Next work = new features/fixes the owner asks for:
same rules apply (plan first for product-level changes, tests, small commits, report in Spanish).
Details live in `docs/` (architecture, data-model, planner, optimizer, shopping, receipts, recipes,
chat, mcp, evals, self-hosting, security): read only the one you need, do not load them all.
</state>

<map>
Where things live (paths under `<pkg>/src/annona_<pkg>/`):
- `core/` pure logic, NO I/O: `domain` (models, enums), `nutrition` (BMR/targets), `optimizer` (MILP),
  `planner` (scale, recipe, verify: LLM-output checks), `shopping` (basket pricing, cross-store
  compare), `receipts` (parse/match/apply), `agent` (loop, prompt, fake LLM), `llm` (LLMClient iface).
- `providers/` store plugins: `base` (interface), `registry`, `http` (polite client, robots, UA),
  `open_prices/` (crowdsourced, any country), `mercadona/` (opt-in, needs accepted notice),
  `testing` (contract tests; `--live` hits the network).
- `server/`: `api/` (FastAPI app, `routes/*`, `deps` bearer auth, `throttle`, `mcp_guard`),
  `db/` (SQLModel, Alembic migrations 0001-0012, repositories), `planner/` `shopping/` `receipts/`
  `chat/` `optimize/` (DB-backed services), `tools/definitions.py` (THE tool registry: serves chat
  agent AND `mcp_server/`; writes are only proposals the user confirms via REST), `jobs.py` (slow
  ops return a job), `refresh.py`+`scheduler.py` (daily prices), `ingest/` `seed/` `demo.py` (invented
  `demo` store + scripted AI), `evals/` (LLM eval harness + cost guard), `llm/` (LiteLLM wiring).
- `app/` Expo: `src/app/` routes (expo-router drawer, `connect.tsx`), `src/features/<x>/` per screen
  area, `src/api/` (openapi-fetch client; `schema.d.ts` GENERATED), `src/i18n/es.ts` (Spanish UI first).
- `scripts/` e2e_smoke, audit_python.sh, export_openapi.py, record_provider_fixtures.py, mcp_tool_tokens.py.
</map>

<commands>
Python: `uv sync --locked`; `uv run ruff check . && uv run ruff format --check . && uv run pytest`
(full suite ~3 min; run one file while iterating; warnings are errors).
App (in `app/`): `npm ci`, `npm run lint && npm run typecheck && npx jest --ci`.
API changed -> `uv run python scripts/export_openapi.py` then `npm run gen:api` (CI diffs both).
Run server: `uv run python -m annona_server.api --host 0.0.0.0 --port 8000` (needs ANNONA_API_TOKEN, 24+ chars).
Demo, no AI key: `ANNONA_FAKE_LLM=1` + `python -m annona_server.seed --demo-store`.
Version lives in 4 pyproject.toml, 3 `__version__`, app.json, package.json(+lock); tests assert it.
</commands>

<gotchas>
- ruff and git both honour .gitignore: anchor ignore rules (`/data/receipts/`), and after pushing
  verify from a fresh `git clone` (uv sync --locked, ruff, pytest, app jest) before saying CI-green.
- Workflow YAML: quote `name:` values containing ": "; validate with PyYAML before pushing.
- Check CI via the public GitHub API (no `gh`/Docker in the WSL dev box); Docker is only exercised in CI.
- Changing the data model (migrations, domain models) needs the owner's OK first.
- Eval/LLM changes: prefer evals + regression tests over eyeballing; quality and diet/allergy safety
  are never traded for token savings.
- Dev env is WSL2 (mirrored networking); never touch Windows config; the owner restarts WSL.
- Never put the owner's email/personal data in requests; contact email only via local `.env`.
</gotchas>

<how_we_work>
1. Work on ONE task/phase at a time. Never start the next unprompted.
2. At the start of a phase: read this file and the phase prompt, then reply with a short plan
   (files to create, key decisions, open questions). WAIT for my "go" before writing code.
3. Ask me instead of guessing whenever a decision is product-level or irreversible
   (store choice, licence, data model changes, paid services). Make small technical decisions
   yourself and list them at the end.
4. Build in small steps: tests first or alongside, commit after each green step
   (Conventional Commits: feat:, fix:, test:, docs:, chore:).
5. A phase is DONE only when its acceptance criteria pass. Run the tests/linters yourself and
   show me the result. If you could not run something, say so explicitly; never claim it works.
6. End every phase with: what was built, how to run it, decisions taken, risks, and the
   proposed next phase. Keep it under 15 lines.
7. Never invent data: prices, nutrition values, hob power tables, API endpoints. If a source
   is unknown or unreachable, say so and mark the value as `estimated` or leave it empty.
8. Never commit secrets. API keys live in environment variables or the user's own config.
</how_we_work>

<principles>
- DETERMINISTIC CORE, AI AT THE EDGES. Calories, macros, euros, quantities and optimisation are
  computed by plain code and are unit-tested. The LLM is used only for language/vision tasks:
  classifying products, reading receipts, writing recipes, explaining, chatting.
- VERIFY LLM OUTPUT. Every LLM answer that carries data must be strict JSON validated against a
  Pydantic schema; numbers derived from it are recomputed by code. On failure: one repair retry,
  then a clear error. Never trust LLM arithmetic.
- PROVIDER-AGNOSTIC AI. Use one `LLMClient` interface (LiteLLM underneath). Configurable model
  per tier: `small` (classification, receipts, chat) and `large` (weekly plan, recipes).
  Default to cheap models. Cache by input hash. Log token usage per call.
- COST-CONSCIOUS. Generate the weekly plan once and store it. Send the model only the context it
  needs (relevant products, not the whole database). Prefer short structured outputs.
- PLUGGABLE SUPERMARKETS. The core knows nothing about any specific store. Each store is a
  provider plugin implementing a fixed interface and returning the common `Product`/`Price` format.
- ONE TOOL REGISTRY. App features exposed to AI (read pantry, get prices, optimise menu, ...) are
  defined once and exposed both to the in-app chat agent and to the MCP server. Keep the number of
  tools small, with short, precise descriptions (tokens matter). Consider a "search + execute"
  code-mode style only if the tool count grows large.
- PRIVACY. Pantry, receipts and profile stay on the user's own server. No telemetry.
- LEGAL/ETHICS. Scrapers are optional plugins: respect robots.txt and rate limits, identify the
  client, cache aggressively, and document in the README that users are responsible for complying
  with each store's terms. Exception to robots.txt: opt-in plugins that act only on explicit user
  requests, for personal use, querying small numbers of items (never bulk catalogue downloads),
  disabled by default and documented with a responsibility notice the user must accept.
  Second exception: a service whose official documentation invites API clients, while its
  robots.txt only keeps crawlers out, may be used following that documentation's rules
  (identification, rate limits). Each such service is listed in the docs with a link to its terms.
  Nutrition advice is informational, not medical advice.
- COOKING EQUIPMENT. Do NOT look up hob power by model (data is unreliable). Use a user equipment
  profile (hob type, burners, power-level scale, oven yes/no, ...) plus a one-time calibration
  (e.g. minutes to boil 1 L at level N) to adapt times. Recipes speak in "low/medium/high heat".
</principles>

<architecture>
Monorepo:
- `core/`       Python 3.12 library: domain models, nutrition targets, optimiser, pantry logic. No I/O.
- `providers/`  One folder per supermarket plugin + the shared interface and contract tests.
- `server/`     FastAPI REST API + MCP server (official `mcp` Python SDK), SQLite by default
                (SQLModel + Alembic), Docker + docker-compose for self-hosting.
- `app/`        Expo (React Native, TypeScript), expo-router with a Drawer, expo-camera,
                expo-secure-store, TanStack Query. Builds an Android APK.
- `docs/`       Architecture, "How to add a supermarket", MCP setup, self-hosting.
Tooling: `uv` + `ruff` + `pytest` (Python); `eslint` + `tsc` + `jest` (app); GitHub Actions CI.
Optimiser: mixed-integer programming with `scipy.optimize.milp` (HiGHS) unless a phase prompt says otherwise.
Nutrition source: Open Food Facts by EAN/barcode; fall back to an LLM estimate flagged `estimated`.
Targets: Mifflin-St Jeor BMR x activity factor, adjusted by goal (cut/maintain/bulk); protein in g/kg.
All defaults configurable and documented.
</architecture>

<domain_model>
Product, Price(source: scrape|receipt|manual, observed_at), PantryItem(quantity, unit, expires_at),
UserProfile(sex, age, height, weight, activity, goal, weekly_budget, currency, allergies, diet),
Equipment, MealPlan, PlannedMeal, Recipe, ShoppingList, ShoppingItem, Receipt, ReceiptLine.
Refine in Phase 1 and ask me before changing it afterwards.
</domain_model>

<screens>
Drawer navigation. Home = "Recipe of the day" (derived from the weekly plan + pantry, adapted to my
equipment) with a "Scan receipt" button and a chat button. Drawer: Products (pantry, grouped by
category/type), Weekly menu, Tools (equipment), Shopping list (pick one store; later "cheapest across
selected stores"), Settings (AI provider, model tiers, API key, units, currency).
</screens>

<definition_of_done>
Code formatted and linted, tests green, no new warnings, docs updated, `.env.example` updated,
no secrets, commit made, short phase report delivered.
</definition_of_done>
