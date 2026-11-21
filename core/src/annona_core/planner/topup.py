# SPDX-License-Identifier: AGPL-3.0-or-later
"""Buy one more pack when a good menu needs a little more of a product than was bought.

Used by :func:`plan_week` as its ``top_up``: only for stock-only shortfalls, only whole packs,
and only within the weekly budget. Otherwise the plan goes back to the LLM for a repair.
"""

from __future__ import annotations

import math
from decimal import Decimal

from annona_core.optimizer import Result

from .planner import ExtraPurchase, TopUp
from .verify import PlanContext


def make_top_up(ctx: PlanContext, shopping: Result, budget_cents: int) -> TopUp:
    lines = {line.product_id: line for line in shopping.lines}

    def top_up(short: dict[int, Decimal]):
        extras: list[ExtraPurchase] = []
        added: dict[int, Decimal] = {}
        for pid, missing in sorted(short.items()):
            line = lines.get(pid)
            if line is None or line.pack_basis <= 0:
                return None
            packs = math.ceil(missing / line.pack_basis)
            extras.append(
                ExtraPurchase(
                    product_id=pid,
                    name=line.name,
                    packs=packs,
                    cost_cents=packs * line.price_cents,
                )
            )
            added[pid] = line.pack_basis * packs
        if shopping.total_cost_cents + sum(e.cost_cents for e in extras) > budget_cents:
            return None
        available = tuple(
            a.model_copy(update={"available": a.available + added.get(a.product.id, Decimal(0))})
            for a in ctx.available
        )
        return ctx.model_copy(update={"available": available}), extras

    return top_up
