# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic receipts with known ground truth, rendered as photos of different difficulty.

Everything here is invented (names, prices, stores): no real receipt, no private data. A receipt
is generated from a seed, so a run is reproducible and two models can be compared on the same
images. Difficulty imitates what phones produce: ``clean`` (a flat scan), ``noisy`` (slight
rotation, blur, JPEG, paper texture) and ``hard`` (faded thermal print, strong blur, shadow, skew).

Pillow is an eval-only (development) dependency.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

RENDERER_VERSION = "1"

# (product id, catalogue name, printed forms, pack price in cents, weighed price per kg or None)
# The catalogue names and prices are invented. Printed forms imitate abbreviated receipt text.
PRODUCTS: list[tuple[int, str, list[str], int, int | None]] = [
    (1, "Arroz redondo Hacendado", ["ARROZ REDONDO 1KG", "ARROZ REDONDO"], 115, None),
    (2, "Macarrón Hacendado", ["MACARRON 500G", "MACARRON HACENDADO"], 90, None),
    (3, "Espagueti Hacendado", ["ESPAGUETI 500G", "SPAGHETTI"], 90, None),
    (4, "Leche semidesnatada Hacendado", ["LECHE SEMI 6X1L", "LECHE SEMIDESN."], 498, None),
    (5, "Leche entera Hacendado", ["LECHE ENTERA 6X1L", "LECHE ENT."], 498, None),
    (6, "Yogur natural Hacendado", ["YOGUR NAT.", "YOGUR NATURAL 4X125"], 105, None),
    (7, "Yogur de fresa Hacendado", ["YOGUR FRESA", "YOGUR FRESA 4X125G"], 110, None),
    (8, "Huevos", ["HUEVOS 30 L", "HUEVOS GRANDES 30"], 590, None),
    (9, "Filetes pechuga de pollo", ["FILETE PECHUGA POLLO", "FIL.PECH.POLLO"], 424, 770),
    (10, "Muslos de pollo", ["MUSLO POLLO BANDEJA", "MUSLOS POLLO"], 380, 520),
    (
        11,
        "Atún claro al natural Hacendado",
        ["ATUN CLARO NAT. P3", "ATUN CLARO NATURAL"],
        420,
        None,
    ),
    (12, "Lenteja pardina Hacendado", ["LENTEJA PARDINA 1KG", "LENTEJAS PARDINAS"], 185, None),
    (13, "Garbanzo cocido Hacendado", ["GARBANZO COCIDO", "GARBANZOS COC. 400G"], 90, None),
    (14, "Copos de avena", ["COPOS AVENA 800G", "AVENA COPOS"], 130, None),
    (
        15,
        "Pan de molde integral Hacendado",
        ["PAN MOLDE INTEGRAL", "PAN M. INTEGRAL AVENA"],
        150,
        None,
    ),
    (16, "Aceite de oliva virgen extra Hacendado", ["AOVE 1L", "ACEITE OLIVA V.EXTRA"], 899, None),
    (17, "Tomate frito Hacendado", ["TOMATE FRITO 400G", "TOMATE FRITO"], 80, None),
    (18, "Plátano de Canarias", ["PLATANO CANARIAS", "PLATANOS"], 190, 190),
    (19, "Manzanas Golden", ["MANZANA GOLDEN", "MANZANAS GOLDEN KG"], 210, 210),
    (20, "Naranjas", ["NARANJA MESA", "NARANJAS KG"], 150, 150),
    (21, "Cebollas", ["CEBOLLA MALLA 1KG", "CEBOLLAS"], 150, None),
    (22, "Zanahorias", ["ZANAHORIA BOLSA 1KG", "ZANAHORIAS"], 100, None),
    (23, "Brócoli", ["BROCOLI", "BROCOLI BANDEJA"], 180, None),
    (
        24,
        "Queso fresco batido 0% Hacendado",
        ["QUESO F.BATIDO 0%", "QUESO FRESCO BATIDO"],
        110,
        None,
    ),
    (25, "Almendra natural Hacendado", ["ALMENDRA NATURAL", "ALMENDRAS NAT. 200G"], 230, None),
    (26, "Patatas fritas Hacendado", ["PATATAS FRITAS", "PATATAS FRIT. CLASICAS"], 120, None),
    (27, "Galletas María Hacendado", ["GALLETAS MARIA", "GALLETAS MARIA 800G"], 160, None),
    (28, "Agua mineral 6x1,5L", ["AGUA MINERAL 6X1,5L", "AGUA MIN. PACK 6"], 270, None),
]
NON_PRODUCT_LINES = ["BOLSA PLASTICO", "BOLSA COMPRA"]  # bought, but not catalogue food
POSTAL_CODE = "29010"  # printed in every synthetic shop address
STORES = ["MERCADONA S.A.", "SUPERMERCADOS EJEMPLO S.L.", "SUPER DEMO S.A."]
CATALOGUE_NAMES = {pid: name for pid, name, *_ in PRODUCTS}
_CENT = Decimal("0.01")


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100},{abs(cents) % 100:02d}"


