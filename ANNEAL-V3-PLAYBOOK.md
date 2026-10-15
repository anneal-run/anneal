# Anneal v3: Validation Playbook (revision 3)

Oct 15, 2026. Revision 3 adds the coding agent's corrections: a shared search budget across arms, no answer key in P0, correctness gates tied to what the holdout can resolve, external work gated on the harness earning it, an amortization window for search cost, and a pre-registered reading of the most likely result. Revision 2 folded in the earlier review: the central hypothesis is narrowed to one sentence, the scope is cut to what proves it, the coding-agent baseline is mandatory, evaluator overfitting is treated as the main technical risk, and Flow 1 (codebase discovery) is a separate experiment so a failure can be attributed.

## The central hypothesis

Can a coding agent, orchestrated by Anneal, autonomously discover and implement a better architecture for an existing AI workflow, with evidence reliable enough that the owning team deploys the change, and do it better than the same coding agent would on its own?

Everything below exists to answer that. The scanner, the hosted platform and the subscription are later questions.

## What gets built, what doesn't

Built: an executable harness around an existing workflow; an evaluator with a strict holdout; a challenger engine where a coding agent proposes structural candidates and GEPA tunes the prompt components inside each candidate; an orchestrator that runs, scores and ranks; a PR with tests, a feature flag and the old implementation as fallback.

Not built: an optimizer (GEPA and Opik exist), observability, dashboards, an SDK, a hosted platform, billing. Not in this experiment: the codebase scanner (see Experiment D).

## The baseline that decides it

Three arms on every workflow, same repo, same traces, same instruction ("make this workflow cheaper or more correct without breaking its contract"):

- Arm A: a coding agent alone (Claude Code or Codex), repo and traces only.
- Arm B: the same coding agent given Anneal's harness and evaluator, nothing else.
- Arm C: Anneal end to end (harness, evaluator, structural challenger engine, orchestrator).

Shared budget, pre-registered: every arm gets the same number of scored candidates, the same model dollars and the same wall-clock hours. Arm B spends its budget however it likes. If C wins only because it searched more, that is not a product result, so the budget is written in `report/prereg.md` before day 1 and the orchestrator enforces it.

Reading the result: if C beats B and A inside the same budget, the engine is the product. If B matches C, the harness and evaluator are the product and the engine is a prompt. If A matches C, nothing here is a product. Also report a prompt-optimized control (GEPA on the current architecture) beside all three; it stands in for what Opik or FutureAGI would deliver.

## Hypotheses (predicted values written in `report/prereg.md` before day 1)

| Id | Hypothesis | Pass | Fail |
| --- | --- | --- | --- |
| H1 | A runnable harness (entrypoint, tools, fixtures, cost meter) can be built from a real repo mostly by the agent | under 1 working day on the dogfood repo and on one unfamiliar repo in a supported stack, with every manual intervention logged and under 20% of the time | over 2 days on the unfamiliar repo with the time dominated by repo-specific plumbing |
| H2 | A structural challenger (fewer calls, different graph, code for a step, tool changes) beats both the baseline and the prompt-optimized control | cost: at least 30% lower per run, with the search cost amortized over one month of that workflow's volume. Correctness: the holdout confidence interval excludes zero, with the minimum detectable effect printed as the bar (a 50 to 100 item holdout cannot resolve 3 points; say so). Non-inferiority margins: correctness not more than 2 points worse, p95 latency not more than 20% higher, safety invariants intact. On 2 of 3 workflows | wins are prompt-level only, the structural win disappears on the holdout, or the gain exists only on mocked tools |
| H3 | The evidence is good enough to act on | an external team merges the PR or schedules a production trial for it, on at least 1 of 2 external workflows; "would merge" is recorded but does not pass | owners ask for a full labeled set before considering it |
| H4 | Teams will pay for the process, not the report | at least 1 team commits in writing, with a named price, to pay for the same process on a second workflow; a promise without a number is a polite yes and does not pass | nobody wants a second workflow |
| H5 | Arm C beats Arm B | C finds a structural win B did not, or the same win with less human time, on 2 of 3 | B matches C |

