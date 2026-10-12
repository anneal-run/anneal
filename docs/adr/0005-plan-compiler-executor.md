# 0005. WorkflowPlan v0, the Tier 1 compiler and the executor (M1.4)

Date: 2026-10-12
Status: accepted

## Context

ANNEAL-ROADMAP.md M1.4 fixes the plan's contract fields, the three M1 step types and the template language. It leaves open:
- how the dominant path is chosen;
- what an `llm` step asks the model for;
- how a branch that the plan does not follow is detected;
- what the executor does with writes it may not perform.

## Decision

**Dominant path.** Walk the prefix tree from the root, taking the most common next step each time, until the most common continuation is "end of run". Every node needs `min_support` runs, otherwise nothing is compiled. Bindings are computed only from the runs that follow the path exactly (`compiled_from`).

**Steps per model call.** The mapping follows the M1.3 class (rules in `anneal/compile/compiler.py`):
- `constrained` steps ask only for the *top-level* arguments the model wrote. Bound arguments stay templated, so the model cannot get them wrong.
- A `judgment` step that chooses a tool returns `{tool, arguments}`, with `expected_tool` set to the path's tool. Any other choice deopts. This is how "a cluster that branches is compiled only along its dominant path and other paths fall back" is enforced at run time.

**Bindings to templates.** Only `exact`, `trim`, `lower`, `trim|lower`, `date` (to `fmt_date` with the one format that reproduces every run) and `concat` are expressible. `number`, `substring`, `normalize` and embedded `json` are refused, each with a log line naming the position, tool and path.
- Inconsistent bindings (agreeing in fewer than 95% of runs) are refused the same way.
- A refused argument is asked of the model, unless an override template is supplied for `<position_id>:<tool>:<path>`. An override is stored in the plan as a `ManualOverride`, which is the automation debt M2.2 clears.
- Model-written values that are identical in every run become literals.
- A `tool` step is never emitted with an unbound argument.

**Unsupported in M1, compiling nothing (logged):**
- a tool call not requested by a model;
- parallel tool calls in a judgment step;
- more than one tool in one call needing model-written arguments;
- a run output that does not bind.

**LLM prompts.**
- The system template is the most common system prompt at that position; a varying prompt is logged.
- The user template shows the run input and every earlier step's result, then the instruction.
- Replay (M1.5) is where prompt quality is measured; nothing here claims it is good enough.

**Guards.** One `schema` guard for every input path a template reads, typed from the compile runs. Enum, range, length and pattern guards exist in the executor and are mined in M1.8 and M2.3.

**Undeclared tools** get `side_effect=True, severity=S2, idempotent=False` and a log line.

**Executor.**
- **Order:** steps run in dependency order (templates define the edges). Ties keep plan order.
- **Deopt** on:
  - a guard failure;
  - a tool error;
  - a template error;
  - a schema-invalid llm output after one retry (the retry carries the validation errors as feedback);
  - an off-path tool choice;
  - and **before** any tool whose severity is not live (default S0 only). Skipping a write instead would let a plan report success for an action it never took.
- **Trace:** every execution is a `Run` with `tier=1` and `source="anneal"`. A deopted trace has status `pending`, because the run continues in the original agent.
- **Runners:** tool and LLM runners are callables passed in. Provider adapters belong to the M2 SDK.

**Additive fields:** `LlmStep.role` and `expected_tool`, `WorkflowPlan.plan_version`, `compile_log` and `manual_overrides`. `plan_id` is the first 16 hex characters of the blake3 hash of the plan's canonical JSON without `plan_id`. The registry refuses to load a plan whose content no longer matches its id.

## Consequences

- A judgment step that chooses between tools still costs a model call on every run, and deopts on the minority branch. Savings come only from removable calls and measured constrained deltas, as M1.3 requires.
- `constrained` calls whose model-written argument is copied from an earlier model's text (the synthetic `send_email(body=<draft>)`) could bind to that step's output instead of asking again. That is left as M2 work, so the classifier and the compiler keep agreeing on what is constrained.
