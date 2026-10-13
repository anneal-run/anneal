from typing import Any

import pytest

from anneal.replay.arms import ArmRow, ArmsReport, Outcome
from anneal.replay.replay import ReplayReport
from anneal.report.analyze import AnalyzeReport, ClassRow, ClusterRow
from anneal.report.memo import (
    DeoptTrial,
    FallbackReport,
    ManualStep,
    Memo,
    gate1,
    render_memo,
    repeated_spend_share,
)


def analyze_report(share: float, clusters: list[tuple[int, float]] | None = None) -> AnalyzeReport:
    return AnalyzeReport(
        workflow_id="wf",
        runs=10,
        model_calls=40,
        unknown_cost_calls=0,
        spend_usd=1.0,
        clusters=[
            ClusterRow(
                cluster_id=f"c{i}",
                runs=runs,
                run_share=runs / 10,
                spend_usd=spend,
                spend_share=spend,
                variants=1,
                steps=4,
            )
            for i, (runs, spend) in enumerate(clusters or [(10, 1.0)])
        ],
        by_class=[
            ClassRow(call_class="removable", calls=10, spend_usd=share, share=share),
            ClassRow(call_class="judgment", calls=30, spend_usd=1 - share, share=1 - share),
        ],
        positions=[],
        tier1_saving_usd=share,
        tier1_share=share,
        constrained_unmeasured_usd=0.0,
        min_support=5,
        stable_share=0.95,
    )


def replay_report(**overrides: Any) -> ReplayReport:
    fields: dict[str, Any] = {
        "workflow_id": "wf",
        "compiled": True,
        "plan_id": "p1",
        "compiled_from": [],
        "compile_log": [],
        "compile_runs": 70,
        "holdout_runs": 30,
        "llm_mode": "recorded",
        "task_check": "partner:check",
        "correct": 20,
        "fallback": 10,
        "wrong_by_severity": {"S0": 0, "S1": 0, "S2": 0},
        "wrong_rate_by_severity": {"S0": 0.0, "S1": 0.0, "S2": 0.0},
        "fallback_rate": 1 / 3,
        "tier0_success_rate": 1.0,
        "compiled_success_rate": 1.0,
        "accepted_success_rate": 1.0,
        "output_equivalence_rate": 1.0,
        "deopt_by_step": {},
        "divergence_by_step": {},
        "cost_per_run_tier0": 0.09,
        "cost_per_run_compiled": 0.05,
        "rows": [],
    }
    return ReplayReport(**{**fields, **overrides})


def fallback_report(passed: int = 20, total: int = 20) -> FallbackReport:
    return FallbackReport(
        framework="langgraph",
        trials=[
            DeoptTrial(
                run_id=f"r{i}",
                step_id=f"s{i % 4}",
                task_success=i < passed,
                repeated=[],
            )
            for i in range(total)
        ],
    )


def arms_report(
    compiled_cost: float = 0.05,
    baseline_cost: float = 0.0,
    compiled_drift: Outcome = "fallback",
    baseline_drift: Outcome = "silent",
) -> ArmsReport:
    rows = []
    for arm, cost, drifted in [
        ("compiled", compiled_cost, compiled_drift),
        ("baseline", baseline_cost, baseline_drift),
    ]:
        rows.append(ArmRow(case_id="c", drift=None, arm=arm, outcome="correct", cost_usd=cost))
        for d in ("new_enum", "renamed_field", "new_topic"):
            rows.append(ArmRow(case_id=f"c:{d}", drift=d, arm=arm, outcome=drifted, cost_usd=cost))
    return ArmsReport(
        rows=rows, arms=["compiled", "baseline"], drifts=["new_enum", "new_topic", "renamed_field"]
    )


def verdicts(**kwargs: Any) -> dict[str, str]:
    args: dict[str, Any] = {
        "holdout": analyze_report(0.5),
        "replay": replay_report(),
        "fallback": fallback_report(),
        "arms": arms_report(),
        "build_seconds": {"compiled": 600.0, "baseline": 8 * 3600.0},
    }
    gate = gate1(**{**args, **kwargs})
    return {c.id: c.verdict for c in gate.criteria} | {"gate": gate.verdict}


def test_everything_inside_the_thresholds_passes() -> None:
    assert verdicts() == {"H2": "pass", "H3": "pass", "fallback": "pass", "H4": "pass"} | {
        "gate": "passed"
    }


@pytest.mark.parametrize(
    ("share", "drift_won", "expected"),
    [
        (0.40, True, "pass"),
        (0.24, True, "stop"),
        (0.30, True, "pass"),  # between 25% and 40%: proceeds because drift was won
        (0.30, False, "stop"),
    ],
)
def test_h2_thresholds_and_the_drift_condition(
    share: float, drift_won: bool, expected: str
) -> None:
    arms = arms_report() if drift_won else arms_report(compiled_drift="silent")
    assert verdicts(holdout=analyze_report(share), arms=arms)["H2"] == expected


def test_any_stop_stops_the_gate() -> None:
    assert verdicts(holdout=analyze_report(0.1))["gate"] == "stop"


