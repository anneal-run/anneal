# One SQL call, behind a flag

`direct_sql` answers with a single SQL statement. It runs only when `ANNEAL_TABLETALK` is set. With the flag unset, `ask` is the original agent. When the one-shot query fails to execute, the original agent answers that question and that cost is counted. Nothing in this change deploys. There is no shadow runner.

## What we measured

Both systems ran on 400 Spider development questions. The list was sealed before either system ran: seed 8, and none of the 60 questions from an earlier check. The search that proposed `direct_sql` cost $0.6956 and is amortized over 1,000 runs.

| | correct | cost |
|---|---|---|
| original agent | 180/400 | $2.0614 |
| direct_sql | 280/400 | $0.4212 |

It fell back to the original agent on 2 of 400 questions, 0.5%.

The orchestrator, told that this pre-registration named one arm:

```
margin: 10.0 points; n required: 393
n reached: 400
verdict: single_arm
```

`direct_sql` is worth it on that rule. It is compatible with the tools, correct on the holdout, and 66.1% cheaper after the search cost is amortized. Correctness is +25.0 points, interval 20.5 to 29.5.

## Where it loses

Spider difficulty is the official count of components in the gold SQL. A loss is a question `direct_sql` got wrong. The number in parentheses is how many of those the original agent got right.

| difficulty | questions | direct wrong | original right, direct wrong |
|---|---|---|---|
| easy | 85 | 11 | 1 |
| medium | 172 | 51 | 4 |
| hard | 74 | 24 | 0 |
| extra | 69 | 34 | 0 |

Wrong answers get more common as the question gets harder.

## Tests and rollback

The tests are the 42 optimization fixtures. Unset `ANNEAL_TABLETALK` and the original agent is the whole path. There is no migration.
