"""Fallback that resumes the original agent (CONTRACT, ANNEAL-ROADMAP.md M1.6).

On a deopt, the agent's own history is reconstructed: the initial messages
(the run input, and the agent's system prompt if the agent keeps it in its
message history), then, for each completed step in order:

- a tool step: one assistant message carrying the tool call (the arguments
  the compiled path actually used) and one tool message carrying its result;
- a text llm step: one assistant message with the text.

An llm step that wrote a tool's arguments or chose a tool is represented by
that tool's call, so its output appears only if the tool ran. Never a summary.
History is framework-neutral (`anneal.schema.Message`); integrations convert it
(`anneal.integrations.langgraph`). Tool call ids are the steps' operation keys,
`anneal-<run_id>-<step_id>`; keys of side-effect calls that did not complete are
available to the agent's tools through `operation_key_for` (M1.7).
"""

import json
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

from anneal.compile.plan import EndStep, LlmStep, ToolStep, WorkflowPlan
from anneal.runtime.executor import (
    ExecutionResult,
    Executor,
    LlmRunner,
    ToolRunner,
    operation_key,
)
from anneal.runtime.outbox import Outbox, Reconcile, canonical
from anneal.schema import Message, Severity, ToolCallRequest

Fallback = Callable[[list[Message], Any], Any]
"""The original agent entrypoint: `(history, run_input) -> output`."""


call_id = operation_key
"""Tool call ids in reconstructed history are the steps' operation keys."""

_RESUME_KEYS: ContextVar[Mapping[tuple[str, str], str] | None] = ContextVar(
    "anneal_resume_keys", default=None
)


def operation_key_for(tool: str, args: Any) -> str | None:
    """While a fallback runs: the operation key of a side-effect call the compiled path
    attempted without completing, if `tool` is called with the same arguments. Agent
    tools pass it to the external system so a repeat is a no-op there."""
    keys = _RESUME_KEYS.get()
    return keys.get((tool, canonical(args))) if keys else None


def default_initial_messages(run_input: Any) -> list[Message]:
    """The run input as the first user message (JSON unless it is already text)."""
    content = run_input if isinstance(run_input, str) else json.dumps(run_input, sort_keys=True)
    return [Message(role="user", content=content)]


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def reconstruct_history(
    plan: WorkflowPlan, execution: ExecutionResult, initial: Sequence[Message]
) -> list[Message]:
    """The message history the agent would have had after the completed steps."""
    steps = {s.id: s for s in plan.steps}
    run_id = execution.trace.run_id
    history = list(initial)
    for step_id in execution.completed:
        step = steps[step_id]
        match step:
            case ToolStep():
                cid = call_id(run_id, step_id)
                request = ToolCallRequest(id=cid, name=step.name, args=execution.rendered[step_id])
                history += [
                    Message(role="assistant", content="", tool_calls=[request]),
                    Message(
                        role="tool",
                        content=_text(execution.state[step_id]),
                        tool_call_id=cid,
                        name=step.name,
                    ),
                ]
            case LlmStep() if (
                step.forced_tool is None
                and step.expected_tool is None
                and "text" in execution.state[step_id]
            ):
                history.append(Message(role="assistant", content=execution.state[step_id]["text"]))
            case LlmStep() | EndStep():
                pass
    return history


@dataclass
class WorkflowOutcome:
    output: Any
    tier: Literal[0, 1]
    """1 when the compiled path finished the run, 0 when the original agent did."""
    execution: ExecutionResult
    history: list[Message] | None = None


class CompiledWorkflow:
    """Runs a plan and hands any deopt to the registered fallback with the reconstructed history."""

    def __init__(
        self,
        plan: WorkflowPlan,
        *,
        tools: ToolRunner,
        llm: LlmRunner,
        fallback: Fallback | None = None,
        initial_messages: Callable[[Any], list[Message]] = default_initial_messages,
        live_severities: frozenset[Severity] = frozenset({"S0"}),
        outbox: Outbox | None = None,
        reconcilers: Mapping[str, Reconcile] | None = None,
    ) -> None:
        self.plan = plan
        self.executor = Executor(
            plan,
            tools=tools,
            llm=llm,
            live_severities=live_severities,
            outbox=outbox,
            reconcilers=reconcilers,
        )
        self.fallback = fallback
        self.initial_messages = initial_messages

    def register_fallback(self, fallback: Fallback) -> Fallback:
        """Register the original agent entrypoint; usable as a decorator."""
        self.fallback = fallback
        return fallback

    def run(self, run_input: Any, *, run_id: str | None = None) -> WorkflowOutcome:
        execution = self.executor.run(run_input, run_id=run_id)
        if execution.deopt is None:
            return WorkflowOutcome(output=execution.output, tier=1, execution=execution)
        if self.fallback is None:
            raise RuntimeError(f"deopt at {execution.deopt.step_id} and no fallback registered")
        history = reconstruct_history(self.plan, execution, self.initial_messages(run_input))
        token = _RESUME_KEYS.set(dict(execution.pending_keys))
        try:
            output = self.fallback(history, run_input)
        finally:
            _RESUME_KEYS.reset(token)
        return WorkflowOutcome(output=output, tier=0, execution=execution, history=history)
