# 0010. The Milestone 1 memo and how Gate 1 is evaluated (M1.9)

Date: 2026-10-13
Status: accepted

## Context

M1.9 requires `report/m1.md` with numbers for H1 to H4, the manual steps, and the hypotheses register. `make m1` must produce it end to end. Gate 1 is stated in prose in the roadmap. To be computed rather than argued, each criterion needs an exact reading. There is still no partner workflow.

## Decision

`anneal.report.memo.gate1` gives each criterion one of four verdicts: `pass`, `fail`, `stop` or `open` (cannot be decided from what was measured). The gate verdict, in this order, is:
- `stop` if any criterion is `stop`;
- `not passed` if any criterion is `fail`;
- `incomplete` if any criterion is `open`;
- `passed` otherwise.

**H2.**
- **What is measured:** `tier1_share` from `anneal analyze` on the holdout runs. That is removable spend plus measured constrained savings, with unmeasured constrained savings counted as zero.
- **Thresholds:** 40% or more passes; under 25% stops.
- **In between:** H2 passes only if the H4 drift part is won, and stops otherwise.

**H3.** Computed from the replay report. All of these must hold, otherwise it fails:
- compiled task success is at most 1 point below Tier 0 (fallbacks count with Tier 0's result);
- zero S1 and S2 wrong executions;
- the S0 wrong rate among accepted runs is within the 1% budget;
- a plan was compiled.

**Fallback.**
- **Pass:** at least 20 injected deopts, all finishing with task success and none repeating a completed write.
- **Fail:** any failure.
- **Open:** fewer than 20 trials.
- **Trial placement:** trials are placed on inputs the plan accepts, deopting at each step in turn, so every step is exercised.

**H4.** It has three parts. The compiled arm wins a part as follows:
- **Build time:** the compiled build time is under half the baseline's. If either build time is not measured, this part is unknown.
- **Cost:** the compiled cost per task on the holdout is below the baseline's.
- **Drift:** on at least two drift types, the compiled arm falls back or handles it while the script fails (loudly or silently). A loud failure counts as "needs a patch".

H4 passes if any part is won. It stops ("the script wins on all three") only if all three parts are known and lost. Otherwise it is open.

**Build time must include human setup.** The compiled arm's build time must include the time a person spent on tool declarations and the task check, timed the same way as the baseline's. Compile compute time alone is not a build time. Until it is timed, the build part of H4 is unknown.

**H1.** H1 is the share of model spend in skeleton clusters with at least `min_support` runs, over all runs. It is reported, not gated.

**Two cost numbers.**
- **Replay cost per run** charges a fallback run its compiled spend plus the full recorded Tier 0 cost. This is conservative, ADR 0006.
- **Arm cost per task** charges what the resumed agent actually spent.

Both are shown, and they differ by design.

**Synthetic memos.**
- **Banner:** a memo built from simulated data carries a banner and labels the gate verdict "would be, on real data".
- **Register:** the roadmap's hypotheses register is updated only from a memo on real data.

**`make m1`** runs `tests/synth/m1.py`. It performs the following steps on the simulated support workflow:
1. analyze all runs and the holdout;
2. compile on the first 70%;
3. replay the rest with the task check;
4. inject 20 deopts and resume with the history-driven agent;
5. run the three arms with the drift suite;
6. write `report/m1.md`.

For a partner, the same steps run with their store, tool declarations, agreed task check, agent entrypoint and baseline. Only the experiment module changes.

## What the synthetic memo says

| criterion | verdict | measured |
| --- | --- | --- |
| H2 | stop | 16.7% of holdout spend removable; 33.3% constrained, unmeasured |
| H3 | pass | 100% vs 100% task success, no wrong executions (recorded answers) |
| fallback | pass | 20 of 20, every step s0 to s8 |
| H4 | open | build not timed; cost and drift (1 of 3) lost |

H2 stops before H4 matters. The ticket summary, the reply and the routing decision are template-like or rule-like. M1 can classify them only as constrained or judgment. This is the same finding as ADR 0009, reached through the spend numbers.

## Consequences

- Gate 1 on a partner workflow is a run of `make m1` with a partner experiment module, plus the open items listed in the memo.
- Changing a threshold means editing the roadmap (CONTRACT) and this ADR. The constants live in `anneal.report.memo`.
