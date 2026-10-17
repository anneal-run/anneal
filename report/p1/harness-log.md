# Harness log

The first attempt, on open_deep_research, is the section below the rule. It did not reach a harness. The rerun is the section above the rule. Onboarding for the rerun started when the repository was cloned, at 2026-10-16T23:07:02Z, and is not harness time. The harness clock starts at the first `anneal challenge harness` command.

## Rerun, tabletalk

Wall clock started: 2026-10-16T23:15:45Z
Wall clock ended: 2026-10-16T23:16:04Z, when `make harness` printed `answered` and exited 0.
Wall clock: 19 seconds.

| start (UTC) | minutes | intervention |
|---|---|---|
| 2026-10-16T23:15:50Z | 0.18 | `make harness` failed because the generated Makefile runs `python` and this machine has `python3`. Added a `python` symlink on `PATH` and reran the same target. The rerun started at 2026-10-16T23:16:01Z. |

Manual share: 0.18 / 0.32 = 58%. The share is high because the harness command itself finished in the same second and the only hand edit was the interpreter name.

Reading the repository, installing it, and downloading its databases happened before 2026-10-16T23:15:45Z. That is onboarding. Capture time and capture cost are in report/p1/results.md, not in this share.

## After the harness clock

These are not part of the H1 share.

| start (UTC) | minutes | intervention |
|---|---|---|
| 2026-10-16T23:18:55Z | 0.1 | The first engine session returned HTTP 400 (`context_management` was not accepted). The proxy was changed to forward the beta header. |
| 2026-10-16T23:19:30Z | 4 | The second session sat idle with no files written. It was stopped. |
| 2026-10-16T23:26:00Z | 1 | A session on `claude-opus-4-8` was stopped. That model is not in the price table, so the meter could not cap it. The session that finished used `claude-sonnet-4-5`. |
| 2026-10-16T23:30:53Z | 0 | Scoring injected the environment key in place of the mock key hardcoded in the four submissions. The submission files were not rewritten. |

---

## First attempt, open_deep_research

Wall clock started: 2026-10-16T22:53:11Z
Wall clock ended: 2026-10-16T22:57:10Z
Wall clock: 4 minutes. Manual share: 100%. No harness was written. The import failed on a file that is not a LangSmith export.
