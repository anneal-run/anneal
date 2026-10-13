"""Tier 1 compiler: the dominant path of a workflow to a `WorkflowPlan`.

The dominant path is the most common full step sequence, found by walking the
prefix tree and taking the most common next step at each node. Only runs that
follow it exactly (`compiled_from`) are used for bindings; other paths fall
back at run time. Every node on the path needs `min_support` runs.

Per model call on the path, by its class (ANNEAL-ROADMAP.md M1.3):

- `removable` → `tool` steps with templated arguments;
- `constrained` → an `llm` step with the tool forced, asking only for the
  top-level arguments the model wrote, then the `tool` step;
- `judgment` choosing a tool → an `llm` step returning `{tool, arguments}` with
  `expected_tool` set to the path's tool (any other choice deopts), then the tool;
- `judgment` writing text, and `terminal` → an `llm` step returning `{text}`;

then an `end` step built from the run output's bindings.

A binding becomes a template only when the template language can express it
(exact, trim, lower, date re-format, concat) and it holds in `stable_share` of
the runs. Anything else is refused with a log line naming it, and the argument
is asked of the model instead, unless an override template is supplied for
`<position_id>:<tool>:<path>`, which is recorded as a `ManualOverride`. A `tool`
step is never written with an unbound argument.
"""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from anneal.canon.dates import DATE_FORMATS, parse_dates
from anneal.canon.provenance import provenance
from anneal.canon.shape import leaves, split_path
from anneal.canon.skeleton import skeleton, skeleton_hash
from anneal.classify import classify
from anneal.classify.classifier import (
    MIN_SUPPORT,
    STABLE_SHARE,
    RunView,
    Step,
    leaf_signature,
    position_id,
    requested_tools,
    run_view,
)
from anneal.compile.plan import EndStep, Guard, LlmStep, ManualOverride, ToolStep, WorkflowPlan
from anneal.compile.template import input_paths
from anneal.schema import ModelCall, Run, Severity, ToolCall

_EXPRESSIBLE = {
    "exact": "",
    "trim": " | trim",
    "lower": " | lower",
    "trim|lower": " | trim | lower",
}
_END: Step = ("end", "", "")


