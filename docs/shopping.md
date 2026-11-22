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

## Cheapest basket across stores

`core/shopping/compare.py` prices the same needs at every selected store (`price_basket`) and
compares them (`compare_baskets`):

- **Each store alone.** Complete baskets rank first, then the cheapest: a basket missing items is
  not "cheaper".
- **The best split between two stores.** Every need is bought where its packs cost least among the
  two. It is proposed only if it saves at least 1 EUR over the best single store
  (`min_saving_cents`, configurable): a second trip has to be worth it. If no store has everything
  but two together do, the split is shown as the only way.

`POST /plans/{id}/shopping-compare` and the "Comparar tiendas" button of the shopping screen. Only
stores with priced products in the database can be compared; with one real store (Mercadona) it
needs a second one ([adding-a-supermarket.md](adding-a-supermarket.md)).

## API

`GET /plans/{id}/shopping-list[?store_id=]`, `POST /plans/{id}/shopping-list`,
`POST /plans/{id}/shopping-compare`,
`PATCH /shopping-items/{id}` (returns what changed in the pantry), `GET /catalog/stores`.
