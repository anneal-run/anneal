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
"""

import copy
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

Outcome = Literal["correct", "fallback", "fallback_wrong", "loud", "silent"]


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


def behaviour_of(outcomes: Sequence[Outcome]) -> str:
    counts = Counter(outcomes)
    if counts["silent"] or counts["fallback_wrong"]:
        return "fails silently"
    if counts["loud"] or counts["fallback"]:
        return "fails loudly" if counts["loud"] >= counts["fallback"] else "falls back"
    return "handles it"


class ArmsReport(BaseModel):
    rows: list[ArmRow]
    arms: list[str]
    drifts: list[str]

    def summary(self, arm: str, drift: str | None) -> ArmSummary:
        rows = [r for r in self.rows if r.arm == arm and r.drift == drift]
        counts = Counter(r.outcome for r in rows)
        n = len(rows)
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
            behaviour=behaviour_of([r.outcome for r in rows]),
        )


def _score(case: Case, run: ArmRun, check: TaskCheck) -> Outcome:
    if run.error is not None:
        return "loud"
    done = check(case, run)
    if run.fell_back:
        return "fallback" if done else "fallback_wrong"
    return "correct" if done else "silent"


def evaluate(cases: Sequence[Case], arms: Mapping[str, Arm], check: TaskCheck) -> ArmsReport:
    """Run every arm on every case (each on its own copy of the input) and score it."""
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
    return ArmsReport(rows=rows, arms=list(arms), drifts=drifts)


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
    return "\n".join(out) + "\n"
