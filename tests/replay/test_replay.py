import json
from pathlib import Path
from typing import Any

import pytest
from synth.checks import support_task_done
from synth.generator import WORKFLOW, generate

from anneal.cli import main
from anneal.compile.compiler import ToolSpec
from anneal.compile.plan import ToolStep
from anneal.replay.replay import ReplayReport, render_markdown, replay, replay_plan
from anneal.replay.split import chronological_split
from anneal.schema import ModelCall, Run
from anneal.schema.store import Store

TOOLS = {
    "lookup_customer": ToolSpec(side_effect=False, severity="S0", idempotent=True),
    "create_ticket": ToolSpec(severity="S1", idempotent=True),
    "auto_reply": ToolSpec(severity="S1"),
    "escalate": ToolSpec(severity="S1"),
    "send_email": ToolSpec(severity="S2"),
}


@pytest.fixture(scope="module")
def runs() -> list[Run]:
    return generate(seed=0)[0]


@pytest.fixture(scope="module")
def report(runs: list[Run]) -> ReplayReport:
    return replay(runs, tools=TOOLS, task_check=support_task_done)


def tool_route(run: Run) -> str:
    return next(
        e.name for e in run.events if e.kind == "tool_call" and e.name in {"auto_reply", "escalate"}
    )


def test_compiles_on_the_early_runs_and_tests_on_the_late_ones(
    runs: list[Run], report: ReplayReport
) -> None:
    compile_runs, holdout = chronological_split(runs, 0.7)
    assert report.compiled and report.plan_id
    assert (report.compile_runs, report.holdout_runs) == (len(compile_runs), len(holdout))
    assert [r.run_id for r in report.rows] == [r.run_id for r in holdout]


def test_on_path_runs_succeed_and_branches_fall_back(runs: list[Run], report: ReplayReport) -> None:
    _, holdout = chronological_split(runs, 0.7)
    by_id = {r.run_id: r for r in holdout}
    for row in report.rows:
        run = by_id[row.run_id]
        variant = any(e.kind == "tool_call" and e.name == "add_note" for e in run.events)
        if tool_route(run) == "escalate":
            assert (row.outcome, row.step_id) == ("fallback", "s3"), row
        elif variant:
            assert (row.outcome, row.step_id) == ("fallback", "s8"), row
        else:
            assert row.outcome == "correct", row
            assert row.equivalent is True
    assert report.wrong_by_severity == {"S0": 0, "S1": 0, "S2": 0}


def test_rates_are_reported_against_tier0(report: ReplayReport) -> None:
    assert report.tier0_success_rate == 1.0
    assert report.compiled_success_rate == 1.0  # fallbacks finish in the original agent
    n = report.holdout_runs
    assert report.fallback_rate == pytest.approx(report.fallback / n)
    assert report.correct + report.fallback == n
    assert report.deopt_by_step["s3"] == sum(1 for r in report.rows if r.step_id == "s3")
    assert report.llm_mode == "recorded"


def test_cost_per_run_compiled_vs_tier0(report: ReplayReport) -> None:
    for row in report.rows:
        if row.outcome == "correct":
            assert row.cost_compiled == pytest.approx(
                row.cost_tier0 - 0.010
            )  # the removable lookup
        else:
            assert row.cost_compiled >= row.cost_tier0  # fallback pays for both, conservatively
    assert report.cost_per_run_tier0 == pytest.approx(
        sum(r.cost_tier0 for r in report.rows) / len(report.rows)
    )


def test_a_wrong_binding_is_a_wrong_execution_at_the_tools_severity(
    runs: list[Run], report: ReplayReport
) -> None:
    from anneal.compile.compiler import compile_plan

    compile_runs, holdout = chronological_split(runs, 0.7)
    plan = compile_plan(compile_runs, tools=TOOLS).plan
    assert plan is not None
    broken_steps: list[Any] = [
        s.model_copy(
            update={"args_template": {**s.args_template, "customer_id": "{{input.email}}"}}
        )
        if isinstance(s, ToolStep) and s.name == "create_ticket"
        else s
        for s in plan.steps
    ]
    broken = plan.model_copy(update={"steps": broken_steps})
    result = replay_plan(broken, holdout, task_check=support_task_done)
    assert result.wrong_by_severity["S1"] == len(holdout)
    assert {r.step_id for r in result.rows} == {"s2"}
    assert result.divergence_by_step == {"s2": len(holdout)}
    assert result.wrong_rate_by_severity["S1"] == 1.0


