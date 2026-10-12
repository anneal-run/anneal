"""Synthetic support-workflow traces with planted call classes.

Every model call gets a ground-truth class, and the analyzer must recover all of
them exactly. The main flow per run:

| step | model call | planted class | why |
| --- | --- | --- | --- |
| 1 | requests `lookup_customer(email, include)` | removable | email from input, constant include |
| 2 | requests `create_ticket(customer_id, summary)` | constrained | trap: model-written |
| 3 | requests `auto_reply` (~60%) or `escalate` (~40%) | judgment | tool choice varies |
| 4 | writes a draft reply (text only) | judgment | its text flows into a later argument |
| 5 | requests `send_email(to, body=<draft>)` | constrained | body comes from model text |
| 6 | final answer | terminal | produces the run output |

Some runs request `add_note` before the final answer (judgment, rare branch). A
separate `faq` flow with too few runs to classify is judgment by low support.
"""

import random
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from anneal.schema import Event, ModelCall, Run, ToolCall, ToolCallRequest

CallClass = Literal["removable", "constrained", "judgment", "terminal"]
WORKFLOW = "synth_support"
T0 = datetime(2026, 9, 1, tzinfo=UTC)

COST = {
    "lookup": 0.010,
    "ticket": 0.020,
    "route": 0.015,
    "draft": 0.030,
    "send": 0.005,
    "note": 0.004,
    "final": 0.008,
    "faq": 0.012,
}
_MOODS = ["Frustrated", "Calm", "Confused", "Polite", "Impatient"]
_ISSUES = ["late delivery", "damaged parcel", "wrong size", "missing invoice", "double charge"]
_PHRASES = ["we are on it", "thanks for waiting", "sorry about this", "we will follow up"]


class _RunBuilder:
    def __init__(self, run_id: str, start: datetime) -> None:
        self.run_id = run_id
        self.start = start
        self.events: list[Event] = []
        self.truth: dict[str, CallClass] = {}

    def _id(self) -> str:
        return f"{self.run_id}-e{len(self.events)}"

    def _ts(self) -> datetime:
        return self.start + timedelta(seconds=len(self.events))

    def model(
        self,
        cls: CallClass,
        cost_key: str,
        scope: str = "support",
        text: str = "",
        requests: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> list[str]:
        event_id = self._id()
        call_ids = [f"{event_id}-c{i}" for i in range(len(requests or []))]
        self.events.append(
            ModelCall(
                event_id=event_id,
                ts=self._ts(),
                scope=scope,
                provider="openai",
                model="gpt-4o-mini",
                output_text=text,
                tool_calls_requested=[
                    ToolCallRequest(id=cid, name=name, args=args)
                    for cid, (name, args) in zip(call_ids, requests or [], strict=True)
                ],
                tokens_in=1000,
                tokens_out=50,
                tokens_cached=0,
                cost_usd=COST[cost_key],
            )
        )
        self.truth[event_id] = cls
        return call_ids

    def tool(self, call_id: str, name: str, args: dict[str, Any], result: Any) -> None:
        self.events.append(
            ToolCall(
                event_id=self._id(),
                ts=self._ts(),
                name=name,
                args=args,
                result=result,
                tool_call_id=call_id,
            )
        )

    def call(
        self, cls: CallClass, cost_key: str, name: str, args: dict[str, Any], result: Any
    ) -> None:
        (call_id,) = self.model(cls, cost_key, requests=[(name, args)])
        self.tool(call_id, name, args, result)


def _support_run(i: int, rng: random.Random) -> tuple[Run, dict[str, CallClass]]:
    run_id = f"run-{i:04d}"
    b = _RunBuilder(run_id, T0 + timedelta(hours=i))
    email = f"user{i}@example.com"
    run_input = {"email": email, "message": f"My order {1000 + i} has a problem"}
    customer_id, ticket_id = f"C-{i:04d}", f"T-{i:05d}"

    b.call(
        "removable",
        "lookup",
        "lookup_customer",
        {"email": email, "include": "tier"},
        {"customer_id": customer_id, "tier": rng.choice(["gold", "silver", "bronze"])},
    )
    summary = f"{rng.choice(_MOODS)} customer reports {rng.choice(_ISSUES)}"
    b.call(
        "constrained",
        "ticket",
        "create_ticket",
        {"customer_id": customer_id, "summary": summary},
        {"ticket_id": ticket_id},
    )
    route = "escalate" if rng.random() < 0.4 else "auto_reply"
    b.call("judgment", "route", route, {"ticket_id": ticket_id}, {"ok": True})
    draft = f"Hello, about ticket {ticket_id}: {rng.choice(_PHRASES)}."
    b.model("judgment", "draft", text=draft)
    b.call("constrained", "send", "send_email", {"to": email, "body": draft}, {"sent": True})
    if i % 25 == 7:
        note = f"note {rng.random():.6f}"
        b.call("judgment", "note", "add_note", {"note": note}, {"ok": True})
    final = f"Done: ticket {ticket_id} handled."
    b.model("terminal", "final", text=final)
    run = Run(
        run_id=run_id,
        workflow_id=WORKFLOW,
        started_at=b.start,
        ended_at=b._ts(),
        status="success",
        input=run_input,
        output={"answer": final},
        events=b.events,
        source="synth",
    )
    return run, b.truth


def _faq_run(i: int) -> tuple[Run, dict[str, CallClass]]:
    run_id = f"faq-{i:04d}"
    b = _RunBuilder(run_id, T0 + timedelta(hours=i, minutes=30))
    question = f"How do I change my password? ({i})"
    (cid,) = b.model("judgment", "faq", scope="faq", requests=[("search_kb", {"q": question})])
    b.tool(cid, "search_kb", {"q": question}, {"article": "KB-7"})
    b.model("terminal", "final", scope="faq", text="See KB-7.")
    run = Run(
        run_id=run_id,
        workflow_id=WORKFLOW,
        started_at=b.start,
        status="success",
        input={"email": f"faq{i}@example.com", "message": question},
        output={"answer": "See KB-7."},
        events=b.events,
        source="synth",
    )
    return run, b.truth


def generate(
    n_runs: int = 60, n_faq: int = 3, seed: int = 0
) -> tuple[list[Run], dict[str, CallClass]]:
    """Runs sorted by start time, and the planted class of every model call by event id."""
    rng = random.Random(seed)
    runs: list[Run] = []
    truth: dict[str, CallClass] = {}
    for i in range(n_runs):
        run, t = _support_run(i, rng)
        runs.append(run)
        truth |= t
    for i in range(n_faq):
        run, t = _faq_run(i)
        runs.append(run)
        truth |= t
    return sorted(runs, key=lambda r: r.started_at), truth
