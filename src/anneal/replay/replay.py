"""Chronological replay with task-level checks (ANNEAL-ROADMAP.md M1.5).

Compile on the first `compile_share` of runs by time, then run the plan on
every later run. Tools are served from that run's recording; llm steps are
answered from its recorded model calls (`llm_mode="recorded"`) unless a live
runner factory is given. Each holdout run ends up:

- `fallback`: the plan deopted (guard, off-path choice, invalid output, a
  recorded tool error). The original agent finishes it, so for system-level
  success it counts as Tier 0's own outcome;
- `wrong`: the plan's guards accepted it and either a tool call diverged from
  the recording (severity: that tool step's) or the task check failed (S0);
- `correct`: the task check passed.

Wrong-execution rates are among accepted runs (`correct + wrong`).
Compiled cost is what the trace spent; a fallback also pays the full Tier 0
cost of the run, an upper bound on resuming.
"""

import importlib
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from anneal.classify.classifier import MIN_SUPPORT, STABLE_SHARE
from anneal.compile.compiler import ToolSpec, compile_plan
from anneal.compile.plan import ToolStep, WorkflowPlan
from anneal.replay.critical import equivalent
from anneal.replay.recording import RecordedLlm, RecordingToolServer
from anneal.replay.split import chronological_split
from anneal.runtime.executor import Executor, LlmRunner
from anneal.schema import ModelCall, Run, Severity

ALL_SEVERITIES: frozenset[Severity] = frozenset({"S0", "S1", "S2"})
DEFAULT_CHECK_LABEL = "same_outcome (default: output equivalence, not a partner check)"


class TaskCheck(Protocol):
    def __call__(self, run: Run, recorded: Run) -> bool:
        """Was the job done in `run`? `recorded` is the Tier 0 run for the same input."""
        ...


def same_outcome(run: Run, recorded: Run) -> bool:
    """Default check: the run succeeded and its output is equivalent to the recorded one."""
    return run.status == "success" and equivalent(run.output, recorded.output)


def load_check(spec: str) -> TaskCheck:
    """Import a task check from `package.module:function`."""
    module, _, name = spec.partition(":")
    check: TaskCheck = getattr(importlib.import_module(module), name)
    return check


class ReplayRow(BaseModel):
    run_id: str
    outcome: Literal["correct", "wrong", "fallback"]
    severity: Severity | None = None
    step_id: str | None = None
    reason: str | None = None
    tier0_success: bool
    equivalent: bool | None = None
    cost_tier0: float
    cost_compiled: float


class ReplayReport(BaseModel):
    workflow_id: str
    compiled: bool
    plan_id: str | None
    compiled_from: list[str]
    compile_log: list[str]
    compile_runs: int
    holdout_runs: int
    llm_mode: Literal["recorded", "live"]
    task_check: str
    correct: int
    fallback: int
    wrong_by_severity: dict[str, int]
    wrong_rate_by_severity: dict[str, float]
    fallback_rate: float
    tier0_success_rate: float
    compiled_success_rate: float
    accepted_success_rate: float | None
    output_equivalence_rate: float | None
    deopt_by_step: dict[str, int]
    divergence_by_step: dict[str, int]
    cost_per_run_tier0: float
    cost_per_run_compiled: float
    rows: list[ReplayRow]


def _cost(run: Run) -> float:
    return sum(e.cost_usd or 0.0 for e in run.events if isinstance(e, ModelCall))


def _label(check: TaskCheck | None) -> str:
    if check is None:
        return DEFAULT_CHECK_LABEL
    return f"{getattr(check, '__module__', '?')}:{getattr(check, '__qualname__', repr(check))}"


