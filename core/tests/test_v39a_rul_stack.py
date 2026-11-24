"""Focused V3.9A current-stack RUL integration tests."""

from copy import deepcopy
import csv
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import rul
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.event_lifecycle import EventLifecycleManager, LifecycleStatus
from ops_sim.models import ContactInfo, SatelliteState
from ops_sim.packets import assess_packet_delivery
from ops_sim.policies import make_policy
from ops_sim.rul import (
    RULSample,
    RULSummary,
    SurvivalCurvePoint,
    estimate_remaining_useful_life,
    summarize_rul_samples,
)
from ops_sim.scenarios import StochasticPostLifeEventsScenario
from ops_sim.simulator import Simulator


TINY_CONFIG = replace(
    DEFAULT_CONFIG,
    hours_per_year=8,
    checkpoint_hours=4,
    plan_duration_hours=8,
    emergency_after_hours=40,
    post_life_stress_start_year=0.0,
)

CURRENT_PROVENANCE_FIELDS = {
    "stationkeeping_planning_model",
    "event_lifecycle_model",
    "debris_risk_model",
    "autonomy_model",
    "power_model",
    "thermal_model",
    "target_model",
    "pointing_model",
    "packet_model",
    "packet_delivery_model",
    "packet_drop_fraction_proxy",
}

CONTINUATION_DIAGNOSTIC_FIELDS = {
    "contingency_plan_uploads_during_rul",
    "autonomous_actions_during_rul",
    "lifecycle_uploads_during_rul",
    "lifecycle_resolved_success_during_rul",
    "lifecycle_resolved_failed_during_rul",
    "telemetry_delivery_failures_during_rul",
    "command_packet_failures_during_rul",
    "daily_plan_packet_failures_during_rul",
    "thermal_stress_hours_during_rul",
    "target_area_imaged_during_rul_km2",
}

CURRENT_STACK = {
    "contact_model_name": "geometry",
    "operator_view": "delayed_telemetry",
    "planning_model": "risk_aware",
    "maneuver_model": "stationkeeping_proxy",
    "stationkeeping_planning_model": "drift_aware",
    "orbit_evolution_model": "drift_proxy",
    "event_lifecycle_model": "warning_proxy",
    "debris_risk_model": "severity_proxy",
    "autonomy_model": "contingency_plan",
    "power_model": "eclipse_proxy",
    "thermal_model": "load_stress_proxy",
    "target_model": "scene_scheduling_proxy",
    "pointing_model": "bounded_pointing_proxy",
    "packet_model": "packet_proxy",
    "packet_delivery_model": "loss_retry_proxy",
    "packet_drop_fraction_proxy": 0.25,
}


class ScheduledContacts:
    def __init__(self, command_hours: set[int]) -> None:
        self.command_hours = command_hours

    def contact_at_hour(self, hour: int) -> ContactInfo:
        minutes = 8.0 if hour in self.command_hours else 0.0
        return ContactInfo(minutes, minutes)


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _rul_kwargs(**changes):
    values = {
        "policy_name": "adaptive",
        "scenario_name": "nominal",
        "start_year": 0.5,
        "horizon_years": 0.5,
        "samples": 1,
        "seed": 39,
        "config": TINY_CONFIG,
    }
    values.update(changes)
    return values


def test_omitted_current_selectors_equal_explicit_legacy_defaults() -> None:
    implicit = estimate_remaining_useful_life(**_rul_kwargs())
    explicit = estimate_remaining_useful_life(
        **_rul_kwargs(
            stationkeeping_planning_model="legacy",
            event_lifecycle_model="none",
            debris_risk_model="legacy",
            autonomy_model="none",
            power_model="legacy",
            thermal_model="legacy",
            target_model="legacy",
            pointing_model="legacy",
            packet_model="legacy",
            packet_delivery_model="ideal",
            packet_drop_fraction_proxy=(
                TINY_CONFIG.packet_drop_fraction_proxy
            ),
        )
    )
    assert implicit == explicit
    sample, summary, curve = implicit[0][0], implicit[1], implicit[2]
    assert sample.additional_hours_survived == 4
    assert summary.expected_rul_years_censored == pytest.approx(0.5)
    assert curve[-1].survival_probability == pytest.approx(1.0)

    args = rul.build_parser().parse_args([])
    assert args.contact_model == "synthetic"
    assert args.operator_view == "omniscient"
    assert args.planning_model == "reactive"
    assert args.maneuver_model == "none"
    assert args.orbit_evolution_model == "fixed"
    assert args.stationkeeping_planning_model == "legacy"
    assert args.event_lifecycle_model == "none"
    assert args.debris_risk_model == "legacy"
    assert args.autonomy_model == "none"
    assert args.power_model == "legacy"
    assert args.thermal_model == "legacy"
    assert args.target_model == "legacy"
    assert args.pointing_model == "legacy"
    assert args.packet_model == "legacy"
    assert args.packet_delivery_model == "ideal"
    assert args.packet_drop_fraction_proxy == pytest.approx(
        DEFAULT_CONFIG.packet_drop_fraction_proxy
    )


