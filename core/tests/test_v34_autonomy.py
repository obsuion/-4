import csv
from copy import deepcopy
from pathlib import Path

import pytest

import decision_report
import debris_risk_report
import event_lifecycle_report
import lifecycle_seed_finder
import run
from ops_sim.autonomy import (
    AUTONOMY_MODELS,
    AutonomyAuthority,
    AutonomyTrigger,
)
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.debris_risk import assess_debris_risk
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.event_lifecycle import EventLifecycleManager
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import Policy
from ops_sim.scenarios import Scenario, StochasticPostLifeEventsScenario
from ops_sim.simulator import Simulator


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


class StandbyPolicy(Policy):
    name = "v34_standby"

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
        command_hours: set[int] = frozenset(),
        data_hours: set[int] = frozenset(),
    ) -> None:
        self.command_hours = command_hours
        self.data_hours = data_hours

    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(
            cmd_contact_min=8.0 if hour in self.command_hours else 0.0,
            data_contact_min=8.0 if hour in self.data_hours else 0.0,
        )


class BlockCommandScenario(Scenario):
    def modify_contacts(
        self, contact_info: ContactInfo, state: SatelliteState, hour: int
    ) -> ContactInfo:
        return ContactInfo(data_contact_min=contact_info.data_contact_min)


def debris_event(hour: int = 96) -> ExternalEvent:
    return ExternalEvent(
        hour=hour,
        event_type="debris_conjunction",
        severity=0.85,
        duration_hours=1,
        target="solar_health,adcs_health",
        effect=0.05,
        description="controlled V3.4 lifecycle event",
    )


def debris_scenario(event: ExternalEvent) -> StochasticPostLifeEventsScenario:
    return StochasticPostLifeEventsScenario(event_catalog=EventCatalog(
        [event], 34, "stochastic_post_life_events", event.hour + 1
    ))


def run_no_contact_ladder(autonomy_model: str):
    records = []
    result = Simulator(
        StandbyPolicy(),
        contact_model=ContactSchedule({0}),
        operator_view="delayed_telemetry",
        maneuver_model=(
            "stationkeeping_proxy"
            if autonomy_model == "limited_maneuver_authority"
            else "none"
        ),
        autonomy_model=autonomy_model,
    ).run(
        hours_as_years(DEFAULT_CONFIG.emergency_after_hours + 1),
        on_hour=records.append,
    )
    return result, records


def test_default_none_preserves_v33_behavior_and_blank_fields():
    assert AUTONOMY_MODELS == (
        "none",
        "safe_mode_only",
        "contingency_plan",
        "limited_maneuver_authority",
    )
    assert Simulator(StandbyPolicy()).autonomy_model == "none"
    assert run.build_parser().parse_args([]).autonomy_model == "none"
    initial = SatelliteState(soc=30.0, data_buffer_gb=950.0)
    default_records = []
    explicit_records = []
    default = Simulator(
        StandbyPolicy(), contact_model=ContactSchedule()
    ).run(
        hours_as_years(1),
        state=deepcopy(initial),
        on_hour=default_records.append,
    )
    explicit = Simulator(
        StandbyPolicy(),
        contact_model=ContactSchedule(),
        autonomy_model="none",
    ).run(
        hours_as_years(1),
        state=deepcopy(initial),
        on_hour=explicit_records.append,
    )

    assert default.state == explicit.state
    assert default.metrics == explicit.metrics
    assert default.events == explicit.events
    assert default.autonomous_action_count == 0
    record = default_records[0]
    assert record.autonomy_model == "none"
    assert record.autonomy_active_this_hour is False
    assert record.autonomy_trigger_this_hour is None
    assert record.contingency_plan_active is False


@pytest.mark.parametrize(
    ("state", "trigger"),
    [
        (SatelliteState(soc=30.0), AutonomyTrigger.LOW_EFFECTIVE_ENERGY.value),
        (
            SatelliteState(soc=80.0, thermal_health=0.20),
            AutonomyTrigger.THERMAL_PROTECTION.value,
        ),
    ],
)
def test_safe_mode_only_uses_real_state_without_contact(state, trigger):
    records = []
    result = Simulator(
        StandbyPolicy(),
        contact_model=ContactSchedule(),
        operator_view="delayed_telemetry",
        autonomy_model="safe_mode_only",
    ).run(hours_as_years(1), state=state, on_hour=records.append)

    record = records[0]
    assert record.mode == Mode.SAFE.value
    assert record.autonomy_active_this_hour is True
    assert record.autonomy_trigger_this_hour == trigger
    assert record.autonomy_authority_this_hour == (
        AutonomyAuthority.SAFE_MODE.value
    )
    assert record.autonomy_selected_mode_this_hour == Mode.SAFE.value
    assert record.telemetry_updated_this_hour is False
    assert result.autonomous_safe_mode_count == 1
    assert result.autonomous_downlink_count == 0
    assert result.autonomous_maneuver_count == 0


