# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run and compare evals.

python -m annona_server.evals run --classifier rules
python -m annona_server.evals run --classifier llm --prompt v1_plain          # estimate only
python -m annona_server.evals run --classifier llm --prompt v1_role --yes     # spend
python -m annona_server.evals compare
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

from annona_core.llm import Tier

from ..config import load_env
from ..db import migrate
from ..db.engine import database_url, make_engine, session_scope
from ..ingest.llm_classify import DEFAULT_PROMPT, PROMPTS
from ..llm.storage import spent_usd
from .runner import (
    EVAL_TASK_PREFIX,
    RESULTS,
    BudgetError,
    budget_usd,
    estimate_cost_usd,
    load_dataset,
    load_reports,
    rescore,
    run_classification,
    save_report,
)


def _prices(model: str) -> tuple[Decimal, Decimal] | None:
    from ..llm.litellm_backend import litellm

    info = litellm.model_cost.get(model) or litellm.model_cost.get(model.split("/", 1)[-1])
    if not info or "input_cost_per_token" not in info:
        return None
    # Standard (peak) prices: an upper bound for the estimate.
    return Decimal(str(info["input_cost_per_token"])), Decimal(str(info["output_cost_per_token"]))


def _fmt(value, pct: bool = False, money: bool = False) -> str:
    if value is None:
        return "-"
    if money:
        return f"{Decimal(value):.6f}"
    return f"{value * 100:.1f}%" if pct else str(value)


def compare() -> None:
    header = f"{'run':16} {'model':26} {'prompt':9} {'acc':>6} {'clear':>6} {'type':>6} "
    header += f"{'repair':>6} {'cost $':>10} {'p50 ms':>7}"
    print(header)
    for r in load_reports():
        m, meta = r["metrics"], r["meta"]
        print(
            f"{r['_file'][:15]:16} {meta['model'][:26]:26} {(meta['prompt'] or '-'):9} "
            f"{_fmt(m['accuracy'], True):>6} {_fmt(m['accuracy_unambiguous'], True):>6} "
            f"{_fmt(m['type_accuracy'], True):>6} {_fmt(m['repair_rate'], True):>6} "
            f"{_fmt(m['cost_usd'], money=True):>10} {_fmt(m['latency_ms_p50']):>7}"
        )


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="python -m annona_server.evals")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the product classification eval")
    run.add_argument("--classifier", choices=["rules", "llm"], default="llm")
    run.add_argument("--prompt", choices=sorted(PROMPTS), default=DEFAULT_PROMPT)
    run.add_argument("--model", help="override the small-tier model (LiteLLM id)")
    run.add_argument("--batch-size", type=int, default=20)
    run.add_argument("--limit", type=int)
    run.add_argument("--yes", action="store_true", help="actually spend money on the run")
    sub.add_parser("compare", help="compare saved reports")
    sub.add_parser("rescore", help="re-apply current dataset labels to saved runs (free)")
    args = parser.parse_args()

    if args.command == "compare":
        compare()
        return
    if args.command == "rescore":
        rows = load_dataset()
        for report in load_reports():
            path = RESULTS / report.pop("_file")
            path.write_text(json.dumps(rescore(report, rows), indent=2, ensure_ascii=False) + "\n")
        compare()
        return

    rows = load_dataset()[: args.limit] if args.limit else load_dataset()
    if args.classifier == "rules":
        report = run_classification(rows, classifier="rules")
        print(f"saved {save_report(report)}")
        compare()
        return

    from ..llm import make_llm_client
    from ..llm.config import llm_settings

    settings = llm_settings()
    if args.model:
        settings.models[Tier.SMALL] = args.model
    model = settings.models[Tier.SMALL]
    prices = _prices(model)
    if prices is None:
        sys.exit(f"no known price for {model}: refusing to run without a cost estimate")
    estimate = estimate_cost_usd(rows, args.prompt, args.batch_size, *prices)

    url = database_url()
    migrate.upgrade(url)
    engine = make_engine(url)
    try:
        with session_scope(engine) as session:
            spent = spent_usd(session, EVAL_TASK_PREFIX)
            print(
                f"{len(rows)} items, model {model}, prompt {args.prompt}: estimated cost up to "
                f"${estimate} (eval budget ${budget_usd()}, already spent ${spent})"
            )
            if not args.yes:
                print("dry run: add --yes to spend")
                return
            try:
                report = run_classification(
                    rows,
                    classifier="llm",
                    llm=make_llm_client(session, settings=settings),
                    prompt=args.prompt,
                    batch_size=args.batch_size,
                    session=session,
                    estimated_cost=estimate,
                )
            except BudgetError as error:
                sys.exit(str(error))
    finally:
        engine.dispose()
    print(f"saved {save_report(report)}")
    compare()


if __name__ == "__main__":
    main()
