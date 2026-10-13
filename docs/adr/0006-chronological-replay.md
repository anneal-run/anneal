# 0006. Chronological replay (M1.5)

Date: 2026-10-13
Status: accepted

## Context

M1.5 asks for:
- a chronological 70/30 split;
- a recording-backed tool server;
- a per-workflow task check;
- critical-field matching;
- a replay report.

It does not say where an llm step's answer comes from during replay, how a divergence is scored against fallbacks, or how a fallback is costed.

## Decision

**Split.** Runs are ordered by `(started_at, run_id)`. The first `floor(n * share)` runs (at least one, never all) are used for compiling; the rest are the holdout. Compilation receives only the early runs, so holdout data cannot leak into a plan.

**Tools.** A call is served when `(name, canonical args)` matches a recorded call. Canonical means key-order independent and treating `1.0` the same as `1`. Identical calls are served in recorded order, and a recorded tool error is raised again. Any other call is a divergence.

**LLM steps** (`llm_mode`):
- **`recorded` (default).** Answers come from the holdout run's own model call at the same prefix-tree position (`LlmStep.position_id`, added for this):
  - a forced step gets the recorded arguments for its schema keys;
  - a choice step gets the recorded tool and arguments;
  - a text step gets the recorded text.
  
  If the recorded model did something the step cannot express (a different tool, text instead of a tool, or no call at that position), the step deopts. This measures the deterministic parts exactly. It is **optimistic about forced steps**: a live model forced onto a tool would answer anyway, possibly wrongly.
- **`live`.** Any `LlmRunner` factory can be passed in. Live replay needs the M2 provider adapters, and Gate 1's H3 claim should be confirmed with it before shadow mode.

**Outcomes per holdout run:**
- **wrong.** A divergence counts as wrong at the diverging tool step's severity, because live, the compiled path would have made that call. A completed run whose task check fails counts as wrong at S0.
- **fallback.** Any other deopt.
- **correct.** The task check passes.

Wrong-execution rates are computed among accepted runs (correct plus wrong).

**Success.** System-level success counts a fallback at Tier 0's own outcome, since the original agent finishes it.

**Task check.** `TaskCheck(run, recorded) -> bool` is a per-workflow function, loaded in the CLI as `module:function`. It is evaluated the same way on the recorded run (Tier 0 success) and on the compiled trace. Without one, the default is "status success and output equivalent". It is labelled in every report as **not a partner check**, so its numbers cannot be mistaken for Gate 1 evidence.

**Critical fields.**
- **Normalization.** Amounts are compared as normalized decimals and dates as ISO strings. Recipients are emails and email/phone placeholders. Ids are other placeholders, UUIDs, tokens mixing letters and digits, and bare integers of two or more digits. Negations come from a fixed word list.
- **Equivalence.** Structures must match. Text with critical fields must match them exactly. Text without any is compared with a lexical similarity of at least 0.8. That stands in for an embedding similarity, which can be passed in; no embedding model is bundled in M1. There is no model judge.

**Cost.** Compiled cost is the trace's model spend. A fallback is additionally charged the full Tier 0 cost of the run, an upper bound on resuming.

## Consequences

- With a small removable share and frequent fallbacks, compiled cost per run can exceed Tier 0. The synthetic workflow shows exactly this: $0.0966 against $0.0882, with 37% fallbacks. The report shows it rather than hiding it.
- H3 cannot be passed on recorded-mode replay alone. The report says so on every run.

## Amendment (2026-10-13): live read-only tools

With live model answers, a constrained step writes arguments no recording has, for example a new search query. Served from the recording, every such read was a divergence, so an S0 wrong execution would be counted even when the read was harmless. `replay_plan(..., live_tools=...)` serves steps of tools declared `side_effect=False` from a live runner. Side-effect tools are always served from the recording: replay never writes. The report states which mode was used (`tools_mode`).
