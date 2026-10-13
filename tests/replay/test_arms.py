from typing import Any

import pytest

from anneal.replay.arms import ArmRun, Case, evaluate, render_markdown


def case(i: int, drift: str | None = None) -> Case:
    return Case(case_id=f"c{i}", input={"n": i}, drift=drift)


def check(c: Case, run: ArmRun) -> bool:
    return bool(run.output == c.input["n"] * 2)


def doubler(c: Case) -> ArmRun:
    return ArmRun(output=c.input["n"] * 2, cost_usd=0.01, model_calls=1)


def test_each_run_gets_an_outcome() -> None:
    def arm(c: Case) -> ArmRun:
        n = c.input["n"]
        if n == 1:
            return ArmRun(output=None, cost_usd=0.0, error="KeyError: email")
        if n == 2:
            return ArmRun(output=4, cost_usd=0.03, fell_back=True)
        if n == 3:
            return ArmRun(output=0, cost_usd=0.03, fell_back=True)
        if n == 4:
            raise RuntimeError("boom")
        return ArmRun(output=n * 2 if n == 0 else -1, cost_usd=0.01)

    report = evaluate([case(i) for i in range(6)], {"x": arm}, check)
    outcomes = {r.case_id: r.outcome for r in report.rows}
    assert outcomes == {
        "c0": "correct",
        "c1": "loud",
        "c2": "fallback",
        "c3": "fallback_wrong",
        "c4": "loud",
        "c5": "silent",
    }
    assert next(r for r in report.rows if r.case_id == "c4").error == "RuntimeError: boom"


def test_summary_per_arm_and_drift() -> None:
    def silent_on_drift(c: Case) -> ArmRun:
        return ArmRun(output=-1 if c.drift else c.input["n"] * 2, cost_usd=0.02, model_calls=2)

    cases = [case(i) for i in range(4)] + [case(i, "renamed_field") for i in range(4, 6)]
    report = evaluate(cases, {"good": doubler, "script": silent_on_drift}, check)
    good = report.summary("good", None)
    assert (good.cases, good.success_rate) == (4, 1.0)
    assert good.cost_per_task == pytest.approx(0.01)
    drifted = report.summary("script", "renamed_field")
    assert (drifted.silent, drifted.behaviour) == (2, "fails silently")
    assert report.summary("good", "renamed_field").behaviour == "handles it"
    assert report.drifts == ["renamed_field"]
    assert report.arms == ["good", "script"]


@pytest.mark.parametrize(
    ("outcomes", "behaviour"),
    [
        (["fallback", "fallback", "correct"], "falls back"),
        (["loud", "loud", "fallback"], "fails loudly"),
        (["silent", "loud", "loud"], "fails silently"),  # any silent failure is reported
        (["fallback_wrong", "fallback"], "fails silently"),
    ],
)
def test_behaviour_names_the_worst_mode_that_occurred(outcomes: list[str], behaviour: str) -> None:
    from anneal.replay.arms import behaviour_of

    assert behaviour_of(outcomes) == behaviour  # type: ignore[arg-type]


def test_markdown_has_the_three_arm_table() -> None:
    report = evaluate(
        [case(0), case(1, "new_enum")], {"tier0": doubler, "compiled": doubler}, check
    )
    text = render_markdown(report, build_time={"compiled": "4 s", "tier0": "n/a"})
    assert "| arm | build time | cost per task | task success | new_enum |" in text
    assert "| compiled | 4 s |" in text


def test_arm_inputs_are_isolated_copies() -> None:
    def mutating(c: Case) -> ArmRun:
        c.input["n"] = 99
        return ArmRun(output=0, cost_usd=0)

    cases = [case(1)]
    evaluate(cases, {"a": mutating, "b": doubler}, check)
    assert cases[0].input == {"n": 1}


# With an imperfect reference (a real model's Tier 0 is right 70-80% of the time)


def noisy(fail: set[int]) -> Any:
    """An arm that gets the cases in `fail` wrong, silently."""

    def arm(c: Case) -> ArmRun:
        n = c.input["n"]
        return ArmRun(output=-1 if n in fail else n * 2, cost_usd=0.01)

    return arm


def cases(n: int, drift: str | None, start: int = 0) -> list[Case]:
    return [case(i, drift) for i in range(start, start + n)]


def test_without_a_reference_any_silent_failure_labels_the_arm() -> None:
    all_cases = cases(20, None) + cases(20, "new_topic", 20)
    report = evaluate(all_cases, {"tier0": noisy({3, 25})}, check)
    assert report.summary("tier0", "new_topic").behaviour == "fails silently"


def test_reference_relative_scoring_ignores_cases_the_reference_got_wrong() -> None:
    tier0_wrong = {3, 7, 25, 31}  # the reference's own misses, holdout and drift
    all_cases = cases(20, None) + cases(20, "new_topic", 20)
    arms = {"tier0": noisy(tier0_wrong), "compiled": noisy(tier0_wrong | {5, 28})}
    report = evaluate(all_cases, arms, check, reference="tier0")
    drifted = report.summary("compiled", "new_topic")
    assert drifted.scored_cases == 18  # 20 minus the reference's two misses
    assert drifted.behaviour == "handles it"  # one regression on holdout, one on drift
    assert report.summary("tier0", "new_topic").behaviour == "handles it"


def test_a_drift_that_raises_silent_failures_by_ten_points_fails_silently() -> None:
    all_cases = cases(20, None) + cases(20, "new_topic", 20)
    arms = {"tier0": noisy(set()), "compiled": noisy({5, 21, 22, 23})}  # 5% vs 15%
    report = evaluate(all_cases, arms, check, reference="tier0")
    s = report.summary("compiled", "new_topic")
    assert s.silent_rate == pytest.approx(0.15)
    assert s.holdout_silent_rate == pytest.approx(0.05)
    assert s.behaviour == "fails silently"


def test_fallbacks_and_loud_failures_are_also_measured_against_the_holdout() -> None:
    def falls_back_on_drift(c: Case) -> ArmRun:
        return ArmRun(output=c.input["n"] * 2, cost_usd=0.01, fell_back=c.drift is not None)

    all_cases = cases(10, None) + cases(10, "new_enum", 10)
    report = evaluate(
        all_cases, {"tier0": doubler, "compiled": falls_back_on_drift}, check, reference="tier0"
    )
    assert report.summary("compiled", "new_enum").behaviour == "falls back"
    assert report.summary("compiled", None).behaviour == "handles it"


def test_markdown_explains_reference_relative_drift() -> None:
    all_cases = cases(4, None) + cases(4, "new_enum", 4)
    report = evaluate(all_cases, {"tier0": doubler, "compiled": doubler}, check, reference="tier0")
    text = render_markdown(report)
    assert "scored on the cases `tier0` got done" in text
    assert "| compiled | new_enum | 4 | 0% | 0% |" in text
