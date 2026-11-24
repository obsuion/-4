from dataclasses import replace

import pytest

from ops_sim.config import DEFAULT_CONFIG
from ops_sim.decision import (
    RISK_FIELDS,
    assess_mode_options,
    build_failure_attribution,
    build_risk_snapshot,
)
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import Policy, make_policy
from ops_sim.simulator import Simulator


def hours_as_years(hours: int) -> float:
    return hours / DEFAULT_CONFIG.hours_per_year


class AlwaysImagingPolicy(Policy):
    name = "always_imaging"

    @property
    def safe_threshold(self) -> float:
        return self.config.adaptive_safe_threshold

    def select_mode(self, state, contact):
        return Mode.IMAGING


def risk_for(
    state: SatelliteState,
    *,
    contact: ContactInfo = ContactInfo(),
    operator_view: str = "omniscient",
    maneuver_model: str = "none",
    orbit_evolution_model: str = "fixed",
    telemetry_age_hours: int = 0,
):
    return build_risk_snapshot(
        hour=10,
        policy="adaptive",
        scenario="nominal",
        operator_view=operator_view,
        planning_model="reactive",
        maneuver_model=maneuver_model,
        orbit_evolution_model=orbit_evolution_model,
        state=state,
        contact=contact,
        planned_mode=None,
        selected_mode=Mode.STANDBY,
        executed_mode=Mode.STANDBY,
        telemetry_age_hours=telemetry_age_hours,
        safe_threshold=DEFAULT_CONFIG.adaptive_safe_threshold,
    )


def options_for(
    state: SatelliteState,
    *,
    contact: ContactInfo = ContactInfo(),
    maneuver_model: str = "none",
):
    risk = risk_for(
        state, contact=contact, maneuver_model=maneuver_model
    )
    return {
        item.mode: item
        for item in assess_mode_options(
            state=state,
            contact=contact,
            risk_snapshot=risk,
            maneuver_model=maneuver_model,
            safe_threshold=DEFAULT_CONFIG.adaptive_safe_threshold,
        )
    }


def test_risk_scores_are_clamped_and_low_soc_increases_power_risk():
    extreme = SatelliteState(
        soc=-50,
        comms_health=-2,
        payload_health=3,
        adcs_health=-1,
        thermal_health=2,
        data_buffer_gb=5000,
    )
    snapshot = risk_for(extreme)
    assert all(0.0 <= getattr(snapshot, field) <= 1.0 for field in RISK_FIELDS)

    low = risk_for(SatelliteState(soc=10))
    high = risk_for(SatelliteState(soc=90))
    assert low.power_risk > high.power_risk
    assert low.energy_margin_risk > high.energy_margin_risk


def test_buffer_and_telemetry_staleness_raise_only_relevant_risks():
    empty = risk_for(SatelliteState(data_buffer_gb=0))
    full = risk_for(SatelliteState(data_buffer_gb=950))
    assert full.storage_risk > empty.storage_risk

    current = risk_for(
        SatelliteState(),
        operator_view="delayed_telemetry",
        telemetry_age_hours=0,
    )
    stale = risk_for(
        SatelliteState(),
        operator_view="delayed_telemetry",
        telemetry_age_hours=48,
    )
    omniscient = risk_for(
        SatelliteState(),
        operator_view="omniscient",
        telemetry_age_hours=48,
    )
    assert stale.telemetry_staleness_risk > current.telemetry_staleness_risk
    assert omniscient.telemetry_staleness_risk == 0


def test_fuel_and_drift_risks_apply_only_when_maneuvers_are_relevant():
    state = SatelliteState(
        delta_v_remaining_m_per_s=0.1,
        orbit_drift_proxy_km=1.0,
    )
    disabled = risk_for(state, maneuver_model="none")
    enabled = risk_for(
        state,
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    )
    assert disabled.fuel_risk == 0
    assert disabled.orbit_drift_risk == 0
    assert enabled.fuel_risk > 0
    assert enabled.orbit_drift_risk > 0


def test_option_assessments_explain_existing_mode_constraints():
    no_contact = options_for(
        SatelliteState(data_buffer_gb=100), contact=ContactInfo()
    )
    assert no_contact[Mode.DOWNLINK.value].feasible is False
    assert no_contact[Mode.DOWNLINK.value].rejection_reason == "no data contact"
    assert no_contact[Mode.SAFE.value].feasible is True

    payload_failed = options_for(SatelliteState(payload_health=0.05))
    assert payload_failed[Mode.IMAGING.value].feasible is False
    assert payload_failed[Mode.IMAGING.value].rejection_reason == (
        "payload unavailable"
    )

    disabled = options_for(SatelliteState(), maneuver_model="none")
    assert disabled[Mode.MANEUVER.value].feasible is False
    assert disabled[Mode.MANEUVER.value].rejection_reason == (
        "maneuver model disabled"
    )

    no_fuel = options_for(
        SatelliteState(delta_v_remaining_m_per_s=0.0),
        maneuver_model="stationkeeping_proxy",
    )
    assert no_fuel[Mode.MANEUVER.value].feasible is False
    assert no_fuel[Mode.MANEUVER.value].rejection_reason == "insufficient fuel"


def test_simulator_callback_is_observational_and_emits_once_per_hour():
    years = hours_as_years(8)
    baseline = Simulator(make_policy("adaptive")).run(years)

    explanations = []
    explained = Simulator(make_policy("adaptive")).run(
        years, on_decision_explanation=explanations.append
    )

    assert len(explanations) == explained.state.hours_completed == 8
    assert explained.state == baseline.state
    assert explained.metrics == baseline.metrics
    assert explained.events == baseline.events
    assert all(item.executed_mode in {mode.value for mode in Mode} for item in explanations)
    assert all(item.option_assessments for item in explanations)


def test_callback_preserves_custom_configuration_and_safe_override_reason():
    config = replace(DEFAULT_CONFIG, initial_soc=10.0)
    explanations = []
    Simulator(
        AlwaysImagingPolicy(config), config=config
    ).run(
        hours_as_years(1),
        on_decision_explanation=explanations.append,
    )

    assert explanations[0].selected_mode == Mode.SAFE.value
    assert explanations[0].executed_mode == Mode.SAFE.value
    assert explanations[0].main_reason == "critical_power_override"
    assert "low_effective_energy_margin" in explanations[0].active_constraints


def test_failure_attribution_uses_recent_risks_and_final_state():
    config = replace(DEFAULT_CONFIG, initial_soc=0.0)
    explanations = []
    result = Simulator(
        make_policy("adaptive", config), config=config
    ).run(
        hours_as_years(10),
        on_decision_explanation=explanations.append,
    )

    attribution = build_failure_attribution(result, explanations, config)
    assert result.state.alive is False
    assert attribution.survived is False
    assert attribution.loss_reason == "critical_power"
    assert attribution.loss_hour == explanations[-1].hour
    assert attribution.likely_bottleneck == "power"
    assert attribution.last_soc == pytest.approx(result.state.soc)
    assert attribution.last_health == pytest.approx(
        result.state.total_health(config)
    )
