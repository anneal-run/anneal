"""Model-call classification (CONTRACT classes, ANNEAL-ROADMAP.md M1.3).

A *position* is a node of the prefix tree over runs: the model calls whose
earlier steps are identical and whose role is the same. Each step is
`("model", role, outcome)` or `("tool", name, ok|error)`. Measuring "the same tool
choice at this position" over runs that share a prefix, rather than over runs
that share a whole skeleton, avoids selection bias: grouping by whole skeleton
puts each branch in its own cluster, where every choice looks stable.

Rules, first match wins, per call:

1. `terminal`: the run's last top-level model call that requests no tool.
2. `judgment` / `low_support`: the position has fewer than `min_support` runs.
3. `judgment` / `choice_varies`: the dominant outcome covers less than
   `stable_share` of the position's runs; `off_dominant_choice` for calls that
   took a minority outcome at a stable position.
4. `judgment` / `text_flows_into_args`: text written by any call at this
   position is the source of a later tool argument.
5. `judgment` / `text_output`: the dominant outcome requests no tool.
6. The arguments of the requested tools, per `tool:path` across the dominant
   calls: each must have one binding (same source step, path and transform) in
   at least `stable_share` of them, or the same model-written value in all of
   them (a constant). Then `removable` / `args_bound`; otherwise `constrained`
   with `args_model_generated` or `args_inconsistent`.
"""

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import blake3
from pydantic import BaseModel, ConfigDict

from anneal.canon.provenance import LeafProvenance, provenance
from anneal.canon.shape import leaves
from anneal.schema import Event, ModelCall, Run, ToolCall

CallClass = Literal["removable", "constrained", "judgment", "terminal"]
CALL_CLASSES: tuple[CallClass, ...] = ("removable", "constrained", "judgment", "terminal")
MIN_SUPPORT = 5
STABLE_SHARE = 0.95

Step = tuple[str, str, str]


class CallClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    event_id: str
    position_id: str
    depth: int
    role: str
    call_class: CallClass
    reason: str
    cost_usd: float | None


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)

    position_id: str
    depth: int
    role: str
    runs: int
    dominant: str
    dominant_share: float
    call_class: CallClass
    """The class most calls at this position received."""
    reason: str
    bindings: dict[str, str]
    """`tool:path` to a description of its dominant binding, for removable/constrained."""
    spend_usd: float
    """Spend of the calls at this position that received `call_class`."""


class Classification(BaseModel):
    model_config = ConfigDict(frozen=True)

    calls: list[CallClassification]
    positions: list[Position]


@dataclass
class _Call:
    run: Run
    event: ModelCall
    index: int
    outcome: str
    terminal: bool


@dataclass
class _RunView:
    run: Run
    events: list[Event]
    steps: list[Step]
    index_of: dict[str, int]
    prov: dict[str, list[LeafProvenance]] = field(default_factory=dict)


def _step(event: Event) -> Step | None:
    if isinstance(event, ModelCall):
        role = event.scope or (f"sys:{event.system_hash}" if event.system_hash else "model")
        names = sorted({t.name for t in event.tool_calls_requested})
        outcome = "calls:" + ",".join(names) if names else "text"
        return ("model", role, outcome)
    if isinstance(event, ToolCall):
        return ("tool", event.name, "error" if event.error else "ok")
    return None


def _view(run: Run) -> _RunView:
    events = [e for e in run.events if _step(e) is not None]
    steps = [s for s in map(_step, events) if s is not None]
    view = _RunView(run, events, steps, {e.event_id: i for i, e in enumerate(events)})
    for leaf in provenance(run):
        view.prov.setdefault(leaf.event_id, []).append(leaf)
    return view


def _position_id(prefix: Sequence[Step], role: str) -> str:
    payload = json.dumps([list(prefix), role], separators=(",", ":"))
    return blake3.blake3(payload.encode()).hexdigest()[:12]


