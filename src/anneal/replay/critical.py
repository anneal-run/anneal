"""Critical-field extraction and output equivalence (ANNEAL-ROADMAP.md M1.5, section 2).

Critical fields are matched exactly after normalization: amounts (as decimals),
ids, recipients, dates (as ISO) and negations. Text with no critical field in
either value falls back to a similarity score. M1 uses a lexical ratio as the
default; an embedding similarity can be passed in. There is no model judge.
Equivalence is evidence; the task check is the verdict.
"""

import difflib
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from anneal.canon.dates import parse_dates

Similarity = Callable[[str, str], float]
SIMILARITY_THRESHOLD = 0.8

_RECIPIENT = re.compile(
    r"<(?:EMAIL|PHONE)_\d+>|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
)
_PLACEHOLDER_ID = re.compile(r"<[A-Z]+_\d+>")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
_DATE = re.compile(
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b{_MONTH} \d{{1,2}}, \d{{4}}\b|\b\d{{1,2}} {_MONTH} \d{{4}}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{4}\b"
)
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b")
_ALNUM_ID = re.compile(
    r"\b(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b"
)
_AMOUNT = re.compile(r"[$€£]\s?\d[\d,]*(?:\.\d+)?|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+\.\d+\b")
_INTEGER = re.compile(r"\b\d{2,}\b")
_NEGATIONS = {
    "not", "no", "never", "none", "nothing", "nobody", "neither", "nor", "without",
    "cannot", "can't", "won't", "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't",
    "weren't", "shouldn't", "wouldn't", "couldn't", "haven't", "hasn't", "hadn't",
}  # fmt: skip


def _take(pattern: re.Pattern[str], text: str) -> tuple[list[str], str]:
    found = pattern.findall(text)
    return found, pattern.sub(" ", text)


def _amount(raw: str) -> str:
    try:
        return str(Decimal(re.sub(r"[$€£,\s]", "", raw)).normalize())
    except InvalidOperation:
        return raw


def _date(raw: str) -> str:
    dates = parse_dates(raw)
    return next(iter(dates)).isoformat() if len(dates) == 1 else raw


def critical_fields(text: str) -> dict[str, set[str]]:
    """Normalized critical values found in `text`, by category."""
    recipients, rest = _take(_RECIPIENT, text)
    placeholders, rest = _take(_PLACEHOLDER_ID, rest)
    dates, rest = _take(_DATE, rest)
    uuids, rest = _take(_UUID, rest)
    alnum, rest = _take(_ALNUM_ID, rest)
    amounts, rest = _take(_AMOUNT, rest)
    integers, rest = _take(_INTEGER, rest)
    words = re.findall(r"[a-z']+", text.lower())
    return {
        "amounts": {_amount(a) for a in amounts},
        "ids": {*placeholders, *(u.lower() for u in uuids), *alnum, *integers},
        "recipients": {r if r.startswith("<") else r.lower() for r in recipients},
        "dates": {_date(d) for d in dates},
        "negations": {w for w in words if w in _NEGATIONS},
    }


def lexical_similarity(a: str, b: str) -> float:
    def norm(s: str) -> str:
        return " ".join(re.findall(r"\w+", s.lower()))

    return difflib.SequenceMatcher(None, norm(a), norm(b), autojunk=False).ratio()


def equivalent(
    a: Any,
    b: Any,
    *,
    similarity: Similarity = lexical_similarity,
    threshold: float = SIMILARITY_THRESHOLD,
) -> bool:
    """Same structure; text leaves agree on critical fields exactly, or by similarity if none."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(
            equivalent(a[k], b[k], similarity=similarity, threshold=threshold) for k in a
        )
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(
            equivalent(x, y, similarity=similarity, threshold=threshold)
            for x, y in zip(a, b, strict=True)
        )
    if isinstance(a, str) and isinstance(b, str):
        fa, fb = critical_fields(a), critical_fields(b)
        if any(fa.values()) or any(fb.values()):
            return fa == fb
        return a == b or similarity(a, b) >= threshold
    return bool(a == b) and type(a) is type(b)
