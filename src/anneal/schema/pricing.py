"""Model price table and cost filling.

Prices live in `pricing.yaml` (bundled) or a user-supplied file of the same
shape. Model names resolve exactly, after stripping a `provider/` prefix, or by
dropping a trailing date snapshot such as `-2024-07-18` or `-20250929`.
"""

import re
from importlib.resources import files
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from anneal.schema.models import ModelCall, Run

_DATE_SUFFIX = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$")


class Rates(BaseModel):
    """USD per 1M tokens."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input: float
    cached_input: float
    output: float


class LongContext(Rates):
    over_input_tokens: int


class ModelPrice(Rates):
    long_context: LongContext | None = None

    def rates_for(self, tokens_in: int) -> Rates:
        if self.long_context and tokens_in > self.long_context.over_input_tokens:
            return self.long_context
        return self


class PriceTable(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    models: dict[str, ModelPrice]

    @classmethod
    def load(cls, path: Path | str | None = None) -> "PriceTable":
        """Load `path`, or the bundled table when `path` is None."""
        if path is None:
            text = files("anneal.schema").joinpath("pricing.yaml").read_text(encoding="utf-8")
        else:
            text = Path(path).read_text(encoding="utf-8")
        return cls.model_validate(yaml.safe_load(text))

    def price(self, model: str) -> ModelPrice | None:
        """Price for `model`, or None when it is not in the table."""
        name = model.rsplit("/", 1)[-1]
        return self.models.get(name) or self.models.get(_DATE_SUFFIX.sub("", name))

    def cost(self, model: str, tokens_in: int, tokens_out: int, tokens_cached: int) -> float | None:
        """USD cost of one call; `tokens_cached` is a subset of `tokens_in`."""
        price = self.price(model)
        if price is None:
            return None
        rates = price.rates_for(tokens_in)
        uncached = tokens_in - tokens_cached
        usd = (
            uncached * rates.input + tokens_cached * rates.cached_input + tokens_out * rates.output
        )
        return usd / 1_000_000


def fill_costs(run: Run, table: PriceTable) -> Run:
    """Fill `cost_usd` on model calls that lack it; costs reported by the source are kept."""
    events = []
    for event in run.events:
        if isinstance(event, ModelCall) and event.cost_usd is None and event.model:
            cost = table.cost(
                event.model,
                event.tokens_in or 0,
                event.tokens_out or 0,
                event.tokens_cached or 0,
            )
            event = event.model_copy(update={"cost_usd": cost})
        events.append(event)
    return run.model_copy(update={"events": events})