def test_current_stack_provenance_and_cli_csv_contract(tmp_path) -> None:
    samples, summary, curve = estimate_remaining_useful_life(
        **_rul_kwargs(**CURRENT_STACK)
    )
    sample = samples[0]
    assert CURRENT_PROVENANCE_FIELDS <= {field.name for field in fields(RULSample)}
    assert CURRENT_PROVENANCE_FIELDS <= {field.name for field in fields(RULSummary)}
    assert CURRENT_PROVENANCE_FIELDS <= {
        field.name for field in fields(SurvivalCurvePoint)
    }
    assert CONTINUATION_DIAGNOSTIC_FIELDS <= sample.as_dict().keys()
    for name in CURRENT_PROVENANCE_FIELDS:
        assert name in sample.as_dict()
        assert getattr(summary, name) == getattr(sample, name)
        assert all(getattr(point, name) == getattr(sample, name) for point in curve)

    with pytest.raises(ValueError, match="one run configuration"):
        summarize_rul_samples([
            sample,
            replace(sample, power_model="legacy"),
        ])

    assert rul.main([
        "--start-year", "0",
        "--horizon-years", "0.001",
        "--samples", "1",
        "--contact-model", "geometry",
        "--operator-view", "delayed_telemetry",
        "--planning-model", "risk_aware",
        "--maneuver-model", "stationkeeping_proxy",
        "--stationkeeping-planning-model", "drift_aware",
        "--orbit-evolution-model", "drift_proxy",
        "--event-lifecycle-model", "warning_proxy",
        "--debris-risk-model", "severity_proxy",
        "--autonomy-model", "contingency_plan",
        "--power-model", "eclipse_proxy",
        "--thermal-model", "load_stress_proxy",
        "--target-model", "scene_scheduling_proxy",
        "--pointing-model", "bounded_pointing_proxy",
        "--packet-model", "packet_proxy",
        "--packet-delivery-model", "loss_retry_proxy",
        "--packet-drop-fraction-proxy", "0.25",
        "--results-dir", str(tmp_path),
    ]) == 0
    sample_row = _read_csv(tmp_path / "rul_samples.csv")[0]
    summary_row = _read_csv(tmp_path / "rul_summary.csv")[0]
    curve_row = _read_csv(tmp_path / "rul_survival_curve.csv")[0]
    assert CURRENT_PROVENANCE_FIELDS <= sample_row.keys()
    assert CURRENT_PROVENANCE_FIELDS <= summary_row.keys()
    assert CURRENT_PROVENANCE_FIELDS <= curve_row.keys()
    assert CONTINUATION_DIAGNOSTIC_FIELDS <= sample_row.keys()
    assert sample_row["packet_model"] == "packet_proxy"
    assert sample_row["packet_delivery_model"] == "loss_retry_proxy"


def test_short_estimator_constructs_complete_current_stack() -> None:
    samples, summary, curve = estimate_remaining_useful_life(
        **_rul_kwargs(**CURRENT_STACK)
    )
    sample = samples[0]
    assert sample.survived_to_horizon is True
    assert sample.additional_hours_survived == 4
    assert sample.contact_model == "geometry"
    assert sample.stationkeeping_planning_model == "drift_aware"
    assert sample.event_lifecycle_model == "warning_proxy"
    assert sample.debris_risk_model == "severity_proxy"
    assert sample.autonomy_model == "contingency_plan"
    assert sample.power_model == "eclipse_proxy"
    assert sample.thermal_model == "load_stress_proxy"
    assert sample.target_model == "scene_scheduling_proxy"
    assert sample.pointing_model == "bounded_pointing_proxy"
    assert sample.packet_model == "packet_proxy"
    assert sample.packet_delivery_model == "loss_retry_proxy"
    assert summary.samples == 1
    assert curve


