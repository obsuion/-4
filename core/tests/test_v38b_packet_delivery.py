"""Focused V3.8B bounded packet delivery/retry proxy tests."""

from copy import deepcopy
from dataclasses import asdict, fields
from pathlib import Path

import pytest

import decision_report
import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.event_lifecycle import EventLifecycleManager, LifecycleStatus
from ops_sim.models import ContactInfo, DailyPlan, Mode, SatelliteState
from ops_sim.packets import (
    PACKET_DELIVERY_MODELS,
    assess_packet_delivery,
    assess_packets_for_hour,
)
from ops_sim.policies import make_policy
from ops_sim.scenarios import Scenario, StochasticPostLifeEventsScenario
from ops_sim.simulator import HourRecord, SimulationResult, Simulator


DELIVERY_HOUR_FIELDS = {
    "packet_delivery_model",
    "telemetry_packet_delivery_attempted_this_hour",
    "telemetry_packet_delivery_failed_this_hour",
    "command_packets_attempted_this_hour",
    "command_packets_failed_this_hour",
    "daily_plan_packet_delivery_attempted_this_hour",
    "daily_plan_packet_delivery_failed_this_hour",
    "packet_delivery_reason_this_hour",
}

DELIVERY_SUMMARY_FIELDS = {
    "packet_delivery_model",
    "packet_delivery_seed",
    "packet_drop_fraction_proxy",
    "telemetry_delivery_attempts",
    "telemetry_delivery_failures",
    "command_packet_attempts",
    "command_packet_failures",
    "daily_plan_packet_attempts",
    "daily_plan_packet_failures",
    "packet_delivery_failure_events",
    "max_telemetry_age_hours",
}


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


class ContactSchedule:
    def __init__(self, command_hours=(), *, always_command=False) -> None:
        self.command_hours = set(command_hours)
        self.always_command = always_command

    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(
            cmd_contact_min=(
                8.0
                if self.always_command or hour in self.command_hours
                else 0.0
            )
        )


class BlockContact(Scenario):
    name = "block_packet_contact"

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo()


def debris_catalog(execution_hour: int = 12, count: int = 1) -> EventCatalog:
    events = [
        ExternalEvent(
            hour=execution_hour,
            event_type="debris_conjunction",
            severity=0.8,
            duration_hours=1,
            target="adcs_health,thermal_health",
            effect=0.02,
            description=f"V3.8B delivery event {index}",
        )
        for index in range(count)
    ]
    return EventCatalog(
        events,
        380,
        "stochastic_post_life_events",
        execution_hour + 1,
    )


def operational_record(record: HourRecord) -> dict[str, object]:
    packet_fields = {
        field.name
        for field in fields(HourRecord)
        if field.name.startswith("packet_")
        or field.name.startswith("telemetry_packet_")
        or field.name.startswith("command_packets_")
        or field.name.startswith("daily_plan_packet_")
    }
    return {
        key: value
        for key, value in asdict(record).items()
        if key not in packet_fields
    }


def test_delivery_selectors_defaults_validation_and_cli() -> None:
    assert PACKET_DELIVERY_MODELS == ("ideal", "loss_retry_proxy")
    default = Simulator(make_policy("adaptive"))
    assert default.packet_delivery_model == "ideal"
    assert default.packet_delivery_seed == 0
    assert default.packet_drop_fraction_proxy == pytest.approx(0.10)
    assert run.build_parser().parse_args([]).packet_delivery_model == "ideal"
    assert (
        decision_report.build_parser().parse_args([]).packet_delivery_model
        == "ideal"
    )
    for selector in PACKET_DELIVERY_MODELS:
        assert run.build_parser().parse_args([
            "--packet-delivery-model", selector
        ]).packet_delivery_model == selector
    with pytest.raises(ValueError, match="packet_delivery_model"):
        Simulator(
            make_policy("adaptive"),
            packet_model="packet_proxy",
            packet_delivery_model="radio",
        )
    with pytest.raises(ValueError, match="requires packet_model"):
        Simulator(
            make_policy("adaptive"),
            packet_delivery_model="loss_retry_proxy",
        )
    for invalid in (-0.01, 1.01, float("nan")):
        with pytest.raises(ValueError, match="packet_drop_fraction_proxy"):
            Simulator(
                make_policy("adaptive"),
                packet_model="packet_proxy",
                packet_delivery_model="loss_retry_proxy",
                packet_drop_fraction_proxy=invalid,
            )


