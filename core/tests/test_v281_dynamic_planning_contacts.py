from dataclasses import replace

import pytest

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


def hours_as_years(hours: int, config=DEFAULT_CONFIG) -> float:
    return hours / config.hours_per_year


def planning_config(**changes) -> SimulationConfig:
    values = {
        "plan_duration_hours": 6,
        "orbit_drift_proxy_km_per_day": 0.24,
        "orbit_drift_threshold_km": 10.0,
        "orbit_drift_warning_threshold_km": 10.0,
        "orbit_drift_critical_threshold_km": 20.0,
        "orbit_phase_error_deg_per_drift_km": 0.0,
        "orbit_altitude_offset_km_per_drift_km": 1.0,
        "orbit_groundtrack_error_km_per_drift_km": 0.0,
        "orbit_geometry_degraded_threshold_km": 10.0,
        "orbit_geometry_critical_threshold_km": 20.0,
        "maximum_orbit_altitude_offset_km": 1000.0,
    }
    values.update(changes)
    return replace(DEFAULT_CONFIG, **values)


def geometry_summary(
    hour: int,
    *,
    cmd_contact_min: float,
    data_contact_min: float,
    diagnostic_value: float,
) -> GeometryContactSummary:
    raw_visible_seconds = max(cmd_contact_min, data_contact_min) * 60.0
    return GeometryContactSummary(
        hour=hour,
        raw_visible_seconds=raw_visible_seconds,
        usable_cmd_seconds=cmd_contact_min * 60.0,
        usable_data_seconds=data_contact_min * 60.0,
        cmd_contact_min=cmd_contact_min,
        data_contact_min=data_contact_min,
        max_elevation_deg=diagnostic_value,
        min_range_km=1000.0 + diagnostic_value,
        first_visible_offset_seconds=(
            0.0 if raw_visible_seconds > 0 else None
        ),
        last_visible_offset_seconds=(
            raw_visible_seconds - 1.0
            if raw_visible_seconds > 0
            else None
        ),
    )


class AltitudeSensitiveGeometryModel(GeometryContactModel):
    """Deterministic probe whose data minutes expose effective altitude."""

    def __init__(self, config: SimulationConfig):
        super().__init__(
            GroundStation(0.0, 0.0, -90.0),
            config,
            step_seconds=config.seconds_per_hour,
        )
        self.dynamic_calls: list[tuple[int, float]] = []

    def contact_summary_at_hour_for_config(
        self, hour: int, orbit_config: SimulationConfig
    ) -> GeometryContactSummary:
        altitude_offset = (
            orbit_config.orbit_altitude_km
            - self.config.orbit_altitude_km
        )
        self.dynamic_calls.append((hour, altitude_offset))
        data_minutes = max(0.0, min(60.0, altitude_offset * 100.0))
        return geometry_summary(
            hour,
            cmd_contact_min=5.0,
            data_contact_min=data_minutes,
            diagnostic_value=altitude_offset,
        )


class HourSensitiveGeometryModel(GeometryContactModel):
    """Geometry-typed forecast probe with a data opportunity at hour two."""

    def __init__(self, config: SimulationConfig):
        super().__init__(
            GroundStation(0.0, 0.0, -90.0),
            config,
            step_seconds=config.seconds_per_hour,
        )

    def contact_summary_at_hour_for_config(
        self, hour: int, orbit_config: SimulationConfig
    ) -> GeometryContactSummary:
        data_minutes = 10.0 if hour == 2 else 0.0
        return geometry_summary(
            hour,
            cmd_contact_min=5.0,
            data_contact_min=data_minutes,
            diagnostic_value=float(hour),
        )


class CountingFixedGeometryModel(GeometryContactModel):
    def __init__(self, config: SimulationConfig):
        super().__init__(
            GroundStation(0.0, 0.0, -90.0),
            config,
            step_seconds=config.seconds_per_hour,
        )
        self.build_hours: list[int] = []
        self.dynamic_hours: list[int] = []

    def _build_contact_summary(
        self, hour: int, orbit_config: SimulationConfig
    ) -> GeometryContactSummary:
        self.build_hours.append(hour)
        return super()._build_contact_summary(hour, orbit_config)

    def contact_summary_at_hour_for_config(
        self, hour: int, orbit_config: SimulationConfig
    ) -> GeometryContactSummary:
        self.dynamic_hours.append(hour)
        return super().contact_summary_at_hour_for_config(
            hour, orbit_config
        )


