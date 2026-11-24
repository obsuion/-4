import csv
from math import isclose

import pytest

from ops_sim.analysis import (
    PAPER_SCORE_NORMALIZATION,
    PAPER_SCORE_WEIGHTS,
    compute_ablation_deltas,
    load_analysis_csvs,
    load_csv_rows,
    rank_policies,
    render_markdown_table,
    summarize_sensitivity,
)


def _write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_csv_loading_parses_numbers_blanks_and_optional_files(tmp_path):
    path = tmp_path / "summary.csv"
    _write_csv(
        path,
        ["policy", "score", "blank", "survived", "small", "label"],
        [{
            "policy": "adaptive",
            "score": "0.75",
            "blank": " ",
            "survived": "true",
            "small": "1e-3",
            "label": "A-01",
        }],
    )

    rows = load_csv_rows(path)

    assert rows == [{
        "policy": "adaptive",
        "score": 0.75,
        "blank": None,
        "survived": True,
        "small": 0.001,
        "label": "A-01",
    }]
    assert load_csv_rows(tmp_path / "absent.csv", optional=True) == []
    with pytest.raises(FileNotFoundError, match="Required analysis CSV"):
        load_csv_rows(tmp_path / "absent.csv")


def test_bundle_loader_skips_absent_optional_rul_files(tmp_path):
    _write_csv(
        tmp_path / "summary.csv",
        ["policy", "score"],
        [{"policy": "adaptive", "score": 0.5}],
    )

    package = load_analysis_csvs(tmp_path, skip_rul=True)

    assert package.summary[0]["score"] == 0.5
    assert package.monte_carlo_summary == []
    assert package.rul_samples == []
    assert package.rul_summary == []
    assert package.rul_survival_curve == []


def test_policy_ranking_uses_documented_deterministic_weighting():
    simulator_rows = [
        {
            "policy": "alpha",
            "score": 0.8,
            "survived_hours": 80,
            "total_hours": 100,
            "data_downlinked_gb": 100,
            "final_health": 0.9,
            "fuel_remaining_percent": 80,
        },
        {
            "policy": "beta",
            "score": 0.4,
            "survived": True,
            "data_downlinked_gb": 50,
            "final_health": 0.8,
            "fuel_remaining_percent": 60,
        },
    ]
    rul_rows = [
        {
            "policy": "alpha",
            "expected_rul_years_censored": 4,
            "median_rul_years_censored": 3.8,
        },
        {
            "policy": "beta",
            "expected_rul_years_censored": 2,
            "median_rul_years_censored": 1.5,
        },
    ]

    first = rank_policies(simulator_rows, rul_rows)
    second = rank_policies(simulator_rows, rul_rows)

    assert first == second
    assert [row["policy"] for row in first] == ["alpha", "beta"]
    assert [row["rank"] for row in first] == [1, 2]
    assert first[0]["simulator_score_rank"] == 1
    assert first[1]["simulator_score_rank"] == 2
    assert first[0]["survival_fraction_rank"] == 2
    assert first[1]["survival_fraction_rank"] == 1
    assert first[0]["expected_rul_years_censored_rank"] == 1
    assert isclose(first[0]["paper_score"], 0.935)
    assert isclose(first[1]["paper_score"], 0.35)
    assert first[0]["median_rul_years_censored"] == 3.8
    assert isclose(sum(PAPER_SCORE_WEIGHTS.values()), 1.0)
    assert set(PAPER_SCORE_WEIGHTS) == set(PAPER_SCORE_NORMALIZATION)


def test_policy_ranking_handles_missing_optional_columns_without_penalty():
    rows = [
        {
            "policy": "alpha",
            "score": "0.8",
            "survived": "true",
            "data_downlinked_gb": "10",
            "final_health": "0.9",
        },
        {
            "policy": "beta",
            "score": "0.6",
            "survived": "true",
            "data_downlinked_gb": "5",
            "final_health": "0.8",
        },
    ]

    ranked = rank_policies(rows)

    assert [row["policy"] for row in ranked] == ["alpha", "beta"]
    assert all(row["fuel_remaining_percent"] is None for row in ranked)
    assert all(
        row["expected_rul_years_censored"] is None for row in ranked
    )
    assert all(
        row["expected_rul_years_censored_rank"] is None for row in ranked
    )
    # Fuel and RUL weights are absent, so the four available weights are
    # renormalized rather than silently treated as zero-valued metrics.
    expected_alpha = (0.25 + 0.20 + 0.20 + 0.15 * 0.9) / 0.80
    assert isclose(ranked[0]["paper_score"], expected_alpha)