Prompt-only wins are reported separately. They are evidence for the incumbents' product, not for this one.

## Assets to reuse (verify readiness on day 1, do not rewrite)

LangSmith importer (there is no OpenTelemetry importer); shape and provenance inference; recording-backed replay server; equivalence rules with critical-field exact match; LangGraph fallback and history reconstruction; report writer; `examples/github_triage` with 360 traced real runs. Day 1 starts from `report/github_triage-dogfood.md`, which already ran this path and lists what broke. Do not rediscover that list, and do not treat the Tier 1 compiler as the challenger: on this workflow it compiled a plan and finished no holdout run.

## Deliverables

### D1. Harness builder

A coding-agent skill plus a CLI that produce, inside the customer's repo: an entry wrapper around the real code path; read-only tools live; side-effecting tools served from recordings with canonical-arg matching; mocks where nothing is recorded, flagged in the report (a candidate whose gain appears only on mocked tools is disqualified, not flagged); fixtures from traces; fixed seeds; a cost and latency meter on every model call; `make harness` running the baseline end to end. Log every manual intervention with its duration in `report/harness-log.md`.

### D2. Evaluator builder, with the holdout as a hard rule

- Weak labels from downstream signals (overrides, corrections, retries, reopened tickets, escalations), each with a documented mapping to right or wrong and an estimated precision.
- A labeled set of 100 to 200 items with the owning engineer or a model judge plus human review of disagreements. Hours logged.
- Chronological split: optimization set and holdout. The challenger engine never sees the holdout, never sees holdout scores, and the orchestrator reports holdout results only once per candidate at the end. Any candidate whose optimization-set gain exceeds its holdout gain by more than the confidence interval is flagged as overfit and disqualified.
- Three verdicts per challenger: compatible (contract and invariants), correct (against labels, with a confidence interval and the minimum detectable effect printed), worth it (cost, latency, risk against the gain).
- Beyond average correctness: p95 latency, tool-call counts and patterns, safety invariants (no new side-effect tools, no removed approvals), and a hard-case subset scored separately.
- Critical fields matched exactly; free text only where no critical field exists.

### D3. Challenger engine

Two layers, because a prompt optimizer cannot do code transformation:

- Structural proposer: a coding agent generates candidate implementations from the harness and the traces. Candidate types it may use on P1 and P2: collapse the loop into prefetch plus one structured call; deterministic router plus a small model; bounded workflow instead of a planner; code for any step whose outputs are a deterministic function of state (provenance says so); tool removal or re-description; cheaper model with the same structure. At least three genuinely different architectures per workflow, not three prompts. On P0 the proposer gets no menu at all (see P0): the dogfood repo's known win must be discovered, not selected.
- Component tuner: GEPA on the prompt components inside each candidate, and on the baseline as the control arm.
- Orchestrator: runs every candidate through D2 on the optimization set, ranks, then scores the top three once on the holdout.

### D4. Verdict report and PR

`report/<workflow>.md`: baseline, control, every candidate with the three verdicts, holdout results, what was mocked, labeling hours, the overfit flags. A PR with the winner behind a feature flag, the old implementation wired as fallback, tests from the fixtures, a rollback note. Nothing deploys; the owners approve.

## Experiments, in order

### Experiment P0, days 1 to 5: structural optimization on the dogfood repo

`examples/github_triage`, 360 traced runs, 41 observed tool sequences. The known answer from the earlier test is that a prefetch-plus-one-call script matched the agent at a seventh of the cost. Because the answer is known, P0 runs without an answer key: the proposer prompt names no candidate types, and the earlier memo is kept out of its context. If the engine finds the known win or something better unprompted, P0 is evidence of discovery; if it only finds it when the menu lists it, H2 and H5 do not pass on this repo and P0 counts as a pipeline check only. Output: three-arm result plus control under the shared budget, harness log, evaluator with holdout.

