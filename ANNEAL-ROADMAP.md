# Anneal: Build Roadmap for Claude Code / Codex (revision 2)

Revision 2, Oct 12, 2026. Supersedes revision 1. The product is named Anneal (anneal.run). Changes: calls are classified by whether argument construction is reproducible, not by whether the tool choice repeats; guards are a pre-filter with measured error budgets, not a guarantee; fallback and side effects are designed together and early; evaluation uses chronological holdouts and task-level success; a handwritten-workflow baseline is mandatory everywhere; the first milestone is one format, one workflow, one compiled path, versus that baseline. Rust, multiple importers, multiple frameworks and transform synthesis are deferred until a result earns them.

## 0. How to work this document

This is the executable backlog for Anneal, an agent compiler: a runtime that records how an agent performs a workflow, compiles the reproducible parts into deterministic steps, filters inputs with guards, and hands control back to the original agent when a guard fails or a step cannot be reproduced. Milestones run in order. Each has tasks, interfaces, tests and a gate. Sections marked HYPOTHESIS describe things we believe and have not measured; they are not contracts until the milestone that tests them passes.

**Name and handles (CONTRACT)**

- Product: Anneal. Site and docs: `https://anneal.run`. Tagline for the README: Anneal compiles your agent's hot paths into code; the model only runs on what's new.
- Package: `anneal-run` on PyPI and npm (`anneal` is taken on both). The import package is `anneal` (`import anneal`) and the CLI is `anneal`; the distribution name is independent of both. The names are reserved with a `0.0.1` placeholder release during M1.0; a filename can never be reused on PyPI, so the first real release is `0.1.0`.
- CLI: `anneal import`, `anneal analyze`, `anneal compile`, `anneal run`, `anneal replay`, `anneal status`, `anneal doctor`, `anneal export-report` (`import` added by ADR 0004).
- Config: `anneal.toml`; plan registry `.anneal/plans/`; env prefix `ANNEAL_`.
- GitHub org: `anneal-run` (fill in the actual org once registered). License Apache-2.0.
- Email domain for partners and corp dev: `@anneal.run`.

**Operating rules for the coding agent**

