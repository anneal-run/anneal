"""Three-arm comparison: the original agent, the compiled path, a handwritten baseline.

Every arm runs every case (holdout inputs, and holdout inputs under each drift)
and each run is scored against the workflow's task check:

- `correct`: the arm finished and the task check passed;
- `fallback`: the arm handed off (a compiled deopt) and the job got done;
- `fallback_wrong`: it handed off, but the job was not done, for example a wrong
  write happened before the deopt;
- `loud`: the arm raised or reported an error;
- `silent`: the arm finished without any signal and the task check failed.

Per arm and drift type, the behaviour is the worst mode that occurred: "fails
silently" if any run did, otherwise "fails loudly" or "falls back" by which was
more common, otherwise "handles it".

That rule assumes the reference (Tier 0) is always right, which a real model is
not. With `reference=` (ADR 0011), every arm is scored only on the cases the
reference arm got done, and a drift type's behaviour is what the drift *adds* to
the arm's own holdout rates: "fails silently" if its silent rate (silent plus
fallback_wrong) rises by `DRIFT_MARGIN` or more, otherwise "fails loudly" or
"falls back" if that rate rises by the margin (the larger rise wins), otherwise
"handles it".
"""

import copy
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

Outcome = Literal["correct", "fallback", "fallback_wrong", "loud", "silent"]
DRIFT_MARGIN = 0.10
"""Rise over the holdout rate that a drift type must cause to change the behaviour."""
_DONE = frozenset({"correct", "fallback"})


class Case(BaseModel):
    case_id: str
    input: Any
    drift: str | None = None
    """None for the plain holdout."""


@dataclass
class ArmRun:
    output: Any
    cost_usd: float
    model_calls: int | None = None
    fell_back: bool = False
    error: str | None = None
    effects: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


Arm = Callable[[Case], ArmRun]
TaskCheck = Callable[[Case, ArmRun], bool]


class ArmRow(BaseModel):
    case_id: str
    drift: str | None
    arm: str
    outcome: Outcome
    cost_usd: float
    model_calls: int | None = None
    error: str | None = None


class ArmSummary(BaseModel):
    arm: str
    drift: str | None
    cases: int
    correct: int
    fallback: int
    fallback_wrong: int
    loud: int
    silent: int
    success_rate: float
    cost_per_task: float
    behaviour: str
    scored_cases: int | None = None
    """With a reference: the cases the reference got done, which the rates below use."""
    silent_rate: float | None = None
    loud_rate: float | None = None
    fallback_rate: float | None = None
    holdout_silent_rate: float | None = None
    holdout_loud_rate: float | None = None
    holdout_fallback_rate: float | None = None


def behaviour_of(outcomes: Sequence[Outcome]) -> str:
    counts = Counter(outcomes)
    if counts["silent"] or counts["fallback_wrong"]:
        return "fails silently"
    if counts["loud"] or counts["fallback"]:
        return "fails loudly" if counts["loud"] >= counts["fallback"] else "falls back"
    return "handles it"


def _rates(rows: Sequence["ArmRow"]) -> tuple[float, float, float]:
    n = len(rows) or 1
    counts = Counter(r.outcome for r in rows)
    return (
        (counts["silent"] + counts["fallback_wrong"]) / n,
        counts["loud"] / n,
        counts["fallback"] / n,
    )


def _relative_behaviour(
    drifted: tuple[float, float, float], holdout: tuple[float, float, float]
) -> str:
    silent, loud, fallback = (d - h for d, h in zip(drifted, holdout, strict=True))
    eps = 1e-9
    if silent >= DRIFT_MARGIN - eps:
        return "fails silently"
    if max(loud, fallback) >= DRIFT_MARGIN - eps:
        return "fails loudly" if loud >= fallback else "falls back"
    return "handles it"


