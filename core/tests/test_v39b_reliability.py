"""Focused V3.9B conditional RUL interpretation tests."""

from dataclasses import fields, replace
import csv
from pathlib import Path

import pytest

import rul
from ops_sim.reliability import (
    CensoredSurvivorRiskDistributionRow,
    ConditionalRULSummary,
    ConditionalSurvivalCurvePoint,
    FailureModeDistributionRow,
    build_censored_survivor_risk_distribution,
    build_conditional_survival_curve,
    build_failure_mode_distribution,
    summarize_conditional_rul,
    wilson_interval,
)
from ops_sim.rul import (
    RULSample,
    build_survival_curve,
    estimate_remaining_useful_life,
    summarize_rul_samples,
)


def make_sample(**changes) -> RULSample:
    values = {
        "policy": "adaptive",
        "scenario": "nominal",
        "operator_view": "omniscient",
        "planning_model": "reactive",
        "maneuver_model": "none",
        "orbit_evolution_model": "fixed",
        "contact_model": "synthetic",
        "sample_seed": 0,
        "start_year": 8.0,
        "horizon_years": 3.0,
        "warmup_failed": False,
        "alive_at_start": True,
        "survived_to_horizon": True,
        "additional_hours_survived": 3,
        "additional_years_survived": 3.0,
        "loss_reason": None,
        "risk_driver": "power",
        "risk_margin": 0.5,
        "start_soc": 80.0,
        "start_health": 0.9,
        "start_delta_v_remaining_m_per_s": 8.0,
        "start_fuel_remaining_percent": 80.0,
        "start_orbit_drift_proxy_km": 0.1,
        "final_soc": 70.0,
        "final_health": 0.8,
        "final_delta_v_remaining_m_per_s": 7.0,
        "final_fuel_remaining_percent": 70.0,
        "final_orbit_drift_proxy_km": 0.2,
        "data_downlinked_during_rul_gb": 10.0,
        "data_generated_during_rul_gb": 12.0,
        "debris_avoidance_executed_during_rul": 1,
        "debris_avoidance_skipped_during_rul": 0,
        "maneuver_count_during_rul": 2,
        "orbit_correction_count_during_rul": 2,
    }
    values.update(changes)
    return RULSample(**values)


def mixed_samples() -> list[RULSample]:
    return [
        make_sample(
            sample_seed=0,
            warmup_failed=True,
            alive_at_start=False,
            survived_to_horizon=False,
            additional_hours_survived=0,
            additional_years_survived=0.0,
            loss_reason="critical_power",
        ),
        make_sample(
            sample_seed=1,
            survived_to_horizon=False,
            additional_hours_survived=1,
            additional_years_survived=0.5,
            loss_reason="critical_power",
            risk_driver="power",
        ),
        make_sample(
            sample_seed=2,
            survived_to_horizon=False,
            additional_hours_survived=2,
            additional_years_survived=2.0,
            loss_reason="thermal_failure",
            risk_driver="thermal",
        ),
        make_sample(sample_seed=3, risk_driver="power"),
        make_sample(sample_seed=4, risk_driver="thermal"),
    ]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_old_statistics_and_estimator_contract_remain_unchanged() -> None:
    samples = mixed_samples()
    old_summary = summarize_rul_samples(samples)
    old_curve = build_survival_curve(samples)
    assert old_summary.alive_at_start_fraction == pytest.approx(0.8)
    assert old_summary.expected_rul_years_censored == pytest.approx(1.7)
    assert [point.survival_probability for point in old_curve] == pytest.approx(
        [0.8, 0.6, 0.6, 0.4]
    )

    estimate = estimate_remaining_useful_life(
        policy_name="adaptive",
        scenario_name="nominal",
        start_year=0.0,
        horizon_years=0.0,
        samples=1,
    )
    assert isinstance(estimate, tuple)
    assert len(estimate) == 3


def test_hand_calculated_conditional_summary_excludes_warmup_failures() -> None:
    samples = mixed_samples()
    summary = summarize_conditional_rul(
        samples, bootstrap_replicates=40, bootstrap_seed=9
    )
    assert summary.total_samples == 5
    assert summary.alive_at_start_samples == 4
    assert summary.warmup_failed_samples == 1
    assert summary.alive_at_start_fraction == pytest.approx(0.8)
    assert summary.conditional_survived_to_horizon_fraction == pytest.approx(0.5)
    assert summary.conditional_expected_rul_years_censored == pytest.approx(2.125)
    assert summary.conditional_median_rul_years_censored == pytest.approx(2.5)
    assert summary.conditional_p05_rul_years_censored == pytest.approx(0.725)
    assert summary.conditional_p95_rul_years_censored == pytest.approx(3.0)
    assert summary.conditional_probability_survive_plus_1y == pytest.approx(0.75)
    assert summary.conditional_probability_survive_plus_2y == pytest.approx(0.75)
    assert summary.conditional_probability_survive_plus_3y == pytest.approx(0.5)

    old = summarize_rul_samples(samples)
    assert old.expected_rul_years_censored == pytest.approx(1.7)
    assert old.expected_rul_years_censored != (
        summary.conditional_expected_rul_years_censored
    )


