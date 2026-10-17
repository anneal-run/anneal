"""P0 packs omit the answer key. Holdout ids in a copied file are a leak."""

from pathlib import Path

import pytest

from anneal.challenge.budget import SearchBudget
from anneal.challenge.models import HarnessManifest, ToolBinding
from anneal.challenge.pack import write_pack


def manifest() -> HarnessManifest:
    return HarnessManifest(
        workflow_id="github_triage",
        optimization_run_ids=["run-opt-0001"],
        holdout_run_ids=["run-hold-0009"],
        tools=[ToolBinding(name="get_issue", mode="live", side_effect=False, severity="S0")],
        workflow_files=["examples/github_triage/agent.py"],
        entrypoint=None,
        mocked_tools=[],
    )


def repo(root: Path) -> None:
    agent = root / "examples" / "github_triage"
    agent.mkdir(parents=True)
    (agent / "agent.py").write_text("def run():\n    return 'agent'\n", encoding="utf-8")
    (root / "baseline" / "github_triage").mkdir(parents=True)
    (root / "baseline" / "github_triage" / "workflow.py").write_text(
        "prefetch plus one call\n", encoding="utf-8"
    )
    (root / "report").mkdir()
    (root / "report" / "github_triage-dogfood.md").write_text(
        "a seventh of the cost\n", encoding="utf-8"
    )
    (root / "ANNEAL-V3-PLAYBOOK.md").write_text("prefetch-plus-one-call\n", encoding="utf-8")


def test_p0_pack_hides_the_answer_and_the_menu(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    repo(source)
    dest = tmp_path / "pack"
    write_pack(
        source,
        dest,
        manifest=manifest(),
        arm="C",
        p0=True,
        budget=SearchBudget(candidates=3, dollars=2.0, hours=4.0),
    )
    copied = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert "examples/github_triage/agent.py" in copied
    assert "baseline/github_triage/workflow.py" not in copied
    assert "report/github_triage-dogfood.md" not in copied
    assert "ANNEAL-V3-PLAYBOOK.md" not in copied
    prompt = (dest / "PROMPT.md").read_text(encoding="utf-8")
    assert "prefetch" not in prompt.lower()
    assert "structurally different candidates" in prompt
    assert "original implementation" in prompt
    assert "validity check" in prompt
    assert "only trigger is an exception" in prompt
    assert "Make this workflow cheaper or more correct" in prompt
    assert not (dest / "MENU.md").exists()
    assert "run-hold-0009" not in (dest / "manifest.json").read_text(encoding="utf-8")


def test_arm_a_does_not_receive_the_harness(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    repo(source)
    dest = tmp_path / "pack"
    write_pack(
        source,
        dest,
        manifest=manifest(),
        arm="A",
        p0=True,
        budget=SearchBudget(candidates=3, dollars=2.0, hours=4.0),
    )
    assert not (dest / "manifest.json").exists()
    assert "structurally different" not in (dest / "PROMPT.md").read_text(encoding="utf-8")


def test_later_experiments_give_arm_c_the_menu(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    repo(source)
    dest = tmp_path / "pack"
    write_pack(
        source,
        dest,
        manifest=manifest(),
        arm="C",
        p0=False,
        budget=SearchBudget(candidates=3, dollars=2.0, hours=4.0),
    )
    menu = (dest / "MENU.md").read_text(encoding="utf-8")
    assert "prefetch plus one structured call" in menu


def test_a_copied_fixture_that_names_a_holdout_run_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    repo(source)
    fixture = source / "examples" / "github_triage" / "fixtures.jsonl"
    fixture.write_text('{"run_id": "run-hold-0009", "input": {}}\n', encoding="utf-8")
    leaked = manifest().model_copy(
        update={"workflow_files": ["examples/github_triage/fixtures.jsonl"]}
    )
    with pytest.raises(ValueError, match="holdout"):
        write_pack(
            source,
            tmp_path / "pack",
            manifest=leaked,
            arm="C",
            p0=True,
            budget=SearchBudget(candidates=1, dollars=1.0, hours=1.0),
        )
    assert not (tmp_path / "pack" / "examples" / "github_triage" / "fixtures.jsonl").exists()


def test_a_copied_file_that_names_a_holdout_run_is_a_leak(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    repo(source)
    (source / "examples" / "github_triage" / "agent.py").write_text(
        "HOLD = 'run-hold-0009'\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="holdout"):
        write_pack(
            source,
            tmp_path / "pack",
            manifest=manifest(),
            arm="B",
            p0=True,
            budget=SearchBudget(candidates=1, dollars=1.0, hours=1.0),
        )
