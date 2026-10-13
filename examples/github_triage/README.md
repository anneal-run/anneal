# github_triage: a dogfood workflow

A LangGraph agent triages GitHub issues: it suggests labels from the repository's label set, flags duplicates, and drafts a reply. It runs with a real model and real (read-only) GitHub tools, and is traced to LangSmith. Anneal then runs the whole M1 path on those traces.

Everything here is read-only. `draft_comment` returns text and never posts.

## Files

| File | What it is |
| --- | --- |
| `agent.py` | the LangGraph agent (tool loop plus a structured final answer) |
| `tools.py` | `get_issue`, `list_labels`, `search_similar_issues`, `draft_comment` |
| `github.py` | a read-only REST client with an on-disk cache, which respects rate limits |
| `select_issues.py` | picks closed issues and records what maintainers did (the ground truth) |
| `check.py`, `RUBRIC.md` | the task check and its limits |
| `budget.py` | a spend ledger that stops the run at `TRIAGE_BUDGET_USD` (default $20) |
| `run.py` | runs the agent over a selection, traced |
| `export.py` | exports the traces from LangSmith to JSONL for `anneal import` |

## Environment

| Variable | Required | Notes |
| --- | --- | --- |
| `GITHUB_TOKEN` | yes | read-only access to public repos is enough |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | yes | the model provider's key |
| `TRIAGE_PROVIDER` | no | `anthropic` (default) or `openai` |
| `TRIAGE_MODEL` | no | default `claude-haiku-5-5` |
| `LANGSMITH_TRACING` | for tracing | set to `true` |
| `LANGSMITH_API_KEY` | for tracing | |
| `LANGSMITH_PROJECT` | for tracing | the project the traces go to |

GitHub responses are cached under `.cache/github/`, so reruns are free and deterministic.
