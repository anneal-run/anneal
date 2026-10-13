"""Tests for the env_support baseline workflow, using in-memory fakes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"env_support_{name}", HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wf = _load("workflow")
iface = _load("interface")
ToolError = iface.ToolError

WRITE_TOOLS = {"create_ticket", "auto_reply", "escalate", "send_email"}


class FakeTools:
    def __init__(self, customers: dict[str, dict] | None = None, fail: dict[str, Any] | None = None,
                 results: dict[str, Any] | None = None):
        self.customers = customers if customers is not None else {
            "user0@example.com": {"customer_id": "C-0000", "tier": "silver"}
        }
        self.fail = fail or {}
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []
        self._n = 0

    def call(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((name, dict(args)))
        if name in self.fail:
            raise self.fail[name]
        if name in self.results:
            return self.results[name]
        if name == "lookup_customer":
            if args.get("email") not in self.customers:
                raise ToolError(f"NotFound: {args.get('email')}")
            return dict(self.customers[args["email"]])
        if name == "create_ticket":
            tid = f"T-{self._n:04d}"
            self._n += 1
            return {"ticket_id": tid}
        if name in ("auto_reply", "escalate"):
            return {"ok": True}
        if name == "send_email":
            return {"sent": True}
        raise AssertionError(f"workflow called an unknown tool: {name}")

    @property
    def writes(self) -> list[tuple[str, dict]]:
        return [c for c in self.calls if c[0] in WRITE_TOOLS]


class FakeModel:
    """Counts calls; scripted answers for the drift paths."""

    def __init__(self, read: dict | None = None, choose: str = "order_problem", summary: str = "Customer issue"):
        self._read, self._choose, self._summary = read, choose, summary
        self.calls: list[str] = []

    def read(self, run_input):
        self.calls.append("read")
        if self._read is None:
            raise AssertionError("unexpected model.read")
        return self._read

    def summarize(self, message):
        self.calls.append("summarize")
        return self._summary

    def choose(self, options, context):
        self.calls.append("choose")
        assert self._choose in options or self._choose == "bogus"
        return self._choose

    def write(self, purpose, context):
        self.calls.append("write")
        raise AssertionError("workflow should not need model.write")


def _input(priority="normal", message="My order 1000 has a problem: missing invoice", email="user0@example.com"):
    return {"email": email, "message": message, "priority": priority}


# ------------------------------------------------------------------ usual case


def test_usual_case_exact_writes_and_no_model_calls():
    tools, model = FakeTools(), FakeModel()
    out = wf.run(_input(), tools, model)

    assert out == {"answer": "Done: ticket T-0000 handled."}
    assert tools.calls == [
        ("lookup_customer", {"email": "user0@example.com", "include": "tier"}),
        ("create_ticket", {"customer_id": "C-0000", "summary": "Customer reports missing invoice"}),
        ("auto_reply", {"ticket_id": "T-0000"}),
        ("send_email", {"to": "user0@example.com", "body": "Hello, about ticket T-0000: we are on it."}),
    ]
    assert model.calls == []


def test_replays_all_recorded_traces_exactly():
    runs = [json.loads(line) for line in (HERE / "traces.jsonl").read_text().splitlines() if line.strip()]
    assert len(runs) == 56
    for r in runs:
        recorded = [(e["name"], e["args"]) for e in r["events"] if e["kind"] == "tool_call"]
        lookup = next(e for e in r["events"] if e["kind"] == "tool_call" and e["name"] == "lookup_customer")
        tid = next(e["result"]["ticket_id"] for e in r["events"]
                   if e["kind"] == "tool_call" and e["name"] == "create_ticket")
        tools = FakeTools(customers={r["input"]["email"]: lookup["result"]},
                          results={"create_ticket": {"ticket_id": tid}})
        model = FakeModel()
        out = wf.run(r["input"], tools, model)
        assert tools.calls == recorded, r["run_id"]
        assert out == r["output"], r["run_id"]
        assert model.calls == [], r["run_id"]


# --------------------------------------------------------------------- routing


@pytest.mark.parametrize(
    "priority,tier,route",
    [
        ("low", "bronze", "auto_reply"),
        ("normal", "bronze", "auto_reply"),
        ("low", "silver", "auto_reply"),
        ("normal", "silver", "auto_reply"),
        ("high", "bronze", "escalate"),
        ("high", "silver", "escalate"),
        ("low", "gold", "escalate"),
        ("normal", "gold", "escalate"),
        ("high", "gold", "escalate"),
    ],
)
def test_routing_rule(priority, tier, route):
    tools = FakeTools(customers={"user0@example.com": {"customer_id": "C-1", "tier": tier}})
    wf.run(_input(priority=priority), tools, FakeModel())
    routes = [n for n, _ in tools.calls if n in ("auto_reply", "escalate")]
    assert routes == [route]


def test_priority_and_tier_are_case_insensitive():
    tools = FakeTools(customers={"user0@example.com": {"customer_id": "C-1", "tier": "Gold"}})
    wf.run(_input(priority=" Normal "), tools, FakeModel())
    assert [n for n, _ in tools.writes] == ["create_ticket", "escalate", "send_email"]


# ------------------------------------------------------------ drift: no writes


@pytest.mark.parametrize("priority", ["urgent", "", None, "critical", 3])
def test_unknown_priority_raises_before_any_tool_call(priority):
    tools = FakeTools()
    with pytest.raises(wf.WorkflowError):
        wf.run(_input(priority=priority), tools, FakeModel())
    assert tools.calls == []


def test_unknown_tier_raises_without_writes():
    tools = FakeTools(customers={"user0@example.com": {"customer_id": "C-1", "tier": "platinum"}})
    with pytest.raises(wf.WorkflowError, match="tier"):
        wf.run(_input(), tools, FakeModel())
    assert tools.writes == []


def test_unknown_customer_raises_without_writes():
    tools = FakeTools(customers={})
    with pytest.raises(wf.WorkflowError, match="NotFound"):
        wf.run(_input(), tools, FakeModel())
    assert tools.writes == []


@pytest.mark.parametrize("email", ["", "not-an-email", None])
def test_invalid_email_raises(email):
    tools = FakeTools()
    with pytest.raises(wf.WorkflowError):
        wf.run(_input(email=email), tools, FakeModel())
    assert tools.calls == []


def test_non_dict_input_raises():
    with pytest.raises(wf.WorkflowError):
        wf.run("hello", FakeTools(), FakeModel())


def test_non_order_message_is_refused_without_writes():
    tools, model = FakeTools(), FakeModel(choose="not_order_problem")
    with pytest.raises(wf.NotOrderProblem):
        wf.run(_input(message="How do I reset my password?"), tools, model)
    assert tools.calls == []
    assert model.calls == ["choose"]


def test_classifier_returning_garbage_is_treated_as_not_order():
    tools = FakeTools()
    with pytest.raises(wf.NotOrderProblem):
        wf.run(_input(message="Can I change my billing address?"), tools, FakeModel(choose="bogus"))
    assert tools.calls == []


def test_differently_phrased_order_problem_uses_model_for_summary():
    tools, model = FakeTools(), FakeModel(choose="order_problem", summary="Parcel never arrived")
    out = wf.run(_input(message="Where is my parcel? It never arrived."), tools, model)
    assert out == {"answer": "Done: ticket T-0000 handled."}
    assert tools.writes[0] == ("create_ticket", {"customer_id": "C-0000", "summary": "Parcel never arrived"})
    assert [n for n, _ in tools.writes] == ["create_ticket", "auto_reply", "send_email"]
    assert model.calls == ["choose", "summarize"]


def test_renamed_input_fields_use_model_read_and_are_validated():
    raw = {"from": "user0@example.com", "body": "My order 7 has a problem: wrong size", "urgency": "high"}
    model = FakeModel(read={"email": "user0@example.com", "message": raw["body"], "priority": "high"})
    tools = FakeTools()
    wf.run(raw, tools, model)
    assert model.calls == ["read"]
    assert [n for n, _ in tools.writes] == ["create_ticket", "escalate", "send_email"]


def test_model_read_with_bad_output_raises():
    model = FakeModel(read={"email": "user0@example.com", "message": "x", "priority": "asap"})
    tools = FakeTools()
    with pytest.raises(wf.WorkflowError):
        wf.run({"sender": "user0@example.com", "text": "x"}, tools, model)
    assert tools.calls == []


# ------------------------------------------------- failures mid-way: no retries


def test_routing_failure_stops_and_does_not_retry_or_email():
    tools = FakeTools(fail={"auto_reply": ToolError("boom")})
    with pytest.raises(wf.WorkflowError, match="auto_reply"):
        wf.run(_input(), tools, FakeModel())
    assert [n for n, _ in tools.writes] == ["create_ticket", "auto_reply"]


def test_malformed_ticket_result_raises_before_routing():
    tools = FakeTools(results={"create_ticket": {"id": "T-1"}})
    with pytest.raises(wf.WorkflowError, match="create_ticket"):
        wf.run(_input(), tools, FakeModel())
    assert [n for n, _ in tools.writes] == ["create_ticket"]


def test_email_not_sent_raises():
    tools = FakeTools(results={"send_email": {"sent": False}})
    with pytest.raises(wf.WorkflowError, match="send_email"):
        wf.run(_input(), tools, FakeModel())
    assert [n for n, _ in tools.writes] == ["create_ticket", "auto_reply", "send_email"]
