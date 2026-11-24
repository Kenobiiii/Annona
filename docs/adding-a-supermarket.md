# Adding a supermarket

Each store is a plugin: a Python package that implements `SupermarketProvider`
(`providers/src/annona_providers/base.py`) and registers itself under the `annona.providers`
entry-point group. The core never imports a specific store.

## 1. Research first (before any code)

1. Read the store's `robots.txt` and terms of use.
2. Look for an official or public API. Prefer documented, open sources.
3. Decide the plugin's policy:
   - **Normal plugin**: everything it requests is allowed by `robots.txt`.
   - **Opt-in, personal-use plugin** (the only allowed exception, see CLAUDE.md): disabled by
     default, `opt_in=True` with a `notice` the user must accept, acts only on explicit user
     requests for a few items, limits items per call, and `iter_catalog()` raises
     `CatalogNotSupportedError`. Never download a whole catalogue.

## 2. Start from the template

```bash
cp -r providers/_template ../annona-provider-mystore
```

Rename the package, the class and the entry point (its name must equal `info.id`).

## 3. Implement the interface

| Member | Returns |
|---|---|
| `info` | `ProviderInfo`: id, name, country, currency, `opt_in`, `notice`, `attribution` |
| `store_id` | id stored on products/prices (`info.id` plus an optional variant) |
| `search(query, limit)` | `ProviderProduct` list |
| `get_product(sku)` | `ProviderProduct` or `None` if it does not exist |
| `get_prices(skus)` | `ProviderPrice` list (integer cents, ISO currency, aware `observed_at`) |
| `iter_catalog()` | iterator of products, or raise `CatalogNotSupportedError` |
| `close()` | release the HTTP client |

Rules:

- Make every request through `PoliteTransport`: it sets the User-Agent, checks `robots.txt`,
  waits between requests and caches. Only opt-in plugins may pass `robots_exception=True`.
- Money: convert with `euros_to_cents(Decimal(str(value)))`; never keep floats.
- Never guess: if a package size or price is ambiguous, leave it `None`. Cross-check with the
  store's own reference price when possible (see the Mercadona plugin).
- Accept a `transport` argument so tests can replay fixtures.

## 4. Test with the shared contract

Subclass `annona_providers.testing.ProviderContract` and provide a `provider` fixture built on
`FixtureTransport`. Record fixtures once with `RecordingTransport`
(see `scripts/record_provider_fixtures.py`), review them, keep them small, and commit them.
CI never touches the network. Mark live tests with `@pytest.mark.live`; they run only with:

```bash
uv run pytest --live
```

## Built-in providers

| id | Source | Policy | Notes |
|---|---|---|---|
| `open_prices` | [Open Prices](https://prices.openfoodfacts.org) (Open Food Facts) | normal | Crowdsourced, ODbL 1.0 (credit the source). Follows one brand's locations in one country. Coverage can be sparse or old (Nov 2026: 56 Mercadona stores in Spain with prices, few items each). |
| `mercadona` | Mercadona online shop, via [mercapy](https://github.com/jtayped/mercapy) (MIT) | **opt-in** | Its `robots.txt` disallows `/api`. Needs a postcode (prices vary by warehouse), max 50 products per call, 2 s between requests, no catalogue downloads. From the app: notice accepted and postal code saved per household (Settings > Stores), one search per press, cached a day ([receipts.md](receipts.md)). |

## Spanish stores reviewed (robots.txt, 2026-11-19)

Dia, Alcampo and Eroski disallow everything; Consum disallows `/api/`; Carrefour allows product
pages but blocks automated clients; Lidl allows product pages but sells little food online.


## Worked example: a store in another country and currency (Tesco, UK)

The Open Prices plugin is generic (brand + country + currency), so a store of any country with
volunteer-recorded prices needs **no new code**:

```bash
uv run python -m annona_server.ingest open_prices --brand Tesco --country "United Kingdom" \
    --currency GBP --catalog --limit 200
```

It is tested with recorded real data (`providers/tests/fixtures/open_prices_uk/`, the full provider
contract) and proved something the Spanish stores could not: **one provider instance follows one
brand in one country and currency**, so `info` is per instance (adding this store exposed that the
class-level currency said EUR for every instance).

Currency rules, so amounts are never mixed:

- a household has one currency (Settings); only products priced in it are offered to the optimiser,
  the shopping list and the store comparison. A store in another currency is simply not offered
  (the API says "no products priced in EUR for store ...");
- to plan with Tesco, set the household currency to GBP.

Open Prices is crowdsourced: coverage is sparse and outliers exist (a recorded Tesco price is 90 GBP
for a tin of tomatoes). Treat its prices as hints and keep your own data fresh with receipts.

If you need a real-time, complete catalogue, write a provider over the store's **official** API
(preferred) following the contract above.
