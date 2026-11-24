import csv
from dataclasses import replace
from pathlib import Path

import pytest

import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.contacts import (
    GeometryContactModel,
    GroundStation,
    SyntheticContactModel,
)
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.models import ContactInfo, DailyPlan, Mode, SatelliteState
from ops_sim.policies import make_policy
from ops_sim.scenarios import Scenario, StochasticPostLifeEventsScenario
from ops_sim.simulator import ORBIT_EVOLUTION_MODELS, Simulator


FUEL_PERCENT_FIELDS = {
    "fuel_remaining_percent",
    "fuel_used_percent",
    "stationkeeping_delta_v_cost_percent",
    "debris_avoidance_delta_v_cost_percent",
}
STATE_ORBIT_FIELDS = {
    "orbit_evolution_model",
    "orbit_altitude_offset_km",
    "orbit_phase_error_deg",
    "orbit_groundtrack_error_km",
    "orbit_geometry_degraded",
    "orbit_correction_count",
    "orbit_correction_skipped_count",
    "effective_orbit_altitude_km",
    "effective_orbit_phase_deg",
    "fixed_orbit_sat_lat_deg",
    "fixed_orbit_sat_lon_deg",
    "fixed_orbit_alt_km",
    "fixed_orbit_phase_deg",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_fields(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return set(csv.DictReader(handle).fieldnames or [])


def hours_as_years(hours: int, config=DEFAULT_CONFIG) -> float:
    return hours / config.hours_per_year


def v28_config(**changes):
    values = {
        "initial_delta_v_budget_m_per_s": 2.0,
        "stationkeeping_delta_v_cost_m_per_s": 0.20,
        "debris_avoidance_delta_v_cost_m_per_s": 0.40,
        "minimum_delta_v_for_maneuver_m_per_s": 0.20,
        "maneuver_propulsion_degradation": 0.0,
        "orbit_drift_proxy_km_per_day": 0.024,
        "orbit_drift_threshold_km": 0.01,
        "orbit_drift_warning_threshold_km": 0.01,
        "orbit_drift_critical_threshold_km": 10.0,
        "orbit_drift_reduction_per_maneuver_km": 0.02,
        "orbit_phase_error_deg_per_drift_km": 10.0,
        "orbit_altitude_offset_km_per_drift_km": -2.0,
        "orbit_groundtrack_error_km_per_drift_km": 4.0,
        "orbit_geometry_degraded_threshold_km": 0.03,
        "orbit_geometry_critical_threshold_km": 10.0,
        "stationkeeping_phase_correction_fraction": 0.50,
        "stationkeeping_altitude_correction_fraction": 0.50,
        "stationkeeping_groundtrack_correction_fraction": 0.50,
        "debris_avoidance_phase_impulse_deg": 0.30,
        "debris_avoidance_altitude_impulse_km": 0.20,
        "debris_avoidance_groundtrack_impulse_km": 0.40,
        "maximum_orbit_phase_error_deg": 180.0,
        "maximum_orbit_altitude_offset_km": 1000.0,
        "maximum_orbit_groundtrack_error_km": 10_000.0,
    }
    values.update(changes)
    return replace(DEFAULT_CONFIG, **values)


def maneuver_plan(config=DEFAULT_CONFIG) -> DailyPlan:
    return DailyPlan(
        uploaded_hour=0,
        duration_hours=config.plan_duration_hours,
        planned_modes=(Mode.MANEUVER,)
        + (Mode.STANDBY,) * (config.plan_duration_hours - 1),
        policy_name="adaptive",
        based_on_telemetry_hour=0,
        based_on_telemetry_age_hours=0,
    )


def debris_scenario(effect: float = 0.05):
    event = ExternalEvent(
        0,
        "debris_conjunction",
        1.0,
        1,
        "solar_health,adcs_health",
        effect,
        "V2.8 test conjunction",
    )
    return StochasticPostLifeEventsScenario(
        event_catalog=EventCatalog(
            [event], 42, "stochastic_post_life_events", 1
        )
    )


class NoContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo()


class AlwaysCommandContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(cmd_contact_min=5.0)


class RemoveFinalContactScenario(Scenario):
    name = "remove_final_contact"

    def modify_contacts(
        self, contact: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo()


def test_orbit_evolution_defaults_and_validation():
    args = run.build_parser().parse_args([])
    assert args.orbit_evolution_model == "fixed"
    assert ORBIT_EVOLUTION_MODELS == ("fixed", "drift_proxy")

    for model in ORBIT_EVOLUTION_MODELS:
        assert run.build_parser().parse_args([
            "--orbit-evolution-model", model,
        ]).orbit_evolution_model == model

    with pytest.raises(SystemExit):
        run.build_parser().parse_args([
            "--orbit-evolution-model", "invalid",
        ])
    with pytest.raises(ValueError, match="orbit_evolution_model must be one of"):
        Simulator(
            make_policy("adaptive"), orbit_evolution_model="invalid"
        )


@pytest.mark.parametrize("orbit_model", ORBIT_EVOLUTION_MODELS)
def test_cli_runs_both_orbit_evolution_models(tmp_path, orbit_model):
    results_dir = tmp_path / orbit_model
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--orbit-evolution-model", orbit_model,
        "--log-level", "summary",
        "--results-dir", str(results_dir),
    ]) == 0
    assert read_rows(results_dir / "summary.csv")[0][
        "orbit_evolution_model"
    ] == orbit_model


def test_fuel_percentages_use_the_configured_proxy_budget():
    config = v28_config()
    result = Simulator(
        make_policy("adaptive", config), config=config
    ).run(
        0.0,
        state=SatelliteState(
            delta_v_remaining_m_per_s=1.5,
            delta_v_used_m_per_s=0.5,
        ),
    )

    assert result.fuel_remaining_percent == pytest.approx(75.0)
    assert result.fuel_used_percent == pytest.approx(25.0)
    assert result.stationkeeping_delta_v_cost_percent == pytest.approx(10.0)
    assert result.debris_avoidance_delta_v_cost_percent == pytest.approx(20.0)


def test_v28_state_and_summary_schemas(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--maneuver-model", "stationkeeping_proxy",
        "--orbit-evolution-model", "drift_proxy",
        "--results-dir", str(tmp_path),
    ]) == 0

    state_fields = read_fields(tmp_path / "state_log.csv")
    summary_fields = read_fields(tmp_path / "summary.csv")
    assert FUEL_PERCENT_FIELDS | STATE_ORBIT_FIELDS <= state_fields
    assert FUEL_PERCENT_FIELDS | {"orbit_evolution_model"} <= summary_fields
    assert (
        STATE_ORBIT_FIELDS - {"orbit_evolution_model"}
    ).isdisjoint(summary_fields)


