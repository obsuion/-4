import csv
from pathlib import Path

import debris_risk_report
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import EventCatalog, ExternalEvent


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def controlled_catalog() -> EventCatalog:
    event = ExternalEvent(
        hour=8,
        event_type="debris_conjunction",
        severity=0.9,
        duration_hours=1,
        target="solar_health,adcs_health",
        effect=0.06,
        description="controlled V3.3 report conjunction",
    )
    return EventCatalog(
        [event], 1, "stochastic_post_life_events", 12
    )


def test_report_parser_defaults_match_v33_contract():
    args = debris_risk_report.build_parser().parse_args([])

    assert args.years == 15
    assert args.policy == "survival_first"
    assert args.scenario == "stochastic_post_life_events"
    assert args.operator_view == "delayed_telemetry"
    assert args.planning_model == "risk_aware"
    assert args.maneuver_model == "stationkeeping_proxy"
    assert args.orbit_evolution_model == "drift_proxy"
    assert args.event_lifecycle_model == "warning_proxy"
    assert args.debris_risk_model == "severity_proxy"
    assert args.seed == 1
    assert args.results_dir == Path("results/debris_risk_report")


def test_report_writes_all_outputs_and_pairs_lifecycle(tmp_path):
    years = 12 / DEFAULT_CONFIG.hours_per_year
    result, event_rows, summary = debris_risk_report.run_debris_risk_report(
        years=years,
        policy="survival_first",
        scenario="stochastic_post_life_events",
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        event_lifecycle_model="warning_proxy",
        debris_risk_model="severity_proxy",
        seed=1,
        results_dir=tmp_path,
        event_catalog=controlled_catalog(),
    )

    assert result.debris_risk_model == "severity_proxy"
    assert len(event_rows) == 1
    row = event_rows[0]
    assert row["event_id"]
    assert row["warning_hour"] == 0
    assert row["execution_hour"] == 8
    assert row["response_uploaded"] is True
    assert row["response_executed"] is True
    assert row["response_skipped"] is False
    assert summary["debris_events"] == 1
    assert summary["responses_uploaded"] == 1
    assert summary["responses_executed"] == 1
    assert summary["damage_events"] == 0

    event_csv = tmp_path / "debris_risk_events.csv"
    summary_csv = tmp_path / "debris_risk_summary.csv"
    summary_md = tmp_path / "debris_risk_summary.md"
    assert event_csv.is_file()
    assert summary_csv.is_file()
    assert summary_md.is_file()
    assert set(debris_risk_report.EVENT_FIELDS) <= set(read_rows(event_csv)[0])
    assert set(debris_risk_report.SUMMARY_FIELDS) <= set(
        read_rows(summary_csv)[0]
    )
    markdown = summary_md.read_text(encoding="utf-8")
    assert "synthetic debris risk assessment" in markdown
    assert "not real collision" in markdown
    assert "proxy values" in markdown
    assert "V3.2A handles" in markdown
    assert "V3.3 only characterizes" in markdown


def test_report_cli_writes_empty_but_valid_bounded_outputs(tmp_path):
    assert debris_risk_report.main([
        "--years", "0",
        "--results-dir", str(tmp_path),
    ]) == 0

    assert read_rows(tmp_path / "debris_risk_events.csv") == []
    summary = read_rows(tmp_path / "debris_risk_summary.csv")[0]
    assert summary["debris_risk_model"] == "severity_proxy"
    assert summary["debris_events"] == "0"
    assert (tmp_path / "debris_risk_summary.md").is_file()
