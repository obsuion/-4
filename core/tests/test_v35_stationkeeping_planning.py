"""Focused V3.5 drift-aware stationkeeping planning and report tests."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

import decision_report
import run
from ops_sim.config import DEFAULT_CONFIG, SimulationConfig
from ops_sim.contacts import (
    GeometryContactModel,
    GeometryContactSummary,
    GroundStation,
    SyntheticContactModel,
)
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import make_policy
from ops_sim.scenarios import Scenario, StochasticPostLifeEventsScenario
from ops_sim.simulator import Simulator
from stationkeeping_report import run_stationkeeping_report


def hours_as_years(hours: int, config=DEFAULT_CONFIG) -> float:
    return hours / config.hours_per_year


def critical_state(config=DEFAULT_CONFIG, **changes) -> SatelliteState:
    values = {
        "soc": 80.0,
        "delta_v_remaining_m_per_s": 10.0,
        "propulsion_health": 1.0,
        "orbit_drift_proxy_km": (
            config.orbit_drift_critical_threshold_km + 0.10
        ),
    }
    values.update(changes)
    return SatelliteState(**values)


class RemoveAllContactsScenario(Scenario):
    name = "remove_all_contacts"

    def modify_contacts(
        self, contact: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo()


class DriftDiagnosticGeometryModel(GeometryContactModel):
    """Expose pre-decision phase error through base data-contact minutes."""

    def __init__(self, config: SimulationConfig):
        super().__init__(
            GroundStation(0.0, 0.0, -90.0),
            config,
            step_seconds=config.seconds_per_hour,
        )

    def contact_summary_at_hour_for_config(
        self, hour: int, orbit_config: SimulationConfig
    ) -> GeometryContactSummary:
        minutes = min(
            60.0,
            abs(
                orbit_config.orbit_initial_phase_deg
                - self.config.orbit_initial_phase_deg
            ) * 1000.0,
        )
        return GeometryContactSummary(
            hour=hour,
            raw_visible_seconds=minutes * 60.0,
            usable_cmd_seconds=minutes * 60.0,
            usable_data_seconds=minutes * 60.0,
            cmd_contact_min=minutes,
            data_contact_min=minutes,
            max_elevation_deg=minutes,
            min_range_km=1000.0,
            first_visible_offset_seconds=0.0 if minutes else None,
            last_visible_offset_seconds=minutes * 60.0 if minutes else None,
        )


def test_defaults_preserve_legacy_stationkeeping_behavior() -> None:
    parser_args = run.build_parser().parse_args([])
    omitted = Simulator(make_policy("adaptive"))
    explicit = Simulator(
        make_policy("adaptive"), stationkeeping_planning_model="legacy"
    )

    assert parser_args.stationkeeping_planning_model == "legacy"
    assert omitted.stationkeeping_planning_model == "legacy"
    first = omitted.run(
        hours_as_years(1), state=critical_state()
    )
    second = explicit.run(
        hours_as_years(1), state=deepcopy(critical_state())
    )
    assert first.state.mode == second.state.mode
    assert first.state.maneuver_count == second.state.maneuver_count == 0
    assert first.state.orbit_drift_proxy_km == pytest.approx(
        second.state.orbit_drift_proxy_km
    )


def test_invalid_stationkeeping_planning_selector_is_rejected() -> None:
    with pytest.raises(ValueError, match="stationkeeping_planning_model"):
        Simulator(
            make_policy("adaptive"),
            stationkeeping_planning_model="unbounded",
        )
    with pytest.raises(SystemExit):
        run.build_parser().parse_args(
            ["--stationkeeping-planning-model", "unbounded"]
        )


def test_runner_and_decision_report_expose_selector_and_output_fields() -> None:
    decision_args = decision_report.build_parser().parse_args([])
    assert decision_args.stationkeeping_planning_model == "legacy"

    summary_fields = {
        "stationkeeping_planning_model",
        "stationkeeping_recommended_count",
        "stationkeeping_selected_count",
        "stationkeeping_deferred_count",
        "stationkeeping_unresolved_critical_drift_hours",
        "max_orbit_drift_proxy_km",
        "max_orbit_groundtrack_error_km",
        "max_orbit_phase_error_deg",
    }
    assert summary_fields <= set(run.SUMMARY_FIELDS)
    assert summary_fields <= set(run.MONTE_CARLO_FIELDS)
    assert {
        "stationkeeping_planning_model",
        "stationkeeping_drift_risk_class_this_hour",
        "stationkeeping_recommended_this_hour",
        "stationkeeping_selected_this_hour",
        "stationkeeping_deferred_reason_this_hour",
    } <= set(run.STATE_FIELDS)


@pytest.mark.parametrize(
    ("maneuver_model", "orbit_model", "deferred_reason"),
    [
        ("none", "drift_proxy", "maneuver_model_disabled"),
        ("stationkeeping_proxy", "fixed", "orbit_evolution_fixed"),
    ],
)
def test_drift_aware_model_combination_gating_is_diagnostic(
    maneuver_model: str,
    orbit_model: str,
    deferred_reason: str,
) -> None:
    rows = []
    result = Simulator(
        make_policy("adaptive"),
        maneuver_model=maneuver_model,
        orbit_evolution_model=orbit_model,
        stationkeeping_planning_model="drift_aware",
    ).run(
        hours_as_years(1),
        state=critical_state(),
        on_hour=rows.append,
    )

    assert result.state.maneuver_count == 0
    assert result.stationkeeping_selected_count == 0
    assert rows[0].stationkeeping_recommended_this_hour is True
    assert rows[0].stationkeeping_feasible_this_hour is False
    assert (
        rows[0].stationkeeping_deferred_reason_this_hour
        == deferred_reason
    )


def test_critical_drift_selects_existing_stationkeeping_path() -> None:
    state = critical_state()
    drift_before = state.orbit_drift_proxy_km
    rows = []
    result = Simulator(
        make_policy("adaptive"),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
    ).run(
        hours_as_years(1), state=state, on_hour=rows.append
    )

    assert result.state.mode == Mode.MANEUVER
    assert result.state.maneuver_count == 1
    assert result.stationkeeping_selected_count == 1
    assert rows[0].stationkeeping_selected_this_hour is True
    assert rows[0].maneuver_executed_this_hour is True
    assert result.state.orbit_drift_proxy_km < drift_before


def test_backup_allows_bounded_critical_stationkeeping_override() -> None:
    state = critical_state(backup_mode=True)
    drift_before = state.orbit_drift_proxy_km
    rows = []
    result = Simulator(
        make_policy("adaptive"),
        RemoveAllContactsScenario(),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
    ).run(
        hours_as_years(1), state=state, on_hour=rows.append
    )

    assert rows[0].stationkeeping_selected_this_hour is True
    assert rows[0].mode == Mode.MANEUVER.value
    assert result.state.mode == Mode.MANEUVER
    assert result.state.maneuver_count == 1
    assert result.state.orbit_drift_proxy_km < drift_before


def test_projected_critical_drift_is_scheduled_early_in_daily_plan() -> None:
    config = replace(
        DEFAULT_CONFIG,
        plan_duration_hours=6,
        orbit_drift_proxy_km_per_day=0.60,
        orbit_drift_warning_threshold_km=0.45,
        orbit_drift_critical_threshold_km=0.50,
    )
    state = critical_state(
        config,
        orbit_drift_proxy_km=0.35,
    )
    rows = []
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=SyntheticContactModel(config),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
    ).run(
        hours_as_years(1, config), state=state, on_hour=rows.append
    )

    assert rows[0].orbit_drift_warning is False
    assert rows[0].planned_mode == Mode.MANEUVER.value
    assert rows[0].stationkeeping_selected_this_hour is True
    assert result.state.maneuver_count == 1


@pytest.mark.parametrize(
    ("state_changes", "reason"),
    [
        ({"delta_v_remaining_m_per_s": 0.05}, "insufficient_delta_v"),
        ({"soc": 5.0}, "critical_energy_safe_priority"),
        ({"propulsion_health": 0.10}, "propulsion_health_below_threshold"),
    ],
)
def test_critical_drift_resource_constraints_defer_without_consumption(
    state_changes: dict[str, float], reason: str
) -> None:
    state = critical_state(**state_changes)
    delta_v_before = state.delta_v_remaining_m_per_s
    rows = []
    result = Simulator(
        make_policy("adaptive"),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
    ).run(
        hours_as_years(1), state=state, on_hour=rows.append
    )

    assert result.state.maneuver_count == 0
    assert result.state.delta_v_remaining_m_per_s == delta_v_before
    assert result.stationkeeping_deferred_count == 1
    assert rows[0].stationkeeping_deferred_reason_this_hour == reason


def test_emergency_beacon_has_priority_over_stationkeeping() -> None:
    state = critical_state(
        emergency_beacon_mode=True,
        hours_since_contact=DEFAULT_CONFIG.emergency_after_hours,
    )
    rows = []
    result = Simulator(
        make_policy("adaptive"),
        RemoveAllContactsScenario(),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
    ).run(
        hours_as_years(1), state=state, on_hour=rows.append
    )

    assert result.state.mode == Mode.EMERGENCY_BEACON
    assert result.state.maneuver_count == 0
    assert rows[0].stationkeeping_selected_this_hour is False
    assert rows[0].stationkeeping_blocked_by_priority_this_hour is True
    assert (
        rows[0].stationkeeping_deferred_reason_this_hour
        == "emergency_beacon_priority"
    )


def test_uploaded_debris_tca_response_has_priority_over_stationkeeping() -> None:
    event = ExternalEvent(
        1,
        "debris_conjunction",
        1.0,
        1,
        "adcs_health",
        0.02,
        "priority test conjunction",
    )
    catalog = EventCatalog(
        [event], 42, "stochastic_post_life_events", 2
    )
    scenario = StochasticPostLifeEventsScenario(event_catalog=catalog)
    rows = []
    result = Simulator(
        make_policy("adaptive"),
        scenario,
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
        event_lifecycle_model="warning_proxy",
    ).run(
        hours_as_years(2), state=critical_state(), on_hour=rows.append
    )

    assert rows[1].lifecycle_uploaded_count == 1
    assert rows[1].debris_avoidance_executed_this_hour is True
    assert rows[1].stationkeeping_selected_this_hour is False
    assert rows[1].stationkeeping_blocked_by_priority_this_hour is True
    assert (
        rows[1].stationkeeping_deferred_reason_this_hour
        == "debris_avoidance_priority"
    )
    assert result.state.debris_avoidance_executed_count == 1


def test_stationkeeping_changes_only_later_geometry_contacts() -> None:
    config = replace(
        DEFAULT_CONFIG,
        stationkeeping_phase_correction_fraction=1.0,
        orbit_drift_reduction_per_maneuver_km=0.60,
    )
    rows = []
    Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=DriftDiagnosticGeometryModel(config),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
    ).run(
        hours_as_years(2, config),
        state=critical_state(config),
        on_hour=rows.append,
    )

    assert rows[0].stationkeeping_selected_this_hour is True
    assert rows[0].base_data_contact_min > 0.0
    assert rows[1].base_data_contact_min < rows[0].base_data_contact_min


def test_drift_aware_planning_does_not_refresh_telemetry_or_see_events() -> None:
    config = replace(
        DEFAULT_CONFIG,
        plan_duration_hours=6,
        orbit_drift_proxy_km_per_day=0.60,
        orbit_drift_warning_threshold_km=0.40,
        orbit_drift_critical_threshold_km=0.50,
    )
    future_event = ExternalEvent(
        2,
        "debris_conjunction",
        1.0,
        1,
        "adcs_health",
        0.02,
        "future hidden conjunction",
    )
    future_scenario = StochasticPostLifeEventsScenario(
        event_catalog=EventCatalog(
            [future_event], 7, "stochastic_post_life_events", 6
        )
    )

    def plan_for(scenario: Scenario):
        result = Simulator(
            make_policy("adaptive", config),
            scenario,
            config=config,
            contact_model=SyntheticContactModel(config),
            operator_view="delayed_telemetry",
            planning_model="risk_aware",
            maneuver_model="stationkeeping_proxy",
            orbit_evolution_model="drift_proxy",
            stationkeeping_planning_model="drift_aware",
        ).run(hours_as_years(1, config))
        return result.state.current_plan

    baseline = plan_for(Scenario())
    with_future_event = plan_for(future_scenario)
    assert baseline is not None
    assert with_future_event is not None
    assert with_future_event.planned_modes == baseline.planned_modes

    rows = []
    Simulator(
        make_policy("adaptive", config),
        RemoveAllContactsScenario(),
        config=config,
        contact_model=SyntheticContactModel(config),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
    ).run(hours_as_years(2, config), on_hour=rows.append)
    assert all(not row.telemetry_updated_this_hour for row in rows)


def test_stationkeeping_report_writes_bounded_outputs(tmp_path) -> None:
    result, records, summary = run_stationkeeping_report(
        years=hours_as_years(2),
        policy="adaptive",
        scenario="nominal",
        contact_model="synthetic",
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
        event_lifecycle_model="none",
        debris_risk_model="legacy",
        autonomy_model="none",
        seed=42,
        results_dir=tmp_path,
    )

    assert result.state.hours_completed == len(records) == 2
    assert summary["stationkeeping_planning_model"] == "drift_aware"
    assert (tmp_path / "stationkeeping_trace.csv").is_file()
    assert (tmp_path / "stationkeeping_summary.csv").is_file()
    markdown = " ".join(
        (tmp_path / "stationkeeping_summary.md")
        .read_text(encoding="utf-8")
        .lower()
        .split()
    )
    for phrase in (
        "bounded stationkeeping/drift-planning proxy",
        "not real stationkeeping",
        "flight dynamics",
        "tle/sgp4",
        "j2 or atmospheric-drag",
        "operational kazeosat-1 logic",
        "geometry + `drift_proxy` is the final research direction",
        "synthetic contacts remain baseline/regression controls",
    ):
        assert phrase in markdown


def test_readme_and_final_config_document_v35_direction() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = " ".join(
        (root / "README.md").read_text(encoding="utf-8").lower().split()
    )
    final_config = " ".join(
        (root / "FINAL_CONFIG.md")
        .read_text(encoding="utf-8")
        .lower()
        .split()
    )
    canon = " ".join(
        (root / "PROJECT_CANON.md")
        .read_text(encoding="utf-8")
        .lower()
        .split()
    )

    assert "## v3.5 stationkeeping and drift-planning repair" in readme
    assert "--stationkeeping-planning-model legacy|drift_aware" in readme
    assert "`legacy` is the default everywhere" in readme
    assert "paper_suite.py` and its experiment matrix are not" in readme
    assert "stationkeeping_planning_model = drift_aware" in final_config
    assert "stationkeeping_planning_model = legacy" in final_config
    for document in (readme, canon):
        assert "`backup` is not the terminal no-contact state" in document
        assert "may temporarily select `maneuver` from `backup`" in document
        assert "`emergency_beacon` remains terminal" in document
