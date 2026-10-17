# Status

Experiments are finished. The next work is a partner workflow, and it starts when one exists. P2 stays gated on that.

| Hypothesis | Evidence | Source |
| --- | --- | --- |
| H1, harness from a real repo, manual share under 20% on the dogfood repo and one unfamiliar repo | Dogfood passes: github_triage, 0.46s, manual share 0. The unfamiliar repo does not: tabletalk harness 19s, manual share 58% (a `python` symlink). open_deep_research produced no harness. | [harness-log.md](harness-log.md), [product-dry-run.md](product-dry-run.md), [p1/harness-log.md](p1/harness-log.md), [p1/results.md](p1/results.md) |
| H2, a structural challenger beats the baseline and the prompt control on 2 of 3 workflows | Not shown. P0's corrected reading is `stop_prompt_only`, no structural winner. P1b is one structural result, `direct_sql`, and it is one workflow. | local [p0/memo.md](p0/memo.md), [p1b/memo.md](p1b/memo.md) |
| H3, an external team merges or schedules a trial, 1 of 2 workflows | Not shown. Tabletalk pull request 1 is open, not merged, no comments, no maintainer response. | [p1b/memo.md](p1b/memo.md) |
| H4, a team commits in writing with a named price for a second workflow | Not shown. No paid commitment. | [p1b/memo.md](p1b/memo.md) |
| H5, arm C beats arm B on 2 of 3 | Not shown. P0's A tied B. P1b ran only C. | local [p0/memo.md](p0/memo.md), [p1b/verdict.md](p1b/verdict.md) |
| P0, github_triage, three arms | Corrected reading `stop_prompt_only`. Baseline holdout 36/42 at $0.1419. A 38/42 at $0.0882. B 37/42 at $0.0841. The committed verdict still says `harness_is_the_product`. The correction is the local memo, and that file is not committed. | local [p0/memo.md](p0/memo.md), [p0/verdict.md](p0/verdict.md) |
| P0b | `incomplete`. 184 eligible issues, floor 400. The memo is local and not committed. The floor is in the pre-registration. | local [p0b/memo.md](p0b/memo.md), [p0b/prereg.md](p0b/prereg.md) |
| P0c | Stopped at 6 of 1,200. No row is a result. No gate reads it. | [p0c/stopped.md](p0c/stopped.md) |
| P1, tabletalk, n=18 | `cannot adjudicate`. Margin 10, n required 393. `direct_sql` holdout 13/18 at $0.0204 against the control 10/18 at $0.0908. | [p1/verdict.md](p1/verdict.md), [p1/results.md](p1/results.md) |
| P1b, tabletalk, 400 fresh questions, one arm | `single_arm`. Control 180/400 at $2.0614. `direct_sql` 280/400 at $0.4212. Correctness +25.0 (20.5 to 29.5). Cost reduction 66.1%. Fallback 0.5%. | [p1b/memo.md](p1b/memo.md), [p1b/verdict.md](p1b/verdict.md) |
| D, scanner ranking and one dateparser path | Ranking pass. The dateparser candidate rung was declined: holdout 50/55 against the parser 55/55, correctness −9.1 (−16.8 to −1.4), reading `stop_no_win`. The $0.02 ceiling held. | [d/memo.md](d/memo.md), [d/ranking.md](d/ranking.md), [d/verdict.md](d/verdict.md) |
| D2, dateparser issues, code first | 22 usable cases, under 60. Power check: `cannot adjudicate; n required: 60`. Parser 0/22, parser-first 14/22. Holdout point estimate +57.1. Suite regressions 0. | [d2/memo.md](d2/memo.md), [d2/verdict.md](d2/verdict.md) |

Prompt-only wins are not evidence for this product. P0's cache edits are that kind of result.
