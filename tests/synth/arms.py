"""The three arms on the simulated support environment, and the experiment that compares them.

Every model call costs `MODEL_CALL_USD` in every arm, so cost per task compares how
many model calls each arm makes. The compiled arm is evaluated as it would run once
promoted (all severities live, writes declared idempotent); under the M1 policy it
would deopt before its first write.
"""

import importlib.util
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from anneal.compile.compiler import ToolSpec, compile_plan
from anneal.compile.plan import LlmStep, ToolStep, WorkflowPlan
from anneal.replay.arms import ArmRun, ArmsReport, Case, evaluate
from anneal.replay.split import chronological_split
from anneal.runtime.executor import LlmResponse
from anneal.runtime.fallback import CompiledWorkflow
from anneal.schema import Message, ModelCall, Severity
from synth.env import (
    DRIFTS,
    MODEL_CALL_USD,
    Env,
    ModelCapabilities,
    SimModel,
    Tier0Agent,
    ToolError,
    generate_traces,
    task_done,
)

BASELINE_DIR = Path(__file__).parents[2] / "baseline" / "env_support"
ALL: frozenset[Severity] = frozenset({"S0", "S1", "S2"})
TOOLS = {
    "lookup_customer": ToolSpec(side_effect=False, severity="S0", idempotent=True),
    "create_ticket": ToolSpec(severity="S1", idempotent=True),
    "auto_reply": ToolSpec(severity="S1", idempotent=True),
    "escalate": ToolSpec(severity="S1", idempotent=True),
    "send_email": ToolSpec(severity="S2", idempotent=True),
}
_RESULT = re.compile(r"Result of step (s\d+) \(([^)]*)\):\n(.*)")


def tier0_arm(customers: dict[str, tuple[str, str]]) -> Any:
    def arm(case: Case) -> ArmRun:
        env = Env(customers)
        answer, events, _ = Tier0Agent(env).run(case.input)
        calls = sum(isinstance(e, ModelCall) for e in events)
        error = answer if answer.startswith("Failed") else None
        return ArmRun(
            output={"answer": answer},
            cost_usd=calls * MODEL_CALL_USD,
            model_calls=calls,
            error=error,
            effects=env.effects,
        )

    return arm


class SimLlm:
    """Answers compiled llm steps the way the simulated model would, one call per step."""

    def __init__(self, plan: WorkflowPlan) -> None:
        self.model = SimModel()
        self.final_step = [s.id for s in plan.steps if isinstance(s, LlmStep)][-1]
        self.calls = 0

    def __call__(self, step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
        self.calls += 1
        run_input = json.loads(user.split("Run input:\n", 1)[1].split("\n\n", 1)[0])
        results = {name: json.loads(body) for _, name, body in _RESULT.findall(user)}
        message = self.model.message(run_input)
        topic = self.model.topic(message)
        ticket = results.get("create_ticket", {}).get("ticket_id")
        if step.forced_tool == "create_ticket":
            output: Any = {"summary": self.model.summarize(message)}
        elif step.forced_tool == "send_email":
            drafts = [
                v["text"] for k, v in results.items() if k.startswith("model") and "text" in v
            ]
            output = {"body": drafts[-1] if drafts else self.model.draft(ticket, topic)}
        elif step.expected_tool:
            tier = results.get("lookup_customer", {}).get("tier", "")
            output = {
                "tool": self.model.route(run_input.get("priority"), tier),
                "arguments": {"ticket_id": ticket},
            }
        elif step.id == self.final_step:
            output = {"text": self.model.final(ticket, topic)}
        else:
            output = {"text": self.model.draft(ticket, topic)}
        return LlmResponse(output=output, cost_usd=MODEL_CALL_USD)


def compiled_arm(plan: WorkflowPlan, customers: dict[str, tuple[str, str]]) -> Any:
    def arm(case: Case) -> ArmRun:
        env = Env(customers)
        llm = SimLlm(plan)
        fallback_calls = [0]

        def tools(step: ToolStep, args: Any, key: str | None) -> Any:
            return env.call(step.name, args)

        def fallback(history: list[Message], run_input: Any) -> Any:
            answer, events, _ = Tier0Agent(env).run(run_input, history=history)
            fallback_calls[0] = sum(isinstance(e, ModelCall) for e in events)
            return {"answer": answer}

        workflow = CompiledWorkflow(
            plan, tools=tools, llm=llm, fallback=fallback, live_severities=ALL
        )
        outcome = workflow.run(case.input, run_id=case.case_id)
        calls = llm.calls + fallback_calls[0]
        answer = str(outcome.output.get("answer", "")) if isinstance(outcome.output, dict) else ""
        return ArmRun(
            output=outcome.output,
            cost_usd=calls * MODEL_CALL_USD,
            model_calls=calls,
            fell_back=outcome.tier == 0,
            error=answer if answer.startswith("Failed") else None,
            effects=env.effects,
        )

    return arm


def load_baseline(directory: Path = BASELINE_DIR) -> ModuleType | None:
    path = directory / "workflow.py"
    if not path.exists():
        return None
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("env_support_baseline", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(directory))


def baseline_arm(module: ModuleType, customers: dict[str, tuple[str, str]]) -> Any:
    interface = sys.modules.get("interface")
    tool_error: type[Exception] = getattr(interface, "ToolError", ToolError)

    class EnvTools:
        def __init__(self, env: Env) -> None:
            self.env = env

        def call(self, name: str, args: dict[str, Any]) -> Any:
            try:
                return self.env.call(name, args)
            except ToolError as e:
                raise tool_error(str(e)) from None

    def arm(case: Case) -> ArmRun:
        env = Env(customers)
        model = ModelCapabilities()
        try:
            output = module.run(case.input, EnvTools(env), model)
            error = None
        except Exception as e:
            output, error = None, f"{type(e).__name__}: {e}"
        return ArmRun(
            output=output,
            cost_usd=model.calls * MODEL_CALL_USD,
            model_calls=model.calls,
            error=error,
            effects=env.effects,
        )

    return arm


@dataclass
class Experiment:
    report: ArmsReport
    plan: WorkflowPlan
    compile_seconds: float
    compile_runs: int
    holdout_runs: int


def run_experiment(n: int = 80, include_baseline: bool = True) -> Experiment:
    runs, customers = generate_traces(n)
    compile_runs, holdout = chronological_split(runs, 0.7)
    started = time.perf_counter()
    result = compile_plan(compile_runs, tools=TOOLS)
    compile_seconds = time.perf_counter() - started
    assert result.plan is not None, result.log
    cases = [Case(case_id=r.run_id, input=r.input) for r in holdout]
    cases += [
        Case(case_id=f"{r.run_id}:{name}", input=drift(r.input), drift=name)
        for name, drift in DRIFTS.items()
        for r in holdout
    ]
    arms = {"tier0": tier0_arm(customers), "compiled": compiled_arm(result.plan, customers)}
    if include_baseline and (module := load_baseline()) is not None:
        arms["baseline"] = baseline_arm(module, customers)

    def check(case: Case, run: ArmRun) -> bool:
        return task_done(case.input, run.effects, customers)

    return Experiment(
        report=evaluate(cases, arms, check),
        plan=result.plan,
        compile_seconds=compile_seconds,
        compile_runs=len(compile_runs),
        holdout_runs=len(holdout),
    )
