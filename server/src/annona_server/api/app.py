# SPDX-License-Identifier: AGPL-3.0-or-later
"""The FastAPI application. Interactive docs at ``/docs``; every route under ``/api/v1`` needs
``Authorization: Bearer <ANNONA_API_TOKEN>``."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import Engine
from sqlmodel import Session

from annona_core.llm import LLMClient

from .. import __version__
from ..config import load_env
from ..db import migrate
from ..db.engine import database_url, make_engine
from ..jobs import JobRunner
from ..mcp_server import build_server
from . import errors
from .deps import require_token
from .mcp_guard import BearerGuard, McpPathAlias
from .routes import (
    chat,
    household,
    pantry,
    plans,
    products,
    receipts,
    recipes,
    shopping,
    shopping_lists,
    system,
)
from .throttle import FailureThrottle, SecurityHeaders

MIN_TOKEN_LENGTH = 24

DESCRIPTION = """Self-hosted API of **Annona**, the open-source weekly meal planner.

Authenticate with **Authorize** using the server's `ANNONA_API_TOKEN`. Slow operations (plan
generation, price refresh) return a job: poll `GET /api/v1/jobs/{id}`.
Nutrition is informational, not medical advice."""


def create_app(
    *,
    engine: Engine | None = None,
    runner: JobRunner | None = None,
    token: str | None = None,
    llm_factory: Callable[[Session], LLMClient] | None = None,
    chat_model_factory: Callable[..., Any] | None = None,
) -> FastAPI:
    load_env()
    if engine is None:
        url = database_url()
        migrate.upgrade(url)
        engine = make_engine(url)
    if llm_factory is None:
        from ..llm import make_llm_client

        llm_factory = make_llm_client

    runner = runner or JobRunner(engine)
    mcp_server = build_server(engine, llm_factory=llm_factory, runner=runner)
    # Stateless JSON responses: no server-to-client streaming is needed, and it works behind
    # simple proxies. DNS-rebinding protection is off because every request needs the token.
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp_server.session_manager.run():
            yield
        app.state.runner.shutdown()

    app = FastAPI(
        title="Annona API", version=__version__, description=DESCRIPTION, lifespan=lifespan
    )
    app.state.engine = engine
    app.state.runner = runner
    app.state.token = token if token is not None else os.environ.get("ANNONA_API_TOKEN", "")
    app.state.llm_factory = llm_factory
    app.state.auth_throttle = FailureThrottle()
    app.add_middleware(SecurityHeaders)
    if 0 < len(app.state.token) < MIN_TOKEN_LENGTH:
        logging.getLogger("annona").warning(
            "ANNONA_API_TOKEN is shorter than %d characters: use a long random secret",
            MIN_TOKEN_LENGTH,
        )
    if chat_model_factory is None:
        from ..chat.service import default_model_factory

        chat_model_factory = default_model_factory
    app.state.chat_model_factory = chat_model_factory
    origins = [o for o in os.environ.get("ANNONA_CORS_ORIGINS", "").split(",") if o]
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"]
        )
    errors.install(app)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.mount("/mcp", BearerGuard(mcp_app, lambda: app.state.token, app.state.auth_throttle))
    app.add_middleware(McpPathAlias)

    protected = [Depends(require_token)]
    for module in (
        system,
        household,
        pantry,
        products,
        shopping,
        plans,
        shopping_lists,
        recipes,
        receipts,
        chat,
    ):
        app.include_router(module.router, prefix="/api/v1", dependencies=protected)
    return app
