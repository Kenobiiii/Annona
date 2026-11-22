# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scanning, reviewing and confirming receipts with FakeLLM. SYNTHETIC products and receipts."""

from decimal import Decimal
from pathlib import Path

import pytest

from annona_core.domain import (
    Household,
    PriceSource,
    Product,
    ReceiptLineStatus,
    ReceiptStatus,
    Unit,
)
from annona_core.llm import FakeLLM, LLMClient, Tier
from annona_server.db import repositories as r
from annona_server.receipts import (
    BadImage,
    Decision,
    NeedsAmount,
    ReceiptClosed,
    confirm_receipt,
    discard_receipt,
    scan_receipt,
    view_receipt,
)

FIXTURES = Path(__file__).parent / "fixtures" / "receipts"
MODELS = {Tier.SMALL: "fake/s", Tier.LARGE: "fake/l"}
PHOTO = b"\x89PNG\r\n\x1a\n" + b"synthetic receipt photo"  # only the magic bytes matter here


def llm_for(*fixtures: str) -> LLMClient:
    return LLMClient(FakeLLM([(FIXTURES / f"{n}.json").read_text() for n in fixtures]), MODELS)


@pytest.fixture
def home(session):
    h = r.HouseholdRepository(session).add(Household(name="Casa", weekly_budget_cents=8000))
    products = r.SqlProductRepository(session)

    def add(name, pack, unit, brand=None):
        return products.add(
            Product(
                name=name,
                brand=brand,
                store_id="mercadona",
                store_sku=name,
                package_amount=Decimal(pack) if pack else None,
                package_unit=unit if pack else None,
            )
        )

    ids = {
        "rice": add("Arroz redondo Hacendado", 1000, Unit.G, "Hacendado").id,
        "milk": add("Leche semidesnatada Hacendado", 6000, Unit.ML, "Hacendado").id,
        "whole": add("Leche entera Hacendado", 6000, Unit.ML, "Hacendado").id,
        "chicken": add("Filetes pechuga de pollo", 500, Unit.G).id,
        "eggs": add("Huevos", 30, Unit.UNIT).id,
        "yogurt": add("Yogur natural Hacendado", None, None, "Hacendado").id,  # no pack size
    }
    session.commit()
    return h, ids


def by_text(view):
    return {v.line.raw_text: v for v in view.lines}


def scan(session, home, *fixtures, tmp_path):
    household, _ = home
    result = scan_receipt(session, llm_for(*fixtures), household, tmp_path, PHOTO)
    return view_receipt(session, household, result.receipt.id)


def test_scan_reads_matches_and_checks_the_total(session, home, tmp_path):
    view = scan(session, home, "basic", tmp_path=tmp_path)
    receipt = view.receipt
    assert receipt.status == ReceiptStatus.PENDING_REVIEW and receipt.store_id == "mercadona"
    assert receipt.total_cents == 2205 and receipt.purchased_at.date().isoformat() == "2026-11-12"
    assert (
        view.total_matches is True
        and view.lines_total_cents == 2205
        and view.discounts_cents == -30
    )
    lines = by_text(view)
    assert len(lines) == 6  # the discount is not a product line
    assert lines["ARROZ REDONDO 1KG"].product.name == "Arroz redondo Hacendado"
    assert lines["LECHE SEMI 6X1L"].product.name == "Leche semidesnatada Hacendado"
    assert lines["FILETE PECHUGA POLLO"].product.name == "Filetes pechuga de pollo"
    assert lines["BOLSA PLASTICO"].product is None
    assert lines["BOLSA PLASTICO"].line.status == ReceiptLineStatus.UNMATCHED
    assert all(v.preselected for k, v in lines.items() if k != "BOLSA PLASTICO")
    assert not lines["BOLSA PLASTICO"].preselected


def test_the_photo_stays_on_the_server_and_the_ai_gets_it_once(session, home, tmp_path):
    household, _ = home
    fake = FakeLLM([(FIXTURES / "basic.json").read_text()])
    result = scan_receipt(session, LLMClient(fake, MODELS), household, tmp_path, PHOTO)
    stored = Path(result.receipt.image_path)
    assert stored.parent == tmp_path and stored.read_bytes() == PHOTO
    assert len(fake.requests) == 1 and fake.requests[0][0] == "fake/s"  # small tier, one call
    assert fake.requests[0][1].messages[0].images[0].data == PHOTO


