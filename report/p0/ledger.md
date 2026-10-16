# P0 session record

The holdout was opened once, after the API account had credit. `report/p0/verdict.md` is the orchestrator output and was not edited.

Reading: `incomplete`. Arm C submitted nothing, so the three-arm comparison was not run. Both scored candidates are cost wins on the holdout and are worth it. Neither is a correctness win: the intervals include zero, and the minimum detectable effect is 30.6 points.

Against `report/prereg.md`: H2 expected one structural cost win and H5 expected Arm B to match Arm C. Arm C has no candidate, so that reading (`harness_is_the_product`) was not reached. H3 and H4 stay fails: no merge and no paid commitment.

## Holdout

Each submission's agent was run on the 42 sealed cases with `claude-haiku-5-5`. A tool call whose arguments were already in that run's trace returned the recorded result. Any other call went to GitHub. No observation is marked mocked. Cost uses the price table in `pricing.yaml`.

| Arm | Candidate | Holdout correct | Holdout cost | Live tool calls | Replayed tool calls |
| --- | --- | ---: | ---: | ---: | ---: |
| baseline | original workflow | 36/42 | $0.1419 | — | — |
| A | `A-cache-agent-loop` | 38/42 | $0.0882 | 122 | 100 |
| B | `caching` | 37/42 | $0.0841 | 117 | 102 |

Holdout model spend was $0.0882 for A and $0.0841 for B. There were no run errors.

The orchestrator, amortizing search cost over 10,000 runs, reports a holdout cost reduction of 37.8% for A and 40.2% for B. Both are worth it. B is the structural winner among the candidates that were scored. The reading stays `incomplete` until C has a scored candidate.

## Sessions

Counted run: three sandboxed sessions, one per pack, started together at 2026-10-16T06:11:53Z and exited at 2026-10-16T06:45:45Z (34 minutes). Each session's working directory was its pack. The repository, the sealed harness, the other packs, and this conversation were blocked.

An earlier launch the same morning was stopped after a few minutes because one session searched outside its pack. That launch is not this run.

| Arm | Meter lines | Meter USD | Submission | Claimed hours |
| --- | ---: | ---: | --- | ---: |
| A | 0 | 0.000000 | `A-cache-agent-loop` | 1.0 |
| B | 551 | 0.189460 | `caching` | 1.0 |
| C | 453 | 0.245058 | none | — |

Arm A and Arm B each edited the agent to turn on prompt caching and wrote one `structural` candidate. Both say the search made no new workflow calls: Arm A's meter is empty, and Arm B's meter is the recomputed optimization-set bill. Each submission's `search_cost_usd` equals the sum of its `calls`, and each `opt` list is exactly the 98 optimization run ids. Neither list contains a holdout id.

Arm C recorded 453 calls ($0.245058) while trying variants and then stopped. Its log is the credit-balance error. It wrote no submission. Those calls are search spend, not a holdout score.

## Baseline

`baseline.jsonl` is the original workflow on the 140 repaired runs, joined to `examples/github_triage/data/runs/uv.jsonl` by issue number. Cost is the sum of recorded model-call costs. Latency is `ended_at - started_at`. The split is the sealed chronological split: 98 optimization runs, 42 holdout runs.

| Split | Runs | Correct | Cost |
| --- | ---: | ---: | ---: |
| optimization | 98 | 71 | $0.3317 |
| holdout | 42 | 36 | $0.1419 |
