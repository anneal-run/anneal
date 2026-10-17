"""Rank on the optimization set. Open the holdout once, for three candidates per arm."""

from collections.abc import Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from anneal.challenge.budget import BudgetLedger, SearchBudget, Spend
from anneal.challenge.models import VALIDITY_TRIGGERS, Candidate, MeteredCall, Observation, Verdict
from anneal.challenge.power import n_required
from anneal.challenge.shadow import evidence_header
from anneal.challenge.verdict import CORRECTNESS_MARGIN_POINTS, Mode, judge
from anneal.schema.pricing import PriceTable

Reading = Literal[
    "strong_positive",
    "harness_is_the_product",
    "engine_needs_a_buyer",
    "nothing_is_a_product",
    "stop_prompt_only",
    "stop_no_win",
    "single_arm",
    "incomplete",
]
_COST_TIE = 0.05
_TOP_HOLDOUT = 3


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rejected(_Model):
    candidate_id: str
    arm: str
    reason: str


class Scored(_Model):
    key: str
    candidate_id: str
    arm: str
    kind: Literal["structural", "prompt"]
    human_hours: float
    verdict: Verdict
    holdout_scored: bool
    fallback_rate: float | None = None


class ChallengeReport(_Model):
    reading: Reading
    scored: list[Scored]
    rejected: list[Rejected]
    structural_winner: str | None
    labeling_hours: float = 0.0
    external_merge: bool = False
    paid_commitment: bool = False
    paid_price: str | None = None
    spent: dict[str, Spend] = Field(default_factory=dict)
    margin_points: float = 2.0
    n_reached: int = 0
    n_required: int = 0


class SealedHoldout:
    """Holdout rows can be opened once per candidate. A second open is a bug in the orchestrator."""

    class Reopened(Exception):
        """This candidate's holdout was already read."""

    def __init__(self, rows: dict[str, list[Observation]]) -> None:
        self._rows = rows
        self._opened: set[str] = set()

    def open(self, key: str) -> list[Observation]:
        if key in self._opened:
            raise self.Reopened(key)
        try:
            rows = self._rows[key]
        except KeyError as exc:
            raise ValueError(f"holdout observations missing for {key}") from exc
        self._opened.add(key)
        return rows


def orchestrate(
    *,
    budget: SearchBudget,
    baseline_opt: list[Observation],
    baseline_holdout: list[Observation],
    candidates: list[Candidate],
    holdout: dict[str, list[Observation]],
    labeling_hours: float = 0.0,
    external_merge: bool = False,
    paid_commitment: bool = False,
    paid_price: str | None = None,
    require_fallback: bool = False,
    margin_points: float = CORRECTNESS_MARGIN_POINTS,
    declared_arms: Collection[str] | None = None,
    mode: Mode = "cost",
    cost_ceiling: float | None = None,
) -> ChallengeReport:
    """Score submissions in order until each arm's budget is spent, then reveal the holdout."""
    ledger = BudgetLedger(budget)
    accepted: list[Candidate] = []
    rejected: list[Rejected] = []
    for candidate in candidates:
        if (
            require_fallback
            and candidate.effective_kind() == "structural"
            and candidate.fallback_rate is None
        ):
            rejected.append(
                Rejected(
                    candidate_id=candidate.id,
                    arm=candidate.arm,
                    reason="structural candidate has no confidence fallback",
                )
            )
            continue
        if (
            require_fallback
            and candidate.effective_kind() == "structural"
            and not VALIDITY_TRIGGERS.intersection(candidate.fallback_triggers)
        ):
            rejected.append(
                Rejected(
                    candidate_id=candidate.id,
                    arm=candidate.arm,
                    reason="structural candidate fallback has no validity check",
                )
            )
            continue
        metered = candidate.metered_usd()
        if abs(metered - candidate.search_cost_usd) > 1e-6:
            rejected.append(
                Rejected(
                    candidate_id=candidate.id,
                    arm=candidate.arm,
                    reason="reported spend does not match the meter",
                )
            )
            continue
        if _unmetered(candidate.calls):
            rejected.append(
                Rejected(
                    candidate_id=candidate.id,
                    arm=candidate.arm,
                    reason="spend was not metered at the model call",
                )
            )
            continue
        try:
            ledger.charge(candidate.arm, dollars=metered, hours=candidate.human_hours)
        except BudgetLedger.Exceeded:
            rejected.append(
                Rejected(
                    candidate_id=candidate.id,
                    arm=candidate.arm,
                    reason="search budget exceeded",
                )
            )
            continue
        accepted.append(candidate)

    previews = [
        (candidate, _preview(candidate, baseline_opt, mode=mode, cost_ceiling=cost_ceiling))
        for candidate in accepted
    ]
    selected = _select(previews)
    sealed = SealedHoldout(holdout)
    scored: list[Scored] = []
    for candidate, preview in previews:
        key = _key(candidate)
        if key not in selected:
            scored.append(_scored(candidate, preview, holdout_scored=False))
            continue
        verdict = judge(
            baseline_holdout,
            sealed.open(key),
            search_cost_usd=candidate.metered_usd(),
            monthly_runs=candidate.monthly_runs,
            new_side_effect_tools=candidate.new_side_effect_tools,
            removed_approvals=candidate.removed_approvals,
            optimization=(baseline_opt, candidate.opt),
            mode=mode,
            cost_ceiling=cost_ceiling,
        )
        scored.append(_scored(candidate, verdict, holdout_scored=True))

    reading, winner = _reading(
        scored,
        external_merge=external_merge,
        paid_commitment=paid_commitment,
        declared_arms=None if declared_arms is None else frozenset(declared_arms),
    )
    return ChallengeReport(
        reading=reading,
        scored=scored,
        rejected=rejected,
        structural_winner=winner,
        labeling_hours=labeling_hours,
        external_merge=external_merge,
        paid_commitment=paid_commitment,
        paid_price=paid_price,
        spent={arm: ledger.spent(arm) for arm in sorted({item.arm for item in candidates})},
        margin_points=margin_points,
        n_reached=len(baseline_holdout),
        n_required=n_required(margin_points),
    )


