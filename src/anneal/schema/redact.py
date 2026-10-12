"""Redaction with typed placeholders.

Sensitive values become `<TYPE_N>` placeholders. One `Redactor` instance is used
per run, so equal values map to the same placeholder within a run (which
provenance matching relies on), and numbering restarts for the next run, so
nothing links values across runs. Equality is judged on a normalized key:
emails ignore case, numeric identifiers ignore separators.

Placeholders never match a pattern, so redaction is idempotent.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from anneal.schema.models import Deopt, Event, Message, ModelCall, Run, ToolCall, ToolCallRequest


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text, flags=re.ASCII)


def _luhn(text: str) -> bool:
    digits = _digits(text)
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _iban(text: str) -> bool:
    compact = text.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rotated = compact[4:] + compact[:4]
    return int("".join(str(int(c, 36)) for c in rotated)) % 97 == 1


def _phone(text: str) -> bool:
    return 8 <= len(_digits(text)) <= 15


def _always(_: str) -> bool:
    return True


@dataclass(frozen=True)
class _Rule:
    kind: str
    pattern: re.Pattern[str]
    valid: Callable[[str], bool]
    key: Callable[[str], str]


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.ASCII)


# Applied in this order; earlier rules claim text before later, looser ones see it.
_RULES = (
    _Rule(
        "JWT",
        _compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"),
        _always,
        str,
    ),
    _Rule(
        "KEY",
        _compile(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
            r"|xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}"
            r"|lsv2_[a-z]{2}_[A-Za-z0-9_]{20,})"
        ),
        _always,
        str,
    ),
    _Rule(
        "EMAIL",
        _compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
        _always,
        str.lower,
    ),
    _Rule(
        "IBAN",
        _compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"),
        _iban,
        lambda s: s.replace(" ", ""),
    ),
    _Rule("CARD", _compile(r"(?<!\d)[2-6]\d(?:[ -]?\d){11,17}(?!\d)"), _luhn, _digits),
    _Rule(
        "PHONE",
        _compile(
            r"(?<![\w+])\+\d{1,3}[ .-]?\(?\d{1,4}\)?(?:[ .-]?\d{2,4}){2,4}(?!\w)"
            r"|(?:\(\d{3}\)|(?<!\d)\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)"
        ),
        _phone,
        _digits,
    ),
)


def _scan(rule: _Rule, text: str) -> Iterator[re.Match[str]]:
    """Yield non-overlapping valid matches. A candidate that fails validation
    only advances the scan by one character, so it cannot hide a valid match
    that overlaps it."""
    pos = 0
    while (m := rule.pattern.search(text, pos)) is not None:
        if rule.valid(m.group(0)):
            yield m
            pos = m.end()
        else:
            pos = m.start() + 1


def find_sensitive(text: str) -> list[tuple[str, str]]:
    """Return `(type, match)` for every sensitive value the rules detect in `text`."""
    return [(rule.kind, m.group(0)) for rule in _RULES for m in _scan(rule, text)]


class Redactor:
    """Replaces sensitive values with typed placeholders; use one instance per run."""

    def __init__(self) -> None:
        self._placeholders: dict[tuple[str, str], str] = {}
        self._counts: Counter[str] = Counter()

    def redact(self, value: Any) -> Any:
        """Redact every string leaf in `value`; dict keys and non-strings are kept."""
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, dict):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return type(value)(self.redact(v) for v in value)
        return value

    def _redact_text(self, text: str) -> str:
        for rule in _RULES:
            parts: list[str] = []
            pos = 0
            for m in _scan(rule, text):
                parts += [text[pos : m.start()], self._placeholder(rule, m.group(0))]
                pos = m.end()
            text = "".join(parts) + text[pos:]
        return text

    def _placeholder(self, rule: _Rule, raw: str) -> str:
        key = (rule.kind, rule.key(raw))
        if key not in self._placeholders:
            self._counts[rule.kind] += 1
            self._placeholders[key] = f"<{rule.kind}_{self._counts[rule.kind]}>"
        return self._placeholders[key]


def _redact_request(req: ToolCallRequest, red: Redactor) -> ToolCallRequest:
    return req.model_copy(update={"args": red.redact(req.args)})


def _redact_message(msg: Message, red: Redactor) -> Message:
    return msg.model_copy(
        update={
            "content": red.redact(msg.content),
            "tool_calls": [_redact_request(t, red) for t in msg.tool_calls],
        }
    )


def _redact_event(event: Event, red: Redactor) -> Event:
    match event:
        case ModelCall():
            return event.model_copy(
                update={
                    "messages": [_redact_message(m, red) for m in event.messages],
                    "output_text": red.redact(event.output_text),
                    "tool_calls_requested": [
                        _redact_request(t, red) for t in event.tool_calls_requested
                    ],
                }
            )
        case ToolCall():
            return event.model_copy(
                update={
                    "args": red.redact(event.args),
                    "result": red.redact(event.result),
                    "error": red.redact(event.error),
                }
            )
        case Deopt():
            return event.model_copy(update={"reason": red.redact(event.reason)})


def redact_run(run: Run) -> Run:
    """Return a copy of `run` with every content field redacted; ids and names are kept."""
    red = Redactor()
    return run.model_copy(
        update={
            "input": red.redact(run.input),
            "events": [_redact_event(e, red) for e in run.events],
            "output": red.redact(run.output),
        }
    )
