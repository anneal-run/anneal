# Pre-registration: P0c

Written 2026-10-16, after P0b stopped and before any P0c issue is pulled, any seal is written, or any P0c model call. P0b's pull of `astral-sh/uv` and `pydantic/pydantic` found 184 eligible closed issues, under that file's floor of 400, so nothing was sealed. P0c changes only the sourcing, the floor, and the detectability gate. Steps 3 to 6 of `report/p0b/prereg.md` are otherwise unchanged: rescore with no new search, one new Arm C session whose structural candidates include a confidence fallback, score those hybrids on this holdout, then the H1 rebuild. No P0 file is edited. No number below is revised after the first P0c model call. If one is, that change is visible in git and the run does not count.

P1 and P2 stay gated on this result and on the H1 number. Partner outreach is not this run. It still has no status.

## Budget, the same for the new Arm C session

Enforced from provider usage at the model call, not from a total anyone types:

- 4 scored candidates
- $20 of model spend
- 6 wall-clock hours

A typed dollar total is refused and not scored. A submission whose `search_cost_usd` differs from the sum of its metered calls is refused. Hours are the session log. Search cost is amortized over 10,000 runs. That stand-in is not revised after the spend is known.

The rescore of the baseline, the Arm A cache edit, and A1, A2, and A3 does no new search. Those candidates keep the search cost already on disk. Their new cost is this holdout only.

## What a win has to clear

These are the P0 gates, unchanged:

- Cost: at least 30% lower per run after amortization over 10,000 runs. For a hybrid, the original agent's calls on fallback cases are inside that per-run cost.
- Correctness: not worse than 2 points on the point estimate. The orchestrator also requires the interval's high end to be no worse than −2 points. With a positive half-width that second check is implied by the point estimate, and it is not relaxed.
- p95 latency not more than 1.20× the baseline p95 on the same cases.
- A gain that remains only on mocked tools is a fail. An optimization-set gain that exceeds the new-holdout gain by more than the new-holdout half-width is a fail (overfit).
- No new side-effect tools. No removed approvals.

Prompt caching, a model swap, and a prompt edit are not structural. Arm A's cache edit is the prompt-level control. It cannot be the structural winner.

## Sourcing, floor, and the detectability gate

Eight repos, named now. At least six of them must contribute one or more eligible issues. Fewer than six contributors, and the pull stops unsealed.

- `astral-sh/uv`, after 2026-06-29T23:00:01Z, issue 20055
- `pydantic/pydantic`, after 2026-06-29T19:13:54Z, issue 13369
- `python/mypy`, after 2026-06-24T14:10:40Z, issue 21644
- `godotengine/godot`, after 2026-06-30T23:05:49Z, issue 120797
- `astral-sh/ruff`, after 2026-06-30T00:00:00Z
- `rust-lang/rust`, after 2026-06-30T00:00:00Z
- `golang/go`, after 2026-06-30T00:00:00Z
- `kubernetes/kubernetes`, after 2026-06-30T00:00:00Z

The first four cutoffs are the latest issue of that repo already on disk. The last four are not in the store. Their window opens at 2026-06-30T00:00:00Z, the same season as the others. Nothing opened on or before a cutoff is eligible. No issue number already in `examples/github_triage/data/` is eligible. The old 42 holdout cases are not reused.

Eligible issues are closed issues (not pull requests). Ground truth is the maintainer labels on the issue now, and `duplicate_of` from a findable "Duplicate of #N" comment. A duplicate closure with no findable target is dropped. An issue with no labels and no duplicate mark is dropped. Unauthenticated GraphQL is refused, so a close-as-duplicate that has no such comment is dropped.

Take the earliest eligible issues, oldest first. The floor is 1,200. Below 1,200, do not seal and do not score. At or above 1,200, seal the earliest 1,200.

The minimum detectable effect uses the P0 formula, `(1.96 + 0.8416212335729143) * sqrt(0.5 / n) * 100` points, null variance 0.5. It is a gate. At 1,200 issues it is 5.7 points. If the sealed `n` would print above 6.0 points, do not seal and do not score. The 2-point correctness margin is not this gate and is not moved.

`report/p0c/SEAL.json` is written before any P0c session and before any rescore. It lists `repo` and `number` only. It does not enter a pack.

## What is run, in order

1. This file, committed before the rest.
2. The pull and the seal above. Print `n` and the minimum detectable effect.
3. Rescore, with no new search, on the sealed issues only: the original agent, Arm A's cache edit as it was left on disk, and A1, A2, A3 as they were left on disk. The 42 old holdout rows are not inputs.
4. One new Arm C session. Fresh pack, original `agent.py`, full budget, isolated the same way as P0: the session's only files are the pack, and a session that has read this repository is not this run. The pack does not contain this file, `SEAL.json`, the P0 memo, the P0 results, or the code of A1, A2, or A3. The instruction is the P0 sentence plus one requirement: every structural candidate must include a variant that routes on a confidence signal and falls back to the original agent when confidence is low. The signal comes from the candidate's own output (a structured confidence field, or agreement between the cheap path and a second cheap pass). It does not come from holdout labels. The fallback invokes the original agent, and those calls count in the candidate's cost per run. Each hybrid reports its fallback rate next to its cost.
5. Score every hybrid on the sealed holdout with the orchestrator. A winner has to clear the cost bar with fallback cost included and the correctness margin on this holdout.
6. H1, after the scoring above. Rebuild the dogfood harness from scratch in a fresh session. Log every manual intervention and its duration. Manual share is that duration divided by the session's wall clock. P1 stays gated until this number exists.

## Predicted outcomes, before any P0c run

| Row | Prediction |
| --- | --- |
| Holdout | At least six of the eight repos contribute. The pool has at least 1,200 eligible issues. The seal is the earliest 1,200. `golang/go`, `rust-lang/rust`, and `kubernetes/kubernetes` are the majority. The printed minimum detectable effect is 5.7 points, which clears the 6-point gate. |
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
- `incomplete` — fewer than six repos contribute, the pool is under 1,200, the sealed minimum detectable effect is above 6.0 points, or the new session submits no hybrid.

H1 is reported beside that line and does not change it. P1 and P2 stay gated until the reading is `structural_win` or `stop_drop_was_noise`, and until H1 has a measured manual share. H1 failing the 20% bar keeps P1 gated even if the workflow reading passes. Partner outreach stays without a status.