@dataclass(frozen=True)
class TrueLine:
    printed: str
    total_cents: int
    product_id: int | None  # None for a bag
    quantity: int | None = None
    unit_price_cents: int | None = None
    weight_g: int | None = None


@dataclass
class SyntheticReceipt:
    id: str
    difficulty: str
    store: str
    purchased_on: date
    lines: list[TrueLine]
    discount_cents: int  # <= 0
    total_cents: int
    seed: int
    extras: list[str] = field(default_factory=list)  # distractor lines printed on the photo

    def spec(self) -> dict:
        return {
            "id": self.id,
            "difficulty": self.difficulty,
            "store": self.store,
            "date": self.purchased_on.isoformat(),
            "total_cents": self.total_cents,
            "discount_cents": self.discount_cents,
            "lines": [vars(line) for line in self.lines],
        }


def make_receipts(n: int = 12, seed: int = 7) -> list[SyntheticReceipt]:
    """``n`` receipts, a third of each difficulty, reproducible from ``seed``."""
    rng = random.Random(seed)
    levels = ["clean", "noisy", "hard"]
    receipts = []
    for i in range(n):
        lines: list[TrueLine] = []
        for pid, _name, forms, price, per_kg in rng.sample(PRODUCTS, rng.randint(7, 13)):
            printed = rng.choice(forms)
            roll = rng.random()
            if per_kg is not None and roll < 0.7:
                grams = rng.randrange(250, 1400, 10)
                total = int((Decimal(per_kg) * grams / 1000).quantize(Decimal(1), ROUND_HALF_UP))
                lines.append(TrueLine(printed, total, pid, weight_g=grams, unit_price_cents=per_kg))
            elif roll < 0.35:
                qty = rng.choice([2, 2, 3])
                lines.append(
                    TrueLine(printed, qty * price, pid, quantity=qty, unit_price_cents=price)
                )
            else:
                lines.append(TrueLine(printed, price, pid, quantity=None))
        if rng.random() < 0.5:
            lines.append(TrueLine(rng.choice(NON_PRODUCT_LINES), 5, None))
        rng.shuffle(lines)
        discount = -rng.choice([20, 30, 50, 100]) if rng.random() < 0.25 else 0
        total = sum(ln.total_cents for ln in lines) + discount
        receipts.append(
            SyntheticReceipt(
                id=f"r{i + 1:02d}",
                difficulty=levels[i % 3],
                store=rng.choice(STORES),
                purchased_on=date(2026, 11, 1) + timedelta(days=rng.randrange(0, 21)),
                lines=lines,
                discount_cents=discount,
                total_cents=total,
                seed=rng.randrange(10**6),
                extras=[
                    f"OP: {rng.randrange(1000, 9999)}   TERMINAL {rng.randrange(10, 99)}",
                    "IVA   BASE    CUOTA",
                    f"10%   {money(total * 90 // 100)}   {money(total * 10 // 100)}",
                    f"TARJETA BANCARIA  {money(total)}",
                    "GRACIAS POR SU VISITA",
                ],
            )
        )
    return receipts


