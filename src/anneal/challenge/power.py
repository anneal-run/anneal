"""Refuse a verdict when the holdout cannot resolve the registered correctness margin."""

import math

from anneal.challenge.stats import _Z, _Z_BETA, CORRECTNESS_NULL_VARIANCE
from anneal.challenge.verdict import CORRECTNESS_MARGIN_POINTS


def minimum_detectable_effect(n: int) -> float:
    """Planning effect, in correctness points, at 80% power under the null variance."""
    if n < 1:
        raise ValueError("holdout needs at least one case")
    return (_Z + _Z_BETA) * math.sqrt(CORRECTNESS_NULL_VARIANCE / n) * 100


def n_required(margin_points: float = CORRECTNESS_MARGIN_POINTS) -> int:
    """Smallest holdout whose minimum detectable effect is within the margin."""
    if margin_points <= 0:
        raise ValueError("margin must be positive")
    z = _Z + _Z_BETA
    target = margin_points / (100.0 * z)
    guess = math.ceil(CORRECTNESS_NULL_VARIANCE / (target * target))
    while minimum_detectable_effect(guess) > margin_points:
        guess += 1
    return guess


def adjudication(n: int, *, margin_points: float = CORRECTNESS_MARGIN_POINTS) -> str | None:
    """The refusal line when this holdout cannot support the margin. Otherwise nothing."""
    if n < 1 or minimum_detectable_effect(n) > margin_points:
        return f"cannot adjudicate; n required: {n_required(margin_points)}"
    return None
