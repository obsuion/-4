from copy import deepcopy

import pytest
import run

from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.event_lifecycle import (
    MAXIMUM_CONJUNCTION_WARNING_LEAD_HOURS,
    MINIMUM_CONJUNCTION_WARNING_LEAD_HOURS,
    EventLifecycleManager,
    LifecycleStatus,
)
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import Policy
from ops_sim.scenarios import StochasticPostLifeEventsScenario
from ops_sim.simulator import EVENT_LIFECYCLE_MODELS, Simulator


EXECUTION_HOUR = 96
EVENT_DAMAGE = 0.05


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


def debris_catalog(
    *,
    execution_hour: int = EXECUTION_HOUR,
    duration_hours: int = 1,
    effect: float = EVENT_DAMAGE,
) -> EventCatalog:
    event = ExternalEvent(
        hour=execution_hour,
        event_type="debris_conjunction",
        severity=0.8,
        duration_hours=duration_hours,
        target="adcs_health,thermal_health",
        effect=effect,
        description="deterministic lifecycle acceptance event",
    )
    return EventCatalog(
        events=[event],
        seed=320,
        scenario_name="stochastic_post_life_events",
        total_hours=execution_hour + duration_hours,
    )


def debris_scenario(**catalog_options) -> StochasticPostLifeEventsScenario:
    return StochasticPostLifeEventsScenario(
        event_catalog=debris_catalog(**catalog_options)
    )


class StandbyPolicy(Policy):
    name = "lifecycle_test_standby"

    @property
    def safe_threshold(self) -> float:
        return 0.0

    def select_mode(
        self, state: SatelliteState, contact: ContactInfo
    ) -> Mode:
        return Mode.STANDBY


class ContactSchedule:
    def __init__(
        self,
        command_hours: set[int] | None = None,
        *,
        always_command: bool = False,
        data_contact_min: float = 0.0,
    ) -> None:
        self.command_hours = command_hours or set()
        self.always_command = always_command
        self.data_contact_min = data_contact_min

    def contact_at_hour(self, hour: int) -> ContactInfo:
        has_command = self.always_command or hour in self.command_hours
        return ContactInfo(
            cmd_contact_min=8.0 if has_command else 0.0,
            data_contact_min=self.data_contact_min,
        )


class CommandBlockingDebrisScenario(StochasticPostLifeEventsScenario):
    """Make a nominal command opportunity unavailable after scenario effects."""

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo(data_contact_min=contact_info.data_contact_min)


def test_manager_builds_deterministic_events_with_bounded_warning_lead():
    catalog = debris_catalog()
    first = EventLifecycleManager(catalog)
    second = EventLifecycleManager(catalog)

    assert len(first.events) == 1
    assert first.events[0].as_dict() == second.events[0].as_dict()

    event = first.events[0]
    warning_lead = event.execution_hour - event.warning_hour
    assert MINIMUM_CONJUNCTION_WARNING_LEAD_HOURS <= warning_lead
    assert warning_lead <= MAXIMUM_CONJUNCTION_WARNING_LEAD_HOURS
    assert event.source_event_hour == EXECUTION_HOUR
    assert event.linked_external_event_hour == EXECUTION_HOUR
    assert event.ground_awareness_hour == event.warning_hour
    assert event.decision_deadline_hour == EXECUTION_HOUR - 1
    assert event.status == LifecycleStatus.SCHEDULED.value
    assert first.source_event(event.event_id) is catalog.events[0]


def test_manager_separates_ground_knowledge_from_command_upload_and_state():
    manager = EventLifecycleManager(debris_catalog())
    event = manager.events[0]
    state = SatelliteState(
        soc=63.0,
        data_buffer_gb=17.0,
        mode=Mode.IMAGING,
        payload_health=0.73,
    )
    untouched_state = deepcopy(state)

    before_warning = manager.advance(
        event.warning_hour - 1,
        ContactInfo(cmd_contact_min=12.0, data_contact_min=12.0),
    )
    assert before_warning.ground_known_event_ids == ()
    assert before_warning.spacecraft_known_event_ids == ()
    assert before_warning.uploaded_event_ids == ()
    assert before_warning.transitions == ()

    warning = manager.advance(
        event.warning_hour,
        ContactInfo(data_contact_min=12.0),
    )
    assert warning.ground_known_event_ids == (event.event_id,)
    assert warning.spacecraft_known_event_ids == ()
    assert warning.uploaded_event_ids == ()
    assert event.status == LifecycleStatus.UPLINK_PENDING.value
    assert event.response_uploaded is False
    assert state == untouched_state

    upload = manager.advance(
        event.warning_hour + 1,
        ContactInfo(cmd_contact_min=8.0),
    )
    assert upload.ground_known_event_ids == (event.event_id,)
    assert upload.spacecraft_known_event_ids == (event.event_id,)
    assert upload.uploaded_event_ids == (event.event_id,)
    assert event.status == LifecycleStatus.UPLOADED_TO_SPACECRAFT.value
    assert event.response_upload_hour == event.warning_hour + 1
    assert event.spacecraft_awareness_hour == event.warning_hour + 1
    assert any(
        transition.new_status == LifecycleStatus.KNOWN_TO_GROUND.value
        for transition in manager.transitions
    )
    assert any(
        transition.new_status
        == LifecycleStatus.UPLOADED_TO_SPACECRAFT.value
        for transition in manager.transitions
    )
    assert state == untouched_state


