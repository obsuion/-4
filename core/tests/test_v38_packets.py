"""Focused V3.8A passive command/telemetry packet accounting tests."""

import csv
from copy import deepcopy
from dataclasses import asdict, fields
from pathlib import Path

import pytest

import decision_report
import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.models import ContactInfo, SatelliteState
from ops_sim.packets import PACKET_MODELS, assess_packets_for_hour
from ops_sim.policies import make_policy
from ops_sim.scenarios import Scenario, StochasticPostLifeEventsScenario
from ops_sim.simulator import HourRecord, Simulator


PACKET_HOUR_FIELDS = {
    "packet_model",
    "packet_delivery_model",
    "telemetry_packet_generated_this_hour",
    "telemetry_packet_delivery_attempted_this_hour",
    "telemetry_packet_downlinked_this_hour",
    "telemetry_packet_delivery_failed_this_hour",
    "command_packets_attempted_this_hour",
    "command_packets_uploaded_this_hour",
    "command_packets_failed_this_hour",
    "daily_plan_packet_delivery_attempted_this_hour",
    "daily_plan_packet_uploaded_this_hour",
    "daily_plan_packet_delivery_failed_this_hour",
    "packet_uplink_kb_this_hour",
    "packet_downlink_kb_this_hour",
    "packet_reason_this_hour",
    "packet_delivery_reason_this_hour",
}
PACKET_SUMMARY_FIELDS = {
    "packet_model",
    "packet_delivery_model",
    "packet_delivery_seed",
    "packet_drop_fraction_proxy",
    "telemetry_packets_generated",
    "telemetry_delivery_attempts",
    "telemetry_packets_downlinked",
    "telemetry_delivery_failures",
    "command_packet_attempts",
    "command_packets_uploaded",
    "command_packet_failures",
    "daily_plan_packet_attempts",
    "daily_plan_packets_uploaded",
    "daily_plan_packet_failures",
    "packet_delivery_failure_events",
    "max_telemetry_age_hours",
    "packet_uplink_kb_total",
    "packet_downlink_kb_total",
}


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


class ContactSchedule:
    def __init__(self, command_hours=(), data_hours=()) -> None:
        self.command_hours = set(command_hours)
        self.data_hours = set(data_hours)

    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(
            cmd_contact_min=8.0 if hour in self.command_hours else 0.0,
            data_contact_min=8.0 if hour in self.data_hours else 0.0,
        )


class AlwaysCommandContact:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(cmd_contact_min=8.0)


class BlockFinalContact(Scenario):
    name = "block_final_contact"

    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo()


def packet_free(mapping: dict) -> dict:
    return {
        key: value
        for key, value in mapping.items()
        if key not in PACKET_HOUR_FIELDS | PACKET_SUMMARY_FIELDS
    }


def assert_passive_equivalence(
    legacy_result,
    proxy_result,
    legacy_records=(),
    proxy_records=(),
) -> None:
    assert legacy_result.state == proxy_result.state
    assert legacy_result.metrics == proxy_result.metrics
    assert legacy_result.checkpoints == proxy_result.checkpoints
    assert legacy_result.events == proxy_result.events
    assert packet_free(legacy_result.as_dict()) == packet_free(
        proxy_result.as_dict()
    )
    assert len(legacy_records) == len(proxy_records)
    for legacy_record, proxy_record in zip(legacy_records, proxy_records):
        assert packet_free(asdict(legacy_record)) == packet_free(
            asdict(proxy_record)
        )


def test_packet_selectors_defaults_cli_and_validation() -> None:
    assert PACKET_MODELS == ("legacy", "packet_proxy")
    assert Simulator(make_policy("adaptive")).packet_model == "legacy"
    assert run.build_parser().parse_args([]).packet_model == "legacy"
    assert decision_report.build_parser().parse_args([]).packet_model == "legacy"
    for selector in PACKET_MODELS:
        assert run.build_parser().parse_args(
            ["--packet-model", selector]
        ).packet_model == selector
        assert decision_report.build_parser().parse_args(
            ["--packet-model", selector]
        ).packet_model == selector
    with pytest.raises(ValueError, match="packet_model"):
        Simulator(make_policy("adaptive"), packet_model="ccsds")
    with pytest.raises(SystemExit):
        run.build_parser().parse_args(["--packet-model", "ccsds"])
    with pytest.raises(SystemExit):
        decision_report.build_parser().parse_args(
            ["--packet-model", "ccsds"]
        )


