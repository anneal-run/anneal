"""The challenge commands are the v3 entry point."""

import json
from pathlib import Path

from anneal.cli import main


def test_orchestrate_command_writes_the_harness_reading(tmp_path: Path) -> None:
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"candidates": 2, "dollars": 5, "hours": 5}), encoding="utf-8")
    baseline = tmp_path / "baseline.jsonl"
    opt = {
        "split": "opt",
        "case_id": "opt-0001",
        "correct": True,
        "cost_usd": 0.0035,
        "latency_ms": 100,
        "tools": ["get_issue"],
    }
    hold = {**opt, "split": "holdout", "case_id": "hold-0001"}
    rows = []
    for i in range(20):
        rows.append({**opt, "case_id": f"opt-{i:04d}"})
        rows.append({**hold, "case_id": f"hold-{i:04d}"})
    baseline.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    submissions = tmp_path / "submissions"
    submissions.mkdir()

    def cand(arm: str, name: str, cost: float) -> None:
        (submissions / f"{arm}-{name}.json").write_text(
            json.dumps(
                {
                    "id": name,
                    "arm": arm,
                    "kind": "structural",
                    "search_cost_usd": 0,
                    "human_hours": 0.5,
                    "monthly_runs": 10000,
                    "opt": [
                        {
                            "case_id": f"opt-{i:04d}",
                            "correct": True,
                            "cost_usd": cost,
                            "latency_ms": 100,
                            "tools": ["get_issue"],
                        }
                        for i in range(20)
                    ],
                }
            ),
            encoding="utf-8",
        )

    cand("A", "untuned", 0.0035)
    cand("B", "script", 0.0005)
    cand("C", "script", 0.0005)
    holdout = {
        "A/untuned": [
            {
                "case_id": f"hold-{i:04d}",
                "correct": True,
                "cost_usd": 0.0035,
                "latency_ms": 100,
                "tools": ["get_issue"],
            }
            for i in range(20)
        ],
        "B/script": [
            {
                "case_id": f"hold-{i:04d}",
                "correct": True,
                "cost_usd": 0.0005,
                "latency_ms": 100,
                "tools": ["get_issue"],
            }
            for i in range(20)
        ],
        "C/script": [
            {
                "case_id": f"hold-{i:04d}",
                "correct": True,
                "cost_usd": 0.0005,
                "latency_ms": 100,
                "tools": ["get_issue"],
            }
            for i in range(20)
        ],
    }
    (tmp_path / "holdout.json").write_text(json.dumps(holdout), encoding="utf-8")
    out = tmp_path / "report.md"
    code = main(
        [
            "challenge",
            "orchestrate",
            "--budget",
            str(budget),
            "--baseline",
            str(baseline),
            "--submissions",
            str(submissions),
            "--holdout",
            str(tmp_path / "holdout.json"),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "harness_is_the_product" in text
    assert "Worth it: True" in text
