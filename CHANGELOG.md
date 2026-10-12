# Changelog

## Unreleased

- M1.1: trace schema v1 (`anneal.schema`: Run, ModelCall, ToolCall, Deopt; `anneal schema dump`), typed-placeholder redactor, redact-on-write JSONL store, bundled `pricing.yaml` with cost filling, LangSmith JSONL importer (LangChain and `wrap_openai` payloads) with a synthetic, SDK-validated fixture. ADR 0002.
- M1.0: repo bootstrap. `anneal-run` package with `anneal` CLI (`--version`), uv/ruff/mypy strict/pytest/hypothesis, `make check`, GitHub Actions CI, Apache-2.0, AGENTS.md + CLAUDE.md, ADR 0001 (M1 scope), npm placeholder package.
- M1.0: names reserved: `anneal-run` 0.0.1 placeholder on PyPI and npm. PyPI releases via trusted publishing (`release.yml`, `v*` tags, `pypi` environment).
