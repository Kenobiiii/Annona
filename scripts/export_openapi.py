# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write the REST API's OpenAPI schema for the app's typed client.

Usage: uv run python scripts/export_openapi.py            # rewrite app/src/api/openapi.json
       uv run python scripts/export_openapi.py --check    # exit 1 if the file is stale
"""

import argparse
import json
import sys
from pathlib import Path

from sqlmodel import create_engine

from annona_server.api import create_app

TARGET = Path(__file__).resolve().parent.parent / "app" / "src" / "api" / "openapi.json"


def current_schema() -> str:
    app = create_app(engine=create_engine("sqlite://"), token="schema-only")
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = current_schema()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != schema:
            sys.exit(f"{TARGET} is stale: run `uv run python scripts/export_openapi.py`")
        return
    TARGET.write_text(schema, encoding="utf-8")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
