# Self-hosting

Annona runs on your own machine or server; your pantry, profile and plans never leave it (except
what is sent to the AI provider you configure).

## With Docker (recommended)

Requirements: Docker with Compose v2 (Docker Desktop on Windows/macOS, Docker Engine on Linux).

```bash
git clone https://github.com/Kenobiiii/Annona.git && cd Annona
cp .env.example .env
# edit .env: set ANNONA_API_TOKEN (a long random secret) and your AI key (e.g. DEEPSEEK_API_KEY)
docker compose up -d
```

- API and interactive documentation: <http://localhost:8000/docs> (click **Authorize** and paste
  your token).
- Data lives in the `annona-data` Docker volume (`/data/annona.db` in the container).
- Two services: `api` (the REST API) and `scheduler` (daily price refresh at
  `ANNONA_REFRESH_AT`, default 04:30 UTC; configure `ANNONA_REFRESH_PROVIDERS`).
- Update: `git pull && docker compose up -d --build`.
- Logs: `docker compose logs -f`.

## Without Docker

```bash
uv sync
uv run python -m annona_server.api --host 0.0.0.0 --port 8000
uv run python -m annona_server.scheduler        # in another terminal (or --once)
```

## Phone access on your home network

The Android app (Phase 10) talks to `http://<your-computer-IP>:8000` with the token. Keep the
server on your local network for now; exposing it to the Internet needs HTTPS and is covered
later (Phase 15).

## First steps through the API

1. `PUT /api/v1/household` - name, weekly budget, currency.
2. `POST /api/v1/profiles` - each member (confirm allergies!).
3. `PUT /api/v1/equipment` - your kitchen.
4. Load products and prices (`python -m annona_server.ingest ...` or `POST /api/v1/prices/refresh`).
5. `POST /api/v1/plans` - generate the week; poll the returned job.
