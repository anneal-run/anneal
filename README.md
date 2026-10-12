# Anneal

Anneal compiles your agent's hot paths into code; the model only runs on what's new.

Anneal records how an agent performs a workflow and compiles the reproducible parts into deterministic steps. Guards filter the inputs, and when a guard fails or a step cannot be reproduced, Anneal hands control back to the original agent. Every savings number is reported next to a handwritten script for the same workflow.

Status: pre-alpha (Milestone 1). See [ANNEAL-ROADMAP.md](ANNEAL-ROADMAP.md) and <https://anneal.run>.

## Install

```sh
pip install anneal-run
anneal --version
```

## Analyze a workflow (M1)

```sh
anneal import langsmith export.jsonl --store .anneal/store   # redacted on write
anneal analyze .anneal/store                                  # add --json for machine output
```

`anneal analyze` reports run coverage by skeleton, model spend by call class (`removable`, `constrained`, `judgment`, `terminal`), and a conservative Tier 1 saving. The saving counts removable calls in full, and constrained calls only where you pass a measured delta (`--deltas deltas.json`, keyed by position id). The LangSmith export format is described in [docs/vendor-notes/langsmith.md](docs/vendor-notes/langsmith.md). `anneal schema dump` prints the JSON Schema of a run.

## Develop

```sh
make setup   # uv sync
make check   # ruff + mypy --strict + pytest
```

## Release

Bump `version` in `pyproject.toml`, merge to `main`, then push a matching tag (`git tag v0.1.0 && git push origin v0.1.0`). The `release` workflow checks, builds and publishes to PyPI through trusted publishing; no token is stored anywhere.

## License

Apache-2.0
