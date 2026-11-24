import csv
from math import isfinite

import pytest

import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.inspect_tool import main as inspect_main
from ops_sim.models import ContactInfo
from ops_sim.policies import AdaptivePolicy
from ops_sim.scenarios import Scenario
from ops_sim.simulator import Simulator


DETAILED_CONTACT_FIELDS = {
    "contact_model",
    "base_cmd_contact_min",
    "base_data_contact_min",
    "geometry_raw_visible_seconds",
    "geometry_usable_cmd_seconds",
    "geometry_usable_data_seconds",
    "geometry_max_elevation_deg",
    "geometry_min_range_km",
    "geometry_first_visible_offset_seconds",
    "geometry_last_visible_offset_seconds",
    "ground_station_name",
    "ground_station_lat_deg",
    "ground_station_lon_deg",
    "ground_station_minimum_elevation_deg",
}
GEOMETRY_ONLY_FIELDS = DETAILED_CONTACT_FIELDS - {
    "contact_model",
    "base_cmd_contact_min",
    "base_data_contact_min",
}


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_fields(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return set(csv.DictReader(handle).fieldnames or [])


@pytest.fixture(scope="module")
def synthetic_results(tmp_path_factory):
    results_dir = tmp_path_factory.mktemp("v244_synthetic")
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--results-dir", str(results_dir),
    ]) == 0
    return results_dir


@pytest.fixture(scope="module")
def geometry_results(tmp_path_factory):
    results_dir = tmp_path_factory.mktemp("v244_geometry")
    hours = 72
    assert run.main([
        "--years", str(hours / DEFAULT_CONFIG.hours_per_year),
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--contact-model", "geometry",
        "--results-dir", str(results_dir),
    ]) == 0
    return results_dir


def test_synthetic_log_has_base_contacts_and_blank_geometry_fields(
    synthetic_results,
):
    rows = read_rows(synthetic_results / "state_log.csv")
    assert DETAILED_CONTACT_FIELDS <= set(rows[0])
    for row in rows:
        hour = int(row["hour"])
        expected = 15.0 if hour % 4 == 0 else 0.0
        assert row["contact_model"] == "synthetic"
        assert float(row["base_cmd_contact_min"]) == expected
        assert float(row["base_data_contact_min"]) == expected
        assert float(row["cmd_contact_min"]) == expected
        assert float(row["data_contact_min"]) == expected
        assert all(row[field] == "" for field in GEOMETRY_ONLY_FIELDS)


def test_geometry_log_contains_consistent_contact_diagnostics(geometry_results):
    rows = read_rows(geometry_results / "state_log.csv")
    assert DETAILED_CONTACT_FIELDS <= set(rows[0])
    for row in rows:
        assert row["contact_model"] == "geometry"
        base_cmd = float(row["base_cmd_contact_min"])
        base_data = float(row["base_data_contact_min"])
        usable_cmd = float(row["geometry_usable_cmd_seconds"])
        usable_data = float(row["geometry_usable_data_seconds"])
        raw_visible = float(row["geometry_raw_visible_seconds"])
        assert base_cmd == pytest.approx(usable_cmd / 60)
        assert base_data == pytest.approx(usable_data / 60)
        assert float(row["cmd_contact_min"]) >= 0
        assert float(row["data_contact_min"]) >= 0
        assert base_cmd >= 0
        assert base_data >= 0
        assert 0 <= raw_visible <= DEFAULT_CONFIG.seconds_per_hour
        if row["geometry_max_elevation_deg"]:
            assert isfinite(float(row["geometry_max_elevation_deg"]))
        if row["geometry_min_range_km"]:
            assert float(row["geometry_min_range_km"]) > 0
        assert row["ground_station_name"] == "astana_proxy"
        assert float(row["ground_station_lat_deg"]) == pytest.approx(51.16)
        assert float(row["ground_station_lon_deg"]) == pytest.approx(71.47)
        assert float(
            row["ground_station_minimum_elevation_deg"]
        ) == pytest.approx(DEFAULT_CONFIG.minimum_elevation_deg)


class FixedContactModel:
    def contact_at_hour(self, hour):
        return ContactInfo(7.0, 5.0)


class ZeroContactScenario(Scenario):
    name = "zero_contact_test"

    def modify_contacts(self, contact, state, hour):
        return ContactInfo()


def test_hour_record_preserves_base_contact_before_scenario_modification():
    records = []
    simulator = Simulator(
        AdaptivePolicy(),
        ZeroContactScenario(),
        contact_model=FixedContactModel(),
    )
    result = simulator.run(
        1 / DEFAULT_CONFIG.hours_per_year,
        on_hour=records.append,
    )

    assert result.state.hours_completed == 1
    assert len(records) == 1
    record = records[0]
    assert record.contact_model == "FixedContactModel"
    assert record.base_cmd_contact_min == 7
    assert record.base_data_contact_min == 5
    assert record.cmd_contact_min == 0
    assert record.data_contact_min == 0
    assert record.geometry_raw_visible_seconds is None


def test_inspector_lists_and_selects_geometry_contact_fields(
    geometry_results, capsys
):
    state_log = geometry_results / "state_log.csv"
    assert inspect_main(["--list-fields", "--state-log", str(state_log)]) == 0
    listed = capsys.readouterr().out
    assert "contact_model" in listed
    assert "geometry_raw_visible_seconds" in listed
    assert "ground_station_minimum_elevation_deg" in listed

    assert inspect_main([
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--hour", "0",
        "--fields", "contact_model,geometry_raw_visible_seconds",
        "--state-log", str(state_log),
    ]) == 0
    selected = capsys.readouterr().out
    assert "contact_model" in selected
    assert "geometry_raw_visible_seconds" in selected

    assert inspect_main([
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--hour", "0",
        "--full",
        "--state-log", str(state_log),
    ]) == 0
    full = capsys.readouterr().out
    assert "geometry_max_elevation_deg" in full
    assert "ground_station_name" in full


def test_detailed_contact_fields_are_confined_to_state_log(geometry_results):
    assert DETAILED_CONTACT_FIELDS.isdisjoint(
        read_fields(geometry_results / "summary.csv")
    )
    assert DETAILED_CONTACT_FIELDS.isdisjoint(
        read_fields(geometry_results / "checkpoints.csv")
    )
    assert DETAILED_CONTACT_FIELDS.isdisjoint(
        read_fields(geometry_results / "events_log.csv")
    )
