22 usable issue cases, under the 60-case floor: the power check prints `cannot adjudicate`; the holdout point estimate is +57.1 and suite regressions are 0.

The corpus is 22 cases from open and closed dateparser issues, sealed in [SEAL.json](SEAL.json) before any model call. The pre-registration floor is 60. `cannot adjudicate; n required: 60`. The run still happened. Spend was $0.0040.

Issue cases, all 22: the parser alone is 0/22. Parser first, model on failure, is 14/22. The model ran on 15 cases, where the parser returned None. It was not called on the 7 cases where the parser returned a wrong datetime. One accepted model datetime was the wrong day (issue 271, `1999050`).

Holdout, the last 7: parser 0/7, parser-first 4/7. Correctness +57.1 points, interval 17.5 to 96.7. The correctness-win ceiling is $0.02. Holdout cost per input is $0.000154, under the ceiling. The orchestrator reading on that window is `single_arm`, and it is not an adjudication. The power check refused the corpus.

Suite regressions: 0. The 182 `test_dates_parsing` cases stay 182/182. The model was not called on any of them.

Cost per input on all 22 cases is $0.000182. Failure-path cost per input, the 15 model calls, is $0.000267. Failure-path share of the 22 is 15/22. On the holdout the orchestrator reports failure-path cost $0.000270 and share 57.1% (4 of 7). Failure-path latency on the 15 calls: mean 1106 ms, p95 2496 ms.

Issue numbers: 271, 310, 331, 376, 518, 588, 590, 633, 860, 908, 939, 1012, 1026, 1063, 1098, 1139, 1166, 1171, 1186, 1367. Two cases each for 271 and 590. The verdict file is [verdict.md](verdict.md).