def test_delivery_draw_edges_repeatability_seed_variation() -> None:
    def outcome(seed: int, hour: int, fraction: float = 0.5):
        return assess_packet_delivery(
            packet_delivery_model="loss_retry_proxy",
            attempted=True,
            packet_delivery_seed=seed,
            hour=hour,
            packet_kind="housekeeping_telemetry",
            direction="downlink",
            packet_drop_fraction_proxy=fraction,
        )

    assert outcome(7, 5, 0.0).delivered is True
    assert outcome(7, 5, 1.0).failed is True
    assert outcome(7, 5) == outcome(7, 5)
    sequence_a = [outcome(1, hour).delivered for hour in range(24)]
    sequence_b = [outcome(2, hour).delivered for hour in range(24)]
    assert sequence_a != sequence_b


def test_direct_packet_assessment_rejects_legacy_nonideal_delivery() -> None:
    with pytest.raises(ValueError, match="requires packet_model"):
        assess_packets_for_hour(
            packet_model="legacy",
            packet_delivery_model="loss_retry_proxy",
            telemetry_updated_this_hour=False,
            plan_uploaded_this_hour=False,
        )


def test_ideal_and_zero_drop_have_no_operational_differences() -> None:
    def execute(delivery_model: str, drop_fraction: float):
        records = []
        result = Simulator(
            make_policy("adaptive"),
            contact_model=ContactSchedule(command_hours={0, 4, 8, 12}),
            operator_view="delayed_telemetry",
            autonomy_model="contingency_plan",
            target_model="scene_scheduling_proxy",
            pointing_model="bounded_pointing_proxy",
            power_model="eclipse_proxy",
            thermal_model="load_stress_proxy",
            packet_model="packet_proxy",
            packet_delivery_model=delivery_model,
            packet_delivery_seed=41,
            packet_drop_fraction_proxy=drop_fraction,
        ).run(hours_as_years(16), on_hour=records.append)
        return result, records

    ideal, ideal_records = execute("ideal", 0.10)
    zero, zero_records = execute("loss_retry_proxy", 0.0)
    assert ideal.state == zero.state
    assert ideal.metrics == zero.metrics
    assert [operational_record(row) for row in ideal_records] == [
        operational_record(row) for row in zero_records
    ]
    assert ideal.telemetry_packets_downlinked == zero.telemetry_packets_downlinked
    assert ideal.command_packets_uploaded == zero.command_packets_uploaded
    assert ideal.daily_plan_packets_uploaded == zero.daily_plan_packets_uploaded


def test_forced_telemetry_loss_preserves_stale_observation_then_retries_latest() -> None:
    simulator = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={0, 2}),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=1.0,
    )
    first_records = []
    first = simulator.run(hours_as_years(2), on_hour=first_records.append)
    assert first_records[0].telemetry_packet_delivery_attempted_this_hour is True
    assert first_records[0].telemetry_packet_downlinked_this_hour is False
    assert first_records[0].telemetry_packet_delivery_failed_this_hour is True
    assert simulator.last_telemetry_hour == 0
    assert simulator.telemetry_age_hours == 1
    assert simulator.observed_state is not None
    assert simulator.observed_state.hours_completed == 0

    latest_state = deepcopy(first.state)
    simulator.packet_drop_fraction_proxy = 0.0
    retry_records = []
    simulator.run(
        hours_as_years(1),
        state=first.state,
        start_hour=2,
        on_hour=retry_records.append,
    )
    assert retry_records[0].telemetry_packet_delivery_attempted_this_hour is True
    assert retry_records[0].telemetry_packet_downlinked_this_hour is True
    assert retry_records[0].telemetry_packet_delivery_failed_this_hour is False
    assert simulator.last_telemetry_hour == 2
    assert simulator.telemetry_age_hours == 0
    assert simulator.observed_state == latest_state


