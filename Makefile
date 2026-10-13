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

baseline-test:  # one process per baseline: each has its own workflow.py and interface.py
	for d in baseline/*/; do uv run pytest $$d -q -p no:cacheprovider --no-cov || exit 1; done

m1-dryrun:
	uv run python tests/synth/dry_run.py

m1:
	uv run python tests/synth/m1.py
