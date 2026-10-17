# Experiment D

Written 2026-10-17, before any of these repositories is cloned or read. This is separate from the partner path. It runs for one week. Expected spend for the whole experiment is under $10. P2 stays gated.

## Scanner

`skills/anneal/scan` walks a repository without being pointed at a file. It looks for non-AI code that is losing to messy input:

- high-churn files whose commit messages are about cases
- regex parsers over free text
- large string switches
- manual-review branches and the queues behind them
- templated output with growing conditionals

Each candidate gets evidence: churn, incidents, request volume where observability exists, and manual-queue size. A missing source is recorded as missing. It is not recorded as zero.

The ladder is one of: `keep deterministic` (with the reason), `one structured call`, `bounded workflow`, `agent`.

One file per candidate, in the harness manifest format: `workflow_id`, `optimization_run_ids`, `tools`, `workflow_files`, `entrypoint`, `mocked_tools`. The holdout ids are not in that file. Evidence and the ladder sit beside it.

The scoring rule is fixed here.

A candidate is a Python file that is not a test, not under a vendored or generated tree, and not empty. Its score is the sum of:

- churn: the number of commits in the last 200 that touch the file
- case commits: those whose subject matches `case`, `edge`, `special`, `workaround`, `fallback`, or `parse`, counted again
- regex operations: `re.compile`, `re.match`, `re.search`, `re.sub`, and `re.findall`
- string switches: `==` or `!=` against a string literal inside `if` or `elif`, and `case` arms
- manual-review words: `manual`, `review`, `queue`, `human`
- template conditionals: an f-string or `.format` in a file that also has at least five `if` statements, counted as 1

Ladder, applied in this order:

- `agent` only when the file imports `langgraph`, `langchain`, or `autogen`
- `bounded workflow` only when the file contains both a manual-review word and the word `queue`
- `one structured call` only when the file has at least 3 regex operations, its path contains `parse` or `extract`, and at least one case commit touched it
- otherwise `keep deterministic`, and the reason names the strongest signal that stayed under that line

## Ranking check

The known spot has to be in the top five by score. On a clean repository every candidate is `keep deterministic`.

Pinned before the trees are opened:

| repo | commit | role | known spot |
|---|---|---|---|
| dateutil/dateutil | `2642afacc33fb839c404b75b230fff58b79793f2` | brittle | `dateutil/parser/_parser.py` |
| scrapinghub/dateparser | `07b40b2f01773d830321538ac9d2d6219edbe10e` | brittle | `dateparser/parser.py` |
| john-kurkowski/tldextract | `bf7922f0e472e259ecc073e2395a41b26d34dc5d` | brittle | `tldextract/tldextract.py` |
| more-itertools/more-itertools | `4aeb4338ae1407d8da9723e86da99efeb446f719` | clean | none |
| python-attrs/attrs | `ee66e7274852438cc23d4240a1a9cd632fda8b52` | clean | none |

## The one path after that check

The top candidate on one brittle repository goes through the existing path: capture by running on recorded inputs, harness, engine proposing rungs 2 to 4 with a validity-check fallback, then the evaluator in correctness-win mode, then a pull request that leaves the old code on the path.

Correctness-win mode, chosen before any score exists:

- the holdout correctness interval is entirely above zero (`correctness_low > 0`)
- the cost ceiling is $0.02 per case, after the search cost is amortized, instead of a 30% cost cut. The baseline is local code, so a model call cannot be a cost cut
- latency is not a gate. One model call cannot stay within 1.20× of local code, and that is stated here before the run
- mock-only and overfit still disqualify a candidate. No new side-effect tools. No removed approvals

The 30% cut, the 2-point correctness margin, and the 1.20× latency rule stay the default for every other workflow. The engine cap stays 4 candidates, $10, and 6 hours.

## What is not a result

A ranking computed from a tree that was opened before this file was committed. A cost ceiling chosen after a score. A threshold moved after the five repositories are read, unless this file says the move was made after a named result.

## Amendment, 2026-10-17, after more-itertools

The first ranking is `report/d/ranking.md`. more-itertools was marked bounded workflow because `more.py` and `recipes.py` contain the word `queue`. Those are queue recipes, not a manual-review branch. The fix below was made after that result. Passing more-itertools again is not evidence that the fix works. The two repositories at the bottom of this section are the test, and they had not been cloned or read when this section was written.

Manual review, replacing the bounded-workflow bullet above:

- Routing semantics: an `if` or `elif` body calls, returns, or assigns to a name containing `manual`, `review`, `escalate`, or `human`. `import queue`, `queue.Queue`, a comment, and the bare word `queue` are not a route.
- Evidence gate: `bounded workflow` only when that route is present and at least one of incidents, request volume, or manual-queue size is a real measurement. Manual-queue size is an integer bound to a name containing `manual_queue`, `review_queue`, or `human_queue`. A missing measurement stays missing. It is not zero, and it is not the number of times the word `queue` appears.
- The word `queue` is no longer a manual-review word in the score. The score words are `manual`, `review`, and `human`.

A review branch with no measurement stays `keep deterministic`. The reason says the queue was not measured.

The one path is `dateparser/date.py` on scrapinghub/dateparser at the commit above. It is one structured call. The fallback is the original parser. Labels are the `test_dates_parsing` cases in `tests/test_date_parser.py`: each string and the datetime that test expects, with `RELATIVE_BASE` of 2012-11-13 and `NORMALIZE` false. The holdout is the last 30% of those cases in file order. It is sealed before any model call, and the engine does not see those cases. A string is strange when it contains a character outside ASCII or no four-digit year. That split is reported beside the verdict. It is not a gate. The cost ceiling stays $0.02 per case.

Pinned before these two trees are opened:

| repo | commit | role | known spot |
|---|---|---|---|
| grantjenks/python-sortedcontainers | `3ac358631f58c1347f1d6d2d92784117db0f38ed` | clean, the test | none |
| pallets/markupsafe | `4e111271b1494995708a9e878a10829b5e10c7ba` | clean, the test | none |
