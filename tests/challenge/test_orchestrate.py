"""The orchestrator ranks on the optimization set and scores the holdout once."""

from typing import Literal

import pytest

from anneal.challenge.budget import SearchBudget
from anneal.challenge.models import Candidate, MeteredCall, Observation
from anneal.challenge.orchestrate import orchestrate

Arm = Literal["A", "B", "C", "control"]
Kind = Literal["structural", "prompt"]


def obs(case_id: str, *, cost: float, correct: bool = True) -> Observation:
    return Observation(
        case_id=case_id,
        correct=correct,
        cost_usd=cost,
        latency_ms=100,
        tools=["get_issue"],
        mocked=False,
        safety_ok=True,
    )


def rows(prefix: str, n: int, cost: float) -> list[Observation]:
    return [obs(f"{prefix}-{i:04d}", cost=cost) for i in range(n)]


def candidate(name: str, arm: Arm, kind: Kind, cost: float, *, hours: float = 0.5) -> Candidate:
    return Candidate(
        id=name,
        arm=arm,
        kind=kind,
        search_cost_usd=0.0,
        human_hours=hours,
        monthly_runs=10_000,
        opt=rows("opt", 20, cost),
        new_side_effect_tools=[],
        removed_approvals=[],
    )


def test_a_tying_b_is_not_a_harness_win() -> None:
    report = orchestrate(
        budget=SearchBudget(candidates=3, dollars=5, hours=5),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[
            candidate("cache-a", "A", "structural", 0.0020),
            candidate("cache-b", "B", "structural", 0.0020),
            candidate("untouched", "C", "structural", 0.0035),
        ],
        holdout={
            "A/cache-a": rows("hold", 20, 0.0020),
            "B/cache-b": rows("hold", 20, 0.0020),
            "C/untouched": rows("hold", 20, 0.0035),
        },
    )
    assert report.reading == "nothing_is_a_product"


def test_a_cache_edit_labeled_structural_is_not_a_structural_win() -> None:
    cached = candidate("cache", "A", "structural", 0.0010).model_copy(update={"change": "cache"})
    report = orchestrate(
        budget=SearchBudget(candidates=2, dollars=5, hours=5),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[cached, candidate("same", "B", "structural", 0.0035)],
        holdout={
            "A/cache": rows("hold", 20, 0.0010),
            "B/same": rows("hold", 20, 0.0035),
        },
    )
    assert report.reading == "stop_prompt_only"
    assert report.structural_winner is None
    assert report.scored[0].kind == "prompt"


def test_b_matching_c_is_the_harness_decision() -> None:
    baseline_opt = rows("opt", 20, 0.0035)
    baseline_hold = rows("hold", 20, 0.0035)
    shared = candidate("script", "C", "structural", 0.0005, hours=0.5)
    arm_b = candidate("script", "B", "structural", 0.0005, hours=0.5)
    arm_a = candidate("untuned", "A", "structural", 0.0035, hours=0.5)
    report = orchestrate(
        budget=SearchBudget(candidates=3, dollars=5, hours=5),
        baseline_opt=baseline_opt,
        baseline_holdout=baseline_hold,
        candidates=[shared, arm_b, arm_a],
        holdout={
            "C/script": rows("hold", 20, 0.0005),
            "B/script": rows("hold", 20, 0.0005),
            "A/untuned": rows("hold", 20, 0.0035),
        },
        external_merge=False,
        paid_commitment=False,
    )
    assert report.reading == "harness_is_the_product"
    scored = {item.key: item for item in report.scored}
    assert scored["C/script"].verdict.worth_it
    assert scored["C/script"].holdout_scored


def test_less_human_time_on_the_same_win_means_c_beats_b() -> None:
    report = orchestrate(
        budget=SearchBudget(candidates=2, dollars=5, hours=5),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[
            candidate("script", "C", "structural", 0.0005, hours=0.2),
            candidate("script", "B", "structural", 0.0005, hours=1.0),
            candidate("noop", "A", "structural", 0.0035, hours=0.2),
        ],
        holdout={
            "C/script": rows("hold", 20, 0.0005),
            "B/script": rows("hold", 20, 0.0005),
            "A/noop": rows("hold", 20, 0.0035),
        },
        external_merge=True,
        paid_commitment=True,
        paid_price="$2000",
    )
    assert report.reading == "strong_positive"
    assert report.structural_winner == "C/script"


