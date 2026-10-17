# P1 amendment

Written 2026-10-16, after the open_deep_research attempt and before this repository is cloned or read. That attempt is `report/p1/memo.md`. It stopped because the pinned research agent ships no trace export and costs about a dollar a run to trace. P1 measures harness time and structural search. Those cost the same on a cheap workflow, so the rerun is a cheap one.

## Engine cap

4 candidates, $10, 6 hours. The previous cap was $20. Every engine session so far spent under $0.35. The cap is in `anneal.toml` and in the pack's `BUDGET.json`.

## Repo, named before it is opened

`SkanderGhariani/tabletalk` at `b84d063a3c28afcc84ed09d06dc1a9959b2deb39`.

It qualifies from the public topics and description, without the tree being opened. The topics include `langgraph` and `sqlite`. The description is a local agent that asks a SQLite database questions, with tools and evals. The tool calls are SQL against a local database, which is the cheap case. This checkout has not been read.

## What this run does

Capture by running, then the harness, then arm C only.

The margin for `tabletalk` is 10 points in `anneal.toml`. At a holdout of 18 the expected verdict is `cannot adjudicate`. That output is correct.

Arm C is an isolated pack with no architecture menu, a required confidence fallback, and the $10 cap. The orchestrator scores on the optimization set and opens the holdout once for the top three. Prompt-level candidates are reported separately.

Capture and scoring are expected to stay under $5. The engine session stays inside its $10 cap.
