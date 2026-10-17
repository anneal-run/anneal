# Scan

Walk one repository without being pointed at a file. The thresholds are in `report/d/prereg.md`. Do not move them after the five repositories in that file have been read.

```
anneal challenge scan --repo <checkout> --out <directory>
```

The checkout is the commit named in the pre-registration. The command writes one directory per Python file. `manifest.json` is the harness manifest the proposer is allowed to see: `workflow_id`, `optimization_run_ids`, `tools`, `workflow_files`, `entrypoint`, `mocked_tools`. Holdout ids are not in it. `evidence.json` beside it has the churn, the case commits, the regex count, the string switches, incidents, request volume, and manual-queue size. A source that is not in the checkout is `null`, not zero.

`evidence.json` beside the manifest has `candidate_rung`. The rungs are `one structured call`, `bounded workflow`, and `agent`. A candidate rung is a hypothesis for the evaluator. `keep deterministic` is a terminal verdict and carries its reason. `bounded workflow` requires a review branch and a measured queue. The word `queue` is not either of those. An amendment that moves a threshold is written in `report/d/prereg.md` before any new repository is opened.

Rank by the score in the evidence. On a repository whose pre-registration names a brittle spot, that file has to be in the top five. On a clean repository every file is `keep deterministic`.
