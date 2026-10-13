"""A real LangChain chat model answering compiled llm steps (offline: a fake model)."""

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from anneal.compile.plan import LlmStep
from anneal.integrations.langgraph import chat_model_runner, from_langchain

STEP = LlmStep(
    id="s1",
    role="agent",
    model="claude-haiku-5-5",
    system_template="sys",
    user_template="u",
    output_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
)


class Structured(FakeMessagesListChatModel):
    seen: list[Any] = Field(default_factory=list)
    answers: list[Any] = Field(default_factory=list)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        def answer(messages: list[BaseMessage]) -> dict[str, Any]:
            self.seen.append((schema, kwargs, messages))
            parsed = self.answers.pop(0)
            raw = AIMessage(
                content="",
                usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
                response_metadata={"model_name": "claude-haiku-5-5"},
            )
            return {"raw": raw, "parsed": parsed, "parsing_error": None}

        return RunnableLambda(answer)


def test_runner_asks_for_the_step_schema_and_reports_usage_and_cost() -> None:
    model = Structured(responses=[], seen=[], answers=[{"text": "hi"}])
    prices: list[tuple[str, int, int, int]] = []

    def cost(model_name: str, tin: int, tout: int, cached: int) -> float:
        prices.append((model_name, tin, tout, cached))
        return 0.5

    runner = chat_model_runner(model, cost=cost)
    response = runner(STEP, "system text", "user text", None)
    assert response.output == {"text": "hi"}
    assert (response.tokens_in, response.tokens_out, response.cost_usd) == (100, 10, 0.5)
    assert response.model == "claude-haiku-5-5"
    assert prices == [("claude-haiku-5-5", 100, 10, 0)]
    schema, kwargs, messages = model.seen[0]
    assert schema["properties"] == STEP.output_schema["properties"] and schema["title"]
    assert kwargs["include_raw"] is True
    assert [m.type for m in messages] == ["system", "human"]
    assert (messages[0].content, messages[1].content) == ("system text", "user text")


def test_feedback_from_a_failed_validation_reaches_the_model() -> None:
    model = Structured(responses=[], seen=[], answers=[None])
    response = chat_model_runner(model)(STEP, "s", "u", "missing field text")
    assert response.output == {}  # unparseable answers fail validation and get one retry
    assert "missing field text" in model.seen[0][2][1].content


def test_langgraph_state_messages_become_anneal_messages() -> None:
    state = {
        "messages": [
            {"type": "human", "content": "Please triage issue #1 in a/b.", "id": "x"},
            {"type": "ai", "content": "", "tool_calls": [{"name": "t", "args": {}, "id": "c"}]},
        ]
    }
    messages = from_langchain(state["messages"])
    assert [(m.role, m.content) for m in messages] == [
        ("user", "Please triage issue #1 in a/b."),
        ("assistant", ""),
    ]
    assert messages[1].tool_calls[0].name == "t"