def test_manager_no_command_contact_fails_once_at_tca():
    manager = EventLifecycleManager(debris_catalog())
    event = manager.events[0]

    manager.advance(
        event.warning_hour,
        ContactInfo(data_contact_min=20.0),
    )
    at_tca = manager.advance(event.execution_hour, ContactInfo())

    assert at_tca.ground_known_event_ids == (event.event_id,)
    assert at_tca.spacecraft_known_event_ids == ()
    assert at_tca.avoidance_eligible_event_ids == ()
    assert at_tca.upload_failed_event_ids == (event.event_id,)
    assert event.status == LifecycleStatus.RESOLVED_FAILED.value
    assert event.response_uploaded is False
    assert event.response_executed is False
    assert event.response_skipped is True
    assert event.failure_reason == "no_command_upload_before_tca"
    assert sum(
        transition.new_status == LifecycleStatus.RESOLVED_FAILED.value
        for transition in manager.transitions
    ) == 1


def test_event_lifecycle_none_is_the_v31_debris_behavior():
    assert EVENT_LIFECYCLE_MODELS == ("none", "warning_proxy")
    assert run.build_parser().parse_args([]).event_lifecycle_model == "none"
    with pytest.raises(ValueError, match="event_lifecycle_model must be one of"):
        Simulator(StandbyPolicy(), event_lifecycle_model="invalid")

    initial = SatelliteState(soc=80.0, delta_v_remaining_m_per_s=2.0)
    default_simulator = Simulator(
        StandbyPolicy(),
        debris_scenario(execution_hour=0),
        contact_model=ContactSchedule(),
        maneuver_model="stationkeeping_proxy",
    )
    explicit_none_simulator = Simulator(
        StandbyPolicy(),
        debris_scenario(execution_hour=0),
        contact_model=ContactSchedule(),
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="none",
    )

    default_result = default_simulator.run(
        hours_as_years(1), state=deepcopy(initial)
    )
    explicit_result = explicit_none_simulator.run(
        hours_as_years(1), state=deepcopy(initial)
    )

    assert default_simulator.event_lifecycle_model == "none"
    assert default_simulator.lifecycle_manager is None
    assert explicit_none_simulator.lifecycle_manager is None
    assert default_result.state == explicit_result.state
    assert default_result.metrics == explicit_result.metrics
    assert default_result.events == explicit_result.events
    assert default_result.state.debris_avoidance_executed_count == 1
    assert default_result.state.debris_damage_events == 0


def test_uploaded_response_executes_existing_avoidance_with_sufficient_fuel():
    transitions = []
    records = []
    simulator = Simulator(
        StandbyPolicy(),
        debris_scenario(),
        contact_model=ContactSchedule(always_command=True),
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="warning_proxy",
    )
    result = simulator.run(
        hours_as_years(EXECUTION_HOUR + 1),
        state=SatelliteState(soc=80.0, delta_v_remaining_m_per_s=2.0),
        on_hour=records.append,
        on_lifecycle_transition=transitions.append,
    )

    assert simulator.lifecycle_manager is not None
    event = simulator.lifecycle_manager.events[0]
    assert event.status == LifecycleStatus.RESOLVED_SUCCESS.value
    assert event.response_uploaded is True
    assert event.response_executed is True
    assert event.response_skipped is False
    assert event.failure_reason is None
    assert result.state.debris_avoidance_executed_count == 1
    assert result.state.debris_avoidance_skipped_count == 0
    assert result.state.debris_damage_events == 0
    assert result.state.delta_v_used_m_per_s == pytest.approx(
        DEFAULT_CONFIG.debris_avoidance_delta_v_cost_m_per_s
    )
    assert records[EXECUTION_HOUR].mode == Mode.MANEUVER.value
    assert records[EXECUTION_HOUR].debris_avoidance_executed_this_hour is True
    assert transitions == simulator.lifecycle_manager.transitions


