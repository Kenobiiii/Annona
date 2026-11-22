# Catalogue and price ingestion

Code: `server/src/annona_server/ingest/`. Turns supermarket products and prices into database rows,
adds nutrition and allergens from Open Food Facts, and classifies products.

```bash
# Open data: a store brand's products and prices from Open Prices
uv run python -m annona_server.ingest open_prices --brand Mercadona --catalog --limit 200

# Mercadona (opt-in, personal use): only the products you name or search, max 50 per run
uv run python -m annona_server.ingest mercadona --postal-code 28001 --accept-notice \
    --sku 4740 --query "arroz redondo"
```

Automatic daily runs arrive with the Docker setup (Phase 8).

## What happens to each product

1. **Store facts** (name, brand, barcode, package size) come from the store.
2. **Nutrition and allergens** come from [Open Food Facts](https://world.openfoodfacts.org) (OFF)
   by barcode. Answers, including "not found", are cached for 30 days; OFF allows 15 reads per
   minute, so lookups are spaced 4 s apart. Set `ANNONA_CONTACT_EMAIL` in your `.env`: OFF asks
   API clients to identify themselves with a contact.
3. **Generic reference** for data no real source provides (see [optimizer.md](optimizer.md)):
   nutrition, unit weight and density of the USDA sample food of the same category and type,
   kept as `source: sample`. `python -m annona_server.products fill-sample` applies it to
   products already stored.
4. **Category and type** come from rules: the store's category path (deepest level first), OFF
   category tags, then keywords in the name. Unrecognised products are listed as `unclassified`
   (an LLM classifier arrives in Phase 5).
5. **Prices**: a new row is stored only when the price changed or was seen on a new day, so the
   table is a price history. Unit prices (per kg / l / unit) are computed, never stored.

Running the same ingestion twice changes nothing.

## Who wins when sources disagree

| Data | Priority (higher wins) |
|---|---|
| Nutrition, allergens | manual > label scan > Open Food Facts > LLM estimate > sample |
| Category | manual > rule > LLM |

Automatic sources never overwrite your manual edits.

## Allergens: unknown is not "none"

- OFF lists allergens as tags. `en:none` means "contains none"; an **empty** list only means nobody
  filled it in, so Annona stores **unknown**.
- For anyone with allergies, products with unknown allergens are **excluded** (and the app tells
  them why). If you know a product is safe, set its allergens yourself:

```bash
uv run python -m annona_server.products unknown-allergens        # what is unknown?
uv run python -m annona_server.products search "leche"           # find the product id
uv run python -m annona_server.products allergens 12 milk        # contains milk
uv run python -m annona_server.products allergens 12 --none      # contains none of the EU 14
uv run python -m annona_server.products allergens 12 --unknown   # undo your manual entry
uv run python -m annona_server.products category 12 dairy --type milk
```

Allergen names: `gluten crustaceans eggs fish peanuts soybeans milk nuts celery mustard sesame
sulphites lupin molluscs` (the EU 14). Always check the label.

## robots.txt exceptions in use

CLAUDE.md allows a service whose official documentation invites API clients, while its
robots.txt only keeps crawlers out, to be used following that documentation's rules.

| Service | robots.txt | Official terms followed |
|---|---|---|
| Open Food Facts | `Disallow: /api` for all user agents | [API docs](https://openfoodfacts.github.io/openfoodfacts-server/api/): identify with `AppName/Version (ContactEmail)`, max 15 product reads/min (Annona: 1 every 4 s, 30-day cache) |

Every exempted request is logged with its reason.


## Shop-internal barcodes

EAN-13 codes starting with `2` or `02` are GS1 "restricted circulation" numbers: shops use them
for their own weighed or in-store items, so the same code can mean different products in
different shops. Open Food Facts data under such a code does not describe the item on the shelf
(a real case: a frozen chicken breast was stored as 29 kcal and 0 g protein per 100 g). Ingestion
never queries Open Food Facts for these codes, removes OFF values stored earlier for them and
falls back to the flagged generic reference (`sample`). Scan the label to replace it.
`annona_server.products.drop_untrusted_off_data(session)` repairs an existing database.