def replay_plan(
    plan: WorkflowPlan,
    holdout: Sequence[Run],
    *,
    task_check: TaskCheck | None = None,
    llm_factory: Callable[[Run], LlmRunner] | None = None,
    compile_runs: int = 0,
    compile_log: list[str] | None = None,
) -> ReplayReport:
    """Run `plan` on every holdout run against its recording and score it."""
    check = task_check or same_outcome
    steps = {s.id: s for s in plan.steps}
    rows: list[ReplayRow] = []
    for recorded in holdout:
        server = RecordingToolServer(recorded)
        llm = llm_factory(recorded) if llm_factory else RecordedLlm(recorded)
        executor = Executor(plan, tools=server, llm=llm, live_severities=ALL_SEVERITIES)
        result = executor.run(recorded.input, run_id=f"replay:{recorded.run_id}")
        tier0_ok = bool(check(recorded, recorded))
        cost_tier0 = _cost(recorded)
        spent = _cost(result.trace)
        row: dict[str, Any] = {
            "run_id": recorded.run_id,
            "tier0_success": tier0_ok,
            "cost_tier0": cost_tier0,
        }
        if server.divergence is not None:
            step = steps[server.divergence.step_id]
            severity = step.severity if isinstance(step, ToolStep) else "S0"
            rows.append(
                ReplayRow(
                    **row,
                    outcome="wrong",
                    severity=severity,
                    step_id=step.id,
                    reason=f"diverged: {server.divergence.tool} called with unrecorded arguments",
                    cost_compiled=spent,
                )
            )
        elif result.deopt is not None:
            rows.append(
                ReplayRow(
                    **row,
                    outcome="fallback",
                    step_id=result.deopt.step_id,
                    reason=result.deopt.reason,
                    cost_compiled=spent + cost_tier0,
                )
            )
        else:
            ok = bool(check(result.trace, recorded))
            rows.append(
                ReplayRow(
                    **row,
                    outcome="correct" if ok else "wrong",
                    severity=None if ok else "S0",
                    reason=None if ok else "task check failed",
                    equivalent=equivalent(result.output, recorded.output),
                    cost_compiled=spent,
                )
            )
    return _report(
        plan, rows, compile_runs, compile_log or plan.compile_log, llm_factory, task_check
    )


def _report(
    plan: WorkflowPlan | None,
    rows: list[ReplayRow],
    compile_runs: int,
    compile_log: list[str],
    llm_factory: object,
    task_check: TaskCheck | None,
) -> ReplayReport:
    n = len(rows)
    accepted = [r for r in rows if r.outcome != "fallback"]
    wrong = Counter(r.severity for r in rows if r.outcome == "wrong")
    completed = [r for r in accepted if r.equivalent is not None]

    def rate(k: float, d: float) -> float:
        return k / d if d else 0.0

    return ReplayReport(
        workflow_id=plan.workflow_id if plan else "",
        compiled=plan is not None,
        plan_id=plan.plan_id if plan else None,
        compiled_from=plan.compiled_from if plan else [],
        compile_log=compile_log,
        compile_runs=compile_runs,
        holdout_runs=n,
        llm_mode="live" if llm_factory else "recorded",
        task_check=_label(task_check),
        correct=sum(1 for r in rows if r.outcome == "correct"),
        fallback=n - len(accepted),
        wrong_by_severity={s: wrong.get(s, 0) for s in ("S0", "S1", "S2")},
        wrong_rate_by_severity={
            s: rate(wrong.get(s, 0), len(accepted)) for s in ("S0", "S1", "S2")
        },
        fallback_rate=rate(n - len(accepted), n),
        tier0_success_rate=rate(sum(r.tier0_success for r in rows), n),
        compiled_success_rate=rate(
            sum(
                r.outcome == "correct" or (r.outcome == "fallback" and r.tier0_success)
                for r in rows
            ),
            n,
        ),
        accepted_success_rate=rate(sum(r.outcome == "correct" for r in accepted), len(accepted))
        if accepted
        else None,
        output_equivalence_rate=rate(sum(bool(r.equivalent) for r in completed), len(completed))
        if completed
        else None,
        deopt_by_step=dict(
            Counter(r.step_id for r in rows if r.outcome == "fallback" and r.step_id)
        ),
        divergence_by_step=dict(
            Counter(
                r.step_id
                for r in rows
                if r.reason and r.reason.startswith("diverged") and r.step_id
            )
        ),
        cost_per_run_tier0=rate(sum(r.cost_tier0 for r in rows), n),
        cost_per_run_compiled=rate(sum(r.cost_compiled for r in rows), n),
        rows=rows,
    )


