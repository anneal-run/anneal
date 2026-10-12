# 0004. Classify at prefix-tree positions; add `anneal import`

Date: 2026-10-12
Status: accepted

## Context

M1.3 defines `removable` as "tool choice is the same at this position in 95%+ of runs". The obvious reading measures it inside the M1.2 skeleton clusters. That is wrong. A skeleton includes every later step, so runs that branch differently (auto-reply vs escalate) land in different clusters, and within each cluster the branching choice is 100% stable. The classifier would mark a real model decision as `removable`, and H2 would be overstated by construction. The synthetic generator showed this: a 58/42 routing decision split into two skeleton clusters of 35 and 25 runs.

## Decision

- **Position.** A position is a node of the prefix tree over all runs of the workflow: model calls whose earlier steps are identical and whose role (`scope`, else `sys:<system_hash>`) is the same. Steps are `("model", role, outcome)` and `("tool", name, ok|error)`. Choice stability is measured only over runs that reached that node; later steps never influence it. Positions are identified by a 12-hex blake3 hash of `(prefix, role)`.
- **Classification rules** (first match wins), documented in `anneal/classify/classifier.py`: terminal, low support, choice varies (or off the dominant choice), text flows into later args, text output, then argument bindings.
- **Argument bindings.** A `tool:path` is reproducible when one binding signature (source step index or input, source path, transform, detail) holds in at least 95% of the dominant calls, or when the model wrote the same value in every one of them (a constant). Otherwise the call is `constrained` (`args_model_generated` or `args_inconsistent`). Consistency is required because M1.4 needs one template per argument.
- **Terminal.** The run's last top-level model call that requests no tool.
- **Minimum support.** 5 runs per position, the same figure the roadmap uses for subsequence mining. Below it, calls are `judgment` (`low_support`). The threshold and the 95% share are HYPOTHESIS and are printed in every report.
- **Skeleton clusters** (M1.2) are still used for "run coverage by skeleton" (H1). They are no longer used for classification.
- **Measured deltas.** `anneal analyze --deltas` takes JSON keyed by position id, of the form `{"<position_id>": {"original_usd": x, "constrained_usd": y}}`. Saving is `spend * (1 - y/x)` for that position's constrained calls. Positions without a delta contribute nothing, as M1.3 requires.
- **CLI contract.** `anneal import langsmith <file> --store <dir>` is added to the CLI list. `anneal analyze <store>` reads a store, and without an import command there was no way to fill one.

## Consequences

- Branching workflows show lower `removable` shares than a skeleton-cluster reading would. That is the honest number.
- Deep prefix trees fragment support: a minority branch early on splits every later position. M2.2's `branch` step and subsequence mining address this. Until then, low-support positions are reported, not compiled.
