"""Baseline workflow for `env_support`: a customer order problem -> ticket, route, reply.

Job done (per BRIEF.md) = exactly these writes, once each, in this order:
    create_ticket -> (escalate | auto_reply) -> send_email
for an order problem. Anything else must not be treated as an order problem.

Design:
- Everything observed in the 56 traces is handled deterministically (0 model calls):
  input shape, routing rule, ticket summary, reply body and closing answer are all
  fixed templates in the traces.
- The model is used only when the input drifts away from what the traces show:
    * input without the expected `email`/`message`/`priority` keys -> `model.read`
    * a message that does not match the known order-problem phrasing
      -> `model.choose` to classify it, and `model.summarize` for the ticket summary.
- All validation and every read happen before the first write. If anything is off
  (unknown customer, unknown tier/priority, non-order message, malformed tool result)
  we raise `WorkflowError` instead of guessing. Writes are never retried, so a
  failure mid-way can never produce duplicate tickets or emails.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # typing only; no runtime dependency on how this file is loaded
    from interface import Model, Tools

__all__ = ["run", "WorkflowError", "NotOrderProblem"]

PRIORITIES = {"low", "normal", "high"}
TIERS = {"bronze", "silver", "gold"}
EXPECTED_KEYS = {"email", "message", "priority"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# The only phrasing seen in the traces: "My order 1003 has a problem: wrong size"
ORDER_PROBLEM_RE = re.compile(
    r"^\s*my order\s+#?\w+\s+has a problem:\s*(?P<problem>.+?)\s*\.?\s*$", re.I
)

ORDER_PROBLEM = "order_problem"
NOT_ORDER_PROBLEM = "not_order_problem"


class WorkflowError(Exception):
    """The run cannot be completed safely; no further writes were made."""


class NotOrderProblem(WorkflowError):
    """The message is not an order problem; this workflow does not handle it."""


# --------------------------------------------------------------------------- input


def _normalize_input(run_input: Any, model: Model) -> tuple[str, str, str]:
    if not isinstance(run_input, dict):
        raise WorkflowError(f"input must be a dict, got {type(run_input).__name__}")

    if EXPECTED_KEYS <= run_input.keys():
        fields = {k: run_input[k] for k in EXPECTED_KEYS}
    else:
        # Field names drifted: let the model map them, then validate strictly.
        fields = model.read(run_input)
        if not isinstance(fields, dict):
            raise WorkflowError("model.read did not return a dict")

    email, message, priority = (fields.get(k) for k in ("email", "message", "priority"))

    if not isinstance(email, str) or not EMAIL_RE.match(email.strip()):
        raise WorkflowError(f"missing or invalid email: {email!r}")
    if not isinstance(message, str) or not message.strip():
        raise WorkflowError("missing or empty message")
    if not isinstance(priority, str) or priority.strip().lower() not in PRIORITIES:
        raise WorkflowError(f"unknown priority {priority!r}; expected one of {sorted(PRIORITIES)}")

    return email.strip(), message.strip(), priority.strip().lower()


# ------------------------------------------------------------------ classification


def _classify_and_summarize(message: str, priority: str, model: Model) -> str:
    """Return the ticket summary, or raise NotOrderProblem."""
    m = ORDER_PROBLEM_RE.match(message)
    if m:
        return f"Customer reports {m.group('problem')}"

    choice = model.choose(
        [ORDER_PROBLEM, NOT_ORDER_PROBLEM],
        {
            "task": "Is this customer message reporting a problem with an order they placed?",
            "message": message,
            "priority": priority,
        },
    )
    if choice != ORDER_PROBLEM:
        raise NotOrderProblem(
            f"message is not an order problem (classified {choice!r}): {message!r}"
        )

    summary = model.summarize(message)
    if not isinstance(summary, str) or not summary.strip():
        raise WorkflowError("model.summarize returned an empty summary")
    return " ".join(summary.split())


# ------------------------------------------------------------------------- tools


def _lookup(tools: Tools, email: str) -> tuple[str, str]:
    try:
        res = tools.call("lookup_customer", {"email": email, "include": "tier"})
    except Exception as exc:  # NotFound / ToolError / transport errors
        raise WorkflowError(f"customer lookup failed for {email}: {exc}") from exc
    if not isinstance(res, dict):
        raise WorkflowError(f"unexpected lookup_customer result: {res!r}")
    customer_id, tier = res.get("customer_id"), res.get("tier")
    if not isinstance(customer_id, str) or not customer_id:
        raise WorkflowError(f"lookup_customer returned no customer_id: {res!r}")
    if not isinstance(tier, str) or tier.lower() not in TIERS:
        raise WorkflowError(f"unknown customer tier {tier!r}; expected one of {sorted(TIERS)}")
    return customer_id, tier.lower()


def route_for(priority: str, tier: str) -> str:
    """Business rule: urgent (high priority or gold tier) -> escalate, else auto_reply."""
    return "escalate" if priority == "high" or tier == "gold" else "auto_reply"


def _write(tools: Tools, name: str, args: dict[str, Any], ok: Any) -> Any:
    """Call a write tool exactly once; never retry (retries risk duplicate writes)."""
    try:
        res = tools.call(name, args)
    except Exception as exc:  # any tool failure: stop, do not retry
        raise WorkflowError(f"{name} failed: {exc}") from exc
    if not ok(res):
        raise WorkflowError(f"unexpected {name} result: {res!r}")
    return res


# --------------------------------------------------------------------------- run


def run(run_input: dict, tools: Tools, model: Model) -> dict:
    # 1. Reads and validation only; nothing below can write until all checks pass.
    email, message, priority = _normalize_input(run_input, model)
    summary = _classify_and_summarize(message, priority, model)
    customer_id, tier = _lookup(tools, email)
    route = route_for(priority, tier)

    # 2. Writes, each exactly once.
    ticket = _write(
        tools,
        "create_ticket",
        {"customer_id": customer_id, "summary": summary},
        lambda r: isinstance(r, dict) and isinstance(r.get("ticket_id"), str) and r["ticket_id"],
    )
    ticket_id = ticket["ticket_id"]

    _write(
        tools,
        route,
        {"ticket_id": ticket_id},
        lambda r: isinstance(r, dict) and r.get("ok") is True,
    )

    body = f"Hello, about ticket {ticket_id}: we are on it."
    _write(
        tools,
        "send_email",
        {"to": email, "body": body},
        lambda r: isinstance(r, dict) and r.get("sent") is True,
    )

    return {"answer": f"Done: ticket {ticket_id} handled."}
