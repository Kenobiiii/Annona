# SPDX-License-Identifier: AGPL-3.0-or-later
"""Receipt parsing, matching and effects. Product names and prices are SYNTHETIC."""

import json
from decimal import Decimal

import pytest

from annona_core.domain import Product, Unit
from annona_core.llm import FakeLLM, Image, LLMClient, Tier
from annona_core.receipts import (
    AUTO_SELECT_CONFIDENCE,
    Candidate,
    DraftLine,
    ReceiptDraft,
    line_effect,
    match_line,
    normalise,
    parse_cents,
    parse_date,
    parse_decimal,
    parse_receipt,
    read_receipt,
)
from annona_core.receipts.draft import build_receipt_prompt
from annona_core.receipts.parse import parse_postal_code, parse_weight

D = Decimal


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,15", "1.15"),
        ("1.15", "1.15"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("0,550", "0.550"),
        ("22,35 EUR", "22.35"),
        ("€ 4,98", "4.98"),
        ("-0,50", "-0.50"),
        ("3", "3"),
    ],
)
def test_decimals_as_printed_on_receipts(text, value):
    assert parse_decimal(text) == D(value)


@pytest.mark.parametrize("text", [None, "", "abc", "--"])
def test_unreadable_numbers_are_none(text):
    assert parse_decimal(text) is None and parse_cents(text) is None


def test_cents_are_exact_integers():
    assert parse_cents("1,15") == 115 and parse_cents("0,005") == 1 and parse_cents("-0,50") == -50
    assert parse_cents("19,999") == 2000


def test_weights_and_volumes_become_grams_and_millilitres():
    assert parse_weight("0,550 kg").amount == D(550) and parse_weight("0,550 kg").unit == Unit.G
    assert parse_weight("250 g").amount == D(250)
    assert parse_weight("1,5 l").amount == D(1500) and parse_weight("1,5 l").unit == Unit.ML
    assert parse_weight("7,70 EUR/kg") is None  # a price per kilo is not a weight
    assert (
        parse_weight("2 ud") is None and parse_weight(None) is None and parse_weight("0 kg") is None
    )


def test_dates_day_first():
    assert parse_date("12/11/2026 18:42").isoformat() == "2026-11-12"
    assert parse_date("12-11-26").isoformat() == "2026-11-12"
    assert parse_date("2026-11-12").isoformat() == "2026-11-12"
    assert parse_date("31/02/2026") is None and parse_date("no date") is None


def line(raw, total, **kw):
    return DraftLine(raw_text=raw, total=total, **kw)


def test_a_receipt_is_parsed_and_its_total_checked():
    draft = ReceiptDraft(
        store="MERCADONA",
        date="12/11/2026",
        total="22,30",
        lines=[
            line("ARROZ REDONDO 1KG", "1,15", quantity="1"),
            line("LECHE SEMI 6X1L", "9,96", quantity="2", unit_price="4,98"),
            line("FILETE PECHUGA POLLO", "4,24", weight="0,550 kg", unit_price="7,70"),
            line("HUEVOS 30 L", "5,90"),
            line("YOGUR NAT.", "1,05", quantity="3", unit_price="0,35"),
            line("DESCUENTO", "-0,30"),
        ],
    )
    parsed = parse_receipt(draft)
    assert parsed.total_cents == 2230 and parsed.discounts_cents == -30
    assert [ln.total_cents for ln in parsed.lines] == [115, 996, 424, 590, 105]
    assert sum(ln.total_cents for ln in parsed.lines) == 2230 and parsed.lines_total_cents == 2200
    assert parsed.total_matches is False and parsed.issues == ["total_mismatch:-30"]
    assert parsed.lines[2].weight.amount == D(550) and parsed.lines[1].quantity == D(2)
    assert parsed.purchased_on.isoformat() == "2026-11-12"


def test_a_receipt_whose_lines_add_up_matches_its_total():
    draft = ReceiptDraft(
        total="2,20", lines=[line("A", "1,15"), line("B", "1,35"), line("DTO", "-0,30")]
    )
    parsed = parse_receipt(draft)
    assert parsed.total_matches is True and parsed.issues == []