class ToolSpec(BaseModel):
    """A tool's declaration. Defaults are the most cautious: an irreversible side effect."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    side_effect: bool = True
    severity: Severity = "S2"
    idempotent: bool = False
    """Accepts an operation key and treats a repeat under it as a no-op."""
    reconcile: bool = False
    """A `reconcile(key)` hook will be registered with the executor."""


@dataclass
class CompileResult:
    plan: WorkflowPlan | None
    log: list[str] = field(default_factory=list)


class _Refused(Exception):
    pass


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _value_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, dict):
        return _object_schema({k: _value_schema(v) for k, v in value.items()})
    if isinstance(value, list):
        return {"type": "array", "items": _value_schema(value[0]) if value else {}}
    return {"type": "null"}


def _json_type(values: list[Any]) -> str | None:
    kinds = {_value_schema(v)["type"] for v in values}
    if kinds == {"integer", "number"}:
        return "number"
    return kinds.pop() if len(kinds) == 1 else None


def _ref_path(path: str) -> str:
    """A provenance path (`$.a[0]`) as a template path suffix (`.a[0]`)."""
    return path[1:]


def _top_key(path: str) -> str | None:
    """The top-level argument key a leaf path sits under, or None for a non-object argument."""
    keys = split_path(path)
    return keys[0] if keys and isinstance(keys[0], str) else None


def _set_path(target: Any, path: str, value: Any) -> Any:
    """A copy of `target` with the leaf at `path` replaced."""
    keys = split_path(path)
    if not keys:
        return value
    root = json.loads(json.dumps(target))
    node = root
    for k in keys[:-1]:
        node = node[k]
    node[keys[-1]] = value
    return root


@dataclass
class _Builder:
    views: dict[str, RunView]
    supporting: list[RunView]
    tools: dict[str, ToolSpec]
    overrides: dict[str, Any]
    stable_share: float
    log: list[str]
    call_classes: Mapping[str, str]
    path: list[Step] = field(default_factory=list)
    steps: list[ToolStep | LlmStep] = field(default_factory=list)
    step_of_index: dict[int, str] = field(default_factory=dict)
    manual: list[ManualOverride] = field(default_factory=list)

    def next_id(self) -> str:
        return f"s{len(self.steps)}"

    def tool_spec(self, name: str) -> ToolSpec:
        if name not in self.tools:
            self.log.append(
                f"tool {name}: undeclared, treated as side_effect=True severity=S2 idempotent=False"
            )
            self.tools[name] = ToolSpec()
        return self.tools[name]

    def tool_step(self, name: str, args_template: Any, index: int) -> ToolStep:
        spec = self.tool_spec(name)
        step = ToolStep(
            id=self.next_id(),
            name=name,
            args_template=args_template,
            side_effect=spec.side_effect,
            severity=spec.severity,
            idempotent=spec.idempotent,
            reconcile=spec.reconcile,
        )
        if spec.side_effect and not (spec.idempotent or spec.reconcile):
            self.log.append(
                f"tool {name}: shadow_only (side effect, no idempotency key, no reconcile hook); "
                "a compiled path deopts before it"
            )
        self.steps.append(step)
        self.step_of_index[index] = step.id
        return step

    def user_template(self, instruction: str) -> str:
        lines = ["Run input:", "{{input}}"]
        for s in self.steps:
            label = s.name if isinstance(s, ToolStep) else f"model {s.role}"
            lines += ["", f"Result of step {s.id} ({label}):", f"{{{{steps.{s.id}.result}}}}"]
        return "\n".join([*lines, "", instruction])

    def llm_step(
        self,
        index: int,
        calls: list[ModelCall],
        role: str,
        schema: dict[str, Any],
        instruction: str,
        forced_tool: str | None = None,
        expected_tool: str | None = None,
    ) -> LlmStep:
        systems = Counter(
            "\n".join(str(m.content) for m in c.messages if m.role == "system") for c in calls
        )
        system, n = systems.most_common(1)[0]
        if n < len(calls):
            self.log.append(f"step {self.next_id()}: system prompt varies; using the most common")
        models = Counter(c.model for c in calls if c.model)
        step = LlmStep(
            id=self.next_id(),
            role=role,
            model=models.most_common(1)[0][0] if models else None,
            system_template=system,
            user_template=self.user_template(instruction),
            output_schema=schema,
            forced_tool=forced_tool,
            expected_tool=expected_tool,
            position_id=position_id(self.path[:index], role),
        )
        self.steps.append(step)
        self.step_of_index[index] = step.id
        return step

    def leaf_template(self, signature: tuple[Any, ...], values: list[Any]) -> Any:
        """Template for one leaf binding, or raise `_Refused` with the reason."""
        refs = []
        for kind, index, path, transform, detail in signature[1]:
            if kind == "input":
                ref = f"input{_ref_path(path)}"
            else:
                sid = self.step_of_index.get(index) if isinstance(index, int) else None
                if sid is None:
                    raise _Refused(f"source step {index} is not on the plan")
                suffix = ".text" if kind == "model" and path == "$" else _ref_path(path)
                ref = f"steps.{sid}.result{suffix}"
            refs.append((ref, transform, detail))
        if refs[0][1] == "concat":
            sep = refs[0][2] or ""
            return "{{concat(" + ", ".join(r for r, _, _ in refs) + f", sep={sep!r})}}}}"
        ref, transform, detail = refs[0]
        if transform in _EXPRESSIBLE:
            return f"{{{{{ref}{_EXPRESSIBLE[transform]}}}}}"
        if transform == "date":
            fmt = _date_format(values)
            if fmt is None:
                raise _Refused("date: no single output format fits every run")
            return f"{{{{{ref} | fmt_date({fmt!r})}}}}"
        raise _Refused(f"{transform} from {ref}")

    def bind(self, key: str, sigs: list[tuple[Any, ...]], values: list[Any]) -> Any:
        """Template or literal for a leaf across the supporting runs; raise `_Refused` otherwise."""
        top, n = Counter(sigs).most_common(1)[0]
        if top[0] == "gen" and n == len(sigs) and len(sigs) >= 2:
            return json.loads(top[1])
        if top[0] == "gen" or top[0] == "model":
            raise _Refused("model-written")
        if top[0] != "bind" or n < self.stable_share * len(sigs):
            raise _Refused(f"inconsistent across runs ({n} of {len(sigs)} agree)")
        return self.leaf_template(top, values)


def _date_format(values: list[Any]) -> str | None:
    for fmt in DATE_FORMATS:
        ok = True
        for v in values:
            dates = parse_dates(v)
            if len(dates) != 1 or next(iter(dates)).strftime(fmt) != v:
                ok = False
                break
        if ok:
            return fmt
    return None


def _dominant_path(
    views: list[RunView], min_support: int, log: list[str]
) -> tuple[list[Step], list[RunView]] | None:
    path: list[Step] = []
    remaining = views
    while True:
        depth = len(path)
        counts = Counter(v.steps[depth] if len(v.steps) > depth else _END for v in remaining)
        nxt, n = sorted(counts.items(), key=lambda kv: (-kv[1], json.dumps(kv[0])))[0]
        if n < min_support:
            log.append(
                f"dominant path support {n} < {min_support} runs at step {depth}; nothing compiled"
            )
            return None
        remaining = [
            v for v in remaining if (v.steps[depth] if len(v.steps) > depth else _END) == nxt
        ]
        if nxt == _END:
            return path, remaining
        path.append(nxt)


def compile_plan(
    runs: Sequence[Run],
    *,
    tools: dict[str, ToolSpec] | None = None,
    overrides: dict[str, Any] | None = None,
    min_support: int = MIN_SUPPORT,
    stable_share: float = STABLE_SHARE,
) -> CompileResult:
    """Compile the workflow's dominant path; `plan` is None when nothing can be compiled."""
    log: list[str] = []
    if not runs:
        return CompileResult(None, ["no runs"])
    classification = classify(runs, min_support=min_support, stable_share=stable_share)
    call_class = {c.event_id: c.call_class for c in classification.calls}
    views = {r.run_id: run_view(r) for r in runs}
    found = _dominant_path(sorted(views.values(), key=lambda v: v.run.started_at), min_support, log)
    if found is None:
        return CompileResult(None, log)
    path, supporting = found
    log.append(f"dominant path: {len(path)} steps, {len(supporting)} of {len(runs)} runs")
    b = _Builder(
        views, supporting, dict(tools or {}), dict(overrides or {}), stable_share, log, call_class
    )
    b.path = path
    try:
        _build_steps(b, path)
        end = _end_step(b)
    except _Refused as e:
        log.append(f"not compiled: {e}")
        return CompileResult(None, log)
    steps = [*b.steps, end]
    guards = _guards(steps, supporting)
    rep = supporting[0].run
    plan = WorkflowPlan.build(
        workflow_id=rep.workflow_id,
        skeleton_hash=skeleton_hash(skeleton(rep)),
        compiled_from=sorted(v.run.run_id for v in supporting),
        steps=steps,
        guards=guards,
        compile_log=log,
        manual_overrides=b.manual,
    )
    log.append(f"plan {plan.plan_id}: {len(steps)} steps, {len(guards)} guards")
    return CompileResult(plan, log)


