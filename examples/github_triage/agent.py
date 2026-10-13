"""The triage agent: a plain LangGraph tool loop with a structured final answer.

Written the way a team would write it, not shaped to make compilation look good:
a short system prompt, the four tools bound to the model, a loop until the model
stops calling tools, then one structured-output call for the final triage (the
same pattern as LangGraph's prebuilt agent with `response_format`).

Model from env: `TRIAGE_PROVIDER` (`anthropic` or `openai`, default `anthropic`)
and `TRIAGE_MODEL` (default `claude-haiku-5-5`). No temperature is set for Anthropic:
the Claude 5 models reject it.
"""

import os
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-haiku-5-5"
RUN_NAME = "github_triage"

SYSTEM_PROMPT = """\
You help the maintainers of an open source project triage newly opened GitHub issues.

For each issue:
- Read the issue.
- Check the repository's labels and suggest the ones that apply. Only suggest labels that \
exist in the repository.
- Search for similar earlier issues. If an earlier issue reports the same problem, mark the \
new one as a duplicate of it. If you're not sure, don't mark it as a duplicate.
- Draft a short, friendly reply to the reporter with draft_comment. Don't promise fixes \
or timelines.

When you're done, give your final triage."""


class Triage(BaseModel):
    """The final triage of the issue."""

    suggested_labels: list[str] = Field(description="Labels to apply, from the repo's label set")
    duplicate_of: int | None = Field(description="Number of the earlier issue this duplicates")
    draft_reply: str = Field(description="The reply to post to the reporter")


class TriageState(MessagesState):
    triage: dict[str, Any] | None


def chat_model() -> BaseChatModel:
    provider = os.environ.get("TRIAGE_PROVIDER", DEFAULT_PROVIDER)
    model = os.environ.get("TRIAGE_MODEL", DEFAULT_MODEL)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=model,
            max_tokens=2048,  # type: ignore[call-arg]  # pydantic alias of max_tokens_to_sample
            timeout=60,
            stop=None,
        )
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, temperature=0)
    raise ValueError(f"TRIAGE_PROVIDER must be anthropic or openai, not {provider!r}")


def first_message(repo: str, number: int) -> HumanMessage:
    return HumanMessage(content=f"Please triage issue #{number} in {repo}.")


def build_agent(
    model: BaseChatModel, tools: Sequence[BaseTool]
) -> CompiledStateGraph[Any, Any, Any, Any]:
    with_tools = model.bind_tools(tools)
    structured = model.with_structured_output(Triage)

    def prompt(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
        return [SystemMessage(content=SYSTEM_PROMPT), *messages]

    def agent(state: TriageState) -> dict[str, Any]:
        return {"messages": [with_tools.invoke(prompt(state["messages"]))]}

    def respond(state: TriageState) -> dict[str, Any]:
        # Claude 5 models reject a conversation that ends with an assistant turn.
        ask = HumanMessage(content="Give your final triage.")
        result = structured.invoke([*prompt(state["messages"]), ask])
        assert isinstance(result, Triage)
        return {"triage": result.model_dump()}

    graph = StateGraph(TriageState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(list(tools)))
    graph.add_node("respond", respond)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", "__end__": "respond"})
    graph.add_edge("tools", "agent")
    graph.add_edge("respond", END)
    return graph.compile()
