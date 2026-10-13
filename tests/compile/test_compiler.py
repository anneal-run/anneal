import functools
from datetime import UTC, datetime, timedelta
from typing import Any

from synth.generator import generate

from anneal.compile.compiler import ToolSpec, compile_plan
from anneal.compile.plan import EndStep, LlmStep, ToolStep, WorkflowPlan
from anneal.schema import Event, ModelCall, Run, ToolCall, ToolCallRequest

T0 = datetime(2026, 10, 1, tzinfo=UTC)


@functools.cache
def _default_plan() -> WorkflowPlan:
    runs, _ = generate(seed=0)
    result = compile_plan(runs)
    assert result.plan is not None, result.log
    return result.plan


def synth_plan(**kw: Any) -> WorkflowPlan:
    if not kw:
        return _default_plan()
    runs, _ = generate(seed=0)
    result = compile_plan(runs, **kw)
    assert result.plan is not None, result.log
    return result.plan


def shape_of(plan: WorkflowPlan) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for s in plan.steps:
        match s:
            case ToolStep():
                out.append(("tool", s.name))
            case LlmStep():
                out.append(("llm", s.forced_tool or s.expected_tool))
            case EndStep():
                out.append(("end", None))
    return out


def test_dominant_path_compiles_to_the_expected_steps() -> None:
    plan = synth_plan()
    assert shape_of(plan) == [
        ("tool", "lookup_customer"),
        ("llm", "create_ticket"),
        ("tool", "create_ticket"),
        ("llm", "auto_reply"),
        ("tool", "auto_reply"),
        ("llm", None),
        ("llm", "send_email"),
        ("tool", "send_email"),
        ("llm", None),
        ("end", None),
    ]
    assert [s.id for s in plan.steps] == [f"s{i}" for i in range(9)] + ["end"]


def step(plan: WorkflowPlan, step_id: str) -> Any:
    return next(s for s in plan.steps if s.id == step_id)


def test_removable_call_becomes_a_templated_tool_step() -> None:
    assert step(synth_plan(), "s0").args_template == {"email": "{{input.email}}", "include": "tier"}


