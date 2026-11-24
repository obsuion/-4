import csv
from pathlib import Path

import autonomy_report
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import EventCatalog


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_report_parser_defaults_match_v34_contract():
    args = autonomy_report.build_parser().parse_args([])
    assert args.years == 15
    assert args.policy == "survival_first"
    assert args.scenario == "stochastic_post_life_events"
    assert args.operator_view == "delayed_telemetry"
    assert args.planning_model == "risk_aware"
    assert args.maneuver_model == "stationkeeping_proxy"
    assert args.orbit_evolution_model == "drift_proxy"
    assert args.event_lifecycle_model == "warning_proxy"
    assert args.debris_risk_model == "severity_proxy"
    assert args.autonomy_model == "contingency_plan"
    assert args.seed == 1
    assert args.results_dir == Path("results/autonomy_report")


def test_report_writes_trace_summary_and_limitations(tmp_path):
    hours = 12
    result, records, summary = autonomy_report.run_autonomy_report(
        years=hours / DEFAULT_CONFIG.hours_per_year,
        policy="survival_first",
        scenario="stochastic_post_life_events",
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
        event_lifecycle_model="warning_proxy",
        debris_risk_model="severity_proxy",
        autonomy_model="contingency_plan",
        seed=1,
        results_dir=tmp_path,
        event_catalog=EventCatalog(
            [], 1, "stochastic_post_life_events", hours
        ),
    )

    assert len(records) == hours
    assert result.autonomy_model == "contingency_plan"
    assert summary["autonomy_model"] == "contingency_plan"
    assert summary["contingency_plan_upload_count"] >= 1
    trace_path = tmp_path / "autonomy_trace.csv"
    summary_path = tmp_path / "autonomy_summary.csv"
    markdown_path = tmp_path / "autonomy_summary.md"
    assert trace_path.is_file() and summary_path.is_file()
    assert markdown_path.is_file()
    assert set(autonomy_report.TRACE_FIELDS) <= set(read_rows(trace_path)[0])
    assert set(autonomy_report.SUMMARY_FIELDS) <= set(
        read_rows(summary_path)[0]
    )
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "bounded onboard-autonomy proxy" in markdown
    assert "not real flight software" in markdown
    assert "FDIR" in markdown
    assert "onboard AI" in markdown
    assert "does not know future external events" in markdown
    assert "does not refresh delayed telemetry" in markdown
    assert "ground-only warning" in markdown
    assert "already uploaded/pre-authorized" in markdown
    assert "daily-plan ->" in markdown
    assert "BACKUP -> EMERGENCY_BEACON ladder" in markdown
    assert "terminal no-contact fallback" in markdown
    assert "not the 14-day emergency mechanism" in markdown


def test_zero_hour_cli_still_writes_valid_outputs(tmp_path):
    assert autonomy_report.main([
        "--years", "0",
        "--results-dir", str(tmp_path),
    ]) == 0
    assert read_rows(tmp_path / "autonomy_trace.csv") == []
    summary = read_rows(tmp_path / "autonomy_summary.csv")[0]
    assert summary["autonomy_model"] == "contingency_plan"
    assert summary["autonomous_action_count"] == "0"
    assert (tmp_path / "autonomy_summary.md").is_file()
