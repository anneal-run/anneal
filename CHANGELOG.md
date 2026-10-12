# Changelog

## Unreleased

- M1.4: `WorkflowPlan` v0 with content-hash ids and a registry; the template language (`input`/`steps` refs, `trim`, `lower`, `fmt_date`, `concat`) with a strict renderer; the Tier 1 compiler for the dominant path (refused bindings logged, manual overrides recorded as automation debt); the executor (dependency order, guards, dry-run, one structured-output retry, deopt before non-live writes, tier 1 traces). ADR 0005.
- M1.3: call classifier over prefix-tree positions (removable / constrained / judgment / terminal, with reasons and argument bindings), `anneal import langsmith`, `anneal analyze` (skeleton coverage, spend by class, conservative Tier 1 estimate with measured constrained deltas), synthetic generator with planted classes recovered exactly. ADR 0004.
- M1.2: `anneal.canon`: shape tokenizer with enum vocabulary, provenance matcher (exact, normalized, substring, number/date, embedded JSON, concat; model text as a source), whole-run skeletons hashed with blake3 and clustered by difflib ratio with union-find. ADR 0003.
- M1.1: trace schema v1 (`anneal.schema`: Run, ModelCall, ToolCall, Deopt; `anneal schema dump`), typed-placeholder redactor, redact-on-write JSONL store, bundled `pricing.yaml` with cost filling, LangSmith JSONL importer (LangChain and `wrap_openai` payloads) with a synthetic, SDK-validated fixture. ADR 0002.
- M1.0: repo bootstrap. `anneal-run` package with `anneal` CLI (`--version`), uv/ruff/mypy strict/pytest/hypothesis, `make check`, GitHub Actions CI, Apache-2.0, AGENTS.md + CLAUDE.md, ADR 0001 (M1 scope), npm placeholder package.
- M1.0: names reserved: `anneal-run` 0.0.1 placeholder on PyPI and npm. PyPI releases via trusted publishing (`release.yml`, `v*` tags, `pypi` environment).
