"""Shadow accumulation stops only when the paired difference is clearly outside the margin."""

import json
from pathlib import Path

from anneal.challenge.shadow import evaluate_pairs, load_pairs, margin_points, render_shadow
from anneal.cli import main


def test_a_short_tie_cannot_adjudicate() -> None:
    report = evaluate_pairs([(True, True)] * 5, margin_points=2.0)
    text = render_shadow(report)
    assert report.verdict == "cannot adjudicate"
    assert report.stopped is False
    assert "n reached: 5" in text
    assert "n required:" in text
    assert "margin: 2.0 points" in text


def test_a_clear_gain_stops_before_the_required_n() -> None:
    report = evaluate_pairs([(False, True)] * 8, margin_points=2.0)
    assert report.stopped is True
    assert report.verdict == "outside the margin, better"
    assert report.n_reached == 8
    assert report.n_reached < report.n_required


def test_a_clear_drop_stops_before_the_required_n() -> None:
    report = evaluate_pairs([(True, False)] * 8, margin_points=2.0)
    assert report.verdict == "outside the margin, worse"
    assert report.stopped is True


def test_enough_pairs_inside_the_margin_get_a_verdict() -> None:
    report = evaluate_pairs([(True, True)] * 20, margin_points=50.0)
    assert report.n_reached >= report.n_required
    assert report.verdict == "within the margin"


def test_a_repeated_case_counts_once(tmp_path: Path) -> None:
    path = tmp_path / "pairs.jsonl"
    path.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in (
                {"case_id": "a", "baseline_correct": True, "candidate_correct": False},
                {"case_id": "a", "baseline_correct": True, "candidate_correct": True},
            )
        ),
        encoding="utf-8",
    )
    assert load_pairs(path) == [(True, True)]


def test_margin_is_read_per_workflow(tmp_path: Path) -> None:
    path = tmp_path / "anneal.toml"
    path.write_text("[workflows.demo]\nmargin_points = 4.5\n", encoding="utf-8")
    assert margin_points(path, "demo") == 4.5


def test_shadow_command_prints_n_reached(tmp_path: Path) -> None:
    config = tmp_path / "anneal.toml"
    config.write_text("[workflows.demo]\nmargin_points = 2.0\n", encoding="utf-8")
    pairs = tmp_path / "pairs.jsonl"
    pairs.write_text(
        json.dumps({"case_id": "a", "baseline_correct": True, "candidate_correct": True}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "shadow.md"
    code = main(
        [
            "challenge",
            "shadow",
            "--pairs",
            str(pairs),
            "--config",
            str(config),
            "--workflow",
            "demo",
            "--out",
            str(out),
        ]
    )
    assert code == 2
    assert "n reached: 1" in out.read_text(encoding="utf-8")
    assert "verdict: cannot adjudicate" in out.read_text(encoding="utf-8")
