import pytest

from ops_sim.config import DEFAULT_CONFIG, SimulationConfig
from ops_sim.metrics import calculate_metrics
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import AggressivePolicy, ConservativePolicy
from ops_sim.scenarios import ContactOutageScenario, HighBatteryDegradationScenario, Scenario
from ops_sim.simulator import Simulator


def test_synthetic_contacts_are_minutes_every_four_hours():
    simulator = Simulator(AggressivePolicy())
    assert simulator.nominal_contact(0) == ContactInfo(15, 15)
    assert simulator.nominal_contact(1) == ContactInfo()
    assert simulator.nominal_contact(4) == ContactInfo(15, 15)


def test_imaging_and_downlink_data_accounting():
    simulator = Simulator(AggressivePolicy())
    state = SatelliteState(soc=80)
    simulator._execute_mode(state, Mode.IMAGING, ContactInfo())
    assert state.data_buffer_gb == 25
    assert state.total_images_taken == 1
    simulator._execute_mode(state, Mode.DOWNLINK, ContactInfo(15, 15))
    assert state.data_buffer_gb == 0
    assert state.total_data_downlinked_gb == 25


def test_storage_blocks_imaging_at_ninety_five_percent():
    simulator = Simulator(AggressivePolicy())
    state = SatelliteState(soc=80, data_buffer_gb=950)
    assert simulator._select_mode(state, ContactInfo()) == Mode.STANDBY


def test_low_soc_overrides_policy_with_safe_mode():
    simulator = Simulator(AggressivePolicy())
    state = SatelliteState(soc=14)
    assert simulator._select_mode(state, ContactInfo()) == Mode.SAFE


def test_outage_reaches_backup_then_emergency_and_recovers():
    config = SimulationConfig(outage_start_year=0.0, outage_duration_days=16)
    simulator = Simulator(ConservativePolicy(config), ContactOutageScenario(config), config)
    result = simulator.run(17 / config.days_per_year)
    assert result.state.mode_hours[Mode.BACKUP] > 0
    assert result.state.mode_hours[Mode.EMERGENCY_BEACON] > 0
    assert result.state.hours_since_contact < config.contact_interval_hours
    assert not result.state.emergency_beacon_mode
    event_types = [event.event_type for event in result.events]
    assert event_types.count("contact_outage_begins") == 1
    assert event_types.count("contact_outage_ends") == 1
    assert event_types.count("backup_mode") == 1
    assert event_types.count("emergency_beacon_mode") == 1


def test_critical_power_loss_requires_more_than_six_hours():
    config = SimulationConfig(
        initial_soc=5,
        soc_safe_delta=0,
        solar_annual_degradation=0,
        battery_annual_degradation=0,
        payload_annual_degradation=0,
        storage_annual_degradation=0,
        comms_annual_degradation=0,
    )
    simulator = Simulator(AggressivePolicy(config), Scenario(), config)
    result = simulator.run(8 / config.hours_per_year)
    assert not result.state.alive
    assert result.state.hours_completed == 7
    assert result.state.loss_reason.value == "critical_power"


def test_high_battery_degradation_doubles_hourly_loss():
    config = DEFAULT_CONFIG
    nominal = Simulator(AggressivePolicy(config), Scenario(), config)
    high = Simulator(AggressivePolicy(config), HighBatteryDegradationScenario(config), config)
    nominal_state = SatelliteState()
    high_state = SatelliteState()
    nominal._degrade_health(nominal_state, Mode.STANDBY)
    high._degrade_health(high_state, Mode.STANDBY)
    nominal_loss = 1 - nominal_state.battery_health
    high_loss = 1 - high_state.battery_health
    assert high_loss == pytest.approx(2 * nominal_loss)


def test_metrics_are_normalized_and_formula_is_applied():
    state = SatelliteState(
        soc=50,
        total_data_downlinked_gb=30,
        hours_completed=4,
        safe_mode_hours=1,
    )
    metrics = calculate_metrics(state, 4)
    assert metrics.normalized_data_downlinked == 1
    assert metrics.survival_fraction == 1
    assert metrics.final_soc_fraction == 0.5
    expected = 0.35 + 0.25 + 0.20 + 0.05 - 0.025
    assert metrics.score == pytest.approx(expected)


def test_half_year_checkpoints_and_time_conversion():
    simulator = Simulator(ConservativePolicy())
    result = simulator.run(1)
    assert [checkpoint.hour for checkpoint in result.checkpoints] == [4383, 8766]
    assert result.checkpoints[0].year == pytest.approx(0.5)
