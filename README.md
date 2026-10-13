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
anneal replay .anneal/store --tools tools.yaml --check my_checks:task_done
```

`anneal analyze` reports run coverage by skeleton, model spend by call class (`removable`, `constrained`, `judgment`, `terminal`), and a conservative Tier 1 saving. The saving counts removable calls in full, and constrained calls only where you pass a measured delta (`--deltas deltas.json`, keyed by position id). The LangSmith export format is described in [docs/vendor-notes/langsmith.md](docs/vendor-notes/langsmith.md). `anneal replay` compiles on the earliest 70% of runs and replays the rest against their recordings. It reports task success against Tier 0, wrong executions by severity, fallbacks, and cost per run. `tools.yaml` declares each tool's `side_effect`, `severity`, `idempotent` (accepts an operation key, and a repeat under it is a no-op) and `reconcile` (a `reconcile(key)` hook will be registered). Undeclared tools are treated as irreversible (S2). A side-effect tool with neither a key nor a hook is `shadow_only` and never runs on a compiled path. `--check` names your task-level success function, `(run, recorded) -> bool`. Without it, the report uses output equivalence and says so.

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
