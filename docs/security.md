# Security

Annona is a single-user, self-hosted service. This page is the review checklist for v0.1.0, what was
found, and the risks that remain.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability. Use GitHub's private "Report a vulnerability"
(Security tab) on the repository, or contact the maintainer privately. Never include real tokens or
keys in reports.

## Checklist (v0.1.0)

| Area | Check | Result |
|---|---|---|
| Secrets | No keys, tokens or keystores in files or git history (scanned) | OK |
| Secrets | `.env`, `data/`, receipt photos are git-ignored; `.env.example` has only empty values | OK |
| Secrets | App AI keys live only in the server's `.env`; the app stores just the server token (SecureStore) | OK |
| Auth | Every `/api/v1` route and `/mcp` need `Authorization: Bearer <token>`; constant-time comparison | OK |
| Auth | Server refuses requests (503) when no token is configured | OK |
| Auth | Failed attempts limited: 10 per minute per address, then 429 (REST and MCP share the limit) | OK |
| Auth | Weak token (< 24 chars) logs a warning at start-up | OK |
| HTTP | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` on all responses | OK |
| HTTP | CORS only for origins listed in `ANNONA_CORS_ORIGINS` (none by default) | OK |
| LLM | Writes proposed by the chat agent need an explicit confirmation by the user over REST | OK |
| LLM | Product/receipt text is data, never instructions (prompt-injection safe by structure) | OK, evaluated |
| Data | Pantry, receipts and profile stay on your server; no telemetry | OK |
| Deps | `pip-audit` (Python) and `npm audit --audit-level=high` (app) run in CI | OK, see below |
| Containers | Image built from the repo; data in a volume | Not hardened further |

## Accepted risks

- **filelock CVEs (13).** Fixed upstream only in filelock 4.x, but LiteLLM (pinned) requires
  `filelock<4.0`. They need a local attacker with write access to the lock directory (or Windows).
  Listed one by one, with reasons, in `security/pip-audit-ignore.txt`; revisit when LiteLLM updates.
- **npm moderate advisories (20)** in the app's build/test toolchain, none high or critical; the
  packaged app does not run that tooling.
- **Plain HTTP on a trusted network.** The app allows cleartext HTTP so it works with a LAN address.
  On an untrusted network the token can be read: use [remote-access.md](remote-access.md).
- **In-memory throttle.** It resets on restart and, behind a reverse proxy, is shared by all clients
  (the server sees the proxy's address).
- **One token, one user.** There are no accounts or roles; whoever holds the token can do everything.

## Your responsibilities

Choose a long random token; do not expose the server to the Internet without HTTPS; keep the system
and the image updated; keep your keystore and `.env` private; back up the database.