def test_holdout_is_opened_once_for_the_top_candidates_only() -> None:
    budget = SearchBudget(candidates=3, dollars=5, hours=5)
    baseline_opt = rows("opt", 20, 0.0035)
    cands = [
        candidate("slow", "C", "structural", 0.0030),
        candidate("mid", "C", "structural", 0.0020),
        candidate("fast", "C", "structural", 0.0005),
        candidate("extra", "C", "structural", 0.0004),
    ]
    # Fourth candidate is past the per-arm cap, so it is not scored at all.
    report = orchestrate(
        budget=budget,
        baseline_opt=baseline_opt,
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=cands,
        holdout={
            "C/slow": rows("hold", 20, 0.0030),
            "C/mid": rows("hold", 20, 0.0020),
            "C/fast": rows("hold", 20, 0.0005),
            "C/extra": rows("hold", 20, 0.0001),
        },
    )
    scored_ids = {item.candidate_id for item in report.scored}
    assert "extra" not in scored_ids
    assert report.rejected[0].candidate_id == "extra"
    assert all(item.holdout_scored for item in report.scored)


def test_only_the_top_three_structural_candidates_reach_the_holdout() -> None:
    cands = [
        candidate("slow", "C", "structural", 0.0030),
        candidate("mid", "C", "structural", 0.0020),
        candidate("fast", "C", "structural", 0.0005),
        candidate("faster", "C", "structural", 0.0004),
    ]
    report = orchestrate(
        budget=SearchBudget(candidates=4, dollars=5, hours=5),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=cands,
        holdout={
            "C/slow": rows("hold", 20, 0.0030),
            "C/mid": rows("hold", 20, 0.0020),
            "C/fast": rows("hold", 20, 0.0005),
            "C/faster": rows("hold", 20, 0.0004),
        },
    )
    by_id = {item.candidate_id: item for item in report.scored}
    assert by_id["slow"].holdout_scored is False
    assert by_id["faster"].holdout_scored
    assert by_id["fast"].holdout_scored
    assert by_id["mid"].holdout_scored


def test_a_second_holdout_open_is_refused() -> None:
    from anneal.challenge.orchestrate import SealedHoldout

    sealed = SealedHoldout({"C/fast": rows("hold", 2, 0.0005)})
    sealed.open("C/fast")
    with pytest.raises(SealedHoldout.Reopened):
        sealed.open("C/fast")


def test_prompt_only_win_is_not_a_structural_product() -> None:
    report = orchestrate(
        budget=SearchBudget(candidates=2, dollars=5, hours=5),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[
            candidate("gepa", "control", "prompt", 0.0010),
            candidate("same-graph", "C", "structural", 0.0035),
        ],
        holdout={
            "control/gepa": rows("hold", 20, 0.0010),
            "C/same-graph": rows("hold", 20, 0.0035),
        },
    )
    assert report.reading == "stop_prompt_only"
    assert report.structural_winner is None


def test_reported_spend_that_is_below_the_meter_is_refused() -> None:
    liar = candidate("liar", "C", "structural", 0.0005).model_copy(
        update={
            "search_cost_usd": 0.01,
            "calls": [MeteredCall(cost_usd=3.0, latency_ms=10)],
        }
    )
    report = orchestrate(
        budget=SearchBudget(candidates=3, dollars=5, hours=5),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[
            liar,
            candidate("script", "B", "structural", 0.0005),
            candidate("noop", "A", "structural", 0.0035),
        ],
        holdout={
            "B/script": rows("hold", 20, 0.0005),
            "A/noop": rows("hold", 20, 0.0035),
        },
    )
    assert report.rejected[0].candidate_id == "liar"
    assert report.rejected[0].reason == "reported spend does not match the meter"
    assert all(item.candidate_id != "liar" for item in report.scored)


def _priced(usd_via_input_tokens: int) -> MeteredCall:
    cost = usd_via_input_tokens * 0.10 / 1_000_000
    return MeteredCall(
        cost_usd=cost,
        latency_ms=1,
        model="claude-haiku-5-5",
        tokens_in=usd_via_input_tokens,
        tokens_out=0,
        tokens_cached=0,
    )


