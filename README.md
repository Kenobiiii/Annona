# Annona

**An open-source, self-hosted weekly meal planner that starts from your budget, real supermarket
prices and what you actually have at home — not from a recipe database.**

> **Status: pre-alpha (Phase 14 — chat agent).** Nothing usable yet. Follow the project to see it grow.

## Vision

Annona builds a weekly meal plan from:

1. your **weekly budget**,
2. **real supermarket prices** (each store is a plugin — anyone can add one),
3. what you **buy and keep in your pantry** (scan your receipts),
4. your **goal** (cut / maintain / bulk) and
5. your **physical activity**.

It ships as an **Android app** talking to a **backend you host yourself**. Any AI provider can power
it, and any MCP-capable AI client can drive it.

Design principles:

- **Deterministic core, AI at the edges.** Calories, macros, money, quantities and the shopping
  optimiser are plain, unit-tested code. Language models are only used for language and vision
  tasks (classifying products, reading receipts, writing recipes, chatting), and every number they
  produce is validated and recomputed.
- **Provider-agnostic AI.** Bring your own provider and key; cheap models by default.
- **Pluggable supermarkets.** The core knows nothing about any specific store.
- **Privacy.** Your pantry, receipts and profile stay on your server. No telemetry.

See [docs/architecture.md](docs/architecture.md) for the technical overview.

## Repository layout

| Path         | What                                                              |
|--------------|-------------------------------------------------------------------|
| `core/`      | Python library: domain, nutrition targets, optimiser. No I/O.     |
| `providers/` | Supermarket plugin interface, registry and plugins.               |
| `server/`    | FastAPI REST API + MCP server, SQLite, Docker.                    |
| `app/`       | Expo (React Native, TypeScript) Android app.                      |
| `docs/`      | Architecture and contributor guides.                              |

## Development quick start

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you) and, for the app,
Node.js (current LTS).

```bash
uv sync                  # create .venv with all workspace packages + dev tools
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pytest            # tests
uv run python -m annona_server.seed   # create ./data/annona.db and load sample foods

cd app && npm ci         # app dependencies
npm run lint && npm run typecheck && npm test
```

Copy `.env.example` to `.env` for local configuration. Never commit `.env`.

## Run your own server

```bash
cp .env.example .env    # set ANNONA_API_TOKEN and your AI key
docker compose up -d    # API + docs at http://localhost:8000/docs
```

See [docs/self-hosting.md](docs/self-hosting.md).

## Use it from Claude, Gemini and other AI assistants

Annona is an MCP server (`uv run python -m annona_server.mcp_server`, or `/mcp` on the API).
See [docs/mcp.md](docs/mcp.md).

## Disclaimers

- **Not medical advice.** Nutrition targets and meal plans are informational estimates. Consult a
  qualified professional before changing your diet, especially if you have a medical condition,
  are pregnant, or have a history of eating disorders.
- **Supermarket data.** Store integrations are optional plugins. They try to be polite (respect
  `robots.txt`, rate-limit, identify themselves, cache aggressively), but **you are responsible for
  complying with each store's terms of service** and local law when you enable one. The project is
  not affiliated with any supermarket.
- Prices and nutrition values may be outdated or estimated; estimated values are always flagged.
- **Mercadona plugin (opt-in).** Mercadona has no public API and its `robots.txt` disallows the
  endpoints the plugin uses. It is disabled by default; enabling it means accepting a notice that
  you use it for your own, personal requests and are responsible for complying with its terms.
  It never downloads the whole catalogue. See [adding-a-supermarket.md](docs/adding-a-supermarket.md).
- Crowdsourced prices from [Open Prices](https://prices.openfoodfacts.org) (Open Food Facts
  contributors) are used under the ODbL 1.0 licence.
- Bundled sample nutrition data comes from USDA FoodData Central (public domain).

## Contributing

Want to add a supermarket? Start with [docs/adding-a-supermarket.md](docs/adding-a-supermarket.md).

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) (commits need a DCO sign-off)
and our [Code of Conduct](CODE_OF_CONDUCT.md).

## Licence

[GNU Affero General Public License v3.0 or later](LICENSE) (`AGPL-3.0-or-later`).
If you run a modified version as a network service, you must offer its source to its users.
