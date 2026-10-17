# Anneal (Codex)

This is the same procedure as `SKILL.md`, for a Codex session in the partner's repository. Read `SKILL.md` and follow it in order. The differences are only how the session is started.

1. Start Codex in a fresh directory that contains only the pack from `anneal challenge pack`. Do not open the repository root first.
2. The task prompt is the pack's `PROMPT.md` plus `BUDGET.json`. Do not add an architecture menu, and do not paste a known cheaper implementation.
3. Write submissions under `submissions/` in that directory. Each structural candidate sets `fallback_rate` to the share of cases that invoked the original implementation, and the candidate's cost includes those calls. `fallback_triggers` names a validity check of the result. An exception by itself is refused.
4. Stop when the budget in `BUDGET.json` is spent, or when three structurally different candidates are submitted, whichever comes first.
5. If the repository has no LangSmith export, capture by running before the pack exists. With `LANGSMITH_API_KEY` set, tracing goes on through the environment and the export is imported. Without that key, record the runs locally in the LangSmith record shape and import that file. That time and its model cost are not harness time.
6. Return to the repository root for `anneal challenge orchestrate --require-fallback` and `anneal challenge pr`. A verdict of `cannot adjudicate` still gets the pull request, with the shadow runner attached and the flag off. Do not deploy.
