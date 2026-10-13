# LangGraph

Pinned and checked on 2026-10-13:

- `langgraph` 1.2.15 (dev dependency; used in tests only)
- `langchain-core` 1.6.10 (the `anneal-run[langgraph]` extra)
- Docs: https://langchain-ai.github.io/langgraph/ (graphs, `MessagesState`, `ToolNode`, `tools_condition`)

## What the integration relies on

- **Messages.** LangChain message classes from `langchain_core.messages`: `SystemMessage`, `HumanMessage`, `AIMessage(content, tool_calls=[{"name", "args", "id", "type": "tool_call"}])` and `ToolMessage(content, tool_call_id, name)`.
- **Pairing.** Every tool call id in an `AIMessage` must be answered by a `ToolMessage` with the same `tool_call_id` before the next model turn. Chat model APIs reject unpaired calls.
- **Resuming.** A graph whose state has a `messages` key with an `add_messages` reducer (for example `MessagesState`) is invoked with `graph.invoke({"messages": [...]})`. Execution starts at `START`; for a ReAct-style graph that is the agent node, so the model sees the full reconstructed history and decides the next step.
- **Tool arguments.** `ToolNode` passes `tool_calls[i]["args"]` to the tool. Those arguments must be an object, so the integration refuses non-object arguments.
- **`create_react_agent`.** `langgraph.prebuilt.create_react_agent` still exists in 1.2.15, but the tests build the graph from `StateGraph`, `ToolNode` and `tools_condition` so they depend only on the stable pieces.

## System prompt

Many LangGraph agents inject the system prompt inside the agent node rather than keeping it in `messages`. The default initial history is therefore the run input as one user message. If an agent keeps its system prompt in state, pass `initial_messages=` to `CompiledWorkflow` so it is included. Never include it twice.

## Not covered yet

- Checkpointers and `thread_id`: resuming into an existing persisted thread.
- Subgraphs.
- `Command`-based handoffs.
- Async `ainvoke`.
