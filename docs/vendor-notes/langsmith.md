# LangSmith

Pinned and checked on 2026-10-12:

- `langsmith` 0.14.7: export record schema `langsmith.schemas.Run`
- `langchain-core` 1.6.10: shape of LangChain message payloads
- Docs: https://docs.smith.langchain.com/ (run data format, `Client.list_runs`)

Anneal does not depend on either package. The importer parses plain JSON, and the SDK is used only to validate the test fixture
(`uv run --with langsmith==0.14.7 python tests/fixtures/traces/langsmith/make_fixture.py`).

## What the importer expects

JSONL with one `langsmith.schemas.Run` record per line, flat and in any order. All runs of a trace are included, children too. For example:

```python
from langsmith import Client

with open("export.jsonl", "w") as f:
    for run in Client().list_runs(project_name="my-project"):
        f.write(run.json() + "\n")
```

LangSmith's bulk data export writes Parquet, not JSONL. Supporting it is deferred until a partner needs it (roadmap rule 7).

## Record fields used

| Field | Use |
| --- | --- |
| `id`, `trace_id`, `parent_run_id`, `dotted_order` | grouping, ordering (`dotted_order` sorts depth-first by start time) and nesting |
| `run_type` | `llm` → ModelCall; `tool`, `retriever` → ToolCall; anything else is structure only |
| `name` | tool name; for `chain` runs, the `scope` of the events below them; for the root, the default `workflow_id` |
| `start_time`, `end_time` | ISO 8601. LangSmith returns naive UTC; naive values are read as UTC |
| `status`, `error` | run status; tool error text |
| `prompt_tokens`, `completion_tokens`, `prompt_token_details.cache_read` | token counts, filled server-side |
| `total_cost` | Decimal, serialized as a number or a string; kept as the source's cost |
| `extra.metadata.ls_provider`, `extra.metadata.ls_model_name` | provider and model |
| `extra.tool_call_id` | links a tool run to the model's tool-call request |

## Payload shapes observed

These were captured on 2026-10-12 by tracing a fake tool-calling agent through `LangChainTracer` and `wrap_openai`, with a capturing client and no network.

**LangChain chat model (`run_type: llm`)**

- `inputs.messages` is a batch: a list containing one list of serialized messages (`{"lc": 1, "type": "constructor", "id": [..., "HumanMessage"], "kwargs": {"type": "human", "content": ...}}`).
- `outputs.generations[0][0].message` is a serialized `AIMessage`. Its `kwargs` include `content`, `tool_calls` (`{name, args, id, type: "tool_call"}`, with `args` already a dict), `usage_metadata` (`input_tokens`, `output_tokens`, `input_token_details.cache_read`) and `response_metadata.model_name`.
- `usage_metadata` is also copied to `extra.metadata.usage_metadata`.

**`wrap_openai` (`run_type: llm`)**

- `inputs` is the request: `messages` (`{role, content}`), `model`, `tools`.
- `outputs` is the ChatCompletion: `choices[0].message` with `tool_calls[].function.arguments` as a **JSON string**. Usage arrives as `usage_metadata` in LangChain's normalized form.

**Tool (`run_type: tool`)**

- `inputs` is the args dict when the tool was invoked from a tool call.
- `outputs.output` takes one of three forms:
  - a serialized `ToolMessage` (content in `kwargs.content`);
  - a plain value;
  - a Python repr string, `content='...' name='...' tool_call_id='...'`. The tracer records this when the tool returns a `ToolMessage` object. The importer parses the repr with `ast.literal_eval` on the quoted content only.
  - a plain message dict, `{"type": "tool", "content": ..., "tool_call_id": ...}`. This is what langsmith 0.14.8 records for LangGraph's `ToolNode`. Seen on 2026-10-13 in real dogfood traces; the synthetic fixture never produced it.
- String content that parses as a JSON object or array is decoded.

## Token convention

`ModelCall.tokens_in` includes cached tokens, and `tokens_cached` is the subset. That matches OpenAI's `prompt_tokens` and LangChain's `usage_metadata.input_tokens`. Anthropic's raw API counts cache reads separately from `input_tokens`, but LangChain normalizes them into the total.

## Seen in real exports (2026-10-13, langsmith 0.14.8)

- **`Client.list_runs` is deprecated.** It warns: "removed after Jan 31, 2027; use `client.runs.query()`". The example exporter still uses it, and has to move before that date.
- **Exports are large.** Every `llm` run carries the whole message history in `inputs`. 200 triage traces of about 6 model calls each came to 93 MB of JSONL. Exporting one trace at a time (`list_runs(trace_id=...)`) took about 10 minutes for 360 traces.
- **Re-run issues appear twice.** An interrupted runner re-traces in-flight inputs. The example exporter keeps the latest finished trace per input.

## Not handled yet

- Embedding runs: skipped as structure, so their cost is not counted.
- Streaming chunk events (`events`).
- Attachments.
- The Parquet bulk export.
- Message `content` arrives as provider blocks (lists) and is kept as-is; `output_text` joins only the text blocks.
