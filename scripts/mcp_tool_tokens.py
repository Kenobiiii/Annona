# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure the size of the MCP tool list (what a client sends to the model every turn).

Usage: uv run python scripts/mcp_tool_tokens.py
Token counts use LiteLLM's default tokenizer, an approximation: exact counts depend on the model.
"""

import json

import anyio
from mcp.client import Client
from sqlmodel import create_engine

from annona_server.llm.litellm_backend import litellm
from annona_server.mcp_server import build_server


async def main() -> None:
    async with Client(build_server(create_engine("sqlite://"))) as client:
        tools = (await client.list_tools()).tools
    rows = []
    for t in tools:
        sent = {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        text = json.dumps(sent, separators=(",", ":"))
        out = json.dumps(t.output_schema or {}, separators=(",", ":"))
        rows.append((t.name, litellm.token_counter(text=text), litellm.token_counter(text=out)))
    width = max(len(r[0]) for r in rows)
    print(f"{'tool':{width}}  input+description  output schema")
    for name, inp, out in rows:
        print(f"{name:{width}}  {inp:>17}  {out:>13}")
    print(f"{'TOTAL':{width}}  {sum(r[1] for r in rows):>17}  {sum(r[2] for r in rows):>13}")


anyio.run(main)
