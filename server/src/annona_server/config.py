# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings from environment variables, optionally from a local ``.env`` (never committed)."""

from __future__ import annotations

import os
from functools import cache

from dotenv import load_dotenv


@cache
def load_env() -> None:
    """Load ``.env`` from the working directory once; real environment variables win."""
    load_dotenv(override=False)


def contact_email() -> str | None:
    """``ANNONA_CONTACT_EMAIL``: sent to services that ask API clients for a contact."""
    load_env()
    value = os.environ.get("ANNONA_CONTACT_EMAIL", "").strip()
    return value or None
