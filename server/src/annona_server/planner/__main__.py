# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan a week: shop at one store for the chosen meals, then draft and store the menu.

    python -m annona_server.planner --household 1 --store mercadona --week 2026-11-23 \\
        [--days 0,1,2,3,4] [--skip 1:dinner,3:dinner,4:dinner] [--skip-slot snack] \\
        [--budget 60] [--health-limits] [--regenerate]

Weekdays: 0 = Monday ... 6 = Sunday. Slots: breakfast, lunch, snack, dinner.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal

from annona_core.domain import MealSlot
from annona_core.optimizer import OptimizerSettings
from annona_core.planner import MealSchedule

from ..config import load_env
from ..db import migrate
from ..db.engine import database_url, make_engine, session_scope
from ..db.repositories import NotFoundError, SqlProductRepository
from ..llm import make_llm_client
from ..optimize.__main__ import report
from . import existing_plan, plan_and_store


def _skips(text: str | None) -> list[tuple[int, MealSlot]]:
    if not text:
        return []
    out = []
    for part in text.split(","):
        day, slot = part.split(":")
        out.append((int(day), MealSlot(slot.strip())))
    return out


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="python -m annona_server.planner")
    parser.add_argument("--household", type=int, default=1)
    parser.add_argument("--store", required=True)
    parser.add_argument("--week", type=date.fromisoformat, required=True, help="Monday, ISO date")
    parser.add_argument("--days", default="0,1,2,3,4,5,6", help="weekdays to plan, 0=Monday")
    parser.add_argument("--skip", help="day:slot pairs to skip, e.g. 1:dinner,3:dinner")
    parser.add_argument("--skip-slot", action="append", default=[], help="slot to skip all week")
    parser.add_argument("--budget", type=Decimal)
    parser.add_argument("--health-limits", action="store_true")
    parser.add_argument(
        "--variety",
        choices=["basic", "balanced", "high"],
        default="basic",
        help="more variety costs more (basic = cheapest)",
    )
    parser.add_argument("--regenerate", action="store_true", help="replace this week's plan")
    args = parser.parse_args()

    schedule = MealSchedule.build(
        args.week,
        weekdays=[int(d) for d in args.days.split(",")],
        skip_slots=[MealSlot(s) for s in args.skip_slot],
        skip=_skips(args.skip),
    )
    url = database_url()
    migrate.exit_if_outdated(url)
    engine = make_engine(url)
    try:
        with session_scope(engine) as session:
            if existing_plan(session, args.household, args.week) and not args.regenerate:
                sys.exit("this week already has a plan: add --regenerate to replace it")
            week = plan_and_store(
                session,
                make_llm_client(session),
                household_id=args.household,
                store_id=args.store,
                schedule=schedule,
                on_date=args.week,
                budget_cents=None if args.budget is None else int(args.budget * 100),
                settings=OptimizerSettings(health_limits=args.health_limits, variety=args.variety),
            )
            print(report(week.shopping, week.shopping.total_cost_cents))
            if week.outcome is None:
                sys.exit("no menu: the shopping list is not feasible (see above)")
            names = {p.id: p.name for p in SqlProductRepository(session).list()}
            print_menu(week, names)
    except (NotFoundError, ValueError) as error:
        sys.exit(str(error))
    finally:
        engine.dispose()


def print_menu(week, names: dict[int, str]) -> None:
    outcome = week.outcome
    status = "ACCEPTED" if outcome.accepted else "REJECTED"
    print(f"\nmenu {status}{' after one repair' if outcome.repaired else ''}")
    for meal in sorted(outcome.verification.meals, key=lambda m: (m.day, m.draft.slot)):
        d = meal.draft
        print(f"\n{meal.day:%a %d} {d.slot}: {d.title}  [{', '.join(d.appliances)}]")
        print(f"   {d.summary}")
        for portion in meal.portions:
            items = ", ".join(
                f"{names.get(pid, pid)} {amt}" for pid, amt in portion.amounts.items()
            )
            print(f"   {portion.member} (x{portion.scale}): {items}")
    for issue in outcome.verification.issues:
        print(f"ISSUE {issue.code}: {issue.message}")
    for extra in outcome.extra_purchases:
        print(f"ALSO BUY: {extra.packs} x {extra.name} ({extra.cost_cents / 100:.2f})")
    if week.plan_id:
        print(f"\nstored as meal plan #{week.plan_id}")


if __name__ == "__main__":
    main()
