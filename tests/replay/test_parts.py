from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from anneal.compile.plan import ToolStep
from anneal.replay.critical import critical_fields, equivalent
from anneal.replay.recording import Divergence, RecordedToolError, RecordingToolServer
from anneal.replay.split import chronological_split
from anneal.schema import Event, Run, ToolCall

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def run(run_id: str, minutes: int, events: list[Event] | None = None) -> Run:
    return Run(
        run_id=run_id,
        workflow_id="wf",
        started_at=T0 + timedelta(minutes=minutes),
        status="success",
        events=events or [],
        source="t",
    )


# Chronological split


def test_split_is_by_start_time_and_never_overlaps() -> None:
    runs = [run(f"r{i}", minutes=(i * 7) % 10) for i in range(10)]
    compile_runs, holdout = chronological_split(runs, 0.7)
    assert len(compile_runs) == 7 and len(holdout) == 3
    assert max(r.started_at for r in compile_runs) <= min(r.started_at for r in holdout)
    assert not {r.run_id for r in compile_runs} & {r.run_id for r in holdout}


def test_split_breaks_start_time_ties_by_run_id() -> None:
    runs = [run("b", 0), run("a", 0), run("c", 0)]
    compile_runs, holdout = chronological_split(runs, 0.67)
    assert [r.run_id for r in compile_runs] == ["a", "b"] and [r.run_id for r in holdout] == ["c"]


@pytest.mark.parametrize("share", [0.0, 1.0, 1.5])
def test_split_share_must_leave_both_sides(share: float) -> None:
    with pytest.raises(ValueError):
        chronological_split([run("a", 0), run("b", 1)], share)


# Recording-backed tool server


def tool(
    name: str, args: Any, result: Any = None, error: str | None = None, n: int = 0
) -> ToolCall:
    return ToolCall(event_id=f"t{n}", ts=T0, name=name, args=args, result=result, error=error)


def step(name: str, step_id: str = "s0") -> ToolStep:
    return ToolStep(id=step_id, name=name, args_template={})


def test_matching_calls_are_served_in_recorded_order() -> None:
    server = RecordingToolServer(
        run("r", 0, [tool("get", {"id": 1}, "first", n=0), tool("get", {"id": 1}, "second", n=1)])
    )
    assert server(step("get"), {"id": 1}) == "first"
    assert server(step("get"), {"id": 1.0}) == "second"  # 1.0 is canonically 1


def test_argument_key_order_does_not_matter() -> None:
    server = RecordingToolServer(run("r", 0, [tool("get", {"a": 1, "b": {"y": 2, "x": 1}}, "ok")]))
    assert server(step("get"), {"b": {"x": 1, "y": 2}, "a": 1}) == "ok"


def test_mismatch_is_a_divergence_at_that_step() -> None:
    server = RecordingToolServer(run("r", 0, [tool("send", {"to": "<EMAIL_1>"}, "ok")]))
    with pytest.raises(Divergence):
        server(step("send", "s4"), {"to": "<EMAIL_2>"})
    assert server.divergence is not None
    assert server.divergence.step_id == "s4"
    assert server.divergence.recorded == [{"to": "<EMAIL_1>"}]


def test_recorded_tool_errors_are_raised_again() -> None:
    server = RecordingToolServer(run("r", 0, [tool("get", {"id": 1}, error="NotFound: 1")]))
    with pytest.raises(RecordedToolError, match="NotFound"):
        server(step("get"), {"id": 1})
    assert server.divergence is None


# Critical fields


def test_critical_fields_by_category() -> None:
    text = (
        "Refund $1,234.50 for order ORD-12345 to jane@acme.com by 2026-10-12, do not ship <CARD_1>"
    )
    fields = critical_fields(text)
    assert fields["amounts"] == {"1234.5"}
    assert fields["ids"] == {"ORD-12345", "<CARD_1>"}
    assert fields["recipients"] == {"jane@acme.com"}
    assert fields["dates"] == {"2026-10-12"}
    assert fields["negations"] == {"not"}