def test_drift_proxy_accumulates_bounded_geometry_errors_and_degrades():
    config = v28_config(
        orbit_drift_threshold_km=10.0,
        orbit_drift_warning_threshold_km=10.0,
    )
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(hours_as_years(1, config))

    state = result.state
    assert state.orbit_drift_proxy_km == pytest.approx(0.001)
    assert state.orbit_phase_error_deg == pytest.approx(0.01)
    assert state.orbit_altitude_offset_km == pytest.approx(-0.002)
    assert state.orbit_groundtrack_error_km == pytest.approx(0.004)
    assert state.orbit_geometry_degraded is True


def test_fixed_model_leaves_active_position_on_reference_orbit():
    config = v28_config()
    records = []
    Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="fixed",
    ).run(hours_as_years(1, config), on_hour=records.append)

    record = records[0]
    assert record.orbit_altitude_offset_km == 0
    assert record.orbit_phase_error_deg == 0
    assert record.orbit_groundtrack_error_km == 0
    assert record.orbit_geometry_degraded is False
    assert record.sat_lat_deg == record.fixed_orbit_sat_lat_deg
    assert record.sat_lon_deg == record.fixed_orbit_sat_lon_deg
    assert record.sat_alt_km == record.fixed_orbit_alt_km
    assert record.orbit_phase_deg == record.fixed_orbit_phase_deg


