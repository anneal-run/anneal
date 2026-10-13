"""Handwritten baseline for `github_triage`.

Pipeline (deterministic except where marked MODEL):

1. get_issue + list_labels.
2. Candidate search: build short keyword queries from the title (and an error line in
   the body, if any) and run them with search_similar_issues. GitHub search ANDs terms,
   so long queries return nothing; we use a few short ones and stop once we have enough.
3. MODEL (always, 1 call): pick labels, pick at most one duplicate from the candidates,
   write the reply.
4. MODEL (only when step 3 proposes a duplicate, 1 call): fetch the candidate's body and
   confirm it is the same problem. If it is not, the duplicate is dropped and the reply
   rewritten in the same call.
5. Validation: labels are mapped onto the repository's label set (case-insensitively);
   unknown labels are dropped; a duplicate must be one of the searched candidates. If no
   valid label survives after one retry, raise rather than return an empty triage.

So: 1 model call per issue, 2 when a duplicate is proposed.
"""

from __future__ import annotations

import re
from typing import Any

try:  # the harness may load this file by path, without its directory on sys.path
    from interface import Model, Tools
except ImportError:  # pragma: no cover
    from typing import Any as Model, Any as Tools  # type: ignore[assignment]

MAX_BODY_CHARS = 4000
MAX_CANDIDATES = 10
MAX_QUERIES = 3
ENOUGH_CANDIDATES = 6

# --------------------------------------------------------------------------------------
# Issue text and search queries (deterministic)
# --------------------------------------------------------------------------------------

STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are aren as at be because been
    before being below between both but by can cannot could did didn do does doesn doing don
    down during each even ever every few for from further get gets getting got had has have
    having he her here hers how i if in into is isn it its itself just like make makes may me
    might more most much must my no nor not now of off on once only or other our out over own
    same should so some such than that the their them then there these they this those
    through to too under until up use used uses using very via want wants was way we were what
    when where which while who why will with won would you your yours yet able new still
    issue issues bug bugs feature request support supports supported error errors problem
    problems please help question work works working broken fail fails failed failing wrong
    instead without unable trying try tried allow allows add adds added option options
    """.split()
)

_TEMPLATE_PREFIX = re.compile(
    r"^\s*(?:\[[^\]]{1,40}\]\s*|(?:bug|bug report|feature|feature request|enhancement|question|"
    r"docs?|documentation|proposal|rfc|regression|fix|feat|chore)\s*(?:\([^)]*\))?\s*[:\-]\s*)+",
    re.IGNORECASE,
)
_VERSION = re.compile(r"^(?:v?\d+(?:[.\-_]\d+)+[a-z]*\d*|\d{1,2})$", re.IGNORECASE)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-/]*[A-Za-z0-9]|[A-Za-z0-9]")
_ERROR_LINE = re.compile(
    r"^.*\b(?:error|panic|panicked|exception|traceback|failed|fatal)\b.*$", re.IGNORECASE | re.M
)


def clean_body(body: str | None) -> str:
    """Drop template comments, images and excess whitespace; cap the length."""
    text = body or ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<img[^>]*>", "[image]", text, flags=re.I)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[image]", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS] + "\n[... truncated]"
    return text


def strip_template_prefix(title: str) -> str:
    return _TEMPLATE_PREFIX.sub("", title).strip() or title.strip()


def _keywords(text: str, noise: set[str]) -> list[tuple[str, float, int]]:
    """Return (token, score, position) for distinctive tokens, first occurrence only."""
    text = re.sub(r"<[A-Z][A-Z0-9_]*>", " ", text)  # redaction placeholders such as <EMAIL_1>
    code_spans = {m.lower() for m in re.findall(r"`([^`]+)`", text)}
    seen: set[str] = set()
    stems: set[str] = set()
    out: list[tuple[str, float, int]] = []
    for pos, m in enumerate(_TOKEN.finditer(text)):
        raw = m.group(0).strip(".-/")
        tok = raw.lower()
        if not tok or tok in seen or tok in STOPWORDS or tok in noise:
            continue
        if _VERSION.match(tok) or (len(tok) < 3 and not re.search(r"[_.\-]", tok)):
            continue
        seen.add(tok)
        stem = tok[:5] if tok.isalpha() and len(tok) >= 5 else tok
        if stem in stems:
            continue  # "install" after "installed": same word for search purposes
        stems.add(stem)
        score = min(len(tok), 12) / 3.0
        if re.search(r"[_.\-/]", tok):
            score += 2.0  # identifiers, flags, file names
        if any(tok in span for span in code_spans):
            score += 1.5
        if raw.isupper() and len(raw) > 2:
            score += 1.5  # ERROR_CODES, acronyms
        out.append((tok, score, pos))
    return out


def _top_terms(cands: list[tuple[str, float, int]], k: int) -> list[str]:
    best = sorted(cands, key=lambda c: -c[1])[:k]
    return [t for t, _, _ in sorted(best, key=lambda c: c[2])]


def build_queries(repo: str, title: str, body: str | None) -> list[str]:
    """Short keyword queries, most specific first. Never empty for a non-empty title."""
    owner, name = repo.split("/", 1)
    noise = {owner.lower(), name.lower()}
    t_terms = _keywords(strip_template_prefix(title), noise)
    queries: list[str] = []
    for k in (4, 2):
        terms = _top_terms(t_terms, k)
        if terms:
            queries.append(" ".join(terms))
    m = _ERROR_LINE.search(clean_body(body))
    if m:
        terms = _top_terms(_keywords(m.group(0), noise), 3)
        if len(terms) >= 2:
            queries.append(" ".join(terms))
    if not queries:
        # Title made only of stopwords: fall back to its raw words.
        words = re.findall(r"[A-Za-z0-9]{3,}", title)[:4]
        if words:
            queries.append(" ".join(words))
    # Dedupe while keeping order.
    return list(dict.fromkeys(q for q in queries if q))


def find_candidates(repo: str, issue: dict[str, Any], tools: Tools) -> list[dict[str, Any]]:
    found: dict[int, dict[str, Any]] = {}
    for query in build_queries(repo, issue["title"], issue.get("body"))[:MAX_QUERIES]:
        results = tools.call("search_similar_issues", {"repo": repo, "query": query}) or []
        for r in results:
            num = r.get("number")
            if isinstance(num, int) and num != issue["number"] and num not in found:
                found[num] = r
        if len(found) >= ENOUGH_CANDIDATES:
            break
    return list(found.values())[:MAX_CANDIDATES]


# --------------------------------------------------------------------------------------
# Labels (deterministic)
# --------------------------------------------------------------------------------------


def usable_labels(labels: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Labels that can apply to an issue: drops ones documented as pull-request-only."""
    out = []
    for lab in labels:
        name = (lab.get("name") or "").strip()
        desc = (lab.get("description") or "").strip()
        if not name:
            continue
        if re.search(r"\bpull requests?\b|\bPRs?\b", desc) and "issue" not in desc.lower():
            continue
        out.append({"name": name, "description": desc})
    return out


