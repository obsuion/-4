"""Run one bounded V3.3 synthetic debris-risk assessment report."""

from __future__ import annotations

import argparse
import csv
from math import isfinite
from pathlib import Path
from typing import Mapping, Sequence

from ops_sim.autonomy import AUTONOMY_MODELS
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.contacts import SyntheticContactModel
from ops_sim.debris_risk import (
    DEBRIS_RISK_MODELS,
    assess_debris_risk,
)
from ops_sim.event_catalog import (
    EventCatalog,
    ExternalEvent,
    generate_stochastic_event_catalog,
)
from ops_sim.event_lifecycle import LifecycleEvent
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


DEFAULT_RESULTS_DIR = Path("results/debris_risk_report")
STOCHASTIC_SCENARIO = "stochastic_post_life_events"

EVENT_FIELDS = (
    "seed",
    "event_id",
    "source_event_hour",
    "warning_hour",
    "execution_hour",
    "object_size_cm",
    "relative_velocity_km_s",
    "miss_distance_proxy_m",
    "warning_confidence",
    "risk_score",
    "risk_class",
    "impact_zone",
    "damage_targets",
    "damage_effect",
    "recommended_response",
    "response_uploaded",
    "response_executed",
    "response_skipped",
    "failure_reason",
)

SUMMARY_FIELDS = (
    "policy",
    "scenario",
    "years",
    "seed",
    "debris_risk_model",
    "event_lifecycle_model",
    "autonomy_model",
    "debris_events",
    "high_or_severe_events",
    "severe_events",
    "max_risk_score",
    "responses_uploaded",
    "responses_executed",
    "responses_skipped",
    "damage_events",
    "survived",
    "loss_reason",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one bounded simulation and report synthetic debris-risk "
            "assessments"
        )
    )
    parser.add_argument("--years", type=float, default=15.0)
    parser.add_argument(
        "--policy", choices=POLICIES, default="survival_first"
    )
    parser.add_argument(
        "--scenario", choices=SCENARIOS, default=STOCHASTIC_SCENARIO
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
        default="severity_proxy",
    )
    parser.add_argument(
        "--autonomy-model", choices=AUTONOMY_MODELS, default="none"
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--results-dir", type=Path, default=DEFAULT_RESULTS_DIR
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if not isfinite(args.years) or args.years < 0.0:
        raise SystemExit("--years must be a finite non-negative number")


def _write_rows(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fieldnames: Sequence[str],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _debris_events(catalog: EventCatalog | None) -> tuple[ExternalEvent, ...]:
    if catalog is None:
        return ()
    return tuple(
        event
        for event in catalog.events
        if event.event_type.lower() == "debris_conjunction"
    )


def _lifecycle_by_source(
    simulator: Simulator,
) -> dict[int, LifecycleEvent]:
    manager = simulator.lifecycle_manager
    if manager is None:
        return {}
    return {
        id(manager.source_event(event.event_id)): event
        for event in manager.events
    }


def _assessment_row(
    *,
    seed: int,
    event: ExternalEvent,
    lifecycle_event: LifecycleEvent | None,
) -> dict[str, object]:
    event_id = lifecycle_event.event_id if lifecycle_event is not None else None
    assessment = assess_debris_risk(event, event_id)
    return {
        "seed": seed,
        "event_id": assessment.event_id,
        "source_event_hour": assessment.source_event_hour,
        "warning_hour": (
            lifecycle_event.warning_hour
            if lifecycle_event is not None else None
        ),
        "execution_hour": (
            lifecycle_event.execution_hour
            if lifecycle_event is not None else event.hour
        ),
        "object_size_cm": assessment.object_size_cm,
        "relative_velocity_km_s": assessment.relative_velocity_km_s,
        "miss_distance_proxy_m": assessment.miss_distance_proxy_m,
        "warning_confidence": assessment.warning_confidence,
        "risk_score": assessment.risk_score,
        "risk_class": assessment.risk_class,
        "impact_zone": assessment.impact_zone,
        "damage_targets": ",".join(assessment.damage_targets),
        "damage_effect": assessment.damage_effect,
        "recommended_response": assessment.recommended_response,
        "response_uploaded": (
            lifecycle_event.response_uploaded
            if lifecycle_event is not None else False
        ),
        "response_executed": (
            lifecycle_event.response_executed
            if lifecycle_event is not None else False
        ),
        "response_skipped": (
            lifecycle_event.response_skipped
            if lifecycle_event is not None else False
        ),
        "failure_reason": (
            lifecycle_event.failure_reason
            if lifecycle_event is not None else None
        ),
    }


def _write_summary_markdown(
    path: Path, summary: Mapping[str, object]
) -> None:
    outcome = "survived" if summary["survived"] else "failed"
    loss_reason = summary["loss_reason"] or "none"
    markdown = f"""# Debris risk summary

- Policy: `{summary['policy']}`
- Scenario: `{summary['scenario']}`
- Requested duration: `{float(summary['years']):g}` years
- Debris risk model: `{summary['debris_risk_model']}`
- Lifecycle model: `{summary['event_lifecycle_model']}`
- Autonomy model: `{summary['autonomy_model']}`
- Debris events assessed: `{summary['debris_events']}`
- High or severe events: `{summary['high_or_severe_events']}`
- Severe events: `{summary['severe_events']}`
- Responses uploaded/executed/skipped: `{summary['responses_uploaded']}` / `{summary['responses_executed']}` / `{summary['responses_skipped']}`
- Failed-avoidance damage events: `{summary['damage_events']}`
- Outcome: **{outcome}** (loss reason: `{loss_reason}`)

## Model boundary

This is a synthetic debris risk assessment. `risk_score` is not real collision
probability. Object size, relative velocity, miss distance, and impact zone are
deterministic proxy values, not observations or orbit-determination products.

V3.2A handles the warning, ground-awareness, command-upload, spacecraft-awareness,
TCA, and resolution lifecycle. V3.3 only characterizes debris risk and maps a
failed avoidance into impact-zone health damage. It is not CARA, real conjunction
screening, covariance analysis, TLE/SGP4 propagation, STK, GMAT, flight software,
onboard autonomy, or KazEOSat-1 operational logic.
"""
    path.write_text(markdown, encoding="utf-8")


def run_debris_risk_report(
    *,
    years: float,
    policy: str,
    scenario: str,
    operator_view: str,
    planning_model: str,
    maneuver_model: str,
    orbit_evolution_model: str,
    event_lifecycle_model: str,
    debris_risk_model: str,
    autonomy_model: str = "none",
    seed: int,
    results_dir: Path,
    event_catalog: EventCatalog | None = None,
) -> tuple[object, list[dict[str, object]], dict[str, object]]:
    """Run one simulation and write complete, bounded V3.3 risk outputs."""

    total_hours = int(round(years * DEFAULT_CONFIG.hours_per_year))
    catalog = event_catalog
    if catalog is None and scenario == STOCHASTIC_SCENARIO:
        catalog = generate_stochastic_event_catalog(
            seed, scenario, total_hours, DEFAULT_CONFIG
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
        contact_model=SyntheticContactModel(DEFAULT_CONFIG),
        operator_view=operator_view,
        planning_model=planning_model,
        maneuver_model=maneuver_model,
        orbit_evolution_model=orbit_evolution_model,
        event_lifecycle_model=event_lifecycle_model,
        debris_risk_model=debris_risk_model,
        autonomy_model=autonomy_model,
    )
    result = simulator.run(years)
    lifecycle_by_source = _lifecycle_by_source(simulator)
    event_rows = [
        _assessment_row(
            seed=seed,
            event=event,
            lifecycle_event=lifecycle_by_source.get(id(event)),
        )
        for event in _debris_events(catalog)
    ]
    loss_reason = result.state.loss_reason
    summary: dict[str, object] = {
        "policy": policy,
        "scenario": scenario,
        "years": years,
        "seed": seed,
        "debris_risk_model": debris_risk_model,
        "event_lifecycle_model": event_lifecycle_model,
        "autonomy_model": autonomy_model,
        "debris_events": len(event_rows),
        "high_or_severe_events": sum(
            row["risk_class"] in ("high", "severe")
            for row in event_rows
        ),
        "severe_events": sum(
            row["risk_class"] == "severe" for row in event_rows
        ),
        "max_risk_score": max(
            (float(row["risk_score"]) for row in event_rows),
            default=0.0,
        ),
        "responses_uploaded": sum(
            bool(row["response_uploaded"]) for row in event_rows
        ),
        "responses_executed": sum(
            bool(row["response_executed"]) for row in event_rows
        ),
        "responses_skipped": sum(
            bool(row["response_skipped"]) for row in event_rows
        ),
        "damage_events": result.state.debris_damage_events,
        "survived": result.state.alive,
        "loss_reason": loss_reason.value if loss_reason is not None else "",
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(
        results_dir / "debris_risk_events.csv",
        event_rows,
        EVENT_FIELDS,
    )
    _write_rows(
        results_dir / "debris_risk_summary.csv",
        [summary],
        SUMMARY_FIELDS,
    )
    _write_summary_markdown(
        results_dir / "debris_risk_summary.md", summary
    )
    return result, event_rows, summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    result, event_rows, summary = run_debris_risk_report(
        years=args.years,
        policy=args.policy,
        scenario=args.scenario,
        operator_view=args.operator_view,
        planning_model=args.planning_model,
        maneuver_model=args.maneuver_model,
        orbit_evolution_model=args.orbit_evolution_model,
        event_lifecycle_model=args.event_lifecycle_model,
        debris_risk_model=args.debris_risk_model,
        autonomy_model=args.autonomy_model,
        seed=args.seed,
        results_dir=args.results_dir,
    )
    print(
        "Debris risk report complete: "
        f"events={len(event_rows)}, "
        f"high_or_severe={summary['high_or_severe_events']}, "
        f"survived={result.state.alive}."
    )
    print(f"Outputs: {args.results_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