def test_line_math_is_checked_when_the_numbers_allow_it():
    bad = parse_receipt(
        ReceiptDraft(total="9,00", lines=[line("LECHE", "9,00", quantity="2", unit_price="4,98")])
    )
    assert bad.lines[0].issues == ("line_math",)
    weighed = parse_receipt(  # a weighed line: quantity x unit price is meaningless there
        ReceiptDraft(
            lines=[line("POLLO", "4,24", quantity="1", unit_price="7,70", weight="0,550 kg")]
        )
    )
    assert weighed.lines[0].issues == ()


@pytest.mark.parametrize(
    ("raw", "weight", "reason"),
    [
        ("COPOS AVENA 800G", "800G", "weight_is_pack_size"),
        ("LECHE SEMI 6X1L", "6X1L", "weight_is_pack_size"),
        ("ARROZ REDONDO 1KG", "1 kg", "weight_is_pack_size"),
        ("HUEVOS GRANDES 30", "30", None),  # no unit: not a weight at all
    ],
)
def test_a_pack_size_copied_from_the_name_is_never_taken_as_the_weight_bought(raw, weight, reason):
    parsed = parse_receipt(ReceiptDraft(lines=[line(raw, "2,60", quantity="2", weight=weight)]))
    assert parsed.lines[0].weight is None
    assert (reason in parsed.lines[0].issues) is (reason is not None)


def test_a_real_weight_the_model_also_left_in_the_name_is_kept_when_the_price_confirms_it():
    merged = parse_receipt(
        ReceiptDraft(
            lines=[
                line(
                    "1 FILETE PECHUGA POLLO 0,550 kg 7,70 EUR/kg",
                    "4,24",
                    weight="0,550 kg",
                    unit_price="7,70",
                )
            ]
        )
    )
    assert merged.lines[0].weight.amount == D(550) and merged.lines[0].issues == ()


def test_a_weight_must_agree_with_the_price_per_kilo():
    ok = parse_receipt(
        ReceiptDraft(lines=[line("PECHUGA", "4,24", weight="0,550 kg", unit_price="7,70")])
    )
    assert ok.lines[0].weight.amount == D(550) and ok.lines[0].issues == ()
    off = parse_receipt(
        ReceiptDraft(lines=[line("PECHUGA", "9,99", weight="0,550 kg", unit_price="7,70")])
    )
    assert off.lines[0].weight is None and "weight_math" in off.lines[0].issues


def test_a_line_with_one_price_labelled_unit_price_still_counts():
    parsed = parse_receipt(
        ReceiptDraft(
            total="4,50",
            lines=[
                line("1 CEBOLLAS", None, quantity="1", unit_price="1,50"),
                line("2 PAN", None, quantity="2", unit_price="1,50"),
            ],
        )
    )
    assert [ln.total_cents for ln in parsed.lines] == [150, 300]
    assert all("total_from_unit_price" in ln.issues for ln in parsed.lines)
    assert parsed.total_matches is True  # and the sum check still has the last word


def test_lines_without_an_amount_are_set_aside_not_invented():
    parsed = parse_receipt(
        ReceiptDraft(lines=[line("ARROZ", "1,15"), line("PAN", None), line("", "2,00")])
    )
    assert [ln.raw_text for ln in parsed.lines] == ["ARROZ"]
    assert parsed.skipped == ["PAN", "(empty line)"] and "total_unreadable" in parsed.issues
    assert parsed.total_matches is None


# ---------------------------------------------------------------------------------- matching

CATALOGUE = [
    Candidate(1, "Arroz redondo Hacendado", "shop", "Hacendado"),
    Candidate(2, "Leche semidesnatada Hacendado", "shop", "Hacendado"),
    Candidate(3, "Leche entera Hacendado", "shop", "Hacendado"),
    Candidate(4, "Filetes pechuga de pollo", "shop"),
    Candidate(5, "Pechugas de pollo enteras congeladas", "shop"),
    Candidate(6, "Huevos", "shop"),
    Candidate(7, "Yogur natural Hacendado", "shop", "Hacendado"),
    Candidate(8, "Yogur de fresa Hacendado", "shop", "Hacendado"),
    Candidate(9, "Macarrón Hacendado", "shop", "Hacendado"),
]


