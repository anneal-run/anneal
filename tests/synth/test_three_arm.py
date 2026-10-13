"""The three-arm protocol on the simulated environment (a dry run, not evidence)."""

import pytest

from synth.arms import Experiment, run_experiment


@pytest.fixture(scope="module")
def experiment() -> Experiment:
    return run_experiment(include_baseline=False)


def test_tier0_is_the_reference_and_handles_every_drift(experiment: Experiment) -> None:
    report = experiment.report
    assert report.summary("tier0", None).success_rate == 1.0
    for drift in report.drifts:
        assert report.summary("tier0", drift).behaviour == "handles it", drift


def test_compiled_arm_keeps_task_success_and_costs_less_on_the_holdout(
    experiment: Experiment,
) -> None:
    report = experiment.report
    compiled, tier0 = report.summary("compiled", None), report.summary("tier0", None)
    assert compiled.success_rate == 1.0
    assert compiled.silent == compiled.loud == compiled.fallback_wrong == 0
    assert compiled.cost_per_task < tier0.cost_per_task


def test_compiled_guards_catch_schema_and_enum_drift(experiment: Experiment) -> None:
    report = experiment.report
    assert report.summary("compiled", "renamed_field").behaviour == "falls back"
    assert report.summary("compiled", "new_enum").behaviour == "falls back"
    assert report.summary("compiled", "renamed_field").success_rate == 1.0
    assert report.summary("compiled", "new_enum").success_rate == 1.0


def test_a_new_topic_passes_m1_guards_and_fails_silently(experiment: Experiment) -> None:
    """The honest result: schema and enum guards do not see a new topic (OOD is M2.3)."""
    new_topic = experiment.report.summary("compiled", "new_topic")
    assert new_topic.behaviour == "fails silently"
    assert new_topic.silent > 0
    assert new_topic.fallback_wrong > 0  # deopted, but only after a wrong ticket was written
    assert new_topic.success_rate < 0.25  # only inputs a guard happened to reject


def test_split_sizes(experiment: Experiment) -> None:
    assert (experiment.compile_runs, experiment.holdout_runs) == (56, 24)
    assert len(experiment.report.rows) == 24 * 4 * 2


def test_the_baseline_arm_runs_when_present() -> None:
    from synth.arms import load_baseline

    if load_baseline() is None:
        pytest.skip("no baseline/env_support/workflow.py")
    experiment = run_experiment(include_baseline=True)
    assert experiment.report.arms == ["tier0", "compiled", "baseline"]
    assert len(experiment.report.rows) == 24 * 4 * 3
