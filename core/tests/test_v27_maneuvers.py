import csv
from dataclasses import replace
from pathlib import Path

import pytest

import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.models import ContactInfo, DailyPlan, Mode, SatelliteState
from ops_sim.policies import POLICIES, Policy, make_policy
from ops_sim.simulator import MANEUVER_MODELS, Simulator
from ops_sim.scenarios import StochasticPostLifeEventsScenario


DETAILED_MANEUVER_FIELDS = {
    "delta_v_remaining_m_per_s",
    "delta_v_used_m_per_s",
    "maneuver_count",
    "maneuver_skipped_count",
    "orbit_drift_proxy_km",
    "maneuver_due",
    "maneuver_executed_this_hour",
    "maneuver_skipped_this_hour",
    "maneuver_delta_v_used_this_hour",
    "planned_maneuver",
}
STATE_ONLY_MANEUVER_FIELDS = DETAILED_MANEUVER_FIELDS - {
    "delta_v_used_m_per_s",
    "maneuver_count",
    "maneuver_skipped_count",
}
AGGREGATE_MANEUVER_FIELDS = {
    "maneuver_model",
    "maneuver_mode_fraction",
    "final_delta_v_remaining_m_per_s",
    "delta_v_used_m_per_s",
    "maneuver_count",
    "maneuver_skipped_count",
    "final_orbit_drift_proxy_km",
}
DETAILED_CONSEQUENCE_FIELDS = {
    "debris_conjunction_active",
    "debris_avoidance_required_this_hour",
    "debris_avoidance_executed_count",
    "debris_avoidance_skipped_count",
    "debris_avoidance_executed_this_hour",
    "debris_avoidance_skipped_this_hour",
    "debris_damage_events",
    "debris_damage_this_hour",
    "debris_damage_accumulated",
    "orbit_drift_warning",
    "orbit_drift_critical",
    "orbit_drift_damage_events",
    "orbit_drift_damage_this_hour",
    "orbit_drift_damage_accumulated",
}
AGGREGATE_CONSEQUENCE_FIELDS = {
    "debris_avoidance_executed_count",
    "debris_avoidance_skipped_count",
    "debris_damage_events",
    "debris_damage_accumulated",
    "orbit_drift_damage_events",
    "orbit_drift_damage_accumulated",
}
STATE_ONLY_CONSEQUENCE_FIELDS = (
    DETAILED_CONSEQUENCE_FIELDS - AGGREGATE_CONSEQUENCE_FIELDS
)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_fields(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return set(csv.DictReader(handle).fieldnames or [])


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


def maneuver_config(**changes):
    values = {
        "stationkeeping_delta_v_cost_m_per_s": 0.20,
        "minimum_delta_v_for_maneuver_m_per_s": 0.20,
        "maneuver_propulsion_degradation": 0.01,
        "orbit_drift_proxy_km_per_day": 0.024,
        "orbit_drift_threshold_km": 0.01,
        "orbit_drift_warning_threshold_km": 0.01,
        "orbit_drift_reduction_per_maneuver_km": 0.02,
    }
    values.update(changes)
    return replace(DEFAULT_CONFIG, **values)


def maneuver_plan() -> DailyPlan:
    return DailyPlan(
        uploaded_hour=0,
        duration_hours=DEFAULT_CONFIG.plan_duration_hours,
        planned_modes=(Mode.MANEUVER,) + (Mode.STANDBY,) * 23,
        policy_name="adaptive",
        based_on_telemetry_hour=0,
        based_on_telemetry_age_hours=0,
    )


def debris_scenario(effect: float = 0.05, duration_hours: int = 1):
    event = ExternalEvent(
        0,
        "debris_conjunction",
        1.0,
        duration_hours,
        ",".join(DEFAULT_CONFIG.debris_damage_targets),
        effect,
        "test debris conjunction",
    )
    catalog = EventCatalog(
        [event], 42, "stochastic_post_life_events", duration_hours
    )
    return StochasticPostLifeEventsScenario(event_catalog=catalog)


class NoContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo()


class ManeuverPolicy(Policy):
    name = "maneuver_test"

    @property
    def safe_threshold(self) -> float:
        return DEFAULT_CONFIG.adaptive_safe_threshold

    def select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode:
        return Mode.MANEUVER


def test_maneuver_defaults_preserve_previous_behavior():
    args = run.build_parser().parse_args([])
    assert args.maneuver_model == "none"
    assert MANEUVER_MODELS == ("none", "stationkeeping_proxy")
    assert Mode.MANEUVER in Mode
    assert SatelliteState().mode_hours[Mode.MANEUVER] == 0

    initial_delta_v = DEFAULT_CONFIG.initial_delta_v_budget_m_per_s
    result = Simulator(
        ManeuverPolicy(), contact_model=NoContactModel()
    ).run(hours_as_years(2))
    assert result.maneuver_model == "none"
    assert result.state.mode == Mode.STANDBY
    assert result.state.orbit_drift_proxy_km == 0
    assert result.state.delta_v_remaining_m_per_s == initial_delta_v
    assert result.state.delta_v_used_m_per_s == 0
    assert result.state.maneuver_count == 0
    assert result.state.maneuver_skipped_count == 0


@pytest.mark.parametrize("maneuver_model", MANEUVER_MODELS)
def test_cli_accepts_both_maneuver_models(tmp_path, maneuver_model):
    results_dir = tmp_path / maneuver_model
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--maneuver-model", maneuver_model,
        "--results-dir", str(results_dir),
    ]) == 0
    assert read_rows(results_dir / "summary.csv")[0]["maneuver_model"] == (
        maneuver_model
    )


