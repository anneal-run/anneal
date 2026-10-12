import json
from pathlib import Path

import pytest
from synth.generator import COST, WORKFLOW, generate

from anneal.cli import main
from anneal.report.analyze import Delta, analyze, render_markdown
from anneal.schema.store import Store

FIXTURE = Path(__file__).parents[1] / "fixtures" / "traces" / "langsmith" / "support_triage.jsonl"


def expected_spend() -> dict[str, float]:
    runs, truth = generate(seed=0)
    spend = dict.fromkeys(["removable", "constrained", "judgment", "terminal"], 0.0)
    costs = {e.event_id: e.cost_usd for r in runs for e in r.events if e.kind == "model_call"}
    for event_id, cls in truth.items():
        spend[cls] += costs[event_id] or 0.0
    return spend


def test_spend_by_class_matches_planted_truth() -> None:
    runs, _ = generate(seed=0)
    report = analyze(runs)
    spend = expected_spend()
    total = sum(spend.values())
    assert report.spend_usd == pytest.approx(total)
    for row in report.by_class:
        assert row.spend_usd == pytest.approx(spend[row.call_class]), row.call_class
        assert row.share == pytest.approx(spend[row.call_class] / total)


def test_tier1_estimate_counts_removable_and_no_unmeasured_constrained() -> None:
    runs, _ = generate(seed=0)
    report = analyze(runs)
    spend = expected_spend()
    assert report.tier1_saving_usd == pytest.approx(spend["removable"])
    assert report.tier1_share == pytest.approx(spend["removable"] / sum(spend.values()))
    assert report.constrained_unmeasured_usd == pytest.approx(spend["constrained"])


def test_measured_delta_adds_constrained_saving() -> None:
    runs, _ = generate(seed=0)
    base = analyze(runs)
    ticket = next(p for p in base.positions if p.dominant == "calls:create_ticket")
    measured = analyze(
        runs, deltas={ticket.position_id: Delta(original_usd=0.02, constrained_usd=0.005)}
    )
    assert measured.tier1_saving_usd == pytest.approx(
        base.tier1_saving_usd + ticket.spend_usd * 0.75
    )
    assert measured.constrained_unmeasured_usd == pytest.approx(
        base.constrained_unmeasured_usd - ticket.spend_usd
    )


def test_run_coverage_by_skeleton() -> None:
    runs, _ = generate(seed=0)
    report = analyze(runs)
    assert sum(c.runs for c in report.clusters) == len(runs)
    assert report.clusters[0].run_share >= report.clusters[-1].run_share
    assert sum(c.spend_share for c in report.clusters) == pytest.approx(1.0)


def test_markdown_has_the_sections_and_numbers() -> None:
    runs, _ = generate(seed=0)
    text = render_markdown(analyze(runs))
    for heading in [
        "# anneal analyze",
        "## Run coverage by skeleton",
        "## Spend by class",
        "## Tier 1 estimate",
        "## Positions",
    ]:
        assert heading in text
    assert "removable" in text and "calls:create_ticket" in text


def test_cli_import_then_analyze(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = tmp_path / "store"
    assert main(["import", "langsmith", str(FIXTURE), "--store", str(store)]) == 0
    assert "imported 3 runs" in capsys.readouterr().out
    assert main(["analyze", str(store)]) == 0
    out = capsys.readouterr().out
    assert "# anneal analyze: support_triage" in out
    assert "jane@acme.com" not in out


def test_cli_analyze_json_with_deltas(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs, _ = generate(seed=0)
    Store(tmp_path).write(runs)
    assert main(["analyze", str(tmp_path), "--workflow", WORKFLOW, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    ticket = next(p for p in report["positions"] if p["dominant"] == "calls:create_ticket")
    deltas = tmp_path / "deltas.json"
    deltas.write_text(
        json.dumps({ticket["position_id"]: {"original_usd": 1.0, "constrained_usd": 0.5}})
    )
    assert (
        main(["analyze", str(tmp_path), "--workflow", WORKFLOW, "--json", "--deltas", str(deltas)])
        == 0
    )
    measured = json.loads(capsys.readouterr().out)
    assert measured["tier1_saving_usd"] > report["tier1_saving_usd"]
    assert COST["ticket"] > 0


def test_cli_analyze_needs_a_workflow_when_store_has_several(tmp_path: Path) -> None:
    runs, _ = generate(seed=0, n_runs=5, n_faq=0)
    Store(tmp_path).write(runs)
    Store(tmp_path).write([r.model_copy(update={"workflow_id": "other"}) for r in runs])
    with pytest.raises(SystemExit):
        main(["analyze", str(tmp_path)])