def _catalog_with_warning_hour(target_warning_hour: int) -> EventCatalog:
    resolved_before_boundary = ExternalEvent(
        hour=3,
        event_type="debris_conjunction",
        severity=0.7,
        duration_hours=1,
        target="adcs_health,thermal_health",
        effect=0.01,
        description="V3.9A resolved warm-up event",
    )
    for index in range(1000):
        event = ExternalEvent(
            hour=9,
            event_type="debris_conjunction",
            severity=0.8,
            duration_hours=1,
            target="adcs_health,thermal_health",
            effect=0.02,
            description=f"V3.9A boundary event {index}",
        )
        catalog = EventCatalog(
            [resolved_before_boundary, event],
            0,
            "stochastic_post_life_events",
            10,
        )
        manager = EventLifecycleManager(
            catalog, hours_per_year=TINY_CONFIG.hours_per_year
        )
        if manager.events[1].warning_hour == target_warning_hour:
            return catalog
    raise AssertionError("could not construct requested warning hour")


def _boundary_packet_seed() -> int:
    def delivered(seed, hour, kind, direction="uplink"):
        return assess_packet_delivery(
            packet_delivery_model="loss_retry_proxy",
            attempted=True,
            packet_delivery_seed=seed,
            hour=hour,
            packet_kind=kind,
            direction=direction,
            packet_drop_fraction_proxy=0.5,
        ).delivered

    for seed in range(1000):
        if (
            delivered(seed, 0, "housekeeping_telemetry", "downlink")
            and delivered(seed, 0, "contingency_plan")
            and delivered(seed, 0, "lifecycle_response_channel")
            and delivered(seed, 5, "lifecycle_response_channel")
            and not delivered(seed, 5, "housekeeping_telemetry", "downlink")
        ):
            return seed
    raise AssertionError("could not find bounded packet seed")