def test_default_equals_explicit_legacy_behavior() -> None:
    initial = SatelliteState(soc=80.0, data_buffer_gb=100.0)
    omitted_records = []
    explicit_records = []
    omitted = Simulator(
        make_policy("adaptive"),
        target_model="scene_scheduling_proxy",
        pointing_model="bounded_pointing_proxy",
    ).run(
        hours_as_years(12),
        state=deepcopy(initial),
        on_hour=omitted_records.append,
    )
    explicit = Simulator(
        make_policy("adaptive"),
        target_model="scene_scheduling_proxy",
        pointing_model="bounded_pointing_proxy",
        packet_model="legacy",
    ).run(
        hours_as_years(12),
        state=deepcopy(initial),
        on_hour=explicit_records.append,
    )

    assert omitted.as_dict() == explicit.as_dict()
    assert omitted_records == explicit_records
    assert explicit.telemetry_packets_generated == 0
    assert all(
        record.telemetry_packet_generated_this_hour is None
        for record in explicit_records
    )


def test_housekeeping_generation_and_existing_refresh_are_authoritative() -> None:
    records = []
    result = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={1}),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
    ).run(hours_as_years(3), on_hour=records.append)

    assert [record.telemetry_packet_generated_this_hour for record in records] == [
        True,
        True,
        True,
    ]
    assert [record.telemetry_packet_downlinked_this_hour for record in records] == [
        record.telemetry_updated_this_hour for record in records
    ]
    assert [record.telemetry_updated_this_hour for record in records] == [
        False,
        True,
        False,
    ]
    assert result.telemetry_packets_generated == 3
    assert result.telemetry_packets_downlinked == 1
    assert result.packet_downlink_kb_total == pytest.approx(
        DEFAULT_CONFIG.housekeeping_telemetry_packet_kb
    )


def test_final_scenario_modified_contact_controls_packet_downlink_and_plan() -> None:
    records = []
    Simulator(
        make_policy("adaptive"),
        BlockFinalContact(),
        contact_model=ContactSchedule(command_hours={0}),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
    ).run(hours_as_years(1), on_hour=records.append)

    record = records[0]
    assert record.base_cmd_contact_min > 0.0
    assert record.cmd_contact_min == 0.0
    assert record.telemetry_updated_this_hour is False
    assert record.telemetry_packet_generated_this_hour is True
    assert record.telemetry_packet_downlinked_this_hour is False
    assert record.plan_uploaded_this_hour is False
    assert record.daily_plan_packet_uploaded_this_hour is False


def test_packet_accounting_does_not_change_operator_context() -> None:
    kwargs = {
        "contact_model": ContactSchedule(command_hours={0, 4}),
        "operator_view": "delayed_telemetry",
    }
    legacy_simulator = Simulator(make_policy("adaptive"), **kwargs)
    proxy_simulator = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={0, 4}),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
    )
    legacy = legacy_simulator.run(hours_as_years(6))
    proxy = proxy_simulator.run(hours_as_years(6))

    assert_passive_equivalence(legacy, proxy)
    assert legacy_simulator.observed_state == proxy_simulator.observed_state
    assert legacy_simulator.last_telemetry_hour == proxy_simulator.last_telemetry_hour
    assert legacy_simulator.telemetry_age_hours == proxy_simulator.telemetry_age_hours


def test_standalone_continuation_initialization_is_not_a_packet_downlink() -> None:
    records = []
    state = SatelliteState(hours_completed=5, soc=70.0)
    result = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
    ).run(
        hours_as_years(1),
        state=state,
        start_hour=5,
        on_hour=records.append,
    )

    assert records[0].last_telemetry_hour == 5
    assert records[0].telemetry_updated_this_hour is False
    assert records[0].telemetry_packet_downlinked_this_hour is False
    assert result.telemetry_packets_generated == 1
    assert result.telemetry_packets_downlinked == 0


def test_warmed_continuation_preserves_existing_telemetry_context() -> None:
    simulator = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={0}),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
    )
    first = simulator.run(hours_as_years(1))
    records = []
    second = simulator.run(
        hours_as_years(1),
        state=first.state,
        start_hour=1,
        on_hour=records.append,
    )

    assert records[0].last_telemetry_hour == 0
    assert records[0].telemetry_age_hours == 1
    assert records[0].telemetry_updated_this_hour is False
    assert records[0].telemetry_packet_downlinked_this_hour is False
    assert second.telemetry_packets_generated == 1
    assert second.telemetry_packets_downlinked == 0


def test_daily_plan_packet_exactly_mirrors_existing_upload_flag() -> None:
    records = []
    result = Simulator(
        make_policy("adaptive"),
        contact_model=AlwaysCommandContact(),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
    ).run(hours_as_years(2), on_hour=records.append)

    assert [record.plan_uploaded_this_hour for record in records] == [True, False]
    assert [
        record.daily_plan_packet_uploaded_this_hour for record in records
    ] == [True, False]
    assert [record.command_packets_uploaded_this_hour for record in records] == [
        0,
        0,
    ]
    assert result.daily_plan_packets_uploaded == 1
    assert result.command_packets_uploaded == 0
    assert result.packet_uplink_kb_total == pytest.approx(
        DEFAULT_CONFIG.daily_plan_packet_kb
    )


