from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anneal.schema import Run
from anneal.schema.store import Store

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def run(run_id: str, workflow_id: str = "wf", day: int = 0, **kw: object) -> Run:
    return Run(
        run_id=run_id,
        workflow_id=workflow_id,
        started_at=T0 + timedelta(days=day),
        status="success",
        input=kw.get("input", {"q": run_id}),
        source="test",
    )


def test_write_then_read_returns_runs_sorted_by_start(tmp_path: Path) -> None:
    store = Store(tmp_path)
    assert store.write([run("b", day=2), run("a", day=0), run("c", day=1)]) == 3
    assert [x.run_id for x in store.read("wf")] == ["a", "c", "b"]


def test_read_filters_by_since(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.write([run("a", day=0), run("b", day=1), run("c", day=2)])
    since = T0 + timedelta(days=1)
    assert [x.run_id for x in store.read("wf", since=since)] == ["b", "c"]


def test_workflows_are_isolated(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.write([run("a", "wf1"), run("b", "wf2")])
    assert [x.run_id for x in store.read("wf1")] == ["a"]
    assert store.read("missing") == []


def test_write_redacts_before_touching_disk(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.write([run("a", input={"email": "jane@acme.com"})])
    on_disk = "".join(p.read_text() for p in tmp_path.rglob("*.jsonl"))
    assert "jane@acme.com" not in on_disk
    assert store.read("wf")[0].input == {"email": "<EMAIL_1>"}


def test_rewriting_a_run_id_keeps_the_last_version(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.write([run("a", input={"v": 1})])
    store.write([run("a", input={"v": 2})])
    assert [x.input for x in store.read("wf")] == [{"v": 2}]


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".."])
def test_unsafe_workflow_ids_are_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        Store(tmp_path).write([run("a", workflow_id=bad)])