def test_warmed_estimator_preserves_current_stack_context() -> None:
    catalog = _catalog_with_warning_hour(2)
    sample_seed = _boundary_packet_seed()
    built = []

    class ContextRecordingSimulator(Simulator):
        def run(self, years, state=None, **kwargs):
            records = []
            external_on_hour = kwargs.pop("on_hour", None)

            def record_hour(record):
                records.append(record)
                if external_on_hour is not None:
                    external_on_hour(record)

            result = super().run(
                years, state=state, on_hour=record_hour, **kwargs
            )
            if state is None:
                resolved_event, pending_event = self.lifecycle_manager.events
                self.boundary_resolved_event_status = resolved_event.status
                self.boundary_event_status = pending_event.status
                self.boundary_ground_known = (
                    pending_event.event_id
                    in self.lifecycle_manager.ground_external_awareness
                )
                self.boundary_spacecraft_known = (
                    pending_event.event_id
                    in self.lifecycle_manager.spacecraft_awareness
                )
                self.boundary_contingency_plan = deepcopy(
                    self.contingency_plan
                )
                self.boundary_observed_state = deepcopy(self.observed_state)
                self.boundary_last_telemetry_hour = self.last_telemetry_hour
                self.boundary_telemetry_age_hours = self.telemetry_age_hours
                self.warmup_result = result
            else:
                self.continuation_records = records
                self.continuation_result = result
            return result

    def catalog_factory(seed, scenario_name, total_hours, config):
        return EventCatalog(
            list(catalog.events), seed, scenario_name, total_hours
        )

    def simulator_factory(_seed, event_catalog):
        simulator = ContextRecordingSimulator(
            make_policy("adaptive", TINY_CONFIG),
            StochasticPostLifeEventsScenario(
                config=TINY_CONFIG, event_catalog=event_catalog
            ),
            TINY_CONFIG,
            contact_model=ScheduledContacts({0, 5}),
            operator_view="delayed_telemetry",
            planning_model="risk_aware",
            maneuver_model="stationkeeping_proxy",
            orbit_evolution_model="drift_proxy",
            stationkeeping_planning_model="drift_aware",
            event_lifecycle_model="warning_proxy",
            debris_risk_model="severity_proxy",
            autonomy_model="contingency_plan",
            packet_model="packet_proxy",
            packet_delivery_model="loss_retry_proxy",
            packet_delivery_seed=-1,
            packet_drop_fraction_proxy=0.5,
        )
        built.append(simulator)
        return simulator

    samples, _, _ = estimate_remaining_useful_life(
        policy_name="adaptive",
        scenario_name="stochastic_post_life_events",
        start_year=0.5,
        horizon_years=0.75,
        samples=1,
        seed=sample_seed,
        config=TINY_CONFIG,
        contact_model_name="synthetic",
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        stationkeeping_planning_model="drift_aware",
        event_lifecycle_model="warning_proxy",
        debris_risk_model="severity_proxy",
        autonomy_model="contingency_plan",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=0.5,
        event_catalog_factory=catalog_factory,
        simulator_factory=simulator_factory,
    )
    simulator = built[0]
    sample = samples[0]
    assert len(built) == 1
    assert simulator.packet_delivery_seed == sample_seed
    assert (
        simulator.boundary_resolved_event_status
        == LifecycleStatus.RESOLVED_SUCCESS.value
    )
    assert simulator.boundary_event_status == LifecycleStatus.UPLINK_PENDING.value
    assert simulator.boundary_ground_known is True
    assert simulator.boundary_spacecraft_known is False
    assert simulator.boundary_contingency_plan is not None
    assert simulator.boundary_last_telemetry_hour == 0
    assert simulator.boundary_telemetry_age_hours == 3
    assert simulator.boundary_observed_state != simulator.warmup_result.state
    assert simulator.continuation_records[0].hour == 4
    assert simulator.continuation_records[0].telemetry_age_hours == 4
    hour_five = simulator.continuation_records[1]
    assert hour_five.hour == 5
    assert hour_five.telemetry_packet_delivery_failed_this_hour is True
    resolved_event, event = simulator.lifecycle_manager.events
    assert resolved_event.status == LifecycleStatus.RESOLVED_SUCCESS.value
    assert event.response_upload_hour == 5
    assert event.status == LifecycleStatus.RESOLVED_SUCCESS.value
    assert sample.contingency_plan_uploads_during_rul == 0
    assert sample.lifecycle_uploads_during_rul == 1
    assert sample.lifecycle_resolved_success_during_rul == 1
    assert sample.telemetry_delivery_failures_during_rul == 1

    full_records = []
    full = simulator_factory(sample_seed, catalog_factory(
        sample_seed, "stochastic_post_life_events", 10, TINY_CONFIG
    ))
    full.packet_delivery_seed = sample_seed
    full.run(10 / TINY_CONFIG.hours_per_year, on_hour=full_records.append)
    packet_fields = (
        "telemetry_packet_delivery_attempted_this_hour",
        "telemetry_packet_downlinked_this_hour",
        "telemetry_packet_delivery_failed_this_hour",
        "command_packets_attempted_this_hour",
        "command_packets_uploaded_this_hour",
        "command_packets_failed_this_hour",
    )
    assert [
        tuple(getattr(row, field) for field in packet_fields)
        for row in simulator.continuation_records
    ] == [
        tuple(getattr(row, field) for field in packet_fields)
        for row in full_records[4:]
    ]
    assert [item.as_dict() for item in full.lifecycle_manager.events] == [
        item.as_dict() for item in simulator.lifecycle_manager.events
    ]


def test_packet_sample_seed_is_reproducible_and_nontrivial() -> None:
    kwargs = _rul_kwargs(
        start_year=0.0,
        horizon_years=1.0,
        samples=4,
        seed=0,
        operator_view="delayed_telemetry",
        packet_model="packet_proxy",
        packet_delivery_model="loss_retry_proxy",
        packet_drop_fraction_proxy=0.5,
    )
    first = estimate_remaining_useful_life(**kwargs)[0]
    second = estimate_remaining_useful_life(**kwargs)[0]
    first_failures = [
        (
            sample.sample_seed,
            sample.telemetry_delivery_failures_during_rul,
            sample.daily_plan_packet_failures_during_rul,
        )
        for sample in first
    ]
    second_failures = [
        (
            sample.sample_seed,
            sample.telemetry_delivery_failures_during_rul,
            sample.daily_plan_packet_failures_during_rul,
        )
        for sample in second
    ]
    assert first_failures == second_failures
    assert len({row[1:] for row in first_failures}) > 1


