# SPDX-License-Identifier: AGPL-3.0-or-later
"""One chat turn: builds the host and the model, runs the agent loop and yields its events."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date

from sqlalchemy import Engine
from sqlmodel import Session

from annona_core.agent import AgentCaps, AgentMessage, ChatModel, run_turn, system_prompt
from annona_core.agent.loop import Event
from annona_core.llm import LLMClient, Tier

from ..db.engine import session_scope
from ..db.repositories import HouseholdRepository
from ..jobs import JobRunner
from ..llm.config import llm_settings
from ..planner import language
from ..tools import ToolContext
from .host import RegistryHost

ChatModelFactory = Callable[[Session, Tier], ChatModel]


def default_model_factory(session: Session, tier: Tier) -> ChatModel:
    from ..demo import DemoChatModel, fake_llm_enabled

    if fake_llm_enabled():
        return DemoChatModel()
    from ..llm.storage import SqlUsageSink
    from .litellm_chat import LiteChatModel

    settings = llm_settings()
    return LiteChatModel(
        settings.models[tier],
        tier=tier,
        usage=SqlUsageSink(session),
        timeout_s=settings.timeout_s,
        thinking=settings.thinking,
    )


def chat_turn(
    engine: Engine,
    *,
    model_factory: ChatModelFactory,
    llm_factory: Callable[[Session], LLMClient],
    runner: JobRunner,
    history: list[AgentMessage],
    text: str,
    tier: Tier = Tier.SMALL,
    caps: AgentCaps | None = None,
    today: date | None = None,
) -> Iterator[Event]:
    """Run one user turn in its own database session; commits when the turn ends."""
    with session_scope(engine) as session:
        household = next(iter(HouseholdRepository(session).list()), None)
        if household is None:
            raise LookupError("create the household first")
        lang = language()
        today = today or date.today()
        ctx = ToolContext(
            session=session,
            household=household,
            llm_factory=llm_factory,
            runner=runner,
            today=today,
        )
        host = RegistryHost(session, household, ctx, lang)
        yield from run_turn(
            model_factory(session, tier),
            host,
            history,
            text,
            system=system_prompt(language=lang, today=today.isoformat()),
            caps=caps or AgentCaps(),
        )
