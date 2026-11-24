"""Focused V3.7B bounded attitude/pointing constraint proxy tests."""

import csv
from copy import deepcopy
from dataclasses import fields

import pytest

import decision_report
import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.models import Mode, SatelliteState
from ops_sim.pointing import assess_pointing_for_hour
from ops_sim.policies import make_policy
from ops_sim.simulator import HourRecord, Simulator


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


def state_at_hour(hour: int, **changes) -> SatelliteState:
    state = SatelliteState(hours_completed=hour)
    for name, value in changes.items():
        setattr(state, name, value)
    return state


def test_pointing_model_defaults_to_legacy_everywhere() -> None:
    assert Simulator(make_policy("adaptive")).pointing_model == "legacy"
    assert run.build_parser().parse_args([]).pointing_model == "legacy"
    assert decision_report.build_parser().parse_args([]).pointing_model == "legacy"


def test_invalid_pointing_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="pointing_model"):
        Simulator(make_policy("adaptive"), pointing_model="quaternion_model")
    with pytest.raises(SystemExit):
        run.build_parser().parse_args(
            ["--pointing-model", "quaternion_model"]
        )
    with pytest.raises(SystemExit):
        decision_report.build_parser().parse_args(
            ["--pointing-model", "quaternion_model"]
        )


def test_legacy_pointing_model_preserves_v37a_behavior() -> None:
    initial = SatelliteState(soc=80.0)
    omitted = Simulator(
        make_policy("aggressive"), target_model="scene_scheduling_proxy"
    ).run(hours_as_years(4), state=deepcopy(initial))
    explicit = Simulator(
        make_policy("aggressive"),
        target_model="scene_scheduling_proxy",
        pointing_model="legacy",
    ).run(hours_as_years(4), state=deepcopy(initial))

    assert omitted.state == explicit.state
    assert omitted.metrics == explicit.metrics
    assert omitted.as_dict() == explicit.as_dict()
    assert explicit.pointing_required_hours == 0
    assert explicit.pointing_imaging_loss_gb_proxy == 0.0
    assert explicit.pointing_downlink_loss_gb_proxy == 0.0


