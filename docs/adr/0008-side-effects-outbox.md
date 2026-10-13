# 0008. Side effects: declarations, outbox, operation keys (M1.7)

Date: 2026-10-13
Status: accepted

## Context

M1.7 requires:
- every tool declared with an idempotency key, a reconcile hook, or neither (then it is `shadow_only`);
- an outbox (`intent`, `done`, `unknown`) reconciled on restart, where unknown is never retried and never handed to an agent to repeat;
- executor-generated operation keys, passed to the tool and carried into reconstructed history;
- a chaos test that kills the process between intent and done.

What happens when a side-effect call *raises*, rather than the process dying, is not specified.

## Decision

**Declarations.**
- `ToolSpec` and `ToolStep` gain `reconcile: bool` next to the existing `idempotent: bool` (which means "accepts an operation key; a repeat under it is a no-op").
- A side-effect step with neither is `shadow_only`. `WorkflowPlan.shadow_only_steps()` lists them, the compile log names them, and the executor deopts before calling one, whatever the live severities. Replay turns the policy off (`enforce_side_effects=False`), because recordings have no effects.
- A step that declares `reconcile` but has no registered hook is a construction error.

**Operation keys.**
- The key is `anneal-<run_id>-<step_id>`, which is also the step's tool call id in reconstructed history.
- It is written to the outbox as an `intent` (fsynced) before the call, passed to the tool as the runner's third argument, and marked `done` after it. Read-only tools get no key and no record.
- Writing an intent for a key already in the outbox is an error. A run id can therefore never execute the same operation twice, even across a crash.

**Outbox.**
- Records are one JSON file per key, written atomically (temp file, fsync, rename, directory fsync). No database.
- States are `intent`, `done`, `not_done` and `unknown`. `not_done` is added for a reconcile hook that answers that the operation did not happen.
- `recover(outbox, reconcilers)` reconciles every open intent. A missing hook, a failing hook or an invalid answer is `unknown`. After processing every intent, it raises `NeedsHuman` for the unknown ones. Nothing is ever retried.

**A side-effect call that raises:**
- **With a reconcile hook:**
  - `done` continues the run with the result `{"reconciled": "done"}`;
  - `not_done` deopts;
  - `unknown` raises `NeedsHuman` and stops the run without a deopt.
- **With only an idempotency key:** the outcome is recorded as `unknown`, but the run deopts. The key travels with the fallback: while it runs, `operation_key_for(tool, args)` returns it to the agent's tools for the same call, and they pass it to the external system. This is a deliberate reading of "never deopts into a repeat of the action": under the same key, a repeat is a no-op at the tool, so it is not a repeat of the action. A tool whose keys do not have that property must not be declared `idempotent`.

**M1 live policy.** Only S0 tools execute live by default (`live_severities`). The executor deopts before an S1 or S2 step rather than skipping it, which ADR 0005 already established.

**Evidence.**
- `tests/runtime/test_chaos.py` runs the executor in a child process that kills itself with `os._exit` before or after the tool's effect.
- After restart, `recover` against the effect ledger yields `not_done` or `done`. Re-running the same run id is refused, and a reconcile hook that cannot answer yields `unknown` and `NeedsHuman`. The effect is never executed twice.
- Moving the intent write after the call fails 4 of the 5 chaos tests.

## Consequences

- Interrupted runs are not resumed automatically after a crash in M1. `recover` settles their side effects, and continuing them is an M2 concern.
- Declaring a tool `idempotent` is a safety claim made by the user. Shadow mode (M2.4) is where a wrong claim would first show up.
