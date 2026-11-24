import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

import event_lifecycle_report
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.event_lifecycle import LifecycleEvent, LifecycleTransition


OUTPUT_FILES = {
    "event_lifecycle_events.csv",
    "event_lifecycle_transitions.csv",
    "event_lifecycle_summary.csv",
    "event_lifecycle_summary.md",
}


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _fake_catalog(total_hours: int) -> EventCatalog:
    assert total_hours > 8
    event = ExternalEvent(
        hour=8,
        event_type="debris_conjunction",
        severity=0.6,
        duration_hours=1,
        target="solar_health",
        effect=0.01,
        description="Deterministic report-test conjunction",
    )
    return EventCatalog(
        events=[event],
        seed=987,
        scenario_name="stochastic_post_life_events",
        total_hours=total_hours,
    )


def _install_fake_catalog(monkeypatch) -> None:
    def generate(seed, scenario, total_hours, config):
        assert seed == 987
        assert scenario == "stochastic_post_life_events"
        assert config is DEFAULT_CONFIG
        return _fake_catalog(total_hours)

    monkeypatch.setattr(
        event_lifecycle_report,
        "generate_stochastic_event_catalog",
        generate,
    )


def _cli_args(results_dir: Path) -> list[str]:
    years = 12 / DEFAULT_CONFIG.hours_per_year
    return [
        "--years", str(years),
        "--seed", "987",
        "--results-dir", str(results_dir),
    ]


def test_parser_defaults_match_the_bounded_lifecycle_report_contract():
    args = event_lifecycle_report.build_parser().parse_args([])

    assert args.years == 1
    assert args.policy == "adaptive"
    assert args.scenario == "stochastic_post_life_events"
    assert args.seed == 42
    assert args.contact_model == "synthetic"
    assert args.operator_view == "delayed_telemetry"
    assert args.planning_model == "risk_aware"
    assert args.maneuver_model == "stationkeeping_proxy"
    assert args.orbit_evolution_model == "drift_proxy"
    assert args.event_lifecycle_model == "warning_proxy"
    assert args.results_dir == Path("results/event_lifecycle_report")
    assert args.summary_only is False
    assert args.max_transitions is None


def test_report_cli_writes_all_outputs_from_an_explicit_fake_event(
    tmp_path, monkeypatch
):
    _install_fake_catalog(monkeypatch)

    assert event_lifecycle_report.main(_cli_args(tmp_path)) == 0

    assert OUTPUT_FILES <= {
        path.name for path in tmp_path.iterdir() if path.is_file()
    }
    event_rows = _read_rows(tmp_path / "event_lifecycle_events.csv")
    transition_rows = _read_rows(
        tmp_path / "event_lifecycle_transitions.csv"
    )
    summary_rows = _read_rows(tmp_path / "event_lifecycle_summary.csv")
    assert len(event_rows) == 1
    assert len(transition_rows) > 2
    assert len(summary_rows) == 1
    assert set(event_lifecycle_report.EVENT_FIELDS) <= set(event_rows[0])
    assert set(event_lifecycle_report.TRANSITION_FIELDS) <= set(
        transition_rows[0]
    )
    assert set(event_lifecycle_report.SUMMARY_FIELDS) <= set(summary_rows[0])
    assert summary_rows[0]["lifecycle_events"] == "1"
    assert summary_rows[0]["warnings_generated"] == "1"
    assert summary_rows[0]["event_lifecycle_model"] == "warning_proxy"
    markdown = (tmp_path / "event_lifecycle_summary.md").read_text(
        encoding="utf-8"
    )
    assert "information-flow and command-upload proxy" in markdown
    assert "not real conjunction assessment" in markdown


def test_summary_only_removes_transition_csv_but_keeps_event_and_summary(
    tmp_path, monkeypatch
):
    _install_fake_catalog(monkeypatch)
    transition_path = tmp_path / "event_lifecycle_transitions.csv"
    transition_path.write_text("stale", encoding="utf-8")

    assert event_lifecycle_report.main([
        *_cli_args(tmp_path),
        "--summary-only",
    ]) == 0

    assert not transition_path.exists()
    assert (tmp_path / "event_lifecycle_events.csv").is_file()
    assert (tmp_path / "event_lifecycle_summary.csv").is_file()
    assert (tmp_path / "event_lifecycle_summary.md").is_file()
    assert len(_read_rows(tmp_path / "event_lifecycle_events.csv")) == 1


