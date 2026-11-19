# SPDX-License-Identifier: AGPL-3.0-or-later
"""Repository-wide pytest options."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        help="run tests that make real network requests (never in CI)",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: makes real network requests; needs --live")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live (real network)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
