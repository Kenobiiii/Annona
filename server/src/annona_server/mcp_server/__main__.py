# SPDX-License-Identifier: AGPL-3.0-or-later
"""stdio MCP server: ``python -m annona_server.mcp_server`` (Claude Code, Claude Desktop, ...).

Uses the same database as the API (``ANNONA_DATABASE_URL``). Logs go to stderr; stdout is the
MCP channel.
"""

from ..config import load_env
from ..db import migrate
from ..db.engine import database_url, make_engine
from . import build_server


def main() -> None:
    load_env()
    url = database_url()
    migrate.exit_if_outdated(url)  # an AI client starts this: never migrate here
    build_server(make_engine(url)).run("stdio")


if __name__ == "__main__":
    main()
