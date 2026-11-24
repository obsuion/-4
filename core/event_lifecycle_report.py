"""Run one bounded V3.2A event-lifecycle simulation and write a report."""

from __future__ import annotations

import argparse
import csv
from dataclasses import fields
from enum import Enum
from math import isfinite
from pathlib import Path
from statistics import fmean
from typing import Mapping, Sequence

from ops_sim.autonomy import AUTONOMY_MODELS
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.contacts import (
    GeometryContactModel,
    SyntheticContactModel,
    default_astana_ground_station,
)
from ops_sim.debris_risk import DEBRIS_RISK_MODELS
from ops_sim.event_catalog import (
    EventCatalog,
    generate_stochastic_event_catalog,
)
from ops_sim.event_lifecycle import LifecycleEvent, LifecycleTransition
from ops_sim.policies import POLICIES, make_policy
from ops_sim.scenarios import SCENARIOS, make_scenario
from ops_sim.simulator import (
    EVENT_LIFECYCLE_MODELS,
    MANEUVER_MODELS,
    OPERATOR_VIEWS,
    ORBIT_EVOLUTION_MODELS,
    PLANNING_MODELS,
    Simulator,
)


DEFAULT_RESULTS_DIR = Path("results/event_lifecycle_report")
STOCHASTIC_SCENARIO = "stochastic_post_life_events"
TRANSITIONS_FILE = "event_lifecycle_transitions.csv"

EVENT_FIELDS = (
    "event_id",
    "event_type",
    "source_event_hour",
    "warning_hour",
    "ground_awareness_hour",
    "spacecraft_awareness_hour",
    "decision_deadline_hour",
    "execution_hour",
    "status",
    "severity",
    "confidence",
    "response_uploaded",
    "response_upload_hour",
    "response_executed",
    "response_skipped",
    "failure_reason",
)

TRANSITION_FIELDS = tuple(field.name for field in fields(LifecycleTransition))

SUMMARY_FIELDS = (
    "policy",
    "scenario",
    "years",
    "seed",
    "event_lifecycle_model",
    "debris_risk_model",
    "autonomy_model",
    "lifecycle_events",
    "warnings_generated",
    "responses_uploaded",
    "responses_executed",
    "responses_skipped",
    "resolved_success",
    "resolved_failed",
    "expired",
    "missed_upload_due_to_no_contact",
    "mean_warning_lead_time_hours",
    "mean_upload_lead_time_hours",
    "survived",
    "loss_reason",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one event-lifecycle warning proxy and write event, "
            "transition, and summary reports"
        )
    )
    parser.add_argument("--years", type=float, default=1.0)
    parser.add_argument("--policy", choices=POLICIES, default="adaptive")
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default=STOCHASTIC_SCENARIO,
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--contact-model",
        choices=("synthetic", "geometry"),
        default="synthetic",
    )
    parser.add_argument(
        "--operator-view",
        choices=OPERATOR_VIEWS,
        default="delayed_telemetry",
    )
    parser.add_argument(
        "--planning-model", choices=PLANNING_MODELS, default="risk_aware"
    )
    parser.add_argument(
        "--maneuver-model",
        choices=MANEUVER_MODELS,
        default="stationkeeping_proxy",
    )
    parser.add_argument(
        "--orbit-evolution-model",
        choices=ORBIT_EVOLUTION_MODELS,
        default="drift_proxy",
    )
    parser.add_argument(
        "--event-lifecycle-model",
        choices=EVENT_LIFECYCLE_MODELS,
        default="warning_proxy",
    )
    parser.add_argument(
        "--debris-risk-model",
        choices=DEBRIS_RISK_MODELS,
        default="legacy",
    )
    parser.add_argument(
        "--autonomy-model", choices=AUTONOMY_MODELS, default="none"
    )
    parser.add_argument(
        "--results-dir", type=Path, default=DEFAULT_RESULTS_DIR
    )
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--max-transitions", type=int)
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if not isfinite(args.years) or args.years < 0.0:
        raise SystemExit("--years must be a finite non-negative number")
    if args.max_transitions is not None and args.max_transitions < 0:
        raise SystemExit("--max-transitions must be non-negative")


def _contact_model(name: str):
    if name == "synthetic":
        return SyntheticContactModel(DEFAULT_CONFIG)
    if name == "geometry":
        return GeometryContactModel(
            default_astana_ground_station(DEFAULT_CONFIG), DEFAULT_CONFIG
        )
    raise ValueError(
        f"Unknown contact model {name!r}; choose one of: geometry, synthetic"
    )


