"""Regenerate report/m1.8-synthetic-dry-run.md: `uv run python tests/synth/dry_run.py`."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from anneal.replay.arms import render_markdown
from synth.arms import BASELINE_DIR, run_experiment

OUT = Path(__file__).parents[2] / "report" / "m1.8-synthetic-dry-run.md"


def baseline_build_time() -> str:
    log = BASELINE_DIR / "BUILD_LOG.md"
    m = re.search(r"Time spent: ([^(\n]+)", log.read_text()) if log.exists() else None
    return m.group(1).strip() + " (agent)" if m else "n/a"


def main() -> None:
    e = run_experiment()
    table = render_markdown(
        e.report,
        build_time={
            "tier0": "n/a (existing agent)",
            "compiled": f"{e.compile_seconds:.2f} s compute + tool declarations",
            "baseline": baseline_build_time(),
        },
    )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        "# M1.8 three-arm dry run (synthetic)\n\n"
        "Synthetic environment and simulated model (`tests/synth/env.py`). These numbers test the "
        "protocol, not the product, and are not Gate 1 evidence. Interpretation: ADR 0009.\n\n"
        f"Compiled on {e.compile_runs} runs, compared on {e.holdout_runs} later runs "
        "and on the same runs under each drift. Every model call costs the same in every arm.\n\n"
        f"Compiled plan: `{e.plan.plan_id}`.\n\n" + table
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