### Experiment P1, days 6 to 9: one unfamiliar repo

Gated on H1 passing on the dogfood repo; if the P0 harness was hand-built, P1 and P2 wait until it isn't. The repo and the supported stacks are named in `report/prereg.md` before day 1, not chosen after P0. A public agent repo in a supported stack you have not read. Same process. Output: harness time and manual-intervention share, three-arm result, what broke in the reused assets.

### Experiment P2, days 6 to 14 in parallel: two external workflows

Same gate as P1: no external work until H1 has passed on the dogfood repo. Partners (below). Same process, inside their environment. Output: H2, H3, H4 and H5 numbers.

### Experiment D, separate week, after the decision: codebase discovery (Flow 1)

The scanner that finds non-AI code worth becoming a model call, with "keep deterministic" as a first-class verdict. Measured on ranking quality: does it find credible candidates on repos known to have them, and does it correctly say no on clean repos. Not part of the 14-day decision, so a scanner failure and an engine failure can be told apart.

## Partners

Profile: AI-native SaaS, 2 to 20 engineers, LangGraph or the OpenAI Agents SDK, tracing on, model spend of $10k a month or more on at least one workflow, read-only or idempotent tools in it.

Offer: a free optimization of one workflow, done inside their environment, delivered as a PR they can merge or ignore, with the three-arm comparison so they see what a plain coding agent would have found.

Asks: run the skill on the workflow, 30 to 60 days of traces, one engineer for a two-hour labeling session, and two honest answers: would you merge this, and what would make you run it again next month.

The retention question, asked of every partner: "If this improves the workflow by 30% and you merge it, what causes you to use it again next month?" Record the answer verbatim. Concrete triggers count: constantly changing AI workflows, six-figure monthly spend, ongoing regressions, too many workflows to tune by hand. "We'd rerun it when a new model ships" counts when they name a cadence and a dollar threshold; without those it is a polite answer. Do not rule the model-release trigger out in advance; it may be the most believable reason to run this twice.

Exclusions: your employer's code, traces or customers, in any form. Personal machines and accounts, dated log.

## Decision on day 14 (`report/decision.md`)

Pre-registered reading of the most likely result, written before any run: Arm B matches Arm C, there is a real structural cost win where tools are recorded, and partners will not merge a production rewrite off a two-hour labeling session. If that is what happens, the decision is already made: the product is the harness and the evidence, the engine is a prompt, and the next version is built around the harness, the evaluator and the labeling workflow. That outcome is not inconclusive and must not be narrated as such.

Strong positive: a structural challenger delivers a meaningful improvement that survives the holdout, Arm C beats Arm B, an external team merges or schedules a trial, and one team commits to paying for a second workflow. Build the next version.

Promising but inconclusive: structural wins exist but needed heavy manual work. Narrow to one workflow category or one stack and run three more partners. Arm B matching Arm C is not this bucket. It is the pre-registered decision above: the product is the harness and the evidence.

Negative: wins are prompt or model swaps, the evaluator is not trusted without expensive labeling, or engineers prefer doing this in their own coding agent. Stop.

Harness time over two days on one repo is not a stop by itself; it is a reason to narrow the supported integration. Two paying customers is encouraging, not fit.

## Pre-registration checklist (`report/prereg.md`, before day 1)

- Predicted values for H1 to H5
- Shared search budget per arm: candidates scored, dollars, hours
- The unfamiliar repo for P1 and the supported stacks, named
- Amortization window for search cost: one month of the workflow's volume
- Non-inferiority margins and the minimum detectable effect the holdout can resolve
- The pre-registered reading of the expected result, copied from the decision section

## What to ask the reviewer to attack next time

1. The harness log: is it an agent-built harness with interventions, or a hand-built harness with an agent in the loop.
2. The holdout discipline: show that no holdout score reached the challenger engine.
3. Arm B versus Arm C: what, specifically, did the engine find that the coding agent with the same harness did not.
4. The retention answers, verbatim.
5. The reused assets: what actually worked on day 1 and what had to be rewritten.
