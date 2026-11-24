# Receipt scanning

Photo of a receipt -> pantry and prices updated, **only after you confirm**.

## Flow

1. **Capture** (app): camera or gallery. The photo is shrunk on the phone first (cheaper, faster).
2. **Upload** (`POST /receipts`, multipart): the server checks the file's own bytes (JPEG, PNG or
   WebP, up to 8 MB), stores it under `receipts/` next to the database, and sends it once to the
   configured AI provider (small tier, vision) to be read.
3. **Read** (AI): strict JSON with the store, its postal code, date, total and one entry per line
   *as printed*. The model only transcribes; it never calculates (`core/receipts/draft.py`). The
   one field where it interprets is `search_name`, a plain-words name used only to search a store
   ("YAK SOJA CUP" -> "yakisoba soja vaso"); matching and the review always use the printed text.
4. **Check** (code, `core/receipts/parse.py`): numbers, weights and dates are parsed by code.
   - the lines must add up to the printed total (discounts included); if not, the receipt is
     flagged with the difference. This **sum check** catches missed or misread lines;
   - a line with quantity and unit price must satisfy `quantity x unit price = total`;
   - a weight is accepted only if it is not a pack size copied from the name ("800G", "6X1L") and
     it agrees with the price per kg. A line that prints a single price is taken at that price.
5. **Match** (code, rapidfuzz, `core/receipts/match.py`): each line is compared word by word with
   the catalogue; abbreviations count ("SEMI" -> "semidesnatada"). The result is a suggestion with
   a confidence. Shop products are tried first; generic foods (no store, e.g. "Banana") are only
   a fallback when no shop product fits. Confirmed choices are remembered per store (`receipt_alias`) and used with full
   confidence next time. A tie is never trusted: unclear winners stay below the pre-selection level.
6. **Review** (app): you confirm, change the product (search), create it, or ignore each line. Lines at or above
   0.85 confidence are pre-selected; lower ones and unmatched ones are never applied unless you act.
7. **Confirm** (`POST /receipts/{id}/confirm`): exactly the lines you name, with the product you
   saw, are added to the pantry and their price saved with `source=receipt`. All lines not named
   are ignored. Everything is validated first, so a refused request changes nothing.

## A product the catalogue does not have

**Search the receipt's store** ("Buscar en Mercadona", only for stores with a plugin). The first
time, the app shows the plugin's notice (opt-in plugins) and asks for the shop's postal code,
prefilled from the receipt when it prints one; nothing reaches the store before you accept. Then
it searches with the AI's plain-words name of the line (`search_name`, editable), one search per
press, cached for a day. Picking a result adds that ONE product with the store's SKU, pack size and
price, plus Open Food Facts nutrition and allergens by barcode. The store only receives the search
text and the postal code. Change the postal code or withdraw the notice in Settings > Stores.

Or **create the product** (`POST /products`): a name (taken from the
line), a category and, optionally, a pack size. It is a generic product (no store SKU to give it);
the price you paid is still saved for the receipt's store when you confirm. Nutrition and allergens
stay **unknown** until you add them in Products: nothing is guessed. A product you added with the
same name is reused, not duplicated. Next time, the remembered alias matches the line directly.

## Unknowns are explicit

Receipts often print no weight. For each confirmed line the app shows what is known and what is
assumed: `assumed_one_pack` (no quantity printed), `unknown_pack_size` (the product has no pack
size: you must say how much), `price_from_weight` (a weighed item's price per pack is derived from
the price per kg), `no_price`. Nothing is guessed silently.

## Privacy

The photo is stored only on your server. It leaves it once, to the AI provider you configured
(DeepSeek by default), to be read; the app tells you the first time. Discarding a scan deletes the
photo and its sidecar file. Pantry, prices and names stay on your server.

## API

`POST /receipts`, `GET /receipts/{id}`, `GET /receipts/{id}/image`, `POST /receipts/{id}/confirm`,
`POST /receipts/{id}/discard`; `POST /products` (add a product by hand); store plugins:
`GET|PUT|DELETE /stores/{id}/connection`, `GET /stores/{id}/search?q=`, `POST /stores/{id}/products`
(errors `notice_required` 409, `not_connected` 409, `store_error` 502). Errors: `bad_image` (422), `amount_required` (422, with the line
ids), `receipt_closed` (409), `not_found` (404).

If you tick a shopping-list item **and** scan the receipt of the same purchase, the pantry gets it
twice. Choose one of the two ([shopping.md](shopping.md)).
