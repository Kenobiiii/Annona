# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn offers and pantry items into solver-ready candidates (pure, no solver here).

Everything is expressed in the product's *nutrition basis unit* (g or ml, per 100 of which the
nutrition values are given). Conversions use product data; when a mass<->volume conversion lacks
a density, ``assumed_density_g_per_ml`` is used and the candidate is flagged ``estimated``.
Products that cannot be used (no nutrition, sold by the unit without a unit weight, no package
size) are excluded and reported, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from annona_core.domain import (
    Category,
    NutritionSource,
    PantryItem,
    Product,
    Quantity,
    Unit,
    UnitConversionError,
)
from annona_core.nutrition import check_product

from .models import AllergenNote, DataWarning, Problem

FRUIT_VEG = {Category.FRUIT, Category.VEGETABLES}


@dataclass
class Candidate:
    product: Product
    price_cents: int
    basis: Unit  # g or ml
    pack_basis: Decimal  # one pack, in basis units
    stock_basis: Decimal  # available in the pantry, in basis units
    kcal: Decimal  # per basis unit
    protein: Decimal
    fat: Decimal
    carbs: Decimal
    salt: Decimal | None  # per basis unit; None = unknown
    saturated_fat: Decimal | None
    fruit_veg: bool
    estimated: bool = False
    not_for: list[AllergenNote] = field(default_factory=list)


def _to_basis(
    quantity: Quantity, product: Product, basis: Unit, assumed_density: Decimal
) -> tuple[Decimal, bool]:
    """Amount in ``basis`` units; second value True if an assumed density was used."""
    density = product.density_g_per_ml
    estimated = False
    needs_density = {quantity.unit, basis} >= {Unit.G, Unit.ML} or (
        quantity.unit == Unit.UNIT and basis == Unit.ML
    )
    if needs_density and density is None:
        density, estimated = assumed_density, True
    converted = quantity.to(basis, density_g_per_ml=density, unit_weight_g=product.unit_weight_g)
    return converted.amount, estimated


def prepare(problem: Problem) -> tuple[list[Candidate], list[DataWarning]]:
    settings = problem.settings
    warnings: list[DataWarning] = []
    stock: dict[int, list[PantryItem]] = {}
    for item in problem.pantry:
        stock.setdefault(item.product_id, []).append(item)

    candidates: list[Candidate] = []
    for offer in sorted(problem.offers, key=lambda o: o.product.id or 0):
        product = offer.product
        pid = product.id or 0

        def warn(issue: str, detail: str, product: Product = product, pid: int = pid) -> None:
            warnings.append(
                DataWarning(product_id=pid, name=product.name, issue=issue, detail=detail)
            )

        if product.nutrition is None:
            warn("excluded_no_nutrition", "no nutrition data: add it (label scan or manual)")
            continue
        if product.package is None:
            warn("excluded_no_package", "unknown package size")
            continue
        basis = product.nutrition.basis
        try:
            pack_basis, density_used = _to_basis(
                product.package, product, basis, settings.assumed_density_g_per_ml
            )
            stock_basis = Decimal(0)
            for item in stock.get(pid, []):
                amount, est = _to_basis(
                    item.quantity, product, basis, settings.assumed_density_g_per_ml
                )
                stock_basis += amount
                density_used = density_used or est
        except UnitConversionError:
            warn("excluded_no_unit_weight", "sold by the unit without a weight per unit: add it")
            continue
        if pack_basis <= 0:
            warn("excluded_no_package", "package size is zero")
            continue
        estimated = density_used
        if product.store_id is not None and product.nutrition.source == NutritionSource.SAMPLE:
            estimated = True
            warn(
                "nutrition_sample",
                "approximate nutrition from a generic reference food: scan the label for exact "
                "values",
            )
        if settings.health_limits:
            if product.nutrition.salt_g is None:
                warn("salt_unknown", "salt unknown: counted as 0 for the salt limit")
            if product.nutrition.saturated_fat_g is None:
                warn(
                    "saturated_fat_unknown",
                    "saturated fat unknown: counted as 0 for the saturated-fat limit",
                )
        if density_used:
            warn(
                "density_estimated",
                f"volume/mass conversion assumed {settings.assumed_density_g_per_ml} g/ml: "
                "add the real density for exact results",
            )

        notes = []
        for member in problem.members:
            decision = check_product(product, member)
            if not decision.allowed:
                reasons = [
                    f"{r}: {', '.join(decision.allergens_found)}"
                    if r == "contains_allergen"
                    else str(r)
                    for r in decision.reasons
                ]
                notes.append(AllergenNote(member=member.name, reasons=reasons))
        if problem.members and len(notes) == len(problem.members):
            warn("excluded_nobody_can_eat", "no household member can eat it")
            continue

        n = product.nutrition
        hundred = Decimal(100)
        candidates.append(
            Candidate(
                product=product,
                price_cents=offer.price_cents,
                basis=basis,
                pack_basis=pack_basis,
                stock_basis=stock_basis,
                kcal=n.energy_kcal / hundred,
                protein=n.protein_g / hundred,
                fat=n.fat_g / hundred,
                carbs=n.carbohydrates_g / hundred,
                salt=None if n.salt_g is None else n.salt_g / hundred,
                saturated_fat=None if n.saturated_fat_g is None else n.saturated_fat_g / hundred,
                fruit_veg=product.category in FRUIT_VEG
                and (product.type or "") not in settings.starchy_types,
                estimated=estimated,
                not_for=notes,
            )
        )
    return candidates, warnings
