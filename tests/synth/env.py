"""A simulated support environment for three-arm comparisons (ANNEAL-ROADMAP.md M1.8).

Everything here is deterministic and synthetic. Numbers produced with it test the
protocol, not the product.

- `Env`: the tools, with every call recorded as an effect.
- `SimModel`: stands in for an LLM. It reads inputs flexibly (finds the email in
  any field, understands priority words it has not seen) and makes deterministic
  decisions. Every arm that needs a model uses it through `ModelCapabilities`, so
  the arms differ in structure, not in model quality. Each call costs the same.
- `expected_effects`: the task definition, the ground truth of "the job done".
- `Tier0Agent`: the original agent, deciding each step from its message history,
  so it can also resume from a reconstructed history.
- Drift transforms for the holdout: `new_enum`, `renamed_field`, `new_topic`.
"""

import json
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from anneal.schema import Event, Message, ModelCall, Run, ToolCall, ToolCallRequest

WORKFLOW = "env_support"
MODEL_CALL_USD = 0.015
T0 = datetime(2026, 8, 1, tzinfo=UTC)

ISSUES = ["late delivery", "damaged parcel", "wrong size", "missing invoice", "double charge"]
PRIORITIES = ["low", "normal", "high"]
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


class ToolError(Exception):
    pass


@dataclass
class Env:
    customers: dict[str, tuple[str, str]]
    effects: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def call(self, name: str, args: dict[str, Any]) -> Any:
        self.effects.append((name, dict(args)))
        match name:
            case "lookup_customer":
                if args.get("email") not in self.customers:
                    raise ToolError(f"NotFound: {args.get('email')}")
                cid, tier = self.customers[args["email"]]
                return {"customer_id": cid, "tier": tier}
            case "create_ticket":
                return {"ticket_id": "T-" + str(args["customer_id"]).removeprefix("C-")}
            case "auto_reply" | "escalate":
                return {"ok": True}
            case "cancel_subscription":
                return {"cancelled": True}
            case "send_email":
                return {"sent": True}
        raise ToolError(f"unknown tool {name}")


def make_customers(n: int) -> dict[str, tuple[str, str]]:
    rng = random.Random(11)
    return {
        f"user{i}@example.com": (f"C-{i:04d}", rng.choice(["gold", "silver", "bronze"]))
        for i in range(n)
    }


class SimModel:
    """Deterministic stand-in for an LLM's reading and judgment."""

    @staticmethod
    def find_email(run_input: dict[str, Any]) -> str | None:
        for value in run_input.values():
            if isinstance(value, str) and _EMAIL.fullmatch(value.strip()):
                return value.strip()
        return None

    @staticmethod
    def message(run_input: dict[str, Any]) -> str:
        return str(run_input.get("message", ""))

    @staticmethod
    def topic(message: str) -> str:
        text = message.lower()
        return "cancel" if "cancel" in text and "subscription" in text else "order"

    @staticmethod
    def summarize(message: str) -> str:
        issue = next((i for i in ISSUES if i in message.lower()), "a problem")
        return f"Customer reports {issue}"

    @staticmethod
    def urgent(priority: Any) -> bool:
        return str(priority).lower() in {"high", "urgent", "critical", "asap"}

    def route(self, priority: Any, tier: str) -> str:
        return "escalate" if self.urgent(priority) or tier == "gold" else "auto_reply"

    @staticmethod
    def draft(ticket_id: str | None, topic: str) -> str:
        if topic == "cancel":
            return "Your subscription has been cancelled."
        return f"Hello, about ticket {ticket_id}: we are on it."

    @staticmethod
    def final(ticket_id: str | None, topic: str) -> str:
        return (
            "Done: subscription cancelled."
            if topic == "cancel"
            else f"Done: ticket {ticket_id} handled."
        )