class FractionRecordingSimulator(Simulator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_contact_fractions: list[float] = []

    def _risk_aware_planned_mode(
        self, state, contact, plan_index, data_contact_fraction, profile
    ):
        self.data_contact_fractions.append(data_contact_fraction)
        return super()._risk_aware_planned_mode(
            state, contact, plan_index, data_contact_fraction, profile
        )


class FutureContactDisruptionScenario(Scenario):
    name = "future_contact_disruption"

    def modify_contacts(
        self, contact: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo() if hour == 2 else contact


class RemoveAllContactsScenario(Scenario):
    name = "remove_all_contacts"

    def modify_contacts(
        self, contact: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo()


def future_debris_scenario(config: SimulationConfig):
    event = ExternalEvent(
        2,
        "debris_conjunction",
        1.0,
        1,
        "solar_health,adcs_health",
        0.05,
        "future test conjunction",
    )
    return StochasticPostLifeEventsScenario(
        event_catalog=EventCatalog(
            [event],
            42,
            "stochastic_post_life_events",
            config.plan_duration_hours,
        )
    )


def test_drift_proxy_plan_contacts_follow_projected_state_each_hour():
    config = planning_config()
    model = AltitudeSensitiveGeometryModel(config)
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=model,
        operator_view="delayed_telemetry",
        planning_model="reactive",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(hours_as_years(1, config))

    plan = result.state.current_plan
    assert plan is not None
    # The real upload-hour state has 0.01 km of mapped altitude error. Each
    # following planned hour advances its private projected state by 0.01 km.
    assert plan.expected_data_contact_min_by_hour[:4] == pytest.approx(
        (1.0, 2.0, 3.0, 4.0)
    )
    calls_by_hour = dict(model.dynamic_calls)
    assert calls_by_hour[1] == pytest.approx(0.02)
    assert calls_by_hour[2] == pytest.approx(0.03)
    assert calls_by_hour[3] == pytest.approx(0.04)


def test_risk_aware_projected_correction_changes_later_geometry_forecast():
    config = planning_config(
        orbit_geometry_degraded_threshold_km=0.025,
        orbit_geometry_critical_threshold_km=1.0,
        orbit_drift_reduction_per_maneuver_km=0.03,
        stationkeeping_phase_correction_fraction=1.0,
        stationkeeping_altitude_correction_fraction=1.0,
        stationkeeping_groundtrack_correction_fraction=1.0,
    )
    model = AltitudeSensitiveGeometryModel(config)
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=model,
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(hours_as_years(1, config))

    plan = result.state.current_plan
    assert plan is not None
    assert plan.planned_modes[2] == Mode.MANEUVER
    assert plan.expected_data_contact_min_by_hour[2] == pytest.approx(3.0)
    # The projected correction at index 2 removes 0.03 km of drift/error;
    # normal drift then adds 0.01 km before index 3 is forecast.
    assert plan.expected_data_contact_min_by_hour[3] == pytest.approx(1.0)
    assert (
        plan.expected_data_contact_min_by_hour[3]
        < plan.expected_data_contact_min_by_hour[2]
    )


def test_state_aware_plan_cache_reuses_identical_projected_contacts():
    config = planning_config()
    model = AltitudeSensitiveGeometryModel(config)
    simulator = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=model,
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    )
    simulator.run(hours_as_years(1, config))

    # One actual upload-hour sample plus one sample for each distinct future
    # hour/state pair; repeated remaining-horizon forecasts hit the plan cache.
    assert [hour for hour, _ in model.dynamic_calls] == list(
        range(config.plan_duration_hours)
    )
    assert set(simulator._state_aware_geometry_summaries) == {0}


def test_synthetic_plan_forecast_keeps_the_established_schedule():
    config = planning_config()
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=SyntheticContactModel(config),
        operator_view="delayed_telemetry",
        planning_model="reactive",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(hours_as_years(1, config))

    plan = result.state.current_plan
    assert plan is not None
    assert plan.expected_cmd_contact_min_by_hour == (
        15, 0.0, 0.0, 0.0, 15, 0.0,
    )
    assert plan.expected_data_contact_min_by_hour == (
        15, 0.0, 0.0, 0.0, 15, 0.0,
    )


def test_synthetic_risk_planning_keeps_the_v28_whole_plan_fraction():
    config = planning_config()
    simulator = FractionRecordingSimulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=SyntheticContactModel(config),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    )
    simulator.run(hours_as_years(1, config))

    assert simulator.data_contact_fractions == pytest.approx(
        [2 / config.plan_duration_hours] * config.plan_duration_hours
    )


def test_geometry_fixed_planning_retains_hour_cache_and_never_uses_state_path():
    config = planning_config()
    model = CountingFixedGeometryModel(config)
    result = Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=model,
        operator_view="delayed_telemetry",
        planning_model="reactive",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="fixed",
    ).run(hours_as_years(1, config))

    assert result.state.current_plan is not None
    assert model.dynamic_hours == []
    assert model.build_hours == list(range(config.plan_duration_hours))
    assert set(model._summary_cache) == set(range(config.plan_duration_hours))
    builds_before = list(model.build_hours)
    first = model.contact_summary_at_hour(2)
    second = model.contact_summary_at_hour(2)
    assert first is second
    assert model.build_hours == builds_before