def test_successful_stationkeeping_reduces_proxy_errors_and_updates_fuel():
    config = v28_config(orbit_drift_proxy_km_per_day=0.0)
    state = SatelliteState(
        soc=80.0,
        delta_v_remaining_m_per_s=2.0,
        orbit_drift_proxy_km=0.02,
        orbit_phase_error_deg=2.0,
        orbit_altitude_offset_km=-1.0,
        orbit_groundtrack_error_km=3.0,
        current_plan=maneuver_plan(config),
    )
    state._orbit_proxy_mapped_drift_km = state.orbit_drift_proxy_km

    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(hours_as_years(1, config), state=state)

    assert result.state.mode == Mode.MANEUVER
    assert result.state.maneuver_count == 1
    assert result.state.orbit_correction_count == 1
    assert result.state.orbit_drift_proxy_km == pytest.approx(0.0)
    assert result.state.orbit_phase_error_deg == pytest.approx(1.0)
    assert result.state.orbit_altitude_offset_km == pytest.approx(-0.5)
    assert result.state.orbit_groundtrack_error_km == pytest.approx(1.5)
    assert result.state.delta_v_used_m_per_s == pytest.approx(0.20)
    assert result.fuel_remaining_percent == pytest.approx(90.0)
    assert result.fuel_used_percent == pytest.approx(10.0)


def test_failed_stationkeeping_preserves_errors_and_counts_skipped_correction():
    config = v28_config(orbit_drift_proxy_km_per_day=0.0)
    state = SatelliteState(
        soc=80.0,
        delta_v_remaining_m_per_s=0.10,
        orbit_drift_proxy_km=0.02,
        orbit_phase_error_deg=2.0,
        orbit_altitude_offset_km=-1.0,
        orbit_groundtrack_error_km=3.0,
        current_plan=maneuver_plan(config),
    )
    state._orbit_proxy_mapped_drift_km = state.orbit_drift_proxy_km

    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(hours_as_years(1, config), state=state)

    assert result.state.mode == Mode.STANDBY
    assert result.state.maneuver_skipped_count == 1
    assert result.state.orbit_correction_skipped_count == 1
    assert result.state.orbit_correction_count == 0
    assert result.state.orbit_phase_error_deg == pytest.approx(2.0)
    assert result.state.orbit_altitude_offset_km == pytest.approx(-1.0)
    assert result.state.orbit_groundtrack_error_km == pytest.approx(3.0)
    assert result.state.delta_v_used_m_per_s == 0


