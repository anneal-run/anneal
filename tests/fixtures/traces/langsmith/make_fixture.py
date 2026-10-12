"""Generate `support_triage.jsonl`, a synthetic LangSmith run export.

One JSON object per line, in the shape `Client.list_runs()` returns
(`langsmith.schemas.Run`), flat and unordered like a real export. Payload
shapes inside `inputs`/`outputs` follow what LangChain's tracer and
`langsmith.wrappers.wrap_openai` record; see docs/vendor-notes/langsmith.md.

Regenerate and validate against the pinned SDK:

    uv run --with langsmith==0.14.7 python tests/fixtures/traces/langsmith/make_fixture.py
"""

import importlib
import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

OUT = Path(__file__).with_name("support_triage.jsonl")
NS = uuid.UUID("6f0c7a52-5b8e-4c55-9a7e-3d1d2b6a9e10")

TRIAGE_SYSTEM = "You are the triage agent. Identify the customer and route the ticket."
BILLING_SYSTEM = "You are the billing agent. Resolve refunds."
KB_SYSTEM = "Answer using the knowledge base."


def lc(cls: str, **kwargs: Any) -> dict[str, Any]:
    """A LangChain-serialized message, as the tracer stores it."""
    kind = {"SystemMessage": "system", "HumanMessage": "human", "AIMessage": "ai"}
    kind["ToolMessage"] = "tool"
    return {
        "lc": 1,
        "type": "constructor",
        "id": ["langchain", "schema", "messages", cls],
        "kwargs": {"type": kind[cls], **kwargs},
    }


def ai(content: str = "", tool_calls: list[dict[str, Any]] | None = None, **usage: Any) -> Any:
    calls = [{"type": "tool_call", **c} for c in tool_calls or []]
    return lc(
        "AIMessage",
        content=content,
        tool_calls=calls,
        invalid_tool_calls=[],
        usage_metadata=usage or None,
    )


def lc_llm_outputs(message: dict[str, Any]) -> dict[str, Any]:
    gen = {"text": message["kwargs"]["content"], "type": "ChatGeneration", "message": message}
    return {"generations": [[gen]], "llm_output": None, "run": None, "type": "LLMResult"}


class Trace:
    def __init__(self, key: str, start: datetime) -> None:
        self.key = key
        self.clock = start
        self.records: list[dict[str, Any]] = []
        self.trace_id: str = ""

    def add(
        self,
        name: str,
        run_type: str,
        parent: dict[str, Any] | None,
        inputs: dict[str, Any],
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid5(NS, f"{self.key}/{len(self.records)}"))
        self.clock += timedelta(milliseconds=150)
        stamp = f"{self.clock:%Y%m%dT%H%M%S%f}Z{run_id}"
        if parent is None:
            self.trace_id = run_id
        rec: dict[str, Any] = {
            "id": run_id,
            "name": name,
            "run_type": run_type,
            "start_time": self.clock.isoformat(),
            "end_time": None,
            "extra": extra or {},
            "error": error,
            "serialized": None,
            "events": [],
            "inputs": inputs,
            "outputs": outputs,
            "reference_example_id": None,
            "parent_run_id": parent["id"] if parent else None,
            "tags": [],
            "session_id": str(uuid.uuid5(NS, "session")),
            "child_run_ids": None,
            "status": "error" if error else "success",
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "prompt_token_details": None,
            "completion_token_details": None,
            "first_token_time": None,
            "total_cost": None,
            "prompt_cost": None,
            "completion_cost": None,
            "parent_run_ids": [],
            "trace_id": self.trace_id,
            "dotted_order": f"{parent['dotted_order']}.{stamp}" if parent else stamp,
            "in_dataset": False,
        }
        rec.update(fields)
        self.records.append(rec)
        return rec

    def close(self) -> list[dict[str, Any]]:
        """Set end times so every parent ends after its last child."""
        for rec in reversed(self.records):
            self.clock += timedelta(milliseconds=20)
            rec["end_time"] = self.clock.isoformat()
        return self.records


def anthropic_meta(model: str) -> dict[str, Any]:
    return {"metadata": {"ls_provider": "anthropic", "ls_model_name": model}}


