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
    header += f"{'unsafe':>6} {'restr':>5} {'repair':>6} {'cost $':>10} {'p50 ms':>7}"
    print(header)
    for r in load_reports():
        m, meta = r["metrics"], r["meta"]
        print(
            f"{r['_file'][:15]:16} {meta['model'][:26]:26} {(meta['prompt'] or '-'):9} "
            f"{_fmt(m['accuracy'], True):>6} {_fmt(m['accuracy_unambiguous'], True):>6} "
            f"{_fmt(m['type_accuracy'], True):>6} {_fmt(m.get('diet_unsafe_errors')):>6} "
            f"{_fmt(m.get('diet_over_restrictive_errors')):>5} {_fmt(m['repair_rate'], True):>6} "
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
    pr = sub.add_parser("plan-run", help="run the weekly-planner eval")
    pr.add_argument("--scenario", action="append", help="only these scenario ids")
    pr.add_argument("--model", help="override the large-tier model")
    pr.add_argument("--yes", action="store_true", help="actually spend money on the run")
    ps = sub.add_parser("plan-show", help="print the menus of a planner run")
    ps.add_argument("file")
    ps.add_argument("--scenario")
    rate = sub.add_parser("plan-rate", help="record your 1-5 rating of a menu")
    rate.add_argument("file")
    rate.add_argument("scenario")
    rate.add_argument("score", type=int, choices=range(1, 6))
    rate.add_argument("--note", default="")
    pj = sub.add_parser("plan-judge", help="LLM judge scores for a planner run")
    pj.add_argument("file")
    pj.add_argument("--yes", action="store_true")
    sub.add_parser("plan-compare", help="compare planner runs")
    args = parser.parse_args()

    if args.command == "compare":
        compare()
        return
    if args.command.startswith("plan-"):
        plan_commands(args)
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


def _report_path(name: str):
    from pathlib import Path

    path = Path(name)
    return path if path.exists() else RESULTS / name


def plan_commands(args) -> None:
    from ..llm import make_llm_client
    from ..llm.config import llm_settings
    from . import plans

    if args.command == "plan-show":
        report = json.loads(_report_path(args.file).read_text())
        for entry in report["scenarios"]:
            if args.scenario in (None, entry["id"]):
                print(plans.menu_text(entry))
                print(json.dumps(entry.get("metrics"), indent=1))
                for issue in entry.get("issues", []):
                    print("ISSUE", issue)
                print()
        return
    if args.command == "plan-rate":
        path = _report_path(args.file)
        report = json.loads(path.read_text())
        report["human_ratings"][args.scenario] = {"score": args.score, "note": args.note}
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"saved; judge agreement so far: {plans.agreement(report)}")
        return
    if args.command == "plan-compare":
        print(
            f"{'run':16} {'model':26} {'ok':>3} {'1st':>3} {'meals':>5} {'distinct':>8} "
            f"{'used':>5} {'cost $':>9} {'human':>5} {'judge':>5}"
        )
        for path in sorted(RESULTS.glob("*__plan_week__*.json")):
            r = json.loads(path.read_text())
            for e in r["scenarios"]:
                m = e.get("metrics") or {}
                human = r["human_ratings"].get(e["id"], {}).get("score", "-")
                judged = r["judge"].get(e["id"], {}).get("score", "-")
                print(
                    f"{path.name[:15]:16} {r['meta']['model'][:26]:26} "
                    f"{'y' if m.get('accepted') else 'n':>3} "
                    f"{'y' if m.get('accepted_first_try') else 'n':>3} {m.get('meals', '-'):>5} "
                    f"{m.get('distinct_titles_ratio', '-')!s:>8} "
                    f"{m.get('purchase_used_ratio', '-')!s:>5} "
                    f"{_fmt(m.get('cost_usd'), money=True):>9} {human!s:>5} {judged!s:>5}  "
                    f"{e['id']}"
                )
        return

    settings = llm_settings()
    if args.command == "plan-run" and args.model:
        settings.models[Tier.LARGE] = args.model
    url = database_url()
    migrate.upgrade(url)
    engine = make_engine(url)
    try:
        with session_scope(engine) as session:
            spent = spent_usd(session, EVAL_TASK_PREFIX)
            if args.command == "plan-run":
                prepared = plans.prepare_all(args.scenario)
                model = settings.models[Tier.LARGE]
                prices = _prices(model)
                if prices is None:
                    sys.exit(f"no known price for {model}")
                estimate = sum(
                    (plans.estimate_plan_cost(ctx, *prices) for _, _, ctx in prepared if ctx),
                    Decimal(0),
                )
            else:
                report_path = _report_path(args.file)
                report = json.loads(report_path.read_text())
                model = settings.models[Tier.SMALL]
                prices = _prices(model)
                estimate = Decimal("0.001") * len(report["scenarios"])  # tiny: ~1k tokens each
            print(
                f"model {model}: estimated cost up to ${estimate} "
                f"(eval budget ${budget_usd()}, already spent ${spent:.4f})"
            )
            if spent + estimate > budget_usd():
                sys.exit("eval budget would be exceeded")
            if not args.yes:
                print("dry run: add --yes to spend")
                return
            llm = make_llm_client(session, settings=settings)
            if args.command == "plan-run":
                report = plans.run_plans(llm, prepared, model)
                print(f"saved {plans.save(report)}")
            else:
                plans.judge(llm, report)
                report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
                for sid, verdict in report["judge"].items():
                    print(f"{sid}: {verdict['score']} - {verdict['reasons']}")
                print(f"agreement with your ratings: {plans.agreement(report)}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