def _build_steps(b: _Builder, path: list[Step]) -> None:
    """Emit the plan steps for the path."""
    rep = b.supporting[0]
    consumed: set[int] = set()
    for i, (kind, name, outcome) in enumerate(path):
        event = rep.events[i]
        if event.parent_id is not None or i in consumed:
            continue
        if kind == "tool":
            raise _Refused(f"tool {name} at step {i} was not requested by a model call")
        calls = [v.events[i] for v in b.supporting]
        model_calls = [c for c in calls if isinstance(c, ModelCall)]
        classes = Counter(_class_of(b, c) for c in model_calls)
        cls = classes.most_common(1)[0][0]
        pid = position_id(path[:i], name)
        tool_indices = [rep.index_of[t.event_id] for t in requested_tools(rep, i, model_calls[0])]
        consumed |= set(tool_indices)
        if cls == "terminal" or (cls == "judgment" and outcome == "text"):
            b.llm_step(
                i,
                model_calls,
                name,
                _object_schema({"text": {"type": "string"}}),
                'Reply with JSON {"text": "..."} holding your message.',
            )
            continue
        tool_names = outcome.removeprefix("calls:").split(",")
        if cls == "judgment":
            if len(tool_names) != 1 or len(tool_indices) != 1:
                raise _Refused(
                    f"step {i}: parallel tool calls in a judgment step are not supported in M1"
                )
            choices = sorted(_choices(b, path[:i], name))
            schema = _object_schema({"tool": {"enum": choices}, "arguments": {"type": "object"}})
            llm = b.llm_step(
                i,
                model_calls,
                name,
                schema,
                f"Choose the next tool from {choices} and its arguments. "
                'Reply with JSON {"tool": "...", "arguments": {...}}.',
                expected_tool=tool_names[0],
            )
            b.tool_step(tool_names[0], f"{{{{steps.{llm.id}.result.arguments}}}}", tool_indices[0])
            continue
        _bound_call(b, i, pid, name, model_calls, tool_indices)


def _class_of(b: _Builder, call: ModelCall) -> str:
    return b.call_classes.get(call.event_id, "judgment")


def _choices(b: _Builder, prefix: list[Step], role: str) -> set[str]:
    depth = len(prefix)
    found: set[str] = set()
    for v in b.views.values():
        if (
            v.steps[:depth] == prefix
            and len(v.steps) > depth
            and v.steps[depth][:2] == ("model", role)
        ):
            outcome = v.steps[depth][2]
            if outcome.startswith("calls:"):
                found |= set(outcome.removeprefix("calls:").split(","))
    return found


