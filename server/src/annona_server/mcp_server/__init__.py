# SPDX-License-Identifier: AGPL-3.0-or-later
"""MCP server exposing the tool registry (official ``mcp`` Python SDK).

Transports: stdio (``python -m annona_server.mcp_server``, for desktop clients and Claude Code)
and streamable HTTP mounted on the REST API at ``/mcp/`` behind the same bearer token.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as SdkToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from pydantic_core import PydanticUndefined
from sqlalchemy import Engine
from sqlmodel import Session

from annona_core.llm import LLMClient

from .. import __version__
from ..db.engine import session_scope
from ..db.repositories import HouseholdRepository
from ..jobs import JobRunner
from ..tools import TOOLS, Tool, ToolContext, ToolError

INSTRUCTIONS = (
    "Annona plans a household's weekly meals from its budget, real supermarket prices and "
    "pantry. Amounts are g, ml or units; money is in the household currency. Nutrition is "
    "informational, not medical advice. Start with get_profile. Building a plan takes about a "
    "minute: call build_weekly_plan, then get_plan."
)


def _parameters(tool: Tool) -> list[inspect.Parameter]:
    params = []
    for name, field in tool.input.model_fields.items():
        annotation: Any = field.annotation
        if field.description:
            annotation = Annotated[annotation, Field(description=field.description)]
        if field.default is not PydanticUndefined:
            default = field.default
        elif field.default_factory is not None:
            default = field.default_factory()  # type: ignore[call-arg]
        else:
            default = inspect.Parameter.empty
        params.append(
            inspect.Parameter(
                name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation
            )
        )
    return params


def _function(
    tool: Tool, engine: Engine, llm_factory: Callable[[Session], LLMClient], runner: JobRunner
):
    def call(**kwargs: Any):
        with session_scope(engine) as session:
            household = next(iter(HouseholdRepository(session).list()), None)
            if household is None:
                raise SdkToolError("Annona is not set up yet: create the household in the app")
            ctx = ToolContext(
                session=session,
                household=household,
                llm_factory=llm_factory,
                runner=runner,
                today=date.today(),
            )
            try:
                return tool.run(ctx, kwargs)
            except ToolError as error:
                # The SDK only shows the message of its own ToolError to the client; anything
                # else becomes a generic "error executing tool" (so internals never leak).
                raise SdkToolError(str(error)) from error

    params = _parameters(tool)
    call.__signature__ = inspect.Signature(params, return_annotation=tool.output)  # type: ignore[attr-defined]
    call.__annotations__ = {p.name: p.annotation for p in params} | {"return": tool.output}
    call.__name__ = tool.name
    call.__doc__ = tool.description
    return call


def strip_titles(schema: Any) -> Any:
    """Drop Pydantic's auto-generated ``title`` keys (tokens the model does not need), keeping
    real properties that happen to be called "title"."""
    if isinstance(schema, dict):
        return {
            k: strip_titles(v) for k, v in schema.items() if k != "title" or isinstance(v, dict)
        }
    if isinstance(schema, list):
        return [strip_titles(v) for v in schema]
    return schema


def build_server(
    engine: Engine,
    *,
    llm_factory: Callable[[Session], LLMClient] | None = None,
    runner: JobRunner | None = None,
) -> MCPServer:
    if llm_factory is None:
        from ..llm import make_llm_client

        llm_factory = make_llm_client
    runner = runner or JobRunner(engine)
    server = MCPServer(
        name="annona",
        title="Annona meal planner",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/Kenobiiii/Annona",
    )
    for tool in TOOLS.values():
        server.add_tool(
            _function(tool, engine, llm_factory, runner),
            name=tool.name,
            title=tool.title,
            description=tool.description,
            annotations=ToolAnnotations(
                title=tool.title,
                read_only_hint=tool.read_only,
                destructive_hint=tool.destructive if not tool.read_only else None,
                idempotent_hint=tool.idempotent if not tool.read_only else None,
                open_world_hint=False,
            ),
            structured_output=True,
        )
        # The SDK keeps the generated schemas on its Tool objects (pinned SDK version; covered
        # by tests): trim them once here instead of on every list_tools call.
        registered = server._tool_manager.get_tool(tool.name)
        if registered is not None:
            registered.parameters = strip_titles(registered.parameters)
            if registered.output_schema is not None:
                registered.output_schema = strip_titles(registered.output_schema)
    return server
