# Recorded provider fixtures

Real HTTP exchanges recorded on 2026-11-19 with `scripts/record_provider_fixtures.py` and replayed
by `FixtureTransport` so CI never touches the network. Kept small on purpose (price listings are
trimmed to 5 items).

- `open_prices/`: data from Open Prices by Open Food Facts contributors, licensed under the
  [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
- `mercadona/`: a handful of responses from Mercadona's online shop (postcode 28001, one search,
  one product, one not-found), recorded under the opt-in, personal-use plugin policy. Mercadona
  owns this data; it is included only as a minimal test fixture.
