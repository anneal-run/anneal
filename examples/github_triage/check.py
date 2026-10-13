"""The task check for triage: did the agent's triage match what maintainers did?

A triage counts as the job done when both hold:
- labels: every suggested label exists in the repo, and at least one of them is a
  label maintainers actually applied;
- duplicate: if maintainers closed the issue as a duplicate of #N, `duplicate_of`
  is N; otherwise `duplicate_of` is null.

The draft reply is not judged. The limits of this proxy are in RUBRIC.md.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from anneal.schema import Run
from github_triage.select_issues import Truth


@dataclass(frozen=True)
class Verdict:
    labels_ok: bool
    duplicate_ok: bool
    reason: str

    @property
    def ok(self) -> bool:
        return self.labels_ok and self.duplicate_ok


def judge(triage: Any, truth: Truth, label_set: set[str]) -> Verdict:
    if not isinstance(triage, dict):
        return Verdict(False, False, "no triage")
    suggested = set(triage.get("suggested_labels") or [])
    unknown = suggested - label_set
    overlap = suggested & set(truth.labels)
    labels_ok = bool(suggested) and not unknown and bool(overlap)
    dup = triage.get("duplicate_of")
    duplicate_ok = dup == truth.duplicate_of
    reasons = []
    if unknown:
        reasons.append(f"labels not in repo: {sorted(unknown)}")
    if not overlap:
        reasons.append(f"no overlap with {truth.labels}")
    if not duplicate_ok:
        reasons.append(f"duplicate_of {dup}, maintainers {truth.duplicate_of}")
    return Verdict(labels_ok, duplicate_ok, "; ".join(reasons) or "ok")


def find_triage(output: Any) -> Any:
    """The triage dict inside a run output (the graph state, or the triage itself)."""
    if isinstance(output, dict):
        if "suggested_labels" in output:
            return output
        for value in output.values():
            if (found := find_triage(value)) is not None:
                return found
    return None


_REF = re.compile(r"issue #(\d+) in ([\w.-]+/[\w.-]+?)\.?(?:\s|\"|$)")


def issue_ref(run_input: Any) -> tuple[str, int]:
    """(repo, number) of a run input: `{"repo", "number"}`, or the agent's first message."""
    if isinstance(run_input, dict) and "repo" in run_input and "number" in run_input:
        return str(run_input["repo"]), int(run_input["number"])
    m = _REF.search(json.dumps(run_input))
    if m is None:
        raise ValueError(f"no issue reference in {str(run_input)[:200]}")
    return m.group(2), int(m.group(1))


class RunCheck:
    """`anneal replay --check`-style task check: `check(run, recorded) -> bool`."""

    def __init__(self, truths: dict[tuple[str, int], Truth], labels: dict[str, set[str]]) -> None:
        self.truths = truths
        self.labels = labels
        self.__qualname__ = "RunCheck"

    def __call__(self, run: Run, recorded: Run) -> bool:
        repo, number = issue_ref(recorded.input)
        truth = self.truths[(repo, number)]
        return (
            run.status == "success" and judge(find_triage(run.output), truth, self.labels[repo]).ok
        )