def validate_labels(suggested: list[Any], repo_labels: list[dict[str, str]]) -> list[str]:
    by_lower = {lab["name"].lower(): lab["name"] for lab in repo_labels}
    out: list[str] = []
    for s in suggested:
        if not isinstance(s, str):
            continue
        canon = by_lower.get(s.strip().lower())
        if canon and canon not in out:
            out.append(canon)
    return out


def _duplicate_label(repo_labels: list[dict[str, str]]) -> str | None:
    for lab in repo_labels:
        if lab["name"].lower() in ("duplicate", "type: duplicate", "status: duplicate"):
            return lab["name"]
    return None


# --------------------------------------------------------------------------------------
# Model calls
# --------------------------------------------------------------------------------------

TRIAGE_SYSTEM = """You triage newly opened GitHub issues for open source maintainers.
Return JSON only, matching the schema.

labels: the labels from the repository's list that the maintainers would apply. Copy names
exactly. Usually 1-4 labels: the kind (bug / enhancement / question / documentation or the
repo's equivalent) plus the most specific area or platform labels that clearly fit. Do not
use labels meant for pull requests, CI, releases, bots or maintainers' internal process.
Always give at least one label.

duplicate_of: the number of ONE candidate issue that reports the same problem or asks for
the same thing (same root behaviour, not merely the same topic or area). 0 if none, or if
you are not sure. Most new issues are not duplicates.
duplicate_confidence: high only if the candidate title clearly describes the same problem.

draft_reply: a short, friendly reply to the reporter (2-6 sentences, Markdown). Thank them.
If information needed to reproduce is missing, ask for it specifically. If it is a
duplicate with high confidence, point to the earlier issue; otherwise do not mention
candidates. Never promise a fix, a release or a timeline, and do
not claim anything was closed or labelled."""

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "labels": {"type": "array", "items": {"type": "string"}},
        "duplicate_of": {"type": "integer"},
        "duplicate_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "duplicate_reason": {"type": "string"},
        "draft_reply": {"type": "string"},
    },
    "required": ["labels", "duplicate_of", "duplicate_confidence", "draft_reply"],
}

CONFIRM_SYSTEM = """You check whether a newly opened GitHub issue duplicates an earlier one.
Return JSON only, matching the schema.

same_problem: true only if both issues report the same problem or request the same change,
such that maintainers would close the new one as a duplicate of the earlier one. Sharing a
topic, component or error category is not enough.
If same_problem is false, write reply_if_not_duplicate: a short, friendly reply to the
reporter (2-6 sentences) that does not mention the earlier issue, asks for any missing
reproduction details, and promises no fix or timeline. Otherwise leave it empty."""

