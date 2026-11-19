# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build ``server/src/annona_server/seed/sample_foods.json`` from USDA FoodData Central.

Source: USDA FoodData Central, SR Legacy (April 2018 release), public domain (CC0 1.0).
https://fdc.nal.usda.gov/download-datasets

Every number in the output comes from the dataset. Only two values are *derived*, by code:

* salt_g = sodium_mg * 2.5 / 1000 (EU Regulation 1169/2011, Annex XIV);
* density_g_per_ml = USDA gram weight of "1 cup" / 236.5882365 ml (one US cup).

Usage:
    uv run python scripts/build_usda_seed.py [--zip PATH]          # build the seed file
    uv run python scripts/build_usda_seed.py --zip PATH --search rice   # find fdc ids
Without --zip the dataset (~6 MB) is downloaded to a temporary directory.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

DATASET_URL = (
    "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip"
)
DATASET_NAME = "USDA FoodData Central SR Legacy 2018-04"
OUTPUT = Path(__file__).resolve().parent.parent / "server/src/annona_server/seed/sample_foods.json"
US_CUP_ML = Decimal("236.5882365")
SODIUM_TO_SALT = Decimal("2.5")

# FDC nutrient id -> our field
NUTRIENTS = {
    "1008": "energy_kcal",
    "1003": "protein_g",
    "1004": "fat_g",
    "1258": "saturated_fat_g",
    "1005": "carbohydrates_g",
    "2000": "sugars_g",
    "1079": "fiber_g",
    "1093": "sodium_mg",
}
REQUIRED = ("energy_kcal", "protein_g", "fat_g", "carbohydrates_g")


@dataclass(frozen=True)
class Food:
    key: str
    name: str
    category: str
    type: str
    fdc_id: str
    allergens: tuple[str, ...] = ()
    unit_portion: str | None = None  # USDA portion used as "one unit", e.g. "large"
    density: bool = False  # derive density from the USDA "1 cup" portion
    extra: dict[str, str] = field(default_factory=dict)


# Curated list (selected by description in the dataset). Allergens follow the EU 14.
FOODS: tuple[Food, ...] = (
    Food("rice_white", "White rice, long grain, raw", "grains", "rice", "169756"),
    Food("pasta_dry", "Pasta, dry", "grains", "pasta", "168927", ("gluten",)),
    Food("oats", "Rolled oats", "grains", "oats", "173904", ("gluten",)),
    Food("bread_white", "White bread", "bakery", "bread", "174924", ("gluten",)),
    Food("lentils", "Lentils, dry", "legumes", "lentils", "172420"),
    Food("chickpeas", "Chickpeas, dry", "legumes", "chickpeas", "173756"),
    Food("white_beans", "White beans, dry", "legumes", "beans", "175202"),
    Food("egg", "Egg, whole, raw", "eggs", "egg", "171287", ("eggs",), unit_portion="large"),
    Food("chicken_breast", "Chicken breast, skinless, raw", "meat", "chicken", "171077"),
    Food("pork_loin", "Pork loin, lean, raw", "meat", "pork", "168230"),
    Food("beef_ground", "Ground beef 85/15, raw", "meat", "beef", "171796"),
    Food("tuna_oil", "Tuna in oil, canned, drained", "fish", "tuna", "173708", ("fish",)),
    Food("sardines_oil", "Sardines in oil, canned", "fish", "sardines", "175139", ("fish",)),
    Food("salmon", "Salmon, Atlantic, farmed, raw", "fish", "salmon", "175167", ("fish",)),
    Food("cod", "Cod, raw", "fish", "cod", "171955", ("fish",)),
    Food("milk_whole", "Whole milk", "dairy", "milk", "171265", ("milk",), density=True),
    Food("yogurt_plain", "Plain yogurt, whole milk", "dairy", "yogurt", "171284", ("milk",)),
    Food("cheese_fresh", "Fresh cheese (queso fresco)", "dairy", "cheese", "172223", ("milk",)),
    Food("olive_oil", "Olive oil", "oils_fats", "olive_oil", "171413", density=True),
    Food("butter", "Butter, salted", "oils_fats", "butter", "173410", ("milk",)),
    Food(
        "potato",
        "Potato, raw",
        "vegetables",
        "potato",
        "170026",
        unit_portion='Potato medium (2-1/4" to 3-1/4" dia)',
    ),
    Food(
        "onion", "Onion, raw", "vegetables", "onion", "170000", unit_portion='medium (2-1/2" dia)'
    ),
    Food(
        "tomato",
        "Tomato, raw",
        "vegetables",
        "tomato",
        "170457",
        unit_portion='medium whole (2-3/5" dia)',
    ),
    Food("carrot", "Carrot, raw", "vegetables", "carrot", "170393", unit_portion="medium"),
    Food("spinach", "Spinach, raw", "vegetables", "spinach", "168462"),
    Food("lettuce", "Romaine lettuce, raw", "vegetables", "lettuce", "169247"),
    Food(
        "red_pepper",
        "Red bell pepper, raw",
        "vegetables",
        "pepper",
        "170108",
        unit_portion='medium (approx 2-3/4" long, 2-1/2 dia.)',
    ),
    Food(
        "banana", "Banana", "fruit", "banana", "173944", unit_portion='medium (7" to 7-7/8" long)'
    ),
    Food("apple", "Apple, with skin", "fruit", "apple", "171688", unit_portion='medium (3" dia)'),
    Food("orange", "Orange", "fruit", "orange", "169097", unit_portion='fruit (2-5/8" dia)'),
    Food("almonds", "Almonds", "nuts_seeds", "almonds", "170567", ("nuts",)),
)