def test_invalid_maneuver_model_is_rejected():
    with pytest.raises(SystemExit):
        run.build_parser().parse_args(["--maneuver-model", "invalid"])
    with pytest.raises(ValueError, match="maneuver_model must be one of"):
        Simulator(make_policy("adaptive"), maneuver_model="invalid")


def test_stationkeeping_drift_accumulates_but_none_does_not():
    config = maneuver_config()
    enabled = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
    ).run(hours_as_years(2))
    disabled = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="none",
    ).run(hours_as_years(2))

    assert enabled.state.orbit_drift_proxy_km == pytest.approx(0.002)
    assert disabled.state.orbit_drift_proxy_km == 0


def test_uncorrected_critical_drift_applies_hourly_operational_damage():
    config = maneuver_config(
        orbit_drift_warning_threshold_km=0.001,
        orbit_drift_critical_threshold_km=0.0015,
        orbit_drift_damage_per_hour=0.01,
    )
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, orbit_drift_proxy_km=0.001),
        on_hour=records.append,
    )

    assert records[0].orbit_drift_warning is True
    assert records[0].orbit_drift_critical is True
    assert records[0].orbit_drift_damage_this_hour == pytest.approx(0.01)
    assert result.state.orbit_drift_damage_events == 1
    assert result.state.orbit_drift_damage_accumulated == pytest.approx(0.01)
    assert result.state.adcs_health < 1.0
    assert result.state.thermal_health < 1.0
    assert result.state.comms_health < 1.0


def test_stationkeeping_correction_can_prevent_critical_drift_damage():
    config = maneuver_config(
        orbit_drift_warning_threshold_km=0.001,
        orbit_drift_critical_threshold_km=0.0015,
        orbit_drift_damage_per_hour=0.01,
    )
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(2),
        state=SatelliteState(
            soc=80.0,
            orbit_drift_proxy_km=0.001,
            delta_v_remaining_m_per_s=2.0,
            current_plan=maneuver_plan(),
        ),
        on_hour=records.append,
    )

    assert records[0].maneuver_executed_this_hour is True
    assert records[0].orbit_drift_critical is False
    assert all(record.orbit_drift_damage_this_hour == 0 for record in records)
    assert result.state.orbit_drift_damage_events == 0
    assert result.state.orbit_drift_damage_accumulated == 0


