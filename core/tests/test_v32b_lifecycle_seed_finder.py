import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

import lifecycle_seed_finder
from ops_sim.event_lifecycle import LifecycleEvent, LifecycleTransition


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def fake_lifecycle_event(seed: int) -> LifecycleEvent:
    return LifecycleEvent(
        event_id=f"seed-{seed}-event",
        event_type="debris_conjunction",
        source_event_hour=24,
        warning_hour=12,
        ground_awareness_hour=12,
        spacecraft_awareness_hour=16,
        decision_deadline_hour=23,
        execution_hour=24,
        status="resolved_success",
        severity=0.7,
        confidence=0.7,
        requires_command_upload=True,
        requires_maneuver=True,
        response_uploaded=True,
        response_upload_hour=16,
        response_executed=True,
        response_skipped=False,
        failure_reason=None,
        linked_external_event_hour=24,
    )


def fake_warning(event: LifecycleEvent) -> LifecycleTransition:
    return LifecycleTransition(
        hour=event.warning_hour,
        year=0.0,
        event_id=event.event_id,
        event_type=event.event_type,
        previous_status="scheduled",
        new_status="warned",
        transition_reason="external_warning_issued",
        ground_knows=False,
        spacecraft_knows=False,
        command_contact_min=0.0,
        data_contact_min=0.0,
        response_uploaded=False,
        response_executed=False,
        response_skipped=False,
        failure_reason=None,
    )


def test_seed_finder_parser_defaults_are_bounded():
    args = lifecycle_seed_finder.build_parser().parse_args([])

    assert args.years == 15
    assert args.policy == "survival_first"
    assert args.scenario == "stochastic_post_life_events"
    assert args.operator_view == "delayed_telemetry"
    assert args.planning_model == "risk_aware"
    assert args.maneuver_model == "stationkeeping_proxy"
    assert args.orbit_evolution_model == "drift_proxy"
    assert args.event_lifecycle_model == "warning_proxy"
    assert args.seed_start == 0
    assert args.seed_count == 100
    assert args.results_dir == Path("results/lifecycle_seed_finder")
    assert args.min_warnings == 1
    assert args.stop_after_first is False


def test_seed_finder_writes_compact_csv_and_stops_after_first_match(
    tmp_path, monkeypatch
):
    examined = []

    def fake_report(**kwargs):
        seed = kwargs["seed"]
        examined.append(seed)
        assert kwargs["summary_only"] is True
        assert kwargs["write_outputs"] is False
        result = SimpleNamespace(
            state=SimpleNamespace(alive=True, loss_reason=None),
            metrics=SimpleNamespace(score=0.75, final_total_health=0.9),
        )
        if seed != 2:
            summary = {
                "lifecycle_events": 0,
                "warnings_generated": 0,
                "responses_uploaded": 0,
                "responses_executed": 0,
                "responses_skipped": 0,
                "resolved_success": 0,
                "resolved_failed": 0,
                "missed_upload_due_to_no_contact": 0,
            }
            return result, [], [], summary
        event = fake_lifecycle_event(seed)
        summary = {
            "lifecycle_events": 1,
            "warnings_generated": 1,
            "responses_uploaded": 1,
            "responses_executed": 1,
            "responses_skipped": 0,
            "resolved_success": 1,
            "resolved_failed": 0,
            "missed_upload_due_to_no_contact": 0,
        }
        return result, [event], [fake_warning(event)], summary

    monkeypatch.setattr(
        lifecycle_seed_finder,
        "run_event_lifecycle_report",
        fake_report,
    )

    assert lifecycle_seed_finder.main([
        "--years", "1",
        "--seed-start", "0",
        "--seed-count", "5",
        "--stop-after-first",
        "--results-dir", str(tmp_path),
    ]) == 0

    assert examined == [0, 1, 2]
    rows = read_rows(tmp_path / "lifecycle_seed_finder.csv")
    assert len(rows) == 1
    row = rows[0]
    assert set(lifecycle_seed_finder.OUTPUT_FIELDS) <= set(row)
    assert row["seed"] == "2"
    assert row["warnings_generated"] == "1"
    assert row["first_warning_hour"] == "12"
    assert row["first_execution_hour"] == "24"
    assert row["score"] == "0.75"
    assert not list(tmp_path.glob("seed_*"))


def test_seed_finder_validates_search_bounds():
    with pytest.raises(SystemExit, match="--years"):
        lifecycle_seed_finder.main(["--years", "nan"])
    with pytest.raises(SystemExit, match="--seed-count"):
        lifecycle_seed_finder.main(["--seed-count", "0"])
    with pytest.raises(SystemExit, match="--min-warnings"):
        lifecycle_seed_finder.main(["--min-warnings", "-1"])