def expected_effects(
    run_input: dict[str, Any], customers: dict[str, tuple[str, str]]
) -> list[tuple[str, dict[str, Any]]]:
    """The task definition: which side effects mean the job was done."""
    model = SimModel()
    email = model.find_email(run_input)
    if email is None or email not in customers:
        return []
    cid, tier = customers[email]
    if model.topic(model.message(run_input)) == "cancel":
        return [("cancel_subscription", {"customer_id": cid}), ("send_email", {"to": email})]
    route = model.route(run_input.get("priority"), tier)
    return [
        ("create_ticket", {"customer_id": cid}),
        (route, {"ticket_id": "T-" + cid.removeprefix("C-")}),
        ("send_email", {"to": email}),
    ]


def task_done(
    run_input: dict[str, Any],
    effects: list[tuple[str, dict[str, Any]]],
    customers: dict[str, tuple[str, str]],
) -> bool:
    """Every expected write happened once with the critical arguments, and no other write."""
    writes = [(n, a) for n, a in effects if n != "lookup_customer"]
    expected = expected_effects(run_input, customers)
    if len(writes) != len(expected):
        return False
    return all(
        name == want_name and all(args.get(k) == v for k, v in want_args.items())
        for (name, args), (want_name, want_args) in zip(writes, expected, strict=True)
    )


@dataclass
class ModelCapabilities:
    """What an arm may ask a model, each counted as one model call."""

    model: SimModel = field(default_factory=SimModel)
    calls: int = 0

    def _count(self) -> None:
        self.calls += 1

    def summarize(self, message: str) -> str:
        self._count()
        return self.model.summarize(message)

    def choose(self, options: list[str], context: dict[str, Any]) -> str:
        """Pick one of `options` for the context, as a model would: a classification
        question gets the label that fits the message's topic; a routing question gets
        the routing decision."""
        self._count()
        topic = self.model.topic(str(context.get("message", "")))
        lowered = {o: o.lower() for o in options}
        if topic == "cancel":
            for o, low in lowered.items():
                if "cancel" in low:
                    return o
            for o, low in lowered.items():
                if any(w in low for w in ("not_", "not ", "other", "unknown", "none")):
                    return o
        if topic == "order":
            for o, low in lowered.items():
                if "order" in low and not any(w in low for w in ("not_", "not ")):
                    return o
        choice = self.model.route(context.get("priority"), str(context.get("tier", "")))
        return choice if choice in options else options[0]

    def write(self, purpose: str, context: dict[str, Any]) -> str:
        """Write text for `purpose` ('reply' or 'final') from the context."""
        self._count()
        topic = self.model.topic(str(context.get("message", "")))
        ticket = context.get("ticket_id")
        return (
            self.model.final(ticket, topic)
            if purpose == "final"
            else self.model.draft(ticket, topic)
        )

    def read(self, run_input: dict[str, Any]) -> dict[str, Any]:
        """Extract email, message and priority from an input whatever its field names."""
        self._count()
        return {
            "email": self.model.find_email(run_input),
            "message": self.model.message(run_input),
            "priority": run_input.get("priority"),
        }


