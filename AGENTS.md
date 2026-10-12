# AGENTS.md

Roadmap: ANNEAL-ROADMAP.md (the executable backlog; read it first). Packages live under src/.

Purpose: Anneal (anneal.run), an agent compiler. Records agent runs, finds reproducible structure, compiles it to guarded deterministic steps, hands back to the original agent on anything it cannot reproduce. Every claim of savings is measured against a handwritten workflow for the same task.

Layout (Milestone 1; grows only when a gate says so)
- anneal/schema/      canonical trace models (pydantic v2), redaction, JSONL store
- anneal/importers/   one module per source format (one in M1)
- anneal/canon/       shape abstraction, provenance, skeleton hashing
- anneal/classify/    model-call classification: removable / constrained / judgment / terminal
- anneal/compile/     WorkflowPlan and the Tier 1 compiler
- anneal/runtime/     plan executor, guards, deopt, outbox
- anneal/replay/      chronological replay, shadow, promotion, canary
- anneal/report/      savings memo and baseline comparison
- anneal/cli.py       `anneal` entry point
- baseline/           handwritten workflow(s) for the same tasks, built under the time box in ROADMAP
- tests/fixtures/     golden traces, drift suites
- docs/adr/, docs/vendor-notes/

Commands
- make setup      uv sync
- make check      ruff + mypy --strict + pytest
- make m1         runs the Milestone 1 experiment end to end and writes report/m1.md

Rules
- Work milestones in order from ROADMAP; one task per PR; tests in every PR
- CONTRACT interfaces in ROADMAP need an ADR to change; HYPOTHESIS sections may change after their test
- No infrastructure ahead of a measured need (no Rust, Parquet, extra importers or frameworks until a gate calls for them)
- No exfiltration in library code; sinks, judge and publishing are explicit user choices
- Every savings number is reported next to the handwritten baseline for the same workflow
- Python 3.12, type hints everywhere, mypy strict
