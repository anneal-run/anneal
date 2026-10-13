"""Tests for the github_triage baseline, with fake Tools and Model."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from interface import ToolError  # noqa: E402
import workflow  # noqa: E402
from workflow import build_queries, clean_body, run, usable_labels, validate_labels  # noqa: E402

LABELS = [
    {"name": "bug", "description": "Something isn't working"},
    {"name": "enhancement", "description": "New feature or improvement"},
    {"name": "question", "description": "Asking for clarification or support"},
    {"name": "duplicate", "description": "This issue or pull request already exists"},
    {"name": "area:windows", "description": "Specific to the Windows platform"},
    {"name": "build:skip", "description": "Disable additional builds for a pull request"},
]

ISSUE = {
    "number": 200,
    "title": "[BUG] Crash with `OPENSSL_Applink` on Windows",
    "body": "### Summary\n<!-- describe -->\nRunning `foo venv` crashes.\nerror: OPENSSL_Uplink no OPENSSL_Applink\n",
    "author": "<USER_1>",
    "created_at": "2026-05-01T00:00:00Z",
}
EARLIER = {
    "number": 150,
    "title": "`OPENSSL_Applink` error on Windows",
    "body": "Same crash.",
    "author": "x",
    "created_at": "2025-06-27T00:00:00Z",
}
SEARCH = [
    {"number": 150, "title": "`OPENSSL_Applink` error on Windows", "state": "open", "created_at": "2025-06-27T00:00:00Z"},
    {"number": 90, "title": "Unrelated thing", "state": "closed", "created_at": "2024-01-01T00:00:00Z"},
]


class FakeTools:
    def __init__(self, issues: dict[int, dict[str, Any]], labels: list[dict[str, str]],
                 search: list[dict[str, Any]] | None = None) -> None:
        self.issues, self.labels, self.search = issues, labels, search or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((name, args))
        if name == "get_issue":
            if args["number"] not in self.issues:
                raise ToolError(f"no issue {args['number']}")
            return dict(self.issues[args["number"]])
        if name == "list_labels":
            return self.labels
        if name == "search_similar_issues":
            return self.search
        raise ToolError(f"unknown tool {name}")


class FakeModel:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str, Any]] = []

    def complete(self, system: str, user: str, schema: dict[str, Any] | None = None) -> Any:
        self.calls.append((system, user, schema))
        ans = self.answers.pop(0)
        if isinstance(ans, Exception):
            raise ans
        return ans


def triage(labels: list[str], dup: int = 0, conf: str = "low", reply: str = "Thanks!") -> dict[str, Any]:
    return {"labels": labels, "duplicate_of": dup, "duplicate_confidence": conf,
            "duplicate_reason": "", "draft_reply": reply}


def tools() -> FakeTools:
    return FakeTools({200: ISSUE, 150: EARLIER}, LABELS, SEARCH)


def test_no_duplicate_one_model_call_and_labels_validated() -> None:
    t, m = tools(), FakeModel(triage(["BUG", "area:windows", "not-a-label", "bug"]))
    out = run("o/r", 200, t, m)
    assert out == {"suggested_labels": ["bug", "area:windows"], "duplicate_of": None, "draft_reply": "Thanks!"}
    assert len(m.calls) == 1
    prompt = m.calls[0][1]
    assert "#150" in prompt and "build:skip" not in prompt and "<!--" not in prompt


def test_confirmed_duplicate_adds_duplicate_label() -> None:
    m = FakeModel(triage(["bug"], dup=150, conf="high", reply="See #150."),
                  {"same_problem": True, "reply_if_not_duplicate": ""})
    out = run("o/r", 200, tools(), m)
    assert out["duplicate_of"] == 150
    assert out["suggested_labels"] == ["bug", "duplicate"]
    assert out["draft_reply"] == "See #150."
    assert len(m.calls) == 2 and "Same crash." in m.calls[1][1]


def test_rejected_duplicate_drops_label_and_rewrites_reply() -> None:
    m = FakeModel(triage(["bug", "duplicate"], dup=150, conf="high", reply="See #150."),
                  {"same_problem": False, "reply_if_not_duplicate": "Thanks, can you share a repro?"})
    out = run("o/r", 200, tools(), m)
    assert out["duplicate_of"] is None
    assert out["suggested_labels"] == ["bug"]
    assert out["draft_reply"] == "Thanks, can you share a repro?"


@pytest.mark.parametrize("dup,conf", [(150, "medium"), (999, "high"), (200, "high")])
def test_unsure_or_unsearched_duplicate_is_none(dup: int, conf: str) -> None:
    m = FakeModel(triage(["bug"], dup=dup, conf=conf))
    out = run("o/r", 200, tools(), m)
    assert out["duplicate_of"] is None and len(m.calls) == 1


def test_unconfirmable_duplicate_kept_when_candidate_fetch_fails() -> None:
    t = FakeTools({200: ISSUE}, LABELS, SEARCH)  # 150 cannot be fetched
    out = run("o/r", 200, t, FakeModel(triage(["bug"], dup=150, conf="high")))
    assert out["duplicate_of"] == 150


def test_invalid_labels_retry_then_raise() -> None:
    m = FakeModel(triage(["nope"]), triage(["still-nope"]))
    with pytest.raises(RuntimeError, match="no valid label"):
        run("o/r", 200, tools(), m)
    assert "Choose from exactly" in m.calls[1][1]


def test_invalid_labels_recovered_on_retry() -> None:
    out = run("o/r", 200, tools(), FakeModel(triage(["nope"]), triage(["question"])))
    assert out["suggested_labels"] == ["question"]


def test_unparseable_model_answer_retried_once() -> None:
    out = run("o/r", 200, tools(), FakeModel(ValueError("bad json"), triage(["bug"])))
    assert out["suggested_labels"] == ["bug"]
    with pytest.raises(ValueError):
        run("o/r", 200, tools(), FakeModel(ValueError("a"), ValueError("b")))


def test_errors_are_loud() -> None:
    with pytest.raises(ToolError):
        run("o/r", 404, tools(), FakeModel())
    with pytest.raises(ValueError):
        run("not-a-repo", 1, tools(), FakeModel())
    with pytest.raises(RuntimeError, match="no labels"):
        run("o/r", 200, FakeTools({200: ISSUE}, []), FakeModel())
    with pytest.raises(RuntimeError, match="empty reply"):
        run("o/r", 200, tools(), FakeModel(triage(["bug"], reply="  ")))


def test_no_search_results_still_triages() -> None:
    t = FakeTools({200: ISSUE}, LABELS, [])
    m = FakeModel(triage(["bug"]))
    out = run("o/r", 200, t, m)
    assert out["duplicate_of"] is None
    assert "no earlier issues" in m.calls[0][1]
    assert sum(1 for n, _ in t.calls if n == "search_similar_issues") <= workflow.MAX_QUERIES


def test_build_queries_short_and_clean() -> None:
    qs = build_queries("astral-sh/uv", "[BUG] `uv self update` breaks from v0.10.9 to v0.10.12", "")
    assert qs and all(len(q.split()) <= 4 for q in qs)
    assert all("uv" not in q.split() and "0.10.9" not in q and "bug" not in q.split() for q in qs)
    assert build_queries("o/r", "Support PEP 803", None) == ["pep 803"]
    assert build_queries("o/r", "Feature request: add --frozen flag to sync", "")[0].startswith("frozen")
    assert build_queries("o/r", "it does not work", "") == ["does not work"]


def test_helpers() -> None:
    assert "build:skip" not in [lab["name"] for lab in usable_labels(LABELS)]
    assert "duplicate" in [lab["name"] for lab in usable_labels(LABELS)]  # mentions "issue"
    assert validate_labels(["Bug", 3, "x"], usable_labels(LABELS)) == ["bug"]
    long = clean_body("a" * 10_000)
    assert len(long) < 4100 and long.endswith("[... truncated]")


def _recorded_runs() -> list[dict[str, Any]]:
    path = HERE / "traces.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open()]


def test_replay_against_recorded_tool_results() -> None:
    """Every recorded issue runs end to end with recorded tool results and <= 2 model calls."""
    runs = _recorded_runs()
    if not runs:
        pytest.skip("traces.jsonl not present")
    for r in runs:
        tool_events = [e for e in r["events"] if e["kind"] == "tool_call"]
        issue = next(e["result"] for e in tool_events if e["name"] == "get_issue")
        labels = next(e["result"] for e in tool_events if e["name"] == "list_labels")
        results: list[dict[str, Any]] = []
        for e in tool_events:
            if e["name"] == "search_similar_issues":
                results.extend(e["result"] or [])
        others = {e["result"]["number"]: e["result"] for e in tool_events
                  if e["name"] == "get_issue" and e["result"]["number"] != issue["number"]}
        t = FakeTools({issue["number"]: issue, **others}, labels, results[:5])
        want = r["output"]["triage"]
        m = FakeModel(triage(want["suggested_labels"], dup=want["duplicate_of"] or 0,
                             conf="high", reply=want["draft_reply"]),
                      {"same_problem": True, "reply_if_not_duplicate": ""})
        out = run("astral-sh/uv", issue["number"], t, m)
        assert out["suggested_labels"], issue["number"]
        assert set(out["suggested_labels"]) <= {lab["name"] for lab in labels}
        assert len(m.calls) <= 2
        assert sum(1 for n, _ in t.calls if n == "search_similar_issues") <= workflow.MAX_QUERIES
