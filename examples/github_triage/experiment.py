"""The M1 path on the github_triage dogfood traces, phase by phase.

    python -m github_triage.experiment export|import|analyze|compile|replay|deopts|arms|memo

Each phase writes its result under `data/experiment/` and later phases read it, so
a phase that spends money (`replay`, `deopts`, `arms`) runs once. Every live
model call goes through the spend ledger (`budget.py`).

Datasets: `uv` is compiled (first 70% by start time) and held out (last 30%);
`pydantic`, `mypy` and `godot` are the drift inputs (new label vocabulary,
different issue template, different domain). Their Tier 0 runs are the recorded
traces, scored with the same task check.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.callbacks import UsageMetadataCallbackHandler

from anneal.compile.compiler import ToolSpec, compile_plan
from anneal.compile.plan import LlmStep, ToolStep, WorkflowPlan
from anneal.integrations.langgraph import chat_model_runner, from_langchain, langgraph_fallback
from anneal.replay.arms import ArmRun, ArmsReport, Case, evaluate
from anneal.replay.replay import ReplayReport, replay_plan
from anneal.replay.split import chronological_split
from anneal.report.analyze import AnalyzeReport, analyze
from anneal.runtime.executor import DeoptRequested, LlmResponse, LlmRunner
from anneal.runtime.fallback import CompiledWorkflow
from anneal.schema import Run
from anneal.schema.pricing import PriceTable, fill_costs
from anneal.schema.store import Store
from github_triage.agent import build_agent, chat_model, first_message
from github_triage.budget import Budget
from github_triage.check import RunCheck, find_triage, issue_ref, judge
from github_triage.github import GitHub
from github_triage.run import load_truths
from github_triage.select_issues import Truth
from github_triage.tools import ToolError, Tools, triaging

HERE = Path(__file__).parent
DATA = Path(os.environ.get("TRIAGE_DATA", HERE / "data"))
OUT = DATA / "experiment"
TRACES = DATA / "traces"
STORE = DATA / "store"
PROJECT = os.environ.get("LANGSMITH_PROJECT", "anneal-dogfood-github-triage")
DATASETS = {
    "uv": "github_triage",
    "pydantic": "triage_pydantic",
    "mypy": "triage_mypy",
    "godot": "triage_godot",
}
DRIFTS = {"pydantic": "new_enum", "mypy": "renamed_field", "godot": "new_topic"}
DRIFT_CASES = 30
TOOLS = {
    name: ToolSpec(side_effect=False, severity="S0", idempotent=True)
    for name in ("get_issue", "list_labels", "search_similar_issues", "draft_comment")
}
PRICES = PriceTable.load()


def save(name: str, model: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    text = (
        model.model_dump_json(indent=1)
        if hasattr(model, "model_dump_json")
        else json.dumps(model, indent=1)
    )
    (OUT / name).write_text(text)


def load(name: str) -> Any:
    return json.loads((OUT / name).read_text())


# Data


def truths() -> dict[tuple[str, int], Truth]:
    return {(t.repo, t.number): t for ds in DATASETS for t in load_truths(DATA / f"{ds}.jsonl")}


def label_sets(gh: GitHub) -> dict[str, set[str]]:
    tools = Tools(gh)
    repos = {repo for repo, _ in truths()}
    return {repo: {x["name"] for x in tools.list_labels(repo)} for repo in repos}


def runs_of(dataset: str) -> list[Run]:
    runs = Store(STORE).read(DATASETS[dataset])
    return [fill_costs(r, PRICES) for r in runs if r.status == "success"]


def uv_split() -> tuple[list[Run], list[Run]]:
    return chronological_split(runs_of("uv"), 0.7)


def plan() -> WorkflowPlan:
    return WorkflowPlan.model_validate(load("plan.json"))


# Live runners


class LiveTools:
    """The real (cached, read-only) tools as an executor ToolRunner."""

    def __init__(self, gh: GitHub) -> None:
        self.tools = Tools(gh)

    def __call__(self, step: ToolStep, args: Any, key: str | None) -> Any:
        try:
            return self.tools.call(step.name, args)
        except ToolError as e:
            raise RuntimeError(str(e)) from None


def live_llm(budget: Budget, phase: str) -> LlmRunner:
    runner = chat_model_runner(chat_model(), cost=PRICES.cost)

    def run(step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
        budget.check()
        response = runner(step, system, user, feedback)
        budget.add(phase, response.cost_usd or 0.0)
        return response

    return run


def agent_fallback(tools: Tools, usage: UsageMetadataCallbackHandler) -> Any:
    graph = build_agent(chat_model(), tools.langchain_tools())
    return langgraph_fallback(
        graph, output=lambda s: {"triage": s.get("triage")}, config={"callbacks": [usage]}
    )


def state_input(repo: str, number: int) -> dict[str, Any]:
    return {"messages": [first_message(repo, number).model_dump()]}


def initial_messages(run_input: Any) -> Any:
    return from_langchain(run_input["messages"])


# Phases


def phase_export() -> None:
    for ds in DATASETS:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "github_triage.export",
                str(TRACES / f"{ds}.jsonl"),
                "--project",
                PROJECT,
                "--dataset",
                ds,
            ],
            check=True,
        )


def phase_import() -> None:
    for ds, workflow in DATASETS.items():
        subprocess.run(
            [
                "anneal",
                "import",
                "langsmith",
                str(TRACES / f"{ds}.jsonl"),
                "--store",
                str(STORE),
                "--workflow",
                workflow,
            ],
            check=True,
        )


def phase_analyze() -> None:
    compile_runs, holdout = uv_split()
    save("analyze_all.json", analyze(compile_runs + holdout))
    save("analyze_holdout.json", analyze(holdout))
    save("analyze_compile.json", analyze(compile_runs))


def phase_compile() -> None:
    compile_runs, _ = uv_split()
    started = time.perf_counter()
    result = compile_plan(compile_runs, tools=TOOLS, output_path="$.triage")
    seconds = time.perf_counter() - started
    save(
        "compile.json", {"log": result.log, "seconds": seconds, "compiled": result.plan is not None}
    )
    if result.plan is not None:
        save("plan.json", result.plan)
    print("\n".join(result.log))


def run_check(gh: GitHub) -> RunCheck:
    return RunCheck(truths(), label_sets(gh))


def phase_replay() -> None:
    gh, budget = GitHub(offline=True), Budget()
    compile_runs, holdout = uv_split()
    check = run_check(gh)
    recorded = replay_plan(plan(), holdout, task_check=check, compile_runs=len(compile_runs))
    save("replay_recorded.json", recorded)
    all_truths = truths()
    reader = LiveTools(GitHub())

    def live_tools(run: Run) -> Any:
        repo, number = issue_ref(run.input)
        created = all_truths[(repo, number)].created_at

        def call(step: ToolStep, args: Any, key: str | None) -> Any:
            with triaging(repo, number, created):
                return reader(step, args, key)

        return call

    live = replay_plan(
        plan(),
        holdout,
        task_check=check,
        llm_factory=lambda run: live_llm(budget, "replay_live"),
        compile_runs=len(compile_runs),
        live_tools=live_tools,
    )
    save("replay_live.json", live)


class Recording(LiveTools):
    """Live tools that can inject a deopt at one step."""

    def __init__(self, gh: GitHub, at: str | None = None) -> None:
        super().__init__(gh)
        self.at = at

    def __call__(self, step: ToolStep, args: Any, key: str | None) -> Any:
        if step.id == self.at:
            raise DeoptRequested(step.id, "injected")
        return super().__call__(step, args, key)


def compiled_workflow(
    gh: GitHub, budget: Budget, phase: str, at: str | None = None
) -> tuple[CompiledWorkflow, Recording, Tools, UsageMetadataCallbackHandler]:
    tools = Recording(gh, at)
    llm = live_llm(budget, phase)

    def model(step: LlmStep, system: str, user: str, feedback: str | None) -> LlmResponse:
        if step.id == at:
            raise DeoptRequested(step.id, "injected")
        return llm(step, system, user, feedback)

    agent_tools, usage = Tools(gh), UsageMetadataCallbackHandler()
    workflow = CompiledWorkflow(
        plan(),
        tools=tools,
        llm=model,
        fallback=agent_fallback(agent_tools, usage),
        initial_messages=initial_messages,
    )
    return workflow, tools, agent_tools, usage


def phase_deopts() -> None:
    """20 injected deopts into the real agent, on holdout issues Tier 0 got right, at each
    step the live compiled path reaches (up to and including the first natural deopt)."""
    from anneal.report.memo import DeoptTrial, FallbackReport

    gh, budget = GitHub(), Budget()
    labels, all_truths = label_sets(gh), truths()
    live = ReplayReport.model_validate(load("replay_live.json"))
    _, holdout = uv_split()
    by_id = {r.run_id: r for r in holdout}
    accepted = [by_id[r.run_id] for r in live.rows if r.tier0_success]
    ids = [s.id for s in plan().steps if s.id != "end"]
    first_deopt = min((ids.index(k) for k in live.deopt_by_step), default=len(ids) - 1)
    steps = ids[: first_deopt + 1]
    trials = []
    for i in range(20):
        run, at = accepted[i % len(accepted)], steps[i % len(steps)]
        repo, number = issue_ref(run.input)
        truth = all_truths[(repo, number)]
        workflow, compiled_tools, agent_tools, usage = compiled_workflow(gh, budget, "deopts", at)
        with triaging(repo, number, truth.created_at):
            outcome = workflow.run(state_input(repo, number), run_id=f"inject-{number}-{at}")
        budget.add("deopts", budget.cost(usage.usage_metadata))
        done = [(n, json.dumps(a, sort_keys=True)) for n, a in compiled_tools.tools.calls]
        again = [(n, json.dumps(a, sort_keys=True)) for n, a in agent_tools.calls]
        repeated = sorted({n for n, a in again if (n, a) in set(done)})
        verdict = judge(find_triage(outcome.output), truth, labels[repo])
        trials.append(
            DeoptTrial(
                run_id=f"{repo}#{number}",
                step_id=outcome.execution.deopt.step_id if outcome.execution.deopt else "none",
                task_success=outcome.tier == 0 and verdict.ok,
                repeated=repeated,
            )
        )
        print(at, number, verdict.reason, repeated, flush=True)
    save(
        "deopts.json", FallbackReport(framework="LangGraph 1.2.15, claude-haiku-5-5", trials=trials)
    )


def drift_cases() -> list[Case]:
    _, holdout = uv_split()
    cases = []
    all_truths = truths()
    for run in holdout:
        repo, number = issue_ref(run.input)
        cases.append(Case(case_id=f"{repo}#{number}", input=all_truths[(repo, number)].to_json()))
    for ds, drift in DRIFTS.items():
        for t in load_truths(DATA / f"{ds}.jsonl")[-DRIFT_CASES:]:
            cases.append(Case(case_id=f"{t.repo}#{t.number}", input=t.to_json(), drift=drift))
    return cases


def recorded_rows() -> dict[str, dict[str, Any]]:
    out = {}
    for ds in DATASETS:
        for line in (DATA / "runs" / f"{ds}.jsonl").read_text().splitlines():
            row = json.loads(line)
            out[f"{row['repo']}#{row['number']}"] = row
    return out


class BaselineModel:
    """The baseline's `Model`: the same chat model, with usage counted."""

    def __init__(self, budget: Budget) -> None:
        self.model = chat_model()
        self.budget = budget
        self.cost = 0.0
        self.calls = 0

    def complete(self, system: str, user: str, schema: dict[str, Any] | None = None) -> Any:
        from langchain_core.messages import HumanMessage, SystemMessage

        self.budget.check()
        self.calls += 1
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        usage = UsageMetadataCallbackHandler()
        config: Any = {"callbacks": [usage]}
        if schema is None:
            answer: Any = self.model.invoke(messages, config=config).content
            if isinstance(answer, list):
                answer = "".join(b.get("text", "") for b in answer if isinstance(b, dict))
        else:
            full = {"title": "answer", "description": "Your answer.", **schema}
            answer = self.model.with_structured_output(full).invoke(messages, config=config)
            if answer is None:
                raise ValueError("the model's answer did not parse")
        cost = self.budget.cost(usage.usage_metadata)
        self.cost += cost
        self.budget.add("arms_baseline", cost)
        return answer


