"""LangGraph fallback integration (pinned: langgraph 1.2.15, langchain-core 1.6.10).

`to_langchain` turns a reconstructed history into LangChain messages: an
assistant message's tool calls become `AIMessage.tool_calls`, and tool results
become `ToolMessage`s with the matching `tool_call_id`, the pairing LangGraph
and chat model APIs require. `langgraph_fallback(graph)` returns a fallback
that invokes a compiled graph whose state holds `messages` (for example
`MessagesState`) with that history, so the agent loop continues from it.

Install with `pip install anneal-run[langgraph]`. See docs/vendor-notes/langgraph.md.
"""

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from anneal.runtime.fallback import Fallback
from anneal.schema import Message


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
