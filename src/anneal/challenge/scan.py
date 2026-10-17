"""Walk a repository for non-AI code that is losing to messy input.

The thresholds are the ones in report/d/prereg.md. This module does not choose them.
"""

import ast
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from anneal.challenge.models import HarnessManifest

_CASE = re.compile(r"case|edge|special|workaround|fallback|parse", re.IGNORECASE)
_REGEX_OP = re.compile(r"\bre\.(?:compile|match|search|sub|findall)\b")
_REVIEW = ("manual", "review", "queue", "human")
_SKIP_DIRS = {"test", "tests", "vendor", "vendored", "third_party", "generated", "build", "dist"}
_AGENT = ("langgraph", "langchain", "autogen")


@dataclass(frozen=True)
class ScanCandidate:
    """One file, its evidence, and the rung the frozen rule assigns."""

    path: str
    score: int
    churn: int
    case_commits: int
    regex_ops: int
    string_switches: int
    review_words: int
    template_conditionals: int
    incidents: None
    request_volume: None
    manual_queue: int | None
    ladder: str
    reason: str


def scan(repo: Path) -> list[ScanCandidate]:
    """Score every Python file under `repo`. Highest score first."""
    root = repo.resolve()
    history = _history(root)
    found: list[ScanCandidate] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if _skipped(relative):
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if not source.strip():
            continue
        churn, case_commits = history.get(relative, (0, 0))
        regex_ops = len(_REGEX_OP.findall(source))
        switches = _string_switches(source)
        lowered = source.lower()
        review_words = sum(lowered.count(word) for word in _REVIEW)
        template = _template_conditional(source)
        queue = lowered.count("queue")
        score = churn + case_commits + regex_ops + switches + review_words + template
        ladder, reason = _ladder(
            relative,
            source,
            case_commits=case_commits,
            regex_ops=regex_ops,
            churn=churn,
            switches=switches,
            review_words=review_words,
            template=template,
        )
        found.append(
            ScanCandidate(
                path=relative,
                score=score,
                churn=churn,
                case_commits=case_commits,
                regex_ops=regex_ops,
                string_switches=switches,
                review_words=review_words,
                template_conditionals=template,
                incidents=None,
                request_volume=None,
                manual_queue=queue or None,
                ladder=ladder,
                reason=reason,
            )
        )
    return sorted(found, key=lambda item: (-item.score, item.path))


def write_manifests(repo: Path, candidates: list[ScanCandidate], directory: Path) -> None:
    """One harness manifest per candidate. Holdout ids are not in the file."""
    workflow_id = repo.resolve().name
    directory.mkdir(parents=True, exist_ok=True)
    for candidate in candidates:
        folder = directory / _slug(candidate.path)
        folder.mkdir(parents=True, exist_ok=True)
        manifest = HarnessManifest(
            workflow_id=workflow_id,
            optimization_run_ids=[],
            holdout_run_ids=[],
            tools=[],
            workflow_files=[candidate.path],
            entrypoint=None,
            mocked_tools=[],
        )
        (folder / "manifest.json").write_text(
            json.dumps(manifest.proposer_payload(), indent=2) + "\n", encoding="utf-8"
        )
        evidence = {
            "path": candidate.path,
            "score": candidate.score,
            "churn": candidate.churn,
            "case_commits": candidate.case_commits,
            "regex_ops": candidate.regex_ops,
            "string_switches": candidate.string_switches,
            "review_words": candidate.review_words,
            "template_conditionals": candidate.template_conditionals,
            "incidents": candidate.incidents,
            "request_volume": candidate.request_volume,
            "manual_queue": candidate.manual_queue,
            "ladder": candidate.ladder,
            "reason": candidate.reason,
        }
        (folder / "evidence.json").write_text(
            json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
        )


def _history(repo: Path) -> dict[str, tuple[int, int]]:
    completed = subprocess.run(
        ["git", "-C", str(repo), "log", "-n", "200", "--name-only", "--pretty=format:%x1e%s"],
        check=True,
        capture_output=True,
        text=True,
    )
    counts: dict[str, tuple[int, int]] = {}
    for block in completed.stdout.split("\x1e"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        subject, *files = lines
        case = 1 if _CASE.search(subject) else 0
        for name in files:
            churn, cases = counts.get(name, (0, 0))
            counts[name] = (churn + 1, cases + case)
    return counts


def _skipped(relative: str) -> bool:
    parts = relative.split("/")
    if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in parts[:-1]):
        return True
    name = parts[-1]
    return name.startswith("test_") or name.endswith("_test.py")


def _string_switches(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            count += _string_compares(node.test)
        elif isinstance(node, ast.match_case):
            count += _literal_patterns(node.pattern)
    return count


def _string_compares(node: ast.AST) -> int:
    if isinstance(node, ast.BoolOp):
        return sum(_string_compares(value) for value in node.values)
    if not isinstance(node, ast.Compare):
        return 0
    parts = [node.left, *node.comparators]
    count = 0
    for op, left, right in zip(node.ops, parts, parts[1:], strict=False):
        if isinstance(op, (ast.Eq, ast.NotEq)) and (_is_str(left) or _is_str(right)):
            count += 1
    return count


def _literal_patterns(pattern: ast.pattern) -> int:
    if isinstance(pattern, ast.MatchOr):
        return sum(_literal_patterns(item) for item in pattern.patterns)
    if isinstance(pattern, ast.MatchValue) and _is_str(pattern.value):
        return 1
    return 0


def _is_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _template_conditional(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    formatted = False
    ifs = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            formatted = True
        elif isinstance(node, ast.If):
            ifs += 1
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
        ):
            formatted = True
    return 1 if formatted and ifs >= 5 else 0


def _ladder(
    relative: str,
    source: str,
    *,
    case_commits: int,
    regex_ops: int,
    churn: int,
    switches: int,
    review_words: int,
    template: int,
) -> tuple[str, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = None
    if tree is not None and _imports_agent(tree):
        return "agent", "agent: the file imports an agent framework"
    lowered = source.lower()
    if any(word in lowered for word in _REVIEW) and "queue" in lowered:
        return "bounded workflow", "bounded workflow: manual review and a queue"
    if regex_ops >= 3 and _CASE_PATH(relative) and case_commits >= 1:
        return "one structured call", "one structured call: a regex parser with a case commit"
    signals = {
        "churn": churn,
        "regex operations": regex_ops,
        "string switches": switches,
        "manual-review words": review_words,
        "template conditionals": template,
    }
    name, value = max(signals.items(), key=lambda item: (item[1], item[0]))
    if value == 0:
        return "keep deterministic", "keep deterministic: no messy-input signal"
    return "keep deterministic", f"keep deterministic: {name} ({value}) stayed under the line"


def _CASE_PATH(relative: str) -> bool:
    lowered = relative.lower()
    return "parse" in lowered or "extract" in lowered


def _imports_agent(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names = [node.module.split(".")[0]]
        else:
            continue
        if any(name in _AGENT for name in names):
            return True
    return False


def _slug(relative: str) -> str:
    return relative.replace("/", "__").removesuffix(".py")
