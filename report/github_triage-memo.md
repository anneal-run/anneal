# Milestone 1 memo: github_triage

> **DOGFOOD.** Real model, real tools and real traces, from public repositories, but not a partner workflow: the workflow was chosen to exercise the path and its task check was written by the implementer. It is not Gate 1 evidence and the hypotheses register is not updated from it.

Source: LangGraph triage agent on claude-haiku-5-5, 200 closed astral-sh/uv issues (compile 140, holdout 60), drift sets from pydantic/pydantic, python/mypy, godotengine/godot; traced to LangSmith and imported with `anneal import langsmith`. Task check: `github_triage.check:RunCheck`.

## Gate 1

| criterion | verdict | measured | required |
| --- | --- | --- | --- |
| H2 | stop | 0.0% of holdout spend removable or measured constrained | >= 40%; under 25% stop; between, only if the drift comparison is won |
| H3 | open | task success 73.3% compiled vs 73.3% Tier 0; S1+S2 wrong 0; S0 wrong 0.0%; no holdout run finished on the compiled path | within 1 point of Tier 0; zero S1/S2 wrong; S0 <= 1% |
| fallback | fail | 18 of 20 completed with task success and no repeated step | 20 of 20 injected deopts |
| H4 | open | build not measured; cost $0.0043 vs $0.0005; drift won on 0 of 3 | build time under 50% of the script's, or lower cost per task, or falls back on 2+ drift types where the script fails or needs a patch |

**Gate 1: stop.** (Would be, on partner data.)

## H1, H2: where the spend is

All 200 runs: 98.6% of model spend is in skeleton clusters with at least 5 runs (H1).

Holdout (60 runs, $0.2094):

| class | calls | spend | share |
| --- | ---: | ---: | ---: |
| removable | 0 | $0.0000 | 0.0% |
| constrained | 120 | $0.0420 | 20.0% |
| judgment | 159 | $0.1215 | 58.0% |
| terminal | 60 | $0.0460 | 22.0% |

Tier 1 saving counted for H2: $0.0000 (0.0%); constrained spend without a measured delta, counted as zero: $0.0420.

## H3: chronological replay

Compiled on 140 runs, replayed on the 60 later runs (model answers: live). Plan `677630e80e7c7017`.

|  | value |
| --- | ---: |
| Tier 0 task success | 73.3% |
| compiled task success (fallbacks count as Tier 0) | 73.3% |
| success among runs the guards accepted | n/a |
| fallback rate | 100.0% |
| wrong executions S0 | 0 |
| wrong executions S1 | 0 |
| wrong executions S2 | 0 |
| cost per run, Tier 0 | $0.0035 |
| cost per run, compiled | $0.0048 |

Deopts by step: s5: 1, s6: 59.

## Fallback

18 of 20 injected deopts (LangGraph 1.2.15, claude-haiku-5-5, at steps s0, s1, s2, s3, s4, s5) finished with task success and no repeated step.

- `astral-sh/uv#19566` at s1: success False, repeated nothing
- `astral-sh/uv#19658` at s4: success False, repeated nothing

## H4: against the handwritten baseline

| arm | build time | cost per task | task success | new_enum | new_topic | renamed_field |
| --- | --- | --- | --- | --- | --- | --- |
| tier0 | n/a (existing agent) | $0.0035 | 73.3% | handles it | handles it | handles it |
| compiled | 0.45 s compute; human setup not timed | $0.0043 | 68.3% | handles it | handles it | handles it |
| baseline | 237 s (separate session) | $0.0005 | 75.0% | handles it | handles it | handles it |

| arm | inputs | cases | correct | fallback | fallback_wrong | loud | silent |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| tier0 | holdout | 60 | 44 | 0 | 0 | 0 | 16 |
| tier0 | new_enum | 30 | 25 | 0 | 0 | 0 | 5 |
| tier0 | new_topic | 30 | 22 | 0 | 0 | 0 | 8 |
| tier0 | renamed_field | 30 | 25 | 0 | 0 | 0 | 5 |
| compiled | holdout | 60 | 0 | 41 | 19 | 0 | 0 |
| compiled | new_enum | 30 | 0 | 26 | 4 | 0 | 0 |
| compiled | new_topic | 30 | 0 | 22 | 8 | 0 | 0 |
| compiled | renamed_field | 30 | 0 | 27 | 3 | 0 | 0 |
| baseline | holdout | 60 | 45 | 0 | 0 | 0 | 15 |
| baseline | new_enum | 30 | 25 | 0 | 0 | 0 | 5 |
| baseline | new_topic | 30 | 21 | 0 | 0 | 0 | 9 |
| baseline | renamed_field | 30 | 28 | 0 | 0 | 0 | 2 |

Drift behaviour is scored on the cases `tier0` got done, against each arm's own holdout rates (a rise of 10% or more counts).

| arm | inputs | scored | silent | holdout silent | loud | holdout loud | fallback | holdout fallback | behaviour |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| tier0 | new_enum | 25 | 0% | 0% | 0% | 0% | 0% | 0% | handles it |
| tier0 | new_topic | 22 | 0% | 0% | 0% | 0% | 0% | 0% | handles it |
| tier0 | renamed_field | 25 | 0% | 0% | 0% | 0% | 0% | 0% | handles it |
| compiled | new_enum | 25 | 0% | 9% | 0% | 0% | 100% | 91% | handles it |
| compiled | new_topic | 22 | 0% | 9% | 0% | 0% | 100% | 91% | handles it |
| compiled | renamed_field | 25 | 0% | 9% | 0% | 0% | 100% | 91% | handles it |
| baseline | new_enum | 25 | 4% | 2% | 0% | 0% | 0% | 0% | handles it |
| baseline | new_topic | 22 | 5% | 2% | 0% | 0% | 0% | 0% | handles it |
| baseline | renamed_field | 25 | 0% | 2% | 0% | 0% | 0% | 0% | handles it |

## Manual steps

| step | why | automate in |
| --- | --- | --- |
| Declared 4 tools as read-only S0 | the compiler cannot infer side effects | M2 SDK |
| Wrote the task check and RUBRIC.md | no partner; implementer-defined | never |
| Selected issues and ground truth | labels and duplicate closures as the proxy | never |

## Hypotheses register

| id | hypothesis | number | status (if partner data) |
| --- | --- | --- | --- |
| H1 | repeated runs carry most spend | 98.6% | supported |
| H2 | 40%+ of spend removable or constrained | 0.0% of holdout spend removable or measured constrained | failed |
| H3 | guards and replay keep wrong execution in budget | task success 73.3% compiled vs 73.3% Tier 0; S1+S2 wrong 0; S0 wrong 0.0%; no holdout run finished on the compiled path | untested |
| H4 | compiled beats the script on one of three | build not measured; cost $0.0043 vs $0.0005; drift won on 0 of 3 | untested |

## Open items

- Not a partner workflow; Gate 1 still needs one.
- H4 build time stays open until report/setup-timing.md has stopwatch entries.