def test_continuation_diagnostics_respect_counter_scope() -> None:
    class LifecycleManager:
        phase = "warmup"

        def diagnostics(self):
            values = (
                (2, 1, 1)
                if self.phase == "warmup"
                else (5, 3, 2)
            )
            return SimpleNamespace(
                lifecycle_uploaded_count=values[0],
                lifecycle_resolved_success_count=values[1],
                lifecycle_resolved_failed_count=values[2],
            )

    class ScopedCounterSimulator:
        def __init__(self):
            self.lifecycle_manager = LifecycleManager()
            self.packet_delivery_seed = -1

        def run(self, years, state=None, start_hour=0):
            duration = int(round(years * TINY_CONFIG.hours_per_year))
            if state is None:
                state = SatelliteState(hours_completed=duration)
                self.lifecycle_manager.phase = "warmup"
                return SimpleNamespace(
                    state=state,
                    contingency_plan_upload_count=2,
                    autonomous_action_count=3,
                    telemetry_delivery_failures=9,
                    command_packet_failures=8,
                    daily_plan_packet_failures=7,
                    thermal_stress_hours=6,
                    target_area_imaged_km2=100.0,
                )
            state.hours_completed += duration
            self.lifecycle_manager.phase = "continuation"
            return SimpleNamespace(
                state=state,
                contingency_plan_upload_count=5,
                autonomous_action_count=7,
                telemetry_delivery_failures=1,
                command_packet_failures=2,
                daily_plan_packet_failures=3,
                thermal_stress_hours=4,
                target_area_imaged_km2=5.0,
            )

    simulator = ScopedCounterSimulator()
    samples, _, _ = estimate_remaining_useful_life(
        **_rul_kwargs(
            seed=91,
            packet_model="packet_proxy",
            packet_delivery_model="loss_retry_proxy",
            packet_drop_fraction_proxy=0.5,
            simulator_factory=lambda _seed, _catalog: simulator,
        )
    )
    sample = samples[0]
    assert simulator.packet_delivery_seed == sample.sample_seed == 91
    assert sample.contingency_plan_uploads_during_rul == 3
    assert sample.autonomous_actions_during_rul == 4
    assert sample.lifecycle_uploads_during_rul == 3
    assert sample.lifecycle_resolved_success_during_rul == 2
    assert sample.lifecycle_resolved_failed_during_rul == 1
    assert sample.telemetry_delivery_failures_during_rul == 1
    assert sample.command_packet_failures_during_rul == 2
    assert sample.daily_plan_packet_failures_during_rul == 3
    assert sample.thermal_stress_hours_during_rul == 4
    assert sample.target_area_imaged_during_rul_km2 == pytest.approx(5.0)


def test_rul_rejects_legacy_nonideal_packet_combination() -> None:
    with pytest.raises(ValueError, match="requires packet_model"):
        estimate_remaining_useful_life(
            **_rul_kwargs(packet_delivery_model="loss_retry_proxy")
        )
    with pytest.raises(SystemExit, match="requires --packet-model"):
        rul.main(["--packet-delivery-model", "loss_retry_proxy"])


def test_v39a_documentation_preserves_rul_boundaries() -> None:
    documents = " ".join(
        " ".join(Path(name).read_text(encoding="utf-8").lower().split())
        for name in ("README.md", "PROJECT_CANON.md", "FINAL_CONFIG.md")
    )
    for phrase in (
        "current-stack integration of the existing simulation-based, horizon-censored rul workflow",
        "not a new physical lifetime model",
        "physics-of-failure",
        "v3.9b",
        "sample seed also drives packet delivery",
        "target and pointing",
        "not physical failure modes",
    ):
        assert phrase in documents
    for forbidden_claim in (
        "weibull inference is implemented",
        "kazEOSat-1 lifetime prediction is validated",
    ):
        assert forbidden_claim.lower() not in documents
