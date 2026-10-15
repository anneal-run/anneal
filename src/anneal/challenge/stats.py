"""Intervals for paired case results. The minimum detectable effect uses the null variance."""

import math
from dataclasses import dataclass

_Z = 1.96
_Z_BETA = 0.8416212335729143  # 80% power
CORRECTNESS_NULL_VARIANCE = 0.5  # independent fair coins; a paired difference cannot be noisier


@dataclass(frozen=True)
class Interval:
    estimate: float
    low: float
    high: float
    mde: float

    @property
    def half_width(self) -> float:
        return (self.high - self.low) / 2


def interval(values: list[float], *, null_variance: float | None) -> Interval:
    """Mean of paired differences.

    `null_variance` sets the planning minimum detectable effect, and the interval
    when the sample variance is zero.
    """
    if not values:
        raise ValueError("need at least one case")
    n = len(values)
    estimate = sum(values) / n
    variance = sum((value - estimate) ** 2 for value in values) / (n - 1) if n > 1 else 0.0
    if variance > 0:
        standard_error = math.sqrt(variance / n)
    elif null_variance is not None:
        standard_error = math.sqrt(null_variance / n)
    else:
        standard_error = 0.0
    if null_variance is not None:
        mde = (_Z + _Z_BETA) * math.sqrt(null_variance / n)
    else:
        mde = (_Z + _Z_BETA) * standard_error
    half = _Z * standard_error
    return Interval(estimate, estimate - half, estimate + half, mde)
