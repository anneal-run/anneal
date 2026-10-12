"""Provenance: where each tool-argument leaf came from.

Sources are the leaves available before the tool call: the run input, results
of earlier tool calls, and the text output of earlier model calls. A model's
tool-call request is not a source, since it is the argument itself. Strategies
are tried in order and the first that finds anything wins:

1. `exact`
2. normalized: `trim`, `lower`, `trim|lower`, then `normalize` (case and whitespace)
3. `substring` of 6+ characters
4. `number` or `date` reformat
5. `json`: a leaf inside a source string that holds JSON (`detail` is the inner path)
6. `concat` of two or three leaves with one separator (`detail` is the separator)

Within a strategy the most recent source wins, then a source whose last key
matches the argument's; `ambiguous` is set when more than one source matched.
Booleans, nulls and empty strings are never matched. A leaf with no match is
`model_generated` when a model call requested the tool, otherwise `external`.
"""

import itertools
import json
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from anneal.canon.dates import parse_dates
from anneal.canon.shape import leaves
from anneal.schema import Event, ModelCall, Run, ToolCall

SourceKind = Literal["input", "tool", "model"]
MIN_SUBSTRING = 6
MIN_CONCAT_PART = 2
MAX_CONCAT_CANDIDATES = 30
CONCAT_SEPARATORS = ("", " ", "-", "_", ",", ", ", "/", ":", ".")
_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")
_GROUPED = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_LAST_KEY = re.compile(r"(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[('.*?'|\".*?\")\])$")


