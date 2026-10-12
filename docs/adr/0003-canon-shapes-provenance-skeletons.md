# 0003. Shapes, provenance and skeletons (M1.2)

Date: 2026-10-12
Status: accepted

## Context

ANNEAL-ROADMAP.md M1.2 specifies the shape tokens, the provenance strategies and the skeleton definition, but leaves several choices open. They decide what M1.3 counts as `removable`, so they are recorded here.

## Decision

**Shapes** (`anneal.canon.shape`)

- String classes are checked in this order: redaction placeholder (`ph:<TYPE>`), `email`, `url`, `uuid`, `date` (ISO date or datetime), `numstr`. Then `enum`, then `str[<len bucket>]`.
- `enum` needs at least 20 string observations at a `(context, wildcard path)`. The values that recur (seen twice or more) must number at most 20 and cover at least 95% of observations. The roadmap's "20 or fewer distinct values with 95%+ coverage" was read as requiring recurrence; otherwise any field seen in a handful of runs, or a field of unique identifiers sampled up to 20 times, would qualify. The thresholds are module constants and remain HYPOTHESIS until real traces are seen.
- Objects become sorted keys *with* child shapes. Arrays become the union of element shapes plus a length bucket.
- Coarse shapes drop string and array length buckets.

**Provenance** (`anneal.canon.provenance`)

- **Sources:** the run input, earlier tool results, and earlier model `output_text`. The requesting model's tool-call arguments are excluded, because they are the target itself. Model text is a source so that "output text flows into later args" (the `judgment` class) is visible as an edge with `from_kind: model`.
- **Never matched:** booleans, nulls and empty strings. Two `true` values agreeing is not evidence.
- **Tie-breaking:** strategies are tried in roadmap order, and the first strategy with any hit wins. Within it, the most recent source wins, then a source whose last key equals the argument's key. `ambiguous` is set whenever more than one source matched, so M1.3 can treat ambiguous bindings conservatively.
- **Transform names:** normalization reports the template transform that reproduces the value (`trim`, `lower`, `trim|lower`). `normalize` means only case- and whitespace-insensitive equality held, so no template transform reproduces it.
- **Concatenation:** parts are at least 2 characters and joined by one separator from a fixed list. The search is limited to the 30 most recent candidate parts.
- **Constants:** a leaf with the same value in every run is not detected here; that is a cross-run property for the M1.3 classifier.

**Skeletons** (`anneal.canon.skeleton`)

- **Coarse shapes** are used, so free-text and list lengths do not split clusters. Placeholder types are kept, since they are stable across runs.
- **Model steps** are `("model", role, "", outcome)`. `role` is the event's `scope`, else `sys:<system_hash>`, else `model`. `outcome` is `calls:<sorted tool names>`, `text`, both joined by `+`, or `empty`. Tool steps use `error` as the result token when the tool failed.
- **Deopt events** are not structure and are left out.
- **Clustering:** near-duplicates are compared over *distinct* skeletons with `difflib.SequenceMatcher` (autojunk off) and joined transitively. The cluster's representative and id is its most common skeleton.

## Consequences

- Short identifiers embedded in free text (for example `"1234"` in a ticket) are `model_generated`. The substring threshold (6) is deliberate, and such arguments land in `constrained`, not `removable`.
- Transitive joining can chain dissimilar skeletons through intermediates. M1.3 reports per-cluster alignment, so this will show up in numbers rather than silently.
