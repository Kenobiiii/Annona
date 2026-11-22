# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shopping basket of a plan at one store. Products and prices are SYNTHETIC test values."""

from decimal import Decimal

import pytest

from annona_core.shopping import (
    Need,
    StoreProduct,
    compare_baskets,
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


def three_stores():
    needs = [
        need(1, "Arroz", 1000),
        need(2, "Pollo", 500, type_="chicken", category="meat"),
        need(3, "Leche", 1000, type_="milk", category="dairy", basis="ml"),
    ]

    def store(rice, chicken, milk, name):
        items = []
        if rice is not None:
            items.append(sells(10, "Arroz", 1000, rice))
        if chicken is not None:
            items.append(sells(20, "Pollo", 500, chicken, type_="chicken", category="meat"))
        if milk is not None:
            items.append(sells(30, "Leche", 1000, milk, type_="milk", category="dairy", basis="ml"))
        return price_basket(needs, items, store_id=name)

    return {
        "a": store(100, 400, 120, "a"),  # 620: cheap rice, dear chicken
        "b": store(180, 250, 110, "b"),  # 540: the cheapest single store
        "c": store(90, 500, None, "c"),  # sells no milk at all
    }


def test_the_cheapest_complete_store_wins_and_incomplete_ones_rank_last():
    baskets = three_stores()
    result = compare_baskets(list(baskets.values()))
    assert [b.store_id for b in result.baskets] == ["b", "a", "c"]
    assert (result.best_single_store, result.best_single_cents) == ("b", 540)
    assert baskets["c"].unavailable[0].product_id == 3 and baskets["c"].total_cents == 590


def test_splitting_between_two_stores_reports_the_saving_and_what_to_buy_where():
    result = compare_baskets(list(three_stores().values()), min_saving_cents=50)
    split = result.split
    assert split is not None and set(split.stores) == {"b", "c"}
    # rice at c (90), chicken at b (250), milk at b (110) = 450 versus 540 at b alone; c sells no
    # milk, which is fine: b supplies it.
    assert split.total_cents == 450 and result.saving_cents == 90
    names = {s: sorted(ln.name for ln in lines) for s, lines in split.assignments.items()}
    assert names == {"c": ["Arroz"], "b": ["Leche", "Pollo"]}
    assert split.totals == {"c": 90, "b": 360} and sum(split.totals.values()) == split.total_cents


def test_a_small_saving_is_not_worth_a_second_trip():
    result = compare_baskets(list(three_stores().values()))  # default: at least 1 EUR
    assert result.split is None and result.saving_cents == 0  # 90 cents saved: not enough
    assert result.best_single_store == "b"


def test_a_split_can_be_the_only_way_to_buy_everything():
    needs = [need(1, "Arroz", 1000), need(2, "Pollo", 500, type_="chicken", category="meat")]
    only_rice = price_basket(needs, [sells(10, "Arroz", 1000, 100)], store_id="rice")
    only_chicken = price_basket(
        needs, [sells(20, "Pollo", 500, 300, type_="chicken", category="meat")], store_id="meat"
    )
    result = compare_baskets([only_rice, only_chicken])
    assert result.best_single_store is None and result.best_single_cents is None
    assert result.split is not None and result.split.total_cents == 400 and result.saving_cents == 0


def test_a_need_nobody_sells_means_no_split_can_cover_everything():
    needs = [need(1, "Arroz", 1000), need(9, "Quinoa", 300, type_="quinoa")]
    a = price_basket(needs, [sells(10, "Arroz", 1000, 100)], store_id="a")
    b = price_basket(needs, [sells(10, "Arroz", 1000, 90)], store_id="b")
    assert compare_baskets([a, b]).split is None


def test_one_store_alone_is_just_itself():
    only = three_stores()["b"]
    result = compare_baskets([only])
    assert [b.store_id for b in result.baskets] == ["b"] and result.split is None
    with pytest.raises(ValueError):
        compare_baskets([])


def test_a_split_never_picks_a_store_that_would_sell_nothing():
    cheap = price_basket([need(1, "Arroz", 1000)], [sells(10, "Arroz", 1000, 50)], store_id="x")
    dear = price_basket([need(1, "Arroz", 1000)], [sells(10, "Arroz", 1000, 500)], store_id="y")
    assert compare_baskets([cheap, dear], min_saving_cents=0).split is None
