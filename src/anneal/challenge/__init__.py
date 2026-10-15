"""Anneal v3: a harness, a holdout evaluator, and a budgeted challenger.

The Milestone 1 compiler is a different product. This package does not compile
a trace into the observed path. It builds a harness the proposer can run,
scores structural candidates on a chronological holdout, and keeps every arm
inside one pre-registered search budget.
"""

from anneal.challenge.budget import BudgetLedger, SearchBudget
from anneal.challenge.harness import build_harness, write_harness
from anneal.challenge.orchestrate import orchestrate
from anneal.challenge.pack import write_pack

__all__ = [
    "BudgetLedger",
    "SearchBudget",
    "build_harness",
    "orchestrate",
    "write_harness",
    "write_pack",
]
