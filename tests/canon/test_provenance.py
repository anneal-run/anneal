from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from anneal.canon.provenance import Edge, LeafProvenance, provenance
from anneal.importers.langsmith import load_runs
from anneal.schema import Event, ModelCall, Run, ToolCall, ToolCallRequest
from anneal.schema.redact import redact_run

T0 = datetime(2026, 10, 12, tzinfo=UTC)
FIXTURE = Path(__file__).parents[1] / "fixtures" / "traces" / "langsmith" / "support_triage.jsonl"


class Builder:
    """Builds a run where each tool call is requested by the model call before it."""

    def __init__(self, input: Any) -> None:
        self.input = input
        self.events: list[Event] = []

    def _ts(self) -> datetime:
        return T0 + timedelta(seconds=len(self.events))

    def model(self, text: str = "", requests: list[tuple[str, dict[str, Any]]] = ()) -> "Builder":  # type: ignore[assignment]
        n = len(self.events)
        self.events.append(
            ModelCall(
                event_id=f"m{n}",
                ts=self._ts(),
                output_text=text,
                tool_calls_requested=[
                    ToolCallRequest(id=f"c{n}-{i}", name=name, args=args)
                    for i, (name, args) in enumerate(requests)
                ],
            )
        )
        return self

    def tool(
        self, name: str, args: dict[str, Any], result: Any = None, requested: bool = True
    ) -> "Builder":
        call_id = None
        if requested:
            self.model(requests=[(name, args)])
            call_id = f"c{len(self.events) - 1}-0"
        self.events.append(
            ToolCall(
                event_id=f"t{len(self.events)}",
                ts=self._ts(),
                name=name,
                args=args,
                result=result,
                tool_call_id=call_id,
            )
        )
        return self

    def run(self) -> Run:
        return Run(
            run_id="r",
            workflow_id="wf",
            started_at=T0,
            status="success",
            input=self.input,
            events=self.events,
            source="test",
        )


def leaf(run: Run, path: str, tool: str | None = None) -> LeafProvenance:
    found = [
        p
        for p in provenance(run)
        if p.path == path and (tool is None or _tool_name(run, p.event_id) == tool)
    ]
    assert len(found) == 1, found
    return found[0]


def _tool_name(run: Run, event_id: str) -> str:
    return next(e.name for e in run.events if isinstance(e, ToolCall) and e.event_id == event_id)


def test_exact_match_from_run_input() -> None:
    run = Builder({"ticket": {"email": "<EMAIL_1>"}}).tool("lookup", {"email": "<EMAIL_1>"}).run()
    p = leaf(run, "$.email")
    assert p.status == "bound" and not p.ambiguous
    assert p.edges == [
        Edge(
            from_event="input",
            from_kind="input",
            from_path="$.ticket.email",
            to_event=p.event_id,
            to_path="$.email",
            transform="exact",
        )
    ]


def test_exact_match_from_earlier_tool_result() -> None:
    run = (
        Builder({"q": "hi"})
        .tool("lookup", {"email": "x"}, result={"customer": {"id": "C-42"}})
        .tool("refund", {"customer_id": "C-42"})
        .run()
    )
    (edge,) = leaf(run, "$.customer_id", tool="refund").edges
    assert (edge.from_kind, edge.from_path, edge.transform) == ("tool", "$.customer.id", "exact")


def test_most_recent_source_wins_and_ambiguity_is_flagged() -> None:
    run = (
        Builder({"id": "C-42"})
        .tool("a", {"x": "zzzzzzzz"}, result={"id": "C-42"})
        .tool("b", {"id": "C-42"})
        .run()
    )
    p = leaf(run, "$.id", tool="b")
    assert p.ambiguous
    assert p.edges[0].from_kind == "tool"


def test_same_key_name_breaks_ties_within_an_event() -> None:
    run = Builder({"owner": "C-42", "customer_id": "C-42"}).tool("t", {"customer_id": "C-42"}).run()
    assert leaf(run, "$.customer_id").edges[0].from_path == "$.customer_id"


def test_normalized_matches_name_the_template_transform() -> None:
    run = (
        Builder({"a": "  Jane ", "b": "SUPPORT", "c": "Hello   World"})
        .tool("t", {"x": "jane", "y": "support", "z": "hello  World "})
        .run()
    )
    assert leaf(run, "$.x").edges[0].transform == "trim|lower"
    assert leaf(run, "$.y").edges[0].transform == "lower"
    assert leaf(run, "$.z").edges[0].transform == "normalize"


