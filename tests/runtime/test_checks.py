from typing import Any

import pytest

from anneal.compile.plan import Guard
from anneal.runtime.checks import failing_guard, schema_errors

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool": {"enum": ["a", "b"]},
        "n": {"type": "integer"},
        "x": {"type": "number"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "flag": {"type": "boolean"},
        "none": {"type": "null"},
    },
    "required": ["tool", "n"],
    "additionalProperties": False,
}


def test_valid_output_has_no_errors() -> None:
    value = {"tool": "a", "n": 1, "x": 1.5, "tags": ["t"], "flag": True, "none": None}
    assert schema_errors(value, SCHEMA) == []
    assert schema_errors({"tool": "a", "n": 2, "x": 3}, SCHEMA) == []  # integers are numbers


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ({"n": 1}, "tool: required"),
        ({"tool": "c", "n": 1}, "tool: not one of"),
        ({"tool": "a", "n": True}, "n: expected integer"),
        ({"tool": "a", "n": 1.5}, "n: expected integer"),
        ({"tool": "a", "n": 1, "extra": 1}, "extra: not allowed"),
        ({"tool": "a", "n": 1, "tags": [1]}, "tags[0]: expected string"),
        ("nope", "expected object"),
    ],
)
def test_errors_name_the_path(value: Any, fragment: str) -> None:
    assert any(fragment in e for e in schema_errors(value, SCHEMA)), schema_errors(value, SCHEMA)


def guard(kind: str, **params: Any) -> Guard:
    return Guard(id=kind, kind=kind, path="input.v", params=params)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("g", "ok", "bad"),
    [
        (guard("schema", type="string"), "x", 3),
        (guard("enum", values=["a", "b"]), "a", "c"),
        (guard("range", min=1, max=10), 5, 11),
        (guard("length", min=2, max=4), "abc", "abcdef"),
        (guard("pattern", regex=r"C-\d+"), "C-12", "X-12"),
    ],
)
def test_guards(g: Guard, ok: Any, bad: Any) -> None:
    assert failing_guard([g], {"v": ok}) is None
    assert failing_guard([g], {"v": bad}) == g
    assert failing_guard([g], {}) == g  # a missing path fails every guard


def test_pattern_guards_can_name_a_string_class() -> None:
    g = guard("pattern", **{"class": "email"})
    assert failing_guard([g], {"v": "a@b.io"}) is None
    assert failing_guard([g], {"v": "not an email"}) == g


@pytest.mark.parametrize(
    ("mined", "value"),
    [
        ("ph:EMAIL", "jane@acme.com"),  # compiled from the redacted store, run on live input
        ("email", "<EMAIL_3>"),  # compiled from raw traces, run on redacted input
        ("ph:CARD", "4111 1111 1111 1111"),
        ("ph:PHONE", "+1 415 555 0132"),
    ],
)
def test_a_value_and_its_redaction_placeholder_share_a_class(mined: str, value: str) -> None:
    g = guard("pattern", **{"class": mined})
    assert failing_guard([g], {"v": value}) is None
    assert failing_guard([g], {"v": "plain text"}) == g


def test_nullable_type_lists() -> None:
    from anneal.runtime.checks import schema_errors

    schema = {"type": ["integer", "null"]}
    assert schema_errors(3, schema) == [] and schema_errors(None, schema) == []
    assert schema_errors("3", schema) == ["value: expected one of ['integer', 'null']"]
