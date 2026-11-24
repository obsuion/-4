import csv

import pytest

import overview
import run
from ops_sim.inspect_tool import main as inspect_main
from ops_sim.orbit import position_at_hour
from ops_sim.policies import POLICIES
from ops_sim.scenarios import SCENARIOS, make_scenario


NEW_SCENARIOS = {
    "solar_array_degradation",
    "reduced_downlink_capacity",
    "storage_pressure",
    "payload_degradation",
    "comms_degradation",
    "low_contact_availability",
    "extended_no_contact_30_days",
    "repeated_short_outages",
    "high_imaging_demand",
    "attitude_pointing_stress",
    "combined_energy_stress",
    "extreme_compound_post_life_stress",
}


def test_analytical_orbit_returns_expected_initial_position_and_bounds():
    position = position_at_hour(0)
    assert position.latitude_deg == pytest.approx(0)
    assert position.longitude_deg == pytest.approx(0)
    assert position.altitude_km == pytest.approx(750)
    assert 90 < position.period_minutes < 110
    later = position_at_hour(123)
    assert -90 <= later.latitude_deg <= 90
    assert -180 <= later.longitude_deg <= 180
    assert 0 <= later.phase_deg < 360


def test_all_matrix_creates_four_csv_files(tmp_path):
    assert run.main([
        "--years", "0.001", "--policy", "all", "--scenario", "all",
        "--results-dir", str(tmp_path),
    ]) == 0
    expected = {"summary.csv", "state_log.csv", "checkpoints.csv", "events_log.csv"}
    assert expected == {path.name for path in tmp_path.iterdir()}
    with (tmp_path / "summary.csv").open(newline="", encoding="utf-8") as handle:
        summaries = list(csv.DictReader(handle))
    assert len(summaries) == len(POLICIES) * len(SCENARIOS)
    assert {(row["policy"], row["scenario"]) for row in summaries} == {
        (policy, scenario)
        for policy in POLICIES
        for scenario in SCENARIOS
    }


def test_make_scenario_supports_every_new_scenario():
    assert NEW_SCENARIOS <= set(SCENARIOS)
    for name in NEW_SCENARIOS:
        assert make_scenario(name).name == name


def test_one_year_adaptive_all_scenarios_creates_outputs(tmp_path, capsys):
    assert run.main([
        "--years", "1", "--policy", "adaptive", "--scenario", "all",
        "--results-dir", str(tmp_path),
    ]) == 0
    capsys.readouterr()
    for filename in ("summary.csv", "state_log.csv", "checkpoints.csv", "events_log.csv"):
        assert (tmp_path / filename).exists()
    with (tmp_path / "summary.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["scenario"] for row in rows} == set(SCENARIOS)
    assert {
        "data_lost_gb", "data_loss_fraction", "overflow_hours", "minimum_soc",
        "minimum_health", "final_buffer_fraction", "effective_storage_capacity_gb",
    } <= set(rows[0])
    with (tmp_path / "state_log.csv").open(newline="", encoding="utf-8") as handle:
        state_row = next(csv.DictReader(handle))
    assert {
        "data_lost_gb", "overflow_hours", "effective_storage_capacity_gb",
        "pointing_efficiency", "effective_downlink_rate_gb_per_min",
        "effective_imaging_rate_gb_per_hour", "effective_energy_margin",
        "minimum_soc", "minimum_health",
    } <= set(state_row)
    with (tmp_path / "checkpoints.csv").open(newline="", encoding="utf-8") as handle:
        checkpoint_row = next(csv.DictReader(handle))
    assert {
        "data_lost_gb", "overflow_hours", "effective_storage_capacity_gb",
    } <= set(checkpoint_row)


def test_inspect_reads_specific_hour(tmp_path, capsys):
    run.main([
        "--years", "0.001", "--policy", "adaptive", "--scenario", "nominal",
        "--results-dir", str(tmp_path),
    ])
    capsys.readouterr()
    assert inspect_main([
        "--policy", "adaptive", "--scenario", "nominal", "--hour", "5",
        "--state-log", str(tmp_path / "state_log.csv"),
    ]) == 0
    output = capsys.readouterr().out
    assert "Hour / year: 5" in output
    assert "Approximate position:" in output
    assert "Effective storage capacity:" in output
    assert "Pointing efficiency:" in output
    assert "Effective energy margin:" in output
    assert "Interpretation:" in output


def test_overview_reads_summary_and_sorts_by_score(tmp_path, capsys):
    run.main([
        "--years", "0.001", "--policy", "all", "--scenario", "nominal",
        "--results-dir", str(tmp_path),
    ])
    capsys.readouterr()
    assert overview.main(["--summary", str(tmp_path / "summary.csv")]) == 0
    output = capsys.readouterr().out
    assert "Policy" in output
    assert "adaptive" in output
    assert "Downlinked GB" in output
    assert "Lost GB" in output
    assert "Overflow h" in output
