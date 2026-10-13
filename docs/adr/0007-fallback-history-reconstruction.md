# 0007. Fallback by history reconstruction; LangGraph first (M1.6)

Date: 2026-10-13
Status: accepted

## Context

M1.6 requires a deopt to resume the original agent with the history it would have had, in the framework's own format, never a summary. It also requires that the agent finish the task without repeating a completed step, including a completed side-effect step. There is no partner yet, so the framework is chosen without one.

## Decision

**Framework.** LangGraph comes first. The only importer is LangSmith, which is the same ecosystem, so a LangChain/LangGraph partner is the most likely first one. The integration is an optional extra (`anneal-run[langgraph]`, `langchain-core` only).

**Framework-neutral core** (`anneal.runtime.fallback`):
- **Order.** The initial messages come first. By default that is the run input as a user message; the agent's system prompt is added only if the agent keeps it in its message state.
- **Steps.** Then, for each completed step in execution order:
  - a tool step becomes one assistant message with its tool call (the arguments actually used) and one tool message with its result;
  - a text llm step becomes one assistant message with its text.
- **Steps not emitted.** An llm step that wrote a tool's arguments or chose a tool is not emitted separately; it appears as that tool's call, and only if the tool ran.
- **Call ids.** Tool call ids are `anneal-<run_id>-<step_id>`. M1.7 will carry operation keys through them.

**Registration.** `CompiledWorkflow(plan, tools=..., llm=..., fallback=...)` or `register_fallback(fn)`. The fallback is the user's agent entrypoint, `(history, run_input) -> output`. `langgraph_fallback(graph)` adapts any compiled graph with a `messages` state.

**Evidence** (`tests/integrations/test_langgraph.py`):
- **The agent.** A real LangGraph `StateGraph` with `ToolNode` is driven by a deterministic policy model that decides only from the history it sees.
- **The 20 deopts.** Twenty injected deopts cover every step of the synthetic plan. All 20 finish with task-level success, and no completed tool step is called again.
- **Side effects.** A deopt right after `create_ticket` (S1) keeps the call and its result in the history, and the agent does not create a second ticket.
- **Negative control.** Given a summary instead of history, the same agent redoes the lookup and the ticket. Mutating the reconstruction to drop tool results, or to drop side-effect steps, fails the 20-deopt test.

## Consequences

- The roadmap's 20-of-20 check asks for *real runs* and the *original agent*. Here it ran on synthetic runs with a policy agent, which proves the format and the mechanism but not a real model's behaviour on a reconstructed history. The checkbox stays open until a partner's agent is run through the same test.
- Checkpointed threads, subgraphs and `Command` handoffs are not handled. See docs/vendor-notes/langgraph.md.
