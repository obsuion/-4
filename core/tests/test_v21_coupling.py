import csv

import overview
import pytest
import run

from ops_sim.inspect_tool import main as inspect_main
from ops_sim.models import ContactInfo, Mode, SatelliteState
from ops_sim.policies import AggressivePolicy
from ops_sim.simulator import Simulator


@pytest.fixture
def simulator():
    return Simulator(AggressivePolicy())


def test_comms_health_reduces_downlink(simulator):
    healthy = SatelliteState(data_buffer_gb=100, comms_health=1.0)
    degraded = SatelliteState(data_buffer_gb=100, comms_health=0.5)
    contact = ContactInfo(cmd_contact_min=15, data_contact_min=15)

    simulator._execute_mode(healthy, Mode.DOWNLINK, contact)
    simulator._execute_mode(degraded, Mode.DOWNLINK, contact)

    assert degraded.total_data_downlinked_gb < healthy.total_data_downlinked_gb


def test_payload_health_reduces_imaging_output(simulator):
    healthy = SatelliteState(payload_health=1.0)
    degraded = SatelliteState(payload_health=0.5)

    simulator._execute_mode(healthy, Mode.IMAGING, ContactInfo())
    simulator._execute_mode(degraded, Mode.IMAGING, ContactInfo())

    assert degraded.total_data_generated_gb < healthy.total_data_generated_gb


def test_storage_health_reduces_effective_usable_capacity(simulator):
    healthy = SatelliteState(storage_health=1.0)
    degraded = SatelliteState(storage_health=0.5)

    assert (
        simulator.effective_storage_capacity_gb(degraded)
        < simulator.effective_storage_capacity_gb(healthy)
    )


def test_overflow_records_data_loss_and_increments_overflow_hours(simulator):
    state = SatelliteState(data_buffer_gb=490, storage_health=0.5)
    overflow_hours_before = state.overflow_hours

    simulator._execute_mode(state, Mode.IMAGING, ContactInfo())

    assert state.data_lost_gb > 0
    assert state.overflow_hours == overflow_hours_before + 1


def test_adcs_health_reduces_pointing_efficiency(simulator):
    healthy = SatelliteState(adcs_health=1.0)
    degraded = SatelliteState(adcs_health=0.5)

    assert simulator.pointing_efficiency(degraded) < simulator.pointing_efficiency(healthy)


def test_solar_health_reduces_positive_soc_recovery(simulator):
    healthy = SatelliteState(soc=50, solar_health=1.0)
    degraded = SatelliteState(soc=50, solar_health=0.5)

    simulator._execute_mode(healthy, Mode.SAFE, ContactInfo())
    simulator._execute_mode(degraded, Mode.SAFE, ContactInfo())

    assert degraded.soc - 50 < healthy.soc - 50


def test_degraded_battery_reduces_effective_energy_margin(simulator):
    state = SatelliteState(soc=60, battery_health=0.5)

    assert simulator.effective_energy_margin(state) < state.soc


def _create_v21_outputs(results_dir):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--results-dir", str(results_dir),
    ]) == 0


def test_state_log_contains_v21_fields(tmp_path, capsys):
    _create_v21_outputs(tmp_path)
    capsys.readouterr()

    with (tmp_path / "state_log.csv").open(newline="", encoding="utf-8") as handle:
        fields = set(next(csv.DictReader(handle)))

    assert {
        "data_lost_gb",
        "overflow_hours",
        "effective_storage_capacity_gb",
        "pointing_efficiency",
        "effective_downlink_rate_gb_per_min",
        "effective_imaging_rate_gb_per_hour",
        "effective_energy_margin",
        "minimum_soc",
        "minimum_health",
    } <= fields


def test_inspect_output_contains_v21_operational_fields(tmp_path, capsys):
    _create_v21_outputs(tmp_path)
    capsys.readouterr()

    assert inspect_main([
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--hour", "5",
        "--state-log", str(tmp_path / "state_log.csv"),
    ]) == 0
    output = capsys.readouterr().out

    assert "Effective storage capacity:" in output
    assert "Data lost / overflow hours:" in output
    assert "Pointing efficiency:" in output
    assert "Effective energy margin:" in output
    assert "Effective downlink rate:" in output


def test_overview_output_contains_v21_columns(tmp_path, capsys):
    _create_v21_outputs(tmp_path)
    capsys.readouterr()

    assert overview.main(["--summary", str(tmp_path / "summary.csv")]) == 0
    output = capsys.readouterr().out

    assert "Lost GB" in output
    assert "Overflow h" in output
    assert "Emergency" in output