def test_contingency_plan_upload_uses_final_contact_and_storage_downlink():
    records = []
    result = Simulator(
        StandbyPolicy(),
        contact_model=ContactSchedule({0}, {0}),
        autonomy_model="contingency_plan",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, data_buffer_gb=950.0),
        on_hour=records.append,
    )

    record = records[0]
    assert record.contingency_plan_active is True
    assert record.contingency_plan_age_hours == 0
    assert record.autonomy_trigger_this_hour == "high_storage_pressure"
    assert record.autonomy_selected_mode_this_hour == Mode.DOWNLINK.value
    assert record.mode == Mode.DOWNLINK.value
    assert result.contingency_plan_upload_count == 1
    assert result.autonomous_downlink_count == 1

    blocked_records = []
    blocked = Simulator(
        StandbyPolicy(),
        BlockCommandScenario(),
        contact_model=ContactSchedule({0}, {0}),
        autonomy_model="contingency_plan",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, data_buffer_gb=950.0),
        on_hour=blocked_records.append,
    )
    assert blocked.contingency_plan_upload_count == 0
    assert blocked_records[0].contingency_plan_active is False
    assert blocked_records[0].autonomy_active_this_hour is False


def test_contingency_plan_expires_and_payload_unavailable_selects_standby():
    records = []
    result = Simulator(
        StandbyPolicy(),
        contact_model=ContactSchedule({0}),
        autonomy_model="contingency_plan",
    ).run(
        hours_as_years(DEFAULT_CONFIG.plan_duration_hours + 1),
        state=SatelliteState(soc=80.0, payload_health=0.05),
        on_hour=records.append,
    )

    assert records[0].autonomy_trigger_this_hour == "payload_unavailable"
    assert records[0].mode == Mode.STANDBY.value
    assert records[DEFAULT_CONFIG.plan_duration_hours - 1].contingency_plan_active
    assert records[DEFAULT_CONFIG.plan_duration_hours].contingency_plan_active is False
    assert result.contingency_plan_upload_count == 1
    assert result.contingency_plan_expired_count == 1
    assert result.autonomous_standby_count > 0


def test_existing_no_contact_ladder_remains_with_autonomy_none():
    result, records = run_no_contact_ladder("none")
    plan_expiry_hour = DEFAULT_CONFIG.plan_duration_hours
    emergency_hour = DEFAULT_CONFIG.emergency_after_hours

    assert records[0].plan_uploaded_this_hour is True
    assert records[plan_expiry_hour - 1].valid_daily_plan is True
    assert records[plan_expiry_hour].valid_daily_plan is False
    assert records[plan_expiry_hour].mode == Mode.BACKUP.value
    assert records[emergency_hour - 1].mode == Mode.BACKUP.value
    assert records[emergency_hour].mode == Mode.EMERGENCY_BEACON.value
    assert result.state.emergency_beacon_mode is True
    assert result.autonomous_action_count == 0


@pytest.mark.parametrize(
    "autonomy_model",
    ("contingency_plan", "limited_maneuver_authority"),
)
def test_existing_no_contact_ladder_remains_with_autonomy_enabled(
    autonomy_model,
):
    result, records = run_no_contact_ladder(autonomy_model)
    plan_expiry_hour = DEFAULT_CONFIG.plan_duration_hours
    emergency_hour = DEFAULT_CONFIG.emergency_after_hours

    assert records[0].contingency_plan_active is True
    assert result.contingency_plan_upload_count == 1
    assert result.contingency_plan_expired_count == 1
    assert records[plan_expiry_hour].contingency_plan_active is False
    assert records[plan_expiry_hour].mode == Mode.BACKUP.value
    assert records[plan_expiry_hour].autonomy_active_this_hour is False
    assert records[emergency_hour - 1].mode == Mode.BACKUP.value
    assert records[emergency_hour].mode == Mode.EMERGENCY_BEACON.value
    assert records[emergency_hour].autonomy_active_this_hour is False
    assert records[emergency_hour].autonomy_trigger_this_hour is None
    assert result.state.emergency_beacon_mode is True