def test_a_total_that_does_not_add_up_is_flagged_not_hidden(session, home, tmp_path):
    view = scan(session, home, "wrong_total", tmp_path=tmp_path)
    assert view.total_matches is False and view.issues == ["total_mismatch:-95"]


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"GIF89a....", b"%PDF-1.4"])
def test_only_real_photos_are_accepted(session, home, tmp_path, data):
    photos = tmp_path / "photos"
    with pytest.raises(BadImage):
        scan_receipt(session, llm_for("basic"), home[0], photos, data)
    assert not photos.exists()  # nothing stored for a rejected upload


def test_a_failed_reading_leaves_no_orphan_photo(session, home, tmp_path):
    broken = LLMClient(FakeLLM(["this is not json", "still not json"]), MODELS)
    photos = tmp_path / "photos"
    with pytest.raises(Exception, match="."):
        scan_receipt(session, broken, home[0], photos, PHOTO)
    assert list(photos.iterdir()) == []


def decisions(view, ids, *, only=None, extra=None):
    lines = by_text(view)
    out = []
    for text, key in (only or {}).items():
        out.append(Decision(lines[text].line.id, ids[key]))
    out.extend(extra or [])
    return out


def test_only_the_lines_the_person_confirms_change_the_pantry_and_prices(session, home, tmp_path):
    household, ids = home
    view = scan(session, home, "basic", tmp_path=tmp_path)
    chosen = {"ARROZ REDONDO 1KG": "rice", "LECHE SEMI 6X1L": "milk"}
    applied = confirm_receipt(
        session, household, view.receipt.id, decisions(view, ids, only=chosen)
    )

    assert {a.name for a in applied} == {"Arroz redondo Hacendado", "Leche semidesnatada Hacendado"}
    pantry = {
        i.product_id: (i.amount, i.unit)
        for i in r.SqlPantryRepository(session).for_household(household.id)
    }
    assert pantry == {ids["rice"]: (Decimal(1000), Unit.G), ids["milk"]: (Decimal(12000), Unit.ML)}
    prices = {p.product_id: p for p in r.SqlPriceRepository(session).list()}
    assert prices[ids["rice"]].amount_cents == 115 and prices[ids["milk"]].amount_cents == 498
    assert all(p.source == PriceSource.RECEIPT and p.receipt_line_id for p in prices.values())
    assert prices[ids["rice"]].store_id == "mercadona"
    assert prices[ids["rice"]].observed_at.date().isoformat() == "2026-11-12"

    statuses = {
        v.line.raw_text: v.line.status
        for v in view_receipt(session, household, view.receipt.id).lines
    }
    assert statuses["ARROZ REDONDO 1KG"] == ReceiptLineStatus.CONFIRMED
    assert statuses["HUEVOS 30 L"] == ReceiptLineStatus.IGNORED  # never confirmed: never applied
    assert r.ReceiptRepository(session).get(view.receipt.id).status == ReceiptStatus.CONFIRMED


def test_a_line_nobody_confirmed_is_never_applied_silently(session, home, tmp_path):
    household, ids = home
    view = scan(session, home, "basic", tmp_path=tmp_path)
    assert confirm_receipt(session, household, view.receipt.id, []) == []  # confirm nothing
    assert r.SqlPantryRepository(session).for_household(household.id) == []
    assert r.SqlPriceRepository(session).list() == []
    assert all(
        v.line.status == ReceiptLineStatus.IGNORED
        for v in view_receipt(session, household, view.receipt.id).lines
    )


def test_a_weighed_line_adds_the_weight_and_a_price_per_pack(session, home, tmp_path):
    household, ids = home
    view = scan(session, home, "basic", tmp_path=tmp_path)
    line = by_text(view)["FILETE PECHUGA POLLO"]
    assert line.effect.notes == ("price_from_weight",) and line.effect.pantry_amount == 550
    confirm_receipt(session, household, view.receipt.id, [Decision(line.line.id, ids["chicken"])])
    [item] = r.SqlPantryRepository(session).for_household(household.id)
    assert (item.amount, item.unit) == (Decimal(550), Unit.G)
    [price] = r.SqlPriceRepository(session).list()
    assert price.amount_cents == 385  # 4.24 EUR for 550 g -> 3.85 EUR for a 500 g pack


