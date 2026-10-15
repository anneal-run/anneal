"""`anneal challenge` commands."""

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from anneal.challenge.budget import SearchBudget
from anneal.challenge.harness import build_harness, load_manifest, write_harness
from anneal.challenge.models import Candidate, Observation
from anneal.challenge.orchestrate import orchestrate, render_markdown
from anneal.challenge.pack import write_pack
from anneal.compile.compiler import ToolSpec
from anneal.schema.pricing import PriceTable, fill_costs
from anneal.schema.store import Store


def _observation(raw: dict[str, Any]) -> Observation:
    body = {key: value for key, value in raw.items() if key != "split"}
    return Observation.model_validate(body)


def _harness(args: argparse.Namespace) -> int:
    store = Store(args.store)
    workflow = args.workflow
    if not workflow:
        found = store.workflows()
        if len(found) != 1:
            names = ", ".join(found) or "none"
            args.parser.error(f"--workflow is required; the store has: {names}")
        workflow = found[0]
    prices = PriceTable.load(args.pricing)
    runs = [fill_costs(run, prices) for run in store.read(workflow)]
    raw = yaml.safe_load(Path(args.tools).read_text(encoding="utf-8")) or {}
    tools = {name: ToolSpec.model_validate(spec) for name, spec in raw.items()}
    manifest = build_harness(
        runs,
        tools=tools,
        compile_share=args.compile_share,
        entrypoint=args.entrypoint,
        workflow_files=list(args.file or []),
    )
    write_harness(manifest, runs, Path(args.out))
    print(
        f"harness for {manifest.workflow_id}: "
        f"{len(manifest.optimization_run_ids)} optimization runs, "
        f"{len(manifest.holdout_run_ids)} holdout runs sealed"
    )
    return 0


def _pack(args: argparse.Namespace) -> int:
    budget = SearchBudget.model_validate_json(Path(args.budget).read_text(encoding="utf-8"))
    write_pack(
        Path(args.source),
        Path(args.out),
        manifest=load_manifest(Path(args.harness)),
        arm=args.arm,
        p0=args.p0,
        budget=budget,
    )
    print(f"wrote {args.arm} pack to {args.out}")
    return 0


def _orchestrate(args: argparse.Namespace) -> int:
    budget = SearchBudget.model_validate_json(Path(args.budget).read_text(encoding="utf-8"))
    baseline_opt: list[Observation] = []
    baseline_holdout: list[Observation] = []
    for line in Path(args.baseline).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        row = _observation(raw)
        if raw["split"] == "opt":
            baseline_opt.append(row)
        elif raw["split"] == "holdout":
            baseline_holdout.append(row)
        else:
            raise ValueError(f"unknown split {raw['split']!r}")
    candidates = [
        Candidate.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(Path(args.submissions).glob("*.json"))
    ]
    holdout_raw = json.loads(Path(args.holdout).read_text(encoding="utf-8"))
    holdout = {
        key: [Observation.model_validate(row) for row in rows] for key, rows in holdout_raw.items()
    }
    report = orchestrate(
        budget=budget,
        baseline_opt=baseline_opt,
        baseline_holdout=baseline_holdout,
        candidates=candidates,
        holdout=holdout,
        labeling_hours=args.labeling_hours,
        external_merge=args.merge,
        paid_commitment=args.paid is not None,
        paid_price=args.paid,
    )
    text = render_markdown(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def add_parser(commands: Any) -> None:
    """Register `anneal challenge`."""
    challenge = commands.add_parser(
        "challenge",
        help="build a harness, pack an arm, and score candidates on a holdout",
    )
    sub = challenge.add_subparsers(dest="challenge_command", required=True)

    harness = sub.add_parser("harness", help="write a proposer harness from a trace store")
    harness.add_argument("store", help="store directory")
    harness.add_argument("--out", required=True, help="directory to write")
    harness.add_argument("--tools", required=True, help="YAML of tool declarations")
    harness.add_argument("--workflow", help="workflow id (required if the store has several)")
    harness.add_argument("--pricing", help="price table YAML (default: bundled)")
    harness.add_argument("--compile-share", type=float, default=0.7, dest="compile_share")
    harness.add_argument("--entrypoint", help="command `make harness` runs")
    harness.add_argument("--file", action="append", help="workflow file an arm may read")
    harness.set_defaults(func=_harness, parser=harness)

    pack = sub.add_parser("pack", help="copy the files one arm is allowed to see")
    pack.add_argument("--source", required=True, help="repository root")
    pack.add_argument("--harness", required=True, help="harness directory from `challenge harness`")
    pack.add_argument("--out", required=True, help="new pack directory")
    pack.add_argument("--budget", required=True, help="search budget JSON")
    pack.add_argument("--arm", required=True, choices=("A", "B", "C"))
    pack.add_argument("--p0", action="store_true", help="omit the architecture menu")
    pack.set_defaults(func=_pack)

    board = sub.add_parser("orchestrate", help="rank submissions and score the holdout once")
    board.add_argument("--budget", required=True, help="search budget JSON")
    board.add_argument("--baseline", required=True, help="baseline JSONL with a split field")
    board.add_argument("--submissions", required=True, help="directory of candidate JSON files")
    board.add_argument("--holdout", required=True, help="JSON of arm/id to holdout observations")
    board.add_argument("--out", help="also write the markdown report here")
    board.add_argument("--labeling-hours", type=float, default=0.0, dest="labeling_hours")
    board.add_argument("--merge", action="store_true", help="external team merged or will trial it")
    board.add_argument("--paid", help="named price committed for a second workflow")
    board.set_defaults(func=_orchestrate)
