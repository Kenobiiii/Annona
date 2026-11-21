# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from annona_core.domain import Category, CategorySource
from annona_server.ingest.classify import (
    ClassificationInput,
    LLMClassifierStub,
    RuleClassifier,
    classify,
)

RULES = RuleClassifier()


@pytest.mark.parametrize(
    ("name", "path", "off", "category", "kind"),
    [
        # Store path, deepest level first (top level "Huevos, leche y mantequilla" is ambiguous).
        (
            "Leche semidesnatada Hacendado",
            ("Huevos, leche y mantequilla", "Leche y bebidas vegetales", "Leche semidesnatada"),
            (),
            Category.DAIRY,
            "milk",
        ),
        (
            "Arroz redondo Hacendado",
            ("Arroz, legumbres y pasta", "Arroz"),
            (),
            Category.GRAINS,
            "rice",
        ),
        # OFF tags: dairies win over beverages for a milkshake.
        (
            "Batido cacao 0%",
            (),
            ("en:beverages", "en:dairies"),
            Category.DAIRY,
            "milkshake",
        ),
        # Name only, accent-insensitive.
        ("Lentejas pardinas", (), (), Category.LEGUMES, "lentils"),
        ("Atún claro en aceite", (), (), Category.FISH, "tuna"),
        ("Aceite de oliva virgen extra", (), (), Category.OILS_FATS, "olive_oil"),
    ],
)
def test_rules(name, path, off, category, kind):
    result = RULES.classify(ClassificationInput(name, path, off))
    assert result is not None
    assert (result.category, result.type, result.source) == (category, kind, CategorySource.RULE)


def test_word_boundaries_avoid_false_matches():
    # "panela" must not match "pan ", "nata" inside "natación" style words must not match either.
    assert RULES.classify(ClassificationInput("Panela ecológica")) is None


def test_unknown_products_fall_through_to_the_llm_stub():
    item = ClassificationInput("Producto misterioso XYZ")
    assert classify(item, [RULES, LLMClassifierStub()]) is None


@pytest.mark.parametrize(
    ("name", "path", "category", "kind"),
    [
        # Real Mercadona cases found in the Phase 6 demo.
        (
            "Patatas fritas clásicas Hacendado",
            ("Aperitivos", "Patatas fritas y snacks"),
            Category.OTHER,
            "crisps",
        ),
        (
            "Queso fresco batido desnatado 0% MG",
            (),
            Category.DAIRY,
            "cheese",
        ),
        ("Brócoli", ("Fruta y verdura", "Verdura"), Category.VEGETABLES, "broccoli"),
        ("Calabacín verde", ("Fruta y verdura", "Verdura"), Category.VEGETABLES, "zucchini"),
        ("Pimiento rojo", ("Fruta y verdura", "Verdura"), Category.VEGETABLES, "pepper"),
    ],
)
def test_demo_regressions(name, path, category, kind):
    result = RULES.classify(ClassificationInput(name, path))
    assert (result.category, result.type) == (category, kind)
