# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke test: the package is installed and importable."""

import annona_providers


def test_package_exposes_version() -> None:
    assert annona_providers.__version__ == "0.0.0"