def test_no_contact_or_scenario_removed_contact_creates_no_attempt_or_failure() -> None:
    for scenario in (Scenario(), BlockContact()):
        records = []
        Simulator(
            make_policy("adaptive"),
            scenario,
            contact_model=ContactSchedule(
                command_hours={0} if isinstance(scenario, BlockContact) else set()
            ),
            operator_view="delayed_telemetry",
            packet_model="packet_proxy",
            packet_delivery_model="loss_retry_proxy",
            packet_drop_fraction_proxy=1.0,
        ).run(hours_as_years(1), on_hour=records.append)
        assert records[0].telemetry_packet_generated_this_hour is True
        assert records[0].telemetry_packet_delivery_attempted_this_hour is False
        assert records[0].telemetry_packet_delivery_failed_this_hour is False


def test_standalone_and_warmed_continuation_delivery_semantics() -> None:
    supplied = SatelliteState(hours_completed=5, soc=61.0)
    standalone_records = []
    Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=1.0,
    ).run(
        hours_as_years(1),
        state=supplied,
        start_hour=5,
        on_hour=standalone_records.append,
    )
    assert standalone_records[0].telemetry_packet_delivery_attempted_this_hour is False
    assert standalone_records[0].telemetry_packet_downlinked_this_hour is False

    simulator = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={0, 3}),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=1.0,
    )
    first = simulator.run(hours_as_years(2))
    observed = deepcopy(simulator.observed_state)
    second_records = []
    simulator.run(
        hours_as_years(2),
        state=first.state,
        start_hour=2,
        on_hour=second_records.append,
    )
    assert second_records[0].telemetry_age_hours == 2
    assert second_records[1].telemetry_packet_delivery_failed_this_hour is True
    assert simulator.observed_state == observed


def test_daily_plan_failure_preserves_plan_age_and_retries() -> None:
    old_plan = DailyPlan(
        uploaded_hour=0,
        duration_hours=24,
        planned_modes=(Mode.STANDBY,) * 24,
    )
    state = SatelliteState(
        hours_completed=24,
        current_plan=old_plan,
        daily_plan_age_hours=24,
        hours_since_contact=7,
    )
    simulator = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={24, 25}),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=1.0,
    )
    failed_records = []
    failed = simulator.run(
        hours_as_years(1),
        state=state,
        start_hour=24,
        on_hour=failed_records.append,
    )
    assert failed_records[0].daily_plan_packet_delivery_attempted_this_hour is True
    assert failed_records[0].daily_plan_packet_uploaded_this_hour is False
    assert failed_records[0].daily_plan_packet_delivery_failed_this_hour is True
    assert failed.state.current_plan is old_plan
    assert failed.state.daily_plan_age_hours == 24
    assert failed.state.hours_since_contact == 0
    assert failed.state.backup_mode is True

    simulator.packet_drop_fraction_proxy = 0.0
    retry_records = []
    retried = simulator.run(
        hours_as_years(1),
        state=failed.state,
        start_hour=25,
        on_hour=retry_records.append,
    )
    assert retry_records[0].daily_plan_packet_uploaded_this_hour is True
    assert retried.state.current_plan is not old_plan
    assert retried.state.current_plan.uploaded_hour == 25
    assert retried.state.daily_plan_age_hours == 0
    assert retried.state.backup_mode is False


def test_daily_plan_attempt_predicate_matches_installation_logic() -> None:
    valid_plan = DailyPlan(
        uploaded_hour=0,
        duration_hours=24,
        planned_modes=(Mode.STANDBY,) * 24,
    )
    exhausted_plan = DailyPlan(
        uploaded_hour=0,
        duration_hours=24,
        planned_modes=(Mode.STANDBY,),
    )
    cases = (
        ("no_current_plan", SatelliteState(), ContactInfo(8.0), 0, True),
        (
            "valid_current_plan",
            SatelliteState(current_plan=valid_plan),
            ContactInfo(8.0),
            1,
            False,
        ),
        (
            "expired_current_plan",
            SatelliteState(current_plan=valid_plan),
            ContactInfo(8.0),
            24,
            True,
        ),
        (
            "exhausted_planned_modes",
            SatelliteState(current_plan=exhausted_plan),
            ContactInfo(8.0),
            1,
            True,
        ),
        ("no_command_contact", SatelliteState(), ContactInfo(), 0, False),
    )

    for case_name, state, contact, hour, expected in cases:
        simulator = Simulator(
            make_policy("adaptive"),
            operator_view="delayed_telemetry",
        )
        original_plan = state.current_plan
        attempt_needed = simulator._daily_plan_upload_needed(
            state, contact, hour
        )
        installed = simulator._update_plan_and_contact_state(
            state,
            contact,
            hour,
            policy_state=deepcopy(state),
            upload_allowed=True,
        )

        assert attempt_needed is expected, case_name
        assert installed is attempt_needed, case_name
        if installed:
            assert state.current_plan is not original_plan, case_name
            assert state.current_plan.uploaded_hour == hour, case_name
        else:
            assert state.current_plan is original_plan, case_name


