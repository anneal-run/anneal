from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from anneal.compile.plan import EndStep, LlmStep, PlanRegistry, ToolStep, WorkflowPlan


def steps(**overrides: Any) -> list[Any]:
    return [
        ToolStep(id="s0", name="lookup", args_template={"email": "{{input.email}}"}),
        LlmStep(
            id="s1",
            role="agent",
            system_template="be brief",
            user_template="customer {{steps.s0.result}}",
            output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        ),
        EndStep(output_template={"answer": "{{steps.s1.result.text}}"}),
    ]


def plan(**overrides: Any) -> WorkflowPlan:
    fields: dict[str, Any] = {
        "workflow_id": "wf",
        "skeleton_hash": "abc",
        "compiled_from": ["r1", "r2"],
        "steps": steps(),
    }
    return WorkflowPlan.build(**(fields | overrides))


def test_plan_id_is_a_content_hash() -> None:
    a, b = plan(), plan()
    assert a.plan_id == b.plan_id and len(a.plan_id) == 16
    assert plan(compiled_from=["r1"]).plan_id != a.plan_id


def test_tool_steps_default_to_the_most_cautious_declaration() -> None:
    step = ToolStep(id="s", name="t", args_template={})
    assert (step.side_effect, step.severity, step.idempotent) == (True, "S2", False)


def test_plan_defaults() -> None:
    p = plan()
    assert (p.tier, p.side_effect_policy, p.guards, p.manual_overrides) == (
        1,
        "s0_live_only",
        [],
        [],
    )


@pytest.mark.parametrize(
    "bad_steps",
    [
        [EndStep(output_template="{{steps.s9.result}}")],  # unknown step
        [
            ToolStep(id="s0", name="t", args_template="{{steps.s0.result}}"),
            EndStep(output_template=1),
        ],
        [
            ToolStep(id="s0", name="t", args_template={}),
            ToolStep(id="s0", name="u", args_template={}),
        ],
        [ToolStep(id="s0", name="t", args_template={})],  # no end step
        [EndStep(output_template=1), ToolStep(id="s0", name="t", args_template={})],  # end not last
        [
            ToolStep(id="s0", name="t", args_template="{{input.x | upper}}"),
            EndStep(output_template=1),
        ],
    ],
)
def test_invalid_plans_are_rejected(bad_steps: list[Any]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        plan(steps=bad_steps)


def test_registry_round_trip_and_layout(tmp_path: Path) -> None:
    registry = PlanRegistry(tmp_path)
    p = plan()
    path = registry.save(p)
    assert path == tmp_path / "wf" / f"{p.plan_id}.json"
    assert registry.load("wf", p.plan_id) == p
    assert registry.list("wf") == [p.plan_id]
    assert registry.list("missing") == []


def test_registry_rejects_a_tampered_plan(tmp_path: Path) -> None:
    registry = PlanRegistry(tmp_path)
    p = plan()
    path = registry.save(p)
    path.write_text(path.read_text().replace('"r2"', '"r3"'))
    with pytest.raises(ValueError, match="content hash"):
        registry.load("wf", p.plan_id)