1. Read this whole document and `AGENTS.md` before the first task. Interfaces marked CONTRACT are fixed between milestones; anything marked HYPOTHESIS may change after its test.
2. One task = one branch = one PR. Branch `m<N>/<task-slug>`. Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`).
3. Every PR ships tests. CI must be green before merge. Coverage never drops below the previous main.
4. Any change to a CONTRACT interface needs an ADR at `docs/adr/NNNN-<slug>.md` (context, decision, consequences) and an edit here in the same PR.
5. Never guess a third-party API. Pin versions. Before integrating a framework, read its current docs and record the pinned version and doc URL in `docs/vendor-notes/<framework>.md`.
6. The product never exfiltrates traces: no upload paths, no telemetry, no phone-home in library code. Where traces go is the user's choice through their own configured sinks; an opt-in model judge at compile time and a published benchmark bundle are explicit user actions, logged as such. Redaction runs before any trace is written to disk.
7. Do not add infrastructure ahead of a measured need. No Rust, no Parquet, no second importer, no second framework, no synthesis until the milestone that calls for it, and only if its gate condition says so.
8. After each task: run `make check`, tick the checkbox here, add a line to `CHANGELOG.md`.
9. When a task is ambiguous, write the open question into the PR description, pick the simplest interpretation that keeps CONTRACT interfaces unchanged, and continue.

**Definition of done, per task**

- Code merged behind green CI
- Unit tests for the new behavior; one integration test when the task touches a CLI command or SDK entry point
- Docstrings on public functions; a README section when user-facing
- Checkbox ticked here, CHANGELOG line added

**`AGENTS.md` to place at the repo root** (also symlink as `CLAUDE.md`)

```markdown
# AGENTS.md

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
```

## 1. What this product must beat

The competitor is not the original agent. It is a competent engineer, or a coding agent, turning the same workflow into a conventional script or graph in a day. Savings against the original inefficient agent prove nothing by themselves. The product exists only if it wins on at least one of:

- Conversion effort: a compiled path exists in less than half the time it takes to write the script, including the time to make the script safe.
- Maintenance under change: when inputs drift, the compiled path degrades gracefully (falls back) while the script fails silently or needs a human to notice and patch it.
- Breadth: the compiler covers workflows the team would never get around to scripting.

Every evaluation in this roadmap therefore has three arms: the original agent (Tier 0), the compiled path, and a handwritten baseline built under a time box and treated with the same tests. `baseline/` is a first-class directory, not an afterthought.

## 2. Metrics and error budgets (CONTRACT)

Two numbers describe a compiled path, and they trade off:

- Wrong-execution rate: among inputs the guards accepted, the fraction where the compiled path produced a task-level wrong result, by severity class. This is the safety metric.
- Fallback rate: the fraction of inputs the guards rejected or that deopted mid-plan. This is the cost metric.

Severity classes, assigned per tool at scoping time:

| Class | Meaning | Budget (default, per workflow, configurable in `anneal.toml`) |
| --- | --- | --- |
| S0 | Wrong read-only or draft output, no external effect | <= 1% of accepted runs |
| S1 | Wrong external write that is reversible with a known compensating action | <= 0.1% of accepted runs, and zero before promotion sample is met |
| S2 | Wrong irreversible external write (payment, send, delete) | Zero; never auto-promoted; human allowlist only |

Task-level success is defined per workflow with the partner before any compilation (for example: ticket landed in the correct queue, invoice total matched the ledger). Output equivalence is evidence, not the verdict. Critical fields (amounts, identifiers, recipients, dates, negations) are extracted and matched exactly; embedding similarity is used only for free text that contains no critical field.

Cost per task is always reported as three numbers: Tier 0, compiled, baseline.

## 3. Hypotheses register

| Id | Hypothesis | Tested in | Status |
| --- | --- | --- | --- |
| H1 | In real agent traffic, structurally repeated runs carry the majority of spend | M1 | untested |
| H2 | A meaningful share of model calls (target: 40%+ of spend) are removable or constrained, meaning both tool selection and argument construction can be reproduced from state | M1 | untested |
| H3 | Guards plus chronological replay plus shadow keep wrong execution inside the error budget on real traffic | M1 (replay), M2 (shadow, live) | untested |
| H4 | A compiled path with fallback beats a handwritten script on conversion effort or on behavior under drift | M1 | untested |
| H5 | Teams will install an in-process SDK and register a fallback callable | M2 | untested |
| H6 | Transform synthesis adds a second large cost drop without new wrong executions | M3 | untested |

A milestone gate is the test of its hypotheses. Failed hypotheses are recorded here with the number that failed them.

## Milestone 1: one format, one workflow, one compiled path, one baseline (weeks 1 to 4, Oct 12 to Nov 8)

Goal: on one real partner workflow, measure how much spend is actually removable, compile one hot path, prove it on a chronological holdout with task-level checks, prove fallback resumes the original agent, and compare all of it against a handwritten script built in one day. The output is `report/m1.md` with numbers, not a platform. Parts of the compiler may be scripts and manual steps in this milestone; each manual step is recorded in the report so Milestone 2 knows what to automate.

**M1.0 Minimal repo (day 1)**

- [x] Single Python package `anneal`, `uv`, `ruff`, `mypy --strict`, `pytest`, `hypothesis`; GitHub Actions running `make check`; Apache-2.0; `AGENTS.md`, `CLAUDE.md` symlink, `CHANGELOG.md`, `docs/adr/0001-m1-scope.md`
- [x] `pyproject.toml` with distribution name `anneal-run`, import package `anneal` under `src/`, console script `anneal = "anneal.cli:main"`, hatchling build; publish `0.0.1` placeholder to PyPI and an empty `anneal-run` package to npm to reserve both names; then a project-scoped PyPI token or trusted publishing from the GitHub repo
- [x] No Rust, no Parquet, no SQLite. Store is JSONL on disk, loaded with pandas. Distribution `anneal-run`, import package `anneal`, CLI `anneal`, from the first commit.

**M1.1 Schema and one importer (days 1 to 3)**

Schema (CONTRACT, `anneal.schema`, pydantic v2, `schema_version: 1`): `Run` (`run_id`, `workflow_id`, `started_at`, `ended_at`, `status`, `input`, `output`, `events`, `source`, `tier`), events `ModelCall` (`provider`, `model`, `system_hash`, `messages` redacted, `output_text`, `tool_calls_requested`, `tokens_in`, `tokens_out`, `tokens_cached`, `cost_usd`), `ToolCall` (`name`, `args`, `result`, `error`, `side_effect`, `severity`, `idempotency_key`), `Deopt` (`step_id`, `guard_id`, `reason`, `resumed_at_event`). Each event keeps `parent_id` and `ts`.

- [x] Pydantic models and `anneal schema dump`
- [x] One importer, the format the first partner actually has (default LangSmith run export JSONL; OpenTelemetry GenAI JSON as the alternative). A second importer is added only when a second partner needs it. *(Done as LangSmith JSONL against a synthetic, SDK-validated fixture; no partner yet. Re-verify on the first real export.)*
- [x] Redactor with typed placeholders (`<EMAIL_7>`, `<KEY_2>`) that preserve type class and within-run equality; regex defaults for email, phone, IBAN, card, JWT, API-key; property test that redaction is idempotent
- [x] JSONL store `write(runs)`, `read(workflow_id, since)`; pricing table `pricing.yaml`; `cost_usd` fill
- [x] Fixture under `tests/fixtures/traces/<source>/` with nested runs, a tool error, a handoff; round-trip test

**M1.2 Shape, provenance, skeleton (days 3 to 6)**

- [x] Shape tokenizer: JSON leaves to class tokens (email, URL, UUID, ISO date, numeric string, placeholder type, `enum` when 20 or fewer distinct values with 95%+ coverage, `str` with length bucket, `num`, `bool`, `null`); objects to sorted key sets; arrays to `[shape]` with length bucket
- [x] Provenance matcher: for each tool-arg leaf, search earlier output leaves in order: exact; normalized; substring of 6+; numeric or date reformat; JSON-path extraction; concatenation of up to three leaves. Edge records `(from_event, from_path, to_event, to_path, transform)`. No hit with a model-call producer: `model_generated`. No hit: `external`.
- [x] Skeleton: sequence of `(kind, tool name or model role, arg shape hash, result shape hash)` hashed with blake3; near-duplicates joined by difflib ratio >= 0.9 (union-find). No subsequence mining in M1; whole-run skeletons only.

**M1.3 Call classification (days 6 to 8, CONTRACT)**

Every model call in a cluster is classified by what it would take to reproduce it, not by what it returned:

| Class | Condition | What Tier 1 does with it | Counted as saving |
| --- | --- | --- | --- |
| `removable` | Tool choice is the same at this position in 95%+ of runs AND every argument leaf of the chosen tool has provenance that is not `model_generated` | Replaced by a `tool` step with templated args | Full call cost |
| `constrained` | Tool choice is stable but one or more argument leaves are `model_generated` | Kept as an `llm` step with the tool forced and only the arguments requested as structured output; the tool catalog leaves the prompt | Only the measured delta from one real constrained call versus the original call on the same input; never estimated |
| `judgment` | Tool choice varies, or output text flows into later args | Kept as an `llm` step, structured output | None |
| `terminal` | Produces the run output | Kept | None |

- [x] Classifier with fixture coverage for all four classes, including the trap case: same tool every run, arguments written by the model
- [x] `anneal analyze <store>`: report with run coverage by skeleton, spend share by class, and a conservative Tier 1 estimate that counts `removable` fully and `constrained` only after one measured delta
- [x] Synthetic trace generator in `tests/synth/` with planted removable, constrained and judgment calls; the analyzer must recover the planted classes exactly

**M1.4 Compile one hot path (days 8 to 12)**

`WorkflowPlan` v0 (CONTRACT fields: `plan_id` content hash, `workflow_id`, `skeleton_hash`, `compiled_from`, `steps`, `guards`, `side_effect_policy`, `tier`). Step types in M1: `tool` (`name`, `args_template`, `side_effect`, `severity`, `idempotent`), `llm` (`model`, `system_template`, `user_template`, `output_schema`, `forced_tool` or none), `end` (`output_template`). No `branch` and no `transform` in M1; a cluster that branches is compiled only along its dominant path and other paths fall back. Template syntax: `{{steps.<id>.result.<json-path>}}`, `{{input.<json-path>}}`, named transforms `lower`, `trim`, `fmt_date`, `concat`. Nothing else.

- [x] Plan models, registry at `.anneal/plans/<workflow_id>/<plan_id>.json`, renderer that errors on unknown paths
- [x] Tier 1 compiler for the dominant path: `removable` to `tool`, `constrained` and `judgment` to `llm`, `terminal` to `llm`, `end` from the output template; refuses to write a `tool` step with any unbound argument
- [x] Executor with `state` keyed by step id, dependency order, dry-run, structured-output validation with one retry then `DeoptRequested`; every compiled run is traced with `tier=1`
- [x] Manual steps allowed and logged: if the compiler cannot bind an argument that a human can see is deterministic, the human writes the template and the case is recorded in `report/m1.md` as automation debt

**M1.5 Chronological replay with task-level checks (days 12 to 15)**

- [x] Split the partner's runs by time: compile on the first 70%, test on the untouched last 30%. Never compile on test runs.
- [x] Recording-backed tool server: a tool call is served when `(name, canonical args)` matches the recorded call; mismatch is a divergence at that step and the run fails replay
- [ ] Task-level success check implemented as a function per workflow, agreed in writing with the partner before compilation (what counts as the job done) *(Mechanism done: `TaskCheck(run, recorded)`, loaded with `--check module:function`. The written partner agreement is still open, so this stays unticked.)*
- [x] Critical-field extractor and exact matcher (amounts, ids, recipients, dates, negations); embedding similarity only for free text with no critical field; no model judge in M1
- [x] Replay report: task success rate (compiled vs recorded), wrong-execution by severity, divergence histogram by step, cost per run vs Tier 0

**M1.6 Fallback that resumes the original agent (days 12 to 16, CONTRACT)**

A deopt reconstructs what the agent's own history would have been, in the framework's own message format: for each completed compiled step, one assistant message carrying the tool call and one tool-result message carrying the result, in order, after the original system prompt and the run input. The original agent loop then continues as if it had done the work. A summary message is not acceptable as resume state.

- [x] History reconstruction for the one framework the partner uses (the OpenAI Agents SDK, LangGraph or the Claude Agent SDK), pinned and documented in `docs/vendor-notes/`
- [x] `fallback(history)` registration API; the user supplies the original agent entrypoint
- [ ] Twenty injected deopts at different steps on real runs; the original agent must complete the task in 20 of 20 with task-level success, and its tool calls after resumption must not repeat a completed step *(Passes on synthetic runs with a real LangGraph graph and a history-driven policy model, with a negative control; still to be run with a partner's real runs and agent. ADR 0007.)*
- [x] A deopt mid-plan on a run that already executed a side-effect step: the test asserts the reconstructed history includes that step's call and result, so the agent does not redo it

**M1.7 Side effects, from day one (days 8 to 16, CONTRACT)**

- [x] Every tool is declared with `side_effect`, `severity` (S0, S1, S2) and one of: `idempotency_key` support, a `reconcile(key) -> done | not_done | unknown` hook, or neither. Tools with neither are `shadow_only` and cannot execute on a compiled path, full stop.
- [x] Outbox with states `intent`, `done`, `unknown`. On restart, open intents are reconciled through the hook; `unknown` after reconciliation stops the run and raises for a human; it never retries and never deopts into a repeat of the action
- [x] Operation keys are generated by the executor, written into the outbox before the call, passed to the tool, and carried into the reconstructed history on deopt so a resumed agent reusing the tool gets the same key
- [x] Chaos test: process killed between `intent` and `done`; asserts no double execution and a correct `unknown` when the tool cannot answer
- [x] In M1 the compiled path executes only S0 tools live; S1 and S2 tools are rendered, logged and not executed

**M1.8 The baseline arm (days 10 to 14, in parallel)**

- [ ] A competent engineer, or Claude Code working from the same traces and the same task definition, writes the same workflow as a plain script or graph with the tests the task-level check requires. Time box: one working day. Everything about how long it took and what it needed is logged.
- [ ] The baseline is run on the same chronological holdout with the same task-level check and the same cost accounting
- [ ] Drift suite: three injected changes to the holdout inputs (a new enum value, a schema change such as a renamed field, a new input topic). For each arm record: fails loudly, fails silently (wrong result with no signal), or falls back. The compiled arm's guards in M1 are only schema, enum, range, length and pattern; no OOD scoring yet.

**M1.9 The memo (days 16 to 20)**

- [ ] `report/m1.md`: spend share by class (H1, H2); replay task success and wrong-execution by severity (H3); fallback results; baseline comparison table (build time, cost per task, task success, drift behavior per arm) (H4); list of manual steps taken; hypotheses register updated with numbers
- [ ] The memo is sent to the partner and to at least two other teams whose traces were analyzed

**Gate 1** (all required unless marked)

- H2: `removable` plus measured `constrained` savings are at least 40% of the workflow's spend on the holdout. Under 25%: stop. Between: proceed only if the baseline comparison is won on drift.
- H3: compiled task success on the chronological holdout is within 1 percentage point of Tier 0; zero S1 or S2 wrong executions; S0 within budget
- Fallback: 20 of 20 injected deopts complete with task-level success and no repeated steps
- H4: the compiled arm beats the baseline on at least one of: build time (under half), cost per task, or drift behavior (falls back on at least two of three drift types where the script fails silently or needs a patch). If the script wins on all three, stop.
- Interview signal (not a kill): what each of the five teams said when asked whether they would just write the script, recorded next to the measured comparison

## Milestone 2: make it a product on three live workflows (weeks 5 to 12, Nov 9 to Jan 3)

Goal: everything that was a script or a manual step in M1 becomes automatic; three partner workflows run compiled paths on live traffic inside their error budgets; the baseline comparison is repeated per workflow. The architecture is allowed to grow only where M1 showed the need.

**M2.1 Capture SDK and the one framework integration, with fallback built in**

The SDK and the fallback are one deliverable because the integration is where the framework's message format lives.

- [ ] `anneal.wrap_openai(client)` and `anneal.wrap_anthropic(client)` proxies (chat completions, messages, streaming, tool-use responses); `@anneal.tool(side_effect, severity, idempotent, reconcile)`; `anneal.run(workflow_id, input)` with `contextvars` propagation; JSONL sink by default, OTLP sink as a user-configured option
- [ ] Integration for the framework the partners use, including history reconstruction from M1.6 as part of the integration module; `examples/<framework>/` driven by a replay-based fake model; golden-trace tests
- [ ] Overhead benchmark; fail CI above 2 ms p95 per event
- [ ] A second framework integration only if a signed partner uses it

**M2.2 Compiler generalization**

- [ ] Automate every manual step logged in `report/m1.md`; the list is the backlog
- [ ] `constrained` steps implemented end to end: forced tool, arguments-only structured prompt, measured delta recorded in the plan
- [ ] `branch` step: a decision tree on state features is accepted only if it reproduces every branch on the compile split AND every branch on the chronological holdout; otherwise the branch point stays an `llm` step
- [ ] Subsequence mining (PrefixSpan, min support 5 runs or 2%) so sub-paths shared across skeletons can be compiled when whole runs vary
- [ ] `anneal compile` and `anneal run` CLIs with a human-readable compile log that names every refused binding

**M2.3 Guards as a pre-filter with measured budgets**

Guards do not guarantee anything. They reject obvious drift cheaply so that the expensive checks (replay, shadow, canary) see fewer surprises. Their setting is chosen per workflow from the measured curve of wrong-execution rate among accepted inputs versus fallback rate.

- [ ] Static guards mined on the compile split and validated on the holdout: `schema`, `enum` (20 or fewer values, 95%+ support), `range` (widened 10%), `length`, `pattern`, `invariant`. A guard that rejects more than 1% of holdout runs is widened once, then dropped and logged.
- [ ] Optional `ood` guard: features from shapes, enum one-hots, bucketed numerics and a small local ONNX embedding of free-text leaves; nonconformity as mean distance to 5 nearest compile-split points; the threshold is not fixed at 95% but chosen on the holdout to meet the workflow's severity budget at the lowest fallback rate, and both numbers are stored in the plan
- [ ] Per-workflow report of the accepted-wrong versus fallback curve; the chosen operating point is written into `anneal.toml` and `PARTNER.md`
- [ ] Guard evaluation stays in Python until p95 exceeds 5 ms on a real workflow; only then is a Rust evaluator considered, as its own ADR

**M2.4 Shadow mode with a defined source for skipped writes**

- [ ] `Executor(mode="shadow")` runs the plan beside the live Tier 0 agent on the same input. Read-only tools execute live. For a side-effect step, the plan does not execute; it renders the call and takes the result of the live agent's matching call (same tool, canonical args equal) as the step result. If no matching call exists, the comparison is marked truncated at that step and counts as a disagreement for promotion.
- [ ] `ShadowResult` rows with task-level outcome, critical-field match, severity of any disagreement

**M2.5 Promotion by error budget, and a canary after promotion**

- [ ] Sample sizes by the highest severity class the plan touches: S0 only, 100 shadow runs with S0 within budget; S1, 300 shadow runs with zero S1 disagreements; S2, no automatic promotion, a human allowlists the specific tool and plan after review. Rationale is recorded in the plan: fifty clean runs still leave about a 6% one-sided upper bound on the failure rate at 95% confidence; three hundred brings it near 1%.
- [ ] Canary: after promotion, a configurable sample (default 5%) of runs keeps executing at Tier 0, in parallel or instead, so agreement and task success remain measurable without a live baseline. Demotion when trailing-100 canary agreement drops below 0.95, fallback rate exceeds 0.20, or any S1 wrong execution appears; demotion opens a recompile ticket
- [ ] `anneal status <workflow>`: tier, accepted-wrong by severity, fallback rate, canary agreement, open tickets
- [ ] Transition events for every promotion and demotion with the numbers that triggered them

**M2.6 Partner pilots (three, starting week 5; one may be the M1 partner)**

1. Intake: traces, `anneal analyze`, qualify on the class shares
2. Scoping in writing (`PARTNER.md`): task-level success definition, tool table with `side_effect`, `severity`, `idempotent`, `reconcile`, the severity budgets, dollars per task today
3. Install the SDK with the fallback registered; verify golden-equal traces
4. Two weeks of live capture; compile; chronological replay; the baseline arm built under the same one-day time box
5. Shadow to the sample size the severity class requires
6. Promote; canary on; four weeks of measurement with weekly snapshots
7. Case study row filled only with numbers the partner approved

- [ ] `anneal doctor`, `anneal export-report` (analyze, replay, status, baseline comparison, redaction verified), weekly snapshot command, `PARTNER.md` template

**Gate 2**

- Three workflows live at Tier 1 on partner traffic for four weeks, each inside its severity budget, each with canary agreement >= 0.95
- Per workflow, a baseline comparison with the same three dimensions as M1; at least one workflow where the compiled path beat the script under drift, written up
- H5 confirmed: three teams installed the SDK and registered a fallback without a pairing session longer than one day
- Automation debt from M1 cleared; the compile log names no manual steps on the three workflows

## Milestone 3: Tier 2, the public benchmark, the case (weeks 12 to 22, Jan 4 to Mar 21)

Goal: a second cost drop from transforms where it is safe, a reproducible three-arm benchmark, three published partner numbers, and the material acquirers will ask for.

**M3.1 Tier 2 transforms, conservative**

- [ ] Direct path first: `constrained` or `judgment` steps whose provenance already names the transform (`lower`, `trim`, `fmt_date`, `concat`, JSON-path extraction) are emitted as `transform` steps with no synthesis. Measure how much of Tier 2 this alone delivers before writing a synthesizer.
- [ ] Synthesis only for steps with structured output, all inputs in state, and at least 30 distinct pairs; chronological 80/20 split; the compile-time model writes one pure function with imports limited to `json`, `re`, `datetime`, `math`; up to 3 repair rounds; accept only at 100% on both splits; otherwise keep the `llm` step
- [ ] Sandbox v1: separate process, no network, read-only empty working directory, 256 MB, 2 s CPU, allowlisted imports; escape tests (socket, file write, `import os`, infinite loop, memory bomb) fail closed. WASM and Rust synthesis only if a partner's latency or isolation requirement is measured and recorded in an ADR
- [ ] Transforms inherit the guards and severity of the step they replace; promotion through M2.5 unchanged

**M3.2 The three-arm benchmark**

- [ ] Public tool-use environments (AppWorld-style, tau-bench-style) pinned and vendored by script; three synthetic operations workflows (invoice extraction and validation, ticket triage and routing, record enrichment) with in-distribution and drift generators
- [ ] Arms: Tier 0 agent, compiled (Tier 1 and Tier 2), handwritten baseline built under the one-day time box by a coding agent from the same traces
- [ ] Protocol: 200 inputs per workflow, warm on the first 50 chronologically, measure on the last 150; three seeded repeats; report median and spread; pinned models, prices, seeds and commit in the header
- [ ] Metrics per arm: cost per task, p50 and p95 latency, task success, wrong-execution by severity among accepted, fallback rate, drift behavior (loud, silent, fallback) per drift type
- [ ] `benchmarks/RESULTS.md` regenerated by `make bench`, with a section for every workflow where the compiled arm did not beat the baseline and why; raw redacted traces published as an explicit bundle step
- [ ] `benchmarks/README.md` explaining how an outside team adds a workflow

**M3.3 Second and third framework integrations** only after Gate 2, in the order partners ask for them.

**Gate 3**

- `make bench` reproduces `RESULTS.md` on a second machine within the reported spread, baseline arm included
- Three partner case-study rows approved; at least one at Tier 2; at least one reference call
- Corp dev conversations open with at least three acquirers at once, using the benchmark and the drift comparison as the lead material

## Timeline, gates and kill criteria

```
Milestone 1                  Milestone 2                     Milestone 3
One workflow, one baseline   Three live workflows            Tier 2, benchmark, case
Oct 12 to Nov 8, 2026        Nov 9 to Jan 3, 2027            Jan 4 to Mar 21, 2027
                   [Gate 1]                       [Gate 2]                        [Gate 3]
                   40%+ spend removable           3 live inside budgets           Benchmark public, 3 arms
                   beats script on 1 of 3         beat script under drift once    3 partners, corp dev open

