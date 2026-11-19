# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from annona_providers.base import (
    NoticeNotAcceptedError,
    ProviderError,
    ProviderInfo,
    euros_to_cents,
)
from annona_providers.registry import available_providers, create_provider
from annona_providers.testing import FixtureTransport

from .conftest import FIXTURES


def test_built_in_providers_are_registered():
    infos = {i.id: i for i in available_providers()}
    assert set(infos) >= {"open_prices", "mercadona"}
    assert infos["mercadona"].opt_in and not infos["open_prices"].opt_in


def test_opt_in_provider_needs_accepted_notice():
    with pytest.raises(NoticeNotAcceptedError, match="robots.txt"):
        create_provider("mercadona", postal_code="28001")
    p = create_provider(
        "mercadona",
        accept_notice=True,
        postal_code="28001",
        transport=FixtureTransport(FIXTURES / "mercadona"),
    )
    assert p.store_id == "mercadona"


def test_unknown_provider():
    with pytest.raises(ProviderError, match="unknown provider"):
        create_provider("nope")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "Bad Id"},
        {"country": "esp"},
        {"currency": "euro"},
        {"opt_in": True, "notice": None},
    ],
)
def test_provider_info_validation(kwargs):
    base = {"id": "shop", "name": "Shop", "country": "ES", "currency": "EUR"}
    with pytest.raises(ValueError):
        ProviderInfo(**(base | kwargs))


@pytest.mark.parametrize(
    ("value", "cents"), [("1.85", 185), ("0.005", 1), ("4.98", 498), ("12.950", 1295), (2, 200)]
)
def test_euros_to_cents(value, cents):
    from decimal import Decimal

    assert euros_to_cents(Decimal(value) if isinstance(value, str) else value) == cents


def test_euros_to_cents_rejects_float():
    with pytest.raises(TypeError):
        euros_to_cents(1.85)