def render_markdown(report: ChallengeReport) -> str:
    """Verdict report. These headings are the v3 hypotheses, not the Milestone 1 register."""
    lines = [
        evidence_header(
            n=report.n_reached,
            margin_points=report.margin_points,
            verdict=report.reading,
        ).rstrip("\n"),
        "",
        "# Anneal v3 challenge",
        "",
        f"Reading: `{report.reading}`.",
        "",
        "This is the v3 decision, not the Milestone 1 hypothesis register.",
        "",
        f"Structural winner: {report.structural_winner or 'none'}.",
        f"Labeling hours: {report.labeling_hours}.",
        f"External merge or scheduled trial: {report.external_merge}.",
        f"Paid commitment: {report.paid_commitment}"
        + (f" at {report.paid_price}" if report.paid_price else "")
        + ".",
        "",
        "## Candidates",
        "",
    ]
    if not report.scored:
        lines.append("No candidate was scored inside the budget.")
        lines.append("")
    for scored in report.scored:
        verdict = scored.verdict
        lines.extend(
            [
                f"### {scored.key}",
                "",
                f"- Arm {scored.arm}, {scored.kind}, human hours {scored.human_hours}.",
                f"- Holdout scored: {scored.holdout_scored}.",
                f"- Compatible: {verdict.compatible}. Correct: {verdict.correct}. "
                f"Worth it: {verdict.worth_it}.",
                f"- Cost reduction after one month of amortization: {verdict.cost_reduction:.1%}.",
                *(
                    [f"- Fallback rate: {scored.fallback_rate:.1%}."]
                    if scored.fallback_rate is not None
                    else []
                ),
                f"- Correctness: {verdict.correctness_points:.1f} points "
                f"(interval {verdict.correctness_low:.1f} to {verdict.correctness_high:.1f}, "
                f"minimum detectable effect {verdict.mde_points:.1f} points).",
                f"- Disqualified: {', '.join(verdict.disqualified) or 'no'}.",
                "",
            ]
        )
    if report.rejected:
        lines.append("## Refused")
        lines.append("")
        for refused in report.rejected:
            lines.append(f"- {refused.arm}/{refused.candidate_id}: {refused.reason}.")
        lines.append("")
    return "\n".join(lines)


def _key(candidate: Candidate) -> str:
    return f"{candidate.arm}/{candidate.id}"


