# SPDX-License-Identifier: AGPL-3.0-or-later
"""Demo mode: an invented store and a scripted "AI", to try Annona with no store data and no key.

* :func:`load_demo_store` adds a store called ``demo`` with INVENTED prices (nutrition comes from
  the bundled USDA sample foods). Never use it to plan real shopping.
* ``ANNONA_FAKE_LLM=1`` makes the server answer plans, recipes and replacements with deterministic,
  valid but generic dishes instead of calling an AI provider. For trying the app, demos and CI.
  Receipt reading and product classification need a real model and are refused in this mode.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session

from annona_core.agent import AgentMessage, ModelReply, TextDelta, ToolSpec
from annona_core.domain import NutritionFacts, Price, PriceSource, Product, Unit
from annona_core.llm import FakeLLM, LLMBackend

from .db.repositories import SqlPriceRepository, SqlProductRepository
from .seed import sample_foods

STORE = "demo"
# sample food key -> (Spanish name, pack grams, price in cents). Prices are invented.
CATALOGUE = {
    "rice_white": ("Arroz redondo", 1000, 115),
    "pasta_dry": ("Macarrón", 500, 90),
    "oats": ("Copos de avena", 800, 130),
    "lentils": ("Lenteja pardina", 1000, 185),
    "chickpeas": ("Garbanzos secos", 1000, 190),
    "egg": ("Huevos", 720, 590),
    "chicken_breast": ("Filetes de pechuga de pollo", 550, 424),
    "tuna_oil": ("Atún en aceite", 300, 420),
    "milk_whole": ("Leche entera", 6000, 498),
    "yogurt_plain": ("Yogur natural", 500, 105),
    "olive_oil": ("Aceite de oliva", 900, 899),
    "potato": ("Patatas", 3000, 250),
    "onion": ("Cebollas", 1000, 150),
    "tomato": ("Tomates", 1000, 190),
    "banana": ("Plátanos", 1000, 190),
    "spinach": ("Espinacas", 500, 160),
    "carrot": ("Zanahorias", 1000, 120),
    "apple": ("Manzanas", 1000, 210),
}

SHARES = {"breakfast": 0.25, "lunch": 0.35, "snack": 0.10, "dinner": 0.30}
# "id | name | group | unit | available | planned | kcal/100 | protein/100 | not for"
PRODUCT_ROW = re.compile(
    r"^(\d+) \| [^|]+ \| \w+ \| \w+ \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|", re.M
)


def load_demo_store(session: Session) -> int:
    """Add the demo store's products and prices (idempotent). The caller commits."""
    foods = {f["key"]: f for f in sample_foods()}
    products, prices = SqlProductRepository(session), SqlPriceRepository(session)
    added = 0
    for n, (key, (name, pack, cents)) in enumerate(CATALOGUE.items()):
        if products.get_by_store_sku(STORE, str(n)) is not None:
            continue
        f = foods[key]
        product = products.add(
            Product(
                name=name,
                category=f["category"],
                type=f["type"],
                store_id=STORE,
                store_sku=str(n),
                package_amount=Decimal(pack),
                package_unit=Unit.G,
                allergens=f["allergens"],
                unit_weight_g=f.get("unit_weight_g"),
                density_g_per_ml=f.get("density_g_per_ml"),
                nutrition=NutritionFacts.model_validate(f["nutrition"]),
            )
        )
        assert product.id is not None
        prices.add(
            Price(
                product_id=product.id,
                store_id=STORE,
                amount_cents=cents,
                source=PriceSource.MANUAL,
                observed_at=datetime.now(UTC),
            )
        )
        added += 1
    return added


# ---------------------------------------------------------------------------------------------
# The scripted "AI"
# ---------------------------------------------------------------------------------------------


def plan_answer(request) -> str:
    """A valid menu: every meal uses every product, split by each slot's share of the day."""
    text = request.messages[0].text
    products = [(int(m.group(1)), Decimal(m.group(3))) for m in PRODUCT_ROW.finditer(text)]
    slots = []
    for m in re.finditer(r"^- weekday (\d) \([^)]*\): (.+)$", text, re.M):
        slots += [(int(m.group(1)), s.strip()) for s in m.group(2).split(",")]
    total = sum(SHARES[s] for _, s in slots)
    names = {"breakfast": "Desayuno", "lunch": "Comida", "snack": "Merienda", "dinner": "Cena"}
    meals = [
        {
            "weekday": wd,
            "slot": slot,
            "title": f"{names[slot]} {i + 1}",
            "appliances": ["hob"],
            "ingredients": [
                {
                    "product_id": pid,
                    "amount": str(planned * Decimal(SHARES[slot] / total) * Decimal("0.97")),
                }
                for pid, planned in products
                if planned > 0
            ][:10],
            "summary": "Cocinar a fuego medio.",
        }
        for i, (wd, slot) in enumerate(slots)
    ]
    return json.dumps({"meals": meals})


def recipe_answer(request) -> str:
    text = request.messages[0].text
    ids = [int(m.group(1)) for m in re.finditer(r"^(\d+) \| [^|]+ \| [\d,.]+ \w+$", text, re.M)]
    steps = [
        {"text": f"Cocina {{p{pid}}}.", "appliance": "hob", "heat": "medium", "minutes": 5}
        for pid in ids
    ]
    return json.dumps({"steps": steps})


def swap_answer(request) -> str:
    """A sensible replacement: the leftover products richest in protein, cooked on the hob."""
    text = request.messages[0].text
    rows = [
        (int(m.group(1)), Decimal(m.group(2)), int(m.group(5))) for m in PRODUCT_ROW.finditer(text)
    ]
    products = [(pid, amount) for pid, amount, _ in sorted(rows, key=lambda r: -r[2])[:4]]
    day = int(re.search(r"^- weekday (\d)", text, re.M).group(1))  # type: ignore[union-attr]
    slot = re.search(r"^- weekday \d \([^)]*\): (\w+)", text, re.M).group(1)  # type: ignore[union-attr]
    return json.dumps(
        {
            "meals": [
                {
                    "weekday": day,
                    "slot": slot,
                    "title": "Plato de sustitución",
                    "appliances": ["hob"],
                    "ingredients": [
                        {"product_id": pid, "amount": str(min(amount / 4, Decimal(150)))}
                        for pid, amount in products
                    ],
                    "summary": "Cocinar a fuego medio.",
                }
            ]
        }
    )


def demo_responder(request) -> str:
    if request.task == "recipe_of_the_day":
        return recipe_answer(request)
    if request.task == "swap_meal":
        return swap_answer(request)
    if request.task.startswith("plan_week"):
        return plan_answer(request)
    raise RuntimeError(
        f"demo mode (ANNONA_FAKE_LLM) cannot do {request.task!r}: configure a real AI provider"
    )


def fake_llm_enabled() -> bool:
    return os.environ.get("ANNONA_FAKE_LLM", "").lower() in ("1", "true", "yes")


def demo_backend() -> LLMBackend:
    return FakeLLM(responder=demo_responder)


class DemoChatModel:
    """The chat in demo mode: it says what it needs, because there is no model behind it."""

    def stream(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec], *, max_tokens: int
    ):
        text = (
            "Modo demo: el chat necesita una IA real. Configura tu proveedor en el archivo .env "
            "y desactiva ANNONA_FAKE_LLM."
        )
        yield TextDelta(text)
        yield ModelReply(text=text, model="demo")
