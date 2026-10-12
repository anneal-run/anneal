"""`anneal` command-line entry point.

Subcommands are added by the milestone task that implements them.
"""

import argparse
import json
from collections.abc import Sequence

from anneal import __version__
from anneal.schema import Run


def _schema_dump(_: argparse.Namespace) -> int:
    print(json.dumps(Run.model_json_schema(), indent=2))
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