def test_max_transitions_limits_only_written_transition_rows(
    tmp_path, monkeypatch
):
    _install_fake_catalog(monkeypatch)

    assert event_lifecycle_report.main([
        *_cli_args(tmp_path),
        "--max-transitions", "2",
    ]) == 0

    assert len(_read_rows(tmp_path / "event_lifecycle_transitions.csv")) == 2
    assert len(_read_rows(tmp_path / "event_lifecycle_events.csv")) == 1
    summary = _read_rows(tmp_path / "event_lifecycle_summary.csv")[0]
    assert summary["lifecycle_events"] == "1"
    assert summary["warnings_generated"] == "1"


def test_summary_counts_failed_upload_fixture_without_running_seeded_catalog():
    event = LifecycleEvent(
        event_id="debris-24-test",
        event_type="debris_conjunction",
        source_event_hour=24,
        warning_hour=12,
        ground_awareness_hour=12,
        spacecraft_awareness_hour=None,
        decision_deadline_hour=23,
        execution_hour=24,
        status="resolved_failed",
        severity=0.7,
        confidence=0.85,
        requires_command_upload=True,
        requires_maneuver=True,
        response_uploaded=False,
        response_upload_hour=None,
        response_executed=False,
        response_skipped=True,
        failure_reason="no_command_upload_before_tca",
        linked_external_event_hour=24,
    )
    warned = LifecycleTransition(
        hour=12,
        year=12 / DEFAULT_CONFIG.hours_per_year,
        event_id=event.event_id,
        event_type=event.event_type,
        previous_status="scheduled",
        new_status="warned",
        transition_reason="external_warning_available",
        ground_knows=False,
        spacecraft_knows=False,
        command_contact_min=0,
        data_contact_min=0,
        response_uploaded=False,
        response_executed=False,
        response_skipped=False,
        failure_reason=None,
    )

    summary = event_lifecycle_report.build_lifecycle_summary(
        policy="adaptive",
        scenario="stochastic_post_life_events",
        years=0.01,
        seed=987,
        event_lifecycle_model="warning_proxy",
        events=[event],
        transitions=[warned],
        state=SimpleNamespace(alive=False, loss_reason="thermal_failure"),
    )

    assert summary["lifecycle_events"] == 1
    assert summary["warnings_generated"] == 1
    assert summary["responses_uploaded"] == 0
    assert summary["responses_executed"] == 0
    assert summary["responses_skipped"] == 1
    assert summary["resolved_failed"] == 1
    assert summary["missed_upload_due_to_no_contact"] == 1
    assert summary["mean_warning_lead_time_hours"] == 12
    assert summary["mean_upload_lead_time_hours"] is None
    assert summary["survived"] is False
    assert summary["loss_reason"] == "thermal_failure"


def test_invalid_report_bounds_fail_clearly():
    with pytest.raises(SystemExit, match="--years"):
        event_lifecycle_report.main(["--years", "nan"])
    with pytest.raises(SystemExit, match="--max-transitions"):
        event_lifecycle_report.main(["--max-transitions", "-1"])


def test_readme_documents_v32a_information_boundary_and_report_outputs():
    readme = Path("README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "## V3.2A event lifecycle and awareness proxy" in readme
    assert "`event_lifecycle_model`" in readme
    assert "`none`" in readme and "`warning_proxy`" in readme
    assert "External warning awareness and spacecraft telemetry remain separate" in normalized
    assert "command opportunity uploads the response before TCA" in normalized
    assert "never refreshes delayed-telemetry `observed_state`" in normalized
    assert "`event_lifecycle_report.py`" in readme
    for filename in OUTPUT_FILES:
        assert f"`{filename}`" in readme
    assert "`--summary-only`" in readme
    assert "`--max-transitions N`" in readme
    assert "not real conjunction assessment" in normalized
    assert "real collision probability" in normalized
    assert "CARA, STK, GMAT" in normalized
    assert "flight software" in normalized
    assert "KazEOSat-1 operational logic" in normalized
    assert "deferred to V3.3" in normalized
    assert "deferred to V3.4" in normalized