def tokens(prompt: int, completion: int, cached: int = 0) -> dict[str, Any]:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "prompt_token_details": {"cache_read": cached} if cached else None,
    }


def handoff_trace() -> list[dict[str, Any]]:
    t = Trace("handoff", datetime(2026, 10, 1, 9, 0))
    ticket = "Refund order 1234 please. I'm jane@acme.com, call +1 415 555 0132"
    root = t.add(
        "support_triage",
        "chain",
        None,
        {"ticket": ticket},
        {"answer": "Refund issued for order 1234."},
    )
    triage = t.add("triage_agent", "chain", root, {"ticket": ticket}, {"route": "billing"})
    sys_msg, user = lc("SystemMessage", content=TRIAGE_SYSTEM), lc("HumanMessage", content=ticket)
    call1 = {"name": "lookup_customer", "args": {"email": "jane@acme.com"}, "id": "toolu_1"}
    ai1 = ai(tool_calls=[call1])
    t.add(
        "ChatAnthropic",
        "llm",
        triage,
        {"messages": [[sys_msg, user]]},
        lc_llm_outputs(ai1),
        extra=anthropic_meta("claude-sonnet-5-5"),
        **tokens(1200, 40, 1000),
    )
    customer = '{"customer_id": "C-42", "tier": "gold"}'
    tool_msg = lc("ToolMessage", content=customer, name="lookup_customer", tool_call_id="toolu_1")
    t.add(
        "lookup_customer",
        "tool",
        triage,
        {"email": "jane@acme.com"},
        {"output": tool_msg},
        extra={"tool_call_id": "toolu_1"},
    )
    call2 = {"name": "transfer_to_billing", "args": {"reason": "refund"}, "id": "toolu_2"}
    t.add(
        "ChatAnthropic",
        "llm",
        triage,
        {"messages": [[sys_msg, user, ai1, tool_msg]]},
        lc_llm_outputs(ai(tool_calls=[call2])),
        extra=anthropic_meta("claude-sonnet-5-5"),
        **tokens(1300, 30, 1000),
    )
    t.add(
        "transfer_to_billing",
        "tool",
        triage,
        {"reason": "refund"},
        {"output": "Transferred to billing_agent"},
        extra={"tool_call_id": "toolu_2"},
    )
    billing = t.add("billing_agent", "chain", root, {"ticket": ticket}, {"answer": "done"})
    b_sys = lc("SystemMessage", content=BILLING_SYSTEM)
    b_user = lc("HumanMessage", content=f"{ticket}\ncustomer_id: C-42")
    call3 = {"name": "issue_refund", "args": {"order_id": "1234", "customer_id": "C-42"}}
    ai3 = ai(tool_calls=[call3 | {"id": "toolu_3"}])
    t.add(
        "ChatAnthropic",
        "llm",
        billing,
        {"messages": [[b_sys, b_user]]},
        lc_llm_outputs(ai3),
        extra=anthropic_meta("claude-haiku-5-5"),
        **tokens(800, 35),
    )
    # The repr form below is what LangChain's tracer records when a tool returns
    # a ToolMessage object (observed with langchain-core 1.6.10).
    refund_repr = "content='{\"refund_id\": \"R-9\"}' name='issue_refund' tool_call_id='toolu_3'"
    t.add(
        "issue_refund",
        "tool",
        billing,
        {"order_id": "1234", "customer_id": "C-42"},
        {"output": refund_repr},
        extra={"tool_call_id": "toolu_3"},
    )
    refund_msg = lc(
        "ToolMessage", content='{"refund_id": "R-9"}', name="issue_refund", tool_call_id="toolu_3"
    )
    t.add(
        "ChatAnthropic",
        "llm",
        billing,
        {"messages": [[b_sys, b_user, ai3, refund_msg]]},
        lc_llm_outputs(ai("Refund issued for order 1234.")),
        extra=anthropic_meta("claude-haiku-5-5"),
        **tokens(900, 12),
    )
    return t.close()


