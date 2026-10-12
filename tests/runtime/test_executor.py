from datetime import UTC, datetime
from typing import Any

import pytest
from synth.generator import generate

from anneal.compile.compiler import ToolSpec, compile_plan
from anneal.compile.plan import EndStep, Guard, LlmStep, ToolStep, WorkflowPlan
from anneal.runtime.executor import Executor, LlmResponse
from anneal.schema import Deopt, ModelCall, ToolCall

ALL = frozenset({"S0", "S1", "S2"})
INPUT = {"email": "<EMAIL_1>", "message": "My order 1001 has a problem"}


@pytest.fixture(scope="module")
def plan() -> WorkflowPlan:
    runs, _ = generate(seed=0)
    result = compile_plan(
        runs, tools={"lookup_customer": ToolSpec(side_effect=False, severity="S0")}
    )
    assert result.plan is not None
    return result.plan


class FakeTools:
    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.fail = fail

    def __call__(self, step: ToolStep, args: Any) -> Any:
        self.calls.append((step.name, args))
        if step.name == self.fail:
            raise RuntimeError("upstream 503")
        return {
            "lookup_customer": {"customer_id": "C-0001", "tier": "gold"},
            "create_ticket": {"ticket_id": "T-00001"},
            "auto_reply": {"ok": True},
            "send_email": {"sent": True},
        }[step.name]


