import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from anneal.importers.langsmith import import_records, load_runs
from anneal.schema import ModelCall, Run, ToolCall, ToolCallRequest
from anneal.schema.redact import redact_run
from anneal.schema.store import Store

FIXTURE = Path(__file__).parents[1] / "fixtures" / "traces" / "langsmith" / "support_triage.jsonl"


@pytest.fixture(scope="module")
def runs() -> list[Run]:
    return load_runs(FIXTURE)


def model_calls(run: Run) -> list[ModelCall]:
    return [e for e in run.events if isinstance(e, ModelCall)]


def tool_calls(run: Run) -> list[ToolCall]:
    return [e for e in run.events if isinstance(e, ToolCall)]


def test_one_run_per_trace_sorted_by_start(runs: list[Run]) -> None:
    assert len(runs) == 3
    assert [r.started_at for r in runs] == sorted(r.started_at for r in runs)
    assert {r.workflow_id for r in runs} == {"support_triage"}
    assert {(r.source, r.tier) for r in runs} == {("langsmith", 0)}
    assert all(r.started_at.tzinfo is not None for r in runs)


def test_handoff_trace_events_in_order_with_agent_scope(runs: list[Run]) -> None:
    handoff = runs[0]
    assert [(e.kind, getattr(e, "name", None), e.scope) for e in handoff.events] == [
        ("model_call", None, "triage_agent"),
        ("tool_call", "lookup_customer", "triage_agent"),
        ("model_call", None, "triage_agent"),
        ("tool_call", "transfer_to_billing", "triage_agent"),
        ("model_call", None, "billing_agent"),
        ("tool_call", "issue_refund", "billing_agent"),
        ("model_call", None, "billing_agent"),
    ]
    assert all(e.parent_id is None for e in handoff.events)  # chains are not events
    assert handoff.status == "success"
    assert handoff.output == {"answer": "Refund issued for order 1234."}


def test_langchain_model_call_fields(runs: list[Run]) -> None:
    first, second, *_ = model_calls(runs[0])
    assert (first.provider, first.model) == ("anthropic", "claude-sonnet-5-5")
    assert (first.tokens_in, first.tokens_out, first.tokens_cached) == (1200, 40, 1000)
    assert first.cost_usd is None
    assert [m.role for m in first.messages] == ["system", "user"]
    assert first.output_text == ""
    assert first.tool_calls_requested == [
        ToolCallRequest(id="toolu_1", name="lookup_customer", args={"email": "jane@acme.com"})
    ]
    assert [m.role for m in second.messages] == ["system", "user", "assistant", "tool"]
    assert second.messages[2].tool_calls[0].id == "toolu_1"
    assert second.messages[3].tool_call_id == "toolu_1"


def test_system_hash_groups_calls_by_system_prompt(runs: list[Run]) -> None:
    triage1, triage2, billing1, billing2 = model_calls(runs[0])
    assert triage1.system_hash is not None
    assert triage1.system_hash == triage2.system_hash
    assert billing1.system_hash == billing2.system_hash != triage1.system_hash
    assert model_calls(runs[2])[0].system_hash == triage1.system_hash  # same prompt, other run


def test_tool_results_are_unwrapped(runs: list[Run]) -> None:
    lookup, transfer, refund = tool_calls(runs[0])
    assert lookup.args == {"email": "jane@acme.com"}
    assert lookup.result == {"customer_id": "C-42", "tier": "gold"}  # serialized ToolMessage
    assert lookup.tool_call_id == "toolu_1"
    assert transfer.result == "Transferred to billing_agent"  # plain string
    assert refund.result == {"refund_id": "R-9"}  # ToolMessage repr string
    assert refund.tool_call_id == "toolu_3"
    assert (lookup.side_effect, lookup.severity) == (None, None)  # declared at scoping, not import


def test_openai_wrapper_model_call_fields(runs: list[Run]) -> None:
    first = model_calls(runs[1])[0]
    assert (first.provider, first.model) == ("openai", "gpt-4o-mini")
    assert (first.tokens_in, first.tokens_out, first.tokens_cached) == (300, 25, 128)
    assert first.cost_usd == pytest.approx(0.00012)  # source cost kept, given as a string
    assert first.tool_calls_requested == [
        ToolCallRequest(id="call_1", name="search_kb", args={"query": "reset password"})
    ]
    assert [m.role for m in first.messages] == ["system", "user"]


def test_nested_model_call_points_at_its_tool(runs: list[Run]) -> None:
    nested = runs[1]
    assert [(e.kind, getattr(e, "name", None)) for e in nested.events] == [
        ("model_call", None),
        ("tool_call", "search_kb"),
        ("model_call", None),  # inside search_kb
        ("model_call", None),
    ]
    first, tool, inner, last = nested.events
    assert inner.parent_id == tool.event_id
    assert first.parent_id is None and last.parent_id is None
    assert isinstance(last, ModelCall)
    assert last.output_text == "Go to Settings > Security > Reset password."


def test_tool_error_and_failed_run(runs: list[Run]) -> None:
    failed = runs[2]
    assert failed.status == "error"
    (tool,) = tool_calls(failed)
    assert tool.error == "ToolException: order 99 not found"
    assert tool.result is None


