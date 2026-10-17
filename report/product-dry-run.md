# Product dry run

`examples/github_triage`, 2026-10-16. The traces are the dogfood import (140 runs). That store is gitignored, so a clean clone runs the same commands after `anneal import langsmith`. No proposer session was started, and nothing was deployed.

| step | result | time |
|---|---|---|
| `anneal challenge harness` | 98 optimization runs, 42 holdout runs sealed in `SEAL.json`. Fixtures: 98 lines. Mocked tools: none (all four tools are read-only). | 0.19s |
| `anneal challenge pack --arm C --p0` | Pack has the fallback instruction and no architecture menu. `SEAL.json` is not in the pack. | 0.14s |
| `anneal challenge orchestrate --require-fallback` | `minimum detectable effect: 30.6 points; margin: 2.0 points` then `cannot adjudicate; n required: 9812` | 0.13s |

Total 0.46s. The pull request step did not run, because the 42-case holdout cannot support the 2-point margin. The harness log is [harness-log.md](harness-log.md).
