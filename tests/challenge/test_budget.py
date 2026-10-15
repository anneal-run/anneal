"""Each arm gets the same search budget. Extra scored candidates do not count."""

import pytest

from anneal.challenge.budget import BudgetLedger, SearchBudget


def test_each_arm_has_the_same_cap() -> None:
    ledger = BudgetLedger(SearchBudget(candidates=2, dollars=1.0, hours=1.0))
    ledger.charge("C", dollars=0.4, hours=0.2)
    ledger.charge("B", dollars=0.4, hours=0.2)
    assert ledger.spent("C").candidates == 1
    assert ledger.spent("B").candidates == 1


def test_a_third_scored_candidate_is_refused() -> None:
    ledger = BudgetLedger(SearchBudget(candidates=2, dollars=5.0, hours=5.0))
    ledger.charge("C", dollars=0.1, hours=0.1)
    ledger.charge("C", dollars=0.1, hours=0.1)
    with pytest.raises(ledger.Exceeded):
        ledger.charge("C", dollars=0.1, hours=0.1)
    assert ledger.spent("C").candidates == 2


def test_dollars_and_hours_are_caps_too() -> None:
    ledger = BudgetLedger(SearchBudget(candidates=5, dollars=1.0, hours=1.0))
    ledger.charge("A", dollars=0.6, hours=0.1)
    with pytest.raises(ledger.Exceeded):
        ledger.charge("A", dollars=0.5, hours=0.1)
