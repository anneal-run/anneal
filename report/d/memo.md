# Experiment D

Experiment D reads as a pass on ranking quality and a correct refusal on dateparser: the evaluator declined the scanner's own rung with evidence.

The pre-registration is [prereg.md](prereg.md). The first ranking, before the fix, is [ranking.md](ranking.md). The one-path verdict is [verdict.md](verdict.md).

## What the scanner got right

On dateparser, `dateparser/parser.py` is rank 2 of 253 and the candidate rung is one structured call. The top file is `dateparser/date.py`, also one structured call. That is the file the one path ran. A candidate rung is a hypothesis for the evaluator. `keep deterministic` is a terminal verdict and carries its reason.

`tldextract/tldextract.py` is rank 1 of 9. `src/dateutil/parser/_parser.py` is rank 1 of 22. The pre-registered dateutil path omitted `src/`, so that exact string is not in the tree. Both files stay keep deterministic. dateutil's parser has 34 string switches and one regex operation, and the rule asks for three regex operations before it will replace a parser. tldextract has the churn and no regex operation.

## The false positive and the fix

The first run marked more-itertools as bounded workflow. `more.py` and `recipes.py` contain the word `queue`. They are queue recipes, not a review route.

The amendment was written after that result. A bounded workflow now needs both a review branch and a measured queue. An `if` or `elif` body has to call, return, or assign a manual, review, escalate, or human route, and an integer has to be bound to a `manual_queue`, `review_queue`, or `human_queue` name. The word `queue` is neither a route nor a size. A review branch with no measurement stays keep deterministic.

Rerunning more-itertools after that change makes all four files keep deterministic. That rerun was patched against the repository that produced the false positive, so it is not the test. Attrs was already all keep deterministic and stayed that way.

## The two libraries named after the fix

`grantjenks/python-sortedcontainers` at `3ac358631f58c1347f1d6d2d92784117db0f38ed` and `pallets/markupsafe` at `4e111271b1494995708a9e878a10829b5e10c7ba` were named in the amendment before either tree was cloned. Every file in both is keep deterministic. Sortedcontainers has 5 files. Markupsafe has 5.

## The two it declined to replace

dateutil's parser and tldextract. Both rank first in their repository, and both stay keep deterministic, for the reasons above. The scanner did not send either one down the model path.

## The one path

`dateparser/date.py` at the pinned dateparser commit. One model call, `claude-haiku-4-5`, with the original parser as the fallback. The fallback fires on an empty date, a reply that is not a timestamp, or low confidence. Labels are the 182 `test_dates_parsing` cases, with `RELATIVE_BASE` 2012-11-13 and `NORMALIZE` false. The holdout is the last 55, sealed in [SEAL.json](SEAL.json) before any model call. The call does not see those cases while it is being written. A string is strange when it contains a character outside ASCII or no four-digit year. That split is not a gate.

The original parser is right on all 182. On the holdout:

| | correct | mean latency | p95 latency | cost |
|---|---|---|---|---|
| original parser | 55/55 | 11.5 ms | 38.2 ms | $0 |
| one call, with fallback | 50/55 | 1062 ms | 1629 ms | $0.0184 |

Mean cost is $0.0003 per case. The highest case is $0.0006. The $0.02 ceiling holds. Fallback is 8 of 55, 14.5%, all schema violations. Those eight match the parser, because the fallback is the parser.

The model does not win on the strange strings. On the 38 strange holdout cases the parser is 38/38 and the call is 35/38. The three it misses, all answered rather than declined, are `শুক্রবার`, `15 tammi klo 14:30`, and `12-14 июня 2021`. It also misses two plain ones, `5.7.2018 5.45 ip.` and `5 .7 .2018 5.45 ip.`.

Correctness on the holdout is −9.1 points, interval −16.8 to −1.4. The interval is not above zero. The reading is `stop_no_win`. The ceiling is not what fails.

The header in the verdict file still prints the default 2-point power line, which at 55 cases would be `cannot adjudicate` (n required 9812, minimum detectable effect 26.7). That line is not the gate for this run. The gate that ran is the one in the pre-registration: the interval above zero, and the $0.02 ceiling.

Search cost is $0. The rung was the one named in the amendment, not a separate search. Scoring spent about $0.12, including a discarded first pass that treated a markdown fence as a schema violation. The recorded pass strips one fence and then uses the same timestamp check. The whole experiment stays under $10.

## Scanner conclusion

The ranking is a pass. dateparser's known file, and the two libraries named after the fix, came out where the rules said. dateutil and tldextract stay `keep deterministic`, with the reasons above. The dateparser candidate rung was a hypothesis. The one path tested it and the evaluator declined it: the interval is not above zero. That refusal is the result.
