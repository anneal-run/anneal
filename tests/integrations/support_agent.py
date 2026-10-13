"""A real LangGraph agent for the synthetic support workflow, used as the fallback target.

The chat model is a deterministic policy that decides the next action only from
the message history it is given, as an LLM agent does: it calls each tool whose
result is not yet in the history, in workflow order, reuses a draft reply if one
is there, then answers. Given faithful history it continues where the compiled
path stopped; given a summary, it redoes the work.
"""

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition


def customer_of(email: str) -> str:
    return "C-" + re.sub(r"\W", "", email)[:12]


def ticket_of(customer_id: str) -> str:
    return "T-" + customer_id.removeprefix("C-")


@dataclass
class ToolBox:
    """Tool implementations shared by the compiled path and the agent; records every call."""

    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    phase: str = "compiled"

    def call(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((self.phase, name, args))
        if name == "lookup_customer":
            return {"customer_id": customer_of(args["email"]), "tier": "gold"}
        if name == "create_ticket":
            return {"ticket_id": ticket_of(args["customer_id"])}
        if name in {"auto_reply", "escalate"}:
            return {"ok": True}
        if name == "send_email":
            return {"sent": True}
        raise KeyError(name)

    def langchain_tools(self) -> list[StructuredTool]:
        def make(name: str, params: list[str]) -> StructuredTool:
            def fn(**kwargs: Any) -> str:
                return json.dumps(self.call(name, kwargs))

            schema = {
                "type": "object",
                "properties": {p: {"type": "string"} for p in params},
                "required": params,
            }
            return StructuredTool.from_function(
                func=fn, name=name, description=name, args_schema=schema
            )

        return [
            make("lookup_customer", ["email", "include"]),
            make("create_ticket", ["customer_id", "summary"]),
            make("auto_reply", ["ticket_id"]),
            make("escalate", ["ticket_id"]),
            make("send_email", ["to", "body"]),
        ]


def _parse(content: Any) -> Any:
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        try:
            return ast.literal_eval(content)
        except (ValueError, SyntaxError):
            return content


def decide(messages: list[BaseMessage]) -> AIMessage:
    run_input = _parse(next(m for m in messages if isinstance(m, HumanMessage)).content)
    names = {
        tc["id"]: tc["name"] for m in messages if isinstance(m, AIMessage) for tc in m.tool_calls
    }
    results = {
        names.get(m.tool_call_id, m.name): _parse(m.content)
        for m in messages
        if isinstance(m, ToolMessage)
    }
    drafts = [
        m.content for m in messages if isinstance(m, AIMessage) and m.content and not m.tool_calls
    ]
    n = len(messages)

    def call(name: str, args: dict[str, Any]) -> AIMessage:
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"agent-{n}"}])

    email = run_input["email"]
    if "lookup_customer" not in results:
        return call("lookup_customer", {"email": email, "include": "tier"})
    customer_id = results["lookup_customer"]["customer_id"]
    if "create_ticket" not in results:
        return call(
            "create_ticket", {"customer_id": customer_id, "summary": "Customer reports a problem"}
        )
    ticket_id = results["create_ticket"]["ticket_id"]
    if not {"auto_reply", "escalate"} & results.keys():
        return call("auto_reply", {"ticket_id": ticket_id})
    if "send_email" not in results:
        body = drafts[-1] if drafts else f"Hello, about ticket {ticket_id}: we are on it."
        return call("send_email", {"to": email, "body": body})
    return AIMessage(content=f"Done: ticket {ticket_id} handled.")


class PolicyModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "policy"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "PolicyModel":
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=decide(messages))])


def build_agent(toolbox: ToolBox) -> CompiledStateGraph[Any, Any, Any, Any]:
    model = PolicyModel().bind_tools(toolbox.langchain_tools())

    def agent(state: MessagesState) -> dict[str, Any]:
        return {"messages": [model.invoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(toolbox.langchain_tools()))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()
