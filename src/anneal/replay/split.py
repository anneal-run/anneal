"""Chronological compile/holdout split. Compilation never sees a holdout run."""

import math
from collections.abc import Sequence

from anneal.schema import Run


def chronological_split(
    runs: Sequence[Run], compile_share: float = 0.7
) -> tuple[list[Run], list[Run]]:
    """The first `compile_share` of runs by start time (ties by run_id), and the rest."""
    if not 0 < compile_share < 1:
        raise ValueError("compile_share must be strictly between 0 and 1")
    if len(runs) < 2:
        raise ValueError("need at least two runs to split")
    ordered = sorted(runs, key=lambda r: (r.started_at, r.run_id))
    cut = min(max(math.floor(len(ordered) * compile_share), 1), len(ordered) - 1)
    return ordered[:cut], ordered[cut:]
