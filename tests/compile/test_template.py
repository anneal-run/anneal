from typing import Any

import pytest

from anneal.compile.template import TemplateError, references, render

CTX: dict[str, Any] = {
    "input": {
        "email": "  Jane@Acme.com ",
        "items": [{"sku": "A1"}],
        "n": 3,
        "when": "Oct 12, 2026",
    },
    "steps": {
        "s0": {"result": {"customer_id": "C-42", "tier": "gold", "weird key": 1}},
        "s1": {"result": {"text": "hello"}},
    },
}


def r(template: Any) -> Any:
    return render(template, CTX)


def test_paths_into_input_and_step_results() -> None:
    assert r("{{input.items[0].sku}}") == "A1"
    assert r("{{steps.s0.result.customer_id}}") == "C-42"
    assert r("{{steps.s0.result['weird key']}}") == 1


def test_single_expression_keeps_the_value_type() -> None:
    assert r("{{input.n}}") == 3
    assert r("{{steps.s0.result}}") == CTX["steps"]["s0"]["result"]
    assert r("{{input}}") == CTX["input"]


def test_expressions_inside_text_are_stringified_json_for_objects() -> None:
    assert r("tier={{steps.s0.result.tier}} n={{input.n}}") == "tier=gold n=3"
    assert r("x {{input.items}}") == 'x [{"sku": "A1"}]'


def test_filters_chain_left_to_right() -> None:
    assert r("{{input.email | trim}}") == "Jane@Acme.com"
    assert r("{{input.email | trim | lower}}") == "jane@acme.com"
    assert r("{{ input.when | fmt_date('%Y-%m-%d') }}") == "2026-10-12"


def test_concat_with_separator() -> None:
    assert (
        r("{{concat(steps.s0.result.customer_id, steps.s0.result.tier, sep='-')}}") == "C-42-gold"
    )
    assert r("{{concat(steps.s0.result.tier, input.n)}}") == "gold3"


def test_structures_render_recursively_and_literals_pass_through() -> None:
    template = {"to": "{{input.email | trim}}", "tags": ["{{steps.s0.result.tier}}", 7], "x": None}
    assert r(template) == {"to": "Jane@Acme.com", "tags": ["gold", 7], "x": None}


@pytest.mark.parametrize(
    "bad",
    [
        "{{input.missing}}",
        "{{input.items[5].sku}}",
        "{{steps.s9.result}}",
        "{{steps.s0.output}}",
        "{{input.email | upper}}",
        "{{env.HOME}}",
        "{{input.email",
        "{{ input.when | fmt_date('%Y') | nope }}",
        "{{ input.email | fmt_date('%Y-%m-%d') }}",
    ],
)
def test_unknown_paths_filters_and_syntax_are_errors(bad: str) -> None:
    with pytest.raises(TemplateError):
        r(bad)


def test_references_lists_step_ids() -> None:
    template = {"a": "{{steps.s0.result.x}} and {{steps.s1.result}}", "b": ["{{input.n}}"]}
    assert references(template) == {"s0", "s1"}
    assert references("{{concat(steps.s2.result.a, input.b, sep=' ')}}") == {"s2"}
    with pytest.raises(TemplateError):
        references("{{nope}}")


def test_input_paths_lists_input_references() -> None:
    from anneal.compile.template import input_paths

    template = {
        "a": "{{input.email | trim}} {{input}}",
        "b": "{{concat(input.x[0], steps.s0.result)}}",
    }
    assert input_paths(template) == {"input.email", "input", "input.x[0]"}
