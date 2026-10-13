"""Pick the issues to triage and record what maintainers actually did with them.

Issues are closed issues (not pull requests) opened inside a fixed window, so most
of them had time to be triaged and closed. For each one the ground truth is:
- `labels`: the labels on the issue now, i.e. the ones maintainers applied;
- `duplicate_of`: the issue it was closed as a duplicate of, from the closing
  reason or a `duplicate` label plus a "Duplicate of #N" comment. A duplicate
  closure without a findable target is dropped, since it cannot be judged.
"""

import re
from dataclasses import asdict, dataclass
from typing import Any

from github_triage.github import GitHub


@dataclass(frozen=True)
class Truth:
    repo: str
    number: int
    created_at: str
    title: str
    labels: list[str]
    duplicate_of: int | None
    state_reason: str | None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _is_duplicate(item: dict[str, Any]) -> bool:
    labels = {label["name"].lower() for label in item.get("labels", [])}
    return item.get("state_reason") == "duplicate" or any("duplicate" in x for x in labels)


def duplicate_target(gh: GitHub, repo: str, number: int) -> int | None:
    pattern = re.compile(
        rf"duplicate of\s+(?:https://github\.com/{re.escape(repo)}/issues/|#)(\d+)", re.I
    )
    for comment in gh.get(f"/repos/{repo}/issues/{number}/comments", per_page=100):
        if m := pattern.search(comment.get("body") or ""):
            target = int(m.group(1))
            return target if target != number else None
    return None


def select(gh: GitHub, repo: str, n: int, since: str, until: str) -> tuple[list[Truth], int]:
    """The `n` latest closed, labelled issues opened in [since, until], oldest first,
    and how many duplicate closures were dropped for having no findable target."""
    picked: list[Truth] = []
    dropped = 0
    for page in range(1, 11):
        found = gh.get(
            "/search/issues",
            q=f"repo:{repo} is:issue is:closed created:{since}..{until}",
            sort="created",
            order="desc",
            per_page=100,
            page=page,
        )
        for item in found.get("items", []):
            if not item.get("labels") and not _is_duplicate(item):
                continue
            target = None
            if _is_duplicate(item):
                target = duplicate_target(gh, repo, item["number"])
                if target is None:
                    dropped += 1
                    continue
            picked.append(
                Truth(
                    repo=repo,
                    number=item["number"],
                    created_at=item["created_at"],
                    title=item["title"],
                    labels=sorted(label["name"] for label in item.get("labels", [])),
                    duplicate_of=target,
                    state_reason=item.get("state_reason"),
                )
            )
            if len(picked) == n:
                return sorted(picked, key=lambda t: t.created_at), dropped
        if len(found.get("items", [])) < 100:
            break
    return sorted(picked, key=lambda t: t.created_at), dropped
