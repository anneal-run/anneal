# Experiment D ranking

The pre-registration is [prereg.md](prereg.md), committed at `69d8d07` before these trees were cloned. Each checkout is the commit named there. History was deepened to 200 commits so the churn count is the last 200, which is what the pre-registration scores. The thresholds were not moved after the trees were read.

## Brittle repositories

The known file has to be in the top five by score.

| repo | named spot | rank | ladder |
|---|---|---|---|
| dateparser | `dateparser/parser.py` | 2 of 253 | one structured call |
| tldextract | `tldextract/tldextract.py` | 1 of 9 | keep deterministic |
| dateutil | `dateutil/parser/_parser.py` | not in the tree | |

dateutil keeps its parser at `src/dateutil/parser/_parser.py`. That file is rank 1 of 22. The pre-registration named it without the `src/` prefix, so the named path is a miss. Its ladder is keep deterministic: one regex operation, no case commit in the last 200, and 34 string switches, which the rule counts in the score and does not promote.

tldextract is rank 1 and stays keep deterministic. The file has 45 commits in the window and no regex operation. The rule requires three regex operations before it will say one structured call.

dateparser's top file is `dateparser/date.py`, score 57, one structured call. `dateparser/parser.py` is second, score 52, the same rung.

## Clean repositories

Every file has to be keep deterministic.

| repo | files | other rungs |
|---|---|---|
| attrs | 24 | none |
| more-itertools | 4 | `more.py` and `recipes.py` are bounded workflow |

more-itertools fails the clean check. Both files contain the word `queue`, and the frozen rule treats that word as a manual-review word and as a queue. Attrs passes: all 24 files are keep deterministic.

## What this does not change

The thresholds stay as written. The one path in the pre-registration, capture through a pull request on the top candidate, has not been run. On the brittle repository whose known spot is in the top five and whose top file is a model rung, that file is `dateparser/date.py`.
