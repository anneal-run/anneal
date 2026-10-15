# Anneal

Anneal v3 tests whether a coding agent, given a harness and a holdout, can find a better architecture for an existing agent workflow than the same coding agent would find on its own. The spec is [ANNEAL-V3-PLAYBOOK.md](ANNEAL-V3-PLAYBOOK.md).

```sh
anneal challenge harness .anneal/store --tools tools.yaml --out harness/
anneal challenge pack --source . --harness harness --out pack-c --arm C --p0 --budget budget.json
anneal challenge orchestrate --budget budget.json --baseline baseline.jsonl \
    --submissions candidates/ --holdout holdout.json --out report/workflow.md
```

`challenge harness` writes fixtures and recordings from the optimization split only. Holdout run ids go in `SEAL.json` and are not copied into an arm's pack. `challenge orchestrate` ranks on the optimization set, opens the holdout once for the top three structural candidates per arm, and refuses anything past the shared search budget. A prompt-only win is reported and cannot be the structural winner.

The Milestone 1 compiler is still in this tree (`anneal import`, `anneal analyze`, `anneal replay`). It records a workflow and tries to compile the observed path. On `examples/github_triage` that path did not survive the holdout; a separate coding agent wrote a cheaper script instead. The compiler is evidence and a trace library, not the v3 challenger. See [ANNEAL-ROADMAP.md](ANNEAL-ROADMAP.md) and <https://anneal.run>.

## Install

```sh
pip install anneal-run
anneal --version
```

## Quickstart: a LangGraph agent, end to end

[`examples/github_triage`](examples/github_triage) is a small LangGraph agent that triages GitHub issues with a real model and read-only GitHub tools, traced to LangSmith. The commands below run the whole Milestone 1 path on it. What happened when we did is in [report/github_triage-dogfood.md](report/github_triage-dogfood.md).

```sh
uv sync                                     # includes the `examples` dependency group
export GITHUB_TOKEN=...                     # public read-only access is enough
export ANTHROPIC_API_KEY=...                # or TRIAGE_PROVIDER=openai and OPENAI_API_KEY
export LANGSMITH_TRACING=true LANGSMITH_API_KEY=... LANGSMITH_PROJECT=github-triage
export PYTHONPATH=examples
D=examples/github_triage/data

# 1. Pick closed issues and record what maintainers did with them (the task check's ground truth)
uv run python -m github_triage.select_issues astral-sh/uv 200 $D/uv.jsonl

# 2. Run the agent on them, traced, oldest first (a split by time is then a split by issue age)
uv run python -m github_triage.run $D/uv.jsonl --dataset uv

# 3. Export the traces, import them into a redacted local store, and see where the spend goes
uv run python -m github_triage.experiment export import
uv run anneal analyze $D/store --workflow github_triage

# 4. Compile, replay (recorded and live), inject deopts into the real agent, run the arms, write the memo
uv run python -m github_triage.experiment compile replay deopts arms memo
```

Before step 3, run steps 1 and 2 for the drift repositories too: `pydantic/pydantic` (100 issues), `python/mypy` (30) and `godotengine/godot` (30), each with `--dataset` set to `pydantic`, `mypy` and `godot`, and the output file named to match. The driver expects all four datasets, and the arms need the handwritten baseline in `baseline/github_triage/`. Step 4 uses the Python API for what the CLI does not expose yet:
- an output path for graph state: `compile_plan(..., output_path="$.triage")`;
- live model answers: `chat_model_runner`;
- live read-only tools during replay: `replay_plan(..., live_tools=...)`;
- resuming the real agent on a deopt: `CompiledWorkflow` with `langgraph_fallback`.

Every paid step goes through a spend ledger capped at `TRIAGE_BUDGET_USD` (default $20). Our full run cost $2.05.

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