@pytest.mark.parametrize(
    ("printed", "product"),
    [
        ("ARROZ REDONDO 1KG", 1),
        ("2 LECHE SEMI 6X1L", 2),
        ("FILETE PECHUGA POLLO", 4),
        ("HUEVOS 30 L", 6),
        ("YOGUR NAT.", 7),
        ("MACARRON", 9),
    ],
)
def test_abbreviated_names_find_their_product_with_confidence(printed, product):
    m = match_line(printed, CATALOGUE, store_id="shop")
    assert m.product_id == product and m.source == "fuzzy"
    assert m.preselected, (printed, m.confidence)


def test_normalise_drops_prices_quantities_and_units():
    assert normalise("2 Leche semi 6x1L 4,98") == "LECHE SEMI"
    assert normalise("Plátano de Canarias 1,2 kg") == "PLATANO DE CANARIAS"


def test_an_unclear_match_is_never_preselected():
    # "LECHE" fits two products equally: a coin toss must not look certain.
    m = match_line("LECHE", CATALOGUE)
    assert m.product_id in (2, 3) and not m.preselected
    assert m.confidence < AUTO_SELECT_CONFIDENCE and m.runner_up_id in (2, 3)
    assert {pid for pid, _ in m.alternatives} <= {2, 3}


def test_a_three_letter_prefix_is_not_enough_to_preselect():
    # Found by the eval: a hard photo made "AOVE 1L" read "AVE 1L", a prefix of AVENA.
    oats = [Candidate(1, "Copos de avena", "shop"), Candidate(2, "Arroz", "shop")]
    m = match_line("AVE 1L", oats)
    assert not m.preselected and m.confidence < AUTO_SELECT_CONFIDENCE
    assert match_line("AVENA 1L", oats).preselected  # the real word still is


def test_something_unrelated_has_no_suggestion():
    m = match_line("BOLSA PLASTICO", CATALOGUE)
    assert m.product_id is None and m.source == "none" and not m.preselected
    assert match_line("XQZK", CATALOGUE).product_id is None
    assert match_line("ARROZ", []).product_id is None


def test_a_confirmed_alias_wins_with_full_confidence():
    m = match_line("2 LECHE SEMI 6X1L", CATALOGUE, aliases={"LECHE SEMI": 3})
    assert (m.product_id, m.confidence, m.source) == (3, D(1), "alias")


def test_a_generic_food_is_matched_when_no_shop_product_fits():
    generic = [*CATALOGUE, Candidate(55, "Banana"), Candidate(56, "Fresh cheese (queso fresco)")]
    m = match_line("1 BANANA", generic, store_id="shop")
    assert m.product_id == 55 and m.preselected


def test_a_shop_product_beats_a_generic_food_that_also_fits():
    catalogue = [
        Candidate(1, "Queso fresco batido Hacendado", "shop", "Hacendado"),
        Candidate(2, "Fresh cheese (queso fresco)"),
    ]
    assert match_line("QUESO FRESCO BATIDO", catalogue, store_id="shop").product_id == 1
    assert match_line("QUESO FRESCO", catalogue, store_id="shop").product_id == 1


def test_a_tie_goes_to_the_receipts_own_store():
    twins = [Candidate(10, "Arroz largo", "other"), Candidate(11, "Arroz largo", "mine")]
    assert match_line("ARROZ LARGO", twins, store_id="mine").product_id == 11
    assert match_line("ARROZ LARGO", twins, store_id="other").product_id == 10


# ------------------------------------------------------------------------------- effects


def product(pack=1000, unit=Unit.G, **kw):
    return Product(
        id=1,
        name="Arroz",
        package_amount=D(pack) if pack is not None else None,
        package_unit=unit if pack is not None else None,
        **kw,
    )


def parsed_line(total, **kw):
    return parse_receipt(ReceiptDraft(lines=[line("X", total, **kw)])).lines[0]


def test_packs_with_a_printed_quantity():
    effect = line_effect(
        parsed_line("9,96", quantity="2", unit_price="4,98"), product(6000, Unit.ML)
    )
    assert (effect.pantry_amount, effect.pantry_unit, effect.price_cents) == (
        D(12000),
        Unit.ML,
        498,
    )
    assert effect.notes == ()