class FakeLlm:
    def __init__(self, overrides: dict[str, list[Any]] | None = None) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.overrides = overrides or {}

    def __call__(self, step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
        self.calls.append((step.id, user, feedback))
        if self.overrides.get(step.id):
            return LlmResponse(output=self.overrides[step.id].pop(0))
        if step.forced_tool == "create_ticket":
            output: Any = {"summary": "Calm customer reports late delivery"}
        elif step.expected_tool:
            output = {"tool": step.expected_tool, "arguments": {"ticket_id": "T-00001"}}
        elif step.forced_tool == "send_email":
            output = {"body": "Hello, about ticket T-00001."}
        else:
            output = {"text": "Done: ticket T-00001 handled."}
        return LlmResponse(
            output=output, model="gpt-4o-mini", tokens_in=100, tokens_out=10, cost_usd=0.001
        )


def clock() -> datetime:
    return datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def run(plan: WorkflowPlan, tools: Any = None, llm: Any = None, **kw: Any) -> Any:
    executor = Executor(plan, tools=tools or FakeTools(), llm=llm or FakeLlm(), clock=clock, **kw)
    return executor.run(INPUT, run_id="x1")


def test_full_run_executes_every_step_in_dependency_order(plan: WorkflowPlan) -> None:
    tools = FakeTools()
    result = run(plan, tools=tools, live_severities=ALL)
    assert result.status == "success", result.deopt
    assert result.output == {"answer": "Done: ticket T-00001 handled."}
    assert [name for name, _ in tools.calls] == [
        "lookup_customer",
        "create_ticket",
        "auto_reply",
        "send_email",
    ]
    assert tools.calls[0][1] == {"email": "<EMAIL_1>", "include": "tier"}
    assert tools.calls[1][1] == {
        "customer_id": "C-0001",
        "summary": "Calm customer reports late delivery",
    }
    assert result.completed == [s.id for s in plan.steps]
    assert result.state["s0"] == {"customer_id": "C-0001", "tier": "gold"}


def test_trace_is_a_tier1_run(plan: WorkflowPlan) -> None:
    trace = run(plan, live_severities=ALL).trace
    assert (trace.tier, trace.source, trace.status, trace.workflow_id) == (
        1,
        "anneal",
        "success",
        plan.workflow_id,
    )
    kinds = [e.kind for e in trace.events]
    assert kinds.count("tool_call") == 4 and kinds.count("model_call") == 5
    first_model = next(e for e in trace.events if isinstance(e, ModelCall))
    assert first_model.tool_calls_requested[0].name == "create_ticket"
    assert first_model.cost_usd == 0.001


def test_non_live_severity_deopts_before_the_write(plan: WorkflowPlan) -> None:
    tools = FakeTools()
    result = run(plan, tools=tools)  # default: only S0 runs live
    assert result.status == "deopt"
    assert result.deopt.step_id == "s2" and "S2" in result.deopt.reason
    assert [name for name, _ in tools.calls] == ["lookup_customer"]
    assert result.completed == ["s0", "s1"]
    assert isinstance(result.trace.events[-1], Deopt)
    assert result.trace.status == "pending"


def test_invalid_structured_output_is_retried_once(plan: WorkflowPlan) -> None:
    llm = FakeLlm({"s1": [{"summary": 3}]})
    result = run(plan, llm=llm, live_severities=ALL)
    assert result.status == "success"
    s1_calls = [c for c in llm.calls if c[0] == "s1"]
    assert len(s1_calls) == 2 and s1_calls[1][2] is not None and "summary" in s1_calls[1][2]


def test_invalid_twice_deopts(plan: WorkflowPlan) -> None:
    llm = FakeLlm({"s1": [{"summary": 3}, {"wrong": "x"}]})
    result = run(plan, llm=llm, live_severities=ALL)
    assert (result.status, result.deopt.step_id) == ("deopt", "s1")
    assert "invalid structured output" in result.deopt.reason
    assert len([c for c in llm.calls if c[0] == "s1"]) == 2


def test_choosing_another_tool_deopts(plan: WorkflowPlan) -> None:
    llm = FakeLlm({"s3": [{"tool": "escalate", "arguments": {"ticket_id": "T-00001"}}]})
    result = run(plan, llm=llm, live_severities=ALL)
    assert (result.status, result.deopt.step_id) == ("deopt", "s3")
    assert "escalate" in result.deopt.reason
    assert result.completed == ["s0", "s1", "s2"]


def test_tool_error_deopts_and_is_traced(plan: WorkflowPlan) -> None:
    result = run(plan, tools=FakeTools(fail="lookup_customer"))
    assert (result.status, result.deopt.step_id) == ("deopt", "s0")
    assert "upstream 503" in result.deopt.reason
    failed = next(e for e in result.trace.events if isinstance(e, ToolCall))
    assert failed.error == "RuntimeError: upstream 503"


def test_guard_failure_deopts_before_any_step(plan: WorkflowPlan) -> None:
    tools = FakeTools()
    executor = Executor(plan, tools=tools, llm=FakeLlm(), clock=clock)
    result = executor.run({"email": 42, "message": "x"}, run_id="x2")
    assert result.deopt is not None
    assert (result.status, result.deopt.step_id, result.deopt.guard_id) == (
        "deopt",
        "guards",
        "schema:input.email",
    )
    assert tools.calls == [] and result.completed == []


def test_dry_run_renders_without_calling_anything(plan: WorkflowPlan) -> None:
    tools, llm = FakeTools(), FakeLlm()
    result = Executor(plan, tools=tools, llm=llm, dry_run=True, clock=clock).run(INPUT, run_id="d")
    assert tools.calls == [] and llm.calls == []
    assert result.status == "success"
    assert result.rendered["s0"] == {"email": "<EMAIL_1>", "include": "tier"}
    assert result.rendered["s2"] == {
        "customer_id": "<steps.s0.result.customer_id>",
        "summary": "<steps.s1.result.summary>",
    }


def test_steps_run_in_dependency_order_not_list_order() -> None:
    plan = WorkflowPlan.build(
        workflow_id="wf",
        skeleton_hash="h",
        compiled_from=[],
        steps=[
            ToolStep(
                id="b", name="second", args_template={"x": "{{steps.a.result.v}}"}, severity="S0"
            ),
            ToolStep(id="a", name="first", args_template={}, severity="S0"),
            EndStep(output_template="{{steps.b.result.v}}"),
        ],
        guards=[Guard(id="g", kind="schema", path="input.k", params={"type": "string"})],
    )
    order: list[str] = []

    def tools(step: ToolStep, args: Any) -> Any:
        order.append(step.name)
        return {"v": len(order)}

    result = Executor(plan, tools=tools, llm=FakeLlm(), clock=clock).run({"k": "v"}, run_id="o")
    assert order == ["first", "second"] and result.output == 2