def _plain_value(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _object_row(item: object, fieldnames: Sequence[str]) -> dict[str, object]:
    return {
        field: _plain_value(getattr(item, field))
        for field in fieldnames
    }


def _write_rows(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fieldnames: Sequence[str],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _manager_events(simulator: Simulator) -> list[LifecycleEvent]:
    manager = simulator.lifecycle_manager
    if manager is None:
        return []
    collection = manager.events
    events = (
        list(collection.values())
        if isinstance(collection, Mapping)
        else list(collection)
    )
    return sorted(
        events,
        key=lambda event: (event.source_event_hour, event.event_id),
    )


def _status_name(event: LifecycleEvent) -> str:
    return str(_plain_value(event.status))


def _transition_status(transition: LifecycleTransition) -> str:
    return str(_plain_value(transition.new_status))


def _mean_or_none(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None


def build_lifecycle_summary(
    *,
    policy: str,
    scenario: str,
    years: float,
    seed: int,
    event_lifecycle_model: str,
    events: Sequence[LifecycleEvent],
    transitions: Sequence[LifecycleTransition],
    state: object,
    debris_risk_model: str = "legacy",
    autonomy_model: str = "none",
) -> dict[str, object]:
    """Build one aggregate row from complete, untruncated lifecycle data."""

    warning_event_ids = {
        transition.event_id
        for transition in transitions
        if _transition_status(transition) == "warned"
    }
    warning_leads = [
        float(event.execution_hour - event.warning_hour)
        for event in events
        if event.event_id in warning_event_ids
    ]
    upload_leads = [
        float(event.execution_hour - event.response_upload_hour)
        for event in events
        if event.response_uploaded and event.response_upload_hour is not None
    ]
    loss_reason = getattr(state, "loss_reason", None)
    return {
        "policy": policy,
        "scenario": scenario,
        "years": years,
        "seed": seed,
        "event_lifecycle_model": event_lifecycle_model,
        "debris_risk_model": debris_risk_model,
        "autonomy_model": autonomy_model,
        "lifecycle_events": len(events),
        "warnings_generated": len(warning_event_ids),
        "responses_uploaded": sum(event.response_uploaded for event in events),
        "responses_executed": sum(event.response_executed for event in events),
        "responses_skipped": sum(event.response_skipped for event in events),
        "resolved_success": sum(
            _status_name(event) == "resolved_success" for event in events
        ),
        "resolved_failed": sum(
            _status_name(event) == "resolved_failed" for event in events
        ),
        "expired": sum(_status_name(event) == "expired" for event in events),
        "missed_upload_due_to_no_contact": sum(
            event.failure_reason == "no_command_upload_before_tca"
            for event in events
        ),
        "mean_warning_lead_time_hours": _mean_or_none(warning_leads),
        "mean_upload_lead_time_hours": _mean_or_none(upload_leads),
        "survived": bool(getattr(state, "alive")),
        "loss_reason": _plain_value(loss_reason),
    }


def _write_summary_markdown(
    path: Path, summary: Mapping[str, object]
) -> None:
    missed = int(summary["missed_upload_due_to_no_contact"])
    if missed:
        contact_sentence = (
            f"Communication gaps prevented response upload before TCA for "
            f"**{missed}** lifecycle event(s)."
        )
    else:
        contact_sentence = (
            "No lifecycle event recorded a missed upload caused by the absence "
            "of command contact before TCA."
        )
    outcome = "survived" if summary["survived"] else "failed"
    loss_reason = summary["loss_reason"] or "none"
    markdown = f"""# Event lifecycle summary

- Policy: `{summary['policy']}`
- Scenario: `{summary['scenario']}`
- Requested duration: `{float(summary['years']):g}` years
- Lifecycle model: `{summary['event_lifecycle_model']}`
- Debris risk model: `{summary['debris_risk_model']}`
- Autonomy model: `{summary['autonomy_model']}`
- Lifecycle events: `{summary['lifecycle_events']}`
- Warnings generated: `{summary['warnings_generated']}`
- Responses uploaded: `{summary['responses_uploaded']}`
- Responses executed: `{summary['responses_executed']}`
- Responses skipped: `{summary['responses_skipped']}`
- Outcome: **{outcome}** (loss reason: `{loss_reason}`)

## Communication outcome

{contact_sentence}

## Limitations

This is a deterministic information-flow and command-upload proxy.
It is not real conjunction assessment or real collision probability. It is not
CARA, STK, GMAT, flight software, or KazEOSat-1 operational logic. External
lifecycle warnings do not refresh delayed spacecraft telemetry. Debris size,
velocity, impact-zone and physical-severity modeling are outside V3.2A.
"""
    path.write_text(markdown, encoding="utf-8")


def run_event_lifecycle_report(
    *,
    years: float,
    policy: str,
    scenario: str,
    seed: int,
    contact_model: str,
    operator_view: str,
    planning_model: str,
    maneuver_model: str,
    orbit_evolution_model: str,
    event_lifecycle_model: str,
    results_dir: Path,
    debris_risk_model: str = "legacy",
    autonomy_model: str = "none",
    summary_only: bool = False,
    max_transitions: int | None = None,
    event_catalog: EventCatalog | None = None,
    write_outputs: bool = True,
) -> tuple[
    object,
    list[LifecycleEvent],
    list[LifecycleTransition],
    dict[str, object],
]:
    """Run and write one lifecycle report.

    ``event_catalog`` is an explicit integration/test input.  The CLI normally
    generates the seeded stochastic catalog itself.  Transition truncation is
    applied only while writing; returned transitions and summary counts always
    cover the complete run. ``write_outputs=False`` supports compact callers
    such as the lifecycle seed finder without creating per-seed report trees.
    """

    total_hours = int(round(years * DEFAULT_CONFIG.hours_per_year))
    catalog = event_catalog
    if catalog is None and scenario == STOCHASTIC_SCENARIO:
        catalog = generate_stochastic_event_catalog(
            seed, STOCHASTIC_SCENARIO, total_hours, DEFAULT_CONFIG
        )
    scenario_model = make_scenario(
        scenario,
        DEFAULT_CONFIG,
        seed=seed if scenario == STOCHASTIC_SCENARIO else None,
        total_hours=total_hours,
        event_catalog=catalog,
    )
    simulator = Simulator(
        make_policy(policy, DEFAULT_CONFIG),
        scenario_model,
        DEFAULT_CONFIG,
        contact_model=_contact_model(contact_model),
        operator_view=operator_view,
        planning_model=planning_model,
        maneuver_model=maneuver_model,
        orbit_evolution_model=orbit_evolution_model,
        event_lifecycle_model=event_lifecycle_model,
        debris_risk_model=debris_risk_model,
        autonomy_model=autonomy_model,
    )
    transitions: list[LifecycleTransition] = []
    result = simulator.run(
        years, on_lifecycle_transition=transitions.append
    )
    events = _manager_events(simulator)
    summary = build_lifecycle_summary(
        policy=policy,
        scenario=scenario,
        years=years,
        seed=seed,
        event_lifecycle_model=event_lifecycle_model,
        events=events,
        transitions=transitions,
        state=result.state,
        debris_risk_model=debris_risk_model,
        autonomy_model=autonomy_model,
    )

    if write_outputs:
        results_dir.mkdir(parents=True, exist_ok=True)
        _write_rows(
            results_dir / "event_lifecycle_events.csv",
            [_object_row(event, EVENT_FIELDS) for event in events],
            EVENT_FIELDS,
        )
        transition_path = results_dir / TRANSITIONS_FILE
        if summary_only:
            if transition_path.is_file():
                transition_path.unlink()
        else:
            selected_transitions = (
                transitions
                if max_transitions is None
                else transitions[:max_transitions]
            )
            _write_rows(
                transition_path,
                [
                    _object_row(transition, TRANSITION_FIELDS)
                    for transition in selected_transitions
                ],
                TRANSITION_FIELDS,
            )
        _write_rows(
            results_dir / "event_lifecycle_summary.csv",
            [summary],
            SUMMARY_FIELDS,
        )
        _write_summary_markdown(
            results_dir / "event_lifecycle_summary.md", summary
        )
    return result, events, transitions, summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    result, events, transitions, summary = run_event_lifecycle_report(
        years=args.years,
        policy=args.policy,
        scenario=args.scenario,
        seed=args.seed,
        contact_model=args.contact_model,
        operator_view=args.operator_view,
        planning_model=args.planning_model,
        maneuver_model=args.maneuver_model,
        orbit_evolution_model=args.orbit_evolution_model,
        event_lifecycle_model=args.event_lifecycle_model,
        debris_risk_model=args.debris_risk_model,
        autonomy_model=args.autonomy_model,
        results_dir=args.results_dir,
        summary_only=args.summary_only,
        max_transitions=args.max_transitions,
    )
    print(
        "Event lifecycle report complete: "
        f"events={len(events)}, transitions={len(transitions)}, "
        f"uploaded={summary['responses_uploaded']}, "
        f"survived={result.state.alive}."
    )
    print(f"Outputs: {args.results_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
