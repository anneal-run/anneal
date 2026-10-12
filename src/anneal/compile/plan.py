"""`WorkflowPlan` v0 (CONTRACT, ANNEAL-ROADMAP.md M1.4) and the plan registry.

Contract fields: `plan_id` (content hash), `workflow_id`, `skeleton_hash`,
`compiled_from`, `steps`, `guards`, `side_effect_policy`, `tier`. Step types in
M1: `tool`, `llm` and a final `end`. Additive fields (ADR 0005): `LlmStep.role`
and `expected_tool`, `compile_log`, `manual_overrides`.
"""

import json
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Annotated, Any, Literal

import blake3
from pydantic import BaseModel, ConfigDict, Field, model_validator

from anneal.compile.template import references
from anneal.schema import Severity


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolStep(_Model):
    """Call a tool with templated arguments. Undeclared tools get the most cautious declaration."""

    kind: Literal["tool"] = "tool"
    id: str
    name: str
    args_template: Any
    side_effect: bool = True
    severity: Severity = "S2"
    idempotent: bool = False


class LlmStep(_Model):
    """Call a model for structured output; `forced_tool` is the tool whose arguments it writes."""

    kind: Literal["llm"] = "llm"
    id: str
    role: str
    model: str | None = None
    system_template: str
    user_template: str
    output_schema: dict[str, Any]
    forced_tool: str | None = None
    expected_tool: str | None = None
    """For a tool-choosing step: the tool on the compiled path; any other choice deopts."""


class EndStep(_Model):
    kind: Literal["end"] = "end"
    id: str = "end"
    output_template: Any


Step = Annotated[ToolStep | LlmStep | EndStep, Field(discriminator="kind")]


class Guard(_Model):
    id: str
    kind: Literal["schema", "enum", "range", "length", "pattern"]
    path: str
    """Template-style path under `input`, for example `input.email`."""
    params: dict[str, Any] = Field(default_factory=dict)


class ManualOverride(_Model):
    """A binding a human wrote because the compiler could not; automation debt for M2."""

    key: str
    template: Any
    reason: str


def _templates(step: ToolStep | LlmStep | EndStep) -> list[Any]:
    match step:
        case ToolStep():
            return [step.args_template]
        case LlmStep():
            return [step.system_template, step.user_template]
        case EndStep():
            return [step.output_template]


class WorkflowPlan(_Model):
    plan_version: Literal[0] = 0
    plan_id: str
    workflow_id: str
    skeleton_hash: str
    compiled_from: list[str]
    steps: list[Step]
    guards: list[Guard] = Field(default_factory=list)
    side_effect_policy: Literal["s0_live_only"] = "s0_live_only"
    tier: Literal[1] = 1
    compile_log: list[str] = Field(default_factory=list)
    manual_overrides: list[ManualOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_steps(self) -> "WorkflowPlan":
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("step ids must be unique")
        if not self.steps or not isinstance(self.steps[-1], EndStep):
            raise ValueError("the last step must be the end step")
        if any(isinstance(s, EndStep) for s in self.steps[:-1]):
            raise ValueError("only one end step, and it must be last")
        self.dependency_order()
        return self

    def dependencies(self) -> dict[str, set[str]]:
        """Step id to the step ids its templates read."""
        known = {s.id for s in self.steps}
        deps: dict[str, set[str]] = {}
        for step in self.steps:
            refs = set().union(*(references(t) for t in _templates(step)))
            if unknown := refs - known:
                raise ValueError(f"step {step.id} references unknown steps {sorted(unknown)}")
            deps[step.id] = refs
        return deps

    def dependency_order(self) -> list[str]:
        """Step ids in an order that satisfies every reference; ties keep plan order."""
        sorter = TopologicalSorter(self.dependencies())
        try:
            sorter.prepare()
        except CycleError as e:
            raise ValueError(f"steps reference each other in a cycle: {e.args[1]}") from None
        position = {s.id: i for i, s in enumerate(self.steps)}
        order: list[str] = []
        while sorter.is_active():
            ready = sorted(sorter.get_ready(), key=position.__getitem__)
            order += ready
            sorter.done(*ready)
        return order

    @staticmethod
    def content_hash(fields: dict[str, Any]) -> str:
        body = {k: v for k, v in fields.items() if k != "plan_id"}
        return blake3.blake3(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]

    @classmethod
    def build(cls, **fields: Any) -> "WorkflowPlan":
        """Validate `fields` and set `plan_id` to their content hash."""
        draft = cls.model_validate({**fields, "plan_id": "pending"})
        content = draft.model_dump(mode="json")
        return draft.model_copy(update={"plan_id": cls.content_hash(content)})


class PlanRegistry:
    """Plans on disk at `<root>/<workflow_id>/<plan_id>.json`."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def save(self, plan: WorkflowPlan) -> Path:
        folder = self.root / plan.workflow_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{plan.plan_id}.json"
        path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return path

    def load(self, workflow_id: str, plan_id: str) -> WorkflowPlan:
        path = self.root / workflow_id / f"{plan_id}.json"
        plan = WorkflowPlan.model_validate_json(path.read_text(encoding="utf-8"))
        if WorkflowPlan.content_hash(plan.model_dump(mode="json")) != plan.plan_id:
            raise ValueError(f"{path}: content hash does not match plan_id")
        return plan

    def list(self, workflow_id: str) -> list[str]:
        folder = self.root / workflow_id
        return sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []
