# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions follow SemVer (0.x: things may change).

## [0.1.0] - 2026-11-23

First alpha release.

### Added
- Core: nutrition targets (Mifflin-St Jeor, goals, protein g/kg), MILP optimiser, pantry logic,
  per-store basket pricing and cross-store comparison (cheapest basket, best split between two stores).
- Weekly planner with verified LLM output, recipes adapted to your equipment, meal swaps.
- Supermarket plugins: Open Prices (crowdsourced; Spain and a UK proof), Mercadona (opt-in), plus an
  invented `demo` store.
- Receipts: photo to products, aliases, pantry updates.
- Chat agent (writes are only proposals you confirm) and an MCP server sharing one tool registry.
- Android app (Expo): home, pantry, weekly menu, tools, shopping list with store comparison,
  receipts, chat, settings. Spanish UI.
- Self-hosting: Docker Compose, scheduler, demo mode (`ANNONA_FAKE_LLM=1`), end-to-end smoke test in CI.
- Security: bearer token, failed-attempt throttle (REST and MCP), security headers, weak-token
  warning, dependency audit in CI. See `docs/security.md`.
