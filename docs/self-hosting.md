# Self-hosting

Annona runs on your own machine or server; your pantry, profile and plans never leave it (except
what is sent to the AI provider you configure). This guide takes you from a fresh clone to a
generated weekly plan.

## 1. Start the server (Docker, recommended)

Requirements: Docker with Compose v2.

```bash
git clone https://github.com/Kenobiiii/Annona.git && cd Annona
cp .env.example .env
```

Edit `.env`:

- `ANNONA_API_TOKEN`: a long random secret (at least 24 characters; the server warns otherwise):
  `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
- **Either** demo mode: uncomment `ANNONA_FAKE_LLM=1` (no key needed), **or** real AI: set the key of
  your provider (e.g. `DEEPSEEK_API_KEY`) and, optionally, `ANNONA_LLM_MODEL_SMALL/LARGE`.

```bash
docker compose up -d
curl http://localhost:8000/health        # {"status":"ok","version":"0.1.0"}
```

- API and interactive documentation: <http://localhost:8000/docs> (**Authorize** with your token).
- Data lives in the `annona-data` Docker volume (`/data/annona.db`).
- Services: `api` and `scheduler` (daily price refresh at `ANNONA_REFRESH_AT`, default 04:30 UTC).
- Update: `git pull && docker compose up -d --build`. Only the server changes the database's
  structure (migrations), on start, and first saves a copy of the old file in
  `/data/backups/annona-<old migration>-<UTC time>.db`. Every other command (`ingest`, `products`,
  `optimize`, `planner`, the MCP server, the scheduler, evals) only checks the database is up to
  date and stops if not; `seed` also creates a brand-new database. To migrate without starting the
  server: `python -m annona_server.db upgrade` (same backup).
- Logs: `docker compose logs -f`.

Without Docker: `uv sync`, then `uv run python -m annona_server.api --host 0.0.0.0 --port 8000` and,
in another terminal, `uv run python -m annona_server.scheduler`.

## 2. Load products and prices

- **Just trying it:** `docker compose exec api /app/.venv/bin/python -m annona_server.seed --demo-store` loads the
  sample foods and an **invented** store called `demo` (made-up prices, for trying the app only).
- **Real data:** `docker compose exec api /app/.venv/bin/python -m annona_server.seed` loads the sample foods, then
  ingest a store with `python -m annona_server.ingest ...` (see [ingestion.md](ingestion.md)) and
  set `ANNONA_REFRESH_PROVIDERS` so prices stay fresh. Opt-in providers (e.g. Mercadona) need you to
  accept their notice; read [adding-a-supermarket.md](adding-a-supermarket.md).

## 3. Connect the app and plan

1. In the app enter `http://<server-address>:8000` and the token (Settings).
2. Set household (budget, currency), each member (confirm allergies!) and your equipment.
3. Generate the week. Over the API: `PUT /api/v1/household`, `POST /api/v1/profiles`,
   `POST /api/v1/plans`, then poll the returned job at `GET /api/v1/jobs/{id}`.

## Phone access

- Same network: `http://<computer-LAN-IP>:8000` (the app allows plain HTTP for this).
- Away from home: [remote-access.md](remote-access.md). Do not expose port 8000 directly to the
  Internet without HTTPS.

## Backups

Everything is in one SQLite file (these commands are untested by the maintainers; check the backup opens before relying on it). With the container running:

```bash
docker compose exec api /app/.venv/bin/python -c "import sqlite3; s=sqlite3.connect('/data/annona.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
docker compose cp api:/data/backup.db ./annona-backup.db
```

The server also keeps an automatic copy in `/data/backups/` each time an update migrates the
database; they are never deleted automatically, so remove old ones when you no longer need them.

Restore by copying a backup over `/data/annona.db` with the stack stopped. Receipt photos, if kept,
are under `/data/receipts/`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| App says the server does not accept the token | wrong token, or a typo in the address; after 10 wrong tokens in a minute the server answers 429: wait a minute |
| `503 not_configured` | `ANNONA_API_TOKEN` is empty |
| Plan says "not within budget" | the budget is too low for the prices loaded; check prices were ingested |
| Phone cannot reach the server | firewall, or a different network; try `curl http://<ip>:8000/health` from another device |
| AI errors | key missing or wrong for the chosen model; `GET /api/v1/settings/llm` shows what is configured |
