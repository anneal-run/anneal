"""LangGraph fallback integration (pinned: langgraph 1.2.15, langchain-core 1.6.10).

`to_langchain` turns a reconstructed history into LangChain messages: an
assistant message's tool calls become `AIMessage.tool_calls`, and tool results
become `ToolMessage`s with the matching `tool_call_id`, the pairing LangGraph
and chat model APIs require. `langgraph_fallback(graph)` returns a fallback
that invokes a compiled graph whose state holds `messages` (for example
`MessagesState`) with that history, so the agent loop continues from it.
`from_langchain` goes the other way, for a recorded run input that is graph state.
`chat_model_runner(model)` answers compiled `llm` steps with a LangChain chat model
through structured output, for live replay and for compiled paths in production.

Install with `pip install anneal-run[langgraph]`. See docs/vendor-notes/langgraph.md.
"""

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from anneal.compile.plan import LlmStep
from anneal.importers.langsmith import parse_message
from anneal.runtime.executor import LlmResponse, LlmRunner
from anneal.runtime.fallback import Fallback
from anneal.schema import Message

Cost = Callable[[str, int, int, int], float | None]
"""`(model, tokens_in, tokens_out, tokens_cached) -> USD`, e.g. `PriceTable.cost`."""


def to_langchain(messages: Sequence[Message]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in messages:
        content = m.content if m.content is not None else ""
        match m.role:
            case "system":
                out.append(SystemMessage(content=content))
            case "user":
                out.append(HumanMessage(content=content))
            case "assistant":
                calls = []
                for tc in m.tool_calls:
                    if not isinstance(tc.args, dict):
                        raise ValueError(f"tool call {tc.name}: arguments must be an object")
                    calls.append(
                        {"name": tc.name, "args": tc.args, "id": tc.id, "type": "tool_call"}
                    )
                out.append(AIMessage(content=content, tool_calls=calls))
            case "tool":
                out.append(
                    ToolMessage(content=content, tool_call_id=m.tool_call_id or "", name=m.name)
                )
    return out


def _last_message_text(state: Any) -> Any:
    return state["messages"][-1].content


def langgraph_fallback(
    graph: Any,
    *,
    output: Callable[[Any], Any] = _last_message_text,
    config: dict[str, Any] | None = None,
) -> Fallback:
    """A fallback that resumes `graph` (anything with `.invoke({"messages": ...})`) from history."""

    def fallback(history: list[Message], run_input: Any) -> Any:
        state = graph.invoke({"messages": to_langchain(history)}, config=config)
        return output(state)

    return fallback


def from_langchain(messages: Sequence[Any]) -> list[Message]:
    """LangChain messages (objects, or dicts as LangSmith records them) as anneal messages."""
    return [parse_message(m.model_dump() if isinstance(m, BaseMessage) else m) for m in messages]


def chat_model_runner(model: Any, *, cost: Cost | None = None) -> LlmRunner:
    """An `LlmRunner` that asks `model` (a LangChain chat model) for the step's
    structured output. An answer that does not parse comes back as `{}`, so it
    fails validation and the executor retries once with the error as feedback."""

    def run(step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
        if feedback:
            user = f"{user}\n\nYour previous answer was invalid: {feedback}. Answer again."
        schema = {"title": f"step_{step.id}", "description": "Your answer.", **step.output_schema}
        answer = model.with_structured_output(schema, include_raw=True).invoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
        raw = answer.get("raw")
        usage = getattr(raw, "usage_metadata", None) or {}
        meta = getattr(raw, "response_metadata", None) or {}
        name = meta.get("model_name") or meta.get("model") or step.model
        tokens_in = int(usage.get("input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)
        cached = int((usage.get("input_token_details") or {}).get("cache_read") or 0)
        parsed = answer.get("parsed")
        if hasattr(parsed, "model_dump"):
            parsed = parsed.model_dump()
        return LlmResponse(
            output=parsed if parsed is not None else {},
            model=name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cached=cached,
            cost_usd=cost(name, tokens_in, tokens_out, cached) if cost and name else None,
        )

    return run
