# BUILD_LOG: env_support baseline

- Start: Tue Oct 13 09:04:23 IDT 2026 (from `date`)
- End: Tue Oct 13 09:06:09 IDT 2026 (from `date`)
- Time spent: 1 min 46 s wall-clock (agentic engineer working only from BRIEF.md, interface.py and traces.jsonl)

## What I needed and where it came from

| Need | Source |
| --- | --- |
| Definition of done (3 writes, once each), routing rule, output shape | BRIEF.md |
| Tool names/args/results, `NotFound` behaviour | BRIEF.md tool table, interface.py |
| Input shape (`email`, `message`, `priority`) | traces: all 56 inputs have exactly these keys |
| Priority values `low/normal/high`, tier values `bronze/silver/gold` | traces |
| Routing: `escalate` iff priority `high` or tier `gold` | BRIEF.md, confirmed against all 56 traces (28 escalate / 28 auto_reply, 0 exceptions) |
| Call order: lookup -> create_ticket -> route -> send_email | traces (one sequence in all 56 runs) |
| Ticket summary `Customer reports <problem>` from `My order N has a problem: <problem>` | traces (all 56) |
| Reply body `Hello, about ticket <T>: we are on it.` and answer `Done: ticket <T> handled.` | traces (all 56, fixed templates) |

## Design

- Usual run: **0 model calls**, 4 tool calls (1 read, 3 writes). The agent spent 6 model calls ($0.09) per run for things that are fully deterministic in the traces.
- All reads and checks happen before the first write. Writes are never retried, so a failure can't produce duplicate tickets or emails. A mid-way failure raises with the step name.
- Drift handling:
  - Input without the three expected keys: `model.read` (1 call), then the same strict validation. Extra keys next to the expected three are ignored.
  - Invalid email, or a priority outside `low/normal/high` (e.g. `urgent`): raise `WorkflowError` before any tool call. I do not guess what `urgent` maps to.
  - Unknown customer (`NotFound`) or a tier outside `bronze/silver/gold`: raise before any write.
  - A message not in the known order-problem phrasing: `model.choose(["order_problem", "not_order_problem"])` (1 call). Not an order problem (or any unexpected answer): raise `NotOrderProblem`, no writes. Order problem: `model.summarize` for the ticket summary (1 more call) and the normal flow.
  - Malformed tool results (no `ticket_id`, `ok` not true, `sent` not true): raise.
- Only the four tools in the brief plus `lookup_customer` are ever called.

## Assumptions

- The reply email and closing answer can be fixed templates. The traces show exactly these strings every time, and the brief doesn't ask for personalised text.
- Case and surrounding whitespace in priority and tier don't matter (`High` = `high`).
- `send_email` goes to the input email, which is also the address used for the lookup (as in all traces).
- A non-order message should be refused loudly (raise), not handled with some other set of writes. The brief defines no other job, and failing loudly is preferred.
- Tool exceptions may not be the `interface.ToolError` class itself, so any exception from a tool is caught, wrapped and re-raised as `WorkflowError`.

## Questions for the business

1. What should happen to non-order messages (refund requests, account questions, spam)? A human queue? A different ticket type? Right now they raise.
2. Are there priorities other than low/normal/high (e.g. `urgent`, `critical`)? Should they count as urgent?
3. Are there tiers other than bronze/silver/gold (e.g. `platinum`)? Should they escalate?
4. Do you want a real, personalised reply email? It would cost 1 model call (`write("reply")`) per run, versus the current fixed acknowledgement.
5. Unknown sender email: should we still reply ("we couldn't find your account") or just drop it? Right now it raises with no writes.
6. If a write fails mid-way (e.g. the ticket is created but routing fails), who cleans up? Is any write idempotent so it is safe to retry?

## Tests

`uv run pytest baseline/env_support -q -p no:cacheprovider --no-cov`: 31 passed. They cover the usual case (exact calls, 0 model calls), a replay of all 56 traces (identical tool calls and outputs), the full priority x tier routing matrix, and drift: unknown priority, tier or customer, invalid email, non-dict input, non-order messages, rephrased order problems, renamed input fields, bad `model.read` output, and tool failures or malformed results mid-way.
