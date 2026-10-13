"""The Milestone 1 experiment end to end on the simulated support workflow (`make m1`).

Writes `report/m1.md`. Every number is synthetic (see the banner in the memo); the
same steps run on a partner's store once there is one: analyze, compile on the first
70%, replay the rest with the agreed task check, inject 20 deopts into the real
agent, run the three arms with the drift suite, then evaluate Gate 1 (ADR 0010).
"""

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1]))

from anneal.compile.compiler import compile_plan
from anneal.compile.plan import LlmStep, ToolStep, WorkflowPlan
from anneal.replay.replay import replay_plan
from anneal.replay.split import chronological_split
from anneal.report.analyze import analyze
from anneal.report.memo import DeoptTrial, FallbackReport, ManualStep, Memo, render_memo
from anneal.runtime.executor import DeoptRequested, LlmResponse
from anneal.runtime.fallback import CompiledWorkflow
from anneal.schema import Message, Run, ToolCall
from synth.arms import ALL, BASELINE_DIR, TOOLS, SimLlm, run_experiment
from synth.env import WORKFLOW, Env, Tier0Agent, generate_traces, task_done

OUT = Path(__file__).parents[2] / "report" / "m1.md"
Customers = dict[str, tuple[str, str]]

OPEN_ITEMS = [
    "A partner workflow: every number in this memo is synthetic until one exists.",
    "The task check agreed in writing with the partner before compilation (M1.5).",
    "Replay with live model answers on the partner's holdout (H3; recorded answers here).",
    "20 injected deopts on the partner's real runs and real agent (M1.6).",
    "A baseline written for the partner's workflow under the one-day time box (M1.8).",
    "Timed human setup for the compiled arm (tool declarations, task check), so build time "
    "can be compared (H4).",
    "Interview signal: what five teams say when asked whether they would just write the script.",
    "The memo sent to the partner and to at least two other teams (M1.9).",
]

MANUAL_STEPS = [
    ManualStep(
        step=f"Declared {len(TOOLS)} tools (side effect, severity, idempotency)",
        why="the compiler cannot infer what a write does or whether it can be repeated",
        automate_in="M2 SDK: declared once at tool registration",
    ),
    ManualStep(
        step="Wrote the task check",
        why="what counts as the job done is the partner's definition",
        automate_in="never; agreed per workflow",
    ),
    ManualStep(
        step="Wrote the baseline brief from the task definition",
        why="the baseline author must get the same information as the compiler",
        automate_in="never; part of the protocol",
    ),
]


def env_check(customers: Customers) -> Any:
    def check(run: Run, recorded: Run) -> bool:
        effects = [
            (e.name, dict(e.args))
            for e in run.events
            if isinstance(e, ToolCall) and not e.error and isinstance(e.args, dict)
        ]
        return run.status == "success" and task_done(run.input, effects, customers)

    check.__module__, check.__qualname__ = "synth.m1", "env_task_done"
    return check


def inject_deopts(
    plan: WorkflowPlan, holdout: list[Run], customers: Customers, n: int = 20
) -> FallbackReport:
    """Deopt at every step in turn on inputs the plan accepts; resume with the agent."""

    def workflow(env: Env, at: str | None, mark: list[int]) -> CompiledWorkflow:
        llm = SimLlm(plan)

        def tools(step: ToolStep, args: Any, key: str | None) -> Any:
            if step.id == at:
                raise DeoptRequested(step.id, "injected")
            return env.call(step.name, args)

        def model(step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
            if step.id == at:
                raise DeoptRequested(step.id, "injected")
            return llm(step, system, user, feedback)

        def fallback(history: list[Message], run_input: Any) -> Any:
            mark.append(len(env.effects))
            answer, _, _ = Tier0Agent(env).run(run_input, history=history)
            return {"answer": answer}

        return CompiledWorkflow(
            plan, tools=tools, llm=model, fallback=fallback, live_severities=ALL
        )

    accepted = [
        r
        for r in holdout
        if workflow(Env(customers), None, []).run(r.input, run_id=r.run_id).tier == 1
    ]
    steps = [s.id for s in plan.steps if not s.id.startswith("end")]
    trials = []
    for i in range(n):
        run, at = accepted[i % len(accepted)], steps[i % len(steps)]
        env, mark = Env(customers), list[int]()
        outcome = workflow(env, at, mark).run(run.input, run_id=f"inject:{run.run_id}:{at}")
        split = mark[0] if mark else len(env.effects)
        compiled = {name for name, _ in env.effects[:split] if name != "lookup_customer"}
        agent = [name for name, _ in env.effects[split:]]
        trials.append(
            DeoptTrial(
                run_id=run.run_id,
                step_id=outcome.execution.deopt.step_id if outcome.execution.deopt else "none",
                task_success=outcome.tier == 0 and task_done(run.input, env.effects, customers),
                repeated=sorted(compiled & set(agent)),
            )
        )
    return FallbackReport(framework="synthetic history-driven agent", trials=trials)


def baseline_seconds() -> float | None:
    log = BASELINE_DIR / "BUILD_LOG.md"
    m = re.search(r"Time spent: (\d+) min (\d+) s", log.read_text()) if log.exists() else None
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def build_memo() -> Memo:
    runs, customers = generate_traces()
    compile_runs, holdout = chronological_split(runs, 0.7)
    result = compile_plan(compile_runs, tools=TOOLS)
    assert result.plan is not None, result.log
    plan = result.plan
    replay = replay_plan(
        plan,
        holdout,
        task_check=env_check(customers),
        compile_runs=len(compile_runs),
        compile_log=result.log,
    )
    experiment = run_experiment()
    seconds = baseline_seconds()
    manual = MANUAL_STEPS + [
        ManualStep(step=f"Override `{o.key}`", why="binding the compiler refused", automate_in="M2")
        for o in plan.manual_overrides
    ]
    return Memo(
        workflow_id=WORKFLOW,
        synthetic=True,
        source=(
            f"simulated support environment, {len(runs)} Tier 0 runs "
            "(`tests/synth/env.py`); baseline in `baseline/env_support/`"
        ),
        analyze_all=analyze(runs),
        analyze_holdout=analyze(holdout),
        replay=replay,
        fallback=inject_deopts(plan, holdout, customers),
        arms=experiment.report,
        build_seconds={"tier0": None, "compiled": None, "baseline": seconds},
        build_notes={
            "tier0": "n/a (existing agent)",
            "compiled": f"{experiment.compile_seconds:.2f} s compute; human setup not timed",
            "baseline": f"{seconds} s (agent, one sitting)" if seconds else "not measured",
        },
        manual_steps=manual,
        open_items=OPEN_ITEMS,
    )


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(render_memo(build_memo()))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