def test_no_quantity_is_assumed_out_loud_and_an_unknown_pack_size_asks(session, home, tmp_path):
    household, ids = home
    view = scan(session, home, "basic", tmp_path=tmp_path)
    eggs = by_text(view)["HUEVOS 30 L"]
    assert eggs.effect.notes == ("assumed_one_pack",) and eggs.effect.pantry_amount == 30

    yogurt = by_text(view)["YOGUR NAT."]
    assert yogurt.effect.notes == ("unknown_pack_size",) and yogurt.effect.pantry_amount is None
    with pytest.raises(NeedsAmount) as error:
        confirm_receipt(
            session,
            household,
            view.receipt.id,
            [Decision(eggs.line.id, ids["eggs"]), Decision(yogurt.line.id, ids["yogurt"])],
        )
    assert error.value.line_ids == [yogurt.line.id]
    # Atomic: the refused request changed nothing, not even the line that was fine.
    assert r.SqlPantryRepository(session).for_household(household.id) == []
    assert r.ReceiptRepository(session).get(view.receipt.id).status == ReceiptStatus.PENDING_REVIEW

    confirm_receipt(
        session,
        household,
        view.receipt.id,
        [
            Decision(eggs.line.id, ids["eggs"]),
            Decision(yogurt.line.id, ids["yogurt"], amount=Decimal(375), unit=Unit.G),
        ],
    )
    amounts = {
        i.product_id: i.amount for i in r.SqlPantryRepository(session).for_household(household.id)
    }
    assert amounts == {ids["eggs"]: Decimal(30), ids["yogurt"]: Decimal(375)}


def test_confirming_adds_to_stock_that_is_already_there(session, home, tmp_path):
    household, ids = home
    r.SqlPantryRepository(session).add(
        __import__("annona_core.domain", fromlist=["PantryItem"]).PantryItem(
            household_id=household.id, product_id=ids["rice"], amount=Decimal(250), unit=Unit.G
        )
    )
    view = scan(session, home, "basic", tmp_path=tmp_path)
    confirm_receipt(
        session,
        household,
        view.receipt.id,
        decisions(view, ids, only={"ARROZ REDONDO 1KG": "rice"}),
    )
    [item] = r.SqlPantryRepository(session).for_household(household.id)
    assert item.amount == 1250


def test_a_confirmed_choice_is_remembered_for_next_time(session, home, tmp_path):
    household, ids = home
    first = scan(session, home, "basic", tmp_path=tmp_path)
    # "LECHE SEMI" is the semi-skimmed milk by name, but this household buys whole milk.
    confirm_receipt(
        session,
        household,
        first.receipt.id,
        decisions(first, ids, only={"LECHE SEMI 6X1L": "whole"}),
    )
    second = scan(session, home, "basic", tmp_path=tmp_path / "second")
    milk = by_text(second)["LECHE SEMI 6X1L"]
    assert milk.product.name == "Leche entera Hacendado" and milk.line.confidence == 1
    assert milk.preselected
    assert len(r.ReceiptAliasRepository(session).list(household_id=household.id)) == 1


def test_a_receipt_cannot_be_applied_twice_and_a_scan_can_be_discarded(session, home, tmp_path):
    household, ids = home
    view = scan(session, home, "basic", tmp_path=tmp_path)
    confirm_receipt(session, household, view.receipt.id, [])
    with pytest.raises(ReceiptClosed):
        confirm_receipt(session, household, view.receipt.id, [])
    with pytest.raises(ReceiptClosed):
        discard_receipt(session, household, view.receipt.id)

    other = scan(session, home, "basic", tmp_path=tmp_path / "b")
    photo = Path(other.receipt.image_path)
    assert photo.exists() and photo.with_suffix(".json").exists()
    discard_receipt(session, household, other.receipt.id)
    assert not photo.exists() and not photo.with_suffix(".json").exists()
    closed = r.ReceiptRepository(session).get(other.receipt.id)
    assert closed.status == ReceiptStatus.DISCARDED and closed.image_path is None
    assert r.SqlPantryRepository(session).for_household(household.id) == []