def test_contingency_upload_is_one_command_and_daily_plan_is_not_double_counted() -> None:
    records = []
    result = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={0}),
        operator_view="delayed_telemetry",
        autonomy_model="contingency_plan",
        packet_model="packet_proxy",
    ).run(hours_as_years(1), on_hour=records.append)

    record = records[0]
    assert record.plan_uploaded_this_hour is True
    assert record.daily_plan_packet_uploaded_this_hour is True
    assert record.command_packets_uploaded_this_hour == 1
    assert result.contingency_plan_upload_count == 1
    assert result.daily_plan_packets_uploaded == 1
    assert result.command_packets_uploaded == 1
    assert result.packet_uplink_kb_total == pytest.approx(
        DEFAULT_CONFIG.daily_plan_packet_kb
        + DEFAULT_CONFIG.command_packet_kb
    )


def test_lifecycle_response_upload_multiplicity_is_preserved() -> None:
    events = [
        ExternalEvent(
            hour=100,
            event_type="debris_conjunction",
            severity=0.8,
            duration_hours=1,
            target="adcs_health",
            effect=0.02,
            description=f"packet accounting event {index}",
        )
        for index in range(2)
    ]
    catalog = EventCatalog(
        events, 38, "stochastic_post_life_events", 101
    )
    records = []
    result = Simulator(
        make_policy("adaptive"),
        StochasticPostLifeEventsScenario(event_catalog=catalog),
        contact_model=ContactSchedule(command_hours={96}),
        operator_view="delayed_telemetry",
        event_lifecycle_model="warning_proxy",
        packet_model="packet_proxy",
    ).run(hours_as_years(97), on_hour=records.append)

    upload = records[96]
    assert upload.lifecycle_uploaded_count == 2
    assert upload.command_packets_uploaded_this_hour == 2
    assert upload.daily_plan_packet_uploaded_this_hour is True
    assert upload.packet_uplink_kb_this_hour == pytest.approx(
        2 * DEFAULT_CONFIG.command_packet_kb
        + DEFAULT_CONFIG.daily_plan_packet_kb
    )
    assert result.command_packets_uploaded == 2


def test_packet_totals_equal_exact_hourly_sums() -> None:
    records = []
    result = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(command_hours={0, 4, 8}),
        operator_view="delayed_telemetry",
        autonomy_model="contingency_plan",
        packet_model="packet_proxy",
    ).run(hours_as_years(10), on_hour=records.append)

    assert result.telemetry_packets_generated == sum(
        bool(record.telemetry_packet_generated_this_hour)
        for record in records
    )
    assert result.telemetry_packets_downlinked == sum(
        bool(record.telemetry_packet_downlinked_this_hour)
        for record in records
    )
    assert result.command_packets_uploaded == sum(
        record.command_packets_uploaded_this_hour for record in records
    )
    assert result.daily_plan_packets_uploaded == sum(
        bool(record.daily_plan_packet_uploaded_this_hour)
        for record in records
    )
    assert result.packet_uplink_kb_total == pytest.approx(
        sum(record.packet_uplink_kb_this_hour for record in records)
    )
    assert result.packet_downlink_kb_total == pytest.approx(
        sum(record.packet_downlink_kb_this_hour for record in records)
    )


def test_integrated_packet_proxy_is_operationally_passive() -> None:
    event = ExternalEvent(
        hour=96,
        event_type="debris_conjunction",
        severity=0.85,
        duration_hours=1,
        target="solar_health,adcs_health",
        effect=0.03,
        description="V3.8A passive integration event",
    )
    catalog = EventCatalog(
        [event], 38, "stochastic_post_life_events", 101
    )

    def run_model(packet_model: str):
        records = []
        result = Simulator(
            make_policy("adaptive"),
            StochasticPostLifeEventsScenario(event_catalog=catalog),
            operator_view="delayed_telemetry",
            planning_model="risk_aware",
            maneuver_model="stationkeeping_proxy",
            orbit_evolution_model="drift_proxy",
            stationkeeping_planning_model="drift_aware",
            power_model="eclipse_proxy",
            thermal_model="load_stress_proxy",
            target_model="scene_scheduling_proxy",
            pointing_model="bounded_pointing_proxy",
            event_lifecycle_model="warning_proxy",
            debris_risk_model="severity_proxy",
            autonomy_model="contingency_plan",
            packet_model=packet_model,
        ).run(hours_as_years(101), on_hour=records.append)
        return result, records

    legacy, legacy_records = run_model("legacy")
    proxy, proxy_records = run_model("packet_proxy")

    assert_passive_equivalence(
        legacy, proxy, legacy_records, proxy_records
    )
    assert proxy.telemetry_packets_generated == proxy.state.hours_completed
    assert proxy.packet_uplink_kb_total >= 0.0
    assert proxy.packet_downlink_kb_total >= 0.0


