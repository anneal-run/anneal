"""Shape abstraction: JSON values to class tokens.

Leaves become tokens (`email`, `url`, `uuid`, `date`, `numstr`, `ph:<TYPE>` for
redaction placeholders, `enum`, `str[<len>]`, `num`, `bool`, `null`); objects
become sorted key sets with child shapes; arrays become `[<element shapes>]#<len>`.
Coarse shapes drop length buckets, so values of different lengths share a shape
(used for skeletons).
"""

import ast
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from typing import Any

import blake3

_PLACEHOLDER = re.compile(r"<([A-Z]+)_\d+>")
_CLASSES = (
    ("email", re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")),
    ("url", re.compile(r"https?://\S+")),
    ("uuid", re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")),
    (
        "date",
        re.compile(
            r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
        ),
    ),
    ("numstr", re.compile(r"[+-]?\d+(?:\.\d+)?")),
)
_STR_BUCKETS = ((0, "0"), (8, "1-8"), (32, "9-32"), (128, "33-128"), (512, "129-512"))
_LEN_BUCKETS = ((0, "0"), (1, "1"), (4, "2-4"), (16, "5-16"))
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

ENUM_MAX_VALUES = 20
ENUM_MIN_COVERAGE = 0.95
ENUM_MIN_SUPPORT = 20


def _bucket(n: int, buckets: tuple[tuple[int, str], ...], top: str) -> str:
    return next((label for limit, label in buckets if n <= limit), top)


def _key(path: str, key: str) -> str:
    return f"{path}.{key}" if _IDENT.fullmatch(key) else f"{path}[{key!r}]"


_SEGMENT = re.compile(
    r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+|\*)\]|\[('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\]"
)


def split_path(path: str) -> list[str | int]:
    """Keys of a JSON path from `leaves`: `$.a[0]['b c']` gives `["a", 0, "b c"]`."""
    keys: list[str | int] = []
    for m in _SEGMENT.finditer(path[1:]):
        name, index, quoted = m.groups()
        if index is not None:
            keys.append(int(index))
        elif quoted is not None:
            keys.append(ast.literal_eval(quoted))
        else:
            keys.append(name)
    return keys


def leaves(value: Any, path: str = "$", wildcard: bool = False) -> Iterator[tuple[str, Any]]:
    """Yield `(json_path, leaf)` for every scalar in `value`; `wildcard` writes indices as `[*]`."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaves(v, _key(path, str(k)), wildcard)
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            yield from leaves(v, f"{path}[{'*' if wildcard else i}]", wildcard)
    else:
        yield path, value


def _string_class(text: str) -> str | None:
    if m := _PLACEHOLDER.fullmatch(text):
        return f"ph:{m.group(1)}"
    return next((name for name, rx in _CLASSES if rx.fullmatch(text)), None)


class ShapeVocab:
    """Per-path statistics that decide which string leaves are enums.

    A path is an enum when it has at least `ENUM_MIN_SUPPORT` string observations
    and the values that recur (seen twice or more) number at most `ENUM_MAX_VALUES`
    and cover at least `ENUM_MIN_COVERAGE` of the observations. Requiring recurrence
    keeps identifiers and long tails out. Paths are keyed by a context such as
    `args:<tool>` and a wildcard JSON path.
    """

    def __init__(self, counts: dict[tuple[str, str], Counter[str]]) -> None:
        self._counts = counts
        self._enums = {key for key, c in counts.items() if self._qualifies(c)}

    @staticmethod
    def _qualifies(counts: Counter[str]) -> bool:
        total = sum(counts.values())
        recurring = [n for n in counts.values() if n >= 2]
        return (
            total >= ENUM_MIN_SUPPORT
            and len(recurring) <= ENUM_MAX_VALUES
            and sum(recurring) >= ENUM_MIN_COVERAGE * total
        )

    @classmethod
    def fit(cls, observations: Iterable[tuple[str, Any]]) -> "ShapeVocab":
        """Count plain-string leaves of each `(context, value)` observation."""
        counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        for context, value in observations:
            for path, leaf in leaves(value, wildcard=True):
                if isinstance(leaf, str) and _string_class(leaf) is None:
                    counts[(context, path)][leaf] += 1
        return cls(dict(counts))

    def is_enum(self, context: str, path: str) -> bool:
        return (context, path) in self._enums

    def values(self, context: str, path: str) -> set[str]:
        """Every value observed at the path."""
        return set(self._counts.get((context, path), ()))


def shape(
    value: Any,
    *,
    coarse: bool = False,
    vocab: ShapeVocab | None = None,
    context: str = "",
    _path: str = "$",
) -> str:
    """Canonical shape string of a JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "num"
    if isinstance(value, str):
        if cls := _string_class(value):
            return cls
        if vocab and vocab.is_enum(context, _path):
            return "enum"
        return "str" if coarse else f"str[{_bucket(len(value), _STR_BUCKETS, '513+')}]"
    if isinstance(value, dict):
        fields = (
            f"{k}:{shape(v, coarse=coarse, vocab=vocab, context=context, _path=_key(_path, k))}"
            for k, v in sorted((str(k), v) for k, v in value.items())
        )
        return "{" + ",".join(fields) + "}"
    if isinstance(value, list | tuple):
        child = f"{_path}[*]"
        elems = sorted(
            {shape(v, coarse=coarse, vocab=vocab, context=context, _path=child) for v in value}
        )
        inner = "[" + "|".join(elems) + "]"
        return inner if coarse else f"{inner}#{_bucket(len(value), _LEN_BUCKETS, '17+')}"
    return type(value).__name__


def shape_hash(shape_str: str) -> str:
    """16-hex-character blake3 digest of a shape string."""
    return blake3.blake3(shape_str.encode()).hexdigest()[:16]
