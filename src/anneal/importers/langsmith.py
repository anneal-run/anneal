"""Import a LangSmith run export (JSONL of `langsmith.schemas.Run` records).

One trace (all records sharing a `trace_id`) becomes one `Run`. Records of type
`llm` become `ModelCall` events, `tool` and `retriever` become `ToolCall`
events, and every other type (chain, parser, prompt, ...) is structure only: it
sets `scope` (nearest enclosing chain) but is not an event. Both payload shapes
LangSmith records are understood: LangChain-serialized messages and the raw
OpenAI request/response recorded by `wrap_openai`. Pinned versions and observed
shapes are in docs/vendor-notes/langsmith.md.
"""

import ast
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeGuard

from anneal.schema import Event, Message, ModelCall, Run, ToolCall, ToolCallRequest

SOURCE = "langsmith"
_TOOL_TYPES = {"tool", "retriever"}
_EVENT_TYPES = _TOOL_TYPES | {"llm"}
_ROLES = {
    "system": "system",
    "developer": "system",
    "user": "user",
    "human": "user",
    "assistant": "assistant",
    "ai": "assistant",
    "tool": "tool",
    "function": "tool",
}
_TOOL_MESSAGE_REPR = re.compile(
    r"""^content=('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*") .*tool_call_id="""
)

Record = dict[str, Any]


def load_runs(path: Path | str, workflow_id: str | None = None) -> list[Run]:
    """Read a LangSmith JSONL export and return one `Run` per trace."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return import_records([json.loads(line) for line in lines if line.strip()], workflow_id)


def import_records(records: Iterable[Record], workflow_id: str | None = None) -> list[Run]:
    """Group records by trace and convert each trace; `workflow_id` defaults to the root's name."""
    traces: dict[str, list[Record]] = defaultdict(list)
    for rec in records:
        traces[str(rec.get("trace_id") or rec["id"])].append(rec)
    runs = [_trace_to_run(tid, recs, workflow_id) for tid, recs in traces.items()]
    return sorted(runs, key=lambda r: r.started_at)


def _trace_to_run(trace_id: str, recs: list[Record], workflow_id: str | None) -> Run:
    roots = [r for r in recs if not r.get("parent_run_id")]
    if not roots:
        raise ValueError(f"trace {trace_id}: no root run in the export")
    root = roots[0]
    by_id = {str(r["id"]): r for r in recs}
    ordered = sorted(recs, key=lambda r: (r.get("dotted_order") or "", _ts(r["start_time"])))
    events: list[Event] = []
    for rec in ordered:
        if rec is root or rec.get("run_type") not in _EVENT_TYPES:
            continue
        parent_id, scope = _context(rec, by_id, root)
        common: dict[str, Any] = {
            "event_id": str(rec["id"]),
            "parent_id": parent_id,
            "ts": _ts(rec["start_time"]),
            "scope": scope,
        }
        if rec["run_type"] == "llm":
            events.append(_model_call(rec, common))
        else:
            events.append(_tool_call(rec, common))
    return Run(
        run_id=str(root["id"]),
        workflow_id=workflow_id or root["name"],
        started_at=_ts(root["start_time"]),
        ended_at=_ts(root["end_time"]) if root.get("end_time") else None,
        status=_status(root),
        input=root.get("inputs"),
        output=root.get("outputs"),
        events=events,
        source=SOURCE,
    )


def _context(rec: Record, by_id: dict[str, Record], root: Record) -> tuple[str | None, str | None]:
    """Nearest enclosing event id and nearest enclosing chain name, below the root."""
    parent_id: str | None = None
    scope: str | None = None
    node = by_id.get(str(rec.get("parent_run_id")))
    while node is not None and node is not root:
        if parent_id is None and node.get("run_type") in _EVENT_TYPES:
            parent_id = str(node["id"])
        if scope is None and node.get("run_type") == "chain":
            scope = node["name"]
        node = by_id.get(str(node.get("parent_run_id")))
    return parent_id, scope


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _status(rec: Record) -> Literal["success", "error", "pending"]:
    match rec.get("status"):
        case "success":
            return "success"
        case "error":
            return "error"
        case "pending":
            return "pending"
    if rec.get("error"):
        return "error"
    return "success" if rec.get("end_time") else "pending"


# Model calls


def _model_call(rec: Record, common: dict[str, Any]) -> ModelCall:
    inputs: dict[str, Any] = rec.get("inputs") or {}
    outputs: dict[str, Any] = rec.get("outputs") or {}
    meta: dict[str, Any] = (rec.get("extra") or {}).get("metadata") or {}
    messages = [_message(m) for m in _input_messages(inputs)]
    raw_out = _output_message(outputs)
    out = _message(raw_out) if raw_out is not None else None
    usage = _usage(outputs, raw_out, meta)
    cached = (rec.get("prompt_token_details") or {}).get("cache_read")
    return ModelCall(
        **common,
        provider=meta.get("ls_provider"),
        model=_model_name(rec, meta, outputs, raw_out),
        system_hash=_system_hash(messages),
        messages=messages,
        output_text=_text(out.content) if out else None,
        tool_calls_requested=out.tool_calls if out else [],
        tokens_in=_first(rec.get("prompt_tokens"), usage.get("input_tokens")),
        tokens_out=_first(rec.get("completion_tokens"), usage.get("output_tokens")),
        tokens_cached=_first(cached, (usage.get("input_token_details") or {}).get("cache_read")),
        cost_usd=float(rec["total_cost"]) if rec.get("total_cost") is not None else None,
    )


