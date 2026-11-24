# SPDX-License-Identifier: AGPL-3.0-or-later
"""``python -m annona_server.db upgrade|downgrade [revision]``"""

import argparse

from . import migrate
from .engine import database_url


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m annona_server.db")
    parser.add_argument("action", choices=["upgrade", "downgrade"])
    parser.add_argument("revision", nargs="?", help="default: head (upgrade) / base (downgrade)")
    args = parser.parse_args()
    url = database_url()
    if args.action == "upgrade" and args.revision in (None, "head"):
        backup = migrate.upgrade_with_backup(url)
        if backup:
            print(f"backup saved: {backup}")
    elif args.action == "upgrade":
        migrate.upgrade(url, args.revision)
    else:
        migrate.downgrade(url, args.revision or "base")
    print(f"{args.action} done: {url}")


if __name__ == "__main__":
    main()
