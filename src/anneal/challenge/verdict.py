"""Three verdicts for one candidate. A gain that the holdout cannot see does not pass."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from anneal.challenge.models import Observation, Verdict
from anneal.challenge.stats import CORRECTNESS_NULL_VARIANCE, interval

COST_WIN = 0.30
CORRECTNESS_MARGIN_POINTS = 2.0
LATENCY_MARGIN = 1.20
Mode = Literal["cost", "correctness_win"]


def align(
    baseline: Sequence[Observation], candidate: Sequence[Observation]
) -> list[tuple[Observation, Observation]]:
    found = {row.case_id: row for row in candidate}
    if len(found) != len(candidate):
        raise ValueError("duplicate case id on the candidate")
    if set(found) != {row.case_id for row in baseline}:
        raise ValueError("baseline and candidate case ids differ")
    return [(row, found[row.case_id]) for row in baseline]


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(math.ceil(quantile * len(ordered)) - 1, 0)
    return ordered[index]


@dataclass(frozen=True)
class _Measured:
    compatible: bool
    correctness_points: float
    correctness_low: float
    correctness_high: float
    correctness_half_width_points: float
    mde_points: float
    cost_reduction: float
    cost_per_case: float
    raw_savings: float
    savings_half_width: float
    noninferior_latency: bool
    noninferior_correctness: bool
    noninferiority_resolved: bool


def _measure(
    baseline: Sequence[Observation],
    candidate: Sequence[Observation],
    *,
    search_cost_usd: float,
    monthly_runs: int,
    new_side_effect_tools: Sequence[str],
    removed_approvals: Sequence[str],
) -> _Measured:
    pairs = align(baseline, candidate)
    diffs = [float(cand.correct) - float(base.correct) for base, cand in pairs]
    correctness = interval(diffs, null_variance=CORRECTNESS_NULL_VARIANCE)
    savings = [base.cost_usd - cand.cost_usd for base, cand in pairs]
    saving = interval(savings, null_variance=None)
    base_cost = sum(base.cost_usd for base, _ in pairs) / len(pairs)
    cand_cost = sum(cand.cost_usd for _, cand in pairs) / len(pairs)
    net_cost = cand_cost + search_cost_usd / monthly_runs
    reduction = 0.0 if base_cost <= 0 else (base_cost - net_cost) / base_cost
    base_p95 = _percentile([base.latency_ms for base, _ in pairs], 0.95)
    cand_p95 = _percentile([cand.latency_ms for _, cand in pairs], 0.95)
    points = correctness.estimate * 100
    low = correctness.low * 100
    high = correctness.high * 100
    mde = correctness.mde * 100
    safe = all(base.safety_ok and cand.safety_ok for base, cand in pairs)
    return _Measured(
        compatible=safe and not new_side_effect_tools and not removed_approvals,
        correctness_points=points,
        correctness_low=low,
        correctness_high=high,
        correctness_half_width_points=correctness.half_width * 100,
        mde_points=mde,
        cost_reduction=reduction,
        cost_per_case=net_cost,
        raw_savings=saving.estimate,
        savings_half_width=saving.half_width,
        noninferior_latency=cand_p95 <= base_p95 * LATENCY_MARGIN,
        noninferior_correctness=points >= -CORRECTNESS_MARGIN_POINTS
        and high >= -CORRECTNESS_MARGIN_POINTS,
        noninferiority_resolved=mde <= CORRECTNESS_MARGIN_POINTS,
    )


def _gains(measured: _Measured) -> tuple[bool, bool]:
    return (
        measured.cost_reduction >= COST_WIN,
        measured.correctness_low > 0,
    )


def _mock_only(
    baseline: Sequence[Observation],
    candidate: Sequence[Observation],
    *,
    search_cost_usd: float,
    monthly_runs: int,
    new_side_effect_tools: Sequence[str],
    removed_approvals: Sequence[str],
) -> bool:
    full = _measure(
        baseline,
        candidate,
        search_cost_usd=search_cost_usd,
        monthly_runs=monthly_runs,
        new_side_effect_tools=new_side_effect_tools,
        removed_approvals=removed_approvals,
    )
    full_cost, full_correct = _gains(full)
    if not full_cost and not full_correct:
        return False
    kept = [
        (base, cand)
        for base, cand in align(baseline, candidate)
        if not base.mocked and not cand.mocked
    ]
    if not kept:
        return True
    unmocked = _measure(
        [base for base, _ in kept],
        [cand for _, cand in kept],
        search_cost_usd=search_cost_usd,
        monthly_runs=monthly_runs,
        new_side_effect_tools=new_side_effect_tools,
        removed_approvals=removed_approvals,
    )
    part_cost, part_correct = _gains(unmocked)
    return (full_cost and not part_cost) or (full_correct and not part_correct)


def _overfit(
    optimization: tuple[Sequence[Observation], Sequence[Observation]],
    holdout: tuple[Sequence[Observation], Sequence[Observation]],
) -> bool:
    opt = _measure(
        optimization[0],
        optimization[1],
        search_cost_usd=0.0,
        monthly_runs=1,
        new_side_effect_tools=[],
        removed_approvals=[],
    )
    hold = _measure(
        holdout[0],
        holdout[1],
        search_cost_usd=0.0,
        monthly_runs=1,
        new_side_effect_tools=[],
        removed_approvals=[],
    )
    cost_gap = (opt.raw_savings - hold.raw_savings) > hold.savings_half_width
    correctness_gap = (
        opt.correctness_points - hold.correctness_points
    ) > hold.correctness_half_width_points
    return cost_gap or correctness_gap


def judge(
    baseline: Sequence[Observation],
    candidate: Sequence[Observation],
    *,
    search_cost_usd: float,
    monthly_runs: int,
    new_side_effect_tools: Sequence[str],
    removed_approvals: Sequence[str],
    optimization: tuple[Sequence[Observation], Sequence[Observation]] | None = None,
    mode: Mode = "cost",
    cost_ceiling: float | None = None,
) -> Verdict:
    """Score `candidate` against `baseline` on the same cases.

    Pass `optimization` only when `baseline` and `candidate` are the holdout.
    The optimization pair is used for the overfit check and is not a second holdout look.
    """
    measured = _measure(
        baseline,
        candidate,
        search_cost_usd=search_cost_usd,
        monthly_runs=monthly_runs,
        new_side_effect_tools=new_side_effect_tools,
        removed_approvals=removed_approvals,
    )
    disqualified: list[str] = []
    if not measured.compatible:
        disqualified.append("incompatible")
    if _mock_only(
        baseline,
        candidate,
        search_cost_usd=search_cost_usd,
        monthly_runs=monthly_runs,
        new_side_effect_tools=new_side_effect_tools,
        removed_approvals=removed_approvals,
    ):
        disqualified.append("mock")
    if optimization is not None and _overfit(optimization, (baseline, candidate)):
        disqualified.append("overfit")
    clean = not disqualified
    cost_win = (
        clean
        and measured.cost_reduction >= COST_WIN
        and measured.noninferior_correctness
        and measured.noninferior_latency
    )
    correct = clean and measured.correctness_low > 0
    if mode == "correctness_win":
        if cost_ceiling is None:
            raise ValueError("correctness_win requires a cost ceiling")
        worth_it = clean and correct and measured.cost_per_case <= cost_ceiling
    else:
        worth_it = (
            clean
            and measured.noninferior_latency
            and (cost_win or (correct and measured.cost_reduction >= 0))
        )
    return Verdict(
        compatible=measured.compatible,
        correct=correct,
        worth_it=worth_it,
        cost_win=cost_win,
        correctness_points=measured.correctness_points,
        correctness_low=measured.correctness_low,
        correctness_high=measured.correctness_high,
        mde_points=measured.mde_points,
        cost_reduction=measured.cost_reduction,
        noninferior_latency=measured.noninferior_latency,
        noninferior_correctness=measured.noninferior_correctness,
        noninferiority_resolved=measured.noninferiority_resolved,
        disqualified=disqualified,
    )