def test_substring_of_six_or_more() -> None:
    run = (
        Builder({"text": "Your order ORD-123456 shipped, ref AB1"})
        .tool("t", {"order": "ORD-123456", "ref": "AB1"})
        .run()
    )
    assert leaf(run, "$.order").edges[0].transform == "substring"
    assert leaf(run, "$.ref").status == "model_generated"  # too short to trust


def test_number_and_date_reformats() -> None:
    run = (
        Builder({"amount": "1,234.50", "when": "Oct 12, 2026", "qty": 3})
        .tool("t", {"amount": 1234.5, "date": "2026-10-12", "qty": "3"})
        .run()
    )
    assert leaf(run, "$.amount").edges[0].transform == "number"
    assert leaf(run, "$.date").edges[0].transform == "date"
    assert leaf(run, "$.qty").edges[0].transform == "number"


def test_json_path_into_an_embedded_json_string() -> None:
    run = Builder({"payload": '{"order": {"id": "A-77"}}'}).tool("t", {"id": "A-77"}).run()
    (edge,) = leaf(run, "$.id").edges
    assert (edge.from_path, edge.transform, edge.detail) == ("$.payload", "json", "$.order.id")


def test_concatenation_of_up_to_three_leaves() -> None:
    run = (
        Builder({"first": "Jane", "last": "Doe", "city": "Paris", "zip": "75001"})
        .tool("t", {"name": "Jane Doe", "where": "Paris-75001-Jane"})
        .run()
    )
    name = leaf(run, "$.name")
    assert [(e.from_path, e.transform, e.part, e.parts, e.detail) for e in name.edges] == [
        ("$.first", "concat", 0, 2, " "),
        ("$.last", "concat", 1, 2, " "),
    ]
    assert [e.from_path for e in leaf(run, "$.where").edges] == ["$.city", "$.zip", "$.first"]


def test_model_text_is_a_source_and_marked_as_model() -> None:
    letter = "Dear customer, your refund is on its way."
    run = Builder({"q": "x"}).model(text=letter).tool("send", {"body": letter}).run()
    (edge,) = leaf(run, "$.body").edges
    assert edge.from_kind == "model"


def test_requested_tool_calls_are_not_their_own_source() -> None:
    run = Builder({"q": "refund please"}).tool("t", {"note": "customer is upset"}).run()
    p = leaf(run, "$.note")
    assert (p.status, p.edges) == ("model_generated", [])


def test_unrequested_tool_call_without_match_is_external() -> None:
    run = Builder({"q": "x"}).tool("t", {"token": "abc123xyz"}, requested=False).run()
    assert leaf(run, "$.token").status == "external"


def test_booleans_and_nulls_are_never_matched() -> None:
    run = Builder({"vip": True, "note": None}).tool("t", {"urgent": True, "n": None}).run()
    assert leaf(run, "$.urgent").status == "model_generated"
    assert leaf(run, "$.n").status == "model_generated"


def test_only_earlier_events_are_sources() -> None:
    run = (
        Builder({"q": "x"})
        .tool("first", {"id": "LATER-001"})
        .tool("second", {"q": "y"}, result={"id": "LATER-001"})
        .run()
    )
    assert leaf(run, "$.id", tool="first").status == "model_generated"


def test_fixture_handoff_run_after_redaction() -> None:
    run = redact_run(load_runs(FIXTURE)[0])
    by_tool = {(_tool_name(run, p.event_id), p.path): p for p in provenance(run)}
    email = by_tool[("lookup_customer", "$.email")]
    assert (email.status, email.edges[0].transform) == ("bound", "substring")
    customer = by_tool[("issue_refund", "$.customer_id")]
    assert (customer.edges[0].from_kind, customer.edges[0].from_path) == ("tool", "$.customer_id")
    assert by_tool[("issue_refund", "$.order_id")].status == "model_generated"  # "1234" < 6 chars
    assert by_tool[("transfer_to_billing", "$.reason")].status == "model_generated"


def test_json_looking_text_that_is_not_json_is_skipped() -> None:
    run = Builder({"note": "{not json, id A-77}"}).tool("t", {"id": "A-77", "n": 7}).run()
    assert leaf(run, "$.id").status == "model_generated"
    assert leaf(run, "$.n").status == "model_generated"
