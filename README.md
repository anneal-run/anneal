# Anneal

Anneal compiles your agent's hot paths into code; the model only runs on what's new.

Anneal records how an agent performs a workflow and compiles the reproducible parts into deterministic steps. Guards filter the inputs, and when a guard fails or a step cannot be reproduced, Anneal hands control back to the original agent. Every savings number is reported next to a handwritten script for the same workflow.

Status: pre-alpha (Milestone 1). See [ANNEAL-ROADMAP.md](ANNEAL-ROADMAP.md) and <https://anneal.run>.

## Install

```sh
pip install anneal-run
anneal --version
```

## Develop

```sh
make setup   # uv sync
make check   # ruff + mypy --strict + pytest
```

## License

Apache-2.0
