"""Per-arm search budget. Every arm receives the same cap; the ledger refuses the rest."""

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchBudget(_Model):
    """Scored candidates, model dollars, and wall-clock hours. Written before day 1."""

    candidates: int
    dollars: float
    hours: float


class Spend(_Model):
    candidates: int = 0
    dollars: float = 0.0
    hours: float = 0.0


class BudgetLedger:
    """Charge one scored candidate at a time. A charge past the cap is not recorded."""

    class Exceeded(Exception):
        """This arm has spent its search budget."""

    def __init__(self, budget: SearchBudget) -> None:
        self.budget = budget
        self._spent: dict[str, Spend] = {}

    def charge(self, arm: str, *, dollars: float, hours: float) -> None:
        current = self.spent(arm)
        proposed = Spend(
            candidates=current.candidates + 1,
            dollars=current.dollars + dollars,
            hours=current.hours + hours,
        )
        if (
            proposed.candidates > self.budget.candidates
            or proposed.dollars > self.budget.dollars
            or proposed.hours > self.budget.hours
        ):
            raise self.Exceeded(arm)
        self._spent[arm] = proposed

    def spent(self, arm: str) -> Spend:
        return self._spent.get(arm, Spend())
