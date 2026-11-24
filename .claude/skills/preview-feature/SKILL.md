---
name: preview-feature
description: Run or restart the Annona server and the app dev server so the owner can SEE a new feature on their phone, without breaking their real data, their running server or their local app.json. Use when a feature is ready to try, when the owner says "quiero verlo", "arranca el servidor", "reinicia", "pruébalo en el móvil", or after changing server/app code that needs a restart.
---

# Preview a feature safely

Owner's real data lives in `data/annona.db` and the real server runs on port 8000 with their `.env`.
Background processes of a previous chat do NOT carry over: check what is running before starting.

## 0. Look first (always)

```bash
pgrep -af "[a]nnona_server.api"; pgrep -af "[e]xpo start"; ip -4 addr | grep -o "inet 192\.168[0-9.]*"
git status --short
```

The LAN IP changes between days: always read it again and give the phone `http://<IP>:8000`.
Never print the token or the `.env`; tell the owner to copy it from `.env` if they need it.

## 1. Pick the mode

- **Preview (default, safest):** a COPY of the database on port 8001. The real server and data stay
  untouched; the owner can test the feature with their own data and break nothing.
  ```bash
  P=/tmp/annona-preview; mkdir -p $P && cp data/annona.db $P/annona.db
  (set -a && . ./.env && set +a && export ANNONA_DATABASE_URL=sqlite:///$P/annona.db \
    ANNONA_CORS_ORIGINS=http://localhost:8081 && \
    nohup uv run python -m annona_server.api --host 0.0.0.0 --port 8001 > $P/server.log 2>&1 &)
  ```
  The copy runs the new migrations; the real DB does not. It uses the real AI key, so AI actions
  cost money: say so, or add `ANNONA_FAKE_LLM=1` when the feature does not need a real model.
- **Real server (only when the owner asks to switch to the new version):**
  1. Back up first: `cp data/annona.db data/annona.db.bak-<feature-or-date>`.
  2. If new migrations exist (`ls server/src/annona_server/db/migrations/versions`), tell the owner
     they run on start and cannot be undone except by restoring that backup.
  3. Stop ONLY the server: `kill $(pgrep -f "[a]nnona_server.api")` (never `pkill -f`, it can kill
     your own shell).
  4. Start: `(set -a && . ./.env && set +a && nohup uv run python -m annona_server.api --host 0.0.0.0 --port 8000 > /tmp/annona-server.log 2>&1 &)`

Then verify: `curl -s localhost:<port>/health` and from the LAN IP. Report the exact address for the
phone, which port is the preview and which is real, and how to stop it.

## 2. The app: APK vs live preview

- The installed **APK is a fixed build**: UI changes do NOT appear in it until a new EAS build
  (`cd app && npx eas-cli build --platform android --profile preview`, the owner runs it; it needs
  their login). A feature that only adds server/API behaviour is visible in the APK only if the
  app already has the screen for it.
- To see UI changes now, use the dev server with Expo Go (same Wi-Fi):
  `cd app && REACT_NATIVE_PACKAGER_HOSTNAME=<IP> nohup npx expo start --lan --port 8081 < /dev/null > /tmp/expo.log 2>&1 &`
  Then in the app's connection screen use the preview server address (`:8001`) or the real one.
- Expo rewrites `app/tsconfig.json` when it starts: restore it with `git checkout app/tsconfig.json`.
- If the API changed: `uv run python scripts/export_openapi.py` then `cd app && npm run gen:api`.

## 3. Protect the owner's local files

- `app/app.json` has the owner's EAS `owner` and `extra.eas.projectId` as UNCOMMITTED local changes.
  Never `git add -A`, `git commit -a` or `git checkout app/app.json`. Stage files by name. If
  `app.json` must change, edit the committed version without those two fields (see
  `docs/releasing.md`), commit it, then put the local fields back.
- Never commit `.env`, `data/`, `*.db`, keystores or tokens.
- Do not touch Windows configuration or the owner's browser; the owner restarts WSL.

## 4. When done

Stop what you started (preview server on 8001, Expo on 8081) with `kill $(pgrep -f "[a]nnona_server.api --port 8001")` style patterns,
unless the owner wants it left running; if left running, say that a closed session may stop it.
Delete `/tmp/annona-preview` when the owner no longer needs the copy.
