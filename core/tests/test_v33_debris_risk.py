from copy import deepcopy
from pathlib import Path

import pytest

import decision_report
import event_lifecycle_report
import lifecycle_seed_finder
import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.debris_risk import (
    DEBRIS_RISK_MODELS,
    IMPACT_ZONE_DAMAGE_TARGETS,
    MAXIMUM_PROXY_DAMAGE_EFFECT,
    DebrisImpactZone,
    assess_debris_risk,
)
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.event_lifecycle import EventLifecycleManager
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import Policy
from ops_sim.scenarios import StochasticPostLifeEventsScenario
from ops_sim.simulator import Simulator


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


def debris_event(hour: int = 0, duration_hours: int = 1) -> ExternalEvent:
    return ExternalEvent(
        hour=hour,
        event_type="debris_conjunction",
        severity=0.82,
        duration_hours=duration_hours,
        target="solar_health,adcs_health,thermal_health,comms_health",
        effect=0.05,
        description="controlled V3.3 debris event",
    )


def debris_scenario(
    event: ExternalEvent | None,
) -> StochasticPostLifeEventsScenario:
    events = [] if event is None else [event]
    return StochasticPostLifeEventsScenario(
        event_catalog=EventCatalog(
            events,
            33,
            "stochastic_post_life_events",
            (event.hour + event.duration_hours) if event else 2,
        )
    )


class StandbyPolicy(Policy):
    name = "v33_standby"

    @property
    def safe_threshold(self) -> float:
        return 0.0

    def select_mode(
        self, state: SatelliteState, contact: ContactInfo
    ) -> Mode:
        return Mode.STANDBY


class NoContact:
    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo()


class ContactSchedule:
    def __init__(self, command_hours: set[int]):
        self.command_hours = command_hours

    def contact_at_hour(self, hour: int) -> ContactInfo:
        return ContactInfo(
            cmd_contact_min=8.0 if hour in self.command_hours else 0.0
        )


def test_assessment_is_stable_bounded_and_rejects_non_debris():
    event = debris_event(hour=72)
    first = assess_debris_risk(event, "stable-event-id")
    second = assess_debris_risk(event, "stable-event-id")

    assert first == second
    assert 0.0 <= first.risk_score <= 1.0
    assert 0.0 <= first.warning_confidence <= 1.0
    assert 0.0 <= first.damage_effect <= MAXIMUM_PROXY_DAMAGE_EFFECT
    assert first.object_size_cm > 0.0
    assert first.relative_velocity_km_s > 0.0
    assert first.miss_distance_proxy_m > 0.0
    assert "not collision probability" in first.notes

    with pytest.raises(ValueError, match="debris_conjunction"):
        assess_debris_risk(ExternalEvent(
            0, "solar_storm", 0.5, 1, "solar_health", 0.01, "not debris"
        ))


def test_every_impact_zone_has_the_required_health_mapping():
    assert set(IMPACT_ZONE_DAMAGE_TARGETS) == set(DebrisImpactZone)
    assert IMPACT_ZONE_DAMAGE_TARGETS[DebrisImpactZone.SOLAR_ARRAY] == (
        "solar_health",
    )
    assert IMPACT_ZONE_DAMAGE_TARGETS[DebrisImpactZone.COMMS_ANTENNA] == (
        "comms_health",
    )
    assert IMPACT_ZONE_DAMAGE_TARGETS[DebrisImpactZone.ADCS] == (
        "adcs_health",
    )
    assert IMPACT_ZONE_DAMAGE_TARGETS[
        DebrisImpactZone.THERMAL_CONTROL
    ] == ("thermal_health",)
    assert IMPACT_ZONE_DAMAGE_TARGETS[
        DebrisImpactZone.PAYLOAD_APERTURE
    ] == ("payload_health",)
    assert IMPACT_ZONE_DAMAGE_TARGETS[DebrisImpactZone.OBC] == (
        "obc_health",
    )
    assert IMPACT_ZONE_DAMAGE_TARGETS[DebrisImpactZone.PROPULSION] == (
        "propulsion_health",
    )
    assert IMPACT_ZONE_DAMAGE_TARGETS[DebrisImpactZone.BUS_STRUCTURE] == (
        "adcs_health",
        "thermal_health",
        "obc_health",
    )


def test_legacy_default_preserves_failed_damage_and_counters():
    event = debris_event(duration_hours=2)
    initial = SatelliteState(soc=80.0, delta_v_remaining_m_per_s=0.0)
    default_result = Simulator(
        StandbyPolicy(),
        debris_scenario(event),
        contact_model=NoContact(),
        maneuver_model="none",
    ).run(hours_as_years(2), state=deepcopy(initial))
    explicit_result = Simulator(
        StandbyPolicy(),
        debris_scenario(event),
        contact_model=NoContact(),
        maneuver_model="none",
        debris_risk_model="legacy",
    ).run(hours_as_years(2), state=deepcopy(initial))

    assert DEBRIS_RISK_MODELS == ("legacy", "severity_proxy")
    assert default_result.state == explicit_result.state
    assert default_result.metrics == explicit_result.metrics
    assert explicit_result.state.debris_avoidance_skipped_count == 1
    assert explicit_result.state.debris_damage_events == 1
    assert explicit_result.state.debris_damage_accumulated == pytest.approx(
        event.effect
    )


