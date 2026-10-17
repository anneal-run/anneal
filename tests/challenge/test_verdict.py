"""Evaluator rules from the v3 playbook: holdout resolution, cost, mocks, overfit."""

from anneal.challenge.models import Observation
from anneal.challenge.verdict import judge

MARGIN_CASES = 40


def obs(
    case_id: str,
    *,
    correct: bool = True,
    cost: float = 0.0035,
    latency: float = 100.0,
    mocked: bool = False,
    safety: bool = True,
) -> Observation:
    return Observation(
        case_id=case_id,
        correct=correct,
        cost_usd=cost,
        latency_ms=latency,
        tools=["get_issue"],
        mocked=mocked,
        safety_ok=safety,
    )


def paired(
    n: int,
    *,
    cost: float,
    correct: bool = True,
    latency: float = 100.0,
    mocked: bool = False,
) -> list[Observation]:
    return [
        obs(f"case-{i:04d}", correct=correct, cost=cost, latency=latency, mocked=mocked)
        for i in range(n)
    ]


def test_cost_win_survives_a_tie_the_holdout_cannot_split() -> None:
    baseline = paired(MARGIN_CASES, cost=0.0035)
    candidate = paired(MARGIN_CASES, cost=0.0005)
    verdict = judge(
        baseline,
        candidate,
        search_cost_usd=0.50,
        monthly_runs=10_000,
        new_side_effect_tools=[],
        removed_approvals=[],
    )
    assert verdict.worth_it
    assert verdict.cost_win
    assert not verdict.correct
    assert verdict.mde_points > 2
    assert not verdict.noninferiority_resolved
    assert verdict.cost_reduction >= 0.30


def test_search_cost_that_does_not_pay_back_in_a_month_is_not_a_win() -> None:
    verdict = judge(
        paired(MARGIN_CASES, cost=0.0035),
        paired(MARGIN_CASES, cost=0.0005),
        search_cost_usd=0.50,
        monthly_runs=10,
        new_side_effect_tools=[],
        removed_approvals=[],
    )
    assert not verdict.cost_win
    assert not verdict.worth_it


def test_three_point_correctness_gap_does_not_clear_a_small_holdout() -> None:
    baseline = [obs(f"case-{i:04d}", correct=i >= 1) for i in range(MARGIN_CASES)]
    candidate = [obs(f"case-{i:04d}", correct=True) for i in range(MARGIN_CASES)]
    verdict = judge(
        baseline,
        candidate,
        search_cost_usd=0.0,
        monthly_runs=10_000,
        new_side_effect_tools=[],
        removed_approvals=[],
    )
    assert verdict.correctness_points == 2.5
    assert not verdict.correct
    assert verdict.mde_points > verdict.correctness_points


def test_large_correctness_gain_passes_when_the_interval_excludes_zero() -> None:
    baseline = [obs(f"case-{i:04d}", correct=i % 2 == 0, cost=0.0035) for i in range(MARGIN_CASES)]
    candidate = paired(MARGIN_CASES, cost=0.0035)
    verdict = judge(
        baseline,
        candidate,
        search_cost_usd=0.0,
        monthly_runs=10_000,
        new_side_effect_tools=[],
        removed_approvals=[],
    )
    assert verdict.correct
    assert verdict.worth_it
    assert verdict.correctness_low > 0


def test_gain_that_exists_only_on_mocked_tools_is_disqualified() -> None:
    baseline = [obs(f"case-{i:04d}", cost=0.0035, mocked=i < 30) for i in range(MARGIN_CASES)]
    candidate = [
        obs(f"case-{i:04d}", cost=0.0005 if i < 30 else 0.0035, mocked=i < 30)
        for i in range(MARGIN_CASES)
    ]
    verdict = judge(
        baseline,
        candidate,
        search_cost_usd=0.0,
        monthly_runs=10_000,
        new_side_effect_tools=[],
        removed_approvals=[],
    )
    assert "mock" in verdict.disqualified
    assert not verdict.worth_it


def test_opt_gain_that_vanishes_on_the_holdout_is_overfit() -> None:
    opt_base = paired(30, cost=0.0035)
    opt_cand = paired(30, cost=0.0005)
    hold_base = paired(30, cost=0.0035)
    hold_cand = paired(30, cost=0.0035)
    verdict = judge(
        hold_base,
        hold_cand,
        search_cost_usd=0.0,
        monthly_runs=10_000,
        new_side_effect_tools=[],
        removed_approvals=[],
        optimization=(opt_base, opt_cand),
    )
    assert "overfit" in verdict.disqualified
    assert not verdict.worth_it


def test_new_side_effect_tool_is_not_compatible() -> None:
    verdict = judge(
        paired(MARGIN_CASES, cost=0.0035),
        paired(MARGIN_CASES, cost=0.0005),
        search_cost_usd=0.0,
        monthly_runs=10_000,
        new_side_effect_tools=["post_comment"],
        removed_approvals=[],
    )
    assert not verdict.compatible
    assert not verdict.worth_it


def test_latency_regression_blocks_a_cost_win() -> None:
    verdict = judge(
        paired(MARGIN_CASES, cost=0.0035, latency=100),
        paired(MARGIN_CASES, cost=0.0005, latency=150),
        search_cost_usd=0.0,
        monthly_runs=10_000,
        new_side_effect_tools=[],
        removed_approvals=[],
    )
    assert not verdict.noninferior_latency
    assert not verdict.worth_it


def test_correctness_win_uses_the_ceiling_and_ignores_latency() -> None:
    baseline = paired(MARGIN_CASES, cost=0.0, correct=False, latency=1.0)
    candidate = paired(MARGIN_CASES, cost=0.01, correct=True, latency=1000.0)
    default = judge(
        baseline,
        candidate,
        search_cost_usd=0.0,
        monthly_runs=1,
        new_side_effect_tools=[],
        removed_approvals=[],
    )
    won = judge(
        baseline,
        candidate,
        search_cost_usd=0.0,
        monthly_runs=1,
        new_side_effect_tools=[],
        removed_approvals=[],
        mode="correctness_win",
        cost_ceiling=0.02,
    )
    assert default.worth_it is False
    assert won.correct is True
    assert won.worth_it is True
    assert won.noninferior_latency is False


def test_correctness_win_refuses_a_case_over_the_ceiling() -> None:
    verdict = judge(
        paired(MARGIN_CASES, cost=0.0, correct=False, latency=1.0),
        paired(MARGIN_CASES, cost=0.05, correct=True, latency=1000.0),
        search_cost_usd=0.0,
        monthly_runs=1,
        new_side_effect_tools=[],
        removed_approvals=[],
        mode="correctness_win",
        cost_ceiling=0.02,
    )
    assert verdict.correct is True
    assert verdict.worth_it is False
