# Setup timing for the compiled arm (H4 build time)

H4 compares how long it takes to get a compiled path against how long the handwritten baseline took (ADR 0010). The baseline's time is in its `BUILD_LOG.md`. The compiled arm's build time is the human work below plus compile compute. Until this file has real entries for a workflow, H4 build time for that workflow stays **open**.

## Rules

- **Timing:** use a stopwatch and record wall-clock time, timed the same way as the baseline: from opening the material to the artefact being done and reviewed.
- **Interruptions:** pause the stopwatch for interruptions and do not count them. Write down that they happened.
- **Scope:** time only what the compiled arm needs that the baseline does not already get for free. Both arms get the traces and the brief.
- **Changes:** one row per sitting. If the artefact is changed later, add a new row; do not edit an old one.
- **Estimates:** never enter one. Leave the row out if it was not timed.

## Artefacts

| Artefact | What it is |
| --- | --- |
| Tool declarations | `side_effect`, `severity`, and `idempotent` / `reconcile` for every tool the plan uses (the `--tools` YAML) |
| Task check | the per-workflow function that decides "job done", plus its written rubric |
| PARTNER.md | the scoping note: workflow, owner, task-check agreement, severity assignments, budgets |

## Entries

| Date | Workflow | Artefact | Who | Minutes (stopwatch) | Interruptions | Notes |
| --- | --- | --- | --- | ---: | --- | --- |
| | | | | | | |

## Totals per workflow

Filled in from the entries, not estimated.

| Workflow | Tool declarations | Task check | PARTNER.md | Compile compute | Total | Baseline (BUILD_LOG.md) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| | | | | | | |