@pytest.mark.parametrize(
    "replay",
    [
        replay_report(compiled_success_rate=0.985),  # more than 1 point under Tier 0
        replay_report(wrong_by_severity={"S0": 0, "S1": 1, "S2": 0}),
        replay_report(wrong_rate_by_severity={"S0": 0.02, "S1": 0.0, "S2": 0.0}),
        replay_report(compiled=False),
    ],
)
def test_h3_fails_on_success_gap_writes_or_s0_budget(replay: ReplayReport) -> None:
    v = verdicts(replay=replay)
    assert v["H3"] == "fail"
    assert v["gate"] == "not passed"


def test_h3_allows_one_point_below_tier0() -> None:
    assert verdicts(replay=replay_report(compiled_success_rate=0.99))["H3"] == "pass"


def test_fallback_needs_twenty_of_twenty_without_repeats() -> None:
    assert verdicts(fallback=fallback_report(passed=19))["fallback"] == "fail"
    repeated = fallback_report()
    repeated.trials[3].repeated.append("create_ticket")
    assert verdicts(fallback=repeated)["fallback"] == "fail"
    assert verdicts(fallback=fallback_report(passed=12, total=12))["fallback"] == "open"
    assert verdicts(fallback=None)["fallback"] == "open"


def test_h4_is_won_by_any_one_of_build_time_cost_or_drift() -> None:
    lost_drift = arms_report(compiled_drift="silent")
    expensive = arms_report(compiled_cost=0.1, baseline_cost=0.0, compiled_drift="silent")
    slow = {"compiled": 5 * 3600.0, "baseline": 8 * 3600.0}
    assert verdicts(arms=lost_drift)["H4"] == "pass"  # build time alone; cost and drift lost
    assert verdicts(arms=expensive)["H4"] == "pass"  # build time alone, again
    assert verdicts(arms=expensive, build_seconds=slow)["H4"] == "stop"  # script wins all three
    assert verdicts(arms=arms_report(compiled_cost=0.1), build_seconds=slow)["H4"] == "pass"


def test_h4_drift_counts_only_where_the_script_needs_a_patch() -> None:
    both_fine = arms_report(compiled_cost=0.1, compiled_drift="fallback", baseline_drift="correct")
    slow = {"compiled": 5 * 3600.0, "baseline": 8 * 3600.0}
    assert verdicts(arms=both_fine, build_seconds=slow)["H4"] == "stop"
    loud_script = arms_report(compiled_cost=0.1, baseline_drift="loud")
    assert verdicts(arms=loud_script, build_seconds=slow)["H4"] == "pass"


def test_unmeasured_build_time_leaves_h4_open_unless_another_part_wins() -> None:
    expensive = arms_report(compiled_cost=0.1, compiled_drift="silent")
    unknown = {"compiled": None, "baseline": 106.0}
    v = verdicts(arms=expensive, build_seconds=unknown)
    assert (v["H4"], v["gate"]) == ("open", "incomplete")
    assert verdicts(arms=arms_report(), build_seconds=unknown)["H4"] == "pass"


def test_missing_arms_leave_h4_open() -> None:
    assert verdicts(arms=None)["H4"] == "open"


def test_repeated_spend_share_counts_clusters_with_enough_support() -> None:
    report = analyze_report(0.5, clusters=[(7, 0.6), (2, 0.3), (1, 0.1)])
    assert repeated_spend_share(report) == pytest.approx(0.6)


def test_memo_renders_every_section_and_the_synthetic_banner() -> None:
    memo = Memo(
        workflow_id="wf",
        synthetic=True,
        source="simulated environment",
        analyze_all=analyze_report(0.5),
        analyze_holdout=analyze_report(0.5),
        replay=replay_report(),
        fallback=fallback_report(),
        arms=arms_report(),
        build_seconds={"compiled": None, "baseline": 106.0},
        build_notes={"compiled": "0.02 s compute; human setup not timed"},
        manual_steps=[
            ManualStep(step="Declared 5 tools", why="M1 has no inference", automate_in="M2")
        ],
        open_items=["Written task-check agreement with a partner"],
    )
    text = render_memo(memo)
    assert text.startswith("# Milestone 1 memo: wf")
    assert "SYNTHETIC" in text
    for heading in [
        "## Gate 1",
        "## H1, H2: where the spend is",
        "## H3: chronological replay",
        "## Fallback",
        "## H4: against the handwritten baseline",
        "## Manual steps",
        "## Hypotheses register",
        "## Open items",
    ]:
        assert heading in text, heading
    assert "| H2 | pass |" in text
    assert "Declared 5 tools" in text
    assert "20 of 20" in text


def test_real_memo_has_no_synthetic_banner() -> None:
    memo = Memo(
        workflow_id="wf",
        synthetic=False,
        source="partner export",
        analyze_all=analyze_report(0.5),
        analyze_holdout=analyze_report(0.5),
        replay=replay_report(),
    )
    assert "SYNTHETIC" not in render_memo(memo)


def test_h3_is_open_when_the_compiled_path_never_finished_a_run() -> None:
    """With every holdout run falling back, compiled success equals Tier 0's by
    construction: that is no evidence for H3 (found in the dogfood run, 60 of 60)."""
    replay = replay_report(correct=0, fallback=30, fallback_rate=1.0, accepted_success_rate=None)
    v = verdicts(replay=replay)
    assert v["H3"] == "open"
    gate = gate1(
        holdout=analyze_report(0.5),
        replay=replay,
        fallback=fallback_report(),
        arms=arms_report(),
        build_seconds={"compiled": 600.0, "baseline": 8 * 3600.0},
    )
    assert "no holdout run finished on the compiled path" in gate.criteria[1].measured
