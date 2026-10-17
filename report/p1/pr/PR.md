# tabletalk: direct_sql

`direct_sql` runs only when `ANNEAL_TABLETALK` is set. With the flag unset, the original implementation runs. It also runs when the winner declines a case, and that cost is charged.

## Tests

The harness fixtures are `report/p1/fixtures.jsonl`. `test_fixtures.py` checks that file is present.

## Verdict

report/p1/verdict.md

## Rollback

See `rollback.md`. Unset `ANNEAL_TABLETALK`. There is no migration, and nothing in this change deploys.

## Shadow

`shadow_runner.py` runs the original implementation and the winner on the same case, returns the original result, and appends the pair. `anneal challenge shadow` prints the verdict and the n reached. It stops early only when that difference is clearly outside the margin in `anneal.toml`.
