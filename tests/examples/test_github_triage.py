"""The github_triage example, offline: fake GitHub transport and a scripted chat model."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from github_triage.agent import Triage, build_agent, first_message
from github_triage.check import RunCheck, find_triage, issue_ref, judge
from github_triage.github import CacheMiss, GitHub
from github_triage.select_issues import Truth, select
from github_triage.tools import Tools, triaging
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from anneal.schema import Run

REPO = "acme/widgets"
ISSUES: dict[int, dict[str, Any]] = {
    7: {
        "number": 7,
        "title": "Crash on start",
        "body": "It crashes.",
        "user": {"login": "a"},
        "created_at": "2026-01-01T00:00:00Z",
        "labels": [{"name": "bug"}],
        "state": "closed",
        "state_reason": "completed",
    },
    9: {
        "number": 9,
        "title": "Crash when starting",
        "body": "x" * 5000,
        "user": {"login": "b"},
        "created_at": "2026-02-01T00:00:00Z",
        "labels": [{"name": "duplicate"}],
        "state": "closed",
        "state_reason": "duplicate",
    },
}
LABELS = [{"name": "bug", "description": "broken"}, {"name": "duplicate", "description": None}]


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == f"/repos/{REPO}/labels":
        return httpx.Response(200, json=LABELS)
    if path.startswith(f"/repos/{REPO}/issues/") and path.endswith("/comments"):
        number = int(path.split("/")[-2])
        body = "Duplicate of #7" if number == 9 else "thanks"
        return httpx.Response(200, json=[{"body": body}])
    if path.startswith(f"/repos/{REPO}/issues/"):
        return httpx.Response(200, json=ISSUES[int(path.rsplit("/", 1)[1])])
    if path == "/graphql":
        number = json.loads(request.content)["variables"]["number"]
        nodes = (
            [{"duplicateOf": {"number": 7}}]
            if number == 9 and request.headers.get("x-native")
            else [{}]
        )
        issue = {"timelineItems": {"nodes": nodes}}
        return httpx.Response(200, json={"data": {"repository": {"issue": issue}}})
    if path == "/search/issues":
        return httpx.Response(200, json={"items": list(ISSUES.values())})
    return httpx.Response(404)


@pytest.fixture
def gh(tmp_path: Path) -> GitHub:
    return GitHub(
        token="t", cache_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_responses_are_cached_and_offline_mode_never_calls_github(gh: GitHub) -> None:
    assert gh.get(f"/repos/{REPO}/labels") == LABELS
    assert gh.get(f"/repos/{REPO}/labels") == LABELS
    assert gh.requests == 1
    offline = GitHub(cache_dir=gh.cache_dir, offline=True)
    assert offline.get(f"/repos/{REPO}/labels") == LABELS
    with pytest.raises(CacheMiss):
        offline.get(f"/repos/{REPO}/issues/7")


def test_rate_limit_waits_for_the_reset(tmp_path: Path) -> None:
    answers = iter(
        [
            httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    slept: list[float] = []
    gh = GitHub(
        cache_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(lambda r: next(answers))),
        sleep=slept.append,
    )
    assert gh.get("/rate") == {"ok": True}
    assert len(slept) >= 1 and gh.requests == 2


def test_get_issue_hides_what_maintainers_did_later(gh: GitHub) -> None:
    issue = Tools(gh).get_issue(REPO, 9)
    assert set(issue) == {"number", "title", "body", "author", "created_at"}
    assert issue["body"].endswith("[truncated]") and len(issue["body"]) < 4100


def test_search_only_sees_earlier_issues_and_never_the_issue_itself(gh: GitHub) -> None:
    tools = Tools(gh)
    with pytest.raises(RuntimeError):
        tools.search_similar_issues(REPO, "crash")
    with triaging(REPO, 9, "2026-02-01T00:00:00Z"):
        found = tools.search_similar_issues(REPO, 'crash "start"')
    assert [x["number"] for x in found] == [7]
    (cached,) = [json.loads(p.read_text()) for p in gh.cache_dir.glob("*.json")]
    assert "created:<2026-02-01T00:00:00Z" in cached["params"]["q"]


def test_duplicate_target_from_githubs_close_as_duplicate_link(tmp_path: Path) -> None:
    from github_triage.select_issues import duplicate_target

    def native(request: httpx.Request) -> httpx.Response:
        request.headers["x-native"] = "1"
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json=[])
        return handler(request)

    gh = GitHub(cache_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(native)))
    assert duplicate_target(gh, REPO, 9) == 7  # no comment: only the GraphQL link has it


def test_selection_keeps_duplicates_only_with_a_target(gh: GitHub) -> None:
    truths, dropped = select(gh, REPO, 10, "2026-01-01", "2026-06-30")
    assert [(t.number, t.duplicate_of) for t in truths] == [(7, None), (9, 7)]
    assert dropped == 0


TRUTH = Truth(REPO, 9, "2026-02-01T00:00:00Z", "t", ["bug", "duplicate"], 7, "duplicate")


@pytest.mark.parametrize(
    ("triage", "ok", "reason"),
    [
        ({"suggested_labels": ["bug"], "duplicate_of": 7}, True, "ok"),
        ({"suggested_labels": ["bug", "nope"], "duplicate_of": 7}, False, "not in repo"),
        ({"suggested_labels": [], "duplicate_of": 7}, False, "no overlap"),
        ({"suggested_labels": ["bug"], "duplicate_of": None}, False, "duplicate_of None"),
        (None, False, "no triage"),
    ],
)
def test_task_check(triage: Any, ok: bool, reason: str) -> None:
    verdict = judge(triage, TRUTH, {"bug", "duplicate", "docs"})
    assert verdict.ok is ok and reason in verdict.reason


def test_issue_reference_from_structured_or_message_input() -> None:
    assert issue_ref({"repo": "a/b", "number": "3"}) == ("a/b", 3)
    message = {
        "messages": [{"type": "human", "content": "Please triage issue #12 in astral-sh/uv."}]
    }
    assert issue_ref(message) == ("astral-sh/uv", 12)
    assert find_triage({"messages": [], "triage": {"suggested_labels": []}}) == {
        "suggested_labels": []
    }


class Scripted(BaseChatModel):
    """Calls the tools a typical model would, in parallel where it can, then answers."""

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "Scripted":
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        return RunnableLambda(
            lambda messages: Triage(
                suggested_labels=["bug"], duplicate_of=7, draft_reply="Thanks, tracked in #7."
            )
        )

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        done = {m.name for m in messages if isinstance(m, ToolMessage)}
        n = len(messages)

        def call(*calls: tuple[str, dict[str, Any]]) -> ChatResult:
            tool_calls = [
                {"name": name, "args": args, "id": f"c{n}-{i}", "type": "tool_call"}
                for i, (name, args) in enumerate(calls)
            ]
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage("", tool_calls=tool_calls))]
            )

        if "get_issue" not in done:
            return call(("get_issue", {"repo": REPO, "number": 9}), ("list_labels", {"repo": REPO}))
        if "search_similar_issues" not in done:
            return call(("search_similar_issues", {"repo": REPO, "query": "crash starting"}))
        if "draft_comment" not in done:
            return call(("draft_comment", {"issue_number": 9, "body": "Thanks, tracked in #7."}))
        return ChatResult(generations=[ChatGeneration(message=AIMessage("Done."))])


def test_the_agent_runs_the_tool_loop_and_returns_a_structured_triage(gh: GitHub) -> None:
    tools = Tools(gh)
    graph = build_agent(Scripted(), tools.langchain_tools())
    with triaging(REPO, 9, "2026-02-01T00:00:00Z"):
        state = graph.invoke({"messages": [first_message(REPO, 9)]})
    assert [name for name, _ in tools.calls] == [
        "get_issue",
        "list_labels",
        "search_similar_issues",
        "draft_comment",
    ]
    assert state["triage"] == {
        "suggested_labels": ["bug"],
        "duplicate_of": 7,
        "draft_reply": "Thanks, tracked in #7.",
    }
    assert judge(state["triage"], TRUTH, {"bug", "duplicate"}).ok


def test_run_check_reads_the_issue_from_the_recorded_input() -> None:
    check = RunCheck({(REPO, 9): TRUTH}, {REPO: {"bug", "duplicate"}})
    recorded = Run(
        run_id="r",
        workflow_id="github_triage",
        started_at="2026-10-13T00:00:00Z",  # type: ignore[arg-type]
        status="success",
        input={"messages": [{"content": f"Please triage issue #9 in {REPO}."}]},
        output={"triage": {"suggested_labels": ["bug"], "duplicate_of": 7, "draft_reply": ""}},
        source="test",
    )
    assert check(recorded, recorded)


def test_budget_ledger_survives_concurrent_writers(tmp_path: Path) -> None:
    from concurrent.futures import ProcessPoolExecutor

    from github_triage.budget import Budget

    path = tmp_path / "spend.json"
    with ProcessPoolExecutor(4) as pool:
        list(pool.map(_add_cents, [path] * 40))
    assert Budget(path, cap=1).spent() == {"p": pytest.approx(0.4)}
    with pytest.raises(Exception, match="spent"):
        Budget(path, cap=0.3).check()


def _add_cents(path: Path) -> None:
    from github_triage.budget import Budget

    Budget(path, cap=1).add("p", 0.01)
