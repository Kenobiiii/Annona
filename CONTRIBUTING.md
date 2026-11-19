# Contributing to Annona

Thanks for your interest! This document explains how to propose changes.

## Ground rules

- Be kind: this project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- Code, comments, identifiers, commit messages and docs are written in **English**.
- Read [docs/architecture.md](docs/architecture.md) before larger changes, and open an issue first
  to discuss anything that changes the data model, adds a dependency or touches a public interface.
- Never commit secrets (API keys, tokens, keystores). Configuration lives in `.env` (git-ignored);
  document new settings in `.env.example`.

## Development setup

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pytest
cd app && npm ci && npm run lint && npm run typecheck && npm test
```

A pull request is ready when lint, format check, type check and tests pass, docs are updated, and
there are no new warnings (pytest treats warnings as errors).

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `test:`,
`docs:`, `chore:`, `refactor:`, `ci:`. Keep commits small and focused.

## Developer Certificate of Origin (DCO)

Every commit must be signed off, certifying that you wrote the change or otherwise have the right to
submit it under the project licence, as described in the
[Developer Certificate of Origin 1.1](https://developercertificate.org/).

Add the sign-off with `git commit -s`, which appends:

```
Signed-off-by: Your Name <your.email@example.com>
```

The name and email must match the commit author. Forgot it? `git commit --amend -s` (last commit)
or `git rebase --signoff main` (whole branch).

## Licence headers (SPDX)

All contributions are licensed under **AGPL-3.0-or-later**. Every source file
(`.py`, `.ts`, `.tsx`, `.js`, `.jsx`) must start with an SPDX identifier within its first three lines:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
```

```ts
// SPDX-License-Identifier: AGPL-3.0-or-later
```

This is enforced by `tests/test_spdx_headers.py`. Third-party code copied into the repo keeps its
original SPDX identifier and must have an AGPL-compatible licence.

## Adding a supermarket

Each store is a plugin under `providers/`. A step-by-step guide (`docs/adding-a-supermarket.md`)
will land together with the provider interface.

## Reporting security issues

Please do **not** open a public issue. Email **ponsciber@gmail.com** with details and steps to
reproduce.
