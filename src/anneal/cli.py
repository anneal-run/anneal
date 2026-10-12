"""`anneal` command-line entry point.

Subcommands are added by the milestone task that implements them.
"""

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from anneal import __version__
from anneal.schema import Run
from anneal.schema.pricing import PriceTable, fill_costs
from anneal.schema.store import Store


def _schema_dump(_: argparse.Namespace) -> int:
    print(json.dumps(Run.model_json_schema(), indent=2))
    return 0


def _import_langsmith(args: argparse.Namespace) -> int:
    from anneal.importers.langsmith import load_runs

    runs = load_runs(args.file, workflow_id=args.workflow)
    count = Store(args.store).write(runs)
    workflows = sorted({r.workflow_id for r in runs})
    print(f"imported {count} runs ({', '.join(workflows)}) into {args.store}, redacted")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    from anneal.report.analyze import Delta, analyze, render_markdown

    store = Store(args.store)
    workflow = args.workflow
    if workflow is None:
        found = store.workflows()
        if len(found) != 1:
            args.parser.error(
                f"--workflow is required; the store has: {', '.join(found) or 'none'}"
            )
        workflow = found[0]
    since = datetime.fromisoformat(args.since) if args.since else None
    prices = PriceTable.load(args.pricing)
    runs = [fill_costs(r, prices) for r in store.read(workflow, since=since)]
    deltas = {}
    if args.deltas:
        raw = json.loads(Path(args.deltas).read_text(encoding="utf-8"))
        deltas = {k: Delta.model_validate(v) for k, v in raw.items()}
    report = analyze(runs, deltas=deltas, min_support=args.min_support)
    print(report.model_dump_json(indent=2) if args.json else render_markdown(report), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level `anneal` argument parser."""
    parser = argparse.ArgumentParser(
        prog="anneal",
        description="Compile your agent's hot paths into code; the model only runs on what's new.",
    )
    parser.add_argument("--version", action="version", version=f"anneal {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    schema = commands.add_parser("schema", help="inspect the trace schema")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    dump = schema_commands.add_parser("dump", help="print the Run JSON schema")
    dump.set_defaults(func=_schema_dump)

    imp = commands.add_parser("import", help="import traces into a store (redacted on write)")
    sources = imp.add_subparsers(dest="source", required=True)
    langsmith = sources.add_parser("langsmith", help="LangSmith run export, one JSON run per line")
    langsmith.add_argument("file", help="path to the JSONL export")
    langsmith.add_argument("--store", required=True, help="store directory")
    langsmith.add_argument("--workflow", help="workflow id (default: root run name)")
    langsmith.set_defaults(func=_import_langsmith)

    an = commands.add_parser("analyze", help="spend by call class and a Tier 1 estimate")
    an.add_argument("store", help="store directory")
    an.add_argument("--workflow", help="workflow id (required if the store has several)")
    an.add_argument("--since", help="only runs started at or after this ISO timestamp")
    an.add_argument("--pricing", help="price table YAML (default: bundled)")
    an.add_argument("--deltas", help="JSON of measured constrained deltas by position id")
    an.add_argument("--min-support", type=int, default=5, help="runs needed at a position")
    an.add_argument("--json", action="store_true", help="print the report as JSON")
    an.set_defaults(func=_analyze, parser=an)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