def test_risk_aware_plan_executes_maneuver_and_consumes_resources():
    config = maneuver_config()
    state = SatelliteState(
        soc=80.0,
        data_buffer_gb=100.0,
        orbit_drift_proxy_km=0.02,
        delta_v_remaining_m_per_s=2.0,
    )
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
    ).run(hours_as_years(1), state=state, on_hour=records.append)

    record = records[0]
    assert record.planned_mode == Mode.MANEUVER.value
    assert record.planned_maneuver is True
    assert record.mode == Mode.MANEUVER.value
    assert record.maneuver_executed_this_hour is True
    assert record.maneuver_skipped_this_hour is False
    assert record.maneuver_delta_v_used_this_hour == pytest.approx(0.20)
    assert result.state.delta_v_remaining_m_per_s == pytest.approx(1.80)
    assert result.state.delta_v_used_m_per_s == pytest.approx(0.20)
    assert result.state.maneuver_count == 1
    assert result.state.debris_avoidance_executed_count == 0
    assert result.state.last_maneuver_hour == 0
    assert result.state.orbit_drift_proxy_km < 0.02
    assert result.state.propulsion_health == pytest.approx(0.99)
    assert result.state.mode_hours[Mode.MANEUVER] == 1
    assert result.state.total_data_generated_gb == 0
    assert result.state.total_data_downlinked_gb == 0
    assert result.state.data_buffer_gb == pytest.approx(100.0)


def test_active_debris_conjunction_executes_avoidance_when_resources_exist():
    config = maneuver_config()
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        debris_scenario(),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, delta_v_remaining_m_per_s=2.0),
        on_hour=records.append,
    )

    record = records[0]
    assert record.debris_conjunction_active is True
    assert record.debris_avoidance_required_this_hour is True
    assert record.debris_avoidance_executed_this_hour is True
    assert record.debris_avoidance_skipped_this_hour is False
    assert record.planned_maneuver is False
    assert record.mode == Mode.MANEUVER.value
    assert record.maneuver_delta_v_used_this_hour == pytest.approx(
        config.debris_avoidance_delta_v_cost_m_per_s
    )
    assert result.state.delta_v_remaining_m_per_s == pytest.approx(1.80)
    assert result.state.maneuver_count == 0
    assert result.state.maneuver_skipped_count == 0
    assert result.state.debris_avoidance_executed_count == 1
    assert result.state.debris_avoidance_skipped_count == 0
    assert result.state.debris_damage_events == 0
    assert result.state.debris_damage_accumulated == 0
    assert result.state.total_data_generated_gb == 0
    assert result.state.total_data_downlinked_gb == 0


def test_multi_hour_debris_event_is_resolved_only_once():
    config = maneuver_config()
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        debris_scenario(duration_hours=2),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(2),
        state=SatelliteState(soc=80.0, delta_v_remaining_m_per_s=2.0),
        on_hour=records.append,
    )

    assert [record.debris_conjunction_active for record in records] == [
        True, True,
    ]
    assert [
        record.debris_avoidance_required_this_hour for record in records
    ] == [True, False]
    assert result.state.debris_avoidance_executed_count == 1
    assert result.state.maneuver_count == 0
    assert result.state.delta_v_used_m_per_s == pytest.approx(
        config.debris_avoidance_delta_v_cost_m_per_s
    )


def test_invalid_debris_damage_target_raises_clear_value_error():
    event = ExternalEvent(
        0,
        "debris_conjunction",
        1.0,
        1,
        "solar_health,not_a_health_field",
        0.05,
        "invalid debris target",
    )
    catalog = EventCatalog(
        [event], 42, "stochastic_post_life_events", 1
    )

    with pytest.raises(
        ValueError,
        match=r"Invalid debris damage target\(s\): not_a_health_field",
    ):
        StochasticPostLifeEventsScenario(event_catalog=catalog)


