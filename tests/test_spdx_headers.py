# SPDX-License-Identifier: AGPL-3.0-or-later
"""Repository policy: every source file starts with an SPDX licence identifier.

See CONTRIBUTING.md ("Licence headers").
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPDX_LINE = "SPDX-License-Identifier: AGPL-3.0-or-later"
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    ".expo",
    "build",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "android",
    "ios",
}
# Generated/config files from third-party templates are exempt. schema.d.ts is rewritten by
# `npm run gen:api` (openapi-typescript), so a header could not survive regeneration.
SKIP_FILES = {"expo-env.d.ts", "schema.d.ts"}
HEADER_LINES = 3  # allow a shebang or "use client"-style line before the header


def _source_files() -> list[Path]:
    files = []
    for path in REPO_ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.is_file() and path.suffix in SOURCE_SUFFIXES and path.name not in SKIP_FILES:
            files.append(path)
    return files


def test_source_files_exist() -> None:
    assert _source_files(), "expected at least one source file to check"


def test_every_source_file_has_spdx_header() -> None:
    missing = []
    for path in _source_files():
        head = path.read_text(encoding="utf-8").splitlines()[:HEADER_LINES]
        if not any(SPDX_LINE in line for line in head):
            missing.append(str(path.relative_to(REPO_ROOT)))
    assert not missing, f"missing SPDX header in: {missing}"
