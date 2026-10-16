# Pre-registration: P0b

Written 2026-10-16, after P0 was scored and before any P0b issue is pulled, any seal is written, or any P0b model call. P0b was designed after seeing P0. The 42-run holdout cannot adjudicate a 5 to 12 point correctness drop: its minimum detectable effect is 30.6 points, and A1, A2, and A3 missed the 2-point margin by point estimates the interval could not resolve. The P0 search also had no fallback candidate, so a cheap path that is sometimes wrong had no way to hand those cases back to the original agent. This file freezes the P0b gates before those questions are remeasured. No P0 file is edited. No number below is revised after the first P0b model call. If one is, that change is visible in git and the run does not count.

## Budget, the same for the new Arm C session

Enforced from provider usage at the model call, not from a total anyone types:

- 4 scored candidates
- $20 of model spend
- 6 wall-clock hours

A typed dollar total is refused and not scored. A submission whose `search_cost_usd` differs from the sum of its metered calls is refused. Hours are the session log. Search cost is amortized over 10,000 runs. That stand-in is not revised after the spend is known.

The step that rescores the baseline, the Arm A cache edit, and A1, A2, and A3 does no new search. Those candidates keep the search cost already on disk. Their new cost is the new holdout only.

## What a win has to clear

These are the P0 gates, unchanged:

- Cost: at least 30% lower per run after amortization over 10,000 runs. For a hybrid, the original agent's calls on fallback cases are inside that per-run cost.
- Correctness: not worse than 2 points on the point estimate. The orchestrator also requires the interval's high end to be no worse than −2 points. With a positive half-width that second check is implied by the point estimate, and it is not relaxed.
- p95 latency not more than 1.20× the baseline p95 on the same cases.
- A gain that remains only on mocked tools is a fail. An optimization-set gain that exceeds the new-holdout gain by more than the new-holdout half-width is a fail (overfit).
- No new side-effect tools. No removed approvals.

The new holdout's minimum detectable effect is printed when the seal is written, from the same formula as P0: `(1.96 + 0.8416212335729143) * sqrt(0.5 / n) * 100` points, null variance 0.5. It is a property of `n`. It is not a second bar and it is not revised.

Prompt caching, a model swap, and a prompt edit are not structural. Arm A's cache edit is the prompt-level control. It cannot be the structural winner.

## The new holdout

Repos, the same two as the dogfood set: `astral-sh/uv` and `pydantic/pydantic`.

Eligible issues are closed issues (not pull requests) opened strictly after every issue of that repo already on disk:

- `astral-sh/uv` after 2026-06-29T23:00:01Z, issue 20055
- `pydantic/pydantic` after 2026-06-29T19:13:54Z, issue 13369

Ground truth is the maintainer labels on the issue now, and `duplicate_of` from the closing reason or a duplicate label plus a findable target. A duplicate closure with no findable target is dropped, the same rule as `select_issues.py`. An issue with no labels and no duplicate mark is dropped.

Take the earliest eligible issues, oldest first, until the combined count is 500 or both repos are exhausted. Below 400, do not seal and do not score. The old 42 holdout cases are not reused, and no issue number already in `examples/github_triage/data/uv.jsonl` or `examples/github_triage/data/pydantic.jsonl` is eligible.

`report/p0b/SEAL.json` is written before any P0b session and before any rescore. It lists `repo` and `number` only. It does not enter a pack.

## What is run, in order

1. This file, committed before the rest.
2. The pull and the seal above. Print `n` and the minimum detectable effect.
3. Rescore, with no new search, on the sealed issues only: the original agent, Arm A's cache edit as it was left on disk, and A1, A2, A3 as they were left on disk. The 42 old holdout rows are not inputs.
4. One new Arm C session. Fresh pack, original `agent.py`, full budget, isolated the same way as P0: the session's only files are the pack, and a session that has read this repository is not this run. The pack does not contain this file, `SEAL.json`, the P0 memo, the P0 results, or the code of A1, A2, or A3. The instruction is the P0 sentence plus one requirement: every structural candidate must include a variant that routes on a confidence signal and falls back to the original agent when confidence is low. The signal comes from the candidate's own output (a structured confidence field, or agreement between the cheap path and a second cheap pass). It does not come from holdout labels. The fallback invokes the original agent, and those calls count in the candidate's cost per run. Each hybrid reports its fallback rate next to its cost.
5. Score every hybrid on the sealed holdout with the orchestrator. A winner has to clear the cost bar with fallback cost included and the correctness margin on this holdout.
6. H1, after the scoring above. Rebuild the dogfood harness from scratch in a fresh session. Log every manual intervention and its duration. Manual share is that duration divided by the session's wall clock. P1 stays gated until this number exists.

## Predicted outcomes, before any P0b run

| Row | Prediction |
| --- | --- |
| Holdout | Both repos yield eligible issues. The seal contains between 400 and 500. `uv` is the majority. The printed minimum detectable effect is between 8.9 and 9.9 points. |
| Rescore, cache edit | Cost reduction stays between 30% and 45%. Correctness point estimate stays inside ±2 points. It remains a prompt result. |
| Rescore, A1 | Cost reduction stays at least 70%. The P0 holdout gap of −11.9 points does not repeat at that size. The new point estimate lands between −8 and −2, so A1 still misses the margin. |
| Rescore, A2 | Cost reduction stays at least 60%. Correctness point estimate is −5 points or worse. |
| Rescore, A3 | Cost reduction stays at least 50%. Correctness point estimate is −2 points or worse. |
| New Arm C | It submits at least one hybrid. The confidence signal is poorly calibrated, so the fallback rate on the cheapest hybrid is under 25%, its cost reduction stays above 70%, and its correctness point estimate stays worse than −2. No hybrid clears both bars. |
| H1 | The rebuild finishes in under one day. Manual share is under 20%. |

## Reading the memo will state in one line

- `structural_win` — a plain candidate or a hybrid clears both bars on the new holdout. H2 and H5 pass on this workflow.
- `stop_drop_is_real` — A1, A2, and A3 miss the correctness margin, and no hybrid clears both bars. Stop.
- `stop_drop_was_noise` — a plain rescored architecture clears both bars. H2 and H5 pass on that candidate.
- `incomplete` — the seal has fewer than 400 issues, or the new session submits no hybrid.

H1 is reported beside that line and does not change it. P1 and P2 stay gated until the reading is `structural_win` or `stop_drop_was_noise`, and until H1 has a measured manual share. H1 failing the 20% bar keeps P1 gated even if the workflow reading passes.
