# Baseline brief: `github_triage`

You are the baseline arm of a three-way comparison (ANNEAL-ROADMAP.md M1.8). Write this workflow as a plain Python script, the way a competent engineer would replace an agent with code. The other two arms are the original agent and a compiled path. Your script is what they must beat, so make it good: correct, cheap and robust.

**Time box: one working day.** Log the time you actually spend.

## What you get

- `traces.jsonl`: 140 recorded runs of the current agent, one JSON object per line. Each has `input`, `output` and `events`; the events are model calls and tool calls, with their arguments and results. These are the same runs the compiler sees. They come from one repository (`astral-sh/uv`). Personal data in them is redacted with placeholders such as `<EMAIL_1>`.
- `interface.py`: what your `run` receives (`Tools`, `Model`, `ToolError`).
- `RUBRIC.md`: the definition of "job done" and its known limits.
- This brief.

Do **not** read anything outside `baseline/github_triage/`. A real engineer would have the traces and the task definition, nothing more. You have no API keys: do not call GitHub or a model for real. Build with fakes and the recorded tool results in the traces. The harness runs your script against the real model and the cached GitHub API afterwards.

## The task

You are given a GitHub issue that was just opened. Produce its triage:

```python
{"suggested_labels": [str, ...], "duplicate_of": int | None, "draft_reply": str}
```

- `suggested_labels`: labels that apply. Use only labels that exist in the issue's repository.
- `duplicate_of`: the number of an earlier issue that reports the same problem. Use `None` if there is none or you are not sure.
- `draft_reply`: a short, friendly reply to the reporter. Never post it. Don't promise fixes or timelines.

`RUBRIC.md` has the pass condition. Summary: at least one suggested label must be one the maintainers applied, no suggested label may be outside the repo's set, and `duplicate_of` must match the maintainers' duplicate closure (or be `None` if there was none). The reply is not scored.

**Your script will also be run on other repositories, issue templates and topics than the ones in the traces.** It should work on any public GitHub repository. Where it cannot do the job, failing loudly (raising) is better than silently doing the wrong thing.

## Tools (via `tools.call(name, args)`)

All four are read-only.

| tool | args | result |
| --- | --- | --- |
| `get_issue` | `repo` (`owner/name`), `number` (int) | `{"number", "title", "body", "author", "created_at"}`, as the issue was opened (no labels and no state) |
| `list_labels` | `repo` | `[{"name", "description"}, ...]`: every label in the repo |
| `search_similar_issues` | `repo`, `query` (keywords) | up to 5 `{"number", "title", "state", "created_at"}`. Only issues created before the one being triaged; GitHub issue search syntax applies to `query` |
| `draft_comment` | `issue_number`, `body` | `{"issue_number", "draft"}`. It returns the text and posts nothing; you don't need to call it |

## The model (`model.complete`, see `interface.py`)

It is the same model the agent uses. Use it where judgment or text is needed. You pay per token, and cost per task is one of the things you are measured on. Deterministic code costs nothing.

## Deliverables (all in `baseline/github_triage/`)

1. `workflow.py` with `def run(repo: str, number: int, tools: Tools, model: Model) -> dict`.
2. `test_workflow.py`: pytest tests with your own fakes for `Tools` and `Model`. Run them with `uv run pytest baseline/github_triage -q -p no:cacheprovider --no-cov`.
3. `BUILD_LOG.md`: start and end time (from `date`), time spent, what you needed and where it came from, the assumptions you made, and anything you would ask the maintainers.

You are measured on build time, cost per task, task success on later issues, and behaviour on other repositories. Write to the standard you would ship.
