# Experiment D2

Written 2026-10-17, before any GitHub issue on dateparser is read. This is the last experiment. Expected spend is under $1. After the memo, no new experiment starts. The next work is a partner workflow, and it starts when one exists.

## Target

scrapinghub/dateparser at `07b40b2f01773d830321538ac9d2d6219edbe10e`, the same commit as Experiment D. The file is `dateparser/date.py`. The candidate rung from the scanner was `one structured call`. This run does not use that rung. It uses code first, model on failure.

## Cases

Usable cases come from the repository's open and closed GitHub issues. A case is usable only when all of these hold:

- the issue states an input string and an expected calendar date in the issue text
- the expected date is explicit. It is not inferred, and a relative word such as tomorrow is not usable unless the issue states the reference clock
- the parser at this commit, with that clock when one is stated and otherwise with no relative base, returns None, raises, or returns a datetime that is not the expected date
- the input is not one of the 182 `test_dates_parsing` strings

Each case records the issue number. Several examples in one issue are several cases with that number. The same issue number and input string are kept once. Order for the split is the issue's creation time, then the issue number, then the input.

The holdout is the chronological tail: the first `floor(0.7 × n)` cases are the optimization set and the rest are the holdout. The holdout is sealed before any model call.

The 182 `test_dates_parsing` cases, with `RELATIVE_BASE` 2012-11-13 and `NORMALIZE` false, are the regression suite. The parser is already right on all 182. The candidate has to stay right on all 182. That count is a gate.

## Candidates

The control is the parser alone.

The other candidate is `code_first`. The parser runs on every input. A model is called only when the parser returns None, raises, or returns a value that is not a datetime. A datetime that is merely the wrong day is not a validity failure, and the model is not called. The model's answer is kept only when it is a datetime. Otherwise the parser's result stands. The repair field is `code_first`.

## Verdict

Correctness-win mode, cost ceiling $0.02 per input. The interval has to be above zero. Suite regressions have to be zero. The orchestrator checks that count.

The power check uses the existing minimum detectable effect at 60 cases. Fewer than 60 usable cases print `cannot adjudicate`. The run still happens. The point estimate and the regression count still go in the memo.

Report issue-case correctness for both candidates, suite regressions, cost per input overall, cost per input on the failure path, the failure-path share, and failure-path latency.

## What is not a result

An issue read before this file was committed. An expected date that was not written in the issue. A threshold moved after the issues are read.