def test_debris_avoidance_without_fuel_is_skipped_and_applies_damage():
    config = maneuver_config()
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        debris_scenario(),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, delta_v_remaining_m_per_s=0.10),
        on_hour=records.append,
    )

    assert records[0].mode == Mode.STANDBY.value
    assert records[0].debris_avoidance_skipped_this_hour is True
    assert records[0].debris_damage_this_hour == pytest.approx(0.05)
    assert result.state.delta_v_remaining_m_per_s == pytest.approx(0.10)
    assert result.state.maneuver_count == 0
    assert result.state.maneuver_skipped_count == 0
    assert result.state.debris_avoidance_skipped_count == 1
    assert result.state.debris_damage_events == 1
    assert result.state.debris_damage_accumulated == pytest.approx(0.05)
    assert result.state.solar_health < 1.0
    assert result.state.adcs_health < 1.0
    assert result.state.thermal_health < 1.0
    assert result.state.comms_health < 1.0


def test_low_propulsion_prevents_debris_avoidance_without_direct_mission_loss():
    config = maneuver_config()
    result = Simulator(
        make_policy("adaptive", config),
        debris_scenario(),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(
            soc=80.0,
            propulsion_health=0.10,
            delta_v_remaining_m_per_s=2.0,
        ),
    )

    assert result.state.debris_avoidance_executed_count == 0
    assert result.state.debris_avoidance_skipped_count == 1
    assert result.state.maneuver_count == 0
    assert result.state.maneuver_skipped_count == 0
    assert result.state.debris_damage_events == 1
    assert result.state.propulsion_health == pytest.approx(0.10)
    assert result.state.alive is True
    assert result.state.loss_reason is None


def test_low_real_energy_keeps_safe_priority_and_debris_damage_applies():
    config = maneuver_config()
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        debris_scenario(),
        config=config,
        contact_model=NoContactModel(),
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=20.0, delta_v_remaining_m_per_s=2.0),
        on_hour=records.append,
    )

    assert records[0].mode == Mode.SAFE.value
    assert records[0].debris_avoidance_skipped_this_hour is True
    assert result.state.debris_damage_events == 1
    assert result.state.delta_v_used_m_per_s == 0
    assert result.state.maneuver_skipped_count == 0


def test_maneuver_model_none_cannot_avoid_debris_conjunction():
    records = []
    result = Simulator(
        make_policy("adaptive"),
        debris_scenario(),
        contact_model=NoContactModel(),
        maneuver_model="none",
    ).run(hours_as_years(1), on_hour=records.append)

    assert records[0].debris_avoidance_skipped_this_hour is True
    assert records[0].mode == Mode.STANDBY.value
    assert result.state.debris_avoidance_skipped_count == 1
    assert result.state.debris_damage_events == 1
    assert result.state.delta_v_used_m_per_s == 0
    assert result.state.maneuver_count == 0
    assert result.state.maneuver_skipped_count == 0
    assert result.state.orbit_drift_proxy_km == 0


def test_emergency_beacon_has_priority_over_debris_avoidance():
    config = maneuver_config()
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        debris_scenario(),
        config=config,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(
            soc=80.0,
            emergency_beacon_mode=True,
            delta_v_remaining_m_per_s=2.0,
        ),
        on_hour=records.append,
    )

    assert records[0].mode == Mode.EMERGENCY_BEACON.value
    assert records[0].debris_avoidance_skipped_this_hour is True
    assert result.state.debris_damage_events == 1
    assert result.state.delta_v_used_m_per_s == 0
    assert result.state.maneuver_skipped_count == 0


def test_reactive_planning_does_not_proactively_schedule_maneuver():
    config = maneuver_config()
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        operator_view="delayed_telemetry",
        planning_model="reactive",
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, orbit_drift_proxy_km=0.02),
    )
    assert Mode.MANEUVER not in result.state.current_plan.planned_modes
    assert result.state.maneuver_count == 0


def test_insufficient_delta_v_skips_intended_maneuver_safely():
    config = maneuver_config()
    state = SatelliteState(
        soc=80.0,
        delta_v_remaining_m_per_s=0.10,
        orbit_drift_proxy_km=0.02,
        current_plan=maneuver_plan(),
    )
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
    ).run(hours_as_years(1), state=state, on_hour=records.append)

    assert records[0].planned_maneuver is True
    assert records[0].maneuver_skipped_this_hour is True
    assert records[0].maneuver_executed_this_hour is False
    assert records[0].mode == Mode.STANDBY.value
    assert result.state.delta_v_remaining_m_per_s == pytest.approx(0.10)
    assert result.state.delta_v_used_m_per_s == 0
    assert result.state.maneuver_count == 0
    assert result.state.maneuver_skipped_count == 1
    assert result.state.debris_avoidance_skipped_count == 0


