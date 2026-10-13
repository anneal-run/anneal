import pytest

from anneal.classify import classify
from anneal.compile.compiler import compile_plan
from anneal.compile.plan import LlmStep, ToolStep
from anneal.replay.split import chronological_split
from synth.env import (
    DRIFTS,
    Env,
    Tier0Agent,
    generate_traces,
    make_customers,
    make_inputs,
    task_done,
)


def test_tier0_does_the_job_on_every_input_and_every_drift() -> None:
    customers = make_customers(30)
    for run_input in make_inputs(30):
        for variant in [run_input, *(drift(run_input) for drift in DRIFTS.values())]:
            env = Env(customers)
            answer, _, _ = Tier0Agent(env).run(variant)
            assert answer.startswith("Done:"), (variant, answer)
            assert task_done(variant, env.effects, customers), (variant, env.effects)


def test_task_check_rejects_missing_extra_and_wrong_writes() -> None:
    customers = make_customers(3)
    run_input = make_inputs(1)[0]
    env = Env(customers)
    Tier0Agent(env).run(run_input)
    good = env.effects
    assert task_done(run_input, good, customers)
    assert not task_done(run_input, good[:-1], customers)  # missing email
    assert not task_done(run_input, [*good, ("send_email", {"to": "x"})], customers)  # extra write
    wrong = [(n, {**a, "customer_id": "C-9999"} if n == "create_ticket" else a) for n, a in good]
    assert not task_done(run_input, wrong, customers)
    assert not task_done(DRIFTS["new_topic"](run_input), good, customers)  # a ticket is wrong here


def test_traces_compile_to_the_expected_plan_and_guards() -> None:
    runs, _ = generate_traces(80)
    compile_runs, _ = chronological_split(runs, 0.7)
    classes = {
        (c.depth, c.call_class) for c in classify(compile_runs).calls if c.depth in {0, 2, 4}
    }
    assert {(0, "removable"), (2, "constrained"), (4, "judgment")} <= classes
    result = compile_plan(compile_runs)
    assert result.plan is not None, result.log
    kinds = [
        (type(s).__name__, getattr(s, "name", None) or getattr(s, "forced_tool", None))
        for s in result.plan.steps
    ]
    assert kinds[:3] == [
        ("ToolStep", "lookup_customer"),
        ("LlmStep", "create_ticket"),
        ("ToolStep", "create_ticket"),
    ]
    guards = {g.id: g.params for g in result.plan.guards}
    # Mined from the dominant (auto_reply) path only: "high" always escalates, so a high-
    # priority input falls back at the guards instead of deopting at the routing step.
    assert guards["enum:input.priority"] == {"values": ["low", "normal"]}
    assert guards["pattern:input.email"] == {"class": "email"}
    assert any(isinstance(s, LlmStep) and s.expected_tool for s in result.plan.steps)
    assert all(s.side_effect for s in result.plan.steps if isinstance(s, ToolStep))  # undeclared


@pytest.mark.parametrize("name", list(DRIFTS))
def test_drifts_change_the_input(name: str) -> None:
    run_input = make_inputs(1)[0]
    assert DRIFTS[name](run_input) != run_input


def test_model_choose_answers_classification_questions_like_a_model_would() -> None:
    from synth.env import ModelCapabilities

    model = ModelCapabilities()
    cancel = {"message": "Please cancel my subscription, I no longer need it."}
    order = {"message": "My order 7 has a problem: wrong size"}
    labels = ["order_problem", "not_order_problem"]
    assert model.choose(labels, cancel) == "not_order_problem"
    assert model.choose(labels, order) == "order_problem"
    assert (
        model.choose(["auto_reply", "escalate"], {**order, "priority": "high", "tier": "x"})
        == "escalate"
    )
    assert (
        model.choose(["auto_reply", "escalate", "cancel_subscription"], cancel)
        == "cancel_subscription"
    )