def test_policy_metric_ranks_use_competition_ties_and_missing_values():
    ranked = rank_policies([
        {"policy": "charlie", "score": 0.5},
        {"policy": "alpha", "score": 0.8, "fuel_remaining_percent": 50},
        {"policy": "beta", "score": 0.8, "fuel_remaining_percent": 50},
    ])

    by_policy = {row["policy"]: row for row in ranked}
    assert by_policy["alpha"]["simulator_score_rank"] == 1
    assert by_policy["beta"]["simulator_score_rank"] == 1
    assert by_policy["charlie"]["simulator_score_rank"] == 3
    assert by_policy["alpha"]["fuel_remaining_percent_rank"] == 1
    assert by_policy["beta"]["fuel_remaining_percent_rank"] == 1
    assert by_policy["charlie"]["fuel_remaining_percent_rank"] is None


def test_ablation_deltas_average_replicates_and_use_comparison_minus_baseline():
    rows = [
        {
            "policy": "adaptive",
            "scenario": "stochastic",
            "configuration": "A",
            "score": 0.5,
            "survived_hours": 5,
            "total_hours": 10,
            "data_downlinked_gb": 10,
        },
        {
            "policy": "adaptive",
            "scenario": "stochastic",
            "configuration": "A",
            "score": 0.7,
            "survived_hours": 7,
            "total_hours": 10,
            "data_downlinked_gb": 14,
        },
        {
            "policy": "adaptive",
            "scenario": "stochastic",
            "configuration": "B",
            "score": 0.8,
            "survived": True,
            "data_downlinked_gb": 20,
        },
        {
            "policy": "survival_first",
            "scenario": "stochastic",
            "configuration": "A",
            "score": 0.9,
        },
    ]

    deltas = compute_ablation_deltas(
        rows,
        [("A", "B")],
        metrics=(
            "simulator_score",
            "survival_fraction",
            "data_downlinked_gb",
            "fuel_remaining_percent",
        ),
    )

    assert len(deltas) == 1
    row = deltas[0]
    assert row["baseline"] == "A"
    assert row["comparison"] == "B"
    assert isclose(row["simulator_score_baseline"], 0.6)
    assert isclose(row["simulator_score_delta"], 0.2)
    assert isclose(row["survival_fraction_delta"], 0.4)
    assert row["data_downlinked_gb_delta"] == 8
    assert row["fuel_remaining_percent_delta"] is None


def test_sensitivity_summary_groups_labels_and_reports_mean_min_max():
    rows = [
        {
            "policy": "adaptive",
            "sensitivity_label": "low",
            "score": 1,
            "final_health": 0.6,
        },
        {
            "policy": "adaptive",
            "sensitivity_label": "low",
            "score": 3,
            "final_health": 0.8,
        },
        {
            "policy": "adaptive",
            "sensitivity_label": "high",
            "score": 2,
            "final_health": "",
        },
    ]

    summary = summarize_sensitivity(
        rows,
        group_fields=("policy",),
        metrics=("simulator_score", "final_health"),
    )

    assert [row["sensitivity_label"] for row in summary] == ["high", "low"]
    high, low = summary
    assert high["rows"] == 1
    assert high["final_health_mean"] is None
    assert low["rows"] == 2
    assert low["simulator_score_mean"] == 2
    assert low["simulator_score_min"] == 1
    assert low["simulator_score_max"] == 3
    assert isclose(low["final_health_mean"], 0.7)


def test_markdown_table_is_compact_and_escapes_cells():
    markdown = render_markdown_table(
        [
            {"policy": "risk|aware", "paper_score": 0.87654, "note": None},
            {"policy": "adaptive", "paper_score": 1.0, "note": "a\nb"},
        ],
        columns=("policy", "paper_score", "note"),
        headers={"paper_score": "Paper score"},
        float_digits=3,
    )

    assert markdown == (
        "| Policy | Paper score | Note |\n"
        "| --- | --- | --- |\n"
        "| risk\\|aware | 0.877 |  |\n"
        "| adaptive | 1 | a<br>b |\n"
    )


def test_analysis_requires_names_for_grouped_operations():
    with pytest.raises(ValueError, match="configuration"):
        compute_ablation_deltas([{"score": 1}], [("A", "B")])
    with pytest.raises(ValueError, match="sensitivity_label"):
        summarize_sensitivity([{"score": 1}])
