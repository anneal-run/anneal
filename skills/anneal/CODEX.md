# Anneal (Codex)

This is the same procedure as `SKILL.md`, for a Codex session in the partner's repository. Read `SKILL.md` and follow it in order. The differences are only how the session is started.

1. Start Codex in a fresh directory that contains only the pack from `anneal challenge pack`. Do not open the repository root first.
2. The task prompt is the pack's `PROMPT.md` plus `BUDGET.json`. Do not add an architecture menu, and do not paste a known cheaper implementation.
3. Write submissions under `submissions/` in that directory. Each structural candidate sets `fallback_rate` to the share of cases that invoked the original implementation, and the candidate's cost includes those calls.
4. Stop when the budget in `BUDGET.json` is spent, or when three structurally different candidates are submitted, whichever comes first.
5. Return to the repository root for `anneal challenge orchestrate --require-fallback` and, only if that command names a structural winner, `anneal challenge pr`. A refusal that says `cannot adjudicate; n required: N` ends the task. Do not deploy.
