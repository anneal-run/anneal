"""The harness is built from traces. The proposer never receives the holdout."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

from anneal.challenge.harness import build_harness, write_harness
from anneal.compile.compiler import ToolSpec
from anneal.schema import Event, ModelCall, Run, ToolCall

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def run(i: int, *, tool: str | None) -> Run:
    started = T0 + timedelta(days=i)
    events: list[Event] = [
        ModelCall(
            event_id=f"m{i}",
            ts=started,
            model="claude-haiku-5-5",
            tokens_in=100,
            tokens_out=20,
            cost_usd=0.0035,
        )
    ]
    if tool is not None:
        events.append(
            ToolCall(
                event_id=f"t{i}",
                ts=started,
                name=tool,
                args={"repo": "astral-sh/uv", "number": i},
                result={"ok": True},
            )
        )
    return Run(
        run_id=f"run-{i:04d}",
        workflow_id="github_triage",
        started_at=started,
        ended_at=started,
        status="success",
        input={"number": i},
        output={"labels": ["bug"]},
        source="langsmith",
        events=events,
    )


def test_holdout_stays_out_of_the_proposer_harness(tmp_path: Path) -> None:
    runs = [run(0, tool="post_comment"), run(1, tool="get_issue"), run(2, tool="get_issue")]
    manifest = build_harness(
        runs,
        tools={
            "get_issue": ToolSpec(side_effect=False, severity="S0"),
            "post_comment": ToolSpec(side_effect=True, severity="S1", idempotent=True),
            "send_email": ToolSpec(side_effect=True, severity="S2"),
        },
        compile_share=2 / 3,
        entrypoint="python -c 'print(1)'",
        workflow_files=["examples/github_triage/agent.py"],
    )
    assert manifest.optimization_run_ids == ["run-0000", "run-0001"]
    assert manifest.holdout_run_ids == ["run-0002"]
    modes = {t.name: t.mode for t in manifest.tools}
    assert modes["get_issue"] == "live"
    assert modes["post_comment"] == "recorded"
    assert modes["send_email"] == "mock"
    write_harness(manifest, runs, tmp_path)
    proposer = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    fixtures = (tmp_path / "fixtures.jsonl").read_text(encoding="utf-8")
    assert "run-0002" not in proposer
    assert "run-0002" not in fixtures
    assert "send_email" in proposer


def test_generated_harness_serves_recordings_and_refuses_mocks(tmp_path: Path) -> None:
    runs = [run(0, tool="post_comment"), run(1, tool="get_issue")]
    manifest = build_harness(
        runs,
        tools={
            "get_issue": ToolSpec(side_effect=False, severity="S0"),
            "post_comment": ToolSpec(side_effect=True, severity="S1", idempotent=True),
            "send_email": ToolSpec(side_effect=True, severity="S2"),
        },
        compile_share=0.5,
        entrypoint=None,
        workflow_files=[],
    )
    write_harness(manifest, runs, tmp_path)
    spec = importlib.util.spec_from_file_location("generated_harness", tmp_path / "harness.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert isinstance(module, ModuleType)
    assert module.call_tool("post_comment", {"number": 0, "repo": "astral-sh/uv"}) == {"ok": True}
    try:
        module.call_tool("send_email", {})
    except module.MockedToolError:
        pass
    else:
        raise AssertionError("mocked tool was served as if it were real")


def test_meter_refuses_a_call_past_the_budget_and_does_not_record_it(tmp_path: Path) -> None:
    runs = [run(0, tool="get_issue"), run(1, tool="get_issue")]
    manifest = build_harness(
        runs,
        tools={"get_issue": ToolSpec(side_effect=False, severity="S0")},
        compile_share=0.5,
        entrypoint=None,
        workflow_files=[],
    )
    write_harness(manifest, runs, tmp_path)
    (tmp_path / "BUDGET.json").write_text(
        '{"candidates": 1, "dollars": 1.0, "hours": 1.0}\n', encoding="utf-8"
    )
    spec = importlib.util.spec_from_file_location("metered_harness", tmp_path / "harness.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    meter = module.meter()
    meter.record(0.6, 10)
    try:
        meter.record(0.5, 10)
    except module.BudgetExceeded:
        pass
    else:
        raise AssertionError("a call past the budget was recorded")
    assert meter.total_usd == 0.6
    assert (tmp_path / "meter.jsonl").read_text(encoding="utf-8").count("\n") == 1