def test_a_typed_dollar_amount_is_not_a_metered_call() -> None:
    invented = candidate("invented", "C", "structural", 0.0005).model_copy(
        update={
            "search_cost_usd": 0.0006,
            "calls": [MeteredCall(cost_usd=0.0006, latency_ms=1)],
        }
    )
    report = orchestrate(
        budget=SearchBudget(candidates=1, dollars=5, hours=5),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[invented],
        holdout={"C/invented": rows("hold", 20, 0.0005)},
    )
    assert report.rejected[0].reason == "spend was not metered at the model call"
    assert report.scored == []


def test_the_meter_sum_trips_the_dollar_cap() -> None:
    first = candidate("first", "C", "structural", 0.0005).model_copy(
        update={"search_cost_usd": 0.0006, "calls": [_priced(6_000)]}
    )
    second = candidate("second", "C", "structural", 0.0005).model_copy(
        update={"search_cost_usd": 0.0005, "calls": [_priced(5_000)]}
    )
    report = orchestrate(
        budget=SearchBudget(candidates=4, dollars=0.001, hours=5),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[first, second],
        holdout={
            "C/first": rows("hold", 20, 0.0005),
            "C/second": rows("hold", 20, 0.0005),
        },
    )
    assert [item.candidate_id for item in report.scored] == ["first"]
    assert report.rejected[0].candidate_id == "second"
    assert report.rejected[0].reason == "search budget exceeded"
    assert report.spent["C"].dollars == 0.0006


def test_structural_candidate_without_a_fallback_is_refused() -> None:
    report = orchestrate(
        budget=SearchBudget(candidates=4, dollars=20, hours=6),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[candidate("plain", "C", "structural", 0.0010)],
        holdout={"C/plain": rows("hold", 20, 0.0010)},
        require_fallback=True,
    )
    assert report.scored == []
    assert report.rejected[0].reason == "structural candidate has no confidence fallback"


def test_a_prompt_candidate_does_not_need_a_fallback() -> None:
    report = orchestrate(
        budget=SearchBudget(candidates=4, dollars=20, hours=6),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[candidate("edit", "C", "prompt", 0.0010)],
        holdout={"C/edit": rows("hold", 20, 0.0010)},
        require_fallback=True,
    )
    assert report.rejected == []
    assert report.scored[0].candidate_id == "edit"


def test_an_exception_only_fallback_is_refused() -> None:
    raw = candidate("hybrid", "C", "structural", 0.0010).model_dump()
    raw["fallback_rate"] = 0.2
    raw["fallback_triggers"] = ["exception"]
    hybrid = Candidate.model_validate(raw)
    report = orchestrate(
        budget=SearchBudget(candidates=4, dollars=20, hours=6),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[hybrid],
        holdout={"C/hybrid": rows("hold", 20, 0.0010)},
        require_fallback=True,
    )
    assert report.scored == []
    assert report.rejected[0].reason == "structural candidate fallback has no validity check"


def test_a_validity_check_keeps_the_fallback() -> None:
    raw = candidate("hybrid", "C", "structural", 0.0010).model_dump()
    raw["fallback_rate"] = 0.2
    raw["fallback_triggers"] = ["exception", "empty_result"]
    hybrid = Candidate.model_validate(raw)
    report = orchestrate(
        budget=SearchBudget(candidates=4, dollars=20, hours=6),
        baseline_opt=rows("opt", 20, 0.0035),
        baseline_holdout=rows("hold", 20, 0.0035),
        candidates=[hybrid],
        holdout={"C/hybrid": rows("hold", 20, 0.0010)},
        require_fallback=True,
    )
    assert report.rejected == []
    assert report.scored[0].candidate_id == "hybrid"


def test_fallback_rate_must_be_a_share() -> None:
    raw = candidate("hybrid", "C", "structural", 0.0010).model_dump()
    raw["fallback_rate"] = 1.2
    with pytest.raises(ValueError, match="fallback_rate"):
        Candidate.model_validate(raw)


def test_submission_that_already_contains_holdout_scores_is_rejected() -> None:
    with pytest.raises(ValueError, match="holdout"):
        Candidate.model_validate(
            {
                "id": "leaky",
                "arm": "C",
                "kind": "structural",
                "monthly_runs": 100,
                "opt": [],
                "holdout": [{"case_id": "h", "correct": True, "cost_usd": 0, "latency_ms": 1}],
            }
        )
