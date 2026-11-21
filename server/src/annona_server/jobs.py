# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background jobs for slow operations (LLM plans take 25-90 s, price refreshes minutes).

A job row is created as ``queued``, run on a worker thread with its own database session, and
ends ``done`` (with a JSON result) or ``failed`` (with the error). Clients poll ``/jobs/{id}``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from .db.engine import session_scope
from .db.tables import JobRow

log = logging.getLogger(__name__)

JobFunction = Callable[[Session, dict[str, Any]], dict[str, Any]]


class InlineExecutor(Executor):
    """Runs jobs immediately in the calling thread (tests, CLIs)."""

    def submit(self, fn, /, *args, **kwargs) -> Future:  # type: ignore[override]
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001 - delivered through the future
            future.set_exception(error)
        return future


class JobRunner:
    def __init__(self, engine: Engine, executor: Executor | None = None) -> None:
        self.engine = engine
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")

    def submit(self, kind: str, params: dict[str, Any], fn: JobFunction) -> str:
        job_id = uuid.uuid4().hex
        with session_scope(self.engine) as session:
            session.add(
                JobRow(
                    id=job_id,
                    kind=kind,
                    status="queued",
                    params=params,
                    created_at=datetime.now(UTC),
                )
            )
        self.executor.submit(self._run, job_id, params, fn)
        return job_id

    def _run(self, job_id: str, params: dict[str, Any], fn: JobFunction) -> None:
        self._update(job_id, status="running", started_at=datetime.now(UTC))
        try:
            with session_scope(self.engine) as session:
                result = fn(session, params)
        except Exception as error:
            log.exception("job %s failed", job_id)
            self._update(job_id, status="failed", error=repr(error), finished_at=datetime.now(UTC))
            return
        self._update(job_id, status="done", result=result, finished_at=datetime.now(UTC))

    def _update(self, job_id: str, **fields: Any) -> None:
        with session_scope(self.engine) as session:
            row = session.get(JobRow, job_id)
            if row is not None:
                for key, value in fields.items():
                    setattr(row, key, value)
                session.add(row)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