def receipt_lines(r: SyntheticReceipt) -> list[str]:
    """The text rows of the receipt, as a thermal printer would lay them out."""
    out = [
        r.store,
        f"AV. DEL EJEMPLO 1   {POSTAL_CODE} MALAGA",
        f"{r.purchased_on:%d/%m/%Y} 18:42  OP: 1234",
        "",
    ]
    out.append("DESCRIPCION          P.UNIT    IMPORTE")
    for line in r.lines:
        if line.weight_g:
            kilos = f"{line.weight_g / 1000:.3f}".replace(".", ",")
            out.append(f"1 {line.printed:<24}{money(line.total_cents):>9}")
            out.append(f"  {kilos} kg   {money(line.unit_price_cents or 0)} EUR/kg")
        elif line.quantity:
            each, total = money(line.unit_price_cents or 0), money(line.total_cents)
            out.append(f"{line.quantity} {line.printed:<22}{each:>7}{total:>9}")
        else:
            out.append(f"1 {line.printed:<24}{money(line.total_cents):>9}")
    if r.discount_cents:
        out.append(f"  DESCUENTO{money(r.discount_cents):>23}")
    out += ["", f"TOTAL (EUR){money(r.total_cents):>22}", *r.extras]
    return out


def render(r: SyntheticReceipt, *, quality: int | None = None) -> bytes:
    """The receipt as a JPEG photo, degraded according to its difficulty."""
    try:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
    except ImportError as error:  # pragma: no cover
        raise SystemExit(
            "receipt evals need Pillow: run with `uv run` in the repo (dev group)"
        ) from error

    rng = random.Random(r.seed)
    rows = receipt_lines(r)
    font = ImageFont.load_default(size=22)
    width, height = 700, 60 + 30 * len(rows)
    paper = (250, 250, 246) if r.difficulty == "clean" else (238, 236, 228)
    img = Image.new("RGB", (width, height), paper)
    draw = ImageDraw.Draw(img)
    ink = {"clean": (10, 10, 10), "noisy": (35, 35, 35), "hard": (95, 95, 95)}[r.difficulty]
    for i, row in enumerate(rows):
        draw.text((30, 30 + 30 * i), row, fill=ink, font=font)
    if r.difficulty != "clean":
        for _ in range(width * height // 90):  # paper speckle
            x, y = rng.randrange(width), rng.randrange(height)
            g = rng.randrange(150, 215)
            draw.point((x, y), fill=(g, g, g))
        img = img.filter(ImageFilter.GaussianBlur({"noisy": 0.7, "hard": 1.2}[r.difficulty]))
        angle = rng.uniform(-2, 2) if r.difficulty == "noisy" else rng.uniform(-4.5, 4.5)
        img = img.rotate(angle, expand=True, fillcolor=(205, 200, 190), resample=Image.BICUBIC)
    if r.difficulty == "hard":
        shear = rng.uniform(-0.06, 0.06)
        img = img.transform(
            img.size, Image.AFFINE, (1, shear, 0, 0, 1, 0), Image.BICUBIC, fillcolor=(205, 200, 190)
        )
        img = ImageEnhance.Contrast(img).enhance(0.75)  # faded thermal print
        shadow = Image.linear_gradient("L").resize(img.size).point(lambda v: 255 - v // 4)
        img = Image.composite(img, Image.new("RGB", img.size, (120, 118, 112)), shadow)
    img = img.convert("RGB")
    jpeg_quality = quality or {"clean": 90, "noisy": 60, "hard": 40}[r.difficulty]
    buffer = io.BytesIO()
    img.save(buffer, "JPEG", quality=jpeg_quality)
    return buffer.getvalue()