def test_successful_debris_avoidance_applies_only_drift_proxy_impulse():
    config = v28_config(orbit_drift_proxy_km_per_day=0.0)
    result = Simulator(
        make_policy("adaptive", config),
        debris_scenario(),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(
        hours_as_years(1, config),
        state=SatelliteState(
            soc=80.0, delta_v_remaining_m_per_s=2.0
        ),
    )

    state = result.state
    assert state.mode == Mode.MANEUVER
    assert state.debris_avoidance_executed_count == 1
    assert state.maneuver_count == 0
    assert state.debris_damage_events == 0
    assert state.delta_v_used_m_per_s == pytest.approx(0.40)
    assert state.orbit_phase_error_deg == pytest.approx(0.30)
    assert state.orbit_altitude_offset_km == pytest.approx(0.20)
    assert state.orbit_groundtrack_error_km == pytest.approx(0.40)

    fixed = Simulator(
        make_policy("adaptive", config),
        debris_scenario(),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="fixed",
    ).run(
        hours_as_years(1, config),
        state=SatelliteState(
            soc=80.0, delta_v_remaining_m_per_s=2.0
        ),
    )
    assert fixed.state.debris_avoidance_executed_count == 1
    assert fixed.state.orbit_phase_error_deg == 0
    assert fixed.state.orbit_altitude_offset_km == 0
    assert fixed.state.orbit_groundtrack_error_km == 0


def test_failed_debris_avoidance_applies_damage_without_geometry_impulse():
    config = v28_config(orbit_drift_proxy_km_per_day=0.0)
    result = Simulator(
        make_policy("adaptive", config),
        debris_scenario(effect=0.05),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(
        hours_as_years(1, config),
        state=SatelliteState(
            soc=80.0, delta_v_remaining_m_per_s=0.10
        ),
    )

    state = result.state
    assert state.debris_avoidance_skipped_count == 1
    assert state.debris_avoidance_executed_count == 0
    assert state.debris_damage_events == 1
    assert state.debris_damage_accumulated == pytest.approx(0.05)
    assert state.solar_health < 1.0
    assert state.adcs_health < 1.0
    assert state.delta_v_used_m_per_s == 0
    assert state.orbit_phase_error_deg == 0
    assert state.orbit_altitude_offset_km == 0
    assert state.orbit_groundtrack_error_km == 0


def test_geometry_fixed_uses_established_cached_orbit_even_with_proxy_state():
    config = v28_config()
    model = GeometryContactModel(
        GroundStation(0.0, 0.0, -90.0), config, step_seconds=300
    )
    expected = model.contact_summary_at_hour(0)
    records = []
    Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=model,
        orbit_evolution_model="fixed",
    ).run(
        hours_as_years(1, config),
        state=SatelliteState(
            orbit_altitude_offset_km=500.0,
            orbit_phase_error_deg=120.0,
            orbit_groundtrack_error_km=1000.0,
        ),
        on_hour=records.append,
    )

    record = records[0]
    assert record.base_cmd_contact_min == expected.cmd_contact_min
    assert record.base_data_contact_min == expected.data_contact_min
    assert record.geometry_raw_visible_seconds == expected.raw_visible_seconds
    assert record.geometry_max_elevation_deg == expected.max_elevation_deg
    assert record.geometry_min_range_km == expected.min_range_km
    assert record.sat_lat_deg == record.fixed_orbit_sat_lat_deg
    assert record.sat_lon_deg == record.fixed_orbit_sat_lon_deg
    assert model.contact_summary_at_hour(0) is expected


def test_state_aware_geometry_does_not_reuse_stale_hour_only_summary():
    config = v28_config()
    model = GeometryContactModel(
        GroundStation(0.0, 0.0, -90.0), config, step_seconds=300
    )

    def one_record(state):
        records = []
        Simulator(
            make_policy("adaptive", config),
            config=config,
            contact_model=model,
            orbit_evolution_model="drift_proxy",
        ).run(
            hours_as_years(1, config), state=state,
            on_hour=records.append,
        )
        return records[0]

    reference = one_record(SatelliteState())
    shifted = one_record(SatelliteState(
        orbit_altitude_offset_km=500.0,
        orbit_phase_error_deg=120.0,
        orbit_groundtrack_error_km=1000.0,
    ))

    reference_diagnostics = (
        reference.geometry_max_elevation_deg,
        reference.geometry_min_range_km,
        reference.sat_lat_deg,
        reference.sat_lon_deg,
        reference.sat_alt_km,
    )
    shifted_diagnostics = (
        shifted.geometry_max_elevation_deg,
        shifted.geometry_min_range_km,
        shifted.sat_lat_deg,
        shifted.sat_lon_deg,
        shifted.sat_alt_km,
    )
    assert shifted_diagnostics != reference_diagnostics
    assert shifted.sat_alt_km == pytest.approx(
        config.orbit_altitude_km + 500.0
    )
    assert shifted.fixed_orbit_alt_km == config.orbit_altitude_km
    assert model._summary_cache == {}


def test_synthetic_contacts_are_unchanged_by_drift_proxy_state():
    model = SyntheticContactModel()
    simulator = Simulator(
        make_policy("adaptive"),
        contact_model=model,
        orbit_evolution_model="drift_proxy",
    )
    state = SatelliteState(
        orbit_altitude_offset_km=500.0,
        orbit_phase_error_deg=120.0,
        orbit_groundtrack_error_km=1000.0,
    )

    assert [simulator.nominal_contact(hour, state) for hour in range(12)] == [
        model.contact_at_hour(hour) for hour in range(12)
    ]


def test_delayed_risk_aware_plan_can_correct_degraded_geometry():
    config = v28_config(
        orbit_drift_proxy_km_per_day=0.0,
        orbit_drift_threshold_km=10.0,
        orbit_drift_warning_threshold_km=10.0,
        orbit_geometry_degraded_threshold_km=0.10,
    )
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(
        hours_as_years(1, config),
        state=SatelliteState(
            soc=80.0,
            delta_v_remaining_m_per_s=2.0,
            orbit_groundtrack_error_km=1.0,
            orbit_geometry_degraded=True,
        ),
        on_hour=records.append,
    )

    assert records[0].telemetry_updated_this_hour is True
    assert records[0].plan_uploaded_this_hour is True
    assert records[0].planned_mode == Mode.MANEUVER.value
    assert records[0].mode == Mode.MANEUVER.value
    assert result.state.orbit_correction_count == 1


def test_disrupted_final_contact_still_prevents_delayed_plan_upload():
    config = v28_config(orbit_drift_proxy_km_per_day=0.0)
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        RemoveFinalContactScenario(),
        config=config,
        contact_model=AlwaysCommandContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(
        hours_as_years(1, config),
        state=SatelliteState(
            soc=80.0,
            orbit_groundtrack_error_km=1.0,
            orbit_geometry_degraded=True,
        ),
        on_hour=records.append,
    )

    assert records[0].base_cmd_contact_min == 5.0
    assert records[0].cmd_contact_min == 0
    assert records[0].telemetry_updated_this_hour is False
    assert records[0].plan_uploaded_this_hour is False
    assert result.state.current_plan is None


def test_monte_carlo_includes_v28_aggregate_fields_and_defaults_to_summary(
    tmp_path,
):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "stochastic_post_life_events",
        "--monte-carlo", "2",
        "--operator-view", "delayed_telemetry",
        "--planning-model", "risk_aware",
        "--maneuver-model", "stationkeeping_proxy",
        "--orbit-evolution-model", "drift_proxy",
        "--results-dir", str(tmp_path),
    ]) == 0

    for filename in ("summary.csv", "monte_carlo_summary.csv"):
        rows = read_rows(tmp_path / filename)
        assert len(rows) == 2
        assert {row["orbit_evolution_model"] for row in rows} == {
            "drift_proxy"
        }
        assert FUEL_PERCENT_FIELDS <= set(rows[0])
        assert (STATE_ORBIT_FIELDS - {"orbit_evolution_model"}).isdisjoint(
            rows[0]
        )
    assert not (tmp_path / "state_log.csv").exists()
    assert not (tmp_path / "checkpoints.csv").exists()
    assert not (tmp_path / "events_log.csv").exists()


def test_readme_documents_v28_assumptions_and_geometry_boundary():
    normalized = " ".join(
        Path("README.md").read_text(encoding="utf-8").split()
    ).lower()

    assert "v2.8 orbit evolution and state-aware geometry" in normalized
    assert "--orbit-evolution-model fixed|drift_proxy" in normalized
    assert "`fixed` is the default" in normalized
    assert "open-source maneuver and fuel assumptions" in normalized
    assert "fuel percentages are relative only to that configured proxy" in normalized
    assert "state-dependent geometry does not reuse a stale result cached only by hour" in normalized
    assert "not real flight dynamics" in normalized
    assert "not real stationkeeping" in normalized
    assert "not conjunction analysis" in normalized
    assert "tle/sgp4" in normalized
    assert "configured initial delta-v and maneuver costs remain explicit" in normalized
    assert "synthetic schedule" in normalized
    assert "v2.8.1 makes daily-plan contact forecasts state-aware" in normalized
    assert (
        "future deterministic and stochastic disruptions are still not forecast"
        in normalized
    )
