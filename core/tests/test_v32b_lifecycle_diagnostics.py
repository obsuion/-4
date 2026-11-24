import csv
from pathlib import Path

import decision_report
import run
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.event_catalog import EventCatalog, ExternalEvent
from ops_sim.event_lifecycle import EventLifecycleManager
from ops_sim.models import ContactInfo
from ops_sim.policies import make_policy
from ops_sim.scenarios import StochasticPostLifeEventsScenario
from ops_sim.simulator import Simulator


LIFECYCLE_FIELDS = {
    "lifecycle_ground_known_count",
    "lifecycle_spacecraft_known_count",
    "lifecycle_uploaded_count",
    "lifecycle_pending_count",
    "lifecycle_active_count",
    "lifecycle_missed_upload_count",
    "lifecycle_next_warning_hour",
    "lifecycle_next_execution_hour",
}


def debris_catalog(execution_hour: int = 96) -> EventCatalog:
    return EventCatalog(
        events=[ExternalEvent(
            hour=execution_hour,
            event_type="debris_conjunction",
            severity=0.8,
            duration_hours=1,
            target="adcs_health,thermal_health",
            effect=0.05,
            description="V3.2B deterministic lifecycle event",
        )],
        seed=320,
        scenario_name="stochastic_post_life_events",
        total_hours=execution_hour + 1,
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_simulator_none_diagnostics_are_zero_and_do_not_expose_inventory():
    simulator = Simulator(make_policy("adaptive"))

    diagnostics = simulator.lifecycle_diagnostics()

    assert simulator.event_lifecycle_model == "none"
    assert diagnostics.lifecycle_ground_known_count == 0
    assert diagnostics.lifecycle_spacecraft_known_count == 0
    assert diagnostics.lifecycle_uploaded_count == 0
    assert diagnostics.lifecycle_pending_count == 0
    assert diagnostics.lifecycle_active_count == 0
    assert diagnostics.lifecycle_resolved_success_count == 0
    assert diagnostics.lifecycle_resolved_failed_count == 0
    assert diagnostics.lifecycle_missed_upload_count == 0
    assert diagnostics.lifecycle_next_warning_hour is None
    assert diagnostics.lifecycle_next_execution_hour is None


def test_warning_upload_and_missed_counts_follow_separate_awareness_channels():
    catalog = debris_catalog()
    simulator = Simulator(
        make_policy("adaptive"),
        StochasticPostLifeEventsScenario(event_catalog=catalog),
        event_lifecycle_model="warning_proxy",
    )
    manager = simulator.lifecycle_manager
    assert manager is not None
    event = manager.events[0]

    manager.advance(event.warning_hour - 1, ContactInfo(cmd_contact_min=15))
    before = simulator.lifecycle_diagnostics(event.warning_hour - 1)
    assert before.lifecycle_ground_known_count == 0
    assert before.lifecycle_spacecraft_known_count == 0
    assert before.lifecycle_next_warning_hour is None
    assert before.lifecycle_next_execution_hour is None

    manager.advance(event.warning_hour, ContactInfo(data_contact_min=15))
    warned = simulator.lifecycle_diagnostics(event.warning_hour)
    assert warned.lifecycle_ground_known_count == 1
    assert warned.lifecycle_spacecraft_known_count == 0
    assert warned.lifecycle_uploaded_count == 0
    assert warned.lifecycle_pending_count == 1
    assert warned.lifecycle_next_warning_hour == event.warning_hour
    assert warned.lifecycle_next_execution_hour == event.execution_hour

    manager.advance(event.warning_hour + 1, ContactInfo(cmd_contact_min=15))
    uploaded = simulator.lifecycle_diagnostics(event.warning_hour + 1)
    assert uploaded.lifecycle_ground_known_count == 1
    assert uploaded.lifecycle_spacecraft_known_count == 1
    assert uploaded.lifecycle_uploaded_count == 1
    assert uploaded.lifecycle_pending_count == 0

    missed_simulator = Simulator(
        make_policy("adaptive"),
        StochasticPostLifeEventsScenario(event_catalog=debris_catalog()),
        event_lifecycle_model="warning_proxy",
    )
    missed_manager = missed_simulator.lifecycle_manager
    assert missed_manager is not None
    missed_event = missed_manager.events[0]
    missed_manager.advance(missed_event.warning_hour, ContactInfo())
    missed_manager.advance(missed_event.execution_hour, ContactInfo())
    missed = missed_simulator.lifecycle_diagnostics(
        missed_event.execution_hour
    )
    assert missed.lifecycle_active_count == 1
    assert missed.lifecycle_missed_upload_count == 1
    assert missed.lifecycle_resolved_failed_count == 1


def test_run_state_log_has_zero_blank_lifecycle_defaults(tmp_path):
    assert run.build_parser().parse_args([]).event_lifecycle_model == "none"
    assert run.main([
        "--years", "0.001",
        "--policy", "adaptive",
        "--scenario", "nominal",
        "--results-dir", str(tmp_path),
    ]) == 0

    summary = read_rows(tmp_path / "summary.csv")[0]
    state = read_rows(tmp_path / "state_log.csv")[0]
    assert summary["event_lifecycle_model"] == "none"
    assert state["event_lifecycle_model"] == "none"
    assert LIFECYCLE_FIELDS <= set(state)
    for field in LIFECYCLE_FIELDS - {
        "lifecycle_next_warning_hour",
        "lifecycle_next_execution_hour",
    }:
        assert state[field] == "0"
    assert state["lifecycle_next_warning_hour"] == ""
    assert state["lifecycle_next_execution_hour"] == ""


def test_decision_report_writes_lifecycle_context_without_telemetry_claims(
    tmp_path, monkeypatch
):
    catalog = debris_catalog(execution_hour=8)

    def fake_generate(seed, scenario, total_hours, config):
        return catalog

    monkeypatch.setattr(
        decision_report, "generate_stochastic_event_catalog", fake_generate
    )
    parser = decision_report.build_parser()
    assert parser.parse_args([]).event_lifecycle_model == "none"
    assert parser.parse_args([
        "--event-lifecycle-model", "warning_proxy"
    ]).event_lifecycle_model == "warning_proxy"

    assert decision_report.main([
        "--years", str(12 / DEFAULT_CONFIG.hours_per_year),
        "--policy", "adaptive",
        "--scenario", "stochastic_post_life_events",
        "--operator-view", "delayed_telemetry",
        "--planning-model", "risk_aware",
        "--maneuver-model", "stationkeeping_proxy",
        "--orbit-evolution-model", "drift_proxy",
        "--event-lifecycle-model", "warning_proxy",
        "--results-dir", str(tmp_path),
    ]) == 0

    decisions = read_rows(tmp_path / "decision_trace.csv")
    risks = read_rows(tmp_path / "risk_trace.csv")
    assert LIFECYCLE_FIELDS <= set(decisions[0])
    assert LIFECYCLE_FIELDS <= set(risks[0])
    assert any(row["lifecycle_ground_known_count"] == "1" for row in decisions)
    assert any(row["lifecycle_uploaded_count"] == "1" for row in decisions)
    summary = (tmp_path / "decision_summary.md").read_text(encoding="utf-8")
    assert "## Lifecycle awareness" in summary
    assert "Lifecycle model: `warning_proxy`" in summary
    assert "does not refresh delayed spacecraft telemetry" in summary
    assert "not exposed before their `warning_hour`" in summary


def test_readme_documents_v32b_lifecycle_analytics_and_boundaries():
    readme = Path("README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "## V3.2B lifecycle analytics integration" in readme
    assert "`decision_trace.csv`" in readme
    assert "`risk_trace.csv`" in readme
    assert "`lifecycle_seed_finder.py`" in readme
    assert "reporting and diagnostics only" in normalized
    assert "does not change policy decisions" in normalized
    assert "real collision probability" in normalized
    assert "## Future roadmap" in readme
    for version in (
        "V3.3", "V3.4", "V3.5", "V3.6", "V3.7",
        "V3.8", "V3.9", "V4.0", "V4.1",
    ):
        assert version in readme
    assert "final synthesizer" in normalized
