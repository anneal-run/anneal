"""Structured-output validation (a JSON Schema subset) and input guards."""

import re
from collections.abc import Sequence
from typing import Any

from anneal.canon.shape import string_class
from anneal.compile.plan import Guard
from anneal.compile.template import TemplateError, render
from anneal.schema.redact import find_sensitive

_TYPES: dict[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


def schema_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Errors of `value` against the subset the compiler emits: type, enum, properties,
    required, additionalProperties, items. An empty list means valid."""
    where = path.removeprefix("$.") if path != "$" else "value"
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where}: not one of {schema['enum']}"]
    kind = schema.get("type")
    if isinstance(kind, list):  # ["integer", "null"]
        if not any(_TYPES[k](value) for k in kind):
            return [f"{where}: expected one of {kind}"]
        kind = next(k for k in kind if _TYPES[k](value))
    if kind and not _TYPES[kind](value):
        return [f"{where}: expected {kind}"]
    errors: list[str] = []
    if kind == "object":
        props: dict[str, Any] = schema.get("properties", {})
        errors += [
            f"{path}.{k}: required".removeprefix("$.")
            for k in schema.get("required", [])
            if k not in value
        ]
        for k, v in value.items():
            if k in props:
                errors += schema_errors(v, props[k], f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{k}: not allowed".removeprefix("$."))
    if kind == "array" and "items" in schema:
        for i, item in enumerate(value):
            errors += schema_errors(item, schema["items"], f"{path}[{i}]".removeprefix("$"))
    return errors


def _redaction_class(value: str) -> str | None:
    """`ph:<TYPE>` when the whole value is one sensitive value redaction would replace."""
    found = find_sensitive(value)
    if len(found) == 1 and found[0][1] == value.strip():
        return f"ph:{found[0][0]}"
    return None


def _class_matches(value: str, cls: str) -> bool:
    """A raw value and its redaction placeholder share a class: guards mined from the
    redacted store must accept live input, and the other way round."""
    own = string_class(value)
    kinds = {own, _redaction_class(value)}
    if own == "ph:EMAIL":
        kinds.add("email")
    if "email" in kinds:
        kinds.add("ph:EMAIL")
    return cls in kinds


def _passes(guard: Guard, value: Any) -> bool:
    p = guard.params
    match guard.kind:
        case "schema":
            return "type" not in p or bool(_TYPES[p["type"]](value))
        case "enum":
            return value in p["values"]
        case "range":
            ok = isinstance(value, int | float) and not isinstance(value, bool)
            return ok and p.get("min", value) <= value <= p.get("max", value)
        case "length":
            return isinstance(value, str | list) and p.get("min", 0) <= len(value) <= p.get(
                "max", len(value)
            )
        case "pattern":
            if not isinstance(value, str):
                return False
            if "class" in p:
                return _class_matches(value, p["class"])
            return re.fullmatch(p["regex"], value) is not None


def failing_guard(guards: Sequence[Guard], run_input: Any) -> Guard | None:
    """The first guard the input fails, or None. A missing path fails every kind of guard."""
    for guard in guards:
        try:
            value = render("{{" + guard.path + "}}", {"input": run_input, "steps": {}})
        except TemplateError:
            return guard
        if not _passes(guard, value):
            return guard
    return None
