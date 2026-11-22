# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shopping basket of a plan at one store. Products and prices are SYNTHETIC test values."""

from decimal import Decimal

import pytest

from annona_core.shopping import (
    Basket,
    Need,
    StoreProduct,
    cheapest_split,
    price_basket,
)

D = Decimal


def need(pid, name, amount, *, type_="rice", category="grains", basis="g", pantry=0):
    return Need(
        product_id=pid,
        name=name,
        category=category,
        type=type_,
        basis=basis,
        amount=D(amount),
        in_pantry=D(pantry),
    )


def sells(pid, name, pack, cents, *, type_="rice", category="grains", basis="g", kcal=None):
    return StoreProduct(
        product_id=pid,
        name=name,
        category=category,
        type=type_,
        basis=basis,
        pack_amount=D(pack),
        price_cents=cents,
        kcal_per_100=None if kcal is None else D(kcal),
    )


def test_total_is_whole_packs_times_price():
    rice = need(1, "Arroz", 1500)  # 2 packs of 1 kg
    chicken = need(2, "Pollo", 700, type_="chicken", category="meat")  # 2 packs of 500 g
    store = [
        sells(1, "Arroz", 1000, 120),
        sells(2, "Pollo", 500, 300, type_="chicken", category="meat"),
    ]
    basket = price_basket([rice, chicken], store, store_id="a")
    assert [(ln.name, ln.packs, ln.cost_cents) for ln in basket.lines] == [
        ("Arroz", 2, 240),
        ("Pollo", 2, 600),
    ]
    assert basket.total_cents == 840 == sum(ln.cost_cents for ln in basket.lines)
    assert all(ln.replaces_product_id is None and not ln.alternatives for ln in basket.lines)


def test_the_pantry_is_subtracted_and_a_covered_need_is_not_bought():
    store = [sells(1, "Arroz", 1000, 120), sells(2, "Pasta", 500, 90, type_="pasta")]
    partly = need(1, "Arroz", 1200, pantry=300)  # 900 g left -> 1 pack
    covered = need(2, "Pasta", 400, type_="pasta", pantry=400)
    basket = price_basket([partly, covered], store, store_id="a")
    assert [(ln.name, ln.packs) for ln in basket.lines] == [("Arroz", 1)]
    assert basket.already_have == (2,)
    assert basket.total_cents == 120


def test_an_exact_remaining_amount_does_not_buy_an_extra_pack():
    basket = price_basket([need(1, "Arroz", 2000)], [sells(1, "Arroz", 1000, 100)], store_id="a")
    assert basket.lines[0].packs == 2


def test_a_missing_product_is_replaced_by_the_cheapest_equivalent_with_alternatives():
    wanted = need(10, "Arroz largo", 1000)  # sold at another store only
    store = [
        sells(1, "Arroz redondo", 1000, 150, kcal=350),
        sells(2, "Arroz integral", 1000, 210, kcal=360),
        sells(3, "Arroz basmati", 500, 130, kcal=340),  # 2 packs = 260
        sells(4, "Pasta", 500, 50, type_="pasta"),  # other type: never an equivalent
        sells(5, "Arroz en leche", 1000, 80, type_="rice", category="dairy"),  # other category
    ]
    basket = price_basket([wanted], store, store_id="b", nutrition={10: (D(350), None)})
    [line] = basket.lines
    assert (line.name, line.replaces_product_id, line.cost_cents) == ("Arroz redondo", 10, 150)
    assert [a.name for a in line.alternatives] == ["Arroz integral", "Arroz basmati"]
    integral, basmati = line.alternatives
    assert integral.extra_cost_cents == 60 and integral.kcal_diff_pct == D("2.9")
    assert (
        basmati.packs == 2
        and basmati.extra_cost_cents == 110
        and basmati.kcal_diff_pct == D("-2.9")
    )
    assert basket.total_cents == 150


def test_at_most_three_alternatives_are_offered():
    store = [sells(i, f"Arroz {i}", 1000, 100 + i) for i in range(1, 8)]
    [line] = price_basket([need(99, "Otro arroz", 500)], store, store_id="b").lines
    assert line.name == "Arroz 1" and len(line.alternatives) == 3


def test_nothing_is_invented_when_no_equivalent_exists():
    store = [sells(1, "Pasta", 500, 90, type_="pasta")]
    basket = price_basket(
        [need(10, "Quinoa", 300, type_="quinoa"), need(11, "Mezcla", 200, type_=None)],
        store,
        store_id="b",
    )
    assert basket.lines == () and basket.total_cents == 0
    assert [(u.name, u.reason, u.amount) for u in basket.unavailable] == [
        ("Quinoa", "not_sold", D(300)),
        ("Mezcla", "no_type", D(200)),
    ]


def test_liquids_and_solids_are_never_swapped():
    store = [sells(1, "Arroz", 1000, 100)]  # grams
    basket = price_basket([need(10, "Bebida de arroz", 1000, basis="ml")], store, store_id="b")
    assert basket.lines == () and basket.unavailable[0].reason == "not_sold"


def test_switching_store_changes_the_basket_and_the_total():
    needs = [need(1, "Arroz", 1000), need(2, "Pollo", 500, type_="chicken", category="meat")]
    cheap = [
        sells(1, "Arroz", 1000, 100),
        sells(2, "Pollo", 500, 250, type_="chicken", category="meat"),
    ]
    other = [
        sells(21, "Arroz Bomba", 1000, 190),
        sells(22, "Arroz Largo", 1000, 140),
        sells(23, "Pollo", 1000, 600, type_="chicken", category="meat"),
    ]
    a = price_basket(needs, cheap, store_id="a")
    b = price_basket(needs, other, store_id="b")
    assert (a.store_id, a.total_cents) == ("a", 350)
    assert (b.store_id, b.total_cents) == ("b", 740)
    assert [ln.name for ln in b.lines] == ["Arroz Largo", "Pollo"]
    assert all(ln.replaces_product_id in (1, 2) for ln in b.lines)


def test_prices_stay_in_integer_cents():
    basket = price_basket([need(1, "Arroz", 333)], [sells(1, "Arroz", 100, 7)], store_id="a")
    assert basket.lines[0].packs == 4 and basket.total_cents == 28
    assert isinstance(basket.total_cents, int)


def test_cheapest_split_is_a_marked_extension_point():
    with pytest.raises(NotImplementedError, match="extension point"):
        cheapest_split(
            [Basket(store_id="a", lines=(), unavailable=(), already_have=(), total_cents=0)]
        )