def replay(
    runs: Sequence[Run],
    *,
    compile_share: float = 0.7,
    tools: dict[str, ToolSpec] | None = None,
    task_check: TaskCheck | None = None,
    overrides: dict[str, Any] | None = None,
    llm_factory: Callable[[Run], LlmRunner] | None = None,
    min_support: int = MIN_SUPPORT,
    stable_share: float = STABLE_SHARE,
) -> ReplayReport:
    """Split by time, compile on the early runs, replay the late ones."""
    compile_runs, holdout = chronological_split(runs, compile_share)
    result = compile_plan(
        compile_runs,
        tools=tools,
        overrides=overrides,
        min_support=min_support,
        stable_share=stable_share,
    )
    if result.plan is None:
        report = _report(None, [], len(compile_runs), result.log, llm_factory, task_check)
        return report.model_copy(
            update={"workflow_id": runs[0].workflow_id, "holdout_runs": len(holdout)}
        )
    return replay_plan(
        result.plan,
        holdout,
        task_check=task_check,
        llm_factory=llm_factory,
        compile_runs=len(compile_runs),
        compile_log=result.log,
    )


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def render_markdown(r: ReplayReport) -> str:
    """Human-readable replay report."""
    out = [
        f"# anneal replay: {r.workflow_id}",
        "",
        f"Compiled on the first {r.compile_runs} runs by time; "
        f"replayed {r.holdout_runs} later runs.",
        f"LLM answers: {r.llm_mode}. Task check: {r.task_check}.",
    ]
    if r.llm_mode == "recorded":
        out.append(
            "Recorded mode measures the deterministic parts; forced llm steps are not "
            "exercised against a live model."
        )
    if not r.compiled:
        return (
            "\n".join([*out, "", "Nothing compiled:", *(f"- {line}" for line in r.compile_log)])
            + "\n"
        )
    correct_rate = r.correct / r.holdout_runs if r.holdout_runs else None
    out += [
        f"Plan: {r.plan_id}.",
        "",
        "## Outcomes",
        "",
        "| | runs | rate |",
        "| --- | ---: | ---: |",
        f"| correct | {r.correct} | {_pct(correct_rate)} |",
        f"| wrong | {sum(r.wrong_by_severity.values())} | |",
        f"| fallback | {r.fallback} | {_pct(r.fallback_rate)} |",
        "",
        f"Task success: Tier 0 {_pct(r.tier0_success_rate)}, compiled with fallback "
        f"{_pct(r.compiled_success_rate)}, "
        f"compiled among accepted {_pct(r.accepted_success_rate)}.",
        f"Output equivalence among completed runs (evidence): {_pct(r.output_equivalence_rate)}.",
        "",
        "## Wrong executions by severity",
        "",
        "| severity | runs | rate among accepted |",
        "| --- | ---: | ---: |",
    ]
    out += [
        f"| {s} | {r.wrong_by_severity[s]} | {_pct(r.wrong_rate_by_severity[s])} |"
        for s in ("S0", "S1", "S2")
    ]
    out += ["", "## Deopts and divergences by step", "", "| step | deopts | divergences |"]
    out.append("| --- | ---: | ---: |")
    for step in sorted(set(r.deopt_by_step) | set(r.divergence_by_step)):
        out.append(
            f"| {step} | {r.deopt_by_step.get(step, 0)} | {r.divergence_by_step.get(step, 0)} |"
        )
    out += [
        "",
        "## Cost per run",
        "",
        f"Tier 0 ${r.cost_per_run_tier0:,.4f}; compiled ${r.cost_per_run_compiled:,.4f} "
        "(a fallback is charged its compiled spend plus the full Tier 0 run).",
    ]
    return "\n".join(out) + "\n"