def test_no_quantity_means_one_pack_and_says_so():
    effect = line_effect(parsed_line("1,15"), product())
    assert (effect.pantry_amount, effect.price_cents) == (D(1000), 115)
    assert effect.notes == ("assumed_one_pack",)


def test_a_printed_weight_is_what_was_bought_and_the_price_is_per_pack():
    effect = line_effect(parsed_line("4,24", weight="0,550 kg"), product(500, Unit.G))
    assert effect.pantry_amount == D(550) and effect.pantry_unit == Unit.G
    assert effect.price_cents == 385 and "price_from_weight" in effect.notes  # 424 / 550 x 500


def test_an_unknown_pack_size_is_reported_not_guessed():
    effect = line_effect(parsed_line("1,15", quantity="1"), product(None))
    assert effect.pantry_amount is None and effect.pantry_unit is None
    assert effect.price_cents == 115 and effect.notes == ("unknown_pack_size",)
    weighed = line_effect(parsed_line("4,24", weight="0,550 kg"), product(None))
    assert weighed.pantry_amount == D(550) and weighed.price_cents is None
    assert weighed.notes == ("no_price",)


def test_a_weight_in_another_dimension_needs_data_to_convert():
    # Eggs sold by the unit: a weight alone cannot become "units" without a unit weight.
    eggs = product(30, Unit.UNIT)
    assert line_effect(parsed_line("5,90", weight="1,8 kg"), eggs).pantry_amount == D(
        30
    )  # as packs
    with_weight = product(30, Unit.UNIT, unit_weight_g=D(60))
    assert line_effect(parsed_line("5,90", weight="1,8 kg"), with_weight).pantry_amount == D(30)


# ------------------------------------------------------------------------- the vision call

IMAGE = Image("image/jpeg", b"\xff\xd8 not a real photo")
MODELS = {Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}


def test_the_model_only_reads_and_the_call_uses_the_small_tier_with_the_image():
    answer = json.dumps(
        {
            "store": "SHOP",
            "date": "12/11/2026",
            "total": "1,15",
            "lines": [{"raw_text": "ARROZ", "total": "1,15"}],
        }
    )
    fake = FakeLLM([answer])
    draft, stats = read_receipt(LLMClient(fake, MODELS), IMAGE)
    assert draft.lines[0].raw_text == "ARROZ" and stats.calls == 1
    model, request = fake.requests[0]
    assert model == "fake/s" and request.messages[0].images == (IMAGE,)
    assert (
        "never invent" in request.system.lower()
        and "never\ncalculate" in request.system.replace(" ", "")
    )


@pytest.mark.parametrize(
    ("text", "code"),
    [("29003", "29003"), (" 29003 ", "29003"), ("sw1a 1aa", "SW1A 1AA"), ("MALAGA", None),
     ("12", None), (None, None), ("29003 MALAGA CENTRO", None)],
)  # fmt: skip
def test_a_postal_code_is_kept_only_if_it_looks_like_one(text, code):
    assert parse_postal_code(text) == code


def test_the_search_name_is_kept_apart_and_never_replaces_the_printed_text():
    draft = ReceiptDraft(
        postal_code="29003",
        lines=[
            DraftLine(raw_text="YAK SOJA CUP", total="1,00", search_name=" yakisoba  soja vaso "),
            DraftLine(raw_text="BANANA", total="1,39", search_name="banana"),
            DraftLine(raw_text="SPAGHETTI", total="0,85"),
        ],
    )
    parsed = parse_receipt(draft)
    assert parsed.postal_code == "29003"
    assert [ln.raw_text for ln in parsed.lines] == ["YAK SOJA CUP", "BANANA", "SPAGHETTI"]
    assert [ln.search_name for ln in parsed.lines] == ["yakisoba soja vaso", None, None]


def test_the_prompt_keeps_the_printed_text_and_allows_interpretation_only_for_searching():
    system, _ = build_receipt_prompt()
    assert "search_name: the ONLY field where you may interpret" in system
    assert "raw_text must still be exactly as printed" in system
    assert "postal_code" in system
