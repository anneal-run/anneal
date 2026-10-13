import json
from typing import Any

import pytest
from synth.generator import generate

from anneal.compile.compiler import ToolSpec, compile_plan
from anneal.compile.plan import LlmStep, ToolStep, WorkflowPlan
from anneal.runtime.executor import DeoptRequested, Executor, LlmResponse
from anneal.runtime.fallback import (
    CompiledWorkflow,
    call_id,
    default_initial_messages,
    reconstruct_history,
)
from anneal.schema import Message, Severity

ALL: frozenset[Severity] = frozenset({"S0", "S1", "S2"})
INPUT = {"email": "<EMAIL_1>", "message": "My order 1001 has a problem"}
TOOLS = {
    "lookup_customer": ToolSpec(side_effect=False, severity="S0", idempotent=True),
    "create_ticket": ToolSpec(severity="S1", idempotent=True),
    "auto_reply": ToolSpec(severity="S1", idempotent=True),
    "send_email": ToolSpec(severity="S2", idempotent=True),
}


@pytest.fixture(scope="module")
def plan() -> WorkflowPlan:
    runs, _ = generate(seed=0)
    result = compile_plan(runs, tools=TOOLS)
    assert result.plan is not None
    return result.plan


def tools(step: ToolStep, args: Any, key: str | None = None) -> Any:
    return {
        "lookup_customer": {"customer_id": "C-0001", "tier": "gold"},
        "create_ticket": {"ticket_id": "T-00001"},
        "auto_reply": {"ok": True},
        "send_email": {"sent": True},
    }[step.name]


def llm(step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
    if step.forced_tool == "create_ticket":
        return LlmResponse({"summary": "Calm customer reports late delivery"})
    if step.forced_tool == "send_email":
        return LlmResponse({"body": "Hello, about ticket T-00001."})
    if step.expected_tool:
        return LlmResponse({"tool": step.expected_tool, "arguments": {"ticket_id": "T-00001"}})
    return LlmResponse({"text": "Hello, about ticket T-00001." if step.id == "s5" else "Done."})


def deopt_at(step_id: str) -> Any:
    def runner(step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
        if step.id == step_id:
            raise DeoptRequested(step_id, "injected")
        return llm(step, system, user, feedback)

    return runner


def execute(plan: WorkflowPlan, runner: Any = llm, live: frozenset[Any] = ALL) -> Any:
    return Executor(plan, tools=tools, llm=runner, live_severities=live).run(INPUT, run_id="r1")


def roles(history: list[Message]) -> list[tuple[str, str | None]]:
    return [
        (m.role, m.tool_calls[0].name if m.tool_calls else m.tool_call_id and "result")
        for m in history
    ]


def test_each_completed_tool_step_is_a_call_and_a_result_in_order(plan: WorkflowPlan) -> None:
    execution = execute(plan, deopt_at("s6"))
    history = reconstruct_history(plan, execution, default_initial_messages(INPUT))
    assert roles(history) == [
        ("user", None),
        ("assistant", "lookup_customer"),
        ("tool", "result"),
        ("assistant", "create_ticket"),
        ("tool", "result"),
        ("assistant", "auto_reply"),
        ("tool", "result"),
        ("assistant", None),  # the completed draft (s5), as text
    ]
    assert history[0].content == json.dumps(INPUT, sort_keys=True)
    lookup_call, lookup_result = history[1], history[2]
    assert lookup_call.tool_calls[0].args == {"email": "<EMAIL_1>", "include": "tier"}
    assert lookup_call.tool_calls[0].id == call_id("r1", "s0") == lookup_result.tool_call_id
    assert json.loads(lookup_result.content) == {"customer_id": "C-0001", "tier": "gold"}
    assert history[3].tool_calls[0].args == {
        "customer_id": "C-0001",
        "summary": "Calm customer reports late delivery",
    }
    assert history[7].content == "Hello, about ticket T-00001."


def test_model_output_for_a_tool_that_never_ran_is_left_out(plan: WorkflowPlan) -> None:
    execution = execute(plan, live=frozenset({"S0"}))  # deopts before create_ticket (S1)
    assert execution.deopt.step_id == "s2"
    history = reconstruct_history(plan, execution, default_initial_messages(INPUT))
    assert roles(history) == [("user", None), ("assistant", "lookup_customer"), ("tool", "result")]


def test_a_side_effect_step_that_ran_is_in_the_history(plan: WorkflowPlan) -> None:
    execution = execute(plan, deopt_at("s3"))
    history = reconstruct_history(plan, execution, default_initial_messages(INPUT))
    names = [m.tool_calls[0].name for m in history if m.tool_calls]
    assert names == ["lookup_customer", "create_ticket"]
    assert json.loads(history[-1].content) == {"ticket_id": "T-00001"}


def test_initial_messages_can_carry_the_agent_system_prompt(plan: WorkflowPlan) -> None:
    initial = [Message(role="system", content="You are support."), *default_initial_messages(INPUT)]
    history = reconstruct_history(plan, execute(plan, deopt_at("s1")), initial)
    assert [m.role for m in history] == ["system", "user", "assistant", "tool"]


def test_string_input_is_the_user_message_as_is() -> None:
    assert default_initial_messages("hi") == [Message(role="user", content="hi")]


def test_compiled_workflow_falls_back_with_the_history(plan: WorkflowPlan) -> None:
    calls: list[tuple[list[Message], Any]] = []

    def agent(history: list[Message], run_input: Any) -> Any:
        calls.append((history, run_input))
        return {"answer": "finished by the agent"}

    workflow = CompiledWorkflow(
        plan, tools=tools, llm=deopt_at("s3"), fallback=agent, live_severities=ALL
    )
    outcome = workflow.run(INPUT, run_id="r1")
    assert (outcome.tier, outcome.output) == (0, {"answer": "finished by the agent"})
    ((history, run_input),) = calls
    assert run_input == INPUT and history == outcome.history
    assert outcome.execution.deopt is not None


def test_compiled_workflow_success_never_calls_the_fallback(plan: WorkflowPlan) -> None:
    def agent(history: list[Message], run_input: Any) -> Any:
        raise AssertionError("fallback called")

    outcome = CompiledWorkflow(plan, tools=tools, llm=llm, fallback=agent, live_severities=ALL).run(
        INPUT
    )
    assert outcome.tier == 1 and outcome.history is None
    assert outcome.output == {"answer": "Done."}


def test_a_fallback_must_be_registered(plan: WorkflowPlan) -> None:
    workflow = CompiledWorkflow(plan, tools=tools, llm=deopt_at("s1"), live_severities=ALL)
    with pytest.raises(RuntimeError, match="no fallback registered"):
        workflow.run(INPUT)
    workflow.register_fallback(lambda history, run_input: "ok")
    assert workflow.run(INPUT).output == "ok"