def test_ground_warning_without_upload_applies_debris_damage_only_once():
    duration_hours = 3
    transitions = []
    records = []
    simulator = Simulator(
        StandbyPolicy(),
        CommandBlockingDebrisScenario(
            event_catalog=debris_catalog(duration_hours=duration_hours)
        ),
        contact_model=ContactSchedule(always_command=True),
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="warning_proxy",
    )
    result = simulator.run(
        hours_as_years(EXECUTION_HOUR + duration_hours),
        state=SatelliteState(soc=80.0, delta_v_remaining_m_per_s=2.0),
        on_hour=records.append,
        on_lifecycle_transition=transitions.append,
    )

    assert simulator.lifecycle_manager is not None
    event = simulator.lifecycle_manager.events[0]
    assert event.event_id in simulator.lifecycle_manager.ground_external_awareness
    assert event.event_id not in simulator.lifecycle_manager.spacecraft_awareness
    assert event.response_uploaded is False
    assert event.response_executed is False
    assert event.response_skipped is True
    assert event.failure_reason == "no_command_upload_before_tca"
    assert event.status == LifecycleStatus.RESOLVED_FAILED.value
    assert result.state.debris_avoidance_executed_count == 0
    assert result.state.debris_avoidance_skipped_count == 1
    assert result.state.debris_damage_events == 1
    assert result.state.debris_damage_accumulated == pytest.approx(EVENT_DAMAGE)
    assert result.state.delta_v_used_m_per_s == 0.0
    assert records[EXECUTION_HOUR].debris_damage_this_hour == pytest.approx(
        EVENT_DAMAGE
    )
    assert all(
        record.debris_damage_this_hour == 0.0
        for record in records[EXECUTION_HOUR + 1 :]
    )
    assert transitions == simulator.lifecycle_manager.transitions


def test_uploaded_response_with_insufficient_fuel_resolves_failed():
    simulator = Simulator(
        StandbyPolicy(),
        debris_scenario(),
        contact_model=ContactSchedule(always_command=True),
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="warning_proxy",
    )
    result = simulator.run(
        hours_as_years(EXECUTION_HOUR + 1),
        state=SatelliteState(
            soc=80.0,
            delta_v_remaining_m_per_s=(
                DEFAULT_CONFIG.debris_avoidance_delta_v_cost_m_per_s / 2.0
            ),
        ),
    )

    assert simulator.lifecycle_manager is not None
    event = simulator.lifecycle_manager.events[0]
    assert event.response_uploaded is True
    assert event.response_executed is False
    assert event.response_skipped is True
    assert event.status == LifecycleStatus.RESOLVED_FAILED.value
    assert event.failure_reason == "insufficient_delta_v"
    assert result.state.debris_avoidance_executed_count == 0
    assert result.state.debris_avoidance_skipped_count == 1
    assert result.state.debris_damage_events == 1
    assert result.state.debris_damage_accumulated == pytest.approx(EVENT_DAMAGE)
    assert result.state.delta_v_used_m_per_s == 0.0


def test_no_future_leakage_and_warning_does_not_refresh_delayed_telemetry():
    probe_manager = EventLifecycleManager(debris_catalog())
    warning_hour = probe_manager.events[0].warning_hour
    run_hours = warning_hour + 1
    contact_model = ContactSchedule(command_hours={0})

    lifecycle_records = []
    lifecycle_transitions = []
    lifecycle_simulator = Simulator(
        StandbyPolicy(),
        debris_scenario(),
        contact_model=contact_model,
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="warning_proxy",
    )
    lifecycle_result = lifecycle_simulator.run(
        hours_as_years(run_hours),
        state=SatelliteState(
            soc=71.0,
            data_buffer_gb=13.0,
            payload_health=0.91,
        ),
        on_hour=lifecycle_records.append,
        on_lifecycle_transition=lifecycle_transitions.append,
    )

    control_records = []
    control_simulator = Simulator(
        StandbyPolicy(),
        StochasticPostLifeEventsScenario(
            event_catalog=EventCatalog(
                [], 320, "stochastic_post_life_events", run_hours
            )
        ),
        contact_model=ContactSchedule(command_hours={0}),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="warning_proxy",
    )
    control_result = control_simulator.run(
        hours_as_years(run_hours),
        state=SatelliteState(
            soc=71.0,
            data_buffer_gb=13.0,
            payload_health=0.91,
        ),
        on_hour=control_records.append,
    )

    assert lifecycle_simulator.lifecycle_manager is not None
    event = lifecycle_simulator.lifecycle_manager.events[0]
    assert event.warning_hour == warning_hour
    assert all(
        transition.hour >= warning_hour
        for transition in lifecycle_transitions
    )
    assert lifecycle_result.state == control_result.state
    assert lifecycle_result.metrics == control_result.metrics
    assert [record.mode for record in lifecycle_records] == [
        record.mode for record in control_records
    ]
    assert [record.planned_mode for record in lifecycle_records] == [
        record.planned_mode for record in control_records
    ]

    warning_record = lifecycle_records[warning_hour]
    first_record = lifecycle_records[0]
    assert event.event_id in lifecycle_simulator.lifecycle_manager.ground_external_awareness
    assert event.event_id not in lifecycle_simulator.lifecycle_manager.spacecraft_awareness
    assert warning_record.telemetry_updated_this_hour is False
    assert warning_record.last_telemetry_hour == 0
    assert warning_record.telemetry_age_hours == warning_hour
    assert warning_record.observed_soc == first_record.observed_soc
    assert warning_record.observed_health == first_record.observed_health
    assert warning_record.observed_buffer_gb == first_record.observed_buffer_gb
    assert warning_record.observed_payload_health == (
        first_record.observed_payload_health
    )
    assert lifecycle_simulator.observed_state is not None
    assert lifecycle_simulator.observed_state.mode == Mode.STANDBY