def test_severity_proxy_applies_mapped_damage_once_and_logs_assessment():
    event = debris_event(duration_hours=2)
    assessment = assess_debris_risk(event)
    initial = SatelliteState(soc=80.0)
    records = []
    result = Simulator(
        StandbyPolicy(),
        debris_scenario(event),
        contact_model=NoContact(),
        maneuver_model="none",
        debris_risk_model="severity_proxy",
    ).run(
        hours_as_years(2), state=deepcopy(initial), on_hour=records.append
    )
    control = Simulator(
        StandbyPolicy(),
        debris_scenario(None),
        contact_model=NoContact(),
        maneuver_model="none",
    ).run(hours_as_years(2), state=deepcopy(initial))

    for target in assessment.damage_targets:
        assert getattr(control.state, target) - getattr(result.state, target) == (
            pytest.approx(assessment.damage_effect)
        )
    assert result.state.debris_avoidance_skipped_count == 1
    assert result.state.debris_damage_events == 1
    assert result.state.debris_damage_accumulated == pytest.approx(
        assessment.damage_effect
    )
    assert records[0].debris_risk_model == "severity_proxy"
    assert records[0].debris_risk_class_this_hour == assessment.risk_class
    assert records[0].debris_impact_zone_this_hour == assessment.impact_zone
    assert records[0].debris_risk_score_this_hour == pytest.approx(
        assessment.risk_score
    )
    assert records[1].debris_risk_class_this_hour is None
    assert result.debris_risk_model == "severity_proxy"


def test_successful_avoidance_prevents_severity_damage_and_keeps_counters():
    event = debris_event()
    result = Simulator(
        StandbyPolicy(),
        debris_scenario(event),
        contact_model=NoContact(),
        maneuver_model="stationkeeping_proxy",
        debris_risk_model="severity_proxy",
    ).run(
        hours_as_years(1),
        state=SatelliteState(soc=80.0, delta_v_remaining_m_per_s=2.0),
    )

    assert result.state.debris_avoidance_executed_count == 1
    assert result.state.debris_avoidance_skipped_count == 0
    assert result.state.debris_damage_events == 0
    assert result.state.debris_damage_accumulated == 0.0
    assert result.state.delta_v_used_m_per_s == pytest.approx(
        DEFAULT_CONFIG.debris_avoidance_delta_v_cost_m_per_s
    )


def test_lifecycle_warning_does_not_leak_risk_or_refresh_telemetry():
    event = debris_event(hour=96)
    manager = EventLifecycleManager(
        EventCatalog([event], 33, "stochastic_post_life_events", 97)
    )
    warning_hour = manager.events[0].warning_hour
    records = []
    simulator = Simulator(
        StandbyPolicy(),
        debris_scenario(event),
        contact_model=ContactSchedule({0}),
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        event_lifecycle_model="warning_proxy",
        debris_risk_model="severity_proxy",
    )
    simulator.run(
        hours_as_years(warning_hour + 1),
        state=SatelliteState(soc=70.0),
        on_hour=records.append,
    )

    assert all(record.debris_risk_class_this_hour is None for record in records)
    assert records[warning_hour].lifecycle_ground_known_count == 1
    assert records[warning_hour].lifecycle_spacecraft_known_count == 0
    assert records[warning_hour].telemetry_updated_this_hour is False
    assert records[warning_hour].last_telemetry_hour == 0


def test_cli_selectors_default_to_legacy_and_accept_severity_proxy():
    assert run.build_parser().parse_args([]).debris_risk_model == "legacy"
    assert (
        decision_report.build_parser().parse_args([]).debris_risk_model
        == "legacy"
    )
    assert (
        event_lifecycle_report.build_parser().parse_args([]).debris_risk_model
        == "legacy"
    )
    assert (
        lifecycle_seed_finder.build_parser().parse_args([]).debris_risk_model
        == "legacy"
    )
    for parser in (
        run.build_parser(),
        decision_report.build_parser(),
        event_lifecycle_report.build_parser(),
        lifecycle_seed_finder.build_parser(),
    ):
        assert parser.parse_args([
            "--debris-risk-model", "severity_proxy"
        ]).debris_risk_model == "severity_proxy"
    with pytest.raises(ValueError, match="debris_risk_model must be one of"):
        Simulator(StandbyPolicy(), debris_risk_model="invalid")


def test_readme_documents_v33_scope_and_future_boundaries():
    readme = Path("README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "## V3.3 debris severity and impact-zone proxy" in readme
    assert "`debris_risk_model`" in readme
    assert "`legacy`" in readme and "`severity_proxy`" in readme
    assert "not real collision probability" in normalized
    for boundary in ("CARA", "STK", "GMAT", "SGP4", "TLE"):
        assert boundary in readme
    assert "V3.4" in readme and "onboard autonomy" in normalized
    assert "V3.5" in readme and "stationkeeping/drift planning" in normalized