def classify(
    runs: Sequence[Run], *, min_support: int = MIN_SUPPORT, stable_share: float = STABLE_SHARE
) -> Classification:
    """Classify every model call in `runs` (all from one workflow)."""
    views = {r.run_id: _view(r) for r in runs}
    groups: dict[tuple[tuple[Step, ...], str], list[_Call]] = defaultdict(list)
    for view in views.values():
        top_level = [
            i for i, e in enumerate(view.events) if isinstance(e, ModelCall) and e.parent_id is None
        ]
        for i, event in enumerate(view.events):
            if not isinstance(event, ModelCall):
                continue
            step = view.steps[i]
            terminal = step[2] == "text" and bool(top_level) and i == top_level[-1]
            groups[(tuple(view.steps[:i]), step[1])].append(
                _Call(view.run, event, i, step[2], terminal)
            )

    calls: list[CallClassification] = []
    positions: list[Position] = []
    for (prefix, role), members in groups.items():
        pid = _position_id(prefix, role)
        outcomes = Counter(c.outcome for c in members)
        dominant, count = outcomes.most_common(1)[0]
        share = count / len(members)
        cls, reason, bindings = _position_class(
            members, dominant, share, views, min_support, stable_share
        )
        classified: list[CallClassification] = []
        for c in members:
            if c.terminal:
                c_cls, c_reason = "terminal", "terminal"
            elif reason in {"low_support", "choice_varies"} or c.outcome == dominant:
                c_cls, c_reason = cls, reason
            else:
                c_cls, c_reason = "judgment", "off_dominant_choice"
            classified.append(
                CallClassification(
                    run_id=c.run.run_id,
                    event_id=c.event.event_id,
                    position_id=pid,
                    depth=len(prefix),
                    role=role,
                    call_class=c_cls,  # type: ignore[arg-type]
                    reason=c_reason,
                    cost_usd=c.event.cost_usd,
                )
            )
        calls += classified
        counts = Counter((c.call_class, c.reason) for c in classified)
        (top_cls, top_reason), _ = counts.most_common(1)[0]
        spend = sum(c.cost_usd or 0.0 for c in classified if c.call_class == top_cls)
        positions.append(
            Position(
                position_id=pid,
                depth=len(prefix),
                role=role,
                runs=len(members),
                dominant=dominant,
                dominant_share=share,
                call_class=top_cls,
                reason=top_reason,
                bindings=bindings,
                spend_usd=spend,
            )
        )
    positions.sort(key=lambda p: (-p.runs, p.depth, p.role, p.dominant))
    return Classification(calls=calls, positions=positions)


def _position_class(
    members: list[_Call],
    dominant: str,
    share: float,
    views: dict[str, _RunView],
    min_support: int,
    stable_share: float,
) -> tuple[CallClass, str, dict[str, str]]:
    if len(members) < min_support:
        return "judgment", "low_support", {}
    if share < stable_share:
        return "judgment", "choice_varies", {}
    ids = {c.event.event_id for c in members}
    for c in members:
        view = views[c.run.run_id]
        if any(
            edge.from_event in ids
            for leaves_ in view.prov.values()
            for leaf in leaves_
            for edge in leaf.edges
        ):
            return "judgment", "text_flows_into_args", {}
    if not dominant.startswith("calls:"):
        return "judgment", "text_output", {}

    chosen = [c for c in members if c.outcome == dominant]
    signatures: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for c in chosen:
        view = views[c.run.run_id]
        per_run: dict[str, tuple[Any, ...]] = {}
        for tool in _requested_tools(view, c):
            values = dict(leaves(tool.args))
            for leaf in view.prov.get(tool.event_id, []):
                per_run[f"{tool.name}:{leaf.path}"] = _signature(leaf, values.get(leaf.path), view)
        for key in set(per_run) | set(signatures):
            signatures[key].append(per_run.get(key, ("missing",)))

    bindings: dict[str, str] = {}
    model_generated = inconsistent = False
    for key, sigs in sorted(signatures.items()):
        sigs += [("missing",)] * (len(chosen) - len(sigs))
        top, n = Counter(sigs).most_common(1)[0]
        if top[0] == "gen" and n == len(chosen) and len(chosen) >= 2:
            bindings[key] = f"constant {json.loads(top[1])!r}"
        elif top[0] == "bind" and n >= stable_share * len(chosen):
            bindings[key] = _describe(top)
        elif top[0] in {"gen", "model"}:
            bindings[key] = "model"
            model_generated = True
        else:
            bindings[key] = "inconsistent"
            inconsistent = True
    if model_generated:
        return "constrained", "args_model_generated", bindings
    if inconsistent:
        return "constrained", "args_inconsistent", bindings
    return "removable", "args_bound", bindings


def _requested_tools(view: _RunView, call: _Call) -> list[ToolCall]:
    """Tool calls answering this model call.

    Matched by tool_call_id, else by name until the next model call at the same level.
    """
    request_ids = {r.id for r in call.event.tool_calls_requested if r.id}
    names = {r.name for r in call.event.tool_calls_requested}
    found: list[ToolCall] = []
    for event in view.events[call.index + 1 :]:
        if isinstance(event, ModelCall) and event.parent_id == call.event.parent_id:
            break
        if isinstance(event, ToolCall) and (
            event.tool_call_id in request_ids
            or (event.tool_call_id is None and event.name in names)
        ):
            found.append(event)
    return found


def _signature(leaf: LeafProvenance, value: Any, view: _RunView) -> tuple[Any, ...]:
    if leaf.status != "bound":
        return ("gen", json.dumps(value, sort_keys=True))
    if any(e.from_kind == "model" for e in leaf.edges):
        return ("model",)
    return (
        "bind",
        tuple(
            (
                e.from_kind,
                "input" if e.from_kind == "input" else view.index_of.get(e.from_event, -1),
                e.from_path,
                e.transform,
                e.detail,
            )
            for e in leaf.edges
        ),
    )


def _describe(signature: tuple[Any, ...]) -> str:
    parts = []
    for kind, step, path, transform, detail in signature[1]:
        source = "input" if kind == "input" else f"step {step}"
        extra = f" {detail!r}" if detail else ""
        parts.append(f"{source} {path} ({transform}{extra})")
    return " + ".join(parts)
