# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compute this week's cheapest shop for a household at one store.

python -m annona_server.optimize --household 1 --store mercadona [--budget 60]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal

from annona_core.optimizer import Result, optimise

from ..config import load_env
from ..db import migrate
from ..db.engine import database_url, make_engine, session_scope
from ..db.repositories import NotFoundError
from . import build_problem


def money(cents: int | Decimal) -> str:
    return f"{Decimal(cents) / 100:.2f}"


def report(result: Result, budget_cents: int) -> str:
    out = [f"status: {result.status}"]
    if result.lines:
        out.append(
            f"shopping list ({money(result.total_cost_cents)} {result.currency} of "
            f"{money(budget_cents)} budget):"
        )
        for line in sorted(result.lines, key=lambda x: -x.cost_cents):
            flags = []
            if line.used_from_pantry:
                flags.append(f"uses {line.used_from_pantry:.0f} {line.basis_unit} from pantry")
            if line.estimated:
                flags.append("ESTIMATED conversion")
            for note in line.not_for:
                flags.append(f"NOT for {note.member} ({'; '.join(note.reasons)})")
            extra = f"  [{' | '.join(flags)}]" if flags else ""
            out.append(
                f"  {line.packs_to_buy:>2} x {line.name:<45} {money(line.cost_cents):>7}{extra}"
            )
    if result.daily_average:
        d = result.daily_average
        out.append(
            f"daily average: {d.energy_kcal} kcal, protein {d.protein_g} g, fat {d.fat_g} g,"
            f" carbs {d.carbohydrates_g} g, fruit+veg {d.fruit_veg_g} g"
        )
    for s in result.shortfalls:
        amount = (
            f"{money(s.amount)} {result.currency}" if s.unit == "cents" else f"{s.amount} {s.unit}"
        )
        out.append(f"CANNOT MEET {s.constraint}: {amount} ({s.detail})")
    if result.warnings:
        out.append("INCOMPLETE DATA - results are not complete until these are fixed:")
        out.extend(f"  - {w.name}: {w.issue} ({w.detail})" for w in result.warnings)
    return "\n".join(out)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="python -m annona_server.optimize")
    parser.add_argument("--household", type=int, default=1)
    parser.add_argument("--store", required=True, help="store id, e.g. mercadona")
    parser.add_argument("--budget", type=Decimal, help="weekly budget (default: household's)")
    args = parser.parse_args()
    url = database_url()
    migrate.upgrade(url)
    engine = make_engine(url)
    try:
        with session_scope(engine) as session:
            budget = None if args.budget is None else int(args.budget * 100)
            problem = build_problem(
                session,
                household_id=args.household,
                store_id=args.store,
                on_date=date.today(),
                budget_cents=budget,
            )
            print(report(optimise(problem), problem.budget_cents))
    except (NotFoundError, ValueError) as error:
        sys.exit(str(error))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
