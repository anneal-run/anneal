"""`anneal` command-line entry point.

Subcommands are added by the milestone task that implements them; M1.0 ships
only the parser and `--version`.
"""

import argparse
from collections.abc import Sequence

from anneal import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level `anneal` argument parser."""
    parser = argparse.ArgumentParser(
        prog="anneal",
        description="Compile your agent's hot paths into code; the model only runs on what's new.",
    )
    parser.add_argument("--version", action="version", version=f"anneal {__version__}")
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return 0  # pragma: no cover - unreachable until a subcommand is registered


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
