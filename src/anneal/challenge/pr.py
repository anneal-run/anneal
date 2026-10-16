"""A pull request a partner can open. Nothing here deploys or pushes."""

from pathlib import Path


def write_pull_request(
    dest: Path,
    *,
    workflow: str,
    winner: str,
    verdict: Path,
    fixtures: Path,
) -> None:
    """Write the PR body, the rollback note, and a test that the fixtures are present."""
    if dest.exists():
        raise ValueError(f"{dest} already exists")
    if not verdict.is_file():
        raise ValueError(f"verdict report not found: {verdict}")
    if not fixtures.is_file():
        raise ValueError(f"fixtures not found: {fixtures}")
    dest.mkdir(parents=True)
    flag = "ANNEAL_" + "".join(ch if ch.isalnum() else "_" for ch in workflow.upper())
    (dest / "PR.md").write_text(
        (
            f"# {workflow}: {winner}\n\n"
            f"`{winner}` runs only when `{flag}` is set. "
            "With the flag unset, the original implementation runs. "
            "It also runs when the winner declines a case, and that cost is charged.\n\n"
            "## Tests\n\n"
            f"The harness fixtures are `{fixtures.as_posix()}`. "
            "`test_fixtures.py` checks that file is present.\n\n"
            "## Verdict\n\n"
            f"{verdict.as_posix()}\n\n"
            "## Rollback\n\n"
            f"See `rollback.md`. Unset `{flag}`. "
            "There is no migration, and nothing in this change deploys.\n\n"
            "## Shadow\n\n"
            "`shadow_runner.py` runs the original implementation and the winner on the same case, "
            "returns the original result, and appends the pair. "
            "`anneal challenge shadow` prints the verdict and the n reached. "
            "It stops early only when that difference is clearly outside the margin "
            "in `anneal.toml`.\n"
        ),
        encoding="utf-8",
    )
    (dest / "rollback.md").write_text(
        (
            f"Unset `{flag}`. The original implementation is still on the path "
            "and runs for every case. Nothing was deployed.\n"
        ),
        encoding="utf-8",
    )
    (dest / "shadow_runner.py").write_text(_SHADOW_RUNNER, encoding="utf-8")
    (dest / "test_fixtures.py").write_text(
        (
            '"""The harness fixtures travel with the change."""\n\n'
            "from pathlib import Path\n\n"
            f"FIXTURES = Path({str(fixtures)!r})\n\n\n"
            "def test_harness_fixtures_present() -> None:\n"
            "    assert FIXTURES.is_file()\n"
        ),
        encoding="utf-8",
    )


_SHADOW_RUNNER = '''\
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
        handle.write(json.dumps(row) + "\\n")


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
'''
