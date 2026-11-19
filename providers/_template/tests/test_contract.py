# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every provider must pass the shared contract on recorded fixtures (no network in CI).

Record fixtures locally with ``annona_providers.testing.RecordingTransport``, review the files
(remove anything personal), commit them, then replay them with ``FixtureTransport``.
"""

from pathlib import Path

import pytest

from annona_provider_example import ExampleProvider
from annona_providers.testing import FixtureTransport, ProviderContract

FIXTURES = Path(__file__).parent / "fixtures" / "example"


class TestExampleContract(ProviderContract):
    search_query = "milk"  # TODO: a query that returns products
    known_sku = "123"  # TODO: a product id that exists in the fixtures
    unknown_sku = "does-not-exist"

    @pytest.fixture
    def provider(self):
        p = ExampleProvider(transport=FixtureTransport(FIXTURES))
        yield p
        p.close()
