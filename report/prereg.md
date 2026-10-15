# Pre-registration: Anneal v3

Written 2026-10-16, before any v3 pack is built and before any P0 session. This file is not `report/github_triage-prereg.md`. That file pre-registered the Milestone 1 dogfood and is not evidence for H1–H5 below. These ids are the v3 hypotheses. They are not the Milestone 1 register.

No P0 result is filled in here. If a number below changes after a pack exists, that change is visible in git and the run does not count.

## Budget, the same for every arm

Enforced by the orchestrator from the harness meter, not from a total the arm types in:

- 4 scored candidates
- $20 of model spend
- 6 wall-clock hours

A model call that would pass $20 raises in `CostMeter.record` and is not appended to `meter.jsonl`. The orchestrator charges the sum of those lines. A submission whose `search_cost_usd` differs from that sum is refused and not scored. Hours are the session log; they are not model calls, and a forged hour figure is still a logged claim.

Search cost is amortized over one month of that workflow's volume. For P0 there is no production month. The stand-in, chosen here, is 10,000 runs. Partner workflows use their trailing 30-day run count. The stand-in is not revised after the search cost is known.

## What a win has to clear

- Cost: at least 30% lower per run after that amortization.
- Correctness: the holdout interval excludes zero. The minimum detectable effect is printed from the holdout and is the bar. A 3-point gap on 50 to 100 labels does not pass.
- Non-inferiority: correctness not more than 2 points worse on the point estimate, p95 latency not more than 20% higher, no new side-effect tools, no removed approvals.
- A gain that remains only on mocked tools is a fail. An optimization-set gain that exceeds the holdout gain by more than the holdout interval is a fail.

## P0 and P1, named now

P0 is `examples/github_triage`. The proposer is a new session whose only files are the pack from `anneal challenge pack --p0`. The memo, the baseline script, this file, and the playbook are not inputs. A session that has already read this repository is not a P0 run.

P1 repo: `langchain-ai/open_deep_research` at `1b7d2e80db9faa586165c60e09096dbbfd483a64` (2026-08-10). LangGraph. It is not read for this pre-registration beyond the name and the pinned commit.

Supported stack for this experiment: LangGraph. The OpenAI Agents SDK is not supported. This tree has no integration for it.

## Predicted results

| Id | Prediction, before any v3 run |
| --- | --- |
| H1 | The dogfood harness is rebuilt from the example in under a day with manual time under 20%. The unfamiliar repo uses most of a day and may miss the 20% bar. |
| H2 | One structural cost win, on the dogfood workflow, at least 30% after amortization, if the pack is the whole context. Not 2 of 3. External workflows do not clear the holdout. |
| H3 | Fail. No external team merges or schedules a trial from a two-hour labeling session. |
| H4 | Fail. No written commitment names a price. |
| H5 | Fail. Arm B matches Arm C inside the shared budget. |

## Reading if that is what happens

Arm B matches Arm C, there is a real structural cost win where tools are recorded, and partners will not merge a production rewrite off a two-hour labeling session. The product is the harness and the evidence. The engine is a prompt. That outcome is not inconclusive.