class ArmsReport(BaseModel):
    rows: list[ArmRow]
    arms: list[str]
    drifts: list[str]
    reference: str | None = None

    def _scored(self, arm: str, drift: str | None) -> list[ArmRow]:
        done = {
            r.case_id
            for r in self.rows
            if r.arm == self.reference and r.drift == drift and r.outcome in _DONE
        }
        return [r for r in self.rows if r.arm == arm and r.drift == drift and r.case_id in done]

    def summary(self, arm: str, drift: str | None) -> ArmSummary:
        rows = [r for r in self.rows if r.arm == arm and r.drift == drift]
        counts = Counter(r.outcome for r in rows)
        n = len(rows)
        relative: dict[str, Any] = {}
        if self.reference is not None:
            scored, holdout = self._scored(arm, drift), self._scored(arm, None)
            here, base = _rates(scored), _rates(holdout)
            relative = {
                "scored_cases": len(scored),
                "silent_rate": here[0],
                "loud_rate": here[1],
                "fallback_rate": here[2],
                "holdout_silent_rate": base[0],
                "holdout_loud_rate": base[1],
                "holdout_fallback_rate": base[2],
                "behaviour": _relative_behaviour(here, base),
            }
        return ArmSummary(
            arm=arm,
            drift=drift,
            cases=n,
            correct=counts["correct"],
            fallback=counts["fallback"],
            fallback_wrong=counts["fallback_wrong"],
            loud=counts["loud"],
            silent=counts["silent"],
            success_rate=(counts["correct"] + counts["fallback"]) / n if n else 0.0,
            cost_per_task=sum(r.cost_usd for r in rows) / n if n else 0.0,
            **({"behaviour": behaviour_of([r.outcome for r in rows])} | relative),
        )


def _score(case: Case, run: ArmRun, check: TaskCheck) -> Outcome:
    if run.error is not None:
        return "loud"
    done = check(case, run)
    if run.fell_back:
        return "fallback" if done else "fallback_wrong"
    return "correct" if done else "silent"


def evaluate(
    cases: Sequence[Case],
    arms: Mapping[str, Arm],
    check: TaskCheck,
    reference: str | None = None,
) -> ArmsReport:
    """Run every arm on every case (each on its own copy of the input) and score it.
    `reference` names the arm whose done cases the drift behaviour is measured on."""
    rows: list[ArmRow] = []
    for case in cases:
        for name, arm in arms.items():
            own = case.model_copy(update={"input": copy.deepcopy(case.input)})
            try:
                run = arm(own)
            except Exception as e:  # an arm that raises has failed loudly
                run = ArmRun(output=None, cost_usd=0.0, error=f"{type(e).__name__}: {e}")
            rows.append(
                ArmRow(
                    case_id=case.case_id,
                    drift=case.drift,
                    arm=name,
                    outcome=_score(case, run, check),
                    cost_usd=run.cost_usd,
                    model_calls=run.model_calls,
                    error=run.error,
                )
            )
    drifts = sorted({c.drift for c in cases if c.drift is not None})
    return ArmsReport(rows=rows, arms=list(arms), drifts=drifts, reference=reference)


def render_markdown(report: ArmsReport, build_time: Mapping[str, str] | None = None) -> str:
    """The three-arm table, then outcome counts per arm and drift."""
    build_time = build_time or {}
    header = ["arm", "build time", "cost per task", "task success", *report.drifts]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for arm in report.arms:
        base = report.summary(arm, None)
        cells = [
            arm,
            build_time.get(arm, "n/a"),
            f"${base.cost_per_task:,.4f}",
            f"{base.success_rate:.1%}",
            *(report.summary(arm, d).behaviour for d in report.drifts),
        ]
        out.append("| " + " | ".join(cells) + " |")
    out += [
        "",
        "| arm | inputs | cases | correct | fallback | fallback_wrong | loud | silent |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in report.arms:
        for drift in [None, *report.drifts]:
            s = report.summary(arm, drift)
            out.append(
                f"| {arm} | {drift or 'holdout'} | {s.cases} | {s.correct} | {s.fallback} "
                f"| {s.fallback_wrong} | {s.loud} | {s.silent} |"
            )
    if report.reference is not None:
        out += [
            "",
            f"Drift behaviour is scored on the cases `{report.reference}` got done, against "
            f"each arm's own holdout rates (a rise of {DRIFT_MARGIN:.0%} or more counts).",
            "",
            "| arm | inputs | scored | silent | holdout silent | loud | holdout loud "
            "| fallback | holdout fallback | behaviour |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for arm in report.arms:
            for drift in report.drifts:
                s = report.summary(arm, drift)
                out.append(
                    f"| {arm} | {drift} | {s.scored_cases} | {s.silent_rate:.0%} "
                    f"| {s.holdout_silent_rate:.0%} | {s.loud_rate:.0%} "
                    f"| {s.holdout_loud_rate:.0%} "
                    f"| {s.fallback_rate:.0%} | {s.holdout_fallback_rate:.0%} | {s.behaviour} |"
                )
    return "\n".join(out) + "\n"
