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

## Seen in real traces (github_triage dogfood, 2026-10-13)

These came from running a LangGraph agent with `langchain-anthropic` 1.7.6 on `claude-haiku-5-5`.

- **Graph state is the run's input and output.** `Run.input` is `{"messages": [<HumanMessage dumped as a plain dict>]}`. `Run.output` is the final state, which holds every message, including provider content blocks with `signature` fields, plus any extra state keys. Pass `output_path=` to `compile_plan` to say which part the caller uses. Use `from_langchain` to turn the recorded input back into the initial history.
- **Structured output is a tool request.** `with_structured_output(Model)` on Anthropic sends a forced tool named after the schema (`Triage`). The answer comes back as that tool's arguments, and no tool run follows. Since the ADR 0004 amendment the classifier treats this call as the run's output.
- **Parallel tool calls are common.** The first turn usually asks for `get_issue` and `list_labels` together. Both `ToolMessage`s follow before the next model turn.
- **Claude 5 models reject two things.** They reject `temperature` (400: "`temperature` is deprecated for this model") and they reject a conversation that ends with an assistant turn (400: "does not support assistant message prefill"). A final structured-output call after the tool loop must therefore end with a user turn.

## Not covered yet

- Checkpointers and `thread_id`: resuming into an existing persisted thread.
- Subgraphs.
- `Command`-based handoffs.
- Async `ainvoke`.
