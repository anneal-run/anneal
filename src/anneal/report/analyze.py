"""`anneal analyze`: run coverage by skeleton, spend by class, conservative Tier 1 estimate.

The Tier 1 estimate counts `removable` calls at their full cost. `constrained`
calls count only where a measured delta is supplied for their position (one
real constrained call against the original call on the same input), and then
only as `spend * (1 - constrained_usd / original_usd)`. Nothing is estimated.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from anneal.canon.skeleton import cluster_runs
from anneal.classify import CALL_CLASSES, CallClass, classify
from anneal.classify.classifier import MIN_SUPPORT, STABLE_SHARE
from anneal.schema import ModelCall, Run


class Delta(BaseModel):
    """One measured comparison: the original call and its constrained replacement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    original_usd: float
    constrained_usd: float

    @property
    def saving_share(self) -> float:
        return max(0.0, 1.0 - self.constrained_usd / self.original_usd)


class ClusterRow(BaseModel):
    cluster_id: str
    runs: int
    run_share: float
    spend_usd: float
    spend_share: float
    variants: int
    steps: int


class ClassRow(BaseModel):
    call_class: CallClass
    calls: int
    spend_usd: float
    share: float


class PositionRow(BaseModel):
    position_id: str
    depth: int
    role: str
    runs: int
    dominant: str
    dominant_share: float
    call_class: CallClass
    reason: str
    spend_usd: float
    measured_saving_usd: float | None
    bindings: dict[str, str]


class AnalyzeReport(BaseModel):
    workflow_id: str
    runs: int
    model_calls: int
    unknown_cost_calls: int
    spend_usd: float
    clusters: list[ClusterRow]
    by_class: list[ClassRow]
    positions: list[PositionRow]
    tier1_saving_usd: float
    tier1_share: float
    constrained_unmeasured_usd: float
    min_support: int
    stable_share: float


def _share(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


def analyze(
    runs: Sequence[Run],
    *,
    deltas: dict[str, Delta] | None = None,
    min_support: int = MIN_SUPPORT,
    stable_share: float = STABLE_SHARE,
) -> AnalyzeReport:
    """Analyze the runs of one workflow; costs should already be filled."""
    deltas = deltas or {}
    calls_by_run: dict[str, list[ModelCall]] = {
        r.run_id: [e for e in r.events if isinstance(e, ModelCall)] for r in runs
    }
    run_spend = {rid: sum(c.cost_usd or 0.0 for c in cs) for rid, cs in calls_by_run.items()}
    total = sum(run_spend.values())
    all_calls = [c for cs in calls_by_run.values() for c in cs]

    clusters = [
        ClusterRow(
            cluster_id=c.cluster_id[:12],
            runs=len(c.run_ids),
            run_share=_share(len(c.run_ids), len(runs)),
            spend_usd=sum(run_spend[r] for r in c.run_ids),
            spend_share=_share(sum(run_spend[r] for r in c.run_ids), total),
            variants=len(c.skeleton_hashes),
            steps=len(c.skeleton),
        )
        for c in cluster_runs(runs)
    ]

    result = classify(runs, min_support=min_support, stable_share=stable_share)
    by_class = []
    for cls in CALL_CLASSES:
        members = [c for c in result.calls if c.call_class == cls]
        spend = sum(c.cost_usd or 0.0 for c in members)
        by_class.append(
            ClassRow(
                call_class=cls, calls=len(members), spend_usd=spend, share=_share(spend, total)
            )
        )

    positions = []
    measured = 0.0
    for p in result.positions:
        saving = None
        if p.call_class == "constrained" and p.position_id in deltas:
            saving = p.spend_usd * deltas[p.position_id].saving_share
            measured += p.spend_usd
        positions.append(PositionRow(**p.model_dump(), measured_saving_usd=saving))

    spend_of = {row.call_class: row.spend_usd for row in by_class}
    saving = spend_of["removable"] + sum(p.measured_saving_usd or 0.0 for p in positions)
    return AnalyzeReport(
        workflow_id=runs[0].workflow_id if runs else "",
        runs=len(runs),
        model_calls=len(all_calls),
        unknown_cost_calls=sum(1 for c in all_calls if c.cost_usd is None),
        spend_usd=total,
        clusters=clusters,
        by_class=by_class,
        positions=positions,
        tier1_saving_usd=saving,
        tier1_share=_share(saving, total),
        constrained_unmeasured_usd=spend_of["constrained"] - measured,
        min_support=min_support,
        stable_share=stable_share,
    )


def _usd(x: float) -> str:
    return f"${x:,.4f}"


def _pct(x: float) -> str:
    return f"{x:.1%}"


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def render_markdown(report: AnalyzeReport) -> str:
    """Human-readable report."""
    r = report
    summary = f"{r.runs} runs, {r.model_calls} model calls, {_usd(r.spend_usd)} model spend"
    if r.unknown_cost_calls:
        summary += f" ({r.unknown_cost_calls} calls with unknown cost, counted as $0)"
    out = [
        f"# anneal analyze: {r.workflow_id}",
        "",
        summary,
        f"Thresholds: min support {r.min_support} runs, stable choice {_pct(r.stable_share)}.",
        "",
        "## Run coverage by skeleton",
        "",
        _row("cluster", "runs", "run share", "spend", "spend share", "variants", "steps"),
        _row("---", "---:", "---:", "---:", "---:", "---:", "---:"),
    ]
    for c in r.clusters:
        out.append(
            _row(
                c.cluster_id,
                c.runs,
                _pct(c.run_share),
                _usd(c.spend_usd),
                _pct(c.spend_share),
                c.variants,
                c.steps,
            )
        )
    out += [
        "",
        "## Spend by class",
        "",
        _row("class", "calls", "spend", "share"),
        _row("---", "---:", "---:", "---:"),
    ]
    out += [_row(c.call_class, c.calls, _usd(c.spend_usd), _pct(c.share)) for c in r.by_class]
    out += [
        "",
        "## Tier 1 estimate",
        "",
        f"Conservative saving: {_usd(r.tier1_saving_usd)} ({_pct(r.tier1_share)} of spend).",
        "Counts removable calls in full and constrained calls only where a delta was measured.",
        "Constrained spend without a measured delta (not counted): "
        f"{_usd(r.constrained_unmeasured_usd)}.",
        "",
        "## Positions",
        "",
        _row("position", "depth", "role", "runs", "dominant", "share", "class", "reason", "spend"),
        _row("---", "---:", "---", "---:", "---", "---:", "---", "---", "---:"),
    ]
    for p in r.positions:
        out.append(
            _row(
                p.position_id,
                p.depth,
                p.role,
                p.runs,
                p.dominant,
                _pct(p.dominant_share),
                p.call_class,
                p.reason,
                _usd(p.spend_usd),
            )
        )
    measured = [p for p in r.positions if p.measured_saving_usd is not None]
    if measured:
        out += ["", "## Measured constrained deltas", ""]
        out += [
            f"- `{p.position_id}`: saves {_usd(p.measured_saving_usd or 0.0)}" for p in measured
        ]
    bound = [p for p in r.positions if p.bindings]
    if bound:
        out += ["", "## Argument bindings", ""]
        for p in bound:
            out.append(f"- `{p.position_id}` ({p.dominant}, {p.call_class})")
            out += [f"  - `{k}`: {v}" for k, v in p.bindings.items()]
    return "\n".join(out) + "\n"
