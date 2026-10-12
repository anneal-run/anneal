# 0002. Trace schema v1 details

Date: 2026-10-12
Status: accepted

## Context

ANNEAL-ROADMAP.md M1.1 fixes the field list of `Run`, `ModelCall`, `ToolCall` and `Deopt` as a CONTRACT. Implementing that list required decisions it doesn't spell out. This ADR records them so later changes go through review.

## Decision

- **Event identity and nesting.** Every event has `event_id`, `parent_id`, `ts` and a `kind` discriminator (`model_call`, `tool_call`, `deopt`). `parent_id` is the nearest enclosing *event*, not the nearest source span: a model call inside an agent-as-tool points at the tool call, and chains are never events.
- **`scope`** (additive). Each event carries the name of its nearest enclosing agent or graph node. A handoff is otherwise invisible: the same tool name inside two agents would look identical to skeleton hashing and classification.
- **`tool_call_id`** (additive). Each `ToolCall` carries the id of the model's request that triggered it, so provenance and history reconstruction (M1.6) can pair a request with its result.
- **Messages are typed.** `Message` has `role` (system, user, assistant, tool), `content` kept as the provider gave it, `tool_calls`, `tool_call_id` and `name`. `ToolCallRequest.args` is a dict, or the raw string when the model emitted invalid JSON. That string is kept as evidence and never repaired.
- **Tokens.** `tokens_in` includes cached tokens, and `tokens_cached` is the subset.
- **`system_hash`** is the first 16 hex characters of the SHA-256 of the system messages, computed before redaction. Computing it after redaction would make the hash depend on placeholder numbering, which varies by run.
- **Timestamps** must be timezone-aware. Importers convert naive source values, documenting the assumed zone in vendor notes.
- **Unknown at import.** `side_effect`, `severity` and `idempotency_key` are None on import. They are declared at scoping (M1.7), never inferred from traces.
- **Models are frozen** and reject unknown fields. `schema_version` is `Literal[1]`, so a v2 file fails loudly.
- **Redaction.** One `Redactor` runs per run, so placeholders are equal within a run and unlinkable across runs. Equality uses a normalized key: emails ignore case, numeric identifiers ignore separators. That keeps provenance matching (M1.2) working through reformatting. The store redacts on every write; nothing else writes runs to disk.
- **Store.** Runs are written to `<root>/<workflow_id>/<YYYY-MM-DD>.jsonl` (UTC date), append-only, with the last write winning per `run_id`. pandas is not added until `anneal analyze` (M1.3) needs it.

## Consequences

- Changing any of the above needs an ADR, under rule 4.
- Cost of embedding calls and cache-write surcharges are not yet counted (see docs/vendor-notes/langsmith.md and `pricing.yaml`). Spend shares in M1.3 slightly understate total spend for workflows that use them.
