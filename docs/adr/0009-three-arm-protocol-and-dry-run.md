# 0009. Three-arm protocol, drift suite, and what the synthetic dry run says (M1.8)

Date: 2026-10-13
Status: accepted

## Context

M1.8 requires:
- a handwritten baseline built from the same traces under a one-day time box;
- the baseline run on the same holdout with the same task check and cost accounting;
- a drift suite (a new enum value, a renamed field, a new input topic) that records for each arm whether it fails loudly, fails silently, or falls back.

There is no partner workflow yet. Drifted inputs have no recordings, so the arms cannot be compared by replay alone.

## Decision

**Harness** (`anneal.replay.arms`, product code). Each arm runs each case on its own copy of the input, and each run is scored:
- `correct`;
- `fallback` (handed off, job done);
- `fallback_wrong` (handed off after a wrong write);
- `loud` (raised or reported an error);
- `silent` (finished with no signal, job not done).

Per arm and drift type, the behaviour is the worst mode that occurred. Any silent or fallback-wrong run makes it "fails silently".

**Compiled-arm guards.** Guards are mined from the compile runs on the dominant path:
- **Which fields.** A `schema` guard goes on every input field the plan reads. Because llm steps read the whole input, that is every field.
- **Patterns.** A `pattern` guard by string class is added when all values share one.
- **Enums.** An `enum` guard is added by the M1.2 rule.
- **Ranges.** Numbers get a `range` guard widened by 10% of the observed span.

Two consequences:
- **Guards predict the branch.** Mining on the dominant path makes them a cheap branch predictor. In the dry run, `priority=high` always escalates, so the auto-reply plan's enum guard excludes it, and those inputs fall back at the guards instead of at the routing step.
- **Redaction equivalence.** A pattern guard treats a raw value and its redaction placeholder as the same class. Plans are compiled from the redacted store but run on live input, and without this every live email would fail its guard.

**Simulated environment** (`tests/synth/env.py`, test code). It provides tools that record their effects, a simulated model that reads flexibly and decides deterministically (every model call costs the same in every arm), the ground-truth task definition, a history-driven Tier 0 agent that produces the traces, and the three drifts.

**Baseline.** The baseline is written by a separate agent given only `baseline/env_support/BRIEF.md`, the 56 compile-split traces and `interface.py`, and told not to read anything else in the repo. It logs its own time and its questions for the business.

**Simulator fix before the comparison.** `ModelCapabilities.choose` originally implemented only routing. The baseline asks a classification question (`order_problem` vs `not_order_problem`), which a real model would answer correctly, so `choose` was made topic-aware before the baseline was evaluated. Leaving it unfixed would have turned the baseline's correct refusals into silent wrong tickets.

## What the dry run says

The numbers are in `report/m1.8-synthetic-dry-run.md` (`make m1-dryrun`). They are synthetic and are not Gate 1 evidence.

| arm | build | cost per task | holdout task success | new enum | new topic | renamed field |
| --- | --- | --- | --- | --- | --- | --- |
| tier0 | existing | $0.0900 | 100% | handles it | handles it | handles it |
| compiled | 0.02 s compute, plus tool declarations | $0.0825 | 100% (12 of 24 via fallback) | falls back | fails silently | falls back |
| baseline | 1 min 46 s (agent) | $0.0000 | 100% | fails loudly | fails loudly | handles it |

**Read against H4.** The script wins on cost and build time. On drift, the compiled arm falls back on two drift types, but only one of them (the new enum) is a case where the script needs a patch; the script handles the renamed field itself. On the new topic, the compiled arm writes wrong tickets, silently in 12 runs and before a deopt in 9 more, where the script refuses loudly. On a real workflow, that is the "stop" outcome of Gate 1.

**Why the compiler lost here.** Each of these points to roadmap work:
1. **The routing decision is a rule over state** (priority or tier). The M1 compiler can only keep it as a judgment llm step and deopt on the minority branch, which is 50% fallbacks. The M2.2 `branch` step (a decision tree accepted only if it reproduces every branch on both splits) is exactly what was missing.
2. **Ticket summary, reply and answer are deterministic templates of the input and earlier results.** The compiler classified them as model-written because provenance finds no transform for them. Expressing them needs M3.1 transform synthesis.
3. **A new topic passes schema and enum guards.** Only an OOD guard (M2.3) or a model-side refusal can catch it. Until then, compiled paths on workflows whose input topics can change are unsafe for S1 and S2 writes, and replay with recorded answers would not show it (ADR 0006).

**Fairness caveats.**
- The baseline author is the same model family as the compiler's author, working in minutes, not an engineer working for a day.
- The compiled arm's build time excludes writing the tool declarations and the task check.
- The workflow is one whose model calls are all deterministic in hindsight, which favours the script.

## Consequences

- The harness, drift suite and report are ready for a partner workflow; only the environment changes.
- Before M1.9 on real traces, it is worth checking `anneal analyze` output for the pattern seen here: model calls whose outputs are template-like. They are the cheapest wins for a script and the hardest for the M1 compiler.
