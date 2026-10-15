"""Build a harness from traces. The directory written for a proposer has no holdout ids."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from anneal.challenge.models import HarnessManifest, ToolBinding
from anneal.compile.compiler import ToolSpec
from anneal.replay.split import chronological_split
from anneal.schema import Run, ToolCall

_HARNESS_PY = '''\
"""Generated harness. Reads manifest.json beside this file. Do not add holdout traces here."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class MockedToolError(Exception):
    """This tool has no recording. A win that depends on it is disqualified."""


class Divergence(Exception):
    """The call does not match a recorded optimization-set invocation."""


def _normalize(value):
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def canonical(args):
    return json.dumps(_normalize(args), sort_keys=True, separators=(",", ":"))


def manifest():
    return json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def fixtures():
    allowed = set(manifest()["optimization_run_ids"])
    rows = []
    for line in (ROOT / "fixtures.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["run_id"] not in allowed:
            raise SystemExit(f"fixture {row['run_id']} is outside the optimization set")
        rows.append(row)
    return rows


class BudgetExceeded(Exception):
    """This model call would spend past the dollars in BUDGET.json. It is not recorded."""


class CostMeter:
    def __init__(self, budget_usd=None):
        self.events = []
        self.budget_usd = budget_usd
        self.path = ROOT / "meter.jsonl"

    def record(self, cost_usd, latency_ms):
        cost = float(cost_usd)
        if self.budget_usd is not None and self.total_usd + cost > self.budget_usd:
            raise BudgetExceeded(self.total_usd + cost)
        event = {"cost_usd": cost, "latency_ms": float(latency_ms)}
        self.events.append(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\\n")

    @property
    def total_usd(self):
        return sum(event["cost_usd"] for event in self.events)


def meter():
    """The pack's budget caps calls. A missing BUDGET.json does not invent a cap."""
    path = ROOT / "BUDGET.json"
    budget = None
    if path.exists():
        budget = json.loads(path.read_text(encoding="utf-8"))["dollars"]
    return CostMeter(budget_usd=budget)


def call_tool(name, args):
    tools = {tool["name"]: tool for tool in manifest()["tools"]}
    spec = tools.get(name)
    if spec is None or spec["mode"] == "mock":
        raise MockedToolError(name)
    if spec["mode"] == "live":
        raise MockedToolError(f"{name} is live; call the real tool")
    key = canonical(args)
    path = ROOT / "recordings.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["tool"] == name and canonical(row["args"]) == key:
            return row["result"]
    raise Divergence(name)


def main():
    entry = manifest().get("entrypoint")
    if not entry:
        print("entrypoint is unset", file=sys.stderr)
        return 2
    return subprocess.call(entry, shell=True)


if __name__ == "__main__":
    raise SystemExit(main())
'''

_MAKEFILE = """\
# Generated. Runs the workflow entrypoint declared when the harness was built.
harness:
\tpython harness.py
"""


def build_harness(
    runs: Sequence[Run],
    *,
    tools: dict[str, ToolSpec],
    compile_share: float,
    entrypoint: str | None,
    workflow_files: list[str],
) -> HarnessManifest:
    """Split runs by time and classify tools. Recordings count on the optimization set only."""
    workflows = {run.workflow_id for run in runs}
    if len(workflows) != 1:
        raise ValueError("a harness is built for one workflow")
    optimization, holdout = chronological_split(runs, compile_share)
    recorded = _recordings(optimization)
    bindings: list[ToolBinding] = []
    for name, spec in tools.items():
        calls = recorded.get(name, [])
        mode: Literal["live", "recorded", "mock"]
        if not spec.side_effect:
            mode = "live"
        elif calls:
            mode = "recorded"
        else:
            mode = "mock"
        bindings.append(
            ToolBinding(
                name=name,
                mode=mode,
                side_effect=spec.side_effect,
                severity=spec.severity,
                recorded_calls=len(calls) if mode == "recorded" else 0,
            )
        )
    known = set(tools)
    for name, calls in recorded.items():
        if name in known:
            continue
        bindings.append(
            ToolBinding(
                name=name,
                mode="recorded",
                side_effect=True,
                severity="S2",
                recorded_calls=len(calls),
            )
        )
    return HarnessManifest(
        workflow_id=next(iter(workflows)),
        optimization_run_ids=[run.run_id for run in optimization],
        holdout_run_ids=[run.run_id for run in holdout],
        tools=bindings,
        workflow_files=list(workflow_files),
        entrypoint=entrypoint,
        mocked_tools=[binding.name for binding in bindings if binding.mode == "mock"],
    )


def write_harness(manifest: HarnessManifest, runs: Sequence[Run], directory: Path) -> None:
    """Write the proposer directory. Holdout run ids live in SEAL.json, not the manifest."""
    directory.mkdir(parents=True, exist_ok=True)
    by_id = {run.run_id: run for run in runs}
    optimization = [by_id[run_id] for run_id in manifest.optimization_run_ids]
    (directory / "manifest.json").write_text(
        json.dumps(manifest.proposer_payload(), indent=2) + "\n", encoding="utf-8"
    )
    (directory / "SEAL.json").write_text(
        json.dumps({"holdout_run_ids": manifest.holdout_run_ids}, indent=2) + "\n",
        encoding="utf-8",
    )
    fixture_lines = [
        json.dumps({"run_id": run.run_id, "input": run.input}, sort_keys=True)
        for run in optimization
    ]
    (directory / "fixtures.jsonl").write_text(
        ("\n".join(fixture_lines) + "\n") if fixture_lines else "", encoding="utf-8"
    )
    recorded_names = {binding.name for binding in manifest.tools if binding.mode == "recorded"}
    recording_lines = []
    for run in optimization:
        for event in run.events:
            if isinstance(event, ToolCall) and event.name in recorded_names:
                recording_lines.append(
                    json.dumps(
                        {
                            "run_id": run.run_id,
                            "tool": event.name,
                            "args": event.args,
                            "result": event.result,
                        },
                        sort_keys=True,
                    )
                )
    (directory / "recordings.jsonl").write_text(
        ("\n".join(recording_lines) + "\n") if recording_lines else "", encoding="utf-8"
    )
    (directory / "harness.py").write_text(_HARNESS_PY, encoding="utf-8")
    (directory / "Makefile").write_text(_MAKEFILE, encoding="utf-8")


def load_manifest(directory: Path) -> HarnessManifest:
    """Read a harness directory, including the operator seal the proposer manifest omits."""
    payload = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    seal_path = directory / "SEAL.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8")) if seal_path.exists() else {}
    payload["holdout_run_ids"] = seal.get("holdout_run_ids", payload.get("holdout_run_ids", []))
    return HarnessManifest.model_validate(payload)


def _recordings(runs: Sequence[Run]) -> dict[str, list[ToolCall]]:
    found: dict[str, list[ToolCall]] = {}
    for run in runs:
        for event in run.events:
            if isinstance(event, ToolCall):
                found.setdefault(event.name, []).append(event)
    return found
