"""Focused V3.7A deterministic target/scene scheduling proxy tests."""

import csv
from copy import deepcopy
from dataclasses import fields
from pathlib import Path

import pytest

import decision_report
import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.models import Mode, SatelliteState
from ops_sim.policies import make_policy
from ops_sim.simulator import HourRecord, Simulator
from ops_sim.targets import assess_target_for_hour


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


def state_at_hour(hour: int, **changes) -> SatelliteState:
    state = SatelliteState(hours_completed=hour)
    for name, value in changes.items():
        setattr(state, name, value)
    return state


def test_target_model_defaults_to_legacy_everywhere() -> None:
    assert Simulator(make_policy("adaptive")).target_model == "legacy"
    assert run.build_parser().parse_args([]).target_model == "legacy"
    assert decision_report.build_parser().parse_args([]).target_model == "legacy"


def test_invalid_target_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="target_model"):
        Simulator(make_policy("adaptive"), target_model="real_catalog")
    with pytest.raises(SystemExit):
        run.build_parser().parse_args(["--target-model", "real_catalog"])


def test_legacy_target_model_preserves_v36_imaging_behavior() -> None:
    initial = SatelliteState(soc=80.0)
    omitted_records = []
    explicit_records = []
    omitted = Simulator(make_policy("aggressive")).run(
        hours_as_years(2),
        state=deepcopy(initial),
        on_hour=omitted_records.append,
    )
    explicit = Simulator(
        make_policy("aggressive"), target_model="legacy"
    ).run(
        hours_as_years(2),
        state=deepcopy(initial),
        on_hour=explicit_records.append,
    )

    assert omitted.state == explicit.state
    assert omitted.metrics == explicit.metrics
    assert omitted.state.total_data_generated_gb > 0.0
    assert explicit_records[0].target_data_multiplier_this_hour == 1.0
    assert explicit_records[0].target_opportunity_this_hour is None
    assert explicit.target_opportunity_hours == 0
    assert explicit.target_missed_hours == 0


def test_target_diagnostics_appear_in_hour_summary_and_trace_fields() -> None:
    hourly_fields = {
        "target_model",
        "target_opportunity_this_hour",
        "target_selected_this_hour",
        "target_scene_id_this_hour",
        "target_scene_area_km2_this_hour",
        "target_priority_this_hour",
        "target_imagery_mode_this_hour",
        "target_data_multiplier_this_hour",
        "target_missed_reason_this_hour",
        "target_reason_this_hour",
    }
    summary_fields = {
        "target_model",
        "target_opportunity_hours",
        "target_selected_hours",
        "target_missed_hours",
        "target_area_imaged_km2",
        "target_priority_score_total",
        "target_panchromatic_scenes",
        "target_multispectral_scenes",
    }
    result = Simulator(
        make_policy("aggressive"), target_model="scene_scheduling_proxy"
    ).run(hours_as_years(2))

    assert hourly_fields <= {field.name for field in fields(HourRecord)}
    assert hourly_fields <= set(run.STATE_FIELDS)
    assert hourly_fields <= set(decision_report.TARGET_TRACE_FIELDS)
    assert summary_fields <= set(run.SUMMARY_FIELDS)
    assert summary_fields <= set(run.MONTE_CARLO_FIELDS)
    assert summary_fields <= result.as_dict().keys()
    assert summary_fields <= run._summary_row(result, hours_as_years(2)).keys()


def test_imaging_with_opportunity_selects_default_scene() -> None:
    records = []
    result = Simulator(
        make_policy("aggressive"),
        target_model="scene_scheduling_proxy",
        pointing_model="legacy",
    ).run(hours_as_years(1), on_hour=records.append)

    record = records[0]
    assert record.hour == 0
    assert record.mode == Mode.IMAGING.value
    assert record.target_opportunity_this_hour is True
    assert record.target_selected_this_hour is True
    assert record.target_scene_id_this_hour == "scene_00000000"
    assert record.target_scene_area_km2_this_hour == pytest.approx(400.0)
    assert record.target_imagery_mode_this_hour in {
        "panchromatic", "multispectral"
    }
    assert record.target_data_multiplier_this_hour == 1.0
    assert result.state.total_data_generated_gb > 0.0
    assert result.target_area_imaged_km2 == pytest.approx(400.0)


def test_imaging_without_opportunity_generates_no_payload_data() -> None:
    records = []
    result = Simulator(
        make_policy("aggressive"), target_model="scene_scheduling_proxy"
    ).run(
        hours_as_years(1),
        state=state_at_hour(1, soc=80.0),
        start_hour=1,
        on_hour=records.append,
    )

    record = records[0]
    assert record.mode == Mode.IMAGING.value
    assert record.target_opportunity_this_hour is False
    assert record.target_selected_this_hour is False
    assert record.target_data_multiplier_this_hour == 0.0
    assert record.target_missed_reason_this_hour == "no_target_opportunity"
    assert result.state.total_data_generated_gb == 0.0
    assert result.state.total_images_taken == 0
    assert result.target_area_imaged_km2 == 0.0
    assert result.target_missed_hours == 1


def test_opportunity_is_missed_when_final_mode_is_not_imaging() -> None:
    records = []
    Simulator(
        make_policy("adaptive"), target_model="scene_scheduling_proxy"
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=20.0),
        on_hour=records.append,
    )

    record = records[0]
    assert record.mode == Mode.SAFE.value
    assert record.target_opportunity_this_hour is True
    assert record.target_selected_this_hour is False
    assert record.target_missed_reason_this_hour == "not_imaging_mode"


def test_public_scene_values_are_metadata_not_productivity_calibration() -> None:
    assessment = assess_target_for_hour(
        target_model="scene_scheduling_proxy",
        hour=0,
        mode=Mode.IMAGING,
        state=SatelliteState(),
    )
    result = Simulator(
        make_policy("aggressive"), target_model="scene_scheduling_proxy"
    ).run(hours_as_years(24))
    documents = " ".join(
        (Path(__file__).resolve().parents[1] / name)
        .read_text(encoding="utf-8")
        .lower()
        for name in ("README.md", "PROJECT_CANON.md", "KAZEOSAT_PUBLIC_SPEC.md")
    )

    assert DEFAULT_CONFIG.target_scene_width_km == 20.0
    assert DEFAULT_CONFIG.target_scene_height_km == 20.0
    assert assessment.target_scene_area_km2_this_hour == 400.0
    assert DEFAULT_CONFIG.public_productivity_reference_km2_per_day == 220000.0
    assert result.target_area_imaged_km2 != 220000.0
    assert "does not calibrate" in documents
    assert "not a real target catalog" in documents


def test_decision_trace_and_summary_include_target_diagnostics(tmp_path) -> None:
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
        target_model="scene_scheduling_proxy",
        results_dir=tmp_path,
    )
    with (tmp_path / "decision_trace.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        row = next(csv.DictReader(handle))
    summary = (tmp_path / "decision_summary.md").read_text(encoding="utf-8")

    assert row["target_model"] == "scene_scheduling_proxy"
    assert row["target_opportunity_this_hour"] == "True"
    assert row["target_scene_area_km2_this_hour"] == "400.0"
    assert result.target_model == "scene_scheduling_proxy"
    assert "## Target/scene scheduling" in summary
