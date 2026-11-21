# SPDX-License-Identifier: AGPL-3.0-or-later
"""The app's committed OpenAPI schema must match the API (regenerate with the export script)."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_openapi.py"


def test_committed_openapi_schema_is_current():
    spec = importlib.util.spec_from_file_location("export_openapi", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.TARGET.exists(), "run: uv run python scripts/export_openapi.py"
    assert module.TARGET.read_text(encoding="utf-8") == module.current_schema(), (
        "app/src/api/openapi.json is stale: run `uv run python scripts/export_openapi.py` "
        "then `npm run gen:api` in app/"
    )
