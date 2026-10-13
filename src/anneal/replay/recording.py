"""Recording-backed tools and models for replay.

`RecordingToolServer` serves a tool call only when `(name, canonical args)`
matches a call in the recorded run; identical calls are served in recorded
order. Anything else is a divergence at that step: live, the compiled path
would have made a call the agent never made.

`RecordedLlm` answers an llm step with what the recorded run's model did at
the same prefix-tree position. When the recorded model did something the step
cannot express (another tool, text instead of a tool), it deopts. This makes
replay optimistic about forced steps: a live model forced onto a tool would
answer anyway. Measuring that needs a live runner (ADR 0006).
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from anneal.classify.classifier import position_id, run_view
from anneal.compile.plan import LlmStep, ToolStep
from anneal.runtime.executor import DeoptRequested, LlmResponse
from anneal.runtime.outbox import canonical
from anneal.schema import ModelCall, Run, ToolCall


@dataclass(frozen=True)
class DivergenceInfo:
    step_id: str
    tool: str
    args: Any
    recorded: list[Any]
    """Recorded arguments of calls to the same tool."""


class Divergence(Exception):
    def __init__(self, info: DivergenceInfo) -> None:
        super().__init__(f"{info.tool} called with arguments the recorded run never used")
        self.info = info


class RecordedToolError(Exception):
    """The recorded call failed; replay fails it the same way."""


class RecordingToolServer:
    def __init__(self, run: Run) -> None:
        self._calls: dict[tuple[str, str], deque[ToolCall]] = defaultdict(deque)
        self._by_name: dict[str, list[Any]] = defaultdict(list)
        for e in run.events:
            if isinstance(e, ToolCall):
                self._calls[(e.name, canonical(e.args))].append(e)
                self._by_name[e.name].append(e.args)
        self.divergence: DivergenceInfo | None = None

    def __call__(self, step: ToolStep, args: Any, key: str | None = None) -> Any:
        queue = self._calls.get((step.name, canonical(args)))
        if not queue:
            self.divergence = DivergenceInfo(step.id, step.name, args, self._by_name[step.name])
            raise Divergence(self.divergence)
        call = queue.popleft()
        if call.error:
            raise RecordedToolError(call.error)
        return call.result


class RecordedLlm:
    def __init__(self, run: Run) -> None:
        view = run_view(run)
        self._calls: dict[str, ModelCall] = {}
        for i, event in enumerate(view.events):
            if isinstance(event, ModelCall) and event.parent_id is None:
                self._calls[position_id(view.steps[:i], view.steps[i][1])] = event

    def __call__(self, step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
        call = self._calls.get(step.position_id or "")
        if call is None:
            raise DeoptRequested(step.id, "the recorded run has no model call at this position")
        requests = call.tool_calls_requested
        if step.forced_tool:
            match = next((r for r in requests if r.name == step.forced_tool), None)
            if match is None or not isinstance(match.args, dict):
                raise DeoptRequested(step.id, f"the recorded model did not call {step.forced_tool}")
            keys = step.output_schema.get("properties", {})
            output: Any = {k: v for k, v in match.args.items() if k in keys}
        elif step.expected_tool:
            if not requests:
                raise DeoptRequested(step.id, "the recorded model called no tool")
            output = {"tool": requests[0].name, "arguments": requests[0].args}
        else:
            if requests:
                raise DeoptRequested(
                    step.id, "the recorded model called a tool where the plan expects text"
                )
            output = {"text": call.output_text or ""}
        return LlmResponse(
            output=output,
            model=call.model,
            provider=call.provider,
            tokens_in=call.tokens_in,
            tokens_out=call.tokens_out,
            tokens_cached=call.tokens_cached,
            cost_usd=call.cost_usd,
        )