def test_constrained_call_asks_only_for_model_written_arguments() -> None:
    plan = synth_plan()
    llm, tool = step(plan, "s1"), step(plan, "s2")
    assert llm.forced_tool == "create_ticket"
    assert llm.output_schema == {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    assert tool.args_template == {
        "customer_id": "{{steps.s0.result.customer_id}}",
        "summary": "{{steps.s1.result.summary}}",
    }


def test_tool_choice_step_names_the_compiled_branch() -> None:
    plan = synth_plan()
    choose, tool = step(plan, "s3"), step(plan, "s4")
    assert choose.expected_tool == "auto_reply" and choose.forced_tool is None
    assert choose.output_schema["properties"]["tool"] == {"enum": ["auto_reply", "escalate"]}
    assert tool.args_template == "{{steps.s3.result.arguments}}"


def test_llm_steps_see_the_input_and_earlier_results() -> None:
    send = step(synth_plan(), "s6")
    assert "{{input}}" in send.user_template
    assert "{{steps.s5.result}}" in send.user_template  # the draft it must copy
    assert send.model == "gpt-4o-mini"


def test_end_step_reads_the_terminal_output() -> None:
    assert step(synth_plan(), "end").output_template == {"answer": "{{steps.s8.result.text}}"}


def test_compiled_from_is_the_runs_on_the_dominant_path() -> None:
    runs, _ = generate(seed=0)
    plan = synth_plan()
    routes = {r.run_id: [e.name for e in r.events if isinstance(e, ToolCall)] for r in runs}
    expected = sorted(
        rid
        for rid, tools in routes.items()
        if tools == ["lookup_customer", "create_ticket", "auto_reply", "send_email"]
    )
    assert plan.compiled_from == expected


def test_tool_declarations_and_cautious_defaults() -> None:
    lookup = ToolSpec(side_effect=False, severity="S0", idempotent=True)
    plan = synth_plan(tools={"lookup_customer": lookup})
    assert (step(plan, "s0").severity, step(plan, "s2").severity) == ("S0", "S2")
    assert any("create_ticket" in line and "undeclared" in line for line in plan.compile_log)


def test_guards_cover_every_input_field_when_llm_steps_read_the_whole_input() -> None:
    guards = {g.id: g for g in synth_plan().guards}
    assert set(guards) == {"schema:input.email", "pattern:input.email", "schema:input.message"}
    assert guards["schema:input.email"].params == {"type": "string"}
    assert guards["schema:input.message"].params == {"type": "string"}
    assert guards["pattern:input.email"].params == {"class": "email"}


def test_enum_range_and_pattern_guards_are_mined_from_the_compile_runs() -> None:
    def make_input(i: int) -> dict[str, Any]:
        return {
            "id": f"ID-{i:05d}",
            "priority": ["low", "normal", "high"][i % 3],
            "qty": 10 + i,
            "ref": f"3f2b8c1e-9a4d-4e2b-8f1a-{i:012d}",
        }

    runs = simple_runs(
        30, make_input, lambda i: {"id": f"ID-{i:05d}"}
    )  # the final llm step reads all
    result = compile_plan(runs)
    assert result.plan is not None
    guards = {g.id: g.params for g in result.plan.guards}
    assert guards["enum:input.priority"] == {"values": ["high", "low", "normal"]}
    assert guards["range:input.qty"] == {"min": 7.1, "max": 41.9}  # widened 10% of the span
    assert guards["pattern:input.ref"] == {"class": "uuid"}
    assert "enum:input.id" not in guards  # identifiers are not enums


def test_compiling_is_deterministic() -> None:
    runs, _ = generate(seed=0)
    first, second = compile_plan(runs).plan, compile_plan(runs).plan
    assert first is not None and second is not None and first.plan_id == second.plan_id


# Refusals and manual overrides


def amount_runs(n: int = 10) -> list[Run]:
    runs = []
    for i in range(n):
        args = {"amount": 1000.5 + i, "ref": f"REF-{i:05d}"}
        events: list[Event] = [
            ModelCall(
                event_id=f"r{i}-m",
                ts=T0,
                scope="a",
                tool_calls_requested=[ToolCallRequest(id="c", name="pay", args=args)],
            ),
            ToolCall(
                event_id=f"r{i}-t", ts=T0, name="pay", args=args, result={"ok": 1}, tool_call_id="c"
            ),
            ModelCall(event_id=f"r{i}-f", ts=T0, scope="a", output_text=f"paid {i}"),
        ]
        runs.append(
            Run(
                run_id=f"r{i}",
                workflow_id="wf",
                started_at=T0 + timedelta(minutes=i),
                status="success",
                input={"amount": f"{1000.5 + i:,.2f}", "ref": f"REF-{i:05d}"},
                output=f"paid {i}",
                events=events,
                source="t",
            )
        )
    return runs


def test_inexpressible_binding_is_refused_and_logged() -> None:
    result = compile_plan(amount_runs())
    assert result.plan is not None
    assert shape_of(result.plan)[:2] == [("llm", "pay"), ("tool", "pay")]
    llm = result.plan.steps[0]
    assert isinstance(llm, LlmStep) and list(llm.output_schema["properties"]) == ["amount"]
    assert result.plan.steps[1].args_template == {  # type: ignore[union-attr]
        "amount": "{{steps.s0.result.amount}}",
        "ref": "{{input.ref}}",
    }
    assert any(
        "refused" in line and "pay:$.amount" in line and "number" in line for line in result.log
    )


def test_manual_override_replaces_a_refused_binding_and_is_recorded() -> None:
    first = compile_plan(amount_runs())
    assert first.plan is not None
    position = next(line.split()[2] for line in first.log if "refused" in line)
    key = f"{position}:pay:$.amount"
    result = compile_plan(amount_runs(), overrides={key: "{{input.amount_num}}"})
    assert result.plan is not None
    assert shape_of(result.plan)[0] == ("tool", "pay")
    assert result.plan.steps[0].args_template["amount"] == "{{input.amount_num}}"  # type: ignore[union-attr]
    (manual,) = result.plan.manual_overrides
    assert manual.key == key and "number" in manual.reason


def test_too_little_support_on_the_dominant_path_compiles_nothing() -> None:
    result = compile_plan(amount_runs(3))
    assert result.plan is None
    assert any("support" in line for line in result.log)


def simple_runs(
    n: int,
    make_input: Any,
    make_args: Any,
    make_output: Any = lambda i: f"done {i}",
    requested: bool = True,
    system: Any = lambda i: "be brief",
) -> list[Run]:
    runs = []
    for i in range(n):
        args = make_args(i)
        events: list[Event] = []
        if requested:
            events.append(
                ModelCall(
                    event_id=f"r{i}-m",
                    ts=T0,
                    scope="a",
                    messages=[{"role": "system", "content": system(i)}],  # type: ignore[list-item]
                    tool_calls_requested=[ToolCallRequest(id="c", name="t", args=args)],
                )
            )
        events += [
            ToolCall(
                event_id=f"r{i}-t",
                ts=T0,
                name="t",
                args=args,
                result={"ok": 1},
                tool_call_id="c" if requested else None,
            ),
            ModelCall(event_id=f"r{i}-f", ts=T0, scope="a", output_text=f"done {i}"),
        ]
        runs.append(
            Run(
                run_id=f"r{i}",
                workflow_id="wf",
                started_at=T0 + timedelta(minutes=i),
                status="success",
                input=make_input(i),
                output=make_output(i),
                events=events,
                source="t",
            )
        )
    return runs


def first_tool_args(runs: list[Run], **kw: Any) -> Any:
    result = compile_plan(runs, **kw)
    assert result.plan is not None, result.log
    step0 = result.plan.steps[0]
    assert isinstance(step0, ToolStep), result.log
    return step0.args_template


def test_expressible_transforms_become_template_filters() -> None:
    runs = simple_runs(
        8,
        lambda i: {
            "name": f"  Person{i} ",
            "first": f"Ann{i}",
            "last": f"Lee{i}",
            "when": f"Oct {i + 10}, 2026",
        },
        lambda i: {
            "name": f"person{i}",
            "full": f"Ann{i} Lee{i}",
            "date": f"2026-10-{i + 10}",
        },
    )
    assert first_tool_args(runs) == {
        "name": "{{input.name | trim | lower}}",
        "full": "{{concat(input.first, input.last, sep=' ')}}",
        "date": "{{input.when | fmt_date('%Y-%m-%d')}}",
    }


def test_inconsistent_binding_is_refused_and_asked_of_the_model() -> None:
    runs = simple_runs(
        10,
        lambda i: {"a" if i % 2 else "b": f"KEY-{i:05d}"},
        lambda i: {"key": f"KEY-{i:05d}"},
    )
    result = compile_plan(runs)
    assert result.plan is not None
    assert isinstance(result.plan.steps[0], LlmStep)
    assert any("refused" in line and "inconsistent" in line for line in result.log)


def test_varying_system_prompt_is_logged() -> None:
    runs = simple_runs(
        8,
        lambda i: {"k": "x"},
        lambda i: {"note": f"n{i}"},
        system=lambda i: f"today is day {i % 2}",
    )
    result = compile_plan(runs)
    assert any("system prompt varies" in line for line in result.log)


def test_unreproducible_output_compiles_nothing() -> None:
    runs = simple_runs(
        8,
        lambda i: {"k": f"K-{i:05d}"},
        lambda i: {"k": f"K-{i:05d}"},
        make_output=lambda i: f"random {i * 7919}",
    )
    result = compile_plan(runs)
    assert result.plan is None
    assert any("output" in line and "not reproducible" in line for line in result.log)


def test_unrequested_tool_call_compiles_nothing() -> None:
    runs = simple_runs(
        8, lambda i: {"k": f"K-{i:05d}"}, lambda i: {"k": f"K-{i:05d}"}, requested=False
    )
    result = compile_plan(runs)
    assert result.plan is None
    assert any("not requested by a model call" in line for line in result.log)


def test_llm_steps_record_their_source_position() -> None:
    runs, _ = generate(seed=0)
    from anneal.classify import classify

    positions = {p.position_id for p in classify(runs).positions}
    llm_steps = [s for s in synth_plan().steps if isinstance(s, LlmStep)]
    assert all(s.position_id in positions for s in llm_steps)
    assert len({s.position_id for s in llm_steps}) == len(llm_steps)


def parallel_runs(n: int = 10) -> list[Run]:
    """A model asks for two tools at once and writes both calls' arguments itself (as the
    triage agent does with get_issue and list_labels, reading them out of free text)."""
    runs = []
    for i in range(n):
        a_args, b_args = {"number": 100 + i}, {"repo": f"org/r{i % 3}x"}
        events: list[Event] = [
            ModelCall(
                event_id=f"r{i}-m",
                ts=T0,
                scope="a",
                tool_calls_requested=[
                    ToolCallRequest(id="ca", name="get_issue", args=a_args),
                    ToolCallRequest(id="cb", name="list_labels", args=b_args),
                ],
            ),
            ToolCall(
                event_id=f"r{i}-ta",
                ts=T0,
                name="get_issue",
                args=a_args,
                result={"ok": 1},
                tool_call_id="ca",
            ),
            ToolCall(
                event_id=f"r{i}-tb",
                ts=T0,
                name="list_labels",
                args=b_args,
                result=[],
                tool_call_id="cb",
            ),
            ModelCall(event_id=f"r{i}-f", ts=T0, scope="a", output_text=f"done {i}"),
        ]
        runs.append(
            Run(
                run_id=f"r{i}",
                workflow_id="wf",
                started_at=T0 + timedelta(minutes=i),
                status="success",
                input={"text": f"Please look at issue {100 + i}, it is broken"},
                output=f"done {i}",
                events=events,
                source="t",
            )
        )
    return runs


def test_parallel_calls_with_model_written_arguments_get_one_forced_step_each() -> None:
    result = compile_plan(parallel_runs())
    assert result.plan is not None, result.log
    assert shape_of(result.plan)[:4] == [
        ("llm", "get_issue"),
        ("tool", "get_issue"),
        ("llm", "list_labels"),
        ("tool", "list_labels"),
    ]
    assert any("one forced llm step per tool" in line for line in result.log)
