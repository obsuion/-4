from copy import deepcopy
from dataclasses import replace

import pytest

from ops_sim.config import DEFAULT_CONFIG, SimulationConfig
from ops_sim.contacts import (
    GeometryContactModel,
    GeometryContactSummary,
    GroundStation,
)
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.models import ContactInfo, DailyPlan, Mode, SatelliteState
from ops_sim.orbit import position_at_hour
from ops_sim.policies import Policy, make_policy
from ops_sim.scenarios import Scenario, StochasticPostLifeEventsScenario
from ops_sim.simulator import Simulator


def hours_as_years(hours: int, config=DEFAULT_CONFIG) -> float:
    return hours / config.hours_per_year


class RecordingContactModel:
    def __init__(self):
        self.hours: list[int] = []

    def contact_at_hour(self, hour: int) -> ContactInfo:
        self.hours.append(hour)
        return ContactInfo()


class RecordingScenario(Scenario):
    name = "recording_continuation"

    def __init__(self):
        self.event_hours: list[int] = []
        self.pre_hours: list[int] = []
        self.contact_hours: list[int] = []
        self.post_hours: list[int] = []

    def events_at_hour(self, hour: int) -> list[tuple[str, str]]:
        self.event_hours.append(hour)
        return [("absolute_event", "absolute event at hour five")] if hour == 5 else []

    def apply_pre_hour(self, state: SatelliteState, hour: int) -> None:
        self.pre_hours.append(hour)

    def modify_contacts(
        self, contact: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        self.contact_hours.append(hour)
        return contact

    def apply_post_hour(self, state: SatelliteState, hour: int) -> None:
        self.post_hours.append(hour)


class NoContactModel:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo()


class RecordingPolicy(Policy):
    name = "recording_continuation_policy"

    def __init__(self):
        super().__init__()
        self.calls = 0

    @property
    def safe_threshold(self) -> float:
        return DEFAULT_CONFIG.adaptive_safe_threshold

    def select_mode(
        self, state: SatelliteState, contact: ContactInfo
    ) -> Mode:
        self.calls += 1
        return Mode.IMAGING


class RecordingGeometryModel(GeometryContactModel):
    def __init__(self, config: SimulationConfig):
        super().__init__(
            GroundStation(0.0, 0.0, 5.0),
            config,
            step_seconds=config.seconds_per_hour,
        )
        self.calls: list[tuple[int, float]] = []

    def contact_summary_at_hour_for_config(
        self, hour: int, orbit_config: SimulationConfig
    ) -> GeometryContactSummary:
        self.calls.append((hour, orbit_config.orbit_altitude_km))
        return GeometryContactSummary(
            hour=hour,
            raw_visible_seconds=0.0,
            usable_cmd_seconds=0.0,
            usable_data_seconds=0.0,
            cmd_contact_min=0.0,
            data_contact_min=0.0,
            max_elevation_deg=None,
            min_range_km=None,
            first_visible_offset_seconds=None,
            last_visible_offset_seconds=None,
        )


def continuation_plan() -> DailyPlan:
    modes = (
        Mode.STANDBY,
        Mode.IMAGING,
        Mode.DOWNLINK,
        Mode.SAFE,
    ) + (Mode.STANDBY,) * 20
    return DailyPlan(
        uploaded_hour=3,
        duration_hours=24,
        planned_modes=modes,
        policy_name="recording_continuation_policy",
        based_on_telemetry_hour=3,
        based_on_telemetry_age_hours=0,
    )


def test_default_start_hour_zero_preserves_existing_behavior():
    implicit_records = []
    explicit_records = []
    implicit = Simulator(make_policy("adaptive")).run(
        hours_as_years(3), on_hour=implicit_records.append
    )
    explicit = Simulator(make_policy("adaptive")).run(
        hours_as_years(3),
        on_hour=explicit_records.append,
        start_hour=0,
    )

    assert implicit.state == explicit.state
    assert implicit.metrics == explicit.metrics
    assert implicit.total_hours == explicit.total_hours == 3
    assert implicit_records == explicit_records


@pytest.mark.parametrize("start_hour", [-1, 1.5, "1", True])
def test_start_hour_must_be_a_non_negative_integer(start_hour):
    with pytest.raises(
        ValueError, match="start_hour must be a non-negative integer"
    ):
        Simulator(make_policy("adaptive")).run(
            0.0, state=SatelliteState(), start_hour=start_hour
        )


def test_nonzero_start_requires_matching_supplied_state():
    simulator = Simulator(make_policy("adaptive"))
    with pytest.raises(
        ValueError, match="state is required when start_hour is non-zero"
    ):
        simulator.run(0.0, start_hour=5)

    with pytest.raises(
        ValueError, match="state.hours_completed must equal start_hour"
    ):
        simulator.run(
            0.0,
            state=SatelliteState(hours_completed=4),
            start_hour=5,
        )

    with pytest.raises(
        ValueError, match="state.hours_completed must equal start_hour"
    ):
        simulator.run(
            0.0,
            state=SatelliteState(hours_completed=1),
        )


def test_continuation_routes_absolute_hours_to_every_hourly_interface():
    scenario = RecordingScenario()
    contacts = RecordingContactModel()
    records = []
    emitted = []
    result = Simulator(
        make_policy("adaptive"), scenario, contact_model=contacts
    ).run(
        hours_as_years(2),
        state=SatelliteState(hours_completed=5),
        start_hour=5,
        on_hour=records.append,
        on_event=emitted.append,
    )

    assert contacts.hours == [5, 6]
    assert scenario.event_hours == [5, 6]
    assert scenario.pre_hours == [5, 6]
    assert scenario.contact_hours == [5, 6]
    assert scenario.post_hours == [5, 6]
    assert [record.hour for record in records] == [5, 6]
    assert [record.year for record in records] == pytest.approx([
        5 / DEFAULT_CONFIG.hours_per_year,
        6 / DEFAULT_CONFIG.hours_per_year,
    ])
    assert [event.hour for event in emitted] == [5]
    assert emitted[0].year == pytest.approx(
        5 / DEFAULT_CONFIG.hours_per_year
    )
    assert result.state.hours_completed == 7
    assert result.total_hours == 7
    assert result.requested_years == pytest.approx(hours_as_years(2))


def test_split_run_matches_one_monolithic_run_for_nominal_operations():
    full = Simulator(make_policy("adaptive")).run(hours_as_years(8))

    first = Simulator(make_policy("adaptive")).run(hours_as_years(3))
    continued = Simulator(make_policy("adaptive")).run(
        hours_as_years(5),
        state=first.state,
        start_hour=3,
    )

    assert continued.total_hours == 8
    assert continued.state == full.state
    assert continued.metrics == full.metrics


def test_checkpoint_cadence_and_positions_use_absolute_completed_hour():
    config = replace(DEFAULT_CONFIG, checkpoint_hours=3)
    result = Simulator(
        make_policy("adaptive", config), config=config
    ).run(
        hours_as_years(4, config),
        state=SatelliteState(hours_completed=2),
        start_hour=2,
    )

    assert result.state.hours_completed == 6
    assert result.total_hours == 6
    assert [checkpoint.hour for checkpoint in result.checkpoints] == [3, 6]
    assert [checkpoint.year for checkpoint in result.checkpoints] == pytest.approx([
        3 / config.hours_per_year,
        6 / config.hours_per_year,
    ])
    expected = position_at_hour(6, config)
    assert result.checkpoints[-1].sat_lat_deg == pytest.approx(
        expected.latitude_deg
    )
    assert result.checkpoints[-1].sat_lon_deg == pytest.approx(
        expected.longitude_deg
    )


def test_delayed_continuation_uses_absolute_stored_plan_indices():
    policy = RecordingPolicy()
    records = []
    state = SatelliteState(
        soc=80.0,
        data_buffer_gb=10.0,
        hours_completed=5,
        current_plan=continuation_plan(),
    )
    result = Simulator(
        policy,
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
    ).run(
        hours_as_years(2),
        state=state,
        start_hour=5,
        on_hour=records.append,
    )

    assert policy.calls == 0
    assert [record.plan_mode_index for record in records] == [2, 3]
    assert [record.planned_mode for record in records] == [
        Mode.DOWNLINK.value,
        Mode.SAFE.value,
    ]
    assert [record.mode for record in records] == [
        Mode.DOWNLINK.value,
        Mode.SAFE.value,
    ]
    assert result.state.daily_plan_age_hours == 3


@pytest.mark.parametrize("copy_warm_context", [False, True])
def test_warmed_simulator_preserves_stale_delayed_operator_snapshot(
    copy_warm_context,
):
    simulator = Simulator(
        RecordingPolicy(),
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
    )
    warm = simulator.run(hours_as_years(2))
    stale_soc = simulator.observed_state.soc
    assert warm.state.soc != pytest.approx(stale_soc)
    continuation_simulator = (
        deepcopy(simulator) if copy_warm_context else simulator
    )
    continuation_state = (
        deepcopy(warm.state) if copy_warm_context else warm.state
    )

    records = []
    continuation_simulator.run(
        hours_as_years(1),
        state=continuation_state,
        start_hour=2,
        on_hour=records.append,
    )

    assert records[0].telemetry_updated_this_hour is False
    assert records[0].last_telemetry_hour == 0
    assert records[0].telemetry_age_hours == 2
    assert records[0].observed_soc == pytest.approx(stale_soc)
    assert records[0].soc != pytest.approx(records[0].observed_soc)


def test_fresh_delayed_continuation_uses_known_boundary_snapshot_safely():
    warm_simulator = Simulator(
        RecordingPolicy(),
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
    )
    warm = warm_simulator.run(hours_as_years(2))
    boundary_state = deepcopy(warm.state)
    boundary_soc = boundary_state.soc
    records = []

    Simulator(
        RecordingPolicy(),
        contact_model=NoContactModel(),
        operator_view="delayed_telemetry",
    ).run(
        hours_as_years(1),
        state=boundary_state,
        start_hour=2,
        on_hour=records.append,
    )

    assert records[0].telemetry_updated_this_hour is False
    assert records[0].last_telemetry_hour == 2
    assert records[0].telemetry_age_hours == 0
    assert records[0].observed_soc == pytest.approx(boundary_soc)


def test_drift_proxy_geometry_and_position_logging_use_absolute_hour():
    config = replace(
        DEFAULT_CONFIG,
        orbit_drift_proxy_km_per_day=0.0,
        maximum_orbit_altitude_offset_km=1000.0,
    )
    geometry = RecordingGeometryModel(config)
    records = []
    state = SatelliteState(
        hours_completed=10,
        orbit_altitude_offset_km=25.0,
    )
    Simulator(
        make_policy("adaptive", config),
        config=config,
        contact_model=geometry,
        maneuver_model="none",
        orbit_evolution_model="drift_proxy",
    ).run(
        hours_as_years(2, config),
        state=state,
        start_hour=10,
        on_hour=records.append,
    )

    assert [hour for hour, _ in geometry.calls] == [10, 11]
    assert [altitude for _, altitude in geometry.calls] == pytest.approx([
        config.orbit_altitude_km + 25.0,
        config.orbit_altitude_km + 25.0,
    ])
    assert [record.hour for record in records] == [10, 11]
    fixed_at_ten = position_at_hour(10, config)
    assert records[0].fixed_orbit_sat_lat_deg == pytest.approx(
        fixed_at_ten.latitude_deg
    )
    assert records[0].fixed_orbit_sat_lon_deg == pytest.approx(
        fixed_at_ten.longitude_deg
    )
    assert records[0].sat_alt_km == pytest.approx(
        config.orbit_altitude_km + 25.0
    )


def test_active_debris_event_from_prior_hour_is_not_resolved_twice():
    event = ExternalEvent(
        4,
        "debris_conjunction",
        1.0,
        3,
        "solar_health,adcs_health",
        0.05,
        "cross-boundary conjunction",
    )
    scenario = StochasticPostLifeEventsScenario(
        event_catalog=EventCatalog(
            [event], 42, "stochastic_post_life_events", 7
        )
    )
    records = []
    state = SatelliteState(
        hours_completed=5,
        debris_avoidance_executed_count=1,
        delta_v_remaining_m_per_s=9.8,
        delta_v_used_m_per_s=0.2,
    )
    result = Simulator(
        make_policy("adaptive"),
        scenario,
        maneuver_model="stationkeeping_proxy",
    ).run(
        hours_as_years(2),
        state=state,
        start_hour=5,
        on_hour=records.append,
    )

    assert all(record.debris_conjunction_active for record in records)
    assert not any(
        record.debris_avoidance_required_this_hour for record in records
    )
    assert result.state.debris_avoidance_executed_count == 1
    assert result.state.debris_avoidance_skipped_count == 0
    assert result.state.debris_damage_events == 0
    assert result.state.delta_v_used_m_per_s == pytest.approx(0.2)
