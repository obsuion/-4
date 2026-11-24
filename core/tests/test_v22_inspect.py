import csv
from pathlib import Path

import pytest
import run

from ops_sim.inspect_tool import main as inspect_main


@pytest.fixture(scope="module")
def v22_results(tmp_path_factory):
    results_dir = tmp_path_factory.mktemp("v22_results")
    assert run.main([
        "--years", "0.002",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--results-dir", str(results_dir),
    ]) == 0
    return results_dir


def inspect_args(results_dir, *extra):
    return [
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--hour", "5",
        "--state-log", str(results_dir / "state_log.csv"),
        *extra,
    ]


def test_state_log_contains_full_v22_system_and_capability_fields(v22_results):
    with (v22_results / "state_log.csv").open(newline="", encoding="utf-8") as handle:
        fields = set(next(csv.DictReader(handle)))

    assert {
        "eps_health", "solar_health", "battery_health", "comms_health",
        "payload_health", "storage_health", "adcs_health", "obc_health",
        "thermal_health", "propulsion_health", "effective_energy_margin",
        "effective_storage_capacity_gb", "pointing_efficiency",
        "effective_downlink_rate_gb_per_min",
        "effective_imaging_rate_gb_per_hour", "data_lost_gb", "overflow_hours",
        "minimum_soc", "minimum_health",
    } <= fields


def test_full_view_prints_all_logged_fields(v22_results, capsys):
    capsys.readouterr()
    assert inspect_main(inspect_args(v22_results, "--full")) == 0
    output = capsys.readouterr().out

    assert "adcs_health" in output
    assert "propulsion_health" in output
    assert "effective_energy_margin" in output
    assert "orbit_phase_deg" in output


def test_systems_view_prints_subsystem_and_capability_fields(v22_results, capsys):
    assert inspect_main(inspect_args(v22_results, "--systems")) == 0
    output = capsys.readouterr().out

    assert "eps_health" in output
    assert "battery_health" in output
    assert "thermal_health" in output
    assert "pointing_efficiency" in output
    assert "effective_imaging_rate_gb_per_hour" in output


def test_custom_fields_print_only_identifiers_and_requested_fields(v22_results, capsys):
    assert inspect_main(
        inspect_args(v22_results, "--fields", "soc,battery_health")
    ) == 0
    output = capsys.readouterr().out

    printed_fields = {
        line.split(":", 1)[0].strip()
        for line in output.splitlines()
        if ":" in line
    }
    assert printed_fields == {
        "policy", "scenario", "hour", "year", "soc", "battery_health"
    }


def test_custom_fields_warn_about_missing_names(v22_results, capsys):
    assert inspect_main(
        inspect_args(v22_results, "--fields", "soc,not_a_logged_field")
    ) == 0
    output = capsys.readouterr().out

    assert "soc" in output
    assert "Warning: unavailable fields: not_a_logged_field" in output


def test_around_prints_compact_window(v22_results, capsys):
    assert inspect_main(inspect_args(v22_results, "--around", "2")) == 0
    output = capsys.readouterr().out
    lines = output.splitlines()

    assert "hour" in lines[0]
    assert "effective_energy_margin" in lines[0]
    hours = [int(line.split()[0]) for line in lines[2:]]
    assert hours == [3, 4, 5, 6, 7]


def test_around_has_precedence_and_nearest_selects_window_center(v22_results, capsys):
    args = inspect_args(v22_results, "--nearest", "--around", "1", "--full")
    hour_index = args.index("--hour") + 1
    args[hour_index] = "100"

    assert inspect_main(args) == 0
    output = capsys.readouterr().out

    assert output.splitlines()[0].startswith("hour")
    assert "policy" not in output.splitlines()[0]


def test_list_fields_prints_available_columns(v22_results, capsys):
    assert inspect_main([
        "--list-fields", "--state-log", str(v22_results / "state_log.csv")
    ]) == 0
    output = capsys.readouterr().out

    assert "Available state_log fields:" in output
    assert "adcs_health" in output
    assert "effective_energy_margin" in output


def test_list_fields_missing_default_log_is_clear(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert inspect_main(["--list-fields"]) == 1
    output = capsys.readouterr().out.strip()
    assert output == (
        "results/state_log.csv not found. "
        "Run an experiment first with python run.py ..."
    )


def test_default_compact_report_still_works(v22_results, capsys):
    assert inspect_main(inspect_args(v22_results)) == 0
    output = capsys.readouterr().out

    assert "Policy: adaptive" in output
    assert "Current mode:" in output
    assert "Interpretation:" in output


def test_readme_clarifies_payload_data_units():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "imagery/instrument payload data" in readme
    assert "housekeeping telemetry" in readme
    assert "command uplink" in readme