def _bound_call(
    b: _Builder, i: int, pid: str, role: str, model_calls: list[ModelCall], tool_indices: list[int]
) -> None:
    """A removable or constrained call: template what binds, ask the model for the rest."""
    rep = b.supporting[0]
    planned: list[tuple[str, int, Any, set[str]]] = []
    for t_index in tool_indices:
        tool = rep.events[t_index]
        assert isinstance(tool, ToolCall)
        per_key: dict[str, list[tuple[Any, ...]]] = {}
        values: dict[str, list[Any]] = {}
        for v in b.supporting:
            run_tool = v.events[t_index]
            assert isinstance(run_tool, ToolCall)
            vals = dict(leaves(run_tool.args))
            for leaf in v.prov.get(run_tool.event_id, []):
                per_key.setdefault(leaf.path, []).append(
                    leaf_signature(leaf, vals.get(leaf.path), v)
                )
                values.setdefault(leaf.path, []).append(vals.get(leaf.path))
        template: Any = json.loads(json.dumps(tool.args))
        ask: set[str] = set()
        for path, sigs in sorted(per_key.items()):
            key = f"{pid}:{tool.name}:{path}"
            try:
                value = b.bind(key, sigs, values[path])
            except _Refused as e:
                if key in b.overrides:
                    value = b.overrides[key]
                    b.manual.append(
                        ManualOverride(key=key, template=value, reason=f"compiler refused: {e}")
                    )
                    b.log.append(f"manual override {pid} {tool.name}:{path} = {value!r}")
                else:
                    if str(e) != "model-written":
                        b.log.append(
                            f"refused binding {pid} {tool.name}:{path} ({e}); asking the model"
                        )
                    top = _top_key(path)
                    if top is None:
                        raise _Refused(
                            f"{tool.name}: a non-object argument needs the model"
                        ) from None
                    ask.add(top)
                    continue
            template = _set_path(template, path, value)
        planned.append((tool.name, t_index, template, ask))
    asking = [(name, idx, tpl, ask) for name, idx, tpl, ask in planned if ask]
    if len(asking) > 1:
        raise _Refused(f"step {i}: more than one tool needs model-written arguments")
    for name, t_index, template, ask in planned:
        if ask:
            rep_tool = rep.events[t_index]
            assert isinstance(rep_tool, ToolCall)
            props = {k: _value_schema(rep_tool.args[k]) for k in sorted(ask)}
            llm = b.llm_step(
                i,
                model_calls,
                role,
                _object_schema(props),
                f"Call the tool `{name}`. Reply with JSON holding only these arguments: "
                + ", ".join(sorted(ask))
                + ".",
                forced_tool=name,
            )
            for k in ask:
                template[k] = f"{{{{steps.{llm.id}.result.{k}}}}}"
        b.tool_step(name, template, t_index)


def _end_step(b: _Builder) -> EndStep:
    per_path: dict[str, list[tuple[Any, ...]]] = {}
    values: dict[str, list[Any]] = {}
    for v in b.supporting:
        run = v.run
        last_ts = run.events[-1].ts if run.events else run.started_at
        probe = ToolCall(event_id="__output__", ts=last_ts, name="__output__", args=run.output)
        for leaf in provenance(run.model_copy(update={"events": [*run.events, probe]})):
            if leaf.event_id == "__output__":
                val = dict(leaves(run.output)).get(leaf.path)
                per_path.setdefault(leaf.path, []).append(
                    leaf_signature(leaf, val, v, allow_model=True)
                )
                values.setdefault(leaf.path, []).append(val)
    template: Any = json.loads(json.dumps(b.supporting[0].run.output))
    for path, sigs in sorted(per_path.items()):
        try:
            value = b.bind(f"output:{path}", sigs, values[path])
        except _Refused as e:
            raise _Refused(f"run output {path} is not reproducible ({e})") from None
        template = _set_path(template, path, value)
    return EndStep(output_template=template)


def _guards(
    steps: Sequence[ToolStep | LlmStep | EndStep], supporting: list[RunView]
) -> list[Guard]:
    paths: set[str] = set()
    for s in steps:
        templates: list[Any]
        match s:
            case ToolStep():
                templates = [s.args_template]
            case LlmStep():
                templates = [s.user_template, s.system_template]
            case EndStep():
                templates = [s.output_template]
        for t in templates:
            paths |= input_paths(t)
    guards = []
    for path in sorted(paths - {"input"}):
        observed = []
        for v in supporting:
            flat = dict(leaves(v.run.input))
            leaf = "$" + path.removeprefix("input")
            if leaf in flat:
                observed.append(flat[leaf])
        kind = _json_type(observed) if observed else None
        guards.append(
            Guard(
                id=f"schema:{path}", kind="schema", path=path, params={"type": kind} if kind else {}
            )
        )
    return guards