def test_pointing_diagnostics_appear_in_outputs_and_traces(tmp_path) -> None:
    hourly_fields = {
        "pointing_model",
        "pointing_required_this_hour",
        "pointing_quality_this_hour",
        "pointing_multiplier_this_hour",
        "pointing_limited_this_hour",
        "pointing_missed_this_hour",
        "pointing_off_nadir_proxy_deg_this_hour",
        "pointing_slew_proxy_deg_this_hour",
        "pointing_reason_this_hour",
    }
    summary_fields = {
        "pointing_model",
        "pointing_required_hours",
        "pointing_limited_hours",
        "pointing_missed_hours",
        "min_pointing_quality",
        "average_pointing_quality",
        "pointing_imaging_loss_gb_proxy",
        "pointing_downlink_loss_gb_proxy",
    }
    result, _, _ = decision_report.run_decision_report(
        years=hours_as_years(1),
        policy="aggressive",
        scenario="nominal",
        seed=42,
        contact_model="synthetic",
        operator_view="omniscient",
        planning_model="reactive",
        maneuver_model="none",
        orbit_evolution_model="fixed",
        pointing_model="bounded_pointing_proxy",
        results_dir=tmp_path,
    )
    with (tmp_path / "decision_trace.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        trace_row = next(csv.DictReader(handle))

    assert hourly_fields <= {field.name for field in fields(HourRecord)}
    assert hourly_fields <= set(run.STATE_FIELDS)
    assert hourly_fields <= set(decision_report.POINTING_TRACE_FIELDS)
    assert summary_fields <= set(run.SUMMARY_FIELDS)
    assert summary_fields <= set(run.MONTE_CARLO_FIELDS)
    assert summary_fields <= result.as_dict().keys()
    assert summary_fields <= run._summary_row(result, hours_as_years(1)).keys()
    assert trace_row["pointing_model"] == "bounded_pointing_proxy"
    assert "## Attitude/pointing constraints" in (
        tmp_path / "decision_summary.md"
    ).read_text(encoding="utf-8")


def test_imaging_pointing_limitation_reduces_generated_data() -> None:
    initial = state_at_hour(1, soc=80.0, adcs_health=0.4)
    records = []
    legacy = Simulator(
        make_policy("aggressive"), pointing_model="legacy"
    ).run(
        hours_as_years(1), state=deepcopy(initial), start_hour=1
    )
    bounded = Simulator(
        make_policy("aggressive"), pointing_model="bounded_pointing_proxy"
    ).run(
        hours_as_years(1),
        state=deepcopy(initial),
        start_hour=1,
        on_hour=records.append,
    )

    record = records[0]
    assert record.mode == Mode.IMAGING.value
    assert record.pointing_required_this_hour is True
    assert record.pointing_multiplier_this_hour < 1.0
    assert record.pointing_limited_this_hour is True
    assert bounded.state.total_data_generated_gb < (
        legacy.state.total_data_generated_gb
    )
    assert bounded.pointing_imaging_loss_gb_proxy > 0.0


def test_downlink_pointing_limitation_reduces_downlinked_data() -> None:
    initial = SatelliteState(
        soc=80.0, adcs_health=0.4, data_buffer_gb=500.0
    )
    records = []
    legacy = Simulator(
        make_policy("aggressive"), pointing_model="legacy"
    ).run(hours_as_years(1), state=deepcopy(initial))
    bounded = Simulator(
        make_policy("aggressive"), pointing_model="bounded_pointing_proxy"
    ).run(
        hours_as_years(1),
        state=deepcopy(initial),
        on_hour=records.append,
    )

    record = records[0]
    assert record.mode == Mode.DOWNLINK.value
    assert record.pointing_multiplier_this_hour < 1.0
    assert bounded.state.total_data_downlinked_gb < (
        legacy.state.total_data_downlinked_gb
    )
    assert bounded.pointing_downlink_loss_gb_proxy > 0.0


@pytest.mark.parametrize(
    "mode",
    [
        Mode.SAFE,
        Mode.STANDBY,
        Mode.BACKUP,
        Mode.EMERGENCY_BEACON,
        Mode.MANEUVER,
    ],
)
def test_non_pointing_modes_are_neutral(mode: Mode) -> None:
    assessment = assess_pointing_for_hour(
        pointing_model="bounded_pointing_proxy",
        hour=5,
        mode=mode,
        state=SatelliteState(adcs_health=0.0),
    )

    assert assessment.pointing_required_this_hour is False
    assert assessment.pointing_multiplier_this_hour == 1.0
    assert assessment.pointing_limited_this_hour is False
    assert assessment.pointing_missed_this_hour is False


def test_no_target_opportunity_remains_zero_regardless_of_pointing() -> None:
    records = []
    result = Simulator(
        make_policy("aggressive"),
        target_model="scene_scheduling_proxy",
        pointing_model="bounded_pointing_proxy",
    ).run(
        hours_as_years(1),
        state=state_at_hour(1, soc=80.0, adcs_health=0.4),
        start_hour=1,
        on_hour=records.append,
    )

    record = records[0]
    assert record.mode == Mode.IMAGING.value
    assert record.target_data_multiplier_this_hour == 0.0
    assert record.pointing_multiplier_this_hour < 1.0
    assert result.state.total_data_generated_gb == 0.0
    assert result.state.total_images_taken == 0
    assert result.target_area_imaged_km2 == 0.0


def test_critical_pointing_keeps_selection_but_collects_no_area() -> None:
    records = []
    result = Simulator(
        make_policy("aggressive"),
        target_model="scene_scheduling_proxy",
        pointing_model="bounded_pointing_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, adcs_health=0.2),
        on_hour=records.append,
    )

    record = records[0]
    assert record.target_selected_this_hour is True
    assert record.pointing_multiplier_this_hour == 0.0
    assert result.target_selected_hours == 1
    assert result.target_area_imaged_km2 == 0.0
    assert result.state.total_data_generated_gb == 0.0
    assert result.state.total_images_taken == 0


def test_target_opportunity_combines_with_pointing_multiplier() -> None:
    initial = SatelliteState(soc=80.0, adcs_health=0.4)
    records = []
    target_only = Simulator(
        make_policy("aggressive"),
        target_model="scene_scheduling_proxy",
        pointing_model="legacy",
    ).run(hours_as_years(1), state=deepcopy(initial))
    bounded = Simulator(
        make_policy("aggressive"),
        target_model="scene_scheduling_proxy",
        pointing_model="bounded_pointing_proxy",
    ).run(
        hours_as_years(1),
        state=deepcopy(initial),
        on_hour=records.append,
    )

    record = records[0]
    assert record.target_opportunity_this_hour is True
    assert record.target_selected_this_hour is True
    assert 0.0 < record.pointing_multiplier_this_hour < 1.0
    assert bounded.target_selected_hours == 1
    assert bounded.target_area_imaged_km2 == pytest.approx(
        400.0 * record.pointing_multiplier_this_hour
    )
    assert 0.0 < bounded.target_area_imaged_km2 < 400.0
    assert 0.0 < bounded.state.total_data_generated_gb < (
        target_only.state.total_data_generated_gb
    )
    assert bounded.state.total_data_generated_gb == pytest.approx(
        target_only.state.total_data_generated_gb
        * record.pointing_multiplier_this_hour
    )