class Edge(BaseModel):
    """One data-flow edge from a source leaf to a tool-argument leaf."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    from_event: str
    """Event id, or `input` for the run input."""
    from_kind: SourceKind
    from_path: str
    to_event: str
    to_path: str
    transform: str
    detail: str | None = None
    part: int = 0
    parts: int = 1


class LeafProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    path: str
    status: Literal["bound", "model_generated", "external"]
    edges: list[Edge] = Field(default_factory=list)
    ambiguous: bool = False


@dataclass(frozen=True)
class _Source:
    event_id: str
    kind: SourceKind
    path: str
    value: Any
    order: int


@dataclass(frozen=True)
class _Hit:
    sources: tuple[_Source, ...]
    transform: str
    detail: str | None = None


def provenance(run: Run) -> list[LeafProvenance]:
    """Provenance of every tool-argument leaf in the run, in event order."""
    sources = [_Source("input", "input", p, v, -1) for p, v in leaves(run.input) if _usable(v)]
    out: list[LeafProvenance] = []
    for order, event in enumerate(run.events):
        if isinstance(event, ToolCall):
            requested = _requested_by_model(run.events[:order], event)
            for path, value in leaves(event.args):
                out.append(_leaf(event.event_id, path, value, sources, requested))
            if not event.error:
                sources += [
                    _Source(event.event_id, "tool", p, v, order)
                    for p, v in leaves(event.result)
                    if _usable(v)
                ]
        elif isinstance(event, ModelCall) and event.output_text:
            sources.append(_Source(event.event_id, "model", "$", event.output_text, order))
    return out


def _usable(value: Any) -> bool:
    return value is not None and not isinstance(value, bool) and value != ""


def _requested_by_model(before: Sequence[Event], tool: ToolCall) -> bool:
    calls = [e for e in before if isinstance(e, ModelCall)]
    if tool.tool_call_id and any(
        r.id == tool.tool_call_id for c in calls for r in c.tool_calls_requested
    ):
        return True
    return any(r.name == tool.name for c in calls for r in c.tool_calls_requested)


def _leaf(
    event_id: str, path: str, value: Any, sources: list[_Source], requested: bool
) -> LeafProvenance:
    hits = _match(value, sources) if _usable(value) else []
    if not hits:
        status: Literal["model_generated", "external"] = (
            "model_generated" if requested else "external"
        )
        return LeafProvenance(event_id=event_id, path=path, status=status)
    target_key = _last_key(path)
    best = max(
        hits,
        key=lambda h: (
            max(s.order for s in h.sources),
            any(_last_key(s.path) == target_key for s in h.sources),
            -sources.index(h.sources[0]),
        ),
    )
    edges = [
        Edge(
            from_event=s.event_id,
            from_kind=s.kind,
            from_path=s.path,
            to_event=event_id,
            to_path=path,
            transform=best.transform,
            detail=best.detail,
            part=i,
            parts=len(best.sources),
        )
        for i, s in enumerate(best.sources)
    ]
    return LeafProvenance(
        event_id=event_id, path=path, status="bound", edges=edges, ambiguous=len(hits) > 1
    )


def _last_key(path: str) -> str | None:
    m = _LAST_KEY.search(path)
    if not m:
        return None
    return m.group(1) or m.group(2)[1:-1]


def _match(target: Any, sources: list[_Source]) -> list[_Hit]:
    for strategy in (_exact, _normalized, _substring, _reformat, _json, _concat):
        hits = list(strategy(target, sources))
        if hits:
            return hits
    return []


def _exact(target: Any, sources: list[_Source]) -> Iterator[_Hit]:
    for s in sources:
        same_type = type(s.value) is type(target) or (_is_number(target) and _is_number(s.value))
        if same_type and s.value == target:
            yield _Hit((s,), "exact")


def _normalized(target: Any, sources: list[_Source]) -> Iterator[_Hit]:
    if not isinstance(target, str):
        return
    for s in sources:
        if not isinstance(s.value, str):
            continue
        for name, fn in _NORMALIZERS:
            if fn(s.value) == target:
                yield _Hit((s,), name)
                break
        else:
            if _collapse(s.value) == _collapse(target):
                yield _Hit((s,), "normalize")


def _collapse(text: str) -> str:
    return " ".join(text.split()).casefold()


_NORMALIZERS: tuple[tuple[str, Callable[[str], str]], ...] = (
    ("trim", str.strip),
    ("lower", str.lower),
    ("trim|lower", lambda x: x.strip().lower()),
)


def _substring(target: Any, sources: list[_Source]) -> Iterator[_Hit]:
    if not isinstance(target, str) or len(target) < MIN_SUBSTRING:
        return
    for s in sources:
        if isinstance(s.value, str) and target in s.value and target != s.value:
            yield _Hit((s,), "substring")


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _as_number(value: Any) -> float | None:
    if _is_number(value):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("$€£").strip()
    if _GROUPED.fullmatch(text):
        text = text.replace(",", "")
    return float(text) if _NUMBER.fullmatch(text) else None


def _reformat(target: Any, sources: list[_Source]) -> Iterator[_Hit]:
    number = _as_number(target)
    dates = parse_dates(target)
    for s in sources:
        if number is not None and _as_number(s.value) == number:
            yield _Hit((s,), "number")
        elif dates and dates & parse_dates(s.value):
            yield _Hit((s,), "date")


def _json(target: Any, sources: list[_Source]) -> Iterator[_Hit]:
    for s in sources:
        if not (isinstance(s.value, str) and s.value.lstrip()[:1] in {"{", "["}):
            continue
        try:
            inner = json.loads(s.value)
        except ValueError:
            continue
        for path, value in leaves(inner):
            if type(value) is type(target) and value == target:
                yield _Hit((s,), "json", path)


def _concat(target: Any, sources: list[_Source]) -> Iterator[_Hit]:
    if not isinstance(target, str):
        return
    parts = [
        s
        for s in sources
        if isinstance(s.value, str | int)
        and not isinstance(s.value, bool)
        and len(str(s.value)) >= MIN_CONCAT_PART
        and str(s.value) in target
    ][-MAX_CONCAT_CANDIDATES:]
    for k in (2, 3):
        found = False
        for combo in itertools.permutations(parts, k):
            texts = [str(s.value) for s in combo]
            for sep in CONCAT_SEPARATORS:
                if sep.join(texts) == target:
                    found = True
                    yield _Hit(combo, "concat", sep)
        if found:
            return
