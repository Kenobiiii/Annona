# Shopping list

The list of a plan at one chosen store, priced, with substitutes, shareable as text.

## How a list is built

Pure code (`core/shopping/basket.py`), no AI:

1. **Needs** = every ingredient of every planned meal, summed for the household.
2. **Minus the pantry**: what the pantry already holds of that same product (converted to the
   product's unit) is subtracted. A fully covered need is not bought.
3. **Whole packs** at the store's price: `ceil(missing / pack size)`.
4. **If the store does not sell that product**, the cheapest *equivalent* is used: same category
   AND same type (e.g. grains / rice) and the same unit basis (a liquid is never swapped for a
   solid). Up to three other equivalents are offered as **alternatives**, with the price difference
   for the amount needed and the difference in kcal (and protein, when known) per 100 g/ml.
5. **Nothing is invented**: with no equivalent, the item is listed as *unavailable* in that store
   (`not_sold`), or `no_type` when the product has no type to match on.

Choosing another store in the app builds another list for that store (`POST
/plans/{id}/shopping-list`), kept with its own ticks. Asking again returns the same list;
`refresh=true` rebuilds it and forgets the ticks. The list made with the plan is the one for the
plan's store.

Equivalence depends on the product `type`; products without one cannot be matched across stores.

## Ticking and the pantry

Ticking an item means "bought": its packs (packs x pack size) are **added to the pantry**; unticking
takes them back (never below zero: some may already be cooked). Only a change of state has an
effect, so repeating a request never doubles the stock. The app tells the person the first time and
shows what changed after each tick. Items whose product has no known pack size cannot be added.

This is what fills the pantry that "mark as cooked" ([recipes.md](recipes.md)) deducts from.

## Sharing

The app builds a plain-text version (`shoppingText`): one line per item with its tick, price and
the product it replaces, then what is unavailable. It is shared with the system share sheet.

## Extension point: cheapest basket across stores

`core/shopping/compare.py` defines the result type and a stub, `cheapest_split`, that raises
`NotImplementedError`. `price_basket` already prices the same needs at any one store, so a
comparison calls it once per store and combines the results (the whole-basket cost per store and
the saving of splitting between two). Not built yet, on purpose: no API route or screen exists
for it, and it needs product decisions (how many stores, travel cost, minimum saving).

## API

`GET /plans/{id}/shopping-list[?store_id=]`, `POST /plans/{id}/shopping-list`,
`PATCH /shopping-items/{id}` (returns what changed in the pantry), `GET /catalog/stores`.