def test_physical_contact_preserves_emergency_timer_semantics_on_plan_loss() -> None:
    state = SatelliteState(
        hours_completed=10,
        hours_since_contact=DEFAULT_CONFIG.emergency_after_hours - 1,
    )
    records = []
    result = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={10}),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=1.0,
    ).run(
        hours_as_years(1),
        state=state,
        start_hour=10,
        on_hour=records.append,
    )
    assert records[0].daily_plan_packet_delivery_failed_this_hour is True
    assert result.state.hours_since_contact == 0
    assert result.state.emergency_beacon_mode is False
    assert result.state.backup_mode is True


def test_lifecycle_gate_preserves_ground_awareness_and_retries() -> None:
    manager = EventLifecycleManager(debris_catalog())
    event = manager.events[0]
    if event.warning_hour > 0:
        before = manager.advance(event.warning_hour - 1, ContactInfo())
        assert before.ground_known_event_ids == ()
    failed = manager.advance(
        event.warning_hour,
        ContactInfo(cmd_contact_min=8.0),
        command_upload_allowed=False,
    )
    assert failed.ground_known_event_ids == (event.event_id,)
    assert failed.spacecraft_known_event_ids == ()
    assert failed.upload_attempted_event_ids == (event.event_id,)
    assert failed.upload_delivery_failed_event_ids == (event.event_id,)
    assert event.status == LifecycleStatus.UPLINK_PENDING.value
    assert event.response_uploaded is False

    uploaded = manager.advance(
        event.warning_hour + 1,
        ContactInfo(cmd_contact_min=8.0),
        command_upload_allowed=True,
    )
    assert uploaded.upload_attempted_event_ids == (event.event_id,)
    assert uploaded.upload_delivery_failed_event_ids == ()
    assert event.status == LifecycleStatus.UPLOADED_TO_SPACECRAFT.value
    assert event.response_uploaded is True
    assert event.spacecraft_awareness_hour == event.warning_hour + 1


def test_lifecycle_forced_failure_through_tca_uses_existing_damage_path() -> None:
    catalog = debris_catalog(execution_hour=12)
    simulator = Simulator(
        make_policy("adaptive"),
        StochasticPostLifeEventsScenario(event_catalog=catalog),
        contact_model=ContactSchedule(always_command=True),
        event_lifecycle_model="warning_proxy",
        debris_risk_model="severity_proxy",
        maneuver_model="stationkeeping_proxy",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=1.0,
    )
    records = []
    result = simulator.run(hours_as_years(13), on_hour=records.append)
    event = simulator.lifecycle_manager.events[0]
    assert event.event_id in simulator.lifecycle_manager.ground_external_awareness
    assert event.event_id not in simulator.lifecycle_manager.spacecraft_awareness
    assert event.status == LifecycleStatus.RESOLVED_FAILED.value
    assert event.failure_reason == "no_command_upload_before_tca"
    assert result.state.debris_avoidance_executed_count == 0
    assert result.state.debris_avoidance_skipped_count == 1
    assert result.state.debris_damage_events == 1
    assert result.command_packet_attempts == result.command_packet_failures
    assert result.command_packets_uploaded == 0


def test_multiple_lifecycle_failures_preserve_packet_multiplicity() -> None:
    manager = EventLifecycleManager(debris_catalog(execution_hour=20, count=2))
    attempt_hour = max(event.warning_hour for event in manager.events)
    context = manager.advance(
        attempt_hour,
        ContactInfo(cmd_contact_min=8.0),
        command_upload_allowed=False,
    )
    assert len(context.upload_attempted_event_ids) == 2
    assert len(context.upload_delivery_failed_event_ids) == 2
    assert all(
        event.status == LifecycleStatus.UPLINK_PENDING.value
        for event in manager.events
    )