def record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "trace_id": "00000000-0000-0000-0000-000000000001",
        "parent_run_id": None,
        "dotted_order": "20261012T090000000000Z00000000-0000-0000-0000-000000000001",
        "name": "wf",
        "run_type": "chain",
        "start_time": "2026-10-12T09:00:00",
        "end_time": "2026-10-12T09:00:01",
        "inputs": {"q": 1},
        "outputs": {"a": 2},
        "error": None,
        "extra": {},
    }
    return base | overrides


def child(**overrides: Any) -> dict[str, Any]:
    return record(
        id="00000000-0000-0000-0000-000000000002",
        parent_run_id="00000000-0000-0000-0000-000000000001",
        dotted_order=(
            "20261012T090000000000Z00000000-0000-0000-0000-000000000001."
            "20261012T090000100000Z00000000-0000-0000-0000-000000000002"
        ),
        start_time="2026-10-12T09:00:00.1",
        **overrides,
    )


def test_naive_timestamps_are_read_as_utc() -> None:
    (run,) = import_records([record()])
    assert run.started_at == datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def test_invalid_tool_arguments_are_kept_raw() -> None:
    llm = child(
        run_type="llm",
        inputs={"messages": [{"role": "user", "content": "hi"}]},
        outputs={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {"id": "c", "function": {"name": "t", "arguments": "{not json"}}
                        ],
                    }
                }
            ]
        },
    )
    (run,) = import_records([record(), llm])
    (call,) = model_calls(run)
    assert call.tool_calls_requested == [ToolCallRequest(id="c", name="t", args="{not json")]


def test_workflow_id_override_and_missing_root() -> None:
    (run,) = import_records([record()], workflow_id="other")
    assert run.workflow_id == "other"
    with pytest.raises(ValueError, match="no root run"):
        import_records([child()])


def test_import_store_round_trip_is_redacted(tmp_path: Path, runs: list[Run]) -> None:
    store = Store(tmp_path)
    store.write(runs)
    assert store.read("support_triage") == [redact_run(r) for r in runs]
    on_disk = "".join(p.read_text() for p in tmp_path.rglob("*.jsonl"))
    assert "jane@acme.com" not in on_disk
    assert "415 555 0132" not in on_disk
    assert "<EMAIL_1>" in on_disk


def test_fixture_lines_are_unordered_like_a_real_export() -> None:
    lines = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    starts = [line["start_time"] for line in lines]
    assert starts != sorted(starts)


def test_content_blocks_raw_usage_and_prompts() -> None:
    llm = child(
        run_type="llm",
        inputs={"prompts": ["Say hi"]},
        outputs={
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Hi"}, {"type": "image"}, "!"],
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 2,
                "prompt_tokens_details": {"cached_tokens": 10},
            },
        },
    )
    (run,) = import_records([record(), llm])
    (call,) = model_calls(run)
    assert [(m.role, m.content) for m in call.messages] == [("user", "Say hi")]
    assert call.output_text == "Hi!"
    assert (call.model, call.tokens_in, call.tokens_out, call.tokens_cached) == (
        "gpt-4o",
        50,
        2,
        10,
    )


def test_usage_from_message_metadata_and_model_from_invocation_params() -> None:
    message = {
        "lc": 1,
        "type": "constructor",
        "id": ["langchain", "schema", "messages", "AIMessage"],
        "kwargs": {
            "content": "ok",
            "usage_metadata": {"input_tokens": 7, "output_tokens": 1},
            "response_metadata": {"model_name": "ignored-when-params-present"},
        },
    }
    llm = child(
        run_type="llm",
        inputs={"messages": [[{"type": "human", "content": "q"}]]},
        outputs={"generations": [[{"text": "ok", "message": message}]]},
        extra={"invocation_params": {"model": "claude-haiku-5-5"}},
    )
    (run,) = import_records([record(), llm])
    (call,) = model_calls(run)
    assert (call.model, call.tokens_in, call.tokens_out) == ("claude-haiku-5-5", 7, 1)
    assert call.messages[0].role == "user"


def test_unknown_message_role_is_an_error() -> None:
    llm = child(run_type="llm", inputs={"messages": [{"role": "narrator", "content": "x"}]})
    with pytest.raises(ValueError, match="unknown message role"):
        import_records([record(), llm])


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"status": None, "error": "boom"}, "error"),
        ({"status": None, "end_time": None}, "pending"),
        ({"status": None}, "success"),
        ({"status": "pending"}, "pending"),
    ],
)
def test_run_status_falls_back_to_error_and_end_time(fields: dict[str, Any], status: str) -> None:
    (run,) = import_records([record(**fields)])
    assert run.status == status


def test_retriever_runs_are_tool_calls_and_bad_json_results_stay_text() -> None:
    retriever = child(
        run_type="retriever", name="docs", inputs={"query": "q"}, outputs={"output": "{oops"}
    )
    (run,) = import_records([record(), retriever])
    (tool,) = tool_calls(run)
    assert (tool.name, tool.result) == ("docs", "{oops")
