"""Focused V3.6B bounded thermal/load stress proxy tests."""

import csv
from copy import deepcopy
from dataclasses import fields, replace

import pytest

import decision_report
import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.models import Mode, SatelliteState
from ops_sim.policies import make_policy
from ops_sim.power import compute_sunlight_factor
from ops_sim.simulator import HourRecord, Simulator


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


def test_thermal_model_defaults_to_legacy_everywhere() -> None:
    assert Simulator(make_policy("adaptive")).thermal_model == "legacy"
    assert run.build_parser().parse_args([]).thermal_model == "legacy"
    assert decision_report.build_parser().parse_args([]).thermal_model == "legacy"


def test_invalid_thermal_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="thermal_model"):
        Simulator(make_policy("adaptive"), thermal_model="heat_twin")
    with pytest.raises(SystemExit):
        run.build_parser().parse_args(["--thermal-model", "heat_twin"])


def test_legacy_selector_matches_omitted_run_and_is_neutral() -> None:
    initial = SatelliteState(soc=65.0, data_buffer_gb=100.0)
    omitted_records = []
    explicit_records = []
    omitted = Simulator(make_policy("adaptive")).run(
        hours_as_years(4), state=deepcopy(initial), on_hour=omitted_records.append
    )
    explicit = Simulator(
        make_policy("adaptive"), thermal_model="legacy"
    ).run(
        hours_as_years(4), state=deepcopy(initial), on_hour=explicit_records.append
    )

    assert omitted.state == explicit.state
    assert omitted.metrics == explicit.metrics
    assert omitted.total_thermal_degradation == 0.0
    assert explicit.total_thermal_degradation == 0.0
    assert all(record.thermal_stress_this_hour is None for record in explicit_records)
    assert all(record.thermal_degradation_this_hour == 0.0 for record in explicit_records)


def test_thermal_diagnostics_appear_in_hour_summary_and_decision_fields() -> None:
    hourly_fields = {
        "thermal_model",
        "thermal_load_proxy_this_hour",
        "thermal_hot_stress_this_hour",
        "thermal_cold_stress_this_hour",
        "thermal_stress_this_hour",
        "thermal_degradation_this_hour",
        "thermal_reason_this_hour",
    }
    summary_fields = {
        "thermal_model",
        "thermal_hot_stress_hours",
        "thermal_cold_stress_hours",
        "thermal_stress_hours",
        "max_thermal_stress",
        "total_thermal_degradation",
        "min_thermal_health",
    }
    result = Simulator(
        make_policy("adaptive"), thermal_model="load_stress_proxy"
    ).run(hours_as_years(2))

    assert hourly_fields <= {field.name for field in fields(HourRecord)}
    assert hourly_fields <= set(run.STATE_FIELDS)
    assert hourly_fields <= set(decision_report.THERMAL_TRACE_FIELDS)
    assert summary_fields <= set(run.SUMMARY_FIELDS)
    assert summary_fields <= set(run.MONTE_CARLO_FIELDS)
    assert summary_fields <= result.as_dict().keys()
    assert summary_fields <= run._summary_row(result, hours_as_years(2)).keys()


def test_sunlit_imaging_produces_hot_stress_and_degrades_thermal_health() -> None:
    records = []
    result = Simulator(
        make_policy("adaptive"),
        power_model="eclipse_proxy",
        thermal_model="load_stress_proxy",
    ).run(hours_as_years(1), on_hour=records.append)

    record = records[0]
    assert record.mode == Mode.IMAGING.value
    assert record.eclipse_this_hour is False
    assert record.thermal_hot_stress_this_hour > 0.0
    assert record.thermal_degradation_this_hour > 0.0
    assert result.state.thermal_health < 1.0


def test_eclipsed_safe_mode_produces_cold_stress_and_degrades_health() -> None:
    eclipse_hour = next(
        hour for hour in range(24) if compute_sunlight_factor(hour) == 0.0
    )
    initial = SatelliteState(soc=20.0, hours_completed=eclipse_hour)
    records = []
    result = Simulator(
        make_policy("adaptive"),
        power_model="eclipse_proxy",
        thermal_model="load_stress_proxy",
    ).run(
        hours_as_years(1),
        state=initial,
        start_hour=eclipse_hour,
        on_hour=records.append,
    )

    record = records[0]
    assert record.mode == Mode.SAFE.value
    assert record.eclipse_this_hour is True
    assert record.thermal_cold_stress_this_hour > 0.0
    assert record.thermal_degradation_this_hour > 0.0
    assert result.state.thermal_health < 1.0


def test_thermal_degradation_is_bounded_and_health_is_clamped() -> None:
    config = replace(
        DEFAULT_CONFIG,
        thermal_hot_stress_degradation_per_hour=1.0,
        thermal_high_load_stress_degradation_per_hour=1.0,
        thermal_stress_max_per_hour=0.01,
    )
    initial = SatelliteState(thermal_health=0.001)
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        power_model="eclipse_proxy",
        thermal_model="load_stress_proxy",
    ).run(hours_as_years(1), state=initial, on_hour=records.append)

    assert records[0].thermal_degradation_this_hour <= config.thermal_stress_max_per_hour
    assert records[0].thermal_degradation_this_hour <= 0.001
    assert result.state.thermal_health >= config.minimum_health


def test_power_and_thermal_models_interact_without_inventing_legacy_sunlight() -> None:
    eclipse_records = []
    legacy_records = []
    Simulator(
        make_policy("adaptive"),
        power_model="eclipse_proxy",
        thermal_model="load_stress_proxy",
    ).run(hours_as_years(1), on_hour=eclipse_records.append)
    Simulator(
        make_policy("adaptive"),
        power_model="legacy",
        thermal_model="load_stress_proxy",
    ).run(hours_as_years(1), on_hour=legacy_records.append)

    assert eclipse_records[0].sunlight_factor_this_hour is not None
    assert eclipse_records[0].thermal_stress_this_hour is not None
    assert legacy_records[0].sunlight_factor_this_hour is None
    assert legacy_records[0].eclipse_this_hour is None
    assert legacy_records[0].thermal_hot_stress_this_hour == 0.0
    assert legacy_records[0].thermal_load_proxy_this_hour > 0.0
    assert legacy_records[0].thermal_stress_this_hour > 0.0


def test_decision_trace_and_summary_include_thermal_diagnostics(tmp_path) -> None:
    result, _, _ = decision_report.run_decision_report(
        years=hours_as_years(1),
        policy="adaptive",
        scenario="nominal",
        seed=42,
        contact_model="synthetic",
        operator_view="omniscient",
        planning_model="reactive",
        maneuver_model="none",
        orbit_evolution_model="fixed",
        power_model="eclipse_proxy",
        thermal_model="load_stress_proxy",
        results_dir=tmp_path,
    )
    with (tmp_path / "decision_trace.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        row = next(csv.DictReader(handle))
    summary = (tmp_path / "decision_summary.md").read_text(encoding="utf-8")

    assert row["thermal_model"] == "load_stress_proxy"
    assert row["thermal_stress_this_hour"] != ""
    assert result.thermal_model == "load_stress_proxy"
    assert "## Thermal/load stress" in summary
    assert "Total added thermal degradation" in summary
