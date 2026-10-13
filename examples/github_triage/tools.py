"""The agent's four tools. All are read-only (severity S0); `draft_comment` never posts.

The issue being triaged was opened in the past and has since been labelled and
closed. To keep the agent from seeing the answer:
- `get_issue` returns only what was there when the issue was opened (no labels,
  state, comments or closing reason);
- `search_similar_issues` only finds issues created before it.

The current issue is set per run with `triaging(...)`, the same way in every arm.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool

from github_triage.github import GitHub

BODY_CHARS = 4000
SEARCH_LIMIT = 5


@dataclass(frozen=True)
class Current:
    repo: str
    number: int
    created_at: str


_CURRENT: ContextVar[Current | None] = ContextVar("github_triage_current", default=None)


@contextmanager
def triaging(repo: str, number: int, created_at: str) -> Iterator[None]:
    token = _CURRENT.set(Current(repo, number, created_at))
    try:
        yield
    finally:
        _CURRENT.reset(token)


def _current() -> Current:
    current = _CURRENT.get()
    if current is None:
        raise RuntimeError("tools called outside triaging(...)")
    return current


class ToolError(Exception):
    pass


@dataclass
class Tools:
    gh: GitHub
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def call(self, name: str, args: dict[str, Any]) -> Any:
        self.calls.append((name, dict(args)))
        match name:
            case "get_issue":
                return self.get_issue(**args)
            case "list_labels":
                return self.list_labels(**args)
            case "search_similar_issues":
                return self.search_similar_issues(**args)
            case "draft_comment":
                return self.draft_comment(**args)
        raise ToolError(f"unknown tool {name}")

    def get_issue(self, repo: str, number: int) -> dict[str, Any]:
        """Fetch a GitHub issue as it was opened: title, body, author and creation time."""
        try:
            issue = self.gh.get(f"/repos/{repo}/issues/{int(number)}")
        except Exception as e:
            raise ToolError(f"issue {repo}#{number} not found: {e}") from None
        body = issue.get("body") or ""
        return {
            "number": issue["number"],
            "title": issue["title"],
            "body": body[:BODY_CHARS] + ("\n[truncated]" if len(body) > BODY_CHARS else ""),
            "author": (issue.get("user") or {}).get("login"),
            "created_at": issue["created_at"],
        }

    def list_labels(self, repo: str) -> list[dict[str, str]]:
        """List every label defined in the repository, with its description."""
        labels: list[dict[str, str]] = []
        for page in range(1, 11):
            batch = self.gh.get(f"/repos/{repo}/labels", per_page=100, page=page)
            labels += [
                {"name": x["name"], "description": x.get("description") or ""} for x in batch
            ]
            if len(batch) < 100:
                break
        return labels

    def search_similar_issues(self, repo: str, query: str) -> list[dict[str, Any]]:
        """Search the repository's earlier issues for ones similar to the query."""
        current = _current()
        words = " ".join(query.replace('"', " ").split())[:200]
        q = f"repo:{repo} is:issue created:<{current.created_at[:19]}Z {words}"
        found = self.gh.get("/search/issues", q=q, per_page=SEARCH_LIMIT + 1)
        out = []
        for item in found.get("items", []):
            if item["number"] == current.number and repo == current.repo:
                continue
            out.append(
                {
                    "number": item["number"],
                    "title": item["title"],
                    "state": item["state"],
                    "created_at": item["created_at"],
                }
            )
        return out[:SEARCH_LIMIT]

    @staticmethod
    def draft_comment(issue_number: int, body: str) -> dict[str, Any]:
        """Draft a reply comment for the issue. Returns the draft; nothing is posted."""
        return {"issue_number": int(issue_number), "draft": body}

    def langchain_tools(self) -> list[StructuredTool]:
        def wrap(name: str, fn: Any) -> StructuredTool:
            def run(**kwargs: Any) -> str:
                try:
                    return json.dumps(self.call(name, kwargs))
                except ToolError as e:
                    return json.dumps({"error": str(e)})

            return StructuredTool.from_function(
                func=run, name=name, description=fn.__doc__, args_schema=_schema(name)
            )

        return [
            wrap("get_issue", self.get_issue),
            wrap("list_labels", self.list_labels),
            wrap("search_similar_issues", self.search_similar_issues),
            wrap("draft_comment", self.draft_comment),
        ]


def _schema(name: str) -> dict[str, Any]:
    props: dict[str, dict[str, Any]] = {
        "get_issue": {
            "repo": {"type": "string", "description": "owner/name"},
            "number": {"type": "integer"},
        },
        "list_labels": {"repo": {"type": "string", "description": "owner/name"}},
        "search_similar_issues": {
            "repo": {"type": "string", "description": "owner/name"},
            "query": {"type": "string", "description": "keywords"},
        },
        "draft_comment": {"issue_number": {"type": "integer"}, "body": {"type": "string"}},
    }[name]
    return {"type": "object", "properties": props, "required": list(props)}