def test_future_scenario_disruption_is_not_applied_to_plan_forecast():
    config = planning_config(orbit_drift_proxy_km_per_day=0.0)
    records = []
    Simulator(
        make_policy("downlink_priority", config),
        FutureContactDisruptionScenario(),
        config=config,
        contact_model=HourSensitiveGeometryModel(config),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(
        hours_as_years(3, config),
        state=SatelliteState(soc=80.0, data_buffer_gb=100.0),
        on_hour=records.append,
    )

    assert records[2].base_data_contact_min == 10.0
    assert records[2].data_contact_min == 0.0
    assert records[2].planning_expected_data_contact_min == 10.0
    assert records[2].planned_mode == Mode.DOWNLINK.value


def test_future_debris_event_is_not_visible_to_plan_generation():
    config = planning_config(
        orbit_drift_proxy_km_per_day=0.0,
        orbit_geometry_degraded_threshold_km=10.0,
    )

    def build_plan(scenario):
        result = Simulator(
            make_policy("adaptive", config),
            scenario,
            config=config,
            contact_model=HourSensitiveGeometryModel(config),
            operator_view="delayed_telemetry",
            planning_model="risk_aware",
            maneuver_model="stationkeeping_proxy",
            orbit_evolution_model="drift_proxy",
        ).run(hours_as_years(1, config))
        return result.state.current_plan

    baseline = build_plan(Scenario())
    with_future_debris = build_plan(future_debris_scenario(config))
    assert baseline is not None
    assert with_future_debris is not None
    assert with_future_debris.planned_modes == baseline.planned_modes
    assert (
        with_future_debris.expected_cmd_contact_min_by_hour
        == baseline.expected_cmd_contact_min_by_hour
    )
    assert (
        with_future_debris.expected_data_contact_min_by_hour
        == baseline.expected_data_contact_min_by_hour
    )


def test_delayed_plan_upload_still_requires_final_modified_command_contact():
    config = planning_config(orbit_drift_proxy_km_per_day=0.0)
    records = []
    result = Simulator(
        make_policy("adaptive", config),
        RemoveAllContactsScenario(),
        config=config,
        contact_model=HourSensitiveGeometryModel(config),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ).run(hours_as_years(1, config), on_hour=records.append)

    assert records[0].base_cmd_contact_min == 5.0
    assert records[0].cmd_contact_min == 0.0
    assert records[0].telemetry_updated_this_hour is False
    assert records[0].plan_uploaded_this_hour is False
    assert result.state.current_plan is None