def test_conditional_survival_curve_and_wilson_interval() -> None:
    curve = build_conditional_survival_curve(
        mixed_samples(), bootstrap_replicates=10
    )
    assert [point.years_after_start for point in curve] == [0.0, 1.0, 2.0, 3.0]
    assert [
        point.conditional_survival_probability for point in curve
    ] == pytest.approx([1.0, 0.75, 0.75, 0.5])
    assert (
        curve[0].conditional_survival_ci95_lower,
        curve[0].conditional_survival_ci95_upper,
    ) == (1.0, 1.0)
    lower, upper = wilson_interval(3, 4)
    assert lower == pytest.approx(0.300641842582402)
    assert upper == pytest.approx(0.9544127391902995)
    assert curve[1].conditional_survival_ci95_lower == pytest.approx(lower)
    assert curve[1].conditional_survival_ci95_upper == pytest.approx(upper)


def test_wilson_endpoint_intervals_and_conditional_curve_rows() -> None:
    no_success_lower, no_success_upper = wilson_interval(0, 4)
    all_success_lower, all_success_upper = wilson_interval(4, 4)
    for lower, upper in (
        (no_success_lower, no_success_upper),
        (all_success_lower, all_success_upper),
    ):
        assert 0.0 <= lower <= upper <= 1.0
        assert lower < upper
    assert no_success_lower == 0.0
    assert no_success_upper > 0.0
    assert all_success_lower < 1.0
    assert all_success_upper == 1.0

    failures = [
        make_sample(
            sample_seed=index,
            survived_to_horizon=False,
            additional_years_survived=1.0,
            loss_reason="critical_power",
        )
        for index in range(4)
    ]
    failure_curve = build_conditional_survival_curve(
        failures, bootstrap_replicates=5
    )
    after_failures = next(
        point for point in failure_curve if point.years_after_start == 2.0
    )
    assert after_failures.conditional_survival_probability == 0.0
    assert after_failures.conditional_survival_ci95_lower == pytest.approx(
        no_success_lower
    )
    assert after_failures.conditional_survival_ci95_upper == pytest.approx(
        no_success_upper
    )

    survivors = [make_sample(sample_seed=index) for index in range(4)]
    survivor_curve = build_conditional_survival_curve(
        survivors, bootstrap_replicates=5
    )
    positive_time = next(
        point for point in survivor_curve if point.years_after_start == 1.0
    )
    assert positive_time.conditional_survival_probability == 1.0
    assert positive_time.conditional_survival_ci95_lower == pytest.approx(
        all_success_lower
    )
    assert positive_time.conditional_survival_ci95_upper == pytest.approx(
        all_success_upper
    )


def test_bootstrap_resamples_rows_reproducibly_without_simulator(monkeypatch) -> None:
    samples = [
        make_sample(
            sample_seed=index,
            survived_to_horizon=duration == 3.0,
            additional_years_survived=duration,
        )
        for index, duration in enumerate((0.0, 0.5, 1.5, 2.5, 3.0))
    ]

    def forbidden_run(*args, **kwargs):
        raise AssertionError("bootstrap must not run Simulator")

    monkeypatch.setattr("ops_sim.simulator.Simulator.run", forbidden_run)
    first = summarize_conditional_rul(
        samples, bootstrap_replicates=80, bootstrap_seed=390
    )
    repeated = summarize_conditional_rul(
        samples, bootstrap_replicates=80, bootstrap_seed=390
    )
    changed = summarize_conditional_rul(
        samples, bootstrap_replicates=80, bootstrap_seed=391
    )
    assert first == repeated
    assert (
        first.conditional_expected_rul_years_censored_ci95_lower,
        first.conditional_expected_rul_years_censored_ci95_upper,
    ) != (
        changed.conditional_expected_rul_years_censored_ci95_lower,
        changed.conditional_expected_rul_years_censored_ci95_upper,
    )


def test_failure_and_censored_survivor_distributions_are_separate() -> None:
    samples = mixed_samples()
    failures = build_failure_mode_distribution(
        samples, bootstrap_replicates=10
    )
    assert [row.loss_reason for row in failures] == [
        "critical_power",
        "thermal_failure",
    ]
    assert [row.failure_count for row in failures] == [1, 1]
    assert [
        row.fraction_of_conditional_failures for row in failures
    ] == pytest.approx([0.5, 0.5])
    assert [
        row.fraction_of_alive_at_start_samples for row in failures
    ] == pytest.approx([0.25, 0.25])

    risks = build_censored_survivor_risk_distribution(
        samples, bootstrap_replicates=10
    )
    assert [(row.risk_driver, row.survivor_count) for row in risks] == [
        ("power", 1),
        ("thermal", 1),
    ]
    assert [row.fraction_of_horizon_survivors for row in risks] == pytest.approx(
        [0.5, 0.5]
    )
    assert {row.risk_driver for row in risks}.isdisjoint(
        {row.loss_reason for row in failures}
    )


