"""Canonical trace models, `schema_version: 1` (CONTRACT, see ANNEAL-ROADMAP.md M1.1).

Conventions:
- All timestamps are timezone-aware.
- `ModelCall.tokens_in` counts every input token, including cached ones;
  `tokens_cached` is the subset served from the provider's prompt cache.
- `parent_id` is the nearest enclosing event, or None at the top level of the run.
- `scope` names the enclosing agent or graph node (for example a handoff target),
  so the same tool inside different agents stays distinguishable.
"""

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Severity = Literal["S0", "S1", "S2"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolCallRequest(_Model):
    """A tool call the model asked for in its output."""

    id: str | None = None
    name: str
    args: dict[str, Any] | str
    """Parsed arguments; the raw string when the model emitted invalid JSON."""


class Message(_Model):
    """One chat message in provider-neutral form."""

    role: Literal["system", "user", "assistant", "tool"]
    content: Any = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class _Event(_Model):
    event_id: str
    parent_id: str | None = None
    ts: AwareDatetime
    scope: str | None = None


class ModelCall(_Event):
    """One call to a language model."""

    kind: Literal["model_call"] = "model_call"
    provider: str | None = None
    model: str | None = None
    system_hash: str | None = None
    messages: list[Message] = Field(default_factory=list)
    output_text: str | None = None
    tool_calls_requested: list[ToolCallRequest] = Field(default_factory=list)
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_cached: int | None = None
    cost_usd: float | None = None


class ToolCall(_Event):
    """One tool execution. `side_effect` and `severity` are None until declared at scoping."""

    kind: Literal["tool_call"] = "tool_call"
    name: str
    args: Any
    result: Any = None
    error: str | None = None
    tool_call_id: str | None = None
    side_effect: bool | None = None
    severity: Severity | None = None
    idempotency_key: str | None = None


class Deopt(_Event):
    """A compiled path handing control back to the original agent."""

    kind: Literal["deopt"] = "deopt"
    step_id: str
    guard_id: str | None = None
    reason: str
    resumed_at_event: str | None = None


Event = Annotated[ModelCall | ToolCall | Deopt, Field(discriminator="kind")]


class Run(_Model):
    """One end-to-end execution of a workflow."""

    schema_version: Literal[1] = 1
    run_id: str
    workflow_id: str
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    status: Literal["success", "error", "pending"]
    input: Any = None
    output: Any = None
    events: list[Event] = Field(default_factory=list)
    source: str
    tier: Literal[0, 1, 2] = 0
