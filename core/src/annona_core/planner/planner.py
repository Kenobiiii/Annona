# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weekly planner: the LLM drafts the meals, code verifies and portions them.

One LLM call (large tier) produces a :class:`PlanDraft`; :func:`verify` checks it and computes
portions. Small stock shortfalls can be fixed without the LLM by buying more (``top_up``, if
the budget allows). Otherwise the model gets ONE repair request listing the problems exactly;
if they remain, the plan is rejected with a clear list of issues.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from annona_core.llm import CallStats, LLMClient, LLMRequest, Message, Tier

from .draft import PlanDraft
from .prompt import build_prompt
from .scale import scale_to_energy
from .verify import Issue, PlanContext, Verification, verify

TASK = "plan_week"
REPAIR = (
    "The plan has these problems:\n{issues}\n"
    "Return the complete corrected plan (all meals), fixing every problem."
)


@dataclass(frozen=True)
class ExtraPurchase:
    product_id: int
    name: str
    packs: int
    cost_cents: int


# Given the missing amount per product, return a context with more stock and the purchases that
# provide it, or None if that is not possible (e.g. over budget).
TopUp = Callable[[dict[int, Decimal]], tuple[PlanContext, list[ExtraPurchase]] | None]


@dataclass
class PlanOutcome:
    accepted: bool
    draft: PlanDraft
    verification: Verification
    first_issues: list[Issue]
    repaired: bool
    calls: list[CallStats] = field(default_factory=list)
    extra_purchases: list[ExtraPurchase] = field(default_factory=list)


def _only_stock(result: Verification) -> bool:
    return bool(result.issues) and all(i.code == "stock_exceeded" for i in result.issues)


def _with_top_up(
    draft: PlanDraft, result: Verification, top_up: TopUp | None
) -> tuple[Verification, list[ExtraPurchase]]:
    """Fix stock-only shortfalls by buying more, without calling the LLM, when allowed."""
    if top_up is None or not _only_stock(result):
        return result, []
    offer = top_up(result.stock_short)
    if offer is None:
        return result, []
    new_ctx, extras = offer
    rechecked = verify(draft, new_ctx)
    return (rechecked, extras) if rechecked.ok else (result, [])


def plan_week(
    llm: LLMClient,
    ctx: PlanContext,
    *,
    task: str = TASK,
    use_cache: bool = True,
    top_up: TopUp | None = None,
) -> PlanOutcome:
    system, user = build_prompt(ctx)
    max_tokens = 400 * len(ctx.schedule.slots) + 1000
    first_stats = CallStats()
    request = LLMRequest(
        tier=Tier.LARGE,
        task=task,
        system=system,
        messages=(Message("user", user),),
        max_tokens=max_tokens,
    )
    draft = llm.complete_json(request, PlanDraft, use_cache=use_cache, stats=first_stats)
    draft = scale_to_energy(draft, ctx)
    first = verify(draft, ctx)
    result, extras = _with_top_up(draft, first, top_up)
    if result.ok:
        return PlanOutcome(
            accepted=True,
            draft=draft,
            verification=result,
            first_issues=list(first.issues),
            repaired=False,
            calls=[first_stats],
            extra_purchases=extras,
        )

    issues = "\n".join(f"- {issue.message}" for issue in first.issues)
    repair_request = LLMRequest(
        tier=Tier.LARGE,
        task=task,
        system=system,
        messages=(
            Message("user", user),
            Message("assistant", draft.model_dump_json()),
            Message("user", REPAIR.format(issues=issues)),
        ),
        max_tokens=max_tokens,
    )
    repair_stats = CallStats()
    fixed = llm.complete_json(repair_request, PlanDraft, use_cache=use_cache, stats=repair_stats)
    fixed = scale_to_energy(fixed, ctx)
    fixed_result, extras = _with_top_up(fixed, verify(fixed, ctx), top_up)
    return PlanOutcome(
        accepted=fixed_result.ok,
        draft=fixed,
        verification=fixed_result,
        first_issues=list(first.issues),
        repaired=True,
        calls=[first_stats, repair_stats],
        extra_purchases=extras,
    )
