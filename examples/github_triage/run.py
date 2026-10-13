"""Run the triage agent over a selection of issues, traced to LangSmith.

    python -m github_triage.run data/<dataset>.jsonl --dataset <name>

Needs `GITHUB_TOKEN`, the model provider's API key, and for tracing
`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`.
Runs are started in the file's order (oldest issue first), so a chronological
split by run start time is a split by issue creation time. Each run's triage and
verdict is appended to `data/runs/<dataset>.jsonl`.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from langchain_core.callbacks import UsageMetadataCallbackHandler

from github_triage.agent import RUN_NAME, build_agent, chat_model, first_message
from github_triage.budget import Budget
from github_triage.check import judge
from github_triage.github import GitHub
from github_triage.select_issues import Truth
from github_triage.tools import Tools, triaging

HERE = Path(__file__).parent


def load_truths(path: Path) -> list[Truth]:
    return [Truth(**json.loads(line)) for line in path.read_text().splitlines() if line]


def triage_one(truth: Truth, dataset: str, gh: GitHub, budget: Budget) -> dict[str, Any]:
    tools = Tools(gh)
    graph = build_agent(chat_model(), tools.langchain_tools())
    usage = UsageMetadataCallbackHandler()
    config: Any = {
        "run_name": RUN_NAME,
        "metadata": {"repo": truth.repo, "number": truth.number, "dataset": dataset},
        "tags": [dataset],
        "callbacks": [usage],
        "recursion_limit": 30,
    }
    error = None
    triage = None
    try:
        with triaging(truth.repo, truth.number, truth.created_at):
            state = graph.invoke({"messages": [first_message(truth.repo, truth.number)]}, config)
        triage = state.get("triage")
    except Exception as e:  # recorded, not raised: a failed run is data
        error = f"{type(e).__name__}: {e}"
    cost = budget.cost(usage.usage_metadata)
    budget.add(dataset, cost)
    labels = {x["name"] for x in tools.list_labels(truth.repo)}
    verdict = judge(triage, truth, labels)
    return {
        "repo": truth.repo,
        "number": truth.number,
        "triage": triage,
        "ok": verdict.ok,
        "labels_ok": verdict.labels_ok,
        "duplicate_ok": verdict.duplicate_ok,
        "reason": verdict.reason,
        "cost_usd": cost,
        "tools": [name for name, _ in tools.calls],
        "error": error,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("selection", type=Path)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    truths = load_truths(args.selection)[: args.limit]
    out = HERE / "data" / "runs" / f"{args.dataset}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {
        (r["repo"], r["number"])
        for r in map(json.loads, out.read_text().splitlines() if out.exists() else [])
    }
    todo = [t for t in truths if (t.repo, t.number) not in done]
    gh, budget, lock = GitHub(), Budget(), Lock()

    def work(truth: Truth) -> None:
        budget.check()
        row = triage_one(truth, args.dataset, gh, budget)
        with lock, out.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"{truth.repo}#{truth.number}: {row['reason']} ${row['cost_usd']:.4f}", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        for future in [pool.submit(work, t) for t in todo]:
            future.result()
    print(f"spent so far: ${budget.total():.2f}")


if __name__ == "__main__":
    main()
