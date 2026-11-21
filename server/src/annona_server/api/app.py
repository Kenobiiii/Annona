# SPDX-License-Identifier: AGPL-3.0-or-later
"""The FastAPI application. Interactive docs at ``/docs``; every route under ``/api/v1`` needs
``Authorization: Bearer <ANNONA_API_TOKEN>``."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine
from sqlmodel import Session

from annona_core.llm import LLMClient

from .. import __version__
from ..config import load_env
from ..db import migrate
from ..db.engine import database_url, make_engine
from ..jobs import JobRunner
from . import errors
from .deps import require_token
from .routes import household, pantry, plans, products, shopping, system

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
) -> FastAPI:
    load_env()
    if engine is None:
        url = database_url()
        migrate.upgrade(url)
        engine = make_engine(url)
    if llm_factory is None:
        from ..llm import make_llm_client

        llm_factory = make_llm_client

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.runner.shutdown()

    app = FastAPI(
        title="Annona API", version=__version__, description=DESCRIPTION, lifespan=lifespan
    )
    app.state.engine = engine
    app.state.runner = runner or JobRunner(engine)
    app.state.token = token if token is not None else os.environ.get("ANNONA_API_TOKEN", "")
    app.state.llm_factory = llm_factory
    origins = [o for o in os.environ.get("ANNONA_CORS_ORIGINS", "").split(",") if o]
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"]
        )
    errors.install(app)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    protected = [Depends(require_token)]
    for module in (system, household, pantry, products, shopping, plans):
        app.include_router(module.router, prefix="/api/v1", dependencies=protected)
    return app
