import csv
from pathlib import Path

import pytest

import rul
from ops_sim.contacts import GeometryContactModel, SyntheticContactModel
from ops_sim.policies import POLICIES
from ops_sim.scenarios import SCENARIOS


SAMPLE_FIELDS = {
    "sample_seed",
    "start_year",
    "horizon_years",
    "warmup_failed",
    "alive_at_start",
    "survived_to_horizon",
    "additional_hours_survived",
    "additional_years_survived",
    "loss_reason",
    "risk_driver",
    "risk_margin",
    "start_soc",
    "start_health",
    "start_delta_v_remaining_m_per_s",
    "start_fuel_remaining_percent",
    "start_orbit_drift_proxy_km",
    "final_soc",
    "final_health",
    "final_delta_v_remaining_m_per_s",
    "final_fuel_remaining_percent",
    "final_orbit_drift_proxy_km",
    "data_downlinked_during_rul_gb",
    "data_generated_during_rul_gb",
    "debris_avoidance_executed_during_rul",
    "debris_avoidance_skipped_during_rul",
    "maneuver_count_during_rul",
    "orbit_correction_count_during_rul",
}

SUMMARY_FIELDS = {
    "policy",
    "scenario",
    "operator_view",
    "planning_model",
    "maneuver_model",
    "orbit_evolution_model",
    "contact_model",
    "start_year",
    "horizon_years",
    "samples",
    "alive_at_start_fraction",
    "survived_to_horizon_fraction",
    "expected_rul_years_censored",
    "median_rul_years_censored",
    "p05_rul_years_censored",
    "p95_rul_years_censored",
    "probability_survive_plus_1y",
    "probability_survive_plus_2y",
    "probability_survive_plus_3y",
    "probability_survive_to_horizon",
    "most_common_loss_reason",
    "most_common_risk_driver",
    "mean_start_soc",
    "mean_start_health",
    "mean_start_fuel_remaining_percent",
    "mean_final_soc",
    "mean_final_health",
    "mean_final_fuel_remaining_percent",
    "mean_data_downlinked_during_rul_gb",
    "mean_data_generated_during_rul_gb",
    "mean_maneuver_count_during_rul",
    "mean_debris_avoidance_executed_during_rul",
    "mean_debris_avoidance_skipped_during_rul",
}

SURVIVAL_FIELDS = {
    "policy",
    "scenario",
    "start_year",
    "years_after_start",
    "survival_probability",
    "samples",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_parser_defaults_match_the_v29_contract():
    args = rul.build_parser().parse_args([])

    assert args.start_year == pytest.approx(8.0)
    assert args.horizon_years == pytest.approx(5.0)
    assert args.samples == 50
    assert args.seed == 0
    assert args.policy == "adaptive"
    assert args.scenario == "nominal"
    assert args.contact_model == "synthetic"
    assert args.operator_view == "omniscient"
    assert args.planning_model == "reactive"
    assert args.maneuver_model == "none"
    assert args.orbit_evolution_model == "fixed"
    assert args.results_dir == Path("results/rul")
    assert isinstance(rul.build_contact_model(args), SyntheticContactModel)


def test_parser_accepts_run_choices_and_all_selectors():
    parser = rul.build_parser()
    for policy in [*POLICIES, "all"]:
        assert parser.parse_args(["--policy", policy]).policy == policy
    for scenario in [*SCENARIOS, "all"]:
        assert parser.parse_args(["--scenario", scenario]).scenario == scenario


def test_geometry_options_delegate_to_run_contact_builder():
    args = rul.build_parser().parse_args(
        [
            "--contact-model",
            "geometry",
            "--station-lat",
            "51.16",
            "--station-lon",
            "71.47",
            "--station-name",
            "rul_test_station",
            "--minimum-elevation-deg",
            "7",
            "--geometry-step-seconds",
            "60",
            "--command-overhead-seconds",
            "5",
            "--data-overhead-seconds",
            "30",
            "--min-data-contact-seconds",
            "45",
        ]
    )

    model = rul.build_contact_model(args)
    assert isinstance(model, GeometryContactModel)
    assert model.station.name == "rul_test_station"
    assert model.station.latitude_deg == pytest.approx(51.16)
    assert model.station.longitude_deg == pytest.approx(71.47)
    assert model.station.minimum_elevation_deg == pytest.approx(7)
    assert model.step_seconds == 60
    assert model.command_overhead_seconds == 5
    assert model.data_overhead_seconds == 30
    assert model.min_data_contact_seconds == 45


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--start-year", "-1"], "--start-year"),
        (["--start-year", "nan"], "--start-year"),
        (["--horizon-years", "-1"], "--horizon-years"),
        (["--horizon-years", "inf"], "--horizon-years"),
        (["--samples", "0"], "--samples"),
        (["--station-lat", "51.16"], "require --contact-model geometry"),
        (
            ["--contact-model", "geometry", "--station-lat", "51.16"],
            "must be supplied together",
        ),
    ],
)
def test_cli_validation_is_clear(argv, message):
    with pytest.raises(SystemExit, match=message):
        rul.main(argv)


