# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weekly planner: the LLM drafts the meals, code verifies and portions them.

One LLM call (large tier) produces a :class:`PlanDraft`; :func:`verify` checks it and computes
portions. If verification finds problems, the model gets ONE repair request listing them
exactly; if they remain, the plan is rejected with a clear list of issues.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from annona_core.llm import CallStats, LLMClient, LLMRequest, Message, Tier

from .draft import PlanDraft
from .prompt import build_prompt
from .verify import Issue, PlanContext, Verification, verify

TASK = "plan_week"
REPAIR = (
    "The plan has these problems:\n{issues}\n"
    "Return the complete corrected plan (all meals), fixing every problem."
)


@dataclass
class PlanOutcome:
    accepted: bool
    draft: PlanDraft
    verification: Verification
    first_issues: list[Issue]
    repaired: bool
    calls: list[CallStats] = field(default_factory=list)


def plan_week(
    llm: LLMClient, ctx: PlanContext, *, task: str = TASK, use_cache: bool = True
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
    result = verify(draft, ctx)
    outcome = PlanOutcome(
        accepted=result.ok,
        draft=draft,
        verification=result,
        first_issues=list(result.issues),
        repaired=False,
        calls=[first_stats],
    )
    if result.ok:
        return outcome

    issues = "\n".join(f"- {issue.message}" for issue in result.issues)
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
    fixed_result = verify(fixed, ctx)
    return PlanOutcome(
        accepted=fixed_result.ok,
        draft=fixed,
        verification=fixed_result,
        first_issues=outcome.first_issues,
        repaired=True,
        calls=[first_stats, repair_stats],
    )
