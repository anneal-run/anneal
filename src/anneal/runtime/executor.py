"""Plan executor (ANNEAL-ROADMAP.md M1.4).

Runs a `WorkflowPlan` for one input: guards first, then steps in dependency
order with their results kept in `state` by step id, then the end step. Any of
these stops the run with a deopt, handing control back to the original agent
(M1.6 reconstructs its history from `completed` and the trace):

- a guard fails;
- a tool step's severity is not in `live_severities` (default S0 only). The
  executor stops *before* the write rather than skipping it, so a plan never
  reports success for an action it did not take;
- a tool raises;
- an llm step's output fails its schema twice (one retry with the errors as
  feedback), or a tool-choosing step picks a tool other than `expected_tool`;
- a template does not resolve.

Every execution is traced as a `Run` with `tier=1` and `source="anneal"`. A
deopted trace has status `pending`, since the run continues in the original agent.
`dry_run` renders every step without calling tools or models.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from anneal.compile.plan import EndStep, LlmStep, ToolStep, WorkflowPlan
from anneal.compile.template import TemplateError, render
from anneal.runtime.checks import failing_guard, schema_errors
from anneal.schema import Deopt, Event, Message, ModelCall, Run, Severity, ToolCall, ToolCallRequest


@dataclass(frozen=True)
class LlmResponse:
    output: Any
    model: str | None = None
    provider: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached: int | None = None
    cost_usd: float | None = None


class ToolRunner(Protocol):
    def __call__(self, step: ToolStep, args: Any) -> Any: ...


class LlmRunner(Protocol):
    def __call__(
        self, step: LlmStep, system: str, user: str, feedback: str | None
    ) -> LlmResponse: ...


class DeoptRequested(Exception):
    """The compiled path cannot continue; the original agent takes over."""

    def __init__(self, step_id: str, reason: str, guard_id: str | None = None) -> None:
        super().__init__(f"{step_id}: {reason}")
        self.step_id = step_id
        self.reason = reason
        self.guard_id = guard_id


@dataclass
class ExecutionResult:
    status: Literal["success", "deopt"]
    output: Any
    state: dict[str, Any]
    completed: list[str]
    trace: Run
    deopt: DeoptRequested | None = None
    rendered: dict[str, Any] = field(default_factory=dict)


class _DryValue(str):
    """Stands in for a step result during a dry run; indexing extends the reference."""

    def __getitem__(self, key: Any) -> "_DryValue":
        suffix = f".{key}" if isinstance(key, str) else f"[{key}]"
        return _DryValue(str.__str__(self).removesuffix(">") + suffix + ">")


def _dry(step_id: str) -> _DryValue:
    return _DryValue(f"<steps.{step_id}.result>")


class Executor:
    def __init__(
        self,
        plan: WorkflowPlan,
        *,
        tools: ToolRunner,
        llm: LlmRunner,
        dry_run: bool = False,
        live_severities: frozenset[Severity] = frozenset({"S0"}),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.plan = plan
        self.tools = tools
        self.llm = llm
        self.dry_run = dry_run
        self.live_severities = live_severities
        self.clock = clock
        self._order = plan.dependency_order()
        self._steps = {s.id: s for s in plan.steps}

    def run(self, run_input: Any, *, run_id: str | None = None) -> ExecutionResult:
        run_id = run_id or uuid.uuid4().hex
        started = self.clock()
        state: dict[str, Any] = {}
        completed: list[str] = []
        rendered: dict[str, Any] = {}
        events: list[Event] = []
        output: Any = None
        deopt: DeoptRequested | None = None
        try:
            if (guard := failing_guard(self.plan.guards, run_input)) is not None:
                raise DeoptRequested("guards", f"guard {guard.id} failed", guard_id=guard.id)
            for step_id in self._order:
                step = self._steps[step_id]
                ctx = {"input": run_input, "steps": {k: {"result": v} for k, v in state.items()}}
                match step:
                    case ToolStep():
                        state[step_id] = self._tool(step, ctx, run_id, rendered, events)
                    case LlmStep():
                        state[step_id] = self._llm(step, ctx, run_id, rendered, events)
                    case EndStep():
                        output = self._render(step.id, step.output_template, ctx)
                        rendered[step_id] = output
                completed.append(step_id)
        except DeoptRequested as e:
            deopt = e
            events.append(
                Deopt(
                    event_id=f"{run_id}:deopt",
                    ts=self.clock(),
                    step_id=e.step_id,
                    guard_id=e.guard_id,
                    reason=e.reason,
                )
            )
        trace = Run(
            run_id=run_id,
            workflow_id=self.plan.workflow_id,
            started_at=started,
            ended_at=self.clock(),
            status="pending" if deopt else "success",
            input=run_input,
            output=output,
            events=events,
            source="anneal",
            tier=1,
        )
        return ExecutionResult(
            status="deopt" if deopt else "success",
            output=output,
            state=state,
            completed=completed,
            trace=trace,
            deopt=deopt,
            rendered=rendered,
        )

    def _render(self, step_id: str, template: Any, ctx: dict[str, Any]) -> Any:
        try:
            return render(template, ctx)
        except TemplateError as e:
            raise DeoptRequested(step_id, f"template error: {e}") from None

    def _tool(
        self,
        step: ToolStep,
        ctx: dict[str, Any],
        run_id: str,
        rendered: dict[str, Any],
        events: list[Event],
    ) -> Any:
        args = self._render(step.id, step.args_template, ctx)
        rendered[step.id] = args
        if self.dry_run:
            return _dry(step.id)
        if step.severity not in self.live_severities:
            raise DeoptRequested(step.id, f"tool {step.name} is {step.severity}, not live")
        ts = self.clock()
        common: dict[str, Any] = {
            "event_id": f"{run_id}:{step.id}",
            "ts": ts,
            "name": step.name,
            "args": args,
            "side_effect": step.side_effect,
            "severity": step.severity,
        }
        try:
            result = self.tools(step, args)
        except Exception as e:  # the tool's failure is the agent's to handle
            error = f"{type(e).__name__}: {e}"
            events.append(ToolCall(**common, error=error))
            raise DeoptRequested(step.id, f"tool error: {error}") from None
        events.append(ToolCall(**common, result=result))
        return result

    def _llm(
        self,
        step: LlmStep,
        ctx: dict[str, Any],
        run_id: str,
        rendered: dict[str, Any],
        events: list[Event],
    ) -> Any:
        system = self._render(step.id, step.system_template, ctx)
        user = self._render(step.id, step.user_template, ctx)
        rendered[step.id] = {"system": system, "user": user}
        if self.dry_run:
            return _dry(step.id)
        feedback: str | None = None
        for attempt in range(2):
            response = self.llm(step, system, user, feedback)
            events.append(self._model_event(step, run_id, attempt, system, user, response))
            errors = schema_errors(response.output, step.output_schema)
            if not errors:
                break
            feedback = "; ".join(errors)
        else:
            raise DeoptRequested(step.id, f"invalid structured output after retry: {feedback}")
        output = response.output
        if step.expected_tool and output.get("tool") != step.expected_tool:
            raise DeoptRequested(
                step.id,
                f"chose {output.get('tool')!r}, compiled path expects {step.expected_tool!r}",
            )
        return output

    def _model_event(
        self, step: LlmStep, run_id: str, attempt: int, system: str, user: str, r: LlmResponse
    ) -> ModelCall:
        requested: list[ToolCallRequest] = []
        if isinstance(r.output, dict):
            if step.forced_tool:
                requested = [ToolCallRequest(name=step.forced_tool, args=r.output)]
            elif step.expected_tool and isinstance(r.output.get("tool"), str):
                args = r.output.get("arguments")
                requested = [
                    ToolCallRequest(
                        name=r.output["tool"], args=args if isinstance(args, dict) else {}
                    )
                ]
        return ModelCall(
            event_id=f"{run_id}:{step.id}" + (f":retry{attempt}" if attempt else ""),
            ts=self.clock(),
            scope=step.role,
            provider=r.provider,
            model=r.model or step.model,
            messages=[Message(role="system", content=system), Message(role="user", content=user)],
            output_text=json.dumps(r.output, sort_keys=True),
            tool_calls_requested=requested,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            tokens_cached=r.tokens_cached,
            cost_usd=r.cost_usd,
        )
