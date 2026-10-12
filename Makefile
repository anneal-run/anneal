.PHONY: setup check lint typecheck test m1

setup:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint typecheck test

m1:
	@echo "M1 experiment not implemented yet (see ANNEAL-ROADMAP.md, M1.9)" && exit 1
