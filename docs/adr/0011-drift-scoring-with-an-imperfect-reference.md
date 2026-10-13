# 0011. Drift scoring with an imperfect reference

Date: 2026-10-13
Status: accepted

## Context

ADR 0009 labels each arm's behaviour on a drift type by the worst outcome that occurred: one silent failure makes the arm "fails silently". That rule assumes Tier 0 gets every case right, which the simulated environment did.

A real model does not. In the github_triage dogfood run, Tier 0 got the job done on 72% to 83% of issues, depending on the repository. Under the old rule every arm, Tier 0 included, reads "fails silently" on every input set, and the label says nothing about drift. The dogfood pre-registration predicted this ("expected breakage 1").

## Decision

`evaluate(..., reference="tier0")` scores drift relative to the reference.

- **Scoring set.** For each input set, an arm is scored only on the cases the reference arm got done (`correct` or `fallback`). A case the original agent could not do says nothing about how another arm handles drift.
- **Rates.** On that set, each arm gets a silent rate (`silent` plus `fallback_wrong`), a loud rate and a fallback rate. These are computed on the drift cases and, the same way, on the holdout cases.
- **Behaviour** on a drift type is what the drift adds to the arm's own holdout rates:
  - "fails silently" if the silent rate rises by `DRIFT_MARGIN` (10 points) or more;
  - otherwise "fails loudly" or "falls back" if that rate rises by the margin, with the larger rise winning;
  - otherwise "handles it".
- **Unchanged.** Task success and cost per task are still computed over all cases. The old rule still applies when no reference is given, so the synthetic dry run is unchanged.

**The margin was fixed before any arm ran on real data.** It was set in this ADR, before the three arms were run on the github_triage drift sets. With 30 drift cases, 10 points is three cases. It is a coarse threshold, not a significance test. The memo reports the rates next to the label so a reader can judge for themselves.

## Consequences

- Gate 1's H4 drift part reads the same labels, now with a meaning that survives a reference below 100%.
- **Low-success references.** An arm with a high holdout failure rate can absorb drift failures without changing its label. That is intended, since it is already failing at that rate, but it is why the memo shows the rates.
- **Small sets.** With few scored cases (a reference that is often wrong on a drift set) the rates are noisy. `scored_cases` is reported.