def test_zero_alive_at_start_has_none_scalars_and_empty_tables() -> None:
    samples = [
        make_sample(
            sample_seed=index,
            warmup_failed=True,
            alive_at_start=False,
            survived_to_horizon=False,
            additional_years_survived=0.0,
            loss_reason="critical_power",
        )
        for index in range(2)
    ]
    summary = summarize_conditional_rul(samples, bootstrap_replicates=5)
    assert summary.alive_at_start_samples == 0
    assert summary.alive_at_start_fraction == 0.0
    assert summary.conditional_survived_to_horizon_fraction is None
    assert summary.conditional_expected_rul_years_censored is None
    assert summary.conditional_median_rul_years_censored is None
    assert build_conditional_survival_curve(samples, bootstrap_replicates=5) == []
    assert build_failure_mode_distribution(samples, bootstrap_replicates=5) == []
    assert (
        build_censored_survivor_risk_distribution(
            samples, bootstrap_replicates=5
        )
        == []
    )


def test_one_identical_conditional_sample_has_zero_width_mean_interval() -> None:
    summary = summarize_conditional_rul(
        [make_sample(additional_years_survived=1.25)],
        bootstrap_replicates=20,
    )
    assert summary.conditional_expected_rul_years_censored == pytest.approx(1.25)
    assert summary.conditional_expected_rul_years_censored_ci95_lower == (
        summary.conditional_expected_rul_years_censored
    )
    assert summary.conditional_expected_rul_years_censored_ci95_upper == (
        summary.conditional_expected_rul_years_censored
    )

    identical = summarize_conditional_rul(
        [
            make_sample(
                sample_seed=index,
                additional_years_survived=1.25,
            )
            for index in range(4)
        ],
        bootstrap_replicates=20,
    )
    assert identical.conditional_expected_rul_years_censored_ci95_lower == 1.25
    assert identical.conditional_expected_rul_years_censored_ci95_upper == 1.25


def test_all_survive_and_all_fail_edge_populations() -> None:
    survivors = [make_sample(sample_seed=index) for index in range(3)]
    survivor_summary = summarize_conditional_rul(
        survivors, bootstrap_replicates=5
    )
    assert survivor_summary.conditional_survived_to_horizon_fraction == 1.0
    assert build_failure_mode_distribution(
        survivors, bootstrap_replicates=5
    ) == []

    failures = [
        make_sample(
            sample_seed=index,
            survived_to_horizon=False,
            additional_years_survived=1.0,
            loss_reason="critical_power",
        )
        for index in range(3)
    ]
    failure_summary = summarize_conditional_rul(
        failures, bootstrap_replicates=5
    )
    assert failure_summary.conditional_survived_to_horizon_fraction == 0.0
    assert build_censored_survivor_risk_distribution(
        failures, bootstrap_replicates=5
    ) == []


def test_zero_and_short_horizons_do_not_invent_unsupported_probabilities() -> None:
    zero = [
        make_sample(
            horizon_years=0.0,
            additional_years_survived=0.0,
            additional_hours_survived=0,
        )
    ]
    zero_summary = summarize_conditional_rul(zero, bootstrap_replicates=5)
    assert zero_summary.conditional_expected_rul_years_censored == 0.0
    assert zero_summary.conditional_probability_survive_plus_1y is None
    zero_curve = build_conditional_survival_curve(zero, bootstrap_replicates=5)
    assert len(zero_curve) == 1
    assert zero_curve[0].conditional_survival_probability == 1.0

    short = [
        make_sample(
            horizon_years=0.5,
            additional_years_survived=0.5,
        )
    ]
    short_summary = summarize_conditional_rul(short, bootstrap_replicates=5)
    assert short_summary.conditional_probability_survive_plus_1y is None
    assert short_summary.conditional_probability_survive_plus_2y is None
    assert short_summary.conditional_probability_survive_plus_3y is None
    assert [
        point.years_after_start
        for point in build_conditional_survival_curve(
            short, bootstrap_replicates=5
        )
    ] == [0.0, 0.5]


