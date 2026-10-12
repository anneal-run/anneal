import re
from datetime import UTC, datetime
from typing import Any

from anneal.canon.shape import shape, shape_hash
from anneal.canon.skeleton import cluster_runs, skeleton, skeleton_hash
from anneal.schema import Event, ModelCall, Run, ToolCall, ToolCallRequest

T0 = datetime(2026, 10, 12, tzinfo=UTC)


def model(n: int, calls: list[str] = (), text: str = "", scope: str | None = "agent") -> ModelCall:  # type: ignore[assignment]
    return ModelCall(
        event_id=f"m{n}",
        ts=T0,
        scope=scope,
        output_text=text,
        tool_calls_requested=[ToolCallRequest(name=c, args={}) for c in calls],
    )


def tool(n: int, name: str, args: Any, result: Any = None, error: str | None = None) -> ToolCall:
    return ToolCall(event_id=f"t{n}", ts=T0, name=name, args=args, result=result, error=error)


def run(run_id: str, events: list[Event]) -> Run:
    return Run(
        run_id=run_id, workflow_id="wf", started_at=T0, status="success", events=events, source="t"
    )


def lookup_flow(run_id: str, email: str, tier: str) -> Run:
    return run(
        run_id,
        [
            model(0, ["lookup"]),
            tool(1, "lookup", {"email": email}, {"tier": tier}),
            model(2, text=f"You are {tier}."),
        ],
    )


def test_steps_name_tools_and_model_roles_with_coarse_shape_hashes() -> None:
    steps = skeleton(lookup_flow("a", "<EMAIL_1>", "gold"))
    assert steps == (
        ("model", "agent", "", "calls:lookup"),
        (
            "tool",
            "lookup",
            shape_hash(shape({"email": "<EMAIL_9>"}, coarse=True)),
            shape_hash("{tier:str}"),
        ),
        ("model", "agent", "", "text"),
    )


def test_model_role_falls_back_to_system_hash() -> None:
    call = model(0, scope=None).model_copy(update={"system_hash": "abc"})
    assert skeleton(run("a", [call]))[0][1] == "sys:abc"
    assert skeleton(run("b", [model(0, scope=None)]))[0][1] == "model"


def test_tool_errors_have_their_own_result_token() -> None:
    steps = skeleton(run("a", [tool(0, "t", {}, error="boom")]))
    assert steps[0][3] == "error"


def test_same_structure_different_values_same_hash() -> None:
    a = skeleton_hash(skeleton(lookup_flow("a", "<EMAIL_1>", "gold")))
    b = skeleton_hash(skeleton(lookup_flow("b", "<EMAIL_1>", "a much longer tier name here")))
    assert a == b
    assert re.fullmatch(r"[0-9a-f]{64}", a)


def test_different_order_different_hash() -> None:
    x = run("x", [tool(0, "a", {}), tool(1, "b", {})])
    y = run("y", [tool(0, "b", {}), tool(1, "a", {})])
    assert skeleton_hash(skeleton(x)) != skeleton_hash(skeleton(y))


def chain(run_id: str, names: list[str]) -> Run:
    return run(run_id, [tool(i, n, {}) for i, n in enumerate(names)])


def test_clusters_group_exact_and_near_duplicates() -> None:
    base = [f"s{i}" for i in range(19)]
    runs = [
        chain("a1", base),
        chain("a2", base),
        chain("a3", [*base, "extra"]),  # 19 vs 20 steps: ratio 0.97
        chain("b1", ["x", "y"]),
    ]
    clusters = cluster_runs(runs)
    assert [c.run_ids for c in clusters] == [["a1", "a2", "a3"], ["b1"]]
    big = clusters[0]
    assert big.skeleton == skeleton(runs[0])  # most common member skeleton represents it
    assert big.cluster_id == skeleton_hash(big.skeleton)
    assert len(big.skeleton_hashes) == 2


def test_near_duplicate_joining_is_transitive() -> None:
    base = [f"s{i}" for i in range(18)]
    runs = [
        chain("a", base),
        chain("b", [*base, "p"]),
        chain("c", [*base, "p", "q"]),
        chain("d", ["only"]),
    ]
    clusters = cluster_runs(runs, threshold=0.96)
    # a~b: 2*18/37=0.973, b~c: 2*19/39=0.974, a~c: 2*18/38=0.947 < 0.96
    assert [c.run_ids for c in clusters] == [["a", "b", "c"], ["d"]]


def test_dissimilar_runs_stay_apart() -> None:
    clusters = cluster_runs([chain("a", ["x", "y", "z"]), chain("b", ["x", "y", "w"])])
    assert len(clusters) == 2


def test_deopts_are_not_structure_and_silent_models_are_empty() -> None:
    from anneal.schema import Deopt

    deopt = Deopt(event_id="d", ts=T0, step_id="s", reason="r")
    assert skeleton(run("a", [model(0), deopt])) == (("model", "agent", "", "empty"),)