@pytest.mark.parametrize(
    ("maneuver_model", "delta_v", "expected"),
    [
        ("stationkeeping_proxy", 2.0, True),
        ("none", 2.0, False),
        ("stationkeeping_proxy", 0.0, False),
    ],
)
def test_limited_authority_critical_drift_respects_model_and_resources(
    maneuver_model, delta_v, expected
):
    records = []
    result = Simulator(
        StandbyPolicy(),
        contact_model=ContactSchedule({0}),
        maneuver_model=maneuver_model,
        autonomy_model="limited_maneuver_authority",
    ).run(
        hours_as_years(1),
        state=SatelliteState(
            soc=80.0,
            orbit_drift_proxy_km=0.60,
            delta_v_remaining_m_per_s=delta_v,
        ),
        on_hour=records.append,
    )

    assert (records[0].autonomy_selected_mode_this_hour == Mode.MANEUVER.value) is expected
    assert (result.autonomous_maneuver_count == 1) is expected
    if expected:
        assert records[0].mode == Mode.MANEUVER.value
        assert result.state.delta_v_used_m_per_s == pytest.approx(
            DEFAULT_CONFIG.stationkeeping_delta_v_cost_m_per_s
        )
    else:
        assert result.state.delta_v_used_m_per_s == 0.0


def test_ground_only_warning_cannot_trigger_limited_maneuver_or_telemetry():
    event = debris_event()
    probe = EventLifecycleManager(EventCatalog(
        [event], 34, "stochastic_post_life_events", 97
    ))
    warning_hour = probe.events[0].warning_hour
    records = []
    simulator = Simulator(
        StandbyPolicy(),
        debris_scenario(event),
        contact_model=ContactSchedule({0}),
        operator_view="delayed_telemetry",
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="warning_proxy",
        debris_risk_model="severity_proxy",
        autonomy_model="limited_maneuver_authority",
    )
    simulator.run(
        hours_as_years(warning_hour + 1),
        state=SatelliteState(soc=80.0, delta_v_remaining_m_per_s=2.0),
        on_hour=records.append,
    )

    warning_record = records[warning_hour]
    assert warning_record.lifecycle_ground_known_count == 1
    assert warning_record.lifecycle_spacecraft_known_count == 0
    assert warning_record.autonomy_used_uploaded_response_this_hour is not True
    assert warning_record.autonomy_selected_mode_this_hour != Mode.MANEUVER.value
    assert warning_record.telemetry_updated_this_hour is False
    assert all(
        record.autonomy_trigger_this_hour != "uploaded_debris_response"
        for record in records
    )


def test_uploaded_response_allows_limited_maneuver_at_tca_with_same_cost():
    event = debris_event()
    manager = EventLifecycleManager(EventCatalog(
        [event], 34, "stochastic_post_life_events", 97
    ))
    warning_hour = manager.events[0].warning_hour
    records = []
    result = Simulator(
        StandbyPolicy(),
        debris_scenario(event),
        contact_model=ContactSchedule({warning_hour}),
        operator_view="delayed_telemetry",
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="warning_proxy",
        debris_risk_model="severity_proxy",
        autonomy_model="limited_maneuver_authority",
    ).run(
        hours_as_years(event.hour + 1),
        state=SatelliteState(soc=80.0, delta_v_remaining_m_per_s=2.0),
        on_hour=records.append,
    )

    at_tca = records[event.hour]
    assert at_tca.autonomy_trigger_this_hour == "uploaded_debris_response"
    assert at_tca.autonomy_used_uploaded_response_this_hour is True
    assert at_tca.autonomy_selected_mode_this_hour == Mode.MANEUVER.value
    assert at_tca.debris_avoidance_executed_this_hour is True
    assert result.state.debris_damage_events == 0
    assert result.state.delta_v_used_m_per_s == pytest.approx(
        DEFAULT_CONFIG.debris_avoidance_delta_v_cost_m_per_s
    )