def _preview(
    candidate: Candidate,
    baseline_opt: list[Observation],
    *,
    mode: Mode,
    cost_ceiling: float | None,
) -> Verdict:
    return judge(
        baseline_opt,
        candidate.opt,
        search_cost_usd=candidate.metered_usd(),
        monthly_runs=candidate.monthly_runs,
        new_side_effect_tools=candidate.new_side_effect_tools,
        removed_approvals=candidate.removed_approvals,
        mode=mode,
        cost_ceiling=cost_ceiling,
    )


def _select(previews: list[tuple[Candidate, Verdict]]) -> set[str]:
    selected: set[str] = set()
    by_arm: dict[str, list[tuple[Candidate, Verdict]]] = {}
    for candidate, verdict in previews:
        if candidate.effective_kind() == "prompt":
            selected.add(_key(candidate))
            continue
        by_arm.setdefault(candidate.arm, []).append((candidate, verdict))
    for items in by_arm.values():
        ranked = sorted(
            items,
            key=lambda item: (
                item[1].worth_it,
                item[1].cost_reduction,
                item[1].correctness_points,
            ),
            reverse=True,
        )
        for candidate, _verdict in ranked[:_TOP_HOLDOUT]:
            selected.add(_key(candidate))
    return selected


def _scored(candidate: Candidate, verdict: Verdict, *, holdout_scored: bool) -> Scored:
    return Scored(
        key=_key(candidate),
        candidate_id=candidate.id,
        arm=candidate.arm,
        kind=candidate.effective_kind(),
        human_hours=candidate.human_hours,
        verdict=verdict,
        holdout_scored=holdout_scored,
        fallback_rate=candidate.fallback_rate,
    )


def _best(scored: list[Scored], arm: str) -> Scored | None:
    pool = [
        item
        for item in scored
        if item.arm == arm and item.kind == "structural" and item.holdout_scored
    ]
    if not pool:
        return None
    return max(
        pool,
        key=lambda item: (item.verdict.worth_it, item.verdict.cost_reduction, -item.human_hours),
    )


def _beats(left: Scored | None, right: Scored | None) -> bool:
    if left is None or not left.verdict.worth_it:
        return False
    if right is None or not right.verdict.worth_it:
        return True
    if left.verdict.cost_reduction >= right.verdict.cost_reduction + _COST_TIE:
        return True
    return (
        abs(left.verdict.cost_reduction - right.verdict.cost_reduction) < _COST_TIE
        and left.human_hours < right.human_hours
    )


def _reading(
    scored: list[Scored],
    *,
    external_merge: bool,
    paid_commitment: bool,
    declared_arms: frozenset[str] | None = None,
) -> tuple[Reading, str | None]:
    structural = [
        item
        for item in scored
        if item.kind == "structural" and item.holdout_scored and item.verdict.worth_it
    ]
    prompt = [
        item
        for item in scored
        if item.kind == "prompt" and item.holdout_scored and item.verdict.worth_it
    ]
    if not structural and prompt:
        return "stop_prompt_only", None
    if not structural:
        return "stop_no_win", None
    winner = max(structural, key=lambda item: (item.verdict.cost_reduction, -item.human_hours))
    ran = {item.arm for item in scored}
    if declared_arms is not None and len(declared_arms) == 1 and ran == declared_arms:
        return "single_arm", winner.key
    if not {"A", "B", "C"} <= ran:
        return "incomplete", winner.key
    arm_a, arm_b, arm_c = _best(scored, "A"), _best(scored, "B"), _best(scored, "C")
    if _beats(arm_c, arm_b) and _beats(arm_c, arm_a):
        if external_merge and paid_commitment:
            return "strong_positive", winner.key
        return "engine_needs_a_buyer", winner.key
    # Harness is the product only when B actually beat A and C did not beat B.
    # C losing while A ties B is not that result.
    if _beats(arm_b, arm_a) and not _beats(arm_c, arm_b):
        return "harness_is_the_product", winner.key
    return "nothing_is_a_product", winner.key


def _unmetered(calls: list[MeteredCall]) -> bool:
    """A positive dollar amount with no provider usage is a typed total."""
    prices = PriceTable.load()
    for call in calls:
        if call.cost_usd <= 0 and call.model is None:
            continue
        if call.model is None or call.tokens_in is None or call.tokens_out is None:
            return True
        priced = prices.cost(call.model, call.tokens_in, call.tokens_out, call.tokens_cached)
        if priced is None or abs(priced - call.cost_usd) > 1e-6:
            return True
    return False
