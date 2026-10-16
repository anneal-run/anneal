"""Copy the files an arm is allowed to see. P0 does not include the architecture menu."""

import json
from pathlib import Path
from typing import Literal

from anneal.challenge.budget import SearchBudget
from anneal.challenge.models import HarnessManifest

INSTRUCTION = (
    "Make this workflow cheaper or more correct without breaking its contract.\n"
    "Stay inside the budget in BUDGET.json. Record every model call through the harness meter.\n"
    "Start a new session whose only files are this directory. "
    "A session that already read the repository is not this run.\n"
)

MENU = """\
Candidate types you may use:
- collapse the loop into prefetch plus one structured call
- deterministic router plus a small model
- bounded workflow instead of a planner
- code for any step whose outputs are a deterministic function of state
- tool removal or re-description
- cheaper model with the same structure

At least three genuinely different architectures, not three prompts.
The budget is the constraint. If three architectures do not fit, run fewer, and that result counts.
"""

ENGINE = (
    "Caching, a model swap, and a prompt edit are not architectures.\n"
    "Submit at least three structurally different candidates.\n"
    "Every structural candidate includes a confidence-routed fallback to the original "
    "implementation. The fallback invokes that implementation, and those calls count in cost. "
    "Confidence comes from the candidate's own output or from agreement with a second cheap pass, "
    "never from labels. Report the fallback rate beside the cost.\n"
)

_EXCLUDED_FILES = {"ANNEAL-V3-PLAYBOOK.md", "ANNEAL-ROADMAP.md", "SEAL.json"}
_EXCLUDED_PREFIXES = ("baseline/", "report/", "docs/adr/")


def write_pack(
    source: Path,
    dest: Path,
    *,
    manifest: HarnessManifest,
    arm: Literal["A", "B", "C"],
    p0: bool,
    budget: SearchBudget,
) -> None:
    """Write an arm's working directory. Arm A does not get the harness. P0 does not get a menu."""
    if dest.exists():
        raise ValueError(f"{dest} already exists")
    dest.mkdir(parents=True)
    for relative in manifest.workflow_files:
        _copy_workflow_file(source, dest, relative, manifest.holdout_run_ids)
    if arm in {"B", "C"}:
        (dest / "manifest.json").write_text(
            json.dumps(manifest.proposer_payload(), indent=2) + "\n", encoding="utf-8"
        )
    (dest / "BUDGET.json").write_text(budget.model_dump_json(indent=2) + "\n", encoding="utf-8")
    prompt = INSTRUCTION
    if p0:
        prompt += (
            "No architecture menu is provided. "
            "Discover the change from the workflow and the traces.\n"
        )
    if arm == "C":
        prompt += ENGINE
    (dest / "PROMPT.md").write_text(prompt, encoding="utf-8")
    if arm == "C" and not p0:
        (dest / "MENU.md").write_text(MENU, encoding="utf-8")
    leaked = _leaks(dest, manifest.holdout_run_ids)
    if leaked:
        raise ValueError(f"holdout run id leaked into the pack: {leaked}")


def _excluded(relative: str) -> bool:
    path = relative.replace("\\", "/").lstrip("./")
    return path in _EXCLUDED_FILES or path.startswith(_EXCLUDED_PREFIXES)


def _copy_workflow_file(source: Path, dest: Path, relative: str, holdout_ids: list[str]) -> None:
    if _excluded(relative):
        raise ValueError(f"workflow file is on the answer-key path: {relative}")
    src = source / relative
    text = src.read_text(encoding="utf-8")
    for run_id in holdout_ids:
        if run_id in text:
            raise ValueError(f"holdout run {run_id} leaked into {relative}")
    target = dest / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _leaks(dest: Path, holdout_ids: list[str]) -> str | None:
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for run_id in holdout_ids:
            if run_id in text:
                return f"{run_id} in {path.relative_to(dest)}"
    return None