def _first(*values: Any) -> Any:
    return next((v for v in values if v is not None), None)


def _input_messages(inputs: dict[str, Any]) -> list[Any]:
    messages = inputs.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[0], list):
        return list(messages[0])  # LangChain records a batch of one
    if isinstance(messages, list):
        return messages
    prompts = inputs.get("prompts")
    if isinstance(prompts, list) and prompts:
        return [{"role": "user", "content": prompts[0]}]
    return []


def _output_message(outputs: dict[str, Any]) -> Any:
    generations = outputs.get("generations")
    if isinstance(generations, list) and generations and generations[0]:
        gen = generations[0][0]
        return gen.get("message") or {"role": "assistant", "content": gen.get("text")}
    choices = outputs.get("choices")
    if isinstance(choices, list) and choices:
        return choices[0].get("message")
    return None


def _message(raw: Any) -> Message:
    if isinstance(raw, dict) and raw.get("lc") and "kwargs" in raw:
        kw = raw["kwargs"]
        role = kw.get("type") or str(raw["id"][-1]).removesuffix("Message").lower()
        data = {**kw, "role": role}
    elif isinstance(raw, dict):
        data = {**raw, "role": raw.get("role") or raw.get("type")}
    else:
        data = {"role": "user", "content": raw}
    role = _ROLES.get(str(data["role"]))
    if role is None:
        raise ValueError(f"unknown message role {data['role']!r}")
    return Message(
        role=role,  # type: ignore[arg-type]
        content=data.get("content"),
        tool_calls=[_tool_request(t) for t in data.get("tool_calls") or []],
        tool_call_id=data.get("tool_call_id"),
        name=data.get("name"),
    )


def _tool_request(raw: dict[str, Any]) -> ToolCallRequest:
    if "function" in raw:  # OpenAI shape
        fn = raw["function"]
        return ToolCallRequest(id=raw.get("id"), name=fn["name"], args=_args(fn.get("arguments")))
    return ToolCallRequest(id=raw.get("id"), name=raw["name"], args=_args(raw.get("args")))


def _args(raw: Any) -> dict[str, Any] | str:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return str(raw)
    return parsed if isinstance(parsed, dict) else str(raw)


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in content
            if not isinstance(b, dict) or b.get("type", "text") == "text"
        )
    return json.dumps(content, sort_keys=True)


def _usage(outputs: dict[str, Any], raw_out: Any, meta: dict[str, Any]) -> dict[str, Any]:
    if isinstance(outputs.get("usage_metadata"), dict):
        return dict(outputs["usage_metadata"])
    if isinstance(raw_out, dict) and isinstance(
        (raw_out.get("kwargs") or {}).get("usage_metadata"), dict
    ):
        return dict(raw_out["kwargs"]["usage_metadata"])
    if isinstance(meta.get("usage_metadata"), dict):
        return dict(meta["usage_metadata"])
    usage = outputs.get("usage")
    if isinstance(usage, dict):  # raw OpenAI usage block
        details = usage.get("prompt_tokens_details") or {}
        return {
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "input_token_details": {"cache_read": details.get("cached_tokens")},
        }
    return {}


def _model_name(
    rec: Record, meta: dict[str, Any], outputs: dict[str, Any], raw_out: Any
) -> str | None:
    params = (rec.get("extra") or {}).get("invocation_params") or {}
    response = (
        (raw_out.get("kwargs") or {}).get("response_metadata")
        if isinstance(raw_out, dict)
        else None
    )
    name = _first(
        meta.get("ls_model_name"),
        params.get("model"),
        params.get("model_name"),
        outputs.get("model"),
        (response or {}).get("model_name"),
    )
    return str(name) if name is not None else None


def _system_hash(messages: list[Message]) -> str | None:
    """Hash of the system prompt, computed before redaction so it is stable across runs."""
    system = [json.dumps(m.content, sort_keys=True) for m in messages if m.role == "system"]
    if not system:
        return None
    return hashlib.sha256("\n".join(system).encode()).hexdigest()[:16]


# Tool calls


def _tool_call(rec: Record, common: dict[str, Any]) -> ToolCall:
    outputs = rec.get("outputs")
    raw = (
        outputs.get("output")
        if isinstance(outputs, dict) and set(outputs) == {"output"}
        else outputs
    )
    tool_call_id = (rec.get("extra") or {}).get("tool_call_id")
    if isinstance(raw, dict) and raw.get("lc") and "kwargs" in raw:  # serialized ToolMessage
        tool_call_id = tool_call_id or raw["kwargs"].get("tool_call_id")
        raw = raw["kwargs"].get("content")
    elif _is_plain_tool_message(raw):  # ToolMessage dumped as a plain dict (langsmith 0.14)
        tool_call_id = tool_call_id or raw.get("tool_call_id")
        raw = raw.get("content")
    elif isinstance(raw, str) and (m := _TOOL_MESSAGE_REPR.match(raw)):
        raw = ast.literal_eval(m.group(1))
    return ToolCall(
        **common,
        name=rec["name"],
        args=rec.get("inputs"),
        result=_maybe_json(raw),
        error=rec.get("error"),
        tool_call_id=tool_call_id,
    )


def _is_plain_tool_message(raw: Any) -> TypeGuard[dict[str, Any]]:
    return (
        isinstance(raw, dict)
        and raw.get("type") == "tool"
        and "content" in raw
        and "tool_call_id" in raw
    )


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip()[:1] in {"{", "["}:
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value
