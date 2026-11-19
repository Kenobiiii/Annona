# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke-test the configured AI provider with ONE small call (costs a fraction of a cent).

Usage: uv run python scripts/llm_smoke.py [--tier small|large] [--image photo.jpg]
Needs the provider key in .env (e.g. DEEPSEEK_API_KEY) and optionally ANNONA_LLM_MODEL_*.
"""

import argparse
import mimetypes
from pathlib import Path

from pydantic import BaseModel

from annona_core.llm import CallStats, Image, LLMRequest, Message, Tier
from annona_server.db import migrate
from annona_server.db.engine import database_url, make_engine, session_scope
from annona_server.llm import make_llm_client
from annona_server.llm.config import llm_settings


class Smoke(BaseModel):
    category: str
    reason: str


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=[t.value for t in Tier], default="small")
    parser.add_argument("--image", type=Path, help="optional image to test vision")
    args = parser.parse_args()
    settings = llm_settings()
    tier = Tier(args.tier)
    images: tuple[Image, ...] = ()
    if args.image:
        media = mimetypes.guess_type(args.image.name)[0] or "image/jpeg"
        images = (Image(media, args.image.read_bytes()),)
    text = "What food category is this? " + (
        "Look at the image." if images else "Product: 'Leche semidesnatada Hacendado 6x1L'."
    )
    request = LLMRequest(
        tier=tier,
        task="smoke",
        system="You classify supermarket products. Keep 'reason' under 15 words.",
        messages=(Message("user", text, images),),
        max_tokens=200,
    )
    url = database_url()
    migrate.upgrade(url)
    engine = make_engine(url)
    stats = CallStats()
    with session_scope(engine) as session:
        llm = make_llm_client(session, settings=settings)
        result = llm.complete_json(request, Smoke, use_cache=False, stats=stats)
    engine.dispose()
    print(f"model:   {settings.models[tier]}")
    print(f"answer:  {result.model_dump()}")
    print(f"tokens:  {stats.input_tokens} in / {stats.output_tokens} out")
    cost = "unknown" if stats.cost_usd is None else f"${stats.cost_usd:.6f}"
    print(f"cost:    {cost}   latency: {stats.latency_ms} ms   repaired: {stats.repaired}")


if __name__ == "__main__":
    main()
