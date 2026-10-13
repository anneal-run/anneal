# Task check rubric: github_triage

This is the definition of "job done" for the dogfood workflow. It was written by the implementer, not agreed with a partner (decision 2, 2026-10-13). It is fixed before the first run. Code: `check.py`.

## The job

The agent is given a newly opened issue. It should:
- suggest labels from the repository's label set;
- say whether the issue duplicates an earlier one, and which;
- draft a reply.

## Ground truth

The ground truth is what the maintainers did with the issue afterwards. It is collected by `select_issues.py`.
- **Issues:** closed issues opened between 2026-01-01 and 2026-06-30 that have at least one label or a duplicate closure.
- **`labels`:** the labels on the issue now.
- **`duplicate_of`:** the target of a duplicate closure. That is the closing reason `duplicate`, or a `duplicate` label, plus a "Duplicate of #N" comment. A duplicate closure whose target cannot be found is dropped from the set, and the count is reported.

## Pass condition

Both of these must hold:
1. **Labels.** At least one label is suggested, every suggested label exists in the repository, and at least one of them is among the maintainers' labels.
2. **Duplicate.**
   - If the maintainers closed the issue as a duplicate of #N, `duplicate_of == N`.
   - Otherwise `duplicate_of` is null.

The draft reply is not judged.

## Limits of this proxy

These are known and accepted. They make the absolute success rate a weak number. The comparisons between arms on the same issues are what the experiment is for.

- **The label rule is lenient.** One overlapping label passes, so a broad label (`bug`, `enhancement`) that maintainers almost always apply makes the rule easy to satisfy. Extra wrong labels are not penalised unless they don't exist in the repo.
- **Labels can come from automation.** Some labels come from issue templates or bots (for example a `needs triage` label applied on creation), not from a maintainer's judgment. The agent is not shown the issue's current labels, but a template label is often predictable from the template alone.
- **Labels drift over time.** Labels on closed issues reflect the whole issue lifetime, including relabelling after discussion the agent never saw. The label set is today's, not the one at the time the issue was opened.
- **Unmarked duplicates count against the agent.** If maintainers never marked an issue as a duplicate, `duplicate_of: null` is the expected answer even when the issue really was one. An agent that finds a true but unmarked duplicate is scored wrong.
- **Duplicates with no findable target are dropped.** This biases the set towards duplicates that maintainers bothered to link.
- **Selection is biased.** Only issues that were closed and labelled are included. Open, unlabelled and deleted issues are not. That favours issues that were easy to triage.
- **Search sees today's index.** `search_similar_issues` uses GitHub's current search index, restricted to issues created before the triaged one. Titles may have been edited since, and search ranking is not what it was then.
- **The reply is not checked.** A rude or wrong reply passes. A partner check would need a rubric for it, and no model judge is used in M1.
- **There is no severity.** All tools are read-only (S0) and nothing is posted. Every wrong result is an S0 wrong output.