def test_low_propulsion_health_skips_maneuver_without_mission_loss():
    config = maneuver_config()
    state = SatelliteState(
        soc=80.0,
        propulsion_health=0.10,
        orbit_drift_proxy_km=0.02,
        current_plan=maneuver_plan(),
    )
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
    ).run(hours_as_years(1), state=state, on_hour=records.append)

    assert records[0].maneuver_skipped_this_hour is True
    assert result.state.maneuver_skipped_count == 1
    assert result.state.maneuver_count == 0
    assert result.state.debris_avoidance_skipped_count == 0
    assert result.state.alive is True
    assert result.state.loss_reason is None


def test_real_energy_and_emergency_override_planned_maneuver():
    config = maneuver_config()
    low_energy_records = []
    Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=20.0, current_plan=maneuver_plan()),
        on_hour=low_energy_records.append,
    )
    assert low_energy_records[0].planned_maneuver is True
    assert low_energy_records[0].mode == Mode.SAFE.value
    assert low_energy_records[0].maneuver_skipped_this_hour is True

    emergency_records = []
    Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(
            soc=80.0,
            emergency_beacon_mode=True,
            current_plan=maneuver_plan(),
        ),
        on_hour=emergency_records.append,
    )
    assert emergency_records[0].mode == Mode.EMERGENCY_BEACON.value
    assert emergency_records[0].maneuver_skipped_this_hour is True


def test_no_contact_executes_stored_maneuver_without_live_policy_call():
    config = maneuver_config()
    state = SatelliteState(
        soc=80.0,
        orbit_drift_proxy_km=0.02,
        current_plan=maneuver_plan(),
    )
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
        maneuver_model="stationkeeping_proxy",
    ).run(hours_as_years(1), state=state, on_hour=records.append)
    assert records[0].cmd_contact_min == 0
    assert records[0].plan_uploaded_this_hour is False
    assert records[0].mode == Mode.MANEUVER.value
    assert result.state.maneuver_count == 1


def test_operator_profiles_apply_different_maneuver_reserves():
    config = maneuver_config()
    plans = {}
    for name in POLICIES:
        result = Simulator(
            make_policy(name, config),
            config=config,
            operator_view="delayed_telemetry",
            planning_model="risk_aware",
            maneuver_model="stationkeeping_proxy",
        ).run(
            hours_as_years(1),
            state=SatelliteState(soc=45.0, orbit_drift_proxy_km=0.02),
        )
        plans[name] = result.state.current_plan.planned_modes

    assert plans["aggressive"][0] == Mode.MANEUVER
    assert plans["contact_opportunist"][0] == Mode.MANEUVER
    assert plans["power_saver"][0] != Mode.MANEUVER
    assert plans["battery_protective"][0] != Mode.MANEUVER
    assert len(set(plans.values())) >= 5


def test_v27_state_summary_and_detail_schema_boundaries(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--operator-view", "delayed_telemetry",
        "--planning-model", "risk_aware",
        "--maneuver-model", "stationkeeping_proxy",
        "--results-dir", str(tmp_path),
    ]) == 0

    state_row = read_rows(tmp_path / "state_log.csv")[0]
    assert state_row["maneuver_model"] == "stationkeeping_proxy"
    assert DETAILED_MANEUVER_FIELDS <= set(state_row)
    assert DETAILED_CONSEQUENCE_FIELDS <= set(state_row)
    assert AGGREGATE_MANEUVER_FIELDS <= read_fields(tmp_path / "summary.csv")
    assert AGGREGATE_CONSEQUENCE_FIELDS <= read_fields(
        tmp_path / "summary.csv"
    )
    for filename in ("checkpoints.csv", "events_log.csv"):
        fields = read_fields(tmp_path / filename)
        assert "maneuver_model" not in fields
        assert DETAILED_MANEUVER_FIELDS.isdisjoint(fields)
        assert DETAILED_CONSEQUENCE_FIELDS.isdisjoint(fields)


