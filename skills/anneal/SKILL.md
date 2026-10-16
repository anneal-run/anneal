# Anneal

Build a harness for one workflow, run an isolated proposer, and open a pull request only if the holdout can support the verdict. Do this in the partner's repository. Do not deploy anything.

## Before any session

1. Import the LangSmith export into a local store: `anneal import langsmith <export.jsonl> --store .anneal/store`.
2. Declare tools in `tools.yaml`. A read-only tool is `side_effect: false`. A tool that posts, writes, or deletes is `side_effect: true`.
3. Build the harness, and stop if this command fails. The holdout is sealed here, before any proposer runs:

```sh
anneal challenge harness .anneal/store \
  --tools tools.yaml \
  --workflow <workflow_id> \
  --out harness/ \
  --file <path-to-the-workflow> \
  --entrypoint '<command that runs one case>'
```

`harness/SEAL.json` lists the holdout run ids. `harness/fixtures.jsonl` is the optimization split only. Read-only tools are live. Side-effecting tools with recorded calls are replayed. A side-effecting tool with no recording is marked mock in `manifest.json`, and a candidate that only passes on mocks is disqualified.

4. Start `report/harness-log.md` before the next command:

```markdown
# Harness log

Wall clock started: <UTC timestamp>

| start (UTC) | minutes | intervention |
|---|---|---|
```

Every time a person edits a file, answers a prompt, or restarts a failed command by hand, add a row with the duration. A command that ran unattended is not a row. Manual share is the sum of those minutes divided by the wall clock. This is the H1 measurement.

## Engine

Write `budget.json` as `{"candidates": 4, "dollars": 20, "hours": 6}` unless the partner sets a tighter cap.

```sh
anneal challenge pack \
  --source . \
  --harness harness \
  --out pack/ \
  --arm C \
  --p0 \
  --budget budget.json
```

`--p0` omits the architecture menu. The pack's `PROMPT.md` is the whole instruction: caching, a model swap, and a prompt edit are not architectures; at least three structurally different candidates; each structural candidate falls back to the original implementation. The fallback must call that implementation, and those calls count in cost. Confidence comes from the candidate's own output or from agreement with a second cheap pass, never from labels. The submission reports `fallback_rate` beside cost.

Run the proposer in `pack/` only. A session that has read the rest of the repository is void. The pack does not contain `SEAL.json`, `report/`, or `baseline/`.

## Evaluator

Score with the power check on. Pass `--require-fallback`.

```sh
anneal challenge orchestrate \
  --budget budget.json \
  --baseline baseline.jsonl \
  --submissions pack/submissions \
  --holdout holdout.json \
  --require-fallback \
  --labeling-hours <hours spent labeling, else 0> \
  --out report/verdict.md
```

The command prints the minimum detectable effect. If the holdout cannot support the 2-point correctness margin, the only output is `cannot adjudicate; n required: N` and there is no winner. Do not lower the margin.

A scored candidate has three verdicts: compatible, correct, worth it. The split is chronological. Overfit and mock-only candidates are disqualified. A prompt, cache, or model change is reported and is never the structural winner. Use a downstream signal as the label when the workflow has one. Otherwise label a set by hand and log the hours in the harness log and as `--labeling-hours`.

## Pull request

Only after a verdict names a structural winner:

```sh
anneal challenge pr \
  --workflow <workflow_id> \
  --winner <candidate id> \
  --verdict report/verdict.md \
  --fixtures harness/fixtures.jsonl \
  --out pr/
```

`pr/PR.md` puts the winner behind `ANNEAL_<WORKFLOW>`, leaves the original implementation on the path, points at the fixtures, links the verdict, and says nothing deploys. `pr/rollback.md` is the rollback note: unset the flag. Open that as a pull request in the partner's repository. Do not merge it from this skill, and do not deploy it.