def chat_completion(model: str, message: dict[str, Any], prompt: int, out: int, cached: int) -> Any:
    finish = "tool_calls" if message.get("tool_calls") else "stop"
    return {
        "id": "chatcmpl-x",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "finish_reason": finish, "message": message}],
        "usage_metadata": {
            "input_tokens": prompt,
            "output_tokens": out,
            "total_tokens": prompt + out,
            "input_token_details": {"cache_read": cached},
        },
    }


def openai_meta() -> dict[str, Any]:
    return {"metadata": {"ls_provider": "openai", "ls_model_name": "gpt-4o-mini"}}


def nested_trace() -> list[dict[str, Any]]:
    t = Trace("nested", datetime(2026, 10, 2, 14, 30))
    question = "How do I reset my password?"
    root = t.add("support_triage", "chain", None, {"ticket": question}, {"answer": "see steps"})
    msgs = [{"role": "system", "content": KB_SYSTEM}, {"role": "user", "content": question}]
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "search_kb", "arguments": '{"query": "reset password"}'},
    }
    first = {"role": "assistant", "content": None, "tool_calls": [tool_call]}
    t.add(
        "ChatOpenAI",
        "llm",
        root,
        {"messages": msgs, "model": "gpt-4o-mini", "tools": [{"type": "function"}]},
        chat_completion("gpt-4o-mini-2024-07-18", first, 300, 25, 128),
        extra=openai_meta(),
        total_cost="0.00012",
    )
    article = {"article": "KB-7", "summary": "Settings > Security > Reset password"}
    kb = t.add(
        "search_kb",
        "tool",
        root,
        {"query": "reset password"},
        {"output": article},
        extra={"tool_call_id": "call_1"},
    )
    inner_msgs = [{"role": "user", "content": "Summarize KB-7 in one line."}]
    t.add(
        "ChatOpenAI",
        "llm",
        kb,
        {"messages": inner_msgs, "model": "gpt-4o-mini"},
        chat_completion(
            "gpt-4o-mini-2024-07-18",
            {"role": "assistant", "content": article["summary"]},
            90,
            12,
            0,
        ),
        extra=openai_meta(),
    )
    t.add("StrOutputParser", "parser", root, {"input": "x"}, {"output": "x"})
    final = {"role": "assistant", "content": "Go to Settings > Security > Reset password."}
    tool_result = {"role": "tool", "tool_call_id": "call_1", "content": json.dumps(article)}
    t.add(
        "ChatOpenAI",
        "llm",
        root,
        {"messages": [*msgs, first, tool_result], "model": "gpt-4o-mini"},
        chat_completion("gpt-4o-mini-2024-07-18", final, 420, 18, 256),
        extra=openai_meta(),
    )
    return t.close()


def error_trace() -> list[dict[str, Any]]:
    t = Trace("error", datetime(2026, 10, 3, 11, 15))
    ticket = "Where is order 99?"
    err = "ToolException: order 99 not found"
    root = t.add("support_triage", "chain", None, {"ticket": ticket}, None, error=err)
    sys_msg, user = lc("SystemMessage", content=TRIAGE_SYSTEM), lc("HumanMessage", content=ticket)
    call = {"name": "get_order", "args": {"order_id": "99"}, "id": "toolu_9"}
    t.add(
        "ChatAnthropic",
        "llm",
        root,
        {"messages": [[sys_msg, user]]},
        lc_llm_outputs(ai(tool_calls=[call])),
        extra=anthropic_meta("claude-sonnet-5-5"),
        **tokens(1100, 30, 1000),
    )
    t.add(
        "get_order",
        "tool",
        root,
        {"order_id": "99"},
        None,
        error=err,
        extra={"tool_call_id": "toolu_9"},
    )
    return t.close()


def validate(records: list[dict[str, Any]]) -> None:
    try:
        schemas = importlib.import_module("langsmith.schemas")
    except ImportError:
        print("langsmith not installed; skipped schema validation")
        return
    for rec in records:
        schemas.Run.model_validate(rec)
    print(f"validated {len(records)} records against langsmith.schemas.Run")


def main() -> None:
    records = handoff_trace() + nested_trace() + error_trace()
    validate(records)
    random.Random(7).shuffle(records)
    OUT.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
