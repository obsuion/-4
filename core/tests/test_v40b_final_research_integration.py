"""Focused V4.0B final research-suite integration tests."""

import csv
from pathlib import Path

import pytest

import paper_suite
from ops_sim.analysis import PAPER_SCORE_WEIGHTS
from ops_sim.reliability import summarize_conditional_rul
from ops_sim.research_design import (
    FINAL_V40_CONFIGURATION,
    LEGACY_V30_CORE_CONFIGURATION,
    MODEL_SELECTOR_FIELDS,
)
from ops_sim.research_validation import (
    FAIL,
    LAYER_SENSITIVITY_FIELDS,
    build_internal_validation_checks,
    build_layer_sensitivity_rows,
    build_public_spec_sanity_rows,
    raise_for_validation_failures,
)
from ops_sim.rul import RULSample


RUL_RAW_FILES = {
    "rul_samples.csv",
    "rul_summary.csv",
    "rul_survival_curve.csv",
    "rul_conditional_summary.csv",
    "rul_conditional_survival_curve.csv",
    "rul_failure_modes.csv",
    "rul_censored_survivor_risk_drivers.csv",
}

DETERMINISTIC_CSVS = {
    "raw/core_summary.csv",
    "raw/ablation_raw.csv",
    "raw/rul_samples.csv",
    "raw/rul_summary.csv",
    "raw/rul_survival_curve.csv",
    "raw/rul_conditional_summary.csv",
    "raw/rul_conditional_survival_curve.csv",
    "raw/rul_failure_modes.csv",
    "raw/rul_censored_survivor_risk_drivers.csv",
    "raw/internal_validation_checks.csv",
    "tables/public_spec_sanity.csv",
    "tables/layer_sensitivity_summary.csv",
}


def _design(*args: str):
    parser = paper_suite.build_parser()
    return paper_suite.build_experiment_design(parser.parse_args(list(args)))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _fieldnames(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle).fieldnames or ())


def _run_final_quick(path: Path, *, bootstrap_seed: int = 390) -> None:
    assert paper_suite.main([
        "--suite-profile", "final_v40",
        "--quick",
        "--skip-plots",
        "--results-dir", str(path),
        "--seed", "40",
        "--bootstrap-replicates", "20",
        "--bootstrap-seed", str(bootstrap_seed),
    ]) == 0