def test_failed_uploaded_response_keeps_v33_severity_damage_mapping():
    event = debris_event()
    manager = EventLifecycleManager(EventCatalog(
        [event], 34, "stochastic_post_life_events", 97
    ))
    warning_hour = manager.events[0].warning_hour
    result = Simulator(
        StandbyPolicy(),
        debris_scenario(event),
        contact_model=ContactSchedule({warning_hour}),
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="warning_proxy",
        debris_risk_model="severity_proxy",
        autonomy_model="limited_maneuver_authority",
    ).run(
        hours_as_years(event.hour + 1),
        state=SatelliteState(soc=80.0, delta_v_remaining_m_per_s=0.0),
    )
    assessment = assess_debris_risk(
        event,
        Simulator(
            StandbyPolicy(),
            debris_scenario(event),
            event_lifecycle_model="warning_proxy",
        ).lifecycle_manager.events[0].event_id,
    )

    assert result.state.debris_avoidance_skipped_count == 1
    assert result.state.debris_damage_events == 1
    assert result.state.debris_damage_accumulated == pytest.approx(
        assessment.damage_effect
    )
    for target in assessment.damage_targets:
        assert getattr(result.state, target) < 1.0


def test_every_requested_cli_accepts_autonomy_model():
    for parser in (
        run.build_parser(),
        decision_report.build_parser(),
        event_lifecycle_report.build_parser(),
        debris_risk_report.build_parser(),
        lifecycle_seed_finder.build_parser(),
    ):
        assert parser.parse_args([
            "--autonomy-model", "limited_maneuver_authority"
        ]).autonomy_model == "limited_maneuver_authority"
    with pytest.raises(ValueError, match="autonomy_model must be one of"):
        Simulator(StandbyPolicy(), autonomy_model="invalid")


def test_state_and_decision_logs_include_passive_autonomy_fields(tmp_path):
    state_results = tmp_path / "state"
    assert run.main([
        "--years", str(hours_as_years(1)),
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--autonomy-model", "safe_mode_only",
        "--results-dir", str(state_results),
    ]) == 0
    with (state_results / "state_log.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        state_fields = set(csv.DictReader(handle).fieldnames or ())

    decision_results = tmp_path / "decision"
    decision_report.run_decision_report(
        years=hours_as_years(1),
        policy="adaptive",
        scenario="nominal",
        seed=1,
        contact_model="synthetic",
        operator_view="omniscient",
        planning_model="reactive",
        maneuver_model="none",
        orbit_evolution_model="fixed",
        event_lifecycle_model="none",
        debris_risk_model="legacy",
        autonomy_model="safe_mode_only",
        results_dir=decision_results,
    )
    with (decision_results / "decision_trace.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        decision_fields = set(csv.DictReader(handle).fieldnames or ())
    decision_markdown = (
        decision_results / "decision_summary.md"
    ).read_text(encoding="utf-8")

    expected = {
        "autonomy_model",
        "autonomy_active_this_hour",
        "autonomy_trigger_this_hour",
        "autonomy_authority_this_hour",
        "autonomy_selected_mode_this_hour",
        "autonomy_reason_this_hour",
        "autonomy_pre_authorized_this_hour",
        "autonomy_ground_contact_required_this_hour",
        "autonomy_used_uploaded_response_this_hour",
        "contingency_plan_active",
        "contingency_plan_age_hours",
        "contingency_plan_expires_in_hours",
    }
    assert expected <= state_fields
    assert expected <= decision_fields
    assert "daily-plan -> BACKUP ->" in decision_markdown
    assert "EMERGENCY_BEACON ladder" in decision_markdown
    assert "terminal no-contact fallback" in decision_markdown


def test_readme_documents_v34_scope_and_boundaries():
    readme = Path("README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())
    assert "## V3.4 onboard autonomy and contingency-plan proxy" in readme
    assert "`autonomy_model`" in readme
    for name in AUTONOMY_MODELS:
        assert f"`{name}`" in readme
    assert "Ground-only external warnings" in normalized
    assert "Scheduled future events remain hidden" in normalized
    assert "does not refresh delayed telemetry" in normalized
    assert "not real flight software" in normalized
    assert "FDIR" in readme and "onboard AI" in normalized
    assert "V3.5" in readme and "stationkeeping/drift planning repair" in normalized
    assert "uploaded daily plan -> `BACKUP` -> `EMERGENCY_BEACON` ladder" in normalized
    assert "V3.4 autonomy does not replace" in normalized
    assert "about 14 days without command contact" in normalized
    assert "local contingency diagnostic, not the 14-day emergency mechanism" in normalized