def test_contingency_failure_does_not_create_authority_and_retries() -> None:
    simulator = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={0, 1}),
        autonomy_model="contingency_plan",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=1.0,
    )
    failed_records = []
    first = simulator.run(hours_as_years(1), on_hour=failed_records.append)
    assert failed_records[0].command_packets_attempted_this_hour == 1
    assert failed_records[0].command_packets_uploaded_this_hour == 0
    assert failed_records[0].command_packets_failed_this_hour == 1
    assert simulator.contingency_plan is None
    assert first.contingency_plan_upload_count == 0

    simulator.packet_drop_fraction_proxy = 0.0
    retry_records = []
    second = simulator.run(
        hours_as_years(1),
        state=first.state,
        start_hour=1,
        on_hour=retry_records.append,
    )
    assert retry_records[0].command_packets_uploaded_this_hour == 1
    assert simulator.contingency_plan is not None
    assert second.contingency_plan_upload_count == 1


def test_accounting_reconciles_and_kb_counts_successes_only() -> None:
    records = []
    result = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={0, 2, 4, 6}),
        operator_view="delayed_telemetry",
        autonomy_model="contingency_plan",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_delivery_seed=19,
        packet_drop_fraction_proxy=0.5,
    ).run(hours_as_years(8), on_hour=records.append)
    assert result.telemetry_delivery_attempts == (
        result.telemetry_packets_downlinked + result.telemetry_delivery_failures
    )
    assert result.command_packet_attempts == (
        result.command_packets_uploaded + result.command_packet_failures
    )
    assert result.daily_plan_packet_attempts == (
        result.daily_plan_packets_uploaded + result.daily_plan_packet_failures
    )
    assert result.packet_delivery_failure_events == (
        result.telemetry_delivery_failures
        + result.command_packet_failures
        + result.daily_plan_packet_failures
    )
    assert result.packet_uplink_kb_total == pytest.approx(
        result.command_packets_uploaded * DEFAULT_CONFIG.command_packet_kb
        + result.daily_plan_packets_uploaded
        * DEFAULT_CONFIG.daily_plan_packet_kb
    )
    assert result.packet_downlink_kb_total == pytest.approx(
        result.telemetry_packets_downlinked
        * DEFAULT_CONFIG.housekeeping_telemetry_packet_kb
    )
    assert result.packet_uplink_kb_total == pytest.approx(
        sum(record.packet_uplink_kb_this_hour for record in records)
    )
    assert result.packet_downlink_kb_total == pytest.approx(
        sum(record.packet_downlink_kb_this_hour for record in records)
    )


def test_absolute_hour_command_delivery_is_warmed_continuation_stable() -> None:
    def make_simulator() -> Simulator:
        catalog = EventCatalog(
            [
                ExternalEvent(
                    hour=12,
                    event_type="debris_conjunction",
                    severity=0.8,
                    duration_hours=1,
                    target="adcs_health,thermal_health",
                    effect=0.02,
                    description="V3.8B smoke",
                )
            ],
            380,
            "stochastic_post_life_events",
            13,
        )
        return Simulator(
            make_policy("adaptive"),
            StochasticPostLifeEventsScenario(event_catalog=catalog),
            contact_model=ContactSchedule(command_hours={4, 8}),
            operator_view="delayed_telemetry",
            maneuver_model="stationkeeping_proxy",
            event_lifecycle_model="warning_proxy",
            autonomy_model="contingency_plan",
            packet_model="packet_proxy",
            packet_delivery_model="loss_retry_proxy",
            packet_delivery_seed=23,
            packet_drop_fraction_proxy=0.5,
        )

    full_simulator = make_simulator()
    full_records = []
    full_result = full_simulator.run(
        hours_as_years(13), on_hour=full_records.append
    )

    split_simulator = make_simulator()
    split_records = []
    first = split_simulator.run(
        hours_as_years(6), on_hour=split_records.append
    )
    pending_event = split_simulator.lifecycle_manager.events[0]
    assert pending_event.status == LifecycleStatus.UPLINK_PENDING.value
    assert pending_event.response_uploaded is False
    split_result = split_simulator.run(
        hours_as_years(7),
        state=first.state,
        start_hour=6,
        on_hour=split_records.append,
    )
    fields_to_compare = (
        "command_packets_attempted_this_hour",
        "command_packets_uploaded_this_hour",
        "command_packets_failed_this_hour",
    )
    full_command_rows = [
        tuple(getattr(record, field) for field in fields_to_compare)
        for record in full_records
    ]
    split_command_rows = [
        tuple(getattr(record, field) for field in fields_to_compare)
        for record in split_records
    ]
    assert full_command_rows == split_command_rows
    assert sum(row[0] for row in full_command_rows) > 0
    assert sum(row[1] for row in full_command_rows) > 0
    assert sum(row[2] for row in full_command_rows) > 0

    full_event = full_simulator.lifecycle_manager.events[0]
    split_event = split_simulator.lifecycle_manager.events[0]
    assert split_event.as_dict() == full_event.as_dict()
    assert split_event.status == LifecycleStatus.RESOLVED_SUCCESS.value
    assert split_simulator.lifecycle_manager.ground_external_awareness == (
        full_simulator.lifecycle_manager.ground_external_awareness
    )
    assert split_simulator.lifecycle_manager.spacecraft_awareness == (
        full_simulator.lifecycle_manager.spacecraft_awareness
    )
    assert split_simulator.contingency_plan == full_simulator.contingency_plan
    assert split_result.contingency_plan_upload_count == (
        full_result.contingency_plan_upload_count
    )
    assert split_result.contingency_plan_expired_count == (
        full_result.contingency_plan_expired_count
    )


