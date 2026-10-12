# 0001. Milestone 1 scope

Date: 2026-10-12
Status: accepted

## Context

Anneal compiles the reproducible parts of an agent workflow into deterministic steps and falls back to the original agent when it cannot reproduce a step. The product is only worth building if a compiled path beats a handwritten script for the same workflow on build time, cost per task, or behavior under drift (ANNEAL-ROADMAP.md, section 1). None of the hypotheses H1 to H4 have been measured.

## Decision

Milestone 1 covers one partner workflow, one trace format, one compiled path and one handwritten baseline. Its output is `report/m1.md` with measured numbers, not a platform.

- One Python 3.12 package. The distribution is `anneal-run`, the import package is `anneal` under `src/`, and the CLI is `anneal`. Build with hatchling, manage with uv.
- Storage is JSONL on disk, loaded with pandas. No SQLite, no Parquet, no Rust.
- One importer: the format the first partner actually has. LangSmith run-export JSONL is the default.
- One framework integration for fallback history reconstruction: whichever the partner uses.
- Whole-run skeletons only. No subsequence mining, no `branch` steps and no `transform` steps.
- Compiled paths execute only S0 tools live. S1 and S2 calls are rendered and logged, not executed.
- Manual compiler steps are allowed and recorded as automation debt in `report/m1.md`.
- Tooling: ruff, mypy `--strict`, pytest, hypothesis. GitHub Actions runs `make check`.

## Consequences

- Anything outside this list waits for the gate that calls for it. A PR that adds it without an ADR is rejected.
- Some M1 steps will be scripts or manual work. That is intended, and M2.2 automates them.
- The choice of importer and framework is deferred until the partner is known. The interfaces are fixed now (the `anneal.schema` CONTRACT), so that choice does not affect downstream modules.
