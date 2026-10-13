"""Export the traced runs of one dataset from LangSmith to JSONL for `anneal import`.

    python -m github_triage.export --project <project> --dataset <name> out.jsonl

Writes every run (roots and children) of the traces whose root carries
`metadata.dataset == <name>`, one `langsmith.schemas.Run` per line, as
docs/vendor-notes/langsmith.md describes.
"""

import argparse
from pathlib import Path

from langsmith import Client


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args(argv)
    client = Client()
    roots = [
        r
        for r in client.list_runs(project_name=args.project, is_root=True)
        if (r.extra or {}).get("metadata", {}).get("dataset") == args.dataset
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with args.out.open("w") as f:
        for root in roots:
            for run in client.list_runs(project_name=args.project, trace_id=root.trace_id):
                f.write(run.json() + "\n")
                n += 1
    print(f"{len(roots)} traces, {n} runs -> {args.out}")


if __name__ == "__main__":
    main()
