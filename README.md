# Anneal

Anneal compiles your agent's hot paths into code; the model only runs on what's new.

Anneal records how an agent performs a workflow and compiles the reproducible parts into deterministic steps. Guards filter the inputs, and when a guard fails or a step cannot be reproduced, Anneal hands control back to the original agent. Every savings number is reported next to a handwritten script for the same workflow.

Status: pre-alpha (Milestone 1). See [ANNEAL-ROADMAP.md](ANNEAL-ROADMAP.md) and <https://anneal.run>.

## Install

```sh
pip install anneal-run
anneal --version
```

## Import traces (M1)

Anneal reads a LangSmith run export: one JSON run per line, from `Client.list_runs()`. The format is described in [docs/vendor-notes/langsmith.md](docs/vendor-notes/langsmith.md).

```python
from anneal.importers.langsmith import load_runs
from anneal.schema.pricing import PriceTable, fill_costs
from anneal.schema.store import Store

prices = PriceTable.load()  # bundled table; pass a path to use your own
runs = [fill_costs(r, prices) for r in load_runs("export.jsonl")]
Store(".anneal/store").write(runs)  # redacted before it touches disk
```

`anneal schema dump` prints the JSON Schema of a run.

## Develop

```sh
make setup   # uv sync
make check   # ruff + mypy --strict + pytest
```

## Release

Bump `version` in `pyproject.toml`, merge to `main`, then push a matching tag (`git tag v0.1.0 && git push origin v0.1.0`). The `release` workflow checks, builds and publishes to PyPI through trusted publishing; no token is stored anywhere.

## License

Apache-2.0
