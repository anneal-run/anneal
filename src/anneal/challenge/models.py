"""Shared records for a v3 challenge. Holdout scores are not a field on a candidate."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from anneal.schema import Severity


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Observation(_Model):
    """One case scored for one arm. `mocked` means a tool on this case was served from a mock."""

    case_id: str
    correct: bool
    cost_usd: float
    latency_ms: float
    tools: list[str] = Field(default_factory=list)
    mocked: bool = False
    safety_ok: bool = True


class MeteredCall(_Model):
    """One model call the harness meter recorded. The orchestrator sums these."""

    cost_usd: float
    latency_ms: float


class Candidate(_Model):
    """A submission the orchestrator may score. Optimization cases only."""

    id: str
    arm: Literal["A", "B", "C", "control"]
    kind: Literal["structural", "prompt"]
    search_cost_usd: float = 0.0
    human_hours: float = 0.0
    calls: list[MeteredCall] = Field(default_factory=list)
    monthly_runs: int
    opt: list[Observation]
    new_side_effect_tools: list[str] = Field(default_factory=list)
    removed_approvals: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _positive_volume(self) -> "Candidate":
        if self.monthly_runs < 1:
            raise ValueError("monthly_runs must be at least 1")
        if "/" in self.id:
            raise ValueError("candidate id cannot contain '/'")
        return self

    def metered_usd(self) -> float:
        return sum(call.cost_usd for call in self.calls)


class ToolBinding(_Model):
    name: str
    mode: Literal["live", "recorded", "mock"]
    side_effect: bool
    severity: Severity
    recorded_calls: int = 0


class HarnessManifest(_Model):
    """Operator view. `proposer_payload` is what an arm is allowed to read."""

    workflow_id: str
    optimization_run_ids: list[str]
    holdout_run_ids: list[str]
    tools: list[ToolBinding]
    workflow_files: list[str]
    entrypoint: str | None
    mocked_tools: list[str]

    def proposer_payload(self) -> dict[str, object]:
        payload = self.model_dump()
        payload.pop("holdout_run_ids", None)
        return payload


class Verdict(_Model):
    """The three playbook verdicts, plus the numbers a reviewer needs to attack them."""

    compatible: bool
    correct: bool
    worth_it: bool
    cost_win: bool
    correctness_points: float
    correctness_low: float
    correctness_high: float
    mde_points: float
    cost_reduction: float
    noninferior_latency: bool
    noninferior_correctness: bool
    noninferiority_resolved: bool
    disqualified: list[str]
