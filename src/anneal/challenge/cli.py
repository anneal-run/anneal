"""`anneal challenge` commands."""

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from anneal.challenge.budget import SearchBudget
from anneal.challenge.harness import build_harness, load_manifest, write_harness
from anneal.challenge.models import Candidate, Change, Observation
from anneal.challenge.orchestrate import orchestrate, render_markdown
from anneal.challenge.pack import write_pack
from anneal.challenge.power import adjudication, minimum_detectable_effect
from anneal.challenge.pr import write_pull_request
from anneal.challenge.scan import scan, write_manifests
from anneal.challenge.shadow import (
    evaluate_pairs,
    evidence_header,
    load_pairs,
    margin_points,
    render_shadow,
)
from anneal.challenge.verdict import CORRECTNESS_MARGIN_POINTS
from anneal.compile.compiler import ToolSpec
from anneal.schema.pricing import PriceTable, fill_costs
from anneal.schema.store import Store


def _observation(raw: dict[str, Any]) -> Observation:
    body = {key: value for key, value in raw.items() if key != "split"}
    return Observation.model_validate(body)


def _scan(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    candidates = scan(repo)
    write_manifests(repo, candidates, Path(args.out))
    for item in candidates:
        print(f"{item.score}\t{item.candidate_rung}\t{item.path}")
    return 0


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
    n = len(baseline_holdout)
    margin = _margin(args)
    if n < 1:
        detectable = "minimum detectable effect: unavailable\n"
    else:
        detectable = f"minimum detectable effect: {minimum_detectable_effect(n):.1f} points\n"
    refusal = adjudication(n, margin_points=margin)
    if refusal is not None:
        text = evidence_header(n=n, margin_points=margin, verdict="cannot adjudicate") + detectable
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        print(text, end="")
        return 2
    candidates = [
        _classify(Candidate.model_validate_json(path.read_text(encoding="utf-8")), args.classify)
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
        require_fallback=args.require_fallback,
        margin_points=margin,
        declared_arms={part.strip() for part in args.arms.split(",") if part.strip()}
        if args.arms
        else None,
        mode="correctness_win" if args.mode == "correctness-win" else "cost",
        cost_ceiling=args.cost_ceiling,
        parser_target=args.parser_target,
        regression_baseline=_regression_baseline(args.regression_baseline),
        regression=_regression(args.regression),
    )
    text = render_markdown(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


def _shadow(args: argparse.Namespace) -> int:
    margin = margin_points(Path(args.config), args.workflow)
    report = evaluate_pairs(load_pairs(Path(args.pairs)), margin_points=margin)
    text = render_shadow(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report.stopped else 2


def _regression_baseline(path: str | None) -> list[Observation] | None:
    if not path:
        return None
    rows: list[Observation] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(_observation(json.loads(line)))
    return rows


def _regression(path: str | None) -> dict[str, list[Observation]] | None:
    if not path:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {key: [Observation.model_validate(row) for row in rows] for key, rows in raw.items()}


def _margin(args: argparse.Namespace) -> float:
    if args.config is None:
        return CORRECTNESS_MARGIN_POINTS
    if not args.workflow:
        raise ValueError("--workflow is required with --config")
    return margin_points(Path(args.config), args.workflow)


def _pr(args: argparse.Namespace) -> int:
    write_pull_request(
        Path(args.out),
        workflow=args.workflow,
        winner=args.winner,
        verdict=Path(args.verdict),
        fixtures=Path(args.fixtures),
    )
    print(f"wrote a pull request description to {args.out}")
    return 0


def _classify(candidate: Candidate, rules: list[str] | None) -> Candidate:
    """Operator classification. Cache, prompt, and model do not stay structural."""
    if not rules:
        return candidate
    applied: Change | None = None
    for rule in rules:
        key, _, change = rule.partition("=")
        if key in {candidate.id, f"{candidate.arm}/{candidate.id}"}:
            if change == "architecture":
                applied = "architecture"
            elif change == "prompt":
                applied = "prompt"
            elif change == "cache":
                applied = "cache"
            elif change == "model":
                applied = "model"
            else:
                raise ValueError(f"unknown change {change!r}")
    if applied is None:
        return candidate
    return candidate.model_copy(update={"change": applied})


def add_parser(commands: Any) -> None:
    """Register `anneal challenge`."""
    challenge = commands.add_parser(
        "challenge",
        help="build a harness, pack an arm, and score candidates on a holdout",
    )
    sub = challenge.add_subparsers(dest="challenge_command", required=True)

    walker = sub.add_parser("scan", help="rank non-AI code that is losing to messy input")
    walker.add_argument("--repo", required=True)
    walker.add_argument("--out", required=True, help="one manifest directory per candidate")
    walker.set_defaults(func=_scan)

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
    board.add_argument("--config", help="anneal.toml with a margin per workflow")
    board.add_argument("--workflow", help="workflow id, required with --config")
    board.add_argument(
        "--classify",
        action="append",
        help="operator change for one candidate, as arm/id=cache|prompt|model|architecture",
    )
    board.add_argument(
        "--parser-target",
        action="store_true",
        help="library or parser target; correctness-win requires code first, model on failure",
    )
    board.add_argument("--regression-baseline", help="JSONL of the original suite")
    board.add_argument("--regression", help="JSON of arm/id to the candidate's suite observations")
    board.add_argument(
        "--mode",
        choices=("cost", "correctness-win"),
        default="cost",
        help="cost is the 30 percent cut; correctness-win uses a per-case ceiling",
    )
    board.add_argument(
        "--cost-ceiling",
        type=float,
        dest="cost_ceiling",
        help="dollars per case, required for --mode correctness-win",
    )
    board.add_argument(
        "--arms",
        help="arms named in the pre-registration, comma-separated. One arm is a single-arm verdict",
    )
    board.add_argument(
        "--require-fallback",
        action="store_true",
        help="refuse a structural candidate that does not declare a fallback rate",
    )
    board.set_defaults(func=_orchestrate)

    pull = sub.add_parser("pr", help="write a pull request description; nothing is pushed")
    pull.add_argument("--workflow", required=True)
    pull.add_argument("--winner", required=True, help="candidate id that cleared the gates")
    pull.add_argument("--verdict", required=True, help="verdict report to link")
    pull.add_argument("--fixtures", required=True, help="harness fixtures.jsonl")
    pull.add_argument("--out", required=True, help="new directory for the description")
    pull.set_defaults(func=_pr)

    shadow = sub.add_parser("shadow", help="paired count against the workflow margin")
    shadow.add_argument("--pairs", required=True, help="JSONL of paired correct flags")
    shadow.add_argument("--config", required=True, help="anneal.toml")
    shadow.add_argument("--workflow", required=True)
    shadow.add_argument("--out", help="also write the report here")
    shadow.set_defaults(func=_shadow)