def test_failed_task_check_without_divergence_is_wrong_at_s0(runs: list[Run]) -> None:
    def tier1_never_done(run: Run, recorded: Run) -> bool:
        return run.tier == 0

    result = replay(runs, tools=TOOLS, task_check=tier1_never_done)
    accepted = [r for r in result.rows if r.outcome != "fallback"]
    assert accepted and all((r.outcome, r.severity) == ("wrong", "S0") for r in accepted)
    assert result.wrong_by_severity["S0"] == len(accepted)


def test_default_check_is_output_equivalence(runs: list[Run]) -> None:
    result = replay(runs, tools=TOOLS)
    assert result.task_check == "same_outcome (default: output equivalence, not a partner check)"
    assert result.wrong_by_severity["S0"] == 0


def test_nothing_compiled_is_reported(runs: list[Run]) -> None:
    result = replay(runs[:6], tools=TOOLS)
    assert not result.compiled and result.rows == []
    assert any("support" in line for line in result.compile_log)


def test_live_llm_factory_is_labelled(runs: list[Run]) -> None:
    from anneal.replay.recording import RecordedLlm

    result = replay(runs, tools=TOOLS, llm_factory=RecordedLlm)
    assert result.llm_mode == "live"


def test_markdown(report: ReplayReport) -> None:
    text = render_markdown(report)
    for heading in [
        "# anneal replay",
        "## Outcomes",
        "## Wrong executions by severity",
        "## Deopts and divergences by step",
        "## Cost per run",
    ]:
        assert heading in text


def test_cli_replay(tmp_path: Path, runs: list[Run], capsys: pytest.CaptureFixture[str]) -> None:
    Store(tmp_path / "store").write(runs)
    tools = tmp_path / "tools.yaml"
    tools.write_text("\n".join(f"{n}: {json.dumps(s.model_dump())}" for n, s in TOOLS.items()))
    args = ["replay", str(tmp_path / "store"), "--workflow", WORKFLOW, "--tools", str(tools)]
    assert main([*args, "--check", "synth.checks:support_task_done", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["compiled"] and out["wrong_by_severity"] == {"S0": 0, "S1": 0, "S2": 0}
    assert out["task_check"] == "synth.checks:support_task_done"
    assert main(args) == 0
    assert "# anneal replay: synth_support" in capsys.readouterr().out


def test_holdout_model_calls_are_never_seen_by_the_compiler(
    runs: list[Run], report: ReplayReport
) -> None:
    _, holdout = chronological_split(runs, 0.7)
    held = {e.event_id for r in holdout for e in r.events if isinstance(e, ModelCall)}
    assert held and not held & set(report.compiled_from)
    assert not {r.run_id for r in holdout} & set(report.compiled_from)


def broken_read(runs: list[Run]) -> tuple[Any, list[Run]]:
    """A plan whose read-only lookup is called with arguments no recording has, as a
    live model writing its own arguments would."""
    from anneal.compile.compiler import compile_plan

    compile_runs, holdout = chronological_split(runs, 0.7)
    plan = compile_plan(compile_runs, tools=TOOLS).plan
    assert plan is not None
    steps: list[Any] = [
        s.model_copy(update={"args_template": {**s.args_template, "include": "everything"}})
        if isinstance(s, ToolStep) and s.name == "lookup_customer"
        else s
        for s in plan.steps
    ]
    return plan.model_copy(update={"steps": steps}), holdout


def test_unrecorded_read_arguments_diverge_against_the_recording(runs: list[Run]) -> None:
    plan, holdout = broken_read(runs)
    result = replay_plan(plan, holdout, task_check=support_task_done)
    assert result.tools_mode == "recorded"
    assert result.wrong_by_severity["S0"] == len(holdout)


def test_live_read_only_tools_serve_reads_and_writes_stay_recorded(runs: list[Run]) -> None:
    plan, holdout = broken_read(runs)
    live_calls: list[str] = []

    def live(recorded: Run) -> Any:
        recorded_results = {e.name: e.result for e in recorded.events if e.kind == "tool_call"}

        def call(step: ToolStep, args: Any, key: str | None) -> Any:
            live_calls.append(step.name)
            return recorded_results[step.name]

        return call

    result = replay_plan(plan, holdout, task_check=support_task_done, live_tools=live)
    assert result.tools_mode == "live read-only"
    assert set(live_calls) == {"lookup_customer"}  # side-effect tools never run live
    assert result.wrong_by_severity == {"S0": 0, "S1": 0, "S2": 0}
