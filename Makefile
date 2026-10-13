.PHONY: setup check lint typecheck test baseline-test m1-dryrun m1

setup:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint typecheck test baseline-test

baseline-test:
	uv run pytest baseline -q -p no:cacheprovider --no-cov

m1-dryrun:
	uv run python tests/synth/dry_run.py

m1:
	uv run python tests/synth/m1.py
