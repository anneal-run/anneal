# Baseline brief: `env_support`

You are the baseline arm of a three-way comparison (ANNEAL-ROADMAP.md M1.8). Write this workflow as a plain Python script, the way a competent engineer would replace an agent with code. The other arms are the original agent and a compiled path. Your script is the thing they must beat, so make it good: correct, cheap, and safe.

**Time box: one working day.** Log what you actually spend.

## What you get

- `traces.jsonl`: 56 recorded runs of the current agent, one JSON object per line (`input`, `output`, `events`, where events are model calls and tool calls with arguments and results). These are the same runs the compiler sees.
- `interface.py`: what your `run` receives (`Tools`, `Model`, `ToolError`).
- This brief, which is the task definition the business agreed to.

Do **not** read anything outside `baseline/env_support/`. In particular, do not read `src/` or `tests/`, which hold the compiler and the simulator. A real engineer would have the traces and the task definition, nothing more.

## The task (the agreed definition of "job done")

A customer writes in. The input has their email, a free-text message and a priority. The job is done when exactly these writes happen, once each, and no others:

- **Order problem** (the usual case):
  - a ticket is created for the customer the email belongs to;
  - the ticket is routed: `escalate` for urgent cases (high priority, or a gold-tier customer), `auto_reply` otherwise;
  - a reply email is sent to the customer's address.
- **Anything else** the business may start receiving must not be treated as an order problem. The traces only contain order problems. Handle what you can justify from the traces and this brief.

`lookup_customer` is a read and may be called freely. The output is `{"answer": "<closing text>"}`.

## Tools (via `tools.call(name, args)`)

| tool | args | result | kind |
| --- | --- | --- | --- |
| `lookup_customer` | `email`, `include` (`"tier"`) | `{"customer_id", "tier"}`; raises `NotFound` for unknown emails | read |
| `create_ticket` | `customer_id`, `summary` | `{"ticket_id"}` | write |
| `auto_reply` / `escalate` | `ticket_id` | `{"ok": true}` | write |
| `send_email` | `to`, `body` | `{"sent": true}` | write |

There may be other tools you do not know about. Do not call tools that are not in this table.

## The model (`model`, see `interface.py`)

Use it where judgment or text is needed: `read`, `summarize`, `choose`, `write`. Each call costs $0.015, and cost per task is one of the three things you are measured on. Deterministic code costs nothing.

## Deliverables (all in `baseline/env_support/`)

1. `workflow.py` with `def run(run_input: dict, tools: Tools, model: Model) -> dict`.
2. `test_workflow.py`: pytest tests with your own fakes for `Tools` and `Model`. Cover the usual case, the routing rule, and what your script does with inputs it was not built for. Run them with `uv run pytest baseline/env_support -q`.
3. `BUILD_LOG.md`: start and end time, time spent, what you needed and where it came from, assumptions you made, and anything you would ask the business.

You are measured on build time, cost per task, task success on later runs, and behaviour when inputs drift. On drift, failing loudly (raising) is better than silently doing the wrong thing. Write to the standard you would ship.
