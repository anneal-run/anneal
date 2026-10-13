from pathlib import Path

import pytest

from anneal.runtime.outbox import NeedsHuman, Outbox, ReconcileAnswer, recover


def intent(outbox: Outbox, key: str, tool: str = "send") -> None:
    outbox.write_intent(key, run_id="r", step_id="s1", tool=tool, args={"to": "<EMAIL_1>"})


def test_intents_persist_across_instances(tmp_path: Path) -> None:
    intent(Outbox(tmp_path), "k1")
    record = Outbox(tmp_path).get("k1")
    assert record is not None
    assert (record.state, record.tool, record.args, record.step_id) == (
        "intent",
        "send",
        {"to": "<EMAIL_1>"},
        "s1",
    )


def test_marking_moves_a_record_out_of_open_intents(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path)
    intent(outbox, "k1")
    intent(outbox, "k2")
    outbox.mark("k1", "done")
    assert [r.key for r in Outbox(tmp_path).open_intents()] == ["k2"]
    assert Outbox(tmp_path).get("k1").state == "done"  # type: ignore[union-attr]
    assert not list(tmp_path.glob("*.tmp"))


def test_a_key_can_only_be_opened_once(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path)
    intent(outbox, "k1")
    with pytest.raises(ValueError, match="already"):
        intent(outbox, "k1")


def test_marking_an_unknown_key_fails(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        Outbox(tmp_path).mark("nope", "done")


def test_in_memory_outbox() -> None:
    outbox = Outbox()
    intent(outbox, "k1")
    outbox.mark("k1", "not_done")
    assert outbox.get("k1").state == "not_done"  # type: ignore[union-attr]
    assert outbox.open_intents() == []


def test_recover_reconciles_every_open_intent(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path)
    for key, tool in [("a", "pay"), ("b", "pay"), ("c", "mail")]:
        intent(outbox, key, tool)
    answers: dict[str, ReconcileAnswer] = {"a": "done", "b": "not_done"}
    records = recover(outbox, {"pay": lambda key: answers[key]}, raise_on_unknown=False)
    assert {r.key: r.state for r in records} == {"a": "done", "b": "not_done", "c": "unknown"}
    assert outbox.open_intents() == []


def test_unknown_after_reconciliation_raises_for_a_human(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path)
    intent(outbox, "a", "pay")
    intent(outbox, "b", "pay")

    def reconcile(key: str) -> str:
        if key == "a":
            raise TimeoutError("ledger unreachable")
        return "done"

    with pytest.raises(NeedsHuman) as excinfo:
        recover(outbox, {"pay": reconcile})  # type: ignore[dict-item]
    assert [r.key for r in excinfo.value.records] == ["a"]
    assert outbox.get("b").state == "done"  # type: ignore[union-attr]  # the rest still reconciled


def test_an_invalid_reconcile_answer_is_unknown(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path)
    intent(outbox, "a", "pay")
    records = recover(outbox, {"pay": lambda key: "maybe"}, raise_on_unknown=False)  # type: ignore[dict-item,return-value]
    assert records[0].state == "unknown"
