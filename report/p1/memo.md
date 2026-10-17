# P1: open_deep_research

Pinned commit `1b7d2e80db9faa586165c60e09096dbbfd483a64`. LangGraph graph `src/open_deep_research/deep_researcher.py:deep_researcher`. This repo was not prepared for Anneal. The harness log is [harness-log.md](harness-log.md).

## H1

The harness was not built. Wall clock 4 minutes. Manual share 100%.

H1 does not pass. The prediction was that this repo would use most of a day and might miss the 20% manual bar. It missed the bar because the session stopped before a harness existed.

## What ran

| step | result |
|---|---|
| Clone at the pin | `1b7d2e80` |
| `anneal import langsmith` on `tests/expt_results/deep_research_bench_gpt-5.jsonl` | `KeyError: 'start_time'` |
| `anneal challenge harness` | Not started. There is no store. |
| Pack, engine with fallback, orchestrator | Not started. A pack without a sealed holdout is not this run. |

## What broke

The only JSONL in the tree is `{id, prompt, article}` written by `tests/extract_langsmith_data.py` from a LangSmith project the repo does not include. The importer accepts a LangSmith run export. No new importer was added. The public Deep Research Bench dataset linked from the README is a task list, not a trace export in this tree.

The margin for this workflow is registered in `anneal.toml` as 2.0 points, which needs n of 9812. There is no paired count yet, so there is no verdict.
