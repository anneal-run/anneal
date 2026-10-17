# P1b

Designed after P1. The pre-registration is the P1b section of [../p1/prereg.md](../p1/prereg.md). The 400 questions were sealed in [SEAL.json](SEAL.json) before either system ran. Spend on the two runs was $2.48.

## Holdout

| | correct | cost |
|---|---|---|
| control, the original agent | 180/400 | $2.0614 |
| direct_sql | 280/400 | $0.4212 |

Fallback rate: 2 of 400, 0.5%. Both fallbacks were on hard or extra questions.

Search cost from the earlier engine session, $0.6956, is amortized over 1,000 runs in the submission.

## Where direct_sql loses

Spider difficulty, from the official component count on the gold SQL. A loss is a question `direct_sql` got wrong.

| difficulty | questions | direct wrong | control right and direct wrong |
|---|---|---|---|
| easy | 85 | 11 | 1 |
| medium | 172 | 51 | 4 |
| hard | 74 | 24 | 0 |
| extra | 69 | 34 | 0 |

The wrong answers get more common as the question gets harder: 11 of 85 easy, 51 of 172 medium, 24 of 74 hard, 34 of 69 extra. On hard and extra it did not miss a question the original agent had right.

## Verdict

```
margin: 10.0 points; n required: 393
n reached: 400
verdict: incomplete
```

The full report is [verdict.md](verdict.md). `direct_sql` is worth it on this holdout: compatible, correct, 66.1% cheaper, correctness +25.0 points, interval 20.5 to 29.5. The reading is `incomplete` because arms A and B were not run. That is the pre-registered shape of this run.

## Pull request

The branch `anneal-direct-sql` is committed locally at `15b85b9` on the tabletalk checkout. `ANNEAL_TABLETALK` is off by default, the original agent stays on the path, and the optimization fixtures are the tests. The shadow runner is not in that change.

GitHub rejected the push, so the pull request is not open and there is no maintainer response. The stored GitHub credential was cleared by that rejection.
