# github_triage dogfood: what the real path did

**DOGFOOD, not Gate 1 evidence.** The hypotheses register is untouched. The generated memo is [github_triage-memo.md](github_triage-memo.md), and the pre-registration is [github_triage-prereg.md](github_triage-prereg.md) (commit fc40d1a, before any model call).

## Setup

- **Agent:** a LangGraph agent on `claude-haiku-5-5`.
- **Tools:** four read-only GitHub tools, with every response cached.
- **Tier 0 runs:** 360 in total, traced to LangSmith:
  - `astral-sh/uv`: 200 runs, compiled on 140 and held out 60;
  - `pydantic/pydantic`: 100 runs;
  - `python/mypy`: 30 runs;
  - `godotengine/godot`: 30 runs.
- **Pipeline:** the traces were exported to JSONL and imported with `anneal import langsmith`. Then: analyze, compile, replay (recorded and live), 20 injected deopts into the real agent, and three arms on 150 cases.

Total model spend: **$2.05** of the $20 cap.

| phase | spend |
| --- | ---: |
| Tier 0 runs (uv, pydantic, mypy, godot) | $1.20 |
| smoke test (3 issues; the first 6 attempts failed) | $0.02 |
| live replay | $0.09 |
| injected deopts | $0.07 |
| arms: compiled | $0.61 |
| arms: baseline | $0.07 |

## Breakages found in the real path, and fixed

Each was fixed with a test before the memo, and each fix is its own PR.

| # | Where | What broke | Fix |
| --- | --- | --- | --- |
| 1 | example | Claude 5 models reject `temperature` (400) | dropped it; deviation from the pre-registration, which said temperature 0 |
| 2 | example | Claude 5 models reject a conversation ending with an assistant turn, which broke the final structured call | end with a user turn |
| 3 | example | GitHub REST does not return a "close as duplicate" target, so 21 of 22 pydantic duplicates were dropped | read it via GraphQL (`ClosedEvent.duplicateOf`) |
| 4 | importer | LangGraph `ToolNode` results are exported as plain `ToolMessage` dicts; the whole message was stored as the tool result, so provenance saw no tool output | `fix/importer-plain-toolmessage` |
| 5 | runtime | no `LlmRunner` backed by a real model, so live replay and compiled arms could not run | `feat/chat-model-runner` |
| 6 | provenance | parallel tool calls bound to each other's results; `list_labels.repo` flipped between the input and `get_issue`'s body | `fix/provenance-request-time` (ADR 0003 amended) |
| 7 | classifier | `with_structured_output` on Anthropic is a tool request that never runs, so it came out vacuously `removable` (15% of spend) and would have compiled to a call to a nonexistent tool | `fix/classify-structured-output` (ADR 0004 amended) |
| 8 | compiler | a parallel first call where both tools need model-written arguments was refused, so **no plan could be compiled** | `fix/compile-parallel-model-args` (ADR 0005 amended) |
| 9 | compiler | the run output is LangGraph's whole state (messages, signatures), which is not reproducible, and the structured answer had no step to come from | `fix/compile-structured-terminal`: `output_path`, structured terminal steps, nullable types (ADR 0005 amended) |
| 10 | replay | live model answers write new tool arguments (new search queries); against the recording every one counted as a wrong execution | `feat/replay-live-tools` (ADR 0006 amended) |
| 11 | arms | the drift label assumed a perfect Tier 0; at 73-83% success every arm read "fails silently" | `fix/arms-imperfect-reference` (ADR 0011; margin fixed before the arms ran) |
| 12 | memo | H3 "passed" when 60 of 60 holdout runs fell back, which is true by construction and no evidence | `fix/gate-h3-vacuous` (ADR 0010 amended) |
| 13 | example and Makefile | the spend ledger lost updates across parallel runner processes; restarted runs traced an issue twice; two baselines collided in one pytest session | file lock, latest-trace-per-issue export, one pytest per baseline |

Found but not fixed (findings, not breakages):

- **No guards at all** (0 mined). The run input is `{"messages": [...]}` with the repository and issue number inside free text. M1's input guards have nothing structured to check, so nothing on the compiled path can see a drifted input.
- **`Client.list_runs` is deprecated** in langsmith 0.14.8 (removal after Jan 31, 2027), and exports are large: 93 MB for 200 traces, because every `llm` run carries the full history. Both are recorded in the vendor notes.
- **The H1 measure is too lenient.** difflib at 0.9 merges 197 of 200 runs, with 41 different skeletons, into one cluster, so "98.6% of spend in repeated clusters" overstates how repeated the runs are. The dominant path covers 32%.

## Pre-registration vs actual