CONFIRM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "same_problem": {"type": "boolean"},
        "reply_if_not_duplicate": {"type": "string"},
    },
    "required": ["same_problem", "reply_if_not_duplicate"],
}


def _complete(model: Model, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    """One structured call, retried once if the answer does not parse."""
    try:
        out = model.complete(system, user, schema)
    except ValueError:
        out = model.complete(system, user + "\n\nReturn only a JSON object matching the schema.", schema)
    if not isinstance(out, dict):
        raise ValueError(f"model returned {type(out).__name__}, expected an object")
    return out


def _format_issue(issue: dict[str, Any]) -> str:
    return (
        f"#{issue['number']}: {issue['title']}\n"
        f"opened {issue.get('created_at', '?')}\n\n{clean_body(issue.get('body')) or '(no body)'}"
    )


def _triage_prompt(repo: str, issue: dict[str, Any], labels: list[dict[str, str]],
                   candidates: list[dict[str, Any]], note: str = "") -> str:
    label_lines = "\n".join(
        f"- {lab['name']}" + (f": {lab['description']}" if lab["description"] else "") for lab in labels
    )
    if candidates:
        cand_lines = "\n".join(
            f"- #{c['number']} [{c.get('state', '?')}, {str(c.get('created_at', ''))[:10]}] {c.get('title', '')}"
            for c in candidates
        )
    else:
        cand_lines = "(search found no earlier issues)"
    return (
        f"Repository: {repo}\n\n## Repository labels\n{label_lines}\n\n"
        f"## Earlier issues found by search (duplicate candidates)\n{cand_lines}\n\n"
        f"## New issue\n{_format_issue(issue)}\n{note}"
    )


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def run(repo: str, number: int, tools: Tools, model: Model) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+", repo or ""):
        raise ValueError(f"repo must be 'owner/name', got {repo!r}")

    issue = tools.call("get_issue", {"repo": repo, "number": number})
    if not isinstance(issue, dict) or not issue.get("title"):
        raise RuntimeError(f"get_issue returned no usable issue for {repo}#{number}")
    issue.setdefault("number", number)

    repo_labels = usable_labels(tools.call("list_labels", {"repo": repo}) or [])
    if not repo_labels:
        raise RuntimeError(f"{repo} has no labels; cannot suggest any")

    candidates = find_candidates(repo, issue, tools)
    cand_numbers = {c["number"] for c in candidates}

    prompt = _triage_prompt(repo, issue, repo_labels, candidates)
    answer = _complete(model, TRIAGE_SYSTEM, prompt, TRIAGE_SCHEMA)
    labels = validate_labels(answer.get("labels") or [], repo_labels)
    if not labels:
        names = ", ".join(lab["name"] for lab in repo_labels)
        answer = _complete(
            model, TRIAGE_SYSTEM,
            prompt + f"\nYour previous labels were not in the repository. Choose from exactly: {names}",
            TRIAGE_SCHEMA,
        )
        labels = validate_labels(answer.get("labels") or [], repo_labels)
        if not labels:
            raise RuntimeError(f"model suggested no valid label for {repo}#{number}")

    reply = str(answer.get("draft_reply") or "").strip()
    dup = answer.get("duplicate_of")
    duplicate_of: int | None = None
    if (
        isinstance(dup, int) and not isinstance(dup, bool) and dup in cand_numbers
        and answer.get("duplicate_confidence") == "high"
    ):
        duplicate_of = dup
        try:
            earlier = tools.call("get_issue", {"repo": repo, "number": dup})
        except Exception:  # noqa: BLE001  ToolError, or the harness's own class of it
            earlier = None  # cannot confirm; keep the high-confidence title match
        if isinstance(earlier, dict) and earlier.get("title"):
            check = _complete(
                model, CONFIRM_SYSTEM,
                f"Repository: {repo}\n\n## Earlier issue\n{_format_issue(earlier)}\n\n"
                f"## New issue\n{_format_issue(issue)}",
                CONFIRM_SCHEMA,
            )
            if check.get("same_problem") is not True:
                duplicate_of = None
                reply = str(check.get("reply_if_not_duplicate") or "").strip() or reply

    dup_label = _duplicate_label(repo_labels)
    if dup_label:
        if duplicate_of is not None and dup_label not in labels:
            labels.append(dup_label)
        elif duplicate_of is None and dup_label in labels:
            labels.remove(dup_label)
    if not labels:
        raise RuntimeError(f"no label left for {repo}#{number} after duplicate check")

    if not reply:
        raise RuntimeError(f"model returned an empty reply for {repo}#{number}")

    return {"suggested_labels": labels, "duplicate_of": duplicate_of, "draft_reply": reply}
