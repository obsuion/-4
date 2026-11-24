"""Focused V3.6A bounded power/eclipse proxy tests."""

from copy import deepcopy
from dataclasses import fields
from pathlib import Path

import pytest

import decision_report
import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import make_policy
from ops_sim.power import compute_sunlight_factor
from ops_sim.simulator import HourRecord, Simulator


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


def test_power_model_defaults_to_legacy_everywhere() -> None:
    simulator = Simulator(make_policy("adaptive"))

    assert simulator.power_model == "legacy"
    assert run.build_parser().parse_args([]).power_model == "legacy"
    assert decision_report.build_parser().parse_args([]).power_model == "legacy"


def test_invalid_power_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="power_model"):
        Simulator(make_policy("adaptive"), power_model="solar_twin")
    with pytest.raises(SystemExit):
        run.build_parser().parse_args(["--power-model", "solar_twin"])


def test_legacy_power_model_preserves_established_soc_delta() -> None:
    state = SatelliteState(
        soc=50.0,
        solar_health=0.80,
        battery_health=0.75,
    )
    expected_eps_health = state.eps_health(DEFAULT_CONFIG)
    expected_delta = (
        DEFAULT_CONFIG.soc_safe_delta
        * state.solar_health
        * expected_eps_health
    )
    simulator = Simulator(make_policy("adaptive"), power_model="legacy")

    assessment = simulator._execute_mode(
        state, Mode.SAFE, ContactInfo(), hour=1
    )

    assert state.soc == pytest.approx(50.0 + expected_delta)
    assert assessment.soc_delta_power_model == pytest.approx(expected_delta)
    assert assessment.sunlight_factor is None
    assert assessment.eclipse is None


def test_eclipse_proxy_records_sunlight_and_eclipse_hours() -> None:
    records = []
    result = Simulator(
        make_policy("adaptive"), power_model="eclipse_proxy"
    ).run(hours_as_years(12), on_hour=records.append)

    assert len(records) == 12
    assert result.eclipse_hours > 0
    assert result.sunlight_hours > 0
    assert result.eclipse_hours + result.sunlight_hours == 12
    assert {record.eclipse_this_hour for record in records} == {False, True}
    assert {record.sunlight_factor_this_hour for record in records} == {
        0.0,
        1.0,
    }
    assert result.eclipse_fraction_observed == pytest.approx(
        result.eclipse_hours / 12
    )
    assert result.min_sunlight_factor == 0.0
    assert 0.0 < result.average_sunlight_factor < 1.0


def test_eclipse_proxy_removes_positive_charging_in_eclipse() -> None:
    eclipse_hour = next(
        hour
        for hour in range(24)
        if compute_sunlight_factor(hour) == 0.0
    )
    sunlight_hour = next(
        hour
        for hour in range(24)
        if compute_sunlight_factor(hour) == 1.0
    )
    initial = SatelliteState(soc=50.0)
    eclipsed = deepcopy(initial)
    sunlit = deepcopy(initial)
    simulator = Simulator(
        make_policy("adaptive"), power_model="eclipse_proxy"
    )

    eclipse_assessment = simulator._execute_mode(
        eclipsed, Mode.SAFE, ContactInfo(), hour=eclipse_hour
    )
    sunlight_assessment = simulator._execute_mode(
        sunlit, Mode.SAFE, ContactInfo(), hour=sunlight_hour
    )

    assert eclipse_assessment.eclipse is True
    assert eclipse_assessment.soc_delta_power_model == 0.0
    assert eclipsed.soc == initial.soc
    assert sunlight_assessment.eclipse is False
    assert sunlight_assessment.soc_delta_power_model > 0.0
    assert sunlit.soc > initial.soc


def test_power_diagnostics_appear_in_hour_and_summary_fields() -> None:
    hourly_fields = {
        "power_model",
        "sunlight_factor_this_hour",
        "eclipse_this_hour",
        "eclipse_fraction_reference",
        "power_load_proxy_w_this_hour",
        "power_generation_proxy_w_this_hour",
        "net_power_proxy_w_this_hour",
        "soc_delta_power_model_this_hour",
    }
    summary_fields = {
        "power_model",
        "eclipse_hours",
        "sunlight_hours",
        "eclipse_fraction_observed",
        "min_sunlight_factor",
        "average_sunlight_factor",
    }
    result = Simulator(
        make_policy("adaptive"), power_model="eclipse_proxy"
    ).run(hours_as_years(2))

    assert hourly_fields <= {field.name for field in fields(HourRecord)}
    assert hourly_fields <= set(run.STATE_FIELDS)
    assert hourly_fields <= set(decision_report.POWER_TRACE_FIELDS)
    assert summary_fields <= set(run.SUMMARY_FIELDS)
    assert summary_fields <= set(run.MONTE_CARLO_FIELDS)
    assert summary_fields <= result.as_dict().keys()
    assert summary_fields <= run._summary_row(result, hours_as_years(2)).keys()


def test_public_power_reference_is_metadata_not_calibration() -> None:
    root = Path(__file__).resolve().parents[1]
    documents = " ".join(
        (root / name).read_text(encoding="utf-8").lower()
        for name in (
            "README.md",
            "PROJECT_CANON.md",
            "KAZEOSAT_PUBLIC_SPEC.md",
        )
    )

    assert DEFAULT_CONFIG.public_power_reference_w == 1200.0
    assert "1200 w" in documents
    assert "does not calibrate" in documents
    assert "not a real eps" in documents


def test_legacy_selector_matches_omitted_short_run() -> None:
    initial = SatelliteState(soc=65.0, data_buffer_gb=100.0)
    omitted = Simulator(make_policy("adaptive")).run(
        hours_as_years(4), state=deepcopy(initial)
    )
    explicit = Simulator(
        make_policy("adaptive"), power_model="legacy"
    ).run(hours_as_years(4), state=deepcopy(initial))

    assert omitted.state == explicit.state
    assert omitted.metrics == explicit.metrics
    assert omitted.power_model == explicit.power_model == "legacy"
