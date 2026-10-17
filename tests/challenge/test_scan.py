"""The scanner follows the thresholds frozen in report/d/prereg.md."""

import json
import os
import subprocess
from pathlib import Path

from anneal.challenge.scan import scan, write_manifests

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Scan Test",
    "GIT_AUTHOR_EMAIL": "scan@example.com",
    "GIT_COMMITTER_NAME": "Scan Test",
    "GIT_COMMITTER_EMAIL": "scan@example.com",
}


def _commit(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=_ENV)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", message], check=True, env=_ENV)


def _repo(tmp: Path) -> Path:
    subprocess.run(["git", "-C", str(tmp), "init"], check=True, env=_ENV)
    parser = tmp / "pkg" / "parse_dates.py"
    parser.parent.mkdir()
    parser.write_text(
        "import re\n"
        "def parse(text):\n"
        "    re.search(r'a', text)\n"
        "    re.match(r'b', text)\n"
        "    re.findall(r'c', text)\n"
        "    return text\n",
        encoding="utf-8",
    )
    plain = tmp / "pkg" / "add.py"
    plain.write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
    _commit(tmp, "parse the edge case for dates")
    queue = tmp / "pkg" / "route.py"
    queue.write_text(
        "def route(item):\n    # manual review queue\n    return item\n",
        encoding="utf-8",
    )
    _commit(tmp, "add a route")
    return tmp


def test_a_regex_parser_with_a_case_commit_is_one_structured_call(tmp_path: Path) -> None:
    ranked = scan(_repo(tmp_path))
    by_path = {item.path: item for item in ranked}
    parser = by_path["pkg/parse_dates.py"]
    assert parser.candidate_rung == "one structured call"
    assert parser.regex_ops == 3
    assert parser.case_commits == 1
    assert by_path["pkg/add.py"].candidate_rung == "keep deterministic"
    assert by_path["pkg/route.py"].candidate_rung == "keep deterministic"
    assert by_path["pkg/route.py"].manual_queue is None
    assert parser.incidents is None
    assert parser.request_volume is None


def test_a_queue_object_is_not_a_manual_review(tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, env=_ENV)
    path = tmp_path / "pkg" / "jobs.py"
    path.parent.mkdir()
    path.write_text(
        "import queue\ndef consume(jobs: queue.Queue):\n    return jobs.get()\n",
        encoding="utf-8",
    )
    _commit(tmp_path, "consume the queue")
    ranked = scan(tmp_path)
    assert ranked[0].candidate_rung == "keep deterministic"
    assert ranked[0].manual_queue is None


def test_routing_without_a_measured_queue_stays_deterministic(tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, env=_ENV)
    path = tmp_path / "pkg" / "route.py"
    path.parent.mkdir()
    path.write_text(
        "def route(item):\n"
        "    if item.flagged:\n"
        "        return manual_review(item)\n"
        "    return item\n",
        encoding="utf-8",
    )
    _commit(tmp_path, "send flagged items to review")
    ranked = scan(tmp_path)
    assert ranked[0].candidate_rung == "keep deterministic"
    assert ranked[0].manual_queue is None


def test_a_review_branch_with_a_measured_queue_is_a_bounded_workflow(tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, env=_ENV)
    path = tmp_path / "pkg" / "route.py"
    path.parent.mkdir()
    path.write_text(
        "REVIEW_QUEUE_SIZE = 12\n"
        "def route(item):\n"
        "    if item.flagged:\n"
        "        return manual_review(item)\n"
        "    return item\n",
        encoding="utf-8",
    )
    _commit(tmp_path, "cap the review queue")
    ranked = scan(tmp_path)
    assert ranked[0].candidate_rung == "bounded workflow"
    assert ranked[0].manual_queue == 12


def test_a_string_compare_is_scored(tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, env=_ENV)
    path = tmp_path / "pkg" / "choose.py"
    path.parent.mkdir()
    path.write_text(
        "def choose(kind):\n    if kind == 'a' or kind != 'b':\n        return kind\n",
        encoding="utf-8",
    )
    _commit(tmp_path, "choose a kind")
    ranked = scan(tmp_path)
    assert ranked[0].string_switches == 2
    assert ranked[0].candidate_rung == "keep deterministic"


def test_each_candidate_gets_a_harness_manifest_without_the_holdout(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    out = tmp_path / "out"
    write_manifests(repo, scan(repo), out)
    manifest = json.loads((out / "pkg__parse_dates" / "manifest.json").read_text())
    assert manifest["workflow_files"] == ["pkg/parse_dates.py"]
    assert "holdout_run_ids" not in manifest
    evidence = json.loads((out / "pkg__parse_dates" / "evidence.json").read_text())
    assert evidence["candidate_rung"] == "one structured call"
