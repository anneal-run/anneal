# P1 rerun, tabletalk

Repo: [SkanderGhariani/tabletalk](https://github.com/SkanderGhariani/tabletalk) at `b84d063a3c28afcc84ed09d06dc1a9959b2deb39`. Named in [prereg.md](prereg.md) before the tree was opened.

It qualified from the public topics and description. The topics include langgraph and sqlite. The description is a local agent that asks a SQLite database questions, with tools and evals. The tool calls are SQL against a local database. The repo has an entrypoint (`tabletalk.cli:app`) and an eval that samples inputs (`evals/spider.py`, seed 7).

The 60 inputs are that eval's sample of Spider dev, in sample order. The repository itself commits 15 behavior questions in `evals/behaviors.yaml`. Those were not the 60.

## Capture

Runner time 2 minutes 42 seconds. Model cost $0.2892. `anneal import langsmith` imported 60 runs at 2026-10-16T23:15:01Z.

LangSmith tracing was on through the environment. The hosted API returned 401 because this environment has no LangSmith key. The file that imported is the run's own recorded steps, written in the record shape the importer already reads.

## Harness

H1 clock: 2026-10-16T23:15:45Z to 2026-10-16T23:16:04Z. Wall clock 19 seconds. Manual time 11 seconds (the generated Makefile runs `python`, and this machine has `python3`). Manual share 58%. The log is [harness-log.md](harness-log.md).

42 optimization runs, 18 holdout runs, chronological, sealed before the proposer started. Margin 10 points. n required 393. `run_sql` and `ask_user` are live. `run_python` is mock; none of the four candidates call it.

Reading the repo before 2026-10-16T23:15:45Z is onboarding, not harness time.

## Candidates

The control is the original agent on `claude-haiku-4-5`. Optimization 29/42, $0.1985. Holdout 10/18, $0.0908.

The engine session was arm C, isolated pack, no menu, fallback required, cap $10. It spent $0.6956 on `claude-sonnet-4-5` and wrote four candidates. The holdout was opened once, for the three with the best optimization scores. `schema_reduced` stayed on the optimization set.

`two_tier` and `consensus` are the same agent on a cheaper model, once and twice. They are model changes. `direct_sql` skips the agent loop and asks for SQL in one call, then falls back to the original if that SQL fails. `schema_reduced` is a keyword router in front of a smaller schema. Two submissions recorded the original as Sonnet. This run's original is Haiku, and those lines are priced as Haiku. The four files shipped a mock API key; scoring read the environment key and did not rewrite the files.

| candidate | kind | opt correct | opt cost | opt fallback | holdout correct | holdout cost |
|---|---|---|---|---|---|---|
| control | original | 29/42 | $0.1985 |  | 10/18 | $0.0908 |
| direct_sql | structural | 28/42 | $0.0420 | 0.00 | 13/18 | $0.0204 |
| two_tier | model | 28/42 | $0.2074 | 0.05 | 10/18 | $0.0971 |
| consensus | model | 28/42 | $0.3988 | 0.02 | 10/18 | $0.1888 |
| schema_reduced | structural | 25/42 | $0.1859 | 0.29 | not opened |  |

`direct_sql` is 78.8% cheaper on the optimization set and 77.5% cheaper on the holdout. The optimization correctness estimate is 2.4 points below the control. The holdout estimate is 16.7 points above it. The declared fallback rate was 0.35. The measured rate on these 60 cases was 0.

## Verdict

```
margin: 10.0 points; n required: 393
n reached: 18
verdict: cannot adjudicate
minimum detectable effect: 46.7 points
```

`anneal challenge orchestrate --require-fallback` wrote that and exited 2. A holdout of 18 cannot resolve a 10-point margin. That output is the registered result.

## Pull request

[pr/PR.md](pr/PR.md) puts `direct_sql` behind `ANNEAL_TABLETALK`. With the flag unset, the original implementation runs. [pr/shadow_runner.py](pr/shadow_runner.py) runs both and returns the original result. [pr/rollback.md](pr/rollback.md) is the rollback note. Nothing deploys. This was not opened on the tabletalk repository.

## Spend

Capture $0.2892. Scoring $1.1405. Together $1.43. The engine session $0.6956, inside the $10 cap.