def test_cli_writes_the_three_v29_csv_outputs(tmp_path, capsys):
    assert (
        rul.main(
            [
                "--start-year",
                "0",
                "--horizon-years",
                "0.001",
                "--samples",
                "1",
                "--policy",
                "adaptive",
                "--scenario",
                "nominal",
                "--results-dir",
                str(tmp_path),
            ]
        )
        == 0
    )

    assert {path.name for path in tmp_path.iterdir()} == {
        "rul_samples.csv",
        "rul_summary.csv",
        "rul_survival_curve.csv",
    }
    sample_rows = _read_csv(tmp_path / "rul_samples.csv")
    summary_rows = _read_csv(tmp_path / "rul_summary.csv")
    survival_rows = _read_csv(tmp_path / "rul_survival_curve.csv")
    assert len(sample_rows) == 1
    assert len(summary_rows) == 1
    assert survival_rows
    assert SAMPLE_FIELDS <= set(sample_rows[0])
    assert SUMMARY_FIELDS <= set(summary_rows[0])
    assert SURVIVAL_FIELDS <= set(survival_rows[0])
    assert summary_rows[0]["contact_model"] == "synthetic"
    assert "RUL estimation complete" in capsys.readouterr().out


def test_all_selectors_run_the_policy_scenario_matrix(monkeypatch, tmp_path):
    calls = []

    class Row:
        def __init__(self, values):
            self.values = values

        def as_dict(self):
            return self.values

    def fake_estimator(**kwargs):
        policy = kwargs["policy_name"]
        scenario = kwargs["scenario_name"]
        calls.append((policy, scenario))
        provenance = {"policy": policy, "scenario": scenario}
        return (
            [Row({**provenance, "sample_seed": kwargs["seed"]})],
            Row({**provenance, "samples": kwargs["samples"]}),
            [Row({**provenance, "years_after_start": 0.0})],
        )

    monkeypatch.setattr(rul, "estimate_remaining_useful_life", fake_estimator)
    assert rul.main(
        [
            "--policy",
            "all",
            "--scenario",
            "all",
            "--samples",
            "1",
            "--horizon-years",
            "0",
            "--results-dir",
            str(tmp_path),
        ]
    ) == 0

    assert set(calls) == {
        (policy, scenario)
        for policy in POLICIES
        for scenario in SCENARIOS
    }
    assert len(_read_csv(tmp_path / "rul_summary.csv")) == (
        len(POLICIES) * len(SCENARIOS)
    )


def test_readme_documents_v29_semantics_and_outputs():
    readme = Path("README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "## V2.9 Remaining Useful Life estimation" in readme
    assert "warm-up" in readme
    assert "continues it for up to `--horizon-years`" in readme
    assert "horizon-censored" in readme
    assert "common-random-number history" in readme
    assert "not real KazEOSat-1 lifetime predictions" in normalized
    assert "policy, scenario, operator view, planning" in normalized
    assert "contact model, and orbit-evolution model" in normalized
    assert "`rul_samples.csv`" in readme
    assert "`rul_summary.csv`" in readme
    assert "`rul_survival_curve.csv`" in readme