def test_critical_fields_are_normalized() -> None:
    a = critical_fields("total 1234.50 due Oct 12, 2026 to <EMAIL_1>")
    b = critical_fields("total $1,234.5 due 2026-10-12 to <EMAIL_1>")
    assert a == b


def test_equivalence_is_exact_on_critical_fields() -> None:
    assert equivalent(
        {"answer": "Refund 12.50 for ORD-1"}, {"answer": "We refunded 12.50 on ORD-1"}
    )
    assert not equivalent({"answer": "Refund 12.50"}, {"answer": "Refund 12.05"})
    assert not equivalent("we will ship", "we will not ship")
    assert not equivalent({"to": "<EMAIL_1>"}, {"to": "<EMAIL_2>"})


def test_free_text_without_critical_fields_uses_similarity() -> None:
    assert equivalent("Thanks for waiting, we are on it.", "Thanks for waiting, we are on it!")
    assert not equivalent("Thanks for waiting.", "Your account has been closed.")


def test_structure_and_non_text_leaves_must_match_exactly() -> None:
    assert equivalent({"a": 1, "b": [True]}, {"a": 1, "b": [True]})
    assert not equivalent({"a": 1}, {"a": 2})
    assert not equivalent({"a": 1}, {"a": 1, "b": 2})


# Recorded LLM answers


def recorded_llm_case(requests: list[tuple[str, dict[str, Any]]], text: str = "") -> Any:
    from anneal.classify.classifier import position_id, run_view
    from anneal.replay.recording import RecordedLlm
    from anneal.schema import ModelCall, ToolCallRequest

    call = ModelCall(
        event_id="m",
        ts=T0,
        scope="a",
        output_text=text,
        tool_calls_requested=[
            ToolCallRequest(id=f"c{i}", name=n, args=a) for i, (n, a) in enumerate(requests)
        ],
        cost_usd=0.5,
    )
    recorded = run("r", 0, [call])
    pid = position_id(run_view(recorded).steps[:0], "a")
    return RecordedLlm(recorded), pid


def llm_step(pid: str | None, **kw: Any) -> Any:
    from anneal.compile.plan import LlmStep

    schema = kw.pop("schema", {"type": "object", "properties": {"text": {"type": "string"}}})
    return LlmStep(
        id="s1",
        role="a",
        system_template="",
        user_template="",
        output_schema=schema,
        position_id=pid,
        **kw,
    )


def test_recorded_llm_answers_each_kind_of_step() -> None:
    llm, pid = recorded_llm_case([("pay", {"amount": 3, "ref": "R"})])
    forced = llm_step(
        pid, forced_tool="pay", schema={"type": "object", "properties": {"amount": {}}}
    )
    response = llm(forced, "", "", None)
    assert response.output == {"amount": 3} and response.cost_usd == 0.5
    choice = llm_step(pid, expected_tool="pay")
    assert llm(choice, "", "", None).output == {
        "tool": "pay",
        "arguments": {"amount": 3, "ref": "R"},
    }
    text_llm, text_pid = recorded_llm_case([], text="hi")
    assert text_llm(llm_step(text_pid), "", "", None).output == {"text": "hi"}


@pytest.mark.parametrize(
    ("requests", "kw", "reason"),
    [
        ([("other", {})], {"forced_tool": "pay"}, "did not call pay"),
        ([], {"expected_tool": "pay"}, "called no tool"),
        ([("pay", {})], {}, "expects text"),
    ],
)
def test_recorded_llm_deopts_when_the_recorded_model_did_something_else(
    requests: list[tuple[str, dict[str, Any]]], kw: dict[str, Any], reason: str
) -> None:
    from anneal.runtime.executor import DeoptRequested

    llm, pid = recorded_llm_case(requests)
    with pytest.raises(DeoptRequested, match=reason):
        llm(llm_step(pid, **kw), "", "", None)
    with pytest.raises(DeoptRequested, match="no model call at this position"):
        llm(llm_step("elsewhere", **kw), "", "", None)
