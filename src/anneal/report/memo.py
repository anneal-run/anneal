"""The Milestone 1 memo (`report/m1.md`) and the Gate 1 evaluation behind it.

Gate 1 is in ANNEAL-ROADMAP.md; how each criterion is read from the measured
reports is ADR 0010. Every criterion comes out `pass`, `fail`, `stop` or `open`
(not measurable from what was supplied). The gate is `stop` if any criterion is,
otherwise `not passed` if any failed, otherwise `incomplete` if any is open,
otherwise `passed`.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

from anneal.replay.arms import ArmsReport
from anneal.replay.arms import render_markdown as render_arms
from anneal.replay.replay import ReplayReport
from anneal.report.analyze import AnalyzeReport

Verdict = Literal["pass", "fail", "stop", "open"]
GateVerdict = Literal["passed", "not passed", "incomplete", "stop"]

H2_PASS = 0.40
H2_STOP = 0.25
H3_SUCCESS_GAP = 0.01
S0_BUDGET = 0.01
DEOPT_TRIALS = 20
BUILD_RATIO = 0.5
DRIFT_WINS = 2
GRACEFUL = frozenset({"falls back", "handles it"})
NEEDS_PATCH = frozenset({"fails silently", "fails loudly"})


class DeoptTrial(BaseModel):
    run_id: str
    step_id: str
    task_success: bool
    repeated: list[str] = Field(default_factory=list)
    """Completed compiled steps the resumed agent did again."""


class FallbackReport(BaseModel):
    framework: str
    trials: list[DeoptTrial]

    @property
    def passed(self) -> int:
        return sum(t.task_success and not t.repeated for t in self.trials)


class ManualStep(BaseModel):
    step: str
    why: str
    automate_in: str


class Criterion(BaseModel):
    id: str
    verdict: Verdict
    measured: str
    required: str


class Gate1(BaseModel):
    criteria: list[Criterion]
    verdict: GateVerdict


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def repeated_spend_share(report: AnalyzeReport) -> float:
    """H1: spend share of skeleton clusters with at least `min_support` runs."""
    return sum(c.spend_share for c in report.clusters if c.runs >= report.min_support)


def _drift_wins(arms: ArmsReport) -> list[str]:
    return [
        d
        for d in arms.drifts
        if arms.summary("compiled", d).behaviour in GRACEFUL
        and arms.summary("baseline", d).behaviour in NEEDS_PATCH
    ]


def _h4(arms: ArmsReport | None, build: Mapping[str, float | None]) -> Criterion:
    required = (
        f"build time under {BUILD_RATIO:.0%} of the script's, or lower cost per task, "
        f"or falls back on {DRIFT_WINS}+ drift types where the script fails or needs a patch"
    )
    if arms is None or not {"compiled", "baseline"} <= set(arms.arms):
        return Criterion(id="H4", verdict="open", measured="no baseline arm", required=required)
    compiled_s, baseline_s = build.get("compiled"), build.get("baseline")
    build_won = (
        None if compiled_s is None or baseline_s is None else compiled_s < BUILD_RATIO * baseline_s
    )
    c_cost = arms.summary("compiled", None).cost_per_task
    b_cost = arms.summary("baseline", None).cost_per_task
    wins = _drift_wins(arms)
    parts = [build_won, c_cost < b_cost, len(wins) >= DRIFT_WINS]
    verdict: Verdict = "pass" if any(parts) else "open" if None in parts else "stop"
    build_text = (
        "not measured" if build_won is None else f"{compiled_s:,.0f} s vs {baseline_s:,.0f} s"
    )
    measured = (
        f"build {build_text}; cost ${c_cost:.4f} vs ${b_cost:.4f}; "
        f"drift won on {len(wins)} of {len(arms.drifts)}"
        + (f" ({', '.join(wins)})" if wins else "")
    )
    return Criterion(id="H4", verdict=verdict, measured=measured, required=required)


def gate1(
    *,
    holdout: AnalyzeReport,
    replay: ReplayReport,
    fallback: FallbackReport | None,
    arms: ArmsReport | None,
    build_seconds: Mapping[str, float | None],
) -> Gate1:
    """Evaluate Gate 1 from the measured reports (ADR 0010)."""
    h4 = _h4(arms, build_seconds)
    drift_won = arms is not None and h4.verdict != "open" and len(_drift_wins(arms)) >= DRIFT_WINS

    share = holdout.tier1_share
    h2_verdict: Verdict = (
        "pass"
        if share >= H2_PASS
        else "stop"
        if share < H2_STOP
        else ("pass" if drift_won else "stop")
    )
    h2 = Criterion(
        id="H2",
        verdict=h2_verdict,
        measured=f"{_pct(share)} of holdout spend removable or measured constrained",
        required=(
            f">= {H2_PASS:.0%}; under {H2_STOP:.0%} stop; between, only if the drift "
            "comparison is won"
        ),
    )

    s12 = replay.wrong_by_severity.get("S1", 0) + replay.wrong_by_severity.get("S2", 0)
    s0 = replay.wrong_rate_by_severity.get("S0", 0.0)
    gap = replay.tier0_success_rate - replay.compiled_success_rate
    h3_ok = replay.compiled and gap <= H3_SUCCESS_GAP + 1e-9 and s12 == 0 and s0 <= S0_BUDGET
    # Every run fell back: compiled success equals Tier 0's by construction, no evidence.
    vacuous = replay.compiled and replay.accepted_success_rate is None
    h3 = Criterion(
        id="H3",
        verdict="open" if h3_ok and vacuous else "pass" if h3_ok else "fail",
        measured=(
            f"task success {_pct(replay.compiled_success_rate)} compiled vs "
            f"{_pct(replay.tier0_success_rate)} Tier 0; S1+S2 wrong {s12}; S0 wrong {_pct(s0)}"
            + ("" if replay.compiled else "; nothing compiled")
            + ("; no holdout run finished on the compiled path" if vacuous else "")
        ),
        required=(
            f"within {H3_SUCCESS_GAP * 100:.0f} point of Tier 0; zero S1/S2 wrong; "
            f"S0 <= {S0_BUDGET:.0%}"
        ),
    )

    if fallback is None:
        fb = Criterion(
            id="fallback", verdict="open", measured="not run", required="20 of 20 injected deopts"
        )
    else:
        n, ok = len(fallback.trials), fallback.passed
        fb_verdict: Verdict = "fail" if ok < n else "open" if n < DEOPT_TRIALS else "pass"
        fb = Criterion(
            id="fallback",
            verdict=fb_verdict,
            measured=f"{ok} of {n} completed with task success and no repeated step",
            required=f"{DEOPT_TRIALS} of {DEOPT_TRIALS} injected deopts",
        )

    criteria = [h2, h3, fb, h4]
    found = {c.verdict for c in criteria}
    verdict: GateVerdict = (
        "stop"
        if "stop" in found
        else "not passed"
        if "fail" in found
        else "incomplete"
        if "open" in found
        else "passed"
    )
    return Gate1(criteria=criteria, verdict=verdict)


class Memo(BaseModel):
    workflow_id: str
    synthetic: bool
    source: str
    analyze_all: AnalyzeReport
    analyze_holdout: AnalyzeReport
    replay: ReplayReport
    fallback: FallbackReport | None = None
    arms: ArmsReport | None = None
    build_seconds: dict[str, float | None] = Field(default_factory=dict)
    build_notes: dict[str, str] = Field(default_factory=dict)
    manual_steps: list[ManualStep] = Field(default_factory=list)
    open_items: list[str] = Field(default_factory=list)

    def gate(self) -> Gate1:
        return gate1(
            holdout=self.analyze_holdout,
            replay=self.replay,
            fallback=self.fallback,
            arms=self.arms,
            build_seconds=self.build_seconds,
        )


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _status(verdict: Verdict) -> str:
    return {"pass": "supported", "fail": "not supported", "stop": "failed", "open": "untested"}[
        verdict
    ]


def render_memo(memo: Memo) -> str:
    gate = memo.gate()
    by_id = {c.id: c for c in gate.criteria}
    r, h, a = memo.replay, memo.analyze_holdout, memo.analyze_all
    out = [f"# Milestone 1 memo: {memo.workflow_id}", ""]
    if memo.synthetic:
        out += [
            "> **SYNTHETIC.** Every number below comes from a simulated environment and a "
            "simulated model. It exercises the experiment end to end; it is not Gate 1 "
            "evidence and the hypotheses register is not updated from it.",
            "",
        ]
    out += [
        f"Source: {memo.source}. Task check: `{r.task_check}`.",
        "",
        "## Gate 1",
        "",
        _row("criterion", "verdict", "measured", "required"),
        _row("---", "---", "---", "---"),
        *(_row(c.id, c.verdict, c.measured, c.required) for c in gate.criteria),
        "",
        f"**Gate 1: {gate.verdict}.**" + (" (Would be, on real data.)" if memo.synthetic else ""),
        "",
        "## H1, H2: where the spend is",
        "",
        f"All {a.runs} runs: {_pct(repeated_spend_share(a))} of model spend is in skeleton "
        f"clusters with at least {a.min_support} runs (H1).",
        "",
        f"Holdout ({h.runs} runs, ${h.spend_usd:,.4f}):",
        "",
        _row("class", "calls", "spend", "share"),
        _row("---", "---:", "---:", "---:"),
        *(_row(c.call_class, c.calls, f"${c.spend_usd:,.4f}", _pct(c.share)) for c in h.by_class),
        "",
        f"Tier 1 saving counted for H2: ${h.tier1_saving_usd:,.4f} ({_pct(h.tier1_share)}); "
        f"constrained spend without a measured delta, counted as zero: "
        f"${h.constrained_unmeasured_usd:,.4f}.",
        "",
        "## H3: chronological replay",
        "",
        f"Compiled on {r.compile_runs} runs, replayed on the {r.holdout_runs} later runs "
        f"(model answers: {r.llm_mode}). Plan `{r.plan_id}`.",
        "",
        _row("", "value"),
        _row("---", "---:"),
        _row("Tier 0 task success", _pct(r.tier0_success_rate)),
        _row("compiled task success (fallbacks count as Tier 0)", _pct(r.compiled_success_rate)),
        _row("success among runs the guards accepted", _pct(r.accepted_success_rate)),
        _row("fallback rate", _pct(r.fallback_rate)),
        *(_row(f"wrong executions {s}", r.wrong_by_severity.get(s, 0)) for s in ("S0", "S1", "S2")),
        _row("cost per run, Tier 0", f"${r.cost_per_run_tier0:,.4f}"),
        _row("cost per run, compiled", f"${r.cost_per_run_compiled:,.4f}"),
        "",
    ]
    if r.deopt_by_step:
        deopts = ", ".join(f"{k}: {v}" for k, v in sorted(r.deopt_by_step.items()))
        out += [f"Deopts by step: {deopts}.", ""]

    out += ["## Fallback", ""]
    if memo.fallback is None:
        out += ["Injected deopts not run.", ""]
    else:
        f = memo.fallback
        steps = sorted({t.step_id for t in f.trials})
        out += [
            f"{f.passed} of {len(f.trials)} injected deopts ({f.framework}, at steps "
            f"{', '.join(steps)}) finished with task success and no repeated step.",
            "",
        ]
        bad = [t for t in f.trials if not t.task_success or t.repeated]
        out += [
            f"- `{t.run_id}` at {t.step_id}: success {t.task_success}, repeated "
            f"{', '.join(t.repeated) or 'nothing'}"
            for t in bad
        ]
        out += [""] if bad else []

    out += ["## H4: against the handwritten baseline", ""]
    if memo.arms is None:
        out += ["No baseline arm.", ""]
    else:
        labels = {
            arm: (
                memo.build_notes.get(arm)
                or (
                    f"{s:,.0f} s"
                    if (s := memo.build_seconds.get(arm)) is not None
                    else "not measured"
                )
            )
            for arm in memo.arms.arms
        }
        out += [render_arms(memo.arms, build_time=labels)]

    out += ["## Manual steps", ""]
    if memo.manual_steps:
        out += [
            _row("step", "why", "automate in"),
            _row("---", "---", "---"),
            *(_row(m.step, m.why, m.automate_in) for m in memo.manual_steps),
            "",
        ]
    else:
        out += ["None recorded.", ""]

    register = [
        (
            "H1",
            "repeated runs carry most spend",
            f"{_pct(repeated_spend_share(a))}",
            "supported" if repeated_spend_share(a) > 0.5 else "not supported",
        ),
        (
            "H2",
            "40%+ of spend removable or constrained",
            by_id["H2"].measured,
            _status(by_id["H2"].verdict),
        ),
        (
            "H3",
            "guards and replay keep wrong execution in budget",
            by_id["H3"].measured,
            _status(by_id["H3"].verdict),
        ),
        (
            "H4",
            "compiled beats the script on one of three",
            by_id["H4"].measured,
            _status(by_id["H4"].verdict),
        ),
    ]
    out += [
        "## Hypotheses register",
        "",
        _row("id", "hypothesis", "number", "status" + (" (if real)" if memo.synthetic else "")),
        _row("---", "---", "---", "---"),
        *(_row(*row) for row in register),
        "",
        "## Open items",
        "",
        *([f"- {item}" for item in memo.open_items] or ["None."]),
        "",
    ]
    return "\n".join(out)