# ------------------------------------------------------------------------------ the API


@pytest.fixture
def api(engine, home, session, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from annona_server.api import create_app

    monkeypatch.setenv("ANNONA_RECEIPTS_DIR", str(tmp_path / "photos"))
    session.commit()
    answers = [(FIXTURES / "basic.json").read_text()] * 3
    app = create_app(
        engine=engine, token="t", llm_factory=lambda s: LLMClient(FakeLLM(answers), MODELS)
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer t"
        yield client


def upload(api, data=PHOTO, name="ticket.png", kind="image/png"):
    return api.post("/api/v1/receipts", files={"file": (name, data, kind)})


def test_api_scan_review_confirm(api, home):
    _, ids = home
    created = upload(api)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "pending_review" and body["total_matches"] is True
    assert (
        body["store_id"] == "mercadona"
        and body["has_image"]
        and body["purchased_on"] == "2026-11-12"
    )
    lines = {ln["raw_text"]: ln for ln in body["lines"]}
    rice = lines["ARROZ REDONDO 1KG"]
    assert rice["product"]["name"] == "Arroz redondo Hacendado" and rice["preselected"]
    assert (rice["proposed_amount"], rice["proposed_unit"], rice["proposed_price_cents"]) == (
        "1000.000",
        "g",
        115,
    )
    assert lines["BOLSA PLASTICO"]["product"] is None and not lines["BOLSA PLASTICO"]["preselected"]
    yogurt = lines["YOGUR NAT."]
    assert yogurt["proposed_amount"] is None and yogurt["notes"] == ["unknown_pack_size"]

    again = api.get(f"/api/v1/receipts/{body['id']}").json()
    assert again["lines"] == body["lines"]  # the review survives closing the app
    photo = api.get(f"/api/v1/receipts/{body['id']}/image")
    assert photo.status_code == 200 and photo.content == PHOTO

    refused = api.post(
        f"/api/v1/receipts/{body['id']}/confirm",
        json={"lines": [{"line_id": yogurt["id"], "product_id": ids["yogurt"]}]},
    )
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "amount_required"
    assert refused.json()["error"]["details"] == [yogurt["id"]]

    ok = api.post(
        f"/api/v1/receipts/{body['id']}/confirm",
        json={
            "lines": [
                {"line_id": rice["id"], "product_id": ids["rice"]},
                {
                    "line_id": yogurt["id"],
                    "product_id": ids["yogurt"],
                    "amount": "375",
                    "unit": "g",
                },
                {"line_id": lines["BOLSA PLASTICO"]["id"], "ignore": True},
            ]
        },
    )
    assert ok.status_code == 200, ok.text
    assert [a["name"] for a in ok.json()["applied"]] == [
        "Arroz redondo Hacendado",
        "Yogur natural Hacendado",
    ]
    assert ok.json()["ignored"] == 4
    pantry = {p["product_id"]: p["amount"] for p in api.get("/api/v1/pantry").json()["items"]}
    assert Decimal(pantry[ids["rice"]]) == 1000 and Decimal(pantry[ids["yogurt"]]) == 375

    closed = api.post(f"/api/v1/receipts/{body['id']}/confirm", json={"lines": []})
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "receipt_closed"


def test_api_rejects_what_is_not_a_photo_and_discard_removes_it(api):
    assert upload(api, b"hello", "x.txt", "text/plain").status_code == 422
    assert upload(api, b"hello", "x.png", "image/png").json()["error"]["code"] == "bad_image"
    created = upload(api).json()
    assert api.post(f"/api/v1/receipts/{created['id']}/discard").status_code == 204
    assert api.get(f"/api/v1/receipts/{created['id']}/image").status_code == 404
    assert api.post(f"/api/v1/receipts/{created['id']}/discard").status_code == 409
    assert api.get("/api/v1/receipts/999").status_code == 404
