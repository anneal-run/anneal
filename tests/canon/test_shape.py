import re
from collections.abc import Sequence

import pytest

from anneal.canon.shape import ShapeVocab, leaves, shape, shape_hash


@pytest.mark.parametrize(
    ("value", "token"),
    [
        ("<EMAIL_3>", "ph:EMAIL"),
        ("jane@acme.com", "email"),
        ("https://acme.com/a?b=1", "url"),
        ("3f2b8c1e-9a4d-4e2b-8f1a-2c3d4e5f6a7b", "uuid"),
        ("2026-10-12", "date"),
        ("2026-10-12T09:00:00Z", "date"),
        ("2026-10-12 09:00:00.123+02:00", "date"),
        ("1234", "numstr"),
        ("-12.50", "numstr"),
        ("", "str[0]"),
        ("hello", "str[1-8]"),
        ("x" * 9, "str[9-32]"),
        ("x" * 33, "str[33-128]"),
        ("x" * 129, "str[129-512]"),
        ("x" * 513, "str[513+]"),
        (12, "num"),
        (1.5, "num"),
        (True, "bool"),
        (None, "null"),
    ],
)
def test_leaf_tokens(value: object, token: str) -> None:
    assert shape(value) == token


def test_objects_are_sorted_key_sets_with_child_shapes() -> None:
    assert shape({"b": 1, "a": "x"}) == "{a:str[1-8],b:num}"
    assert shape({}) == "{}"


def test_arrays_carry_element_shapes_and_a_length_bucket() -> None:
    assert shape([]) == "[]#0"
    assert shape([1]) == "[num]#1"
    assert shape([1, 2, 3]) == "[num]#2-4"
    assert shape([1, "a", 2, "b", 3]) == "[num|str[1-8]]#5-16"
    assert shape(list(range(17))) == "[num]#17+"


def test_coarse_shapes_drop_length_buckets() -> None:
    value = {"items": [{"sku": "A1", "note": "x" * 50}] * 3}
    assert shape(value, coarse=True) == "{items:[{note:str,sku:str}]}"


def test_shape_hash_is_stable_hex() -> None:
    assert shape_hash("{a:num}") == shape_hash("{a:num}") != shape_hash("{a:str}")
    assert re.fullmatch(r"[0-9a-f]{16}", shape_hash("{a:num}"))


def test_leaves_yield_json_paths() -> None:
    value = {"a": {"b": [10, {"c": "x"}]}, "weird key": 1}
    assert list(leaves(value)) == [
        ("$.a.b[0]", 10),
        ("$.a.b[1].c", "x"),
        ("$['weird key']", 1),
    ]
    assert [p for p, _ in leaves(value, wildcard=True)] == [
        "$.a.b[*]",
        "$.a.b[*].c",
        "$['weird key']",
    ]


def observations(values: Sequence[object], context: str = "args:route") -> list[tuple[str, object]]:
    return [(context, {"queue": v}) for v in values]


def test_enum_needs_few_values_covering_95_percent_with_support() -> None:
    queues = ["billing"] * 30 + ["tech"] * 15 + ["sales"] * 4 + ["other-1"]
    vocab = ShapeVocab.fit(observations(queues))
    assert vocab.is_enum("args:route", "$.queue")
    assert vocab.values("args:route", "$.queue") == {"billing", "tech", "sales", "other-1"}
    assert shape({"queue": "tech"}, vocab=vocab, context="args:route") == "{queue:enum}"
    assert shape({"queue": "tech"}, vocab=vocab, context="args:other") == "{queue:str[1-8]}"


def test_unique_identifiers_are_not_enums() -> None:
    vocab = ShapeVocab.fit(observations([f"id-{i}" for i in range(50)]))
    assert not vocab.is_enum("args:route", "$.queue")


def test_too_few_observations_are_not_enums() -> None:
    vocab = ShapeVocab.fit(observations(["a", "b", "a"]))
    assert not vocab.is_enum("args:route", "$.queue")


def test_long_tail_breaks_coverage() -> None:
    tail = [f"rare-{i}" for i in range(10)]  # 10 of 100 outside the top values
    vocab = ShapeVocab.fit(observations(["a"] * 60 + ["b"] * 30 + tail))
    assert not vocab.is_enum("args:route", "$.queue")


def test_enum_applies_only_to_plain_strings() -> None:
    vocab = ShapeVocab.fit(observations([1, 2] * 30))
    assert not vocab.is_enum("args:route", "$.queue")


def test_split_path_inverts_leaf_paths() -> None:
    from anneal.canon.shape import split_path

    value = {"a": {"b": [10, {"c": "x"}]}, "weird key": 1, "q'uote": 2}
    for path, _ in leaves(value):
        node: object = value
        for key in split_path(path):
            node = node[key]  # type: ignore[index]
        assert node == dict(leaves(value))[path]
    assert split_path("$") == []