Partner pilots run from week 5. Corp dev from week 18.
```

**Kill criteria, any time**

- The handwritten baseline wins on build time, cost and drift behavior for two workflows in a row: there is no product, stop
- `removable` plus measured `constrained` spend is under 25% on two real workflows: the thesis is wrong for real traffic, stop
- An S1 or S2 wrong execution reaches a partner's production after the budgets were met and two fixes: the safety story is not real, stop
- A major framework ships trace-to-graph compilation: compress Milestone 3, open acquirer conversations that week, treat the three-arm benchmark and the drift comparison as the asset

## Non-goals and boundaries

Anneal is a compiler and a cost product, measured against a handwritten baseline. Out of scope for this roadmap; a PR that adds one is rejected without an ADR:

- No hosted trace storage, no SaaS backend, no telemetry; the store is the user's disk or bucket and the sinks are the user's configuration
- No monitoring dashboards, alerting or observability UI; `anneal status` prints text, the OTLP sink feeds existing tools
- No network proxy, gateway or interception; capture is in-process only
- No security scanning, prompt-injection detection, PII product or compliance reporting; redaction exists so traces are safe to store locally
- No Rust before a measured need recorded in an ADR; no Parquet, second importer or second framework before the gate that calls for it
- No fine-tuning or distillation service; distilled judgment models are a separate roadmap after Gate 3
- No cross-customer learning; plans, guards and indexes are per workflow, per store; shared improvements ship as code
- No templates with arbitrary code; the binding syntax is the whole template language, computation lives in guarded `transform` steps
- No claim of a guarantee anywhere in docs or marketing; the product reports measured wrong-execution and fallback rates against stated budgets