def test_tied_failures_are_counted_without_special_inference() -> None:
    samples = [
        make_sample(
            sample_seed=index,
            survived_to_horizon=False,
            additional_years_survived=1.0,
            loss_reason="critical_power",
        )
        for index in range(3)
    ]
    curve = build_conditional_survival_curve(samples, bootstrap_replicates=5)
    assert curve[1].years_after_start == 1.0
    assert curve[1].conditional_survival_probability == 1.0
    assert curve[2].conditional_survival_probability == 0.0
    rows = build_failure_mode_distribution(samples, bootstrap_replicates=5)
    assert len(rows) == 1
    assert rows[0].failure_count == 3


@pytest.mark.parametrize(
    "builder",
    [
        summarize_conditional_rul,
        build_conditional_survival_curve,
        build_failure_mode_distribution,
        build_censored_survivor_risk_distribution,
    ],
)
def test_mixed_current_stack_provenance_is_rejected(builder) -> None:
    with pytest.raises(ValueError, match="one run configuration"):
        builder(
            [make_sample(), make_sample(power_model="eclipse_proxy")],
            bootstrap_replicates=5,
        )


@pytest.mark.parametrize("replicates", [0, -1, True, 1.5])
def test_bootstrap_replicates_must_be_a_positive_integer(replicates) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        summarize_conditional_rul(
            [make_sample()], bootstrap_replicates=replicates
        )


def test_all_outputs_retain_simulation_and_analysis_provenance() -> None:
    sample = make_sample(
        stationkeeping_planning_model="drift_aware",
        event_lifecycle_model="warning_proxy",
        debris_risk_model="severity_proxy",
        autonomy_model="contingency_plan",
        power_model="eclipse_proxy",
        thermal_model="load_stress_proxy",
        target_model="scene_scheduling_proxy",
        pointing_model="bounded_pointing_proxy",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=0.25,
    )
    outputs = [
        summarize_conditional_rul(
            [sample], bootstrap_replicates=7, bootstrap_seed=8
        ),
        *build_conditional_survival_curve(
            [sample], bootstrap_replicates=7, bootstrap_seed=8
        ),
        *build_censored_survivor_risk_distribution(
            [sample], bootstrap_replicates=7, bootstrap_seed=8
        ),
    ]
    for output in outputs:
        assert output.packet_delivery_model == "loss_retry_proxy"
        assert output.packet_drop_fraction_proxy == pytest.approx(0.25)
        assert output.bootstrap_replicates == 7
        assert output.bootstrap_seed == 8


def test_cli_opt_in_preserves_historical_files_and_adds_typed_csvs(
    tmp_path, capsys
) -> None:
    historical = tmp_path / "historical"
    assert rul.main([
        "--start-year", "0",
        "--horizon-years", "0.001",
        "--samples", "1",
        "--results-dir", str(historical),
    ]) == 0
    assert {path.name for path in historical.iterdir()} == {
        "rul_samples.csv",
        "rul_summary.csv",
        "rul_survival_curve.csv",
    }

    analyzed = tmp_path / "analyzed"
    assert rul.main([
        "--start-year", "0",
        "--horizon-years", "0.001",
        "--samples", "1",
        "--include-reliability-analysis",
        "--bootstrap-replicates", "10",
        "--bootstrap-seed", "391",
        "--results-dir", str(analyzed),
    ]) == 0
    assert {path.name for path in analyzed.iterdir()} == {
        "rul_samples.csv",
        "rul_summary.csv",
        "rul_survival_curve.csv",
        "rul_conditional_summary.csv",
        "rul_conditional_survival_curve.csv",
        "rul_failure_modes.csv",
        "rul_censored_survivor_risk_drivers.csv",
    }
    for filename in (
        "rul_samples.csv",
        "rul_summary.csv",
        "rul_survival_curve.csv",
    ):
        assert (historical / filename).read_bytes() == (
            analyzed / filename
        ).read_bytes()
    typed_outputs = (
        ("rul_conditional_summary.csv", ConditionalRULSummary),
        ("rul_conditional_survival_curve.csv", ConditionalSurvivalCurvePoint),
        ("rul_failure_modes.csv", FailureModeDistributionRow),
        (
            "rul_censored_survivor_risk_drivers.csv",
            CensoredSurvivorRiskDistributionRow,
        ),
    )
    for filename, row_type in typed_outputs:
        with (analyzed / filename).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == [field.name for field in fields(row_type)]
            list(reader)
    assert read_csv(analyzed / "rul_conditional_summary.csv")[0][
        "bootstrap_seed"
    ] == "391"
    capsys.readouterr()


def test_cli_rejects_invalid_bootstrap_replicates() -> None:
    with pytest.raises(SystemExit, match="positive integer"):
        rul.main(["--bootstrap-replicates", "0"])


def test_paper_suite_v40b_integrates_v39b_without_the_standalone_flag() -> None:
    source = Path("paper_suite.py").read_text(encoding="utf-8")
    assert "include_reliability_analysis" not in source
    assert "summarize_conditional_rul" in source
    assert "if design.is_final_v40" in source