def load_baseline() -> Any:
    import importlib.util

    directory = HERE.parents[1] / "baseline" / "github_triage"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(
            "github_triage_baseline", directory / "workflow.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(directory))


def phase_arms() -> None:
    gh, budget = GitHub(), Budget()
    labels, all_truths, recorded = label_sets(gh), truths(), recorded_rows()
    baseline = load_baseline()
    interface = sys.modules["interface"]

    class BaselineTools:
        def __init__(self) -> None:
            self.tools = Tools(gh)

        def call(self, name: str, args: dict[str, Any]) -> Any:
            try:
                return self.tools.call(name, args)
            except ToolError as e:
                raise interface.ToolError(str(e)) from None

    def tier0(case: Case) -> ArmRun:
        row = recorded[case.case_id]
        return ArmRun(
            output={"triage": row["triage"]}, cost_usd=row["cost_usd"], error=row["error"]
        )

    def compiled(case: Case) -> ArmRun:
        t = Truth(**case.input)
        workflow, _, _, usage = compiled_workflow(gh, budget, "arms_compiled")
        with triaging(t.repo, t.number, t.created_at):
            outcome = workflow.run(state_input(t.repo, t.number), run_id=f"arm-{t.number}")
        fallback_cost = budget.cost(usage.usage_metadata)
        budget.add("arms_compiled", fallback_cost)
        spent = sum(
            e.cost_usd or 0.0 for e in outcome.execution.trace.events if e.kind == "model_call"
        )
        return ArmRun(
            output=outcome.output, cost_usd=spent + fallback_cost, fell_back=outcome.tier == 0
        )

    def script(case: Case) -> ArmRun:
        t = Truth(**case.input)
        model = BaselineModel(budget)
        try:
            with triaging(t.repo, t.number, t.created_at):
                output = baseline.run(t.repo, t.number, BaselineTools(), model)
            error = None
        except Exception as e:
            output, error = None, f"{type(e).__name__}: {e}"
        return ArmRun(
            output={"triage": output}, cost_usd=model.cost, model_calls=model.calls, error=error
        )

    def check(case: Case, run: ArmRun) -> bool:
        t = all_truths[(case.input["repo"], case.input["number"])]
        return judge(find_triage(run.output), t, labels[t.repo]).ok

    report = evaluate(
        drift_cases(),
        {"tier0": tier0, "compiled": compiled, "baseline": script},
        check,
        reference="tier0",
    )
    save("arms.json", report)


def phase_memo() -> None:
    from anneal.report.memo import FallbackReport, ManualStep, Memo, render_memo

    compile_info = load("compile.json")
    log_path = HERE.parents[1] / "baseline" / "github_triage" / "BUILD_LOG.md"
    import re

    m = (
        re.search(r"Time spent: (\d+) min (\d+) s", log_path.read_text())
        if log_path.exists()
        else None
    )
    baseline_s = int(m.group(1)) * 60 + int(m.group(2)) if m else None
    memo = Memo(
        workflow_id="github_triage",
        stamp="dogfood",
        source=(
            "LangGraph triage agent on claude-haiku-5-5, 200 closed astral-sh/uv issues (compile "
            "140, holdout 60), drift sets from pydantic/pydantic, python/mypy, godotengine/godot; "
            "traced to LangSmith and imported with `anneal import langsmith`"
        ),
        analyze_all=AnalyzeReport.model_validate(load("analyze_all.json")),
        analyze_holdout=AnalyzeReport.model_validate(load("analyze_holdout.json")),
        replay=ReplayReport.model_validate(load("replay_live.json")),
        fallback=FallbackReport.model_validate(load("deopts.json")),
        arms=ArmsReport.model_validate(load("arms.json")),
        build_seconds={"tier0": None, "compiled": None, "baseline": baseline_s},
        build_notes={
            "tier0": "n/a (existing agent)",
            "compiled": f"{compile_info['seconds']:.2f} s compute; human setup not timed",
            "baseline": f"{baseline_s} s (separate session)" if baseline_s else "not measured",
        },
        manual_steps=[
            ManualStep(
                step="Declared 4 tools as read-only S0",
                why="the compiler cannot infer side effects",
                automate_in="M2 SDK",
            ),
            ManualStep(
                step="Wrote the task check and RUBRIC.md",
                why="no partner; implementer-defined",
                automate_in="never",
            ),
            ManualStep(
                step="Selected issues and ground truth",
                why="labels and duplicate closures as the proxy",
                automate_in="never",
            ),
        ],
        open_items=[
            "Not a partner workflow; Gate 1 still needs one.",
            "H4 build time stays open until report/setup-timing.md has stopwatch entries.",
        ],
    )
    (HERE.parents[1] / "report" / "github_triage-memo.md").write_text(render_memo(memo))


PHASES: dict[str, Callable[[], None]] = {
    "export": phase_export,
    "import": phase_import,
    "analyze": phase_analyze,
    "compile": phase_compile,
    "replay": phase_replay,
    "deopts": phase_deopts,
    "arms": phase_arms,
    "memo": phase_memo,
}


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    for name in args:
        PHASES[name]()


if __name__ == "__main__":
    main()
