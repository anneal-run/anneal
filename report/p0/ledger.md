# P0 session record

The holdout was opened once for each submitted candidate. `report/p0/verdict.md` is the orchestrator output and was not edited.

Reading: `harness_is_the_product`. Structural winner among the candidates that cleared the bar: `B/caching`. Arm C was scored and is not worth it. H3 and H4 stay fails: no merge and no paid commitment.

## Holdout

Each submission's agent was run on the 42 sealed cases with `claude-haiku-5-5`. A tool call whose arguments were already in that run's trace returned the recorded result. Any other call went to GitHub. No observation is marked mocked. Cost uses the price table in `pricing.yaml`.

| Arm | Candidate | Holdout correct | Holdout cost | Live tool calls | Replayed tool calls |
| --- | --- | ---: | ---: | ---: | ---: |
| baseline | original workflow | 36/42 | $0.1419 | — | — |
| A | `A-cache-agent-loop` | 38/42 | $0.0882 | 122 | 100 |
| B | `caching` | 37/42 | $0.0841 | 117 | 102 |
| C | `C-cache-agentloop` | 34/42 | $0.1345 | 110 | 104 |

Holdout model spend was $0.0882 for A, $0.0841 for B, and $0.1345 for C. There were no run errors.

The orchestrator, amortizing search cost over 10,000 runs, reports a holdout cost reduction of 37.8% for A, 40.2% for B, and 5.2% for C. A and B are worth it. C is disqualified as overfit: the optimization-set saving in the submission is larger than the holdout saving of the code left in the pack. That code is the original agent. The caching change described in the session log is not in `examples/github_triage/agent.py`.

## Sessions

Counted run: three sandboxed sessions, one per pack, started together at 2026-10-16T06:11:53Z and exited at 2026-10-16T06:45:45Z (34 minutes). Each session's working directory was its pack. The repository, the sealed harness, the other packs, and this conversation were blocked.

An earlier launch the same morning was stopped after a few minutes because one session searched outside its pack. That launch is not this run.

| Arm | Meter lines | Meter USD | Submission | Claimed hours |
| --- | ---: | ---: | --- | ---: |
| A | 0 | 0.000000 | `A-cache-agent-loop` | 1.0 |
| B | 551 | 0.189460 | `caching` | 1.0 |
| C | 453 | 0.245058 | none | — |

Arm A and Arm B each edited the agent to turn on prompt caching and wrote one `structural` candidate. Both say the search made no new workflow calls: Arm A's meter is empty, and Arm B's meter is the recomputed optimization-set bill. Each submission's `search_cost_usd` equals the sum of its `calls`, and each `opt` list is exactly the 98 optimization run ids. Neither list contains a holdout id.

Arm C's first session recorded 453 calls ($0.245058) and stopped with a credit-balance error. It wrote no submission. A replacement session, in a clean pack, ran from 2026-10-16T13:38:21Z to 2026-10-16T13:55:00Z with $19.75 remaining of the $20 cap. It submitted `C-cache-agentloop` after 26 metered calls ($0.008229).

## Baseline

`baseline.jsonl` is the original workflow on the 140 repaired runs, joined to `examples/github_triage/data/runs/uv.jsonl` by issue number. Cost is the sum of recorded model-call costs. Latency is `ended_at - started_at`. The split is the sealed chronological split: 98 optimization runs, 42 holdout runs.

| Split | Runs | Correct | Cost |
| --- | ---: | ---: | ---: |
| optimization | 98 | 71 | $0.3317 |
| holdout | 42 | 36 | $0.1419 |
