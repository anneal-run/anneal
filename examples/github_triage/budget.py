"""A spend ledger that stops the experiment before it goes over budget.

Costs come from token usage priced with anneal's pricing table, so the ledger
works for any provider in `pricing.yaml`. The ledger is a JSON file shared by every
script in the experiment; `TRIAGE_BUDGET_USD` sets the cap (default 20).
"""

import fcntl
import json
import os
from pathlib import Path
from typing import Any

from anneal.schema.pricing import PriceTable

LEDGER = Path(os.environ.get("TRIAGE_DATA", Path(__file__).parent / "data")) / "spend.json"


class OverBudget(RuntimeError):
    pass


class Budget:
    def __init__(self, path: Path = LEDGER, cap: float | None = None) -> None:
        self.path = path
        self.cap = cap if cap is not None else float(os.environ.get("TRIAGE_BUDGET_USD", "20"))
        self.prices = PriceTable.load()

    def spent(self) -> dict[str, float]:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def total(self) -> float:
        return sum(self.spent().values())

    def check(self) -> None:
        if self.total() >= self.cap:
            raise OverBudget(f"spent ${self.total():.2f} of ${self.cap:.2f}")

    def cost(self, usage: dict[str, Any]) -> float:
        """Cost of a `UsageMetadataCallbackHandler.usage_metadata` dict."""
        total = 0.0
        for model, u in usage.items():
            cached = (u.get("input_token_details") or {}).get("cache_read", 0) or 0
            price = self.prices.cost(model, u["input_tokens"], u["output_tokens"], cached)
            if price is None:
                raise KeyError(f"no price for {model}; add it to pricing.yaml")
            total += price
        return total

    def add(self, phase: str, usd: float) -> None:
        """Add spend under an exclusive lock: several runner processes share the ledger."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with (self.path.parent / ".spend.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            spent = self.spent()
            spent[phase] = spent.get(phase, 0.0) + usd
            self.path.write_text(json.dumps(spent, indent=1, sort_keys=True))
