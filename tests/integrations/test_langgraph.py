import json
import re
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from support_agent import ToolBox, build_agent, customer_of, ticket_of
from synth.generator import generate

from anneal.compile.compiler import ToolSpec, compile_plan
from anneal.compile.plan import LlmStep, ToolStep, WorkflowPlan
from anneal.integrations.langgraph import langgraph_fallback, to_langchain
from anneal.replay.split import chronological_split
from anneal.runtime.executor import DeoptRequested, LlmResponse
from anneal.runtime.fallback import CompiledWorkflow
from anneal.schema import Message, Run, Severity, ToolCallRequest

ALL: frozenset[Severity] = frozenset({"S0", "S1", "S2"})
TOOLS = {
    "lookup_customer": ToolSpec(side_effect=False, severity="S0", idempotent=True),
    "create_ticket": ToolSpec(severity="S1", idempotent=True),
    "auto_reply": ToolSpec(severity="S1"),
    "escalate": ToolSpec(severity="S1"),
    "send_email": ToolSpec(severity="S2"),
}


@pytest.fixture(scope="module")
def data() -> tuple[WorkflowPlan, list[Run]]:
    runs, _ = generate(seed=0)
    compile_runs, holdout = chronological_split(runs, 0.7)
    plan = compile_plan(compile_runs, tools=TOOLS).plan
    assert plan is not None
    return plan, holdout


def test_history_converts_to_langchain_messages() -> None:
    history = [
        Message(role="system", content="be brief"),
        Message(role="user", content="hi"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCallRequest(id="c1", name="t", args={"a": 1})],
        ),
        Message(role="tool", content='{"ok": true}', tool_call_id="c1", name="t"),
        Message(role="assistant", content="draft"),
    ]
    converted = to_langchain(history)
    assert [type(m) for m in converted] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
    ]
    assert isinstance(converted[2], AIMessage) and isinstance(converted[3], ToolMessage)
    assert converted[2].tool_calls == [
        {"name": "t", "args": {"a": 1}, "id": "c1", "type": "tool_call"}
    ]
    assert (converted[3].tool_call_id, converted[3].content) == ("c1", '{"ok": true}')


def compiled_llm(step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
    """Answers like a model reading the prompt: ids come from the run input it shows."""
    run_input = json.loads(user.split("Run input:\n", 1)[1].split("\n\n", 1)[0])
    ticket = ticket_of(customer_of(run_input["email"]))
    if step.forced_tool == "create_ticket":
        return LlmResponse({"summary": "Customer reports a problem"})
    if step.forced_tool == "send_email":
        drafts = re.findall(r'"text": "([^"]*)"', user)
        return LlmResponse({"body": drafts[-1] if drafts else f"Hello, about ticket {ticket}."})
    if step.expected_tool:
        return LlmResponse({"tool": step.expected_tool, "arguments": {"ticket_id": ticket}})
    final = step.id == "s8"
    return LlmResponse(
        {"text": f"Done: ticket {ticket} handled." if final else f"Hello, about ticket {ticket}."}
    )


def injected(plan: WorkflowPlan, toolbox: ToolBox, at: str) -> CompiledWorkflow:
    def tools(step: ToolStep, args: Any) -> Any:
        if step.id == at:
            raise DeoptRequested(at, "injected")
        return toolbox.call(step.name, args)

    def llm(step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
        if step.id == at:
            raise DeoptRequested(at, "injected")
        return compiled_llm(step, system, user, feedback)

    def fallback(history: list[Message], run_input: Any) -> Any:
        toolbox.phase = "agent"
        return langgraph_fallback(build_agent(toolbox))(history, run_input)

    return CompiledWorkflow(plan, tools=tools, llm=llm, fallback=fallback, live_severities=ALL)


def task_done(toolbox: ToolBox, run_input: dict[str, Any]) -> bool:
    calls = {name: args for _, name, args in toolbox.calls}
    customer = customer_of(run_input["email"])
    return (
        calls.get("lookup_customer", {}).get("email") == run_input["email"]
        and calls.get("create_ticket", {}).get("customer_id") == customer
        and bool({"auto_reply", "escalate"} & calls.keys())
        and calls.get("send_email", {}).get("to") == run_input["email"]
    )


def test_twenty_injected_deopts_resume_and_finish_without_repeating(
    data: tuple[WorkflowPlan, list[Run]],
) -> None:
    plan, holdout = data
    step_ids = [s.id for s in plan.steps if s.id != "end"]
    cases = [(holdout[i % len(holdout)], step_ids[i % len(step_ids)]) for i in range(20)]
    assert len({at for _, at in cases}) == len(step_ids)  # every step gets a deopt
    for run, at in cases:
        toolbox = ToolBox()
        outcome = injected(plan, toolbox, at).run(run.input, run_id=f"inj-{run.run_id}-{at}")
        assert outcome.tier == 0 and outcome.execution.deopt is not None
        assert outcome.execution.deopt.step_id == at
        assert task_done(toolbox, run.input), (at, toolbox.calls)
        compiled = {
            (n, json.dumps(a, sort_keys=True)) for p, n, a in toolbox.calls if p == "compiled"
        }
        agent = [(n, json.dumps(a, sort_keys=True)) for p, n, a in toolbox.calls if p == "agent"]
        assert not compiled & set(agent), (at, agent)  # no completed step is repeated
        assert not {n for n, _ in compiled} & {n for n, _ in agent}, (at, agent)
        assert outcome.output.startswith("Done: ticket")


def test_deopt_after_a_side_effect_keeps_it_in_the_history(
    data: tuple[WorkflowPlan, list[Run]],
) -> None:
    plan, holdout = data
    toolbox = ToolBox()
    outcome = injected(plan, toolbox, "s3").run(holdout[0].input, run_id="side")
    assert outcome.history is not None
    called = [m.tool_calls[0].name for m in outcome.history if m.tool_calls]
    assert called == ["lookup_customer", "create_ticket"]
    assert [n for p, n, _ in toolbox.calls if p == "agent"].count("create_ticket") == 0


def test_a_summary_instead_of_history_makes_the_agent_repeat_work(
    data: tuple[WorkflowPlan, list[Run]],
) -> None:
    """Negative control: the no-repeat check above is meaningful."""
    _, holdout = data
    toolbox = ToolBox()
    run_input = holdout[0].input
    summary = [
        Message(role="user", content=json.dumps(run_input)),
        Message(role="assistant", content="I looked up the customer and created the ticket."),
    ]
    toolbox.phase = "agent"
    langgraph_fallback(build_agent(toolbox))(summary, run_input)
    assert [n for _, n, _ in toolbox.calls][:2] == ["lookup_customer", "create_ticket"]
