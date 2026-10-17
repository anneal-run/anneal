"""Shadow the winner beside the original implementation. The caller sees the original result."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def append_pair(
    path: Path,
    case_id: str,
    *,
    baseline_correct: bool,
    candidate_correct: bool,
) -> None:
    row = {
        "case_id": case_id,
        "baseline_correct": baseline_correct,
        "candidate_correct": candidate_correct,
    }
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def run_shadow(
    case_id: str,
    case: Any,
    original: Callable[[Any], Any],
    candidate: Callable[[Any], Any],
    judge: Callable[[Any], bool],
    path: Path,
) -> Any:
    baseline = original(case)
    proposed = candidate(case)
    append_pair(
        path,
        case_id,
        baseline_correct=bool(judge(baseline)),
        candidate_correct=bool(judge(proposed)),
    )
    return baseline