@pytest.fixture(scope="module")
def final_quick_package(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("v40b_final_package")
    _run_final_quick(path)
    return path


def _make_sample(**changes) -> RULSample:
    values = {
        "policy": "adaptive",
        "scenario": "stochastic_post_life_events",
        "operator_view": "delayed_telemetry",
        "planning_model": "risk_aware",
        "maneuver_model": "stationkeeping_proxy",
        "orbit_evolution_model": "drift_proxy",
        "contact_model": "geometry",
        "sample_seed": 40,
        "start_year": 1.0,
        "horizon_years": 2.0,
        "warmup_failed": False,
        "alive_at_start": True,
        "survived_to_horizon": True,
        "additional_hours_survived": 2,
        "additional_years_survived": 2.0,
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
        **{
            field: value
            for field, value in (
                FINAL_V40_CONFIGURATION.selector_provenance().items()
            )
            if field not in {
                "contact_model",
                "operator_view",
                "planning_model",
                "maneuver_model",
                "orbit_evolution_model",
            }
        },
    }
    values.update(changes)
    return RULSample(**values)


def test_profile_rul_configuration_identity_and_bootstrap_defaults() -> None:
    final = _design("--quick")
    legacy = _design("--suite-profile", "legacy_v30", "--quick")

    assert final.rul_configuration is FINAL_V40_CONFIGURATION
    assert final.core_configuration is final.rul_configuration
    assert final.rul_is_final_stack is True
    assert final.bootstrap_replicates == 1000
    assert final.bootstrap_seed == 390
    assert legacy.rul_configuration is LEGACY_V30_CORE_CONFIGURATION
    assert legacy.rul_is_final_stack is False


def test_final_estimator_receives_authoritative_complete_stack(monkeypatch) -> None:
    design = _design("--quick")
    estimator_calls: list[dict[str, object]] = []
    analysis_calls = {name: 0 for name in ("summary", "curve", "failure", "risk")}

    class Row:
        def as_dict(self):
            return {}

    class Sample(Row):
        pass

    def estimate(**kwargs):
        estimator_calls.append(kwargs)
        return [Sample()], Row(), [Row()]

    def summary(samples, **kwargs):
        analysis_calls["summary"] += 1
        return Row()

    def curve(samples, **kwargs):
        analysis_calls["curve"] += 1
        return [Row()]

    def failure(samples, **kwargs):
        analysis_calls["failure"] += 1
        return []

    def risk(samples, **kwargs):
        analysis_calls["risk"] += 1
        return []

    monkeypatch.setattr(paper_suite, "estimate_remaining_useful_life", estimate)
    monkeypatch.setattr(paper_suite, "summarize_conditional_rul", summary)
    monkeypatch.setattr(paper_suite, "build_conditional_survival_curve", curve)
    monkeypatch.setattr(paper_suite, "build_failure_mode_distribution", failure)
    monkeypatch.setattr(
        paper_suite, "build_censored_survivor_risk_distribution", risk
    )

    result = paper_suite.run_rul_matrix(design)
    expected = FINAL_V40_CONFIGURATION.rul_kwargs()
    assert len(estimator_calls) == len(design.rul_policies)
    for call in estimator_calls:
        assert {field: call[field] for field in expected} == expected
        assert callable(call["event_catalog_factory"])
    assert analysis_calls == {
        name: len(design.rul_policies) for name in analysis_calls
    }
    assert len(result.samples) == len(design.rul_policies)
    assert len(result.conditional_summaries) == len(design.rul_policies)


def test_final_quick_package_has_full_stack_rul_and_conditional_outputs(
    final_quick_package,
) -> None:
    raw = final_quick_package / "raw"
    assert RUL_RAW_FILES <= {path.name for path in raw.iterdir() if path.is_file()}
    samples = _read_csv(raw / "rul_samples.csv")
    conditional = _read_csv(raw / "rul_conditional_summary.csv")
    assert len(samples) == 2
    assert len(conditional) == 2
    for row in samples:
        assert row["rul_configuration"] == FINAL_V40_CONFIGURATION.label
        assert row["rul_stack_status"] == "final_stack_v40b"
        for field, expected in FINAL_V40_CONFIGURATION.selector_provenance().items():
            if field == "packet_drop_fraction_proxy":
                assert float(row[field]) == expected
            else:
                assert row[field] == expected
    for row in conditional:
        assert int(row["total_samples"]) == (
            int(row["alive_at_start_samples"])
            + int(row["warmup_failed_samples"])
        )
        assert int(row["bootstrap_replicates"]) == 20
        assert int(row["bootstrap_seed"]) == 390
    assert _fieldnames(raw / "rul_failure_modes.csv") == list(
        paper_suite.FAILURE_MODE_FIELDS
    )
    checks = _read_csv(raw / "internal_validation_checks.csv")
    assert checks
    assert {row["status"] for row in checks} == {"pass"}


def test_skip_rul_removes_all_old_and_new_rul_outputs(tmp_path) -> None:
    path = tmp_path / "skip_rul"
    for directory in ("raw", "tables", "figures", "paper"):
        (path / directory).mkdir(parents=True, exist_ok=True)
    for filename in paper_suite.RAW_RUL_FILES:
        (path / "raw" / filename).write_text("stale", encoding="utf-8")
    for filename in paper_suite.TABLE_RUL_FILES:
        (path / "tables" / filename).write_text("stale", encoding="utf-8")

    assert paper_suite.main([
        "--suite-profile", "final_v40",
        "--quick",
        "--skip-rul",
        "--skip-plots",
        "--results-dir", str(path),
        "--seed", "40",
    ]) == 0

    assert all(not (path / "raw" / name).exists() for name in paper_suite.RAW_RUL_FILES)
    assert all(not (path / "tables" / name).exists() for name in paper_suite.TABLE_RUL_FILES)
    assert (path / "raw" / "internal_validation_checks.csv").is_file()
    assert (path / "tables" / "layer_sensitivity_summary.csv").is_file()


def test_unconditional_rul_participates_in_paper_score(final_quick_package) -> None:
    ranking = _read_csv(
        final_quick_package / "tables" / "policy_ranking.csv"
    )
    assert ranking
    assert PAPER_SCORE_WEIGHTS["expected_rul_years_censored"] == 0.15
    assert all(row["expected_rul_years_censored"] for row in ranking)
    assert all(row["normalized_expected_rul_years_censored"] for row in ranking)
    assert "conditional_expected_rul_years_censored" not in PAPER_SCORE_WEIGHTS


def test_bootstrap_is_deterministic_and_does_not_change_samples(
    final_quick_package, tmp_path
) -> None:
    samples = [
        _make_sample(sample_seed=index, additional_years_survived=value)
        for index, value in enumerate((0.5, 1.0, 2.0, 2.0))
    ]
    first = summarize_conditional_rul(
        samples, bootstrap_replicates=40, bootstrap_seed=390
    ).as_dict()
    second = summarize_conditional_rul(
        samples, bootstrap_replicates=40, bootstrap_seed=390
    ).as_dict()
    assert first == second

    identical = tmp_path / "identical"
    _run_final_quick(identical)
    for relative in DETERMINISTIC_CSVS:
        assert (final_quick_package / relative).read_bytes() == (
            identical / relative
        ).read_bytes()

    different_bootstrap = tmp_path / "different_bootstrap"
    _run_final_quick(different_bootstrap, bootstrap_seed=391)
    assert (
        final_quick_package / "raw" / "rul_samples.csv"
    ).read_bytes() == (
        different_bootstrap / "raw" / "rul_samples.csv"
    ).read_bytes()


def test_internal_validation_detects_population_and_provenance_defects() -> None:
    provenance = FINAL_V40_CONFIGURATION.selector_provenance()
    core = [{
        "policy": "adaptive",
        "seed": 40,
        "packet_delivery_seed": 40,
        **provenance,
    }]
    rul_samples = [{
        "policy": "adaptive",
        "rul_configuration": FINAL_V40_CONFIGURATION.label,
        "warmup_failed": False,
        "alive_at_start": True,
        "survived_to_horizon": True,
        **provenance,
    }]
    summary = [{
        "policy": "adaptive",
        "total_samples": 1,
        "alive_at_start_samples": 1,
        "warmup_failed_samples": 0,
        "alive_at_start_fraction": 1.0,
        "conditional_survived_to_horizon_fraction": 1.0,
        "conditional_expected_rul_years_censored": 1.0,
        "conditional_median_rul_years_censored": 1.0,
        "conditional_p05_rul_years_censored": 1.0,
        "conditional_p95_rul_years_censored": 1.0,
    }]
    curve = [{
        "policy": "adaptive",
        "years_after_start": 0.0,
        "conditional_survival_probability": 1.0,
        "conditional_survival_ci95_lower": 1.0,
        "conditional_survival_ci95_upper": 1.0,
    }]
    risks = [{
        "policy": "adaptive",
        "survivor_count": 1,
        "fraction_of_horizon_survivors": 1.0,
    }]
    valid = build_internal_validation_checks(
        core_rows=core,
        rul_sample_rows=rul_samples,
        conditional_summary_rows=summary,
        conditional_survival_rows=curve,
        survivor_risk_rows=risks,
    )
    assert FAIL not in {check.status for check in valid}
    raise_for_validation_failures(valid)

    invalid_core = [{**core[0], "contact_model": "synthetic"}]
    invalid_summary = [{**summary[0], "total_samples": 2}]
    invalid = build_internal_validation_checks(
        core_rows=invalid_core,
        rul_sample_rows=rul_samples,
        conditional_summary_rows=invalid_summary,
        conditional_survival_rows=curve,
        survivor_risk_rows=risks,
    )
    assert FAIL in {check.status for check in invalid}
    with pytest.raises(ValueError, match="validation failed"):
        raise_for_validation_failures(invalid)


def test_validation_uses_actual_samples_as_population_ground_truth() -> None:
    provenance = FINAL_V40_CONFIGURATION.selector_provenance()
    core = [{
        "policy": "adaptive",
        "seed": 40,
        "packet_delivery_seed": 40,
        **provenance,
    }]
    sample_base = {
        "policy": "adaptive",
        "rul_configuration": FINAL_V40_CONFIGURATION.label,
        "warmup_failed": False,
        "alive_at_start": True,
        **provenance,
    }
    samples = [
        {**sample_base, "survived_to_horizon": True},
        {**sample_base, "survived_to_horizon": False},
    ]
    valid_summary = [{
        "policy": "adaptive",
        "total_samples": 2,
        "alive_at_start_samples": 2,
        "warmup_failed_samples": 0,
        "alive_at_start_fraction": 1.0,
        "conditional_survived_to_horizon_fraction": 0.5,
        "conditional_expected_rul_years_censored": 1.0,
        "conditional_median_rul_years_censored": 1.0,
        "conditional_p05_rul_years_censored": 0.5,
        "conditional_p95_rul_years_censored": 1.5,
    }]
    t0_curve = [{
        "policy": "adaptive",
        "years_after_start": 0.0,
        "conditional_survival_probability": 1.0,
        "conditional_survival_ci95_lower": 1.0,
        "conditional_survival_ci95_upper": 1.0,
    }]
    failures = [{
        "policy": "adaptive",
        "failure_count": 1,
        "fraction_of_conditional_failures": 1.0,
        "fraction_of_alive_at_start_samples": 0.5,
    }]
    risks = [{
        "policy": "adaptive",
        "survivor_count": 1,
        "fraction_of_horizon_survivors": 1.0,
    }]

    valid = build_internal_validation_checks(
        core_rows=core,
        rul_sample_rows=samples,
        conditional_summary_rows=valid_summary,
        conditional_survival_rows=t0_curve,
        failure_mode_rows=failures,
        survivor_risk_rows=risks,
    )
    assert FAIL not in {check.status for check in valid}

    wrong_summary = [{
        **valid_summary[0],
        "conditional_survived_to_horizon_fraction": 1.0,
    }]
    fake_survivors = [{
        "policy": "adaptive",
        "survivor_count": 2,
        "fraction_of_horizon_survivors": 1.0,
    }]
    self_consistent_wrong = build_internal_validation_checks(
        core_rows=core,
        rul_sample_rows=samples,
        conditional_summary_rows=wrong_summary,
        conditional_survival_rows=t0_curve,
        survivor_risk_rows=fake_survivors,
    )
    failed_ids = {
        check.check_id for check in self_consistent_wrong
        if check.status == FAIL
    }
    assert "rul_population_accounting" in failed_ids
    assert "conditional_failure_decomposition" in failed_ids
    assert "censored_survivor_risk_decomposition" in failed_ids

    self_balancing_wrong_counts = [{
        **valid_summary[0],
        "alive_at_start_samples": 1,
        "warmup_failed_samples": 1,
        "alive_at_start_fraction": 0.5,
        "conditional_survived_to_horizon_fraction": 1.0,
    }]
    count_checks = build_internal_validation_checks(
        core_rows=core,
        rul_sample_rows=samples,
        conditional_summary_rows=self_balancing_wrong_counts,
        conditional_survival_rows=t0_curve,
        failure_mode_rows=failures,
        survivor_risk_rows=risks,
    )
    assert next(
        check for check in count_checks
        if check.check_id == "rul_population_accounting"
    ).status == FAIL

    zero_samples = [{
        **sample_base,
        "warmup_failed": True,
        "alive_at_start": False,
        "survived_to_horizon": False,
    }]
    zero_summary = [{
        "policy": "adaptive",
        "total_samples": 1,
        "alive_at_start_samples": 0,
        "warmup_failed_samples": 1,
        "alive_at_start_fraction": 0.0,
        "conditional_survived_to_horizon_fraction": None,
        "conditional_expected_rul_years_censored": None,
        "conditional_expected_rul_years_censored_ci95_lower": 0.0,
        "conditional_probability_survive_plus_1y": 0.0,
        "conditional_probability_survive_plus_2y": None,
        "conditional_probability_survive_plus_3y": None,
    }]
    zero_checks = build_internal_validation_checks(
        core_rows=core,
        rul_sample_rows=zero_samples,
        conditional_summary_rows=zero_summary,
    )
    assert next(
        check for check in zero_checks
        if check.check_id == "zero_eligible_population_semantics"
    ).status == FAIL

    missing_t0 = build_internal_validation_checks(
        core_rows=core,
        rul_sample_rows=samples,
        conditional_summary_rows=valid_summary,
        failure_mode_rows=failures,
        survivor_risk_rows=risks,
    )
    assert next(
        check for check in missing_t0
        if check.check_id == "conditional_survival_time_zero_definition"
    ).status == FAIL


def test_public_spec_sanity_records_exact_rounded_and_reference_roles() -> None:
    rows = {row.check_id: row for row in build_public_spec_sanity_rows()}
    assert rows["orbit_altitude_reference"].public_reference == "750 km"
    assert rows["orbit_inclination_reference"].public_reference == "98.5 deg"
    assert "400 km^2" in rows["scene_area_reference"].public_reference
    rate = rows["x_band_rate_rounded_proxy"]
    assert "270 Mbit/s = 2.025 GB/min" in rate.public_reference
    assert rate.relationship == "rounded_proxy_approximation"
    assert rate.implemented_proxy.startswith("2 GB/min")
    power = rows["power_reference_only"]
    assert power.public_reference == "1200 W"
    assert power.relationship == "not_directly_comparable"
    assert "does not calibrate" in power.interpretation


def test_layer_sensitivity_uses_real_fields_and_preserves_missing_values() -> None:
    base = {
        "policy": "adaptive",
        "scenario": "stochastic_post_life_events",
        "score": 1.0,
        "survived": True,
        "data_downlinked_gb": 10.0,
        "final_health": 0.9,
        "fuel_remaining_percent": 80.0,
    }
    rows = [
        {**base, "configuration_label": "final_full_stack"},
        {
            **base,
            "configuration_label": "no_autonomy",
            "score": 0.75,
            "command_packet_failures": 3,
        },
    ]
    output = build_layer_sensitivity_rows(
        rows, (("final_full_stack", "no_autonomy"),)
    )
    assert len(output) == 1
    row = output[0]
    assert tuple(row) == LAYER_SENSITIVITY_FIELDS
    assert row["reference_configuration"] == "final_full_stack"
    assert row["comparison_configuration"] == "no_autonomy"
    assert row["simulator_score_delta"] == pytest.approx(-0.25)
    assert row["command_packet_failures_baseline"] is None
    assert row["command_packet_failures_delta"] is None
    assert row["stationkeeping_selected_count_delta"] is None


def test_generated_v40b_prose_distinguishes_interpretations(
    final_quick_package,
) -> None:
    methods = (final_quick_package / "paper" / "methods_autogenerated.md").read_text(
        encoding="utf-8"
    )
    results = (final_quick_package / "paper" / "results_autogenerated.md").read_text(
        encoding="utf-8"
    )
    limitations = (
        final_quick_package / "paper" / "limitations_autogenerated.md"
    ).read_text(encoding="utf-8")
    assert "same canonical complete-stack configuration" in methods
    assert "unconditional population" in methods
    assert "conditional population" in methods
    assert "95% Wilson intervals" in methods
    assert "20-replicate" in methods
    assert "analysis seed 390" in methods
    assert "not a real lifetime model" in methods
    assert "Best unconditional expected censored RUL" in results
    assert "Conditional given-alive-at-start RUL" in results
    assert "not calibration or validation against operational data" in limitations
    assert "not external validation" in limitations
    assert "not physical causal effects" in limitations
    assert "does not extrapolate" in limitations


def test_v40b_documentation_has_no_real_calibration_or_validation_claim() -> None:
    documents = " ".join(
        " ".join(Path(name).read_text(encoding="utf-8").split())
        for name in (
            "README.md",
            "PROJECT_CANON.md",
            "FINAL_CONFIG.md",
            "KAZEOSAT_PUBLIC_SPEC.md",
        )
    )
    assert "V4.0B" in documents
    assert "internal structural validation" in documents
    assert "public-spec sanity" in documents
    assert "not calibration" in documents
    assert "not external validation" in documents
    assert "validation against real telemetry" not in documents
