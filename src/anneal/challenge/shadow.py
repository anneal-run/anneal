"""Paired shadow counts against a per-workflow margin.

A report always names the verdict and how many pairs have been seen. Sequential
stopping is allowed only when the interval lies entirely outside the margin.
"""

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from anneal.challenge.power import n_required
from anneal.challenge.stats import CORRECTNESS_NULL_VARIANCE, interval


@dataclass(frozen=True)
class ShadowReport:
    margin_points: float
    n_required: int
    n_reached: int
    verdict: str
    stopped: bool
    estimate_points: float | None


def margin_points(path: Path, workflow: str) -> float:
    """The correctness margin registered for one workflow in `anneal.toml`."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        value = data["workflows"][workflow]["margin_points"]
    except KeyError as exc:
        raise ValueError(f"no margin for {workflow} in {path}") from exc
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError("margin_points must be positive")
    return float(value)


def load_pairs(path: Path) -> list[tuple[bool, bool]]:
    """Last row for each case. A repeated case does not count twice."""
    by_id: dict[str, tuple[bool, bool]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        by_id[str(raw["case_id"])] = (bool(raw["baseline_correct"]), bool(raw["candidate_correct"]))
    return list(by_id.values())


def evaluate_pairs(pairs: list[tuple[bool, bool]], *, margin_points: float) -> ShadowReport:
    """Stop early only when the paired difference is clearly outside the margin."""
    needed = n_required(margin_points)
    n = len(pairs)
    if n < 1:
        return ShadowReport(margin_points, needed, 0, "cannot adjudicate", False, None)
    differences = [float(candidate) - float(baseline) for baseline, candidate in pairs]
    span = interval(differences, null_variance=CORRECTNESS_NULL_VARIANCE)
    estimate = span.estimate * 100
    low = span.low * 100
    high = span.high * 100
    if low > margin_points:
        verdict, stopped = "outside the margin, better", True
    elif high < -margin_points:
        verdict, stopped = "outside the margin, worse", True
    elif n >= needed:
        verdict = "within the margin" if estimate >= -margin_points else "worse than the margin"
        stopped = True
    else:
        verdict, stopped = "cannot adjudicate", False
    return ShadowReport(margin_points, needed, n, verdict, stopped, estimate)


def evidence_header(*, n: int, margin_points: float, verdict: str) -> str:
    """Margin, the n that margin needs, the n reached, and the verdict. Every report starts here."""
    return (
        f"margin: {margin_points:.1f} points; n required: {n_required(margin_points)}\n"
        f"n reached: {n}\n"
        f"verdict: {verdict}\n"
    )


def render_shadow(report: ShadowReport) -> str:
    """Every shadow report carries the margin, the n it needs, the n it has, and the verdict."""
    return evidence_header(
        n=report.n_reached,
        margin_points=report.margin_points,
        verdict=report.verdict,
    )
