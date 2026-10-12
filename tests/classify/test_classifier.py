from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from synth.generator import generate

from anneal.classify import Classification, classify
from anneal.importers.langsmith import load_runs
from anneal.schema import Event, ModelCall, Run, ToolCall, ToolCallRequest
from anneal.schema.redact import redact_run

FIXTURE = Path(__file__).parents[1] / "fixtures" / "traces" / "langsmith" / "support_triage.jsonl"
T0 = datetime(2026, 10, 1, tzinfo=UTC)


def by_event(result: Classification) -> dict[str, str]:
    return {c.event_id: c.call_class for c in result.calls}


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_planted_classes_are_recovered_exactly(seed: int) -> None:
    runs, truth = generate(seed=seed)
    assert by_event(classify(runs)) == truth


def test_planted_classes_survive_redaction() -> None:
    runs, truth = generate(seed=3)
    assert by_event(classify([redact_run(r) for r in runs])) == truth


def reasons(result: Classification) -> dict[str, str]:
    return {c.event_id: c.reason for c in result.calls}


def test_reasons_explain_each_planted_class() -> None:
    runs, _ = generate(seed=0)
    result = reasons(classify(runs))
    first = runs[0].run_id
    assert result[f"{first}-e0"] == "args_bound"  # lookup: input + constant
    assert result[f"{first}-e2"] == "args_model_generated"  # create_ticket: the trap
    assert result[f"{first}-e4"] == "choice_varies"  # auto_reply vs escalate
    assert result[f"{first}-e6"] == "text_flows_into_args"  # the draft
    assert result[f"{first}-e7"] == "args_model_generated"  # send_email body from model text
    assert result[f"{first}-e9"] == "terminal"
    faq = next(r for r in runs if r.run_id.startswith("faq"))
    assert result[f"{faq.run_id}-e0"] == "low_support"


def test_positions_summarize_choice_share_and_bindings() -> None:
    runs, _ = generate(seed=0)
    positions = {(p.depth, p.role): p for p in classify(runs).positions if p.runs >= 60}
    lookup = positions[(0, "support")]
    assert (lookup.call_class, lookup.dominant, lookup.dominant_share) == (
        "removable",
        "calls:lookup_customer",
        1.0,
    )
    assert lookup.bindings == {
        "lookup_customer:$.email": "input $.email (exact)",
        "lookup_customer:$.include": "constant 'tier'",
    }
    route = positions[(4, "support")]
    assert route.call_class == "judgment" and 0.5 < route.dominant_share < 0.95


# Small hand-built workflows for the edges of the rules


def flow(run_id: str, i: int, tool: str, args: dict[str, Any], extra_input: dict[str, Any]) -> Run:
    events: list[Event] = [
        ModelCall(
            event_id=f"{run_id}-m",
            ts=T0,
            scope="a",
            tool_calls_requested=[ToolCallRequest(id="c", name=tool, args=args)],
        ),
        ToolCall(
            event_id=f"{run_id}-t", ts=T0, name=tool, args=args, result={"ok": i}, tool_call_id="c"
        ),
        ModelCall(event_id=f"{run_id}-f", ts=T0, scope="a", output_text="done"),
    ]
    return Run(
        run_id=run_id,
        workflow_id="wf",
        started_at=T0 + timedelta(minutes=i),
        status="success",
        input={"id": f"ID-{i:05d}", **extra_input},
        events=events,
        source="t",
    )


@pytest.mark.parametrize(("others", "expected"), [(2, "removable"), (3, "judgment")])
def test_tool_choice_must_be_stable_in_95_percent(others: int, expected: str) -> None:
    runs = [
        flow(f"r{i}", i, "other" if i < others else "get", {"id": f"ID-{i:05d}"}, {})
        for i in range(50)
    ]
    result = classify(runs)
    assert by_event(result)["r49-m"] == expected  # 48/50 = 96% vs 47/50 = 94%


def test_inconsistent_bindings_are_constrained() -> None:
    runs = [
        flow(f"r{i}", i, "get", {"key": f"K-{i:05d}"}, {"a" if i % 2 else "b": f"K-{i:05d}"})
        for i in range(20)
    ]
    assert reasons(classify(runs))["r0-m"] == "args_inconsistent"


def test_low_support_positions_are_judgment() -> None:
    runs = [flow(f"r{i}", i, "get", {"id": f"ID-{i:05d}"}, {}) for i in range(4)]
    assert by_event(classify(runs))["r0-m"] == "judgment"
    assert by_event(classify(runs, min_support=4))["r0-m"] == "removable"


def test_fixture_runs_are_too_few_to_compile() -> None:
    runs = load_runs(FIXTURE)
    classes = by_event(classify(runs))
    finals = [
        [e for e in r.events if isinstance(e, ModelCall) and e.parent_id is None][-1]
        for r in runs[:2]
    ]
    assert {classes[f.event_id] for f in finals} == {"terminal"}
    assert set(classes.values()) <= {"judgment", "terminal"}


def test_position_reports_the_class_most_of_its_calls_received() -> None:
    runs, _ = generate(seed=0)
    result = classify(runs)
    for p in result.positions:
        members = [c for c in result.calls if c.position_id == p.position_id]
        top = max({c.call_class for c in members}, key=[c.call_class for c in members].count)
        assert p.call_class == top, p
        assert p.spend_usd == pytest.approx(
            sum(c.cost_usd or 0.0 for c in members if c.call_class == top)
        )