def _csv(zf: zipfile.ZipFile, name: str) -> csv.DictReader:
    member = next(n for n in zf.namelist() if n.endswith("/" + name))
    return csv.DictReader(io.TextIOWrapper(zf.open(member), encoding="utf-8"))


def _open_dataset(path: Path | None) -> zipfile.ZipFile:
    if path is None:
        path = Path(tempfile.mkdtemp(prefix="usda-")) / "sr_legacy.zip"
        print(f"downloading {DATASET_URL}")
        urllib.request.urlretrieve(DATASET_URL, path)
    return zipfile.ZipFile(path)


def search(zf: zipfile.ZipFile, text: str) -> None:
    needle = text.lower()
    for row in _csv(zf, "food.csv"):
        if needle in row["description"].lower():
            print(row["fdc_id"], row["description"])


def build(zf: zipfile.ZipFile) -> dict:
    ids = {f.fdc_id for f in FOODS}
    descriptions = {
        r["fdc_id"]: r["description"] for r in _csv(zf, "food.csv") if r["fdc_id"] in ids
    }
    values: dict[str, dict[str, Decimal]] = {i: {} for i in ids}
    for r in _csv(zf, "food_nutrient.csv"):
        if r["fdc_id"] in ids and r["nutrient_id"] in NUTRIENTS:
            values[r["fdc_id"]][NUTRIENTS[r["nutrient_id"]]] = Decimal(r["amount"])
    portions: dict[str, dict[str, Decimal]] = {i: {} for i in ids}
    for r in _csv(zf, "food_portion.csv"):
        if r["fdc_id"] in ids:
            label = " ".join(p for p in (r["modifier"], r["portion_description"]) if p).strip()
            if r["amount"] in ("1", "1.0"):
                portions[r["fdc_id"]][label] = Decimal(r["gram_weight"])

    foods = []
    for f in FOODS:
        if f.fdc_id not in descriptions:
            raise SystemExit(f"{f.key}: fdc_id {f.fdc_id} not in dataset")
        v = values[f.fdc_id]
        missing = [n for n in REQUIRED if n not in v]
        if missing:
            raise SystemExit(f"{f.key}: missing required nutrients {missing}")
        sodium = v.pop("sodium_mg", None)
        nutrition = {k: str(val) for k, val in v.items()}
        if sodium is not None:
            nutrition["salt_g"] = str(sodium * SODIUM_TO_SALT / 1000)
        item: dict = {
            "key": f.key,
            "name": f.name,
            "category": f.category,
            "type": f.type,
            "allergens": list(f.allergens),
            "usda_description": descriptions[f.fdc_id],
            "nutrition": {
                "basis": "g",
                **nutrition,
                "source": "sample",
                "source_ref": f"usda-fdc:{f.fdc_id}",
            },
        }
        if f.unit_portion:
            if f.unit_portion not in portions[f.fdc_id]:
                raise SystemExit(f"{f.key}: portion {f.unit_portion!r} not found")
            item["unit_weight_g"] = str(portions[f.fdc_id][f.unit_portion])
            item["unit_portion"] = f.unit_portion
        if f.density:
            cup = portions[f.fdc_id].get("cup")
            if cup is None:
                raise SystemExit(f"{f.key}: no '1 cup' portion to derive density")
            item["density_g_per_ml"] = str((cup / US_CUP_ML).quantize(Decimal("0.001")))
        foods.append(item)

    return {
        "notice": (
            "SAMPLE DATA for development and demos. Generic foods, not products of any store. "
            "Nutrition per 100 g of edible portion."
        ),
        "source": DATASET_NAME,
        "source_url": "https://fdc.nal.usda.gov/download-datasets",
        "licence": "Public domain (CC0 1.0), U.S. Department of Agriculture",
        "derived_values": {
            "salt_g": "sodium_mg * 2.5 / 1000 (EU 1169/2011)",
            "density_g_per_ml": "USDA '1 cup' gram weight / 236.5882365 ml",
        },
        "foods": foods,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--zip", type=Path, help="local copy of the SR Legacy CSV zip")
    parser.add_argument("--search", help="print fdc ids whose description contains this text")
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    with _open_dataset(args.zip) as zf:
        if args.search:
            search(zf, args.search)
            return
        data = build(zf)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(data['foods'])} foods to {args.output}")


if __name__ == "__main__":
    main()
