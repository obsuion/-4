import pytest

from ops_sim.config import SimulationConfig
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import AggressivePolicy
from ops_sim.scenarios import (
    HighImagingDemandScenario,
    LowContactAvailabilityScenario,
    ReducedDownlinkCapacityScenario,
    SCENARIOS,
    SolarArrayDegradationScenario,
)
from ops_sim.simulator import Simulator


NEW_SCENARIOS = set(SCENARIOS) - {
    "nominal", "contact_outage", "high_battery_degradation",
    "stochastic_post_life_events",
}


def immediate_stress_config(**changes):
    return SimulationConfig(post_life_stress_start_year=0.0, **changes)


def test_every_new_scenario_emits_a_transition_event_at_activation():
    config = immediate_stress_config(extreme_blackout_start_year=1.0)
    for name in NEW_SCENARIOS:
        scenario = SCENARIOS[name](config)
        assert scenario.events_at_hour(0), name


def test_solar_stress_accelerates_only_after_activation():
    config = immediate_stress_config()
    nominal_state = SatelliteState()
    stressed_state = SatelliteState()
    nominal = Simulator(AggressivePolicy(config), config=config)
    scenario = SolarArrayDegradationScenario(config)
    stressed = Simulator(AggressivePolicy(config), scenario, config)
    scenario.apply_pre_hour(stressed_state, 0)
    nominal._degrade_health(nominal_state, nominal_state.mode)
    stressed._degrade_health(stressed_state, stressed_state.mode)
    nominal_loss = 1 - nominal_state.solar_health
    stressed_loss = 1 - stressed_state.solar_health
    assert stressed_loss == pytest.approx(
        config.solar_stress_degradation_multiplier * nominal_loss
    )


def test_reduced_downlink_and_high_demand_use_data_path_multipliers():
    config = immediate_stress_config()
    reduced_scenario = ReducedDownlinkCapacityScenario(config)
    reduced_scenario.apply_pre_hour(SatelliteState(), 0)
    reduced = Simulator(AggressivePolicy(config), reduced_scenario, config)
    downlink_state = SatelliteState(data_buffer_gb=100)
    reduced._execute_mode(downlink_state, Mode.DOWNLINK, ContactInfo(15, 15))
    assert downlink_state.total_data_downlinked_gb == 15

    demand_scenario = HighImagingDemandScenario(config)
    demand_scenario.apply_pre_hour(SatelliteState(), 0)
    demand = Simulator(AggressivePolicy(config), demand_scenario, config)
    imaging_state = SatelliteState()
    demand._execute_mode(imaging_state, Mode.IMAGING, ContactInfo())
    assert imaging_state.total_data_generated_gb == 37.5


def test_low_contact_availability_deterministically_retains_one_in_three():
    config = immediate_stress_config()
    scenario = LowContactAvailabilityScenario(config)
    state = SatelliteState()
    scenario.apply_pre_hour(state, 0)
    contact = ContactInfo(15, 15)
    assert scenario.modify_contacts(contact, state, 0) == contact
    assert scenario.modify_contacts(contact, state, 4) == ContactInfo()
    assert scenario.modify_contacts(contact, state, 8) == ContactInfo()
    assert scenario.modify_contacts(contact, state, 12) == contact
