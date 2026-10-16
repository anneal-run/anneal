"""The pull request description wires the original implementation back in and links the verdict."""

from pathlib import Path

import pytest

from anneal.challenge.pr import write_pull_request


def test_pr_keeps_the_original_behind_a_flag(tmp_path: Path) -> None:
    verdict = tmp_path / "verdict.md"
    verdict.write_text("Reading: stop_no_win.\n", encoding="utf-8")
    fixtures = tmp_path / "fixtures.jsonl"
    fixtures.write_text('{"run_id": "opt-1"}\n', encoding="utf-8")
    dest = tmp_path / "pr"
    write_pull_request(
        dest,
        workflow="github_triage",
        winner="collapsed",
        verdict=verdict,
        fixtures=fixtures,
    )
    body = (dest / "PR.md").read_text(encoding="utf-8")
    assert "ANNEAL_GITHUB_TRIAGE" in body
    assert "original implementation" in body
    assert "nothing in this change deploys" in body
    assert str(verdict) in body
    assert "Nothing was deployed" in (dest / "rollback.md").read_text(encoding="utf-8")
    assert "FIXTURES" in (dest / "test_fixtures.py").read_text(encoding="utf-8")


def test_pr_refuses_to_overwrite(tmp_path: Path) -> None:
    verdict = tmp_path / "verdict.md"
    verdict.write_text("ok\n", encoding="utf-8")
    fixtures = tmp_path / "fixtures.jsonl"
    fixtures.write_text("{}\n", encoding="utf-8")
    dest = tmp_path / "pr"
    write_pull_request(
        dest, workflow="github_triage", winner="collapsed", verdict=verdict, fixtures=fixtures
    )
    with pytest.raises(ValueError, match="already exists"):
        write_pull_request(
            dest, workflow="github_triage", winner="collapsed", verdict=verdict, fixtures=fixtures
        )
