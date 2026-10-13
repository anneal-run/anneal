from typing import Any

import pytest

from anneal.compile.plan import EndStep, ToolStep, WorkflowPlan
from anneal.runtime.executor import Executor, LlmResponse
from anneal.runtime.fallback import CompiledWorkflow, call_id, operation_key_for
from anneal.runtime.outbox import NeedsHuman, Outbox
from anneal.schema import Message, Severity

ALL: frozenset[Severity] = frozenset({"S0", "S1", "S2"})
INPUT = {"to": "<EMAIL_1>"}


def plan(*extra: ToolStep, **declaration: Any) -> WorkflowPlan:
    send = ToolStep(
        id="s0", name="send", args_template={"to": "{{input.to}}"}, severity="S1", **declaration
    )
    return WorkflowPlan.build(
        workflow_id="wf",
        skeleton_hash="h",
        compiled_from=[],
        steps=[send, *extra, EndStep(output_template="{{steps.s0.result}}")],
    )


class Tool:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, Any, str | None]] = []
        self.fail = fail

    def __call__(self, step: ToolStep, args: Any, key: str | None) -> Any:
        self.calls.append((step.name, args, key))
        if self.fail:
            raise TimeoutError("gateway timeout")
        return {"sent": True}


def no_llm(step: Any, system: str, user: str, feedback: str | None) -> LlmResponse:
    raise AssertionError("no llm steps here")


def execute(p: WorkflowPlan, tool: Tool, **kw: Any) -> Any:
    return Executor(p, tools=tool, llm=no_llm, live_severities=ALL, **kw).run(INPUT, run_id="r1")


def test_a_side_effect_with_neither_key_nor_hook_is_shadow_only() -> None:
    tool, outbox = Tool(), Outbox()
    p = plan()
    assert p.shadow_only_steps() == ["s0"]
    result = execute(p, tool, outbox=outbox)
    assert result.deopt is not None and "shadow_only" in result.deopt.reason
    assert tool.calls == [] and outbox.records() == []


def test_an_idempotent_tool_gets_the_operation_key_and_an_outbox_record() -> None:
    tool, outbox = Tool(), Outbox()
    result = execute(plan(idempotent=True), tool, outbox=outbox)
    key = call_id("r1", "s0")
    assert result.status == "success" and tool.calls == [("send", INPUT, key)]
    assert result.operation_keys == {"s0": key}
    record = outbox.get(key)
    assert record is not None and (record.state, record.args, record.tool) == (
        "done",
        INPUT,
        "send",
    )


def test_read_only_tools_get_no_key_and_no_record() -> None:
    tool, outbox = Tool(), Outbox()
    result = execute(plan(side_effect=False), tool, outbox=outbox)
    assert result.status == "success" and tool.calls == [("send", INPUT, None)]
    assert outbox.records() == [] and result.operation_keys == {}


@pytest.mark.parametrize(
    ("answer", "status", "state"),
    [("not_done", "deopt", "not_done"), ("done", "success", "done")],
)
def test_a_failed_call_is_reconciled(answer: str, status: str, state: str) -> None:
    tool, outbox = Tool(fail=True), Outbox()
    result = execute(
        plan(reconcile=True), tool, outbox=outbox, reconcilers={"send": lambda key: answer}
    )
    assert result.status == status and len(tool.calls) == 1
    assert outbox.get(call_id("r1", "s0")).state == state  # type: ignore[union-attr]
    if answer == "done":
        assert result.output == {"reconciled": "done"}


def test_unknown_after_reconciliation_stops_for_a_human_without_retrying() -> None:
    tool, outbox = Tool(fail=True), Outbox()
    with pytest.raises(NeedsHuman) as excinfo:
        execute(
            plan(reconcile=True), tool, outbox=outbox, reconcilers={"send": lambda key: "unknown"}
        )
    assert len(tool.calls) == 1
    assert [r.state for r in excinfo.value.records] == ["unknown"]
    assert outbox.get(call_id("r1", "s0")).state == "unknown"  # type: ignore[union-attr]


def test_a_failed_idempotent_call_deopts_and_the_agent_reuses_its_key() -> None:
    tool, outbox = Tool(fail=True), Outbox()
    seen: list[str | None] = []

    def agent(history: list[Message], run_input: Any) -> Any:
        seen.append(operation_key_for("send", {"to": "<EMAIL_1>"}))
        seen.append(operation_key_for("send", {"to": "<EMAIL_2>"}))
        return "done by agent"

    workflow = CompiledWorkflow(
        plan(idempotent=True),
        tools=tool,
        llm=no_llm,
        fallback=agent,
        live_severities=ALL,
        outbox=outbox,
    )
    outcome = workflow.run(INPUT, run_id="r1")
    assert outcome.tier == 0 and outcome.output == "done by agent"
    assert seen == [call_id("r1", "s0"), None]
    assert operation_key_for("send", INPUT) is None  # only while the fallback runs
    assert outbox.get(call_id("r1", "s0")).state == "unknown"  # type: ignore[union-attr]


def test_completed_side_effects_appear_in_history_under_their_key() -> None:
    other = ToolStep(id="s1", name="other", args_template={}, severity="S1")  # shadow_only
    outbox = Outbox()
    workflow = CompiledWorkflow(
        plan(other, idempotent=True),
        tools=Tool(),
        llm=no_llm,
        fallback=lambda history, run_input: history,
        live_severities=ALL,
        outbox=outbox,
    )
    history = workflow.run(INPUT, run_id="r1").output
    (record,) = outbox.records()
    assert history[1].tool_calls[0].id == record.key
    assert history[2].tool_call_id == record.key


def test_a_declared_hook_must_be_registered() -> None:
    with pytest.raises(ValueError, match="reconcile hook"):
        Executor(plan(reconcile=True), tools=Tool(), llm=no_llm)


def test_replay_can_turn_the_policy_off() -> None:
    tool = Tool()
    result = execute(plan(), tool, enforce_side_effects=False)
    assert result.status == "success" and tool.calls == [("send", INPUT, None)]