def test_no_contact_fallback_ladder_is_unchanged() -> None:
    legacy_records = []
    proxy_records = []
    legacy = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(),
        operator_view="delayed_telemetry",
        packet_model="legacy",
    ).run(hours_as_years(337), on_hour=legacy_records.append)
    proxy = Simulator(
        make_policy("adaptive"),
        contact_model=ContactSchedule(),
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
    ).run(hours_as_years(337), on_hour=proxy_records.append)

    assert_passive_equivalence(
        legacy, proxy, legacy_records, proxy_records
    )
    assert [record.mode for record in legacy_records] == [
        record.mode for record in proxy_records
    ]
    assert legacy_records[335].mode == "EMERGENCY_BEACON"


def test_packet_field_contracts_runner_and_decision_report(tmp_path) -> None:
    result = Simulator(
        make_policy("adaptive"), packet_model="packet_proxy"
    ).run(hours_as_years(1))
    assert PACKET_HOUR_FIELDS <= {field.name for field in fields(HourRecord)}
    assert PACKET_HOUR_FIELDS <= set(run.STATE_FIELDS)
    assert PACKET_HOUR_FIELDS <= set(decision_report.PACKET_TRACE_FIELDS)
    assert PACKET_SUMMARY_FIELDS <= set(run.SUMMARY_FIELDS)
    assert PACKET_SUMMARY_FIELDS <= set(run.MONTE_CARLO_FIELDS)
    assert PACKET_SUMMARY_FIELDS <= result.as_dict().keys()
    assert PACKET_SUMMARY_FIELDS <= run._summary_row(
        result, hours_as_years(1)
    ).keys()

    run_dir = tmp_path / "run"
    assert run.main([
        "--years", str(hours_as_years(1)),
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--packet-model", "packet_proxy",
        "--results-dir", str(run_dir),
    ]) == 0
    with (run_dir / "state_log.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        state_row = next(csv.DictReader(handle))
    with (run_dir / "summary.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        summary_row = next(csv.DictReader(handle))
    assert state_row["packet_model"] == "packet_proxy"
    assert summary_row["packet_model"] == "packet_proxy"

    report_dir = tmp_path / "decision"
    decision_report.run_decision_report(
        years=hours_as_years(1),
        policy="adaptive",
        scenario="nominal",
        seed=42,
        contact_model="synthetic",
        operator_view="omniscient",
        planning_model="reactive",
        maneuver_model="none",
        orbit_evolution_model="fixed",
        packet_model="packet_proxy",
        results_dir=report_dir,
    )
    with (report_dir / "decision_trace.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        trace_row = next(csv.DictReader(handle))
    assert trace_row["packet_model"] == "packet_proxy"
    assert "## Command/telemetry packet accounting" in (
        report_dir / "decision_summary.md"
    ).read_text(encoding="utf-8")


def test_packet_constants_and_pure_accounting_definition() -> None:
    assessment = assess_packets_for_hour(
        packet_model="packet_proxy",
        telemetry_updated_this_hour=True,
        plan_uploaded_this_hour=True,
        lifecycle_response_upload_count=2,
        contingency_plan_uploaded_this_hour=True,
    )

    assert DEFAULT_CONFIG.housekeeping_telemetry_packet_kb == 4.0
    assert DEFAULT_CONFIG.command_packet_kb == 1.0
    assert DEFAULT_CONFIG.daily_plan_packet_kb == 8.0
    assert assessment.command_packets_uploaded_this_hour == 3
    assert assessment.packet_uplink_kb_this_hour == pytest.approx(11.0)
    assert assessment.packet_downlink_kb_this_hour == pytest.approx(4.0)


def test_documentation_keeps_packet_proxy_boundaries_explicit() -> None:
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
        "passive accounting",
        "not ccsds",
        "real packet protocol",
        "real s-band/x-band command link",
        "modulation",
        "link budget",
        "ground-network",
        "flight software",
        "qpsk remains metadata only",
        "not calibrated from the public 270 mbit/s",
    ):
        assert phrase in documents
    assert "packet_model = packet_proxy" in documents
    assert "packet_model = legacy" in documents
