"""The process dies between the outbox intent and done (ANNEAL-ROADMAP.md M1.7).

A child process runs a one-step plan whose side-effect tool appends to a ledger
file, and kills itself (`os._exit`) before or after the effect. The parent then
restarts: `recover` reconciles the open intent against the ledger.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from anneal.runtime.outbox import NeedsHuman, Outbox, ReconcileAnswer, recover

CHILD = textwrap.dedent(
    """
    import json, os, sys
    from anneal.compile.plan import EndStep, ToolStep, WorkflowPlan
    from anneal.runtime.executor import Executor
    from anneal.runtime.outbox import Outbox

    outbox_dir, ledger, crash = sys.argv[1:4]
    plan = WorkflowPlan.build(
        workflow_id="wf",
        skeleton_hash="h",
        compiled_from=[],
        steps=[
            ToolStep(id="s0", name="pay", args_template={"amount": "{{input.amount}}"},
                     severity="S1", reconcile=True),
            EndStep(output_template="{{steps.s0.result}}"),
        ],
    )

    def pay(step, args, key):
        if crash == "before_effect":
            os._exit(137)
        with open(ledger, "a") as f:
            f.write(json.dumps({"key": key, "amount": args["amount"]}) + "\\n")
            f.flush()
            os.fsync(f.fileno())
        if crash == "after_effect":
            os._exit(137)
        return {"paid": True}

    def no_llm(*a):
        raise AssertionError

    Executor(plan, tools=pay, llm=no_llm, live_severities=frozenset({"S0", "S1", "S2"}),
             outbox=Outbox(outbox_dir), reconcilers={"pay": lambda key: "unknown"}
    ).run({"amount": 10}, run_id="chaos")
    print("finished")
    """
)
KEY = "anneal-chaos-s0"


def run_child(tmp_path: Path, crash: str) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "child.py"
    script.write_text(CHILD)
    args = [str(tmp_path / "outbox"), str(tmp_path / "ledger.jsonl"), crash]
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


def ledger(tmp_path: Path) -> list[dict[str, object]]:
    path = tmp_path / "ledger.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def from_ledger(tmp_path: Path) -> dict[str, object]:
    def reconcile(key: str) -> ReconcileAnswer:
        return "done" if any(e["key"] == key for e in ledger(tmp_path)) else "not_done"

    return {"pay": reconcile}


@pytest.mark.parametrize(
    ("crash", "answer", "effects"), [("after_effect", "done", 1), ("before_effect", "not_done", 0)]
)
def test_restart_reconciles_without_double_execution(
    tmp_path: Path, crash: str, answer: str, effects: int
) -> None:
    child = run_child(tmp_path, crash)
    assert child.returncode == 137, child.stderr
    outbox = Outbox(tmp_path / "outbox")
    assert [r.key for r in outbox.open_intents()] == [KEY]  # durable before the call
    (record,) = recover(outbox, from_ledger(tmp_path))  # type: ignore[arg-type]
    assert record.state == answer
    assert len(ledger(tmp_path)) == effects  # recovery never re-executes


def test_the_same_operation_cannot_run_twice_after_a_crash(tmp_path: Path) -> None:
    assert run_child(tmp_path, "after_effect").returncode == 137
    rerun = run_child(tmp_path, "none")
    assert rerun.returncode != 0 and "already in the outbox" in rerun.stderr
    assert len(ledger(tmp_path)) == 1


def test_a_tool_that_cannot_answer_is_unknown_and_goes_to_a_human(tmp_path: Path) -> None:
    assert run_child(tmp_path, "after_effect").returncode == 137
    outbox = Outbox(tmp_path / "outbox")

    def unreachable(key: str) -> ReconcileAnswer:
        raise ConnectionError("payments API down")

    with pytest.raises(NeedsHuman) as excinfo:
        recover(outbox, {"pay": unreachable})
    assert [(r.key, r.state) for r in excinfo.value.records] == [(KEY, "unknown")]
    assert outbox.get(KEY).state == "unknown"  # type: ignore[union-attr]
    assert len(ledger(tmp_path)) == 1


def test_a_clean_run_marks_the_intent_done(tmp_path: Path) -> None:
    child = run_child(tmp_path, "none")
    assert child.returncode == 0 and "finished" in child.stdout
    assert Outbox(tmp_path / "outbox").get(KEY).state == "done"  # type: ignore[union-attr]
    assert len(ledger(tmp_path)) == 1
