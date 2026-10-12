from datetime import UTC, datetime
from pathlib import Path

import pytest

from anneal.schema import ModelCall, Run
from anneal.schema.pricing import PriceTable, fill_costs

T0 = datetime(2026, 10, 12, tzinfo=UTC)


@pytest.fixture
def table(tmp_path: Path) -> PriceTable:
    path = tmp_path / "pricing.yaml"
    path.write_text(
        """
as_of: 2026-10-12
models:
  gpt-4o-mini: {input: 0.15, cached_input: 0.075, output: 0.60}
  gpt-4o: {input: 2.50, cached_input: 1.25, output: 10.00}
  tiny-tiered:
    input: 1.0
    cached_input: 0.1
    output: 2.0
    long_context: {over_input_tokens: 1000, input: 5.0, cached_input: 0.5, output: 10.0}
"""
    )
    return PriceTable.load(path)


def test_cost_per_million_tokens(table: PriceTable) -> None:
    # 1M input, 1M output, none cached
    assert table.cost("gpt-4o", 1_000_000, 1_000_000, 0) == pytest.approx(12.50)


def test_cached_tokens_are_a_subset_of_input_and_priced_at_cache_rate(table: PriceTable) -> None:
    cost = table.cost("gpt-4o-mini", tokens_in=1_000_000, tokens_out=0, tokens_cached=400_000)
    assert cost == pytest.approx(0.6 * 0.15 + 0.4 * 0.075)


def test_dated_and_provider_prefixed_names_resolve(table: PriceTable) -> None:
    assert table.price("gpt-4o-mini-2024-07-18") == table.price("gpt-4o-mini")
    assert table.price("openai/gpt-4o") == table.price("gpt-4o")
    assert table.price("gpt-4o-2024-08-06") == table.price("gpt-4o")  # not gpt-4o-mini


def test_unknown_model_has_no_price(table: PriceTable) -> None:
    assert table.price("gpt-4o-turbo") is None
    assert table.cost("nope", 10, 10, 0) is None


def test_long_context_tier_applies_to_whole_request(table: PriceTable) -> None:
    assert table.cost("tiny-tiered", 1_000, 0, 0) == pytest.approx(1_000 * 1.0 / 1e6)
    assert table.cost("tiny-tiered", 1_001, 0, 0) == pytest.approx(1_001 * 5.0 / 1e6)


def test_bundled_table_loads_and_prices_current_models() -> None:
    bundled = PriceTable.load()
    assert bundled.price("claude-sonnet-5-5") is not None
    assert bundled.price("gpt-4o-mini") is not None


def call(event_id: str, model: str, cost: float | None) -> ModelCall:
    return ModelCall(
        event_id=event_id,
        ts=T0,
        provider="openai",
        model=model,
        tokens_in=1_000_000,
        tokens_out=0,
        tokens_cached=0,
        cost_usd=cost,
    )


def test_fill_costs_fills_missing_and_keeps_source_costs(table: PriceTable) -> None:
    run = Run(
        run_id="r",
        workflow_id="wf",
        started_at=T0,
        status="success",
        source="test",
        events=[call("a", "gpt-4o", None), call("b", "gpt-4o", 9.99), call("c", "nope", None)],
    )
    costs = [e.cost_usd for e in fill_costs(run, table).events if isinstance(e, ModelCall)]
    assert costs == [pytest.approx(2.50), 9.99, None]