class Tier0Agent:
    """The original agent: one model call per step, deciding from the message history."""

    def __init__(self, env: Env) -> None:
        self.env = env
        self.model = SimModel()

    def decide(self, history: list[Message], run_input: dict[str, Any]) -> Message:
        names = {tc.id: tc.name for m in history if m.role == "assistant" for tc in m.tool_calls}
        results: dict[str, Any] = {}
        for m in history:
            if m.role == "tool":
                name = names.get(m.tool_call_id or "", m.name or "")
                results[name] = json.loads(m.content) if isinstance(m.content, str) else m.content
        drafts = [
            m.content for m in history if m.role == "assistant" and m.content and not m.tool_calls
        ]
        email = self.model.find_email(run_input)
        message = self.model.message(run_input)
        topic = self.model.topic(message)
        n = len(history)

        def call(name: str, args: dict[str, Any]) -> Message:
            return Message(
                role="assistant",
                content="",
                tool_calls=[ToolCallRequest(id=f"t0-{n}", name=name, args=args)],
            )

        if "lookup_customer" not in results:
            return call("lookup_customer", {"email": email, "include": "tier"})
        lookup = results["lookup_customer"]
        if topic == "cancel":
            if "cancel_subscription" not in results:
                return call("cancel_subscription", {"customer_id": lookup["customer_id"]})
            ticket = None
        else:
            if "create_ticket" not in results:
                return call(
                    "create_ticket",
                    {
                        "customer_id": lookup["customer_id"],
                        "summary": self.model.summarize(message),
                    },
                )
            ticket = results["create_ticket"]["ticket_id"]
            if not {"auto_reply", "escalate"} & results.keys():
                route = self.model.route(run_input.get("priority"), lookup["tier"])
                return call(route, {"ticket_id": ticket})
        if not drafts and "send_email" not in results:
            return Message(role="assistant", content=self.model.draft(ticket, topic))
        if "send_email" not in results:
            return call("send_email", {"to": email, "body": drafts[-1]})
        return Message(role="assistant", content=self.model.final(ticket, topic))

    def run(
        self,
        run_input: dict[str, Any],
        history: list[Message] | None = None,
        run_id: str = "t0",
        start: datetime = T0,
    ) -> tuple[str, list[Event], list[Message]]:
        """Run to the final answer; returns the answer, trace events and the full history."""
        history = list(
            history or [Message(role="user", content=json.dumps(run_input, sort_keys=True))]
        )
        events: list[Event] = []
        clock = [start]

        def ts() -> datetime:
            clock[0] += timedelta(seconds=1)
            return clock[0]

        for _ in range(20):
            step = self.decide(history, run_input)
            history.append(step)
            events.append(
                ModelCall(
                    event_id=f"{run_id}-e{len(events)}",
                    ts=ts(),
                    scope="support",
                    provider="sim",
                    model="sim-model",
                    output_text=step.content or "",
                    tool_calls_requested=step.tool_calls,
                    tokens_in=1000,
                    tokens_out=50,
                    cost_usd=MODEL_CALL_USD,
                )
            )
            if not step.tool_calls:
                if str(step.content).startswith("Done:"):
                    return str(step.content), events, history
                continue
            (request,) = step.tool_calls
            assert isinstance(request.args, dict)
            try:
                result: Any = self.env.call(request.name, request.args)
                error = None
            except ToolError as e:
                result, error = {"error": str(e)}, str(e)
            events.append(
                ToolCall(
                    event_id=f"{run_id}-e{len(events)}",
                    ts=ts(),
                    name=request.name,
                    args=request.args,
                    result=None if error else result,
                    error=error,
                    tool_call_id=request.id,
                )
            )
            history.append(
                Message(
                    role="tool",
                    content=json.dumps(result),
                    tool_call_id=request.id,
                    name=request.name,
                )
            )
            if error:
                return f"Failed: {error}", events, history
        raise RuntimeError("agent did not finish")


def make_inputs(n: int, seed: int = 0) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return [
        {
            "email": f"user{i}@example.com",
            "message": f"My order {1000 + i} has a problem: {rng.choice(ISSUES)}",
            "priority": rng.choices(PRIORITIES, weights=[3, 5, 2])[0],
        }
        for i in range(n)
    ]


def generate_traces(n: int = 80, seed: int = 0) -> tuple[list[Run], dict[str, tuple[str, str]]]:
    """Tier 0 runs in the environment, as recorded traces, and the customer table."""
    customers = make_customers(n)
    runs = []
    for i, run_input in enumerate(make_inputs(n, seed)):
        env = Env(customers)
        start = T0 + timedelta(hours=i)
        answer, events, _ = Tier0Agent(env).run(run_input, run_id=f"run-{i:04d}", start=start)
        runs.append(
            Run(
                run_id=f"run-{i:04d}",
                workflow_id=WORKFLOW,
                started_at=start,
                ended_at=events[-1].ts,
                status="success",
                input=run_input,
                output={"answer": answer},
                events=events,
                source="sim",
            )
        )
    return runs, customers


def new_enum(run_input: dict[str, Any]) -> dict[str, Any]:
    return {**run_input, "priority": "urgent"}


def renamed_field(run_input: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in run_input.items() if k != "email"}
    return {"email_address": run_input["email"], **out}


def new_topic(run_input: dict[str, Any]) -> dict[str, Any]:
    return {**run_input, "message": "Please cancel my subscription, I no longer need it."}


DRIFTS = {"new_enum": new_enum, "renamed_field": renamed_field, "new_topic": new_topic}