| prediction | pre-registered | actual |
| --- | --- | --- |
| model calls per run | 4 to 6 | 5.7 (1,133 calls / 200 runs) |
| distinct skeletons in 140 compile runs | 5 or more | 41 variants over 200 runs |
| dominant path coverage | 40% to 70% | **32%** (45 of 140), below the range |
| removable share | 5% to 15% (point 10%) | **0%**, below the range: the first call's repo and number are not bindable at all (number: no provenance; repo: substring, refused) |
| constrained share | 15% to 35% (point 25%) | 23% (all runs), 20% (holdout) |
| judgment share | 30% to 55% (point 40%) | 55% (all), 58% (holdout), at or just above the top |
| terminal share | 15% to 30% (point 25%) | 22% |
| H2-style Tier 1 share | under 15% | 0% |
| first call refused as a `tool` step | yes | yes, and worse: the compiler refused the whole plan until fix 8 |
| plan has no removable tool steps | yes | yes: 13 steps, 7 of them `llm` (5 tool steps, 1 end) |
| compiled cost about equal to Tier 0 or more | yes | yes: $0.0043 vs $0.0035 per task in the arms; $0.0048 vs $0.0035 in replay |
| recorded-replay fallback rate | 30% to 60% | **100%**, above the range |
| live-replay compiled success within a few points of Tier 0 | yes | 73.3% vs 73.3%, but only because every run fell back |
| no S1/S2 wrong executions | yes | yes (no S1/S2 tools) |
| Tier 0 task success on the uv holdout | 55% to 80% | 73.3% |
| Tier 0 cost per run | $0.002 to $0.006 | $0.0035 |
| whole experiment under $5 | yes | $2.05 |
| Tier 0 drift: handles all three | yes | yes |
| compiled drift: handles it or falls back, input guards blind | yes | it falls back on every input, drifted or not; 0 guards |
| baseline drift: handles if it calls `list_labels` / reads the body | yes, or fails silently if hard-coded | it calls `list_labels` and gives the body to the model: handles all three |
| baseline cheapest | yes | yes: $0.0005 per task, 7x cheaper than Tier 0, with task success 75% vs 73% |
| compiled does not win on drift | yes | yes: 0 of 3 |
| expected breakage 1 (harness assumes a perfect Tier 0) | yes | happened; fixed (11) |
| expected breakage 2 (structured output as a tool call) | yes | happened; it was worse than expected (vacuously removable) (7, 9) |
| expected breakage 3 (run input is graph state) | yes | happened; guards mined nothing |
| expected breakage 4 (tool payloads, content blocks) | yes | happened: plain `ToolMessage` dicts (4) |
| expected breakage 5 (parallel calls in a varying position) | yes | happened in a stable position, and blocked compilation (8); plus the sibling-binding bug (6), not predicted |
| expected breakage 6 (system prompt placement for fallback) | yes | handled by design: 18 of 20 resumed with no repeated step |

Not predicted at all: the Claude 5 API rejections (1, 2), GitHub's duplicate links being GraphQL-only (3), the vacuous H3 pass (12), and the H1 measure being too lenient.

## Setup timing (report/setup-timing.md)

There are no entries: the stopwatch is yours. H4 build time stays **open**. For orientation only (not an entry):
- **Baseline:** its `BUILD_LOG.md` says 3 min 57 s for a separate agent session.
- **Compiled arm:** its compile compute was 0.45 s. The tool declarations here are four lines (all read-only, S0).

## The result in one paragraph

On a real, judgment-heavy agent:
- **The M1 compiler compiles a plan but never executes a run to the end.**
- **The dominant path is one exact tool sequence**: two searches, a draft, a text turn, then the answer. Real runs vary that sequence, so 60 of 60 holdout runs fall back, and the compiled arm costs more than Tier 0.
- **Fallback works:** 18 of 20 injected deopts finished correctly with no repeated step. The two misses are the agent choosing different labels on a rerun, ordinary model variance rather than lost history.
- **The handwritten script wins outright.** It took about 4 minutes to write and costs 1/7 of Tier 0 per task, at the same task success. Nothing in this workflow needed the agent's loop: one well-built prompt with deterministic search does the job.

## What behaved differently from the synthetic environment

1. **Tier 0 is not a reference.** It was 100% in the simulator and 73-83% here, which forced reference-relative drift scoring (ADR 0011). It also makes "20 of 20 injected deopts" unreachable on a 75% task, independent of fallback quality.
2. **Tool order varies run to run.** The simulator's agent always took the same steps; Haiku took 41 different skeletons. The dominant path covers a third of runs, and a live model given the compiled prompt (instead of its own conversation) chose a different next step 59 times out of 60.
3. **Input is free text.** The simulator gave structured fields (`email`, `priority`), so guards and bindings had something to hold. Here the input is a chat message, so nothing binds and nothing is guarded.
4. **Framework shapes leak into the trace.** These include structured output as a fake tool call, graph state as input and output, parallel tool calls, and provider content blocks with signatures. None existed in the simulator, and most of the 13 breakages came from them.
5. **Drift was harmless.** In the simulator, drift broke the script and the compiled path differently. Here every arm read the label set and the issue body at run time, so no arm, script included, was hurt by a new repository, template or topic.
6. **Costs are tiny and dominated by context.** A run cost $0.0035, and the label list repeated in every call is most of it. The script's win comes from making one call with less context, not from removing calls, which is a lever the compiler does not have in M1.
