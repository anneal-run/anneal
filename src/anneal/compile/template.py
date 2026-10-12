"""The plan template language (CONTRACT, ANNEAL-ROADMAP.md M1.4). It is the whole language:

    {{input<path>}}                       the run input
    {{steps.<id>.result<path>}}           the result of an earlier step
    {{<ref> | trim | lower}}              filters, applied left to right
    {{<ref> | fmt_date('%Y-%m-%d')}}      re-format a date the value can be read as
    {{concat(<ref>, <ref>, sep='-')}}     join two or more refs with a separator

`<path>` is `.key`, `[0]` or `['any key']`, repeated. A string that is exactly one
expression renders to the referenced value with its type; expressions inside
other text render as text (objects and arrays as JSON). Unknown paths, filters
and syntax raise `TemplateError`; nothing renders silently empty.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from anneal.canon.dates import parse_dates


class TemplateError(ValueError):
    """A template cannot be parsed or does not resolve against the state."""


_EXPR = re.compile(r"\{\{(.*?)\}\}", re.S)
_REF = re.compile(
    r"(?P<root>input|steps\.(?P<step>[A-Za-z0-9_-]+)\.result)"
    r"(?P<path>(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\]|\['(?:[^'\\]|\\.)*'\]|\[\"(?:[^\"\\]|\\.)*\"\])*)"
)
_SEGMENT = re.compile(
    r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]|\[('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\]"
)
_FMT_DATE = re.compile(r"fmt_date\((['\"])(.*)\1\)")
_SEP = re.compile(r"sep=(['\"])(.*)\1")


@dataclass(frozen=True)
class _Ref:
    step: str | None
    path: tuple[str | int, ...]
    text: str = ""


@dataclass(frozen=True)
class _Expr:
    refs: tuple[_Ref, ...]
    filters: tuple[str, ...] = ()
    sep: str | None = None
    """Set for concat expressions."""


def _parse_ref(text: str) -> _Ref:
    m = _REF.fullmatch(text.strip())
    if not m:
        raise TemplateError(f"unknown reference {text.strip()!r}")
    path: list[str | int] = []
    for seg in _SEGMENT.finditer(m.group("path")):
        key, index, quoted = seg.groups()
        if index is not None:
            path.append(int(index))
        elif quoted is not None:
            path.append(json.loads('"' + quoted[1:-1].replace('"', '\\"') + '"'))
        else:
            path.append(key)
    return _Ref(m.group("step"), tuple(path), m.group(0))


def _split(text: str, sep: str) -> list[str]:
    """Split on `sep` outside quotes and parentheses."""
    parts, depth, quote, start = [], 0, "", 0
    for i, ch in enumerate(text):
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    if quote or depth:
        raise TemplateError(f"unbalanced expression {text!r}")
    return [*parts, text[start:]]


def _parse(expr: str) -> _Expr:
    text = expr.strip()
    if text.startswith("concat(") and text.endswith(")"):
        args = [a.strip() for a in _split(text[len("concat(") : -1], ",")]
        sep = ""
        if args and (m := _SEP.fullmatch(args[-1])):
            sep = m.group(2)
            args = args[:-1]
        if len(args) < 2:
            raise TemplateError(f"concat needs at least two references: {text!r}")
        return _Expr(tuple(_parse_ref(a) for a in args), sep=sep)
    head, *filters = (p.strip() for p in _split(text, "|"))
    for f in filters:
        if f not in {"trim", "lower"} and not _FMT_DATE.fullmatch(f):
            raise TemplateError(f"unknown filter {f!r}")
    return _Expr((_parse_ref(head),), tuple(filters))


def _expressions(template: str) -> Iterator[re.Match[str]]:
    yield from _EXPR.finditer(template)
    if "{{" in _EXPR.sub("", template):
        raise TemplateError(f"unclosed expression in {template!r}")


def _resolve(ref: _Ref, ctx: dict[str, Any]) -> Any:
    if ref.step is None:
        value: Any = ctx.get("input")
        where = "input"
    else:
        steps = ctx.get("steps", {})
        if ref.step not in steps:
            raise TemplateError(f"unknown step {ref.step!r}")
        value = steps[ref.step].get("result")
        where = f"steps.{ref.step}.result"
    for seg in ref.path:
        try:
            value = value[seg]
        except (KeyError, IndexError, TypeError):
            raise TemplateError(f"{where}: no {seg!r}") from None
        where += f"[{seg!r}]"
    return value


def _apply(value: Any, f: str) -> Any:
    if f == "trim":
        return str(value).strip()
    if f == "lower":
        return str(value).lower()
    m = _FMT_DATE.fullmatch(f)
    assert m is not None
    dates = parse_dates(value)
    if len(dates) != 1:
        raise TemplateError(f"fmt_date: cannot read {value!r} as exactly one date")
    return next(iter(dates)).strftime(m.group(2))


def _evaluate(expr: _Expr, ctx: dict[str, Any]) -> Any:
    if expr.sep is not None:
        return expr.sep.join(_text(_resolve(r, ctx)) for r in expr.refs)
    value = _resolve(expr.refs[0], ctx)
    for f in expr.filters:
        value = _apply(value, f)
    return value


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def render(template: Any, ctx: dict[str, Any]) -> Any:
    """Render a template value (string, dict, list or literal) against `{"input", "steps"}`."""
    if isinstance(template, dict):
        return {k: render(v, ctx) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, ctx) for v in template]
    if not isinstance(template, str):
        return template
    matches = list(_expressions(template))
    if len(matches) == 1 and matches[0].span() == (0, len(template)):
        return _evaluate(_parse(matches[0].group(1)), ctx)
    out, pos = [], 0
    for m in matches:
        out += [template[pos : m.start()], _text(_evaluate(_parse(m.group(1)), ctx))]
        pos = m.end()
    return "".join(out) + template[pos:]


def references(template: Any) -> set[str]:
    """Step ids a template reads; also checks that every expression parses."""
    return {r.step for r in _refs(template) if r.step is not None}


def _refs(template: Any) -> list[_Ref]:
    if isinstance(template, dict):
        return [r for v in template.values() for r in _refs(v)]
    if isinstance(template, list):
        return [r for v in template for r in _refs(v)]
    if not isinstance(template, str):
        return []
    return [r for m in _expressions(template) for r in _parse(m.group(1)).refs]


def input_paths(template: Any) -> set[str]:
    """Input references a template reads, as written (`input`, `input.email`, ...)."""
    return {r.text for r in _refs(template) if r.step is None}
