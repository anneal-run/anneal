cannot adjudicate; n required: 60

22 usable issue cases. The pre-registered floor is 60, and the margin is the minimum detectable effect at 60 cases, 25.6 points. The power check refuses this corpus. The point estimate below is not an adjudication.

The correctness-win orchestrator still scored the chronological holdout of 7, ceiling $0.02 per input. Suite regressions are 0.

```
margin: 25.6 points; n required: 60
n reached: 7
verdict: single_arm

# Anneal v3 challenge

Reading: `single_arm`.

This is the v3 decision, not the Milestone 1 hypothesis register.

Structural winner: C/parser_first.
Labeling hours: 0.0.
External merge or scheduled trial: False.
Paid commitment: False.

## Candidates

### C/parser_first

- Arm C, structural, human hours 0.0.
- Holdout scored: True.
- Compatible: True. Correct: True. Worth it: True.
- Cost reduction after one month of amortization: 0.0%.
- Cost per input: $0.0002.
- Failure-path cost per input: $0.0003.
- Failure-path share: 57.1%.
- Suite regressions: 0.
- Correctness: 57.1 points (interval 17.5 to 96.7, minimum detectable effect 74.9 points).
- Disqualified: no.
```

`single_arm` here means the interval on these 7 cases is above zero and the cost is under the ceiling. The minimum detectable effect on 7 cases is 74.9 points, wider than the 25.6-point margin. The line that governs is the first line of this file.