def test_geometry_contacts_are_unchanged_by_maneuver_proxy(tmp_path):
    common = [
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--contact-model", "geometry",
        "--operator-view", "delayed_telemetry",
        "--planning-model", "risk_aware",
    ]
    none_dir = tmp_path / "none"
    proxy_dir = tmp_path / "proxy"
    assert run.main([
        *common, "--maneuver-model", "none",
        "--results-dir", str(none_dir),
    ]) == 0
    assert run.main([
        *common, "--maneuver-model", "stationkeeping_proxy",
        "--results-dir", str(proxy_dir),
    ]) == 0

    none_rows = read_rows(none_dir / "state_log.csv")
    proxy_rows = read_rows(proxy_dir / "state_log.csv")
    contact_fields = (
        "base_cmd_contact_min",
        "base_data_contact_min",
        "cmd_contact_min",
        "data_contact_min",
        "geometry_raw_visible_seconds",
    )
    assert [tuple(row[field] for field in contact_fields) for row in none_rows] == [
        tuple(row[field] for field in contact_fields) for row in proxy_rows
    ]
    row = proxy_rows[0]
    assert row["contact_model"] == "geometry"
    assert "planned_mode" in row
    assert "planning_energy_risk" in row
    assert DETAILED_MANEUVER_FIELDS <= set(row)
    assert DETAILED_CONSEQUENCE_FIELDS <= set(row)


def test_monte_carlo_maneuver_proxy_uses_summary_logging(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "stochastic_post_life_events",
        "--monte-carlo", "2",
        "--operator-view", "delayed_telemetry",
        "--planning-model", "risk_aware",
        "--maneuver-model", "stationkeeping_proxy",
        "--results-dir", str(tmp_path),
    ]) == 0

    for filename in ("summary.csv", "monte_carlo_summary.csv"):
        rows = read_rows(tmp_path / filename)
        assert len(rows) == 2
        assert {row["maneuver_model"] for row in rows} == {
            "stationkeeping_proxy"
        }
        assert AGGREGATE_MANEUVER_FIELDS <= set(rows[0])
        assert AGGREGATE_CONSEQUENCE_FIELDS <= set(rows[0])
        assert STATE_ONLY_MANEUVER_FIELDS.isdisjoint(rows[0])
        assert STATE_ONLY_CONSEQUENCE_FIELDS.isdisjoint(rows[0])
    assert not (tmp_path / "state_log.csv").exists()
    assert not (tmp_path / "checkpoints.csv").exists()
    assert not (tmp_path / "events_log.csv").exists()


def test_readme_documents_v27_boundaries_and_examples():
    readme = Path("README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split()).lower()

    assert "v2.7 fuel, delta-v, and maneuver proxy" in normalized
    assert "--maneuver-model none" in normalized
    assert "default remains" in normalized
    assert "does not affect orbit position, contact geometry" in normalized
    assert "v2.8 orbit evolution and state-aware geometry" in normalized
    assert "not real stationkeeping" in normalized
    assert "tle/sgp4" in normalized
    assert "gmat/stk" in normalized
    assert "low propulsion health" in normalized
    assert "does not itself cause mission loss" in normalized
    assert "debris/conjunction" in normalized
    assert "failed avoidance" in normalized
    assert "damage" in normalized
    assert "not real collision avoidance" in normalized
    assert "not conjunction analysis" in normalized
    assert (
        "only `--contact-model geometry --orbit-evolution-model drift_proxy`"
        in normalized
    )
    assert "`maneuver_count` counts only successful stationkeeping" in normalized
    assert "`debris_avoidance_executed_count` counts only successful" in normalized
    assert "`delta_v_used_m_per_s` remains the total" in normalized
    assert "accumulated event-damage scalar" in normalized
    assert "not multiplied by the number of targets" in normalized
    assert "sum of actual health-field reductions can be larger" in normalized
