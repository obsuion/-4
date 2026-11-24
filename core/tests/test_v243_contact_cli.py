import csv

import pytest

import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.contacts import GeometryContactModel, SyntheticContactModel
from ops_sim.policies import POLICIES
from ops_sim.scenarios import SCENARIOS


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


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def contact_pattern(path):
    return [
        (
            int(row["hour"]),
            float(row["cmd_contact_min"]),
            float(row["data_contact_min"]),
        )
        for row in read_csv(path)
    ]


def test_parser_and_factory_default_to_synthetic_contacts():
    args = run.build_parser().parse_args([])
    assert args.contact_model == "synthetic"
    assert args.geometry_step_seconds == 30
    assert args.command_overhead_seconds == 0
    assert args.data_overhead_seconds == 60
    assert args.min_data_contact_seconds == 60
    assert isinstance(run.build_contact_model(args), SyntheticContactModel)


def test_default_and_explicit_synthetic_cli_keep_fixed_contact_pattern(tmp_path):
    default_dir = tmp_path / "default"
    explicit_dir = tmp_path / "explicit"
    common = [
        "--years", "0.001", "--policy", "adaptive", "--scenario", "nominal",
    ]
    assert run.main([*common, "--results-dir", str(default_dir)]) == 0
    assert run.main([
        *common,
        "--contact-model", "synthetic",
        "--results-dir", str(explicit_dir),
    ]) == 0

    default_pattern = contact_pattern(default_dir / "state_log.csv")
    explicit_pattern = contact_pattern(explicit_dir / "state_log.csv")
    expected = [
        (hour, 15.0, 15.0) if hour % 4 == 0 else (hour, 0.0, 0.0)
        for hour in range(len(default_pattern))
    ]
    assert default_pattern == expected
    assert explicit_pattern == expected


def test_geometry_cli_runs_and_differs_from_fixed_synthetic_pattern(tmp_path):
    hours = 72
    assert run.main([
        "--years", str(hours / DEFAULT_CONFIG.hours_per_year),
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--contact-model", "geometry",
        "--results-dir", str(tmp_path),
    ]) == 0

    assert (tmp_path / "summary.csv").exists()
    pattern = contact_pattern(tmp_path / "state_log.csv")
    fixed_synthetic = [
        (hour, 15.0, 15.0) if hour % 4 == 0 else (hour, 0.0, 0.0)
        for hour in range(len(pattern))
    ]
    assert pattern != fixed_synthetic
    assert DETAILED_CONTACT_FIELDS <= set(
        read_csv(tmp_path / "state_log.csv")[0]
    )


def test_geometry_cli_accepts_custom_station_arguments(tmp_path):
    argv = [
        "--contact-model", "geometry",
        "--station-lat", "51.16",
        "--station-lon", "71.47",
        "--station-name", "custom_test_station",
        "--minimum-elevation-deg", "5",
    ]
    args = run.build_parser().parse_args(argv)
    model = run.build_contact_model(args)
    assert isinstance(model, GeometryContactModel)
    assert model.station.latitude_deg == pytest.approx(51.16)
    assert model.station.longitude_deg == pytest.approx(71.47)
    assert model.station.minimum_elevation_deg == pytest.approx(5)
    assert model.station.name == "custom_test_station"

    assert run.main([
        "--years", "0.001", "--policy", "adaptive", "--scenario", "nominal",
        *argv, "--log-level", "summary", "--results-dir", str(tmp_path),
    ]) == 0
    assert (tmp_path / "summary.csv").exists()


def test_geometry_cli_runs_the_all_scenarios_matrix(tmp_path):
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "all",
        "--seed", "42",
        "--contact-model", "geometry",
        "--log-level", "summary",
        "--results-dir", str(tmp_path),
    ]) == 0
    assert {row["scenario"] for row in read_csv(tmp_path / "summary.csv")} == set(
        SCENARIOS
    )


@pytest.mark.parametrize(
    "coordinate_args",
    [
        ["--station-lat", "51.16"],
        ["--station-lon", "71.47"],
    ],
)
def test_geometry_cli_requires_station_coordinates_together(
    tmp_path, coordinate_args
):
    with pytest.raises(SystemExit, match="must be supplied together"):
        run.main([
            "--contact-model", "geometry", *coordinate_args,
            "--results-dir", str(tmp_path),
        ])


def test_geometry_cli_reports_invalid_sampling_step(tmp_path):
    with pytest.raises(SystemExit, match="step_seconds must be positive"):
        run.main([
            "--contact-model", "geometry",
            "--geometry-step-seconds", "0",
            "--results-dir", str(tmp_path),
        ])


def test_synthetic_cli_rejects_explicit_geometry_only_options(tmp_path):
    with pytest.raises(SystemExit, match="require --contact-model geometry"):
        run.main([
            "--contact-model", "synthetic",
            "--geometry-step-seconds", "30",
            "--results-dir", str(tmp_path),
        ])


def test_seeded_stochastic_policy_matrix_runs_with_geometry(tmp_path):
    assert run.main([
        "--years", "0.01",
        "--policy", "all",
        "--scenario", "stochastic_post_life_events",
        "--seed", "42",
        "--contact-model", "geometry",
        "--results-dir", str(tmp_path),
    ]) == 0

    rows = read_csv(tmp_path / "summary.csv")
    assert len(rows) == len(POLICIES)
    assert {row["policy"] for row in rows} == set(POLICIES)
    assert (
        tmp_path / "event_catalogs"
        / "stochastic_post_life_events_seed42.csv"
    ).exists()


def test_geometry_monte_carlo_uses_summary_logging_by_default(tmp_path):
    assert run.main([
        "--years", "0.01",
        "--policy", "all",
        "--scenario", "stochastic_post_life_events",
        "--monte-carlo", "2",
        "--contact-model", "geometry",
        "--results-dir", str(tmp_path),
    ]) == 0

    summary_rows = read_csv(tmp_path / "summary.csv")
    monte_carlo_rows = read_csv(tmp_path / "monte_carlo_summary.csv")
    assert len(summary_rows) == 2 * len(POLICIES)
    assert len(monte_carlo_rows) == 2 * len(POLICIES)
    assert DETAILED_CONTACT_FIELDS.isdisjoint(summary_rows[0])
    assert DETAILED_CONTACT_FIELDS.isdisjoint(monte_carlo_rows[0])
    assert not (tmp_path / "state_log.csv").exists()
    assert not (tmp_path / "checkpoints.csv").exists()
    assert not (tmp_path / "events_log.csv").exists()
