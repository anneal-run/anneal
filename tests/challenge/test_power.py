"""The evaluator prints the minimum detectable effect and refuses an underpowered holdout."""

from anneal.challenge.power import adjudication, minimum_detectable_effect, n_required


def test_forty_two_cases_cannot_resolve_a_two_point_margin() -> None:
    assert minimum_detectable_effect(42) > 30
    assert adjudication(42) == f"cannot adjudicate; n required: {n_required()}"


def test_the_required_holdout_can_resolve_the_margin() -> None:
    needed = n_required()
    assert adjudication(needed) is None
    assert adjudication(needed - 1) == f"cannot adjudicate; n required: {needed}"
