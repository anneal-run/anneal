# Pre-registration: github_triage dogfood

Written 2026-10-13. No model call or trace exists yet for this workflow: the agent, tools and task check were built and tested offline only, against a fake GitHub and a scripted model. This file is committed before the first run, and git history is the record of that. It is not edited afterwards. The comparison will go in the dogfood memo.

This is a **dogfood** run of the real path. It is not evidence for H1 or H2, and the hypotheses register is not touched by it.

## Protocol

- **Agent.** `examples/github_triage/agent.py`: a LangGraph tool loop plus one structured-output call.
  - Model: `claude-haiku-5-5` at temperature 0.
  - Tools: `get_issue`, `list_labels`, `search_similar_issues` and `draft_comment`, all read-only (S0).
  - Task check: `examples/github_triage/RUBRIC.md`.
- **Compile and holdout: `astral-sh/uv`, 200 issues.** These are the latest closed, labelled issues opened from 2026-01-01 to 2026-06-30, run oldest first. The split is chronological: compile on the first 140, hold out the last 60.
- **Second repository: `pydantic/pydantic`, 100 issues**, same rule. Its runs are recorded Tier 0 traces, and its last 30 are the `new_enum` drift cases (a different label vocabulary).
- **`renamed_field`: `python/mypy`, 30 issues.** Same domain (Python tooling) but a different issue template.
- **`new_topic`: `godotengine/godot`, 30 issues.** A different domain (a game engine).
- **Arms.** Tier 0, compiled and baseline run on the 60 uv holdout issues and on each set of 30 drift cases.
  - The baseline is written by a separate Claude Code session from `BRIEF.md` and the 140 compile traces, with a one-day time box.
- **Replay.** The 60 holdout runs are replayed twice, once with recorded model answers and once with live ones.
- **Injected deopts.** Twenty, into the real LangGraph agent with the real model.
- **Budget.** At most $20 of model spend, enforced by `budget.py`.

## Expected numbers (stated before seeing any trace)

**Shape of the runs.**
- **Calls per run.** A typical run makes 4 to 6 model calls: the tool loop, then the structured answer.
- **Spend sits late in the run.** The call that reads the issue and the label list carries most input tokens. uv has on the order of 100 labels with descriptions, so the label list alone is a few thousand tokens. Later calls repeat all of it.
- **Expect tool-order variance.** The model will not use one fixed tool order. For example, `get_issue` and `list_labels` will sometimes come in parallel and sometimes in sequence, and `search_similar_issues` will be skipped or repeated. Expect 5 or more distinct skeletons in the 140 compile runs, and a dominant path covering 40% to 70% of runs.

**Spend by class, uv compile runs (`anneal analyze`).**

| class | expected share of spend | why |
| --- | --- | --- |
| removable | 5% to 15% (point: 10%) | Only the first call (`get_issue` / `list_labels` with repo and number) can be bound, and only by substring provenance against the free-text first message. It is also the cheapest call. |
| constrained | 15% to 35% (point: 25%) | The `search_similar_issues` query and the `draft_comment` body are written by the model. They count only where the position is stable at 95% or more. |
| judgment | 30% to 55% (point: 40%) | Positions where tool order varies, plus text that flows into later arguments. |
| terminal | 15% to 30% (point: 25%) | The structured triage call. It has the largest context. |

**H2-style Tier 1 share** (removable plus measured constrained, with unmeasured constrained counted as zero): **under 15%**. On partner data that would be a "stop". Here it means nothing either way.

**Compile.**
- **The first call is refused.** The compiler will refuse to compile the first call as a `tool` step, because `repo` and `number` are substrings of the message "Please triage issue #N in R." and the M1 template language cannot extract a substring. It stays a forced-tool `llm` step, or needs a manual override that cannot be written in the template language either. That gets recorded as automation debt.
- **The plan has no removable tool steps.** It is all `llm` steps along the dominant path. So the compiled arm will cost about the same as Tier 0 or more, never meaningfully less.

**Replay.**
- **Recorded answers.** Most holdout runs that leave the dominant path will diverge or deopt. Expect a fallback rate of 30% to 60%.
- **Live answers.** Expect compiled task success within a few points of Tier 0. There are no S1 or S2 tools, so there can be no S1 or S2 wrong executions.

**Task success, Tier 0, uv holdout:** 55% to 80%. The weak point is `duplicate_of`: false duplicates on issues that were never marked as duplicates.

**Cost.**
- **Tier 0:** roughly $0.002 to $0.006 per run with Haiku 5.5.
- **Whole experiment:** under $5.

## Expected drift behaviour per arm

| arm | new_enum (pydantic labels) | renamed_field (mypy template) | new_topic (godot) |
| --- | --- | --- | --- |
| Tier 0 | handles it: reads the new label set | handles it | handles it |
| compiled | handles it or falls back. The repository is inside free text, so M1's input guards (schema, enum, pattern on structured fields) cannot see the change. Llm steps read the new labels the same way Tier 0 does, and deopts come only from tool-order divergence. | same as new_enum | same as new_enum |
| baseline | handles it if it calls `list_labels`; fails silently if it hard-codes uv's labels from the traces | handles it if it gives the body to a model; fails silently if it parses uv's template sections | handles it, by the same reasoning as new_enum |

**Expected overall H4 picture:**
- **Cost:** the baseline will be cheapest, with fewer model calls than Tier 0 and no tool loop.
- **Drift:** the compiled arm will not win on drift, because the script will mostly not need a patch either.
- **Build time:** this stays open until `report/setup-timing.md` has real entries.

## Expected breakages in the real path

These are named in advance so the memo can say which ones happened and which surprised us.

1. **The harness assumes a perfect Tier 0.** The three-arm "behaviour" label takes the worst mode that occurred. With Tier 0 at 55% to 80% task success, every arm, Tier 0 included, will show "fails silently" on every input set. Drift behaviour has to be scored relative to Tier 0 on the same case. Expect a harness fix.
2. **The structured-output call looks like a tool call with no tool run.** It will appear as a model call requesting a `Triage` tool that never runs as a LangSmith tool run. The importer and classifier may mis-handle it.
3. **The run input is LangGraph state.** `Run.input` will be `{"messages": [...]}` in LangChain's serialized form, not structured fields. Guards will be mined on message text.
4. **Real tool payloads may break the importer.** Tool results arrive as `ToolMessage` content strings holding JSON. Model content may arrive as Anthropic content blocks: a list of text and tool-use blocks.
5. **Parallel tool calls in a varying position.** These will reach the compiler's "parallel tool calls in a judgment step are not supported in M1" refusal.
6. **Fallback history needs the system prompt in the right place.** The agent adds its system prompt inside the node, not in state, so `initial_messages` must be the first human message only.
