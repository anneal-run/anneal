import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from anneal.cli import main
from anneal.schema import Deopt, Message, ModelCall, Run, ToolCall, ToolCallRequest

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def make_run() -> Run:
    return Run(
        run_id="r1",
        workflow_id="support_triage",
        started_at=T0,
        ended_at=T0,
        status="success",
        input={"ticket": "refund please"},
        output={"answer": "done"},
        source="langsmith",
        events=[
            ModelCall(
                event_id="e1",
                ts=T0,
                provider="openai",
                model="gpt-4o-mini",
                system_hash="abc",
                messages=[Message(role="system", content="be brief")],
                output_text="",
                tool_calls_requested=[
                    ToolCallRequest(id="call_1", name="lookup", args={"email": "a@b.com"})
                ],
                tokens_in=100,
                tokens_out=20,
                tokens_cached=40,
            ),
            ToolCall(
                event_id="e2",
                parent_id=None,
                ts=T0,
                name="lookup",
                args={"email": "a@b.com"},
                result={"id": 7},
                tool_call_id="call_1",
            ),
            Deopt(
                event_id="e3",
                ts=T0,
                step_id="s2",
                guard_id="g1",
                reason="enum miss",
                resumed_at_event="e2",
            ),
        ],
    )


def test_run_round_trips_through_json() -> None:
    run = make_run()
    assert Run.model_validate_json(run.model_dump_json()) == run


def test_events_are_discriminated_by_kind() -> None:
    restored = Run.model_validate(json.loads(make_run().model_dump_json()))
    assert [type(e) for e in restored.events] == [ModelCall, ToolCall, Deopt]


def test_defaults_mark_a_tier0_schema_v1_run() -> None:
    run = make_run()
    assert run.schema_version == 1
    assert run.tier == 0


def test_unknown_schema_version_is_rejected() -> None:
    data = json.loads(make_run().model_dump_json())
    data["schema_version"] = 2
    with pytest.raises(ValidationError):
        Run.model_validate(data)


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolCall(event_id="e", ts=datetime(2026, 1, 1), name="t", args={})


def test_unknown_severity_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolCall(event_id="e", ts=T0, name="t", args={}, severity="S3")  # type: ignore[arg-type]


def test_schema_dump_prints_run_json_schema(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "dump"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "Run"
    assert {"ModelCall", "ToolCall", "Deopt"} <= set(schema["$defs"])
