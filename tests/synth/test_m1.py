"""`make m1` on the simulated workflow: the experiment runs end to end (synthetic, not evidence)."""

import pytest

from anneal.report.memo import Memo, render_memo
from synth.m1 import build_memo


@pytest.fixture(scope="module")
def memo() -> Memo:
    return build_memo()


def test_the_synthetic_gate_reads_like_the_dry_run(memo: Memo) -> None:
    verdicts = {c.id: c.verdict for c in memo.gate().criteria}
    # Template-like model calls stay classified as model-written in M1: H2 is far under 25%.
    assert verdicts == {"H2": "stop", "H3": "pass", "fallback": "pass", "H4": "open"}
    assert memo.gate().verdict == "stop"
    assert memo.analyze_holdout.tier1_share < 0.25


def test_injected_deopts_cover_every_step_and_never_repeat_a_write(memo: Memo) -> None:
    assert memo.fallback is not None
    trials = memo.fallback.trials
    assert len(trials) == 20 and memo.fallback.passed == 20
    assert {t.step_id for t in trials} == {f"s{i}" for i in range(9)}


def test_the_memo_is_marked_synthetic_and_lists_the_partner_items(memo: Memo) -> None:
    text = render_memo(memo)
    assert "SYNTHETIC" in text and "Would be, on real data" in text
    assert "synth.m1:env_task_done" in text
    assert "agreed in writing with the partner" in text
