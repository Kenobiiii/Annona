# Recorded provider fixtures

Real HTTP exchanges recorded on 2026-11-19 with `scripts/record_provider_fixtures.py` and replayed
by `FixtureTransport` so CI never touches the network. Kept small on purpose (price listings are
trimmed to 5 items).

- `open_prices/`: data from Open Prices by Open Food Facts contributors, licensed under the
  [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
- `mercadona/`: a handful of responses from Mercadona's online shop (postcode 28001, one search,
  one product, one not-found), recorded under the opt-in, personal-use plugin policy. Mercadona
  owns this data; it is included only as a minimal test fixture.
- `open_prices_uk/`: Tesco (United Kingdom, GBP) from Open Prices, recorded on 2026-11-22 with
  `scripts/record_provider_fixtures.py open_prices_uk` (same ODbL 1.0 licence). Used to prove the
  plugin API works for another country and currency. Note: Open Prices is crowdsourced and can hold
  outliers (one recorded price is 90 GBP for a tin of tomatoes); treat prices as hints.