def test_forced_loss_has_no_direct_payload_or_health_mutation() -> None:
    def execute(drop_fraction: float) -> SimulationResult:
        return Simulator(
            make_policy("adaptive"),
            contact_model=ContactSchedule(always_command=True),
            operator_view="omniscient",
            packet_model="packet_proxy",
            packet_delivery_model="loss_retry_proxy",
            packet_drop_fraction_proxy=drop_fraction,
        ).run(hours_as_years(12))

    delivered = execute(0.0)
    lost = execute(1.0)
    assert lost.state.soc == pytest.approx(delivered.state.soc)
    assert lost.state.total_health() == pytest.approx(
        delivered.state.total_health()
    )
    assert lost.state.total_data_generated_gb == pytest.approx(
        delivered.state.total_data_generated_gb
    )
    assert lost.state.total_data_downlinked_gb == pytest.approx(
        delivered.state.total_data_downlinked_gb
    )


def test_delivery_field_contracts_are_exposed_everywhere() -> None:
    assert DELIVERY_HOUR_FIELDS <= {field.name for field in fields(HourRecord)}
    assert DELIVERY_HOUR_FIELDS <= set(run.STATE_FIELDS)
    assert DELIVERY_HOUR_FIELDS <= set(decision_report.PACKET_TRACE_FIELDS)
    assert DELIVERY_SUMMARY_FIELDS <= {field.name for field in fields(SimulationResult)}
    assert DELIVERY_SUMMARY_FIELDS <= set(run.SUMMARY_FIELDS)
    assert DELIVERY_SUMMARY_FIELDS <= set(run.MONTE_CARLO_FIELDS)
    result = Simulator(
        make_policy("adaptive"), packet_model="packet_proxy"
    ).run(hours_as_years(1))
    assert DELIVERY_SUMMARY_FIELDS <= result.as_dict().keys()
    assert DELIVERY_SUMMARY_FIELDS <= run._summary_row(
        result, hours_as_years(1)
    ).keys()


def test_v38b_documentation_states_delivery_boundaries() -> None:
    root = Path(__file__).resolve().parents[1]
    documents = " ".join(
        " ".join((root / name).read_text(encoding="utf-8").lower().split())
        for name in (
            "README.md",
            "PROJECT_CANON.md",
            "FINAL_CONFIG.md",
            "KAZEOSAT_PUBLIC_SPEC.md",
        )
    )
    for phrase in (
        "packet_delivery_model = loss_retry_proxy",
        "packet_delivery_model = ideal",
        "synthetic stress-test fraction",
        "not a real loss probability",
        "retry at a later eligible physical contact",
        "no general packet queue",
        "qpsk remains metadata only",
        "270 mbit/s rate remains a payload reference only",
        "not a real packet network",
        "ber/fer",
        "rf propagation",
        "not propagation delay",
    ):
        assert phrase in documents
