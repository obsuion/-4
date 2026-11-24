"""Find reproducible seeds with non-empty V3.2 lifecycle demonstrations."""

from __future__ import annotations

import argparse
import csv
from math import isfinite
from pathlib import Path

from event_lifecycle_report import run_event_lifecycle_report
from ops_sim.autonomy import AUTONOMY_MODELS
from ops_sim.debris_risk import DEBRIS_RISK_MODELS
from ops_sim.policies import POLICIES
from ops_sim.scenarios import SCENARIOS
from ops_sim.simulator import (
    EVENT_LIFECYCLE_MODELS,
    MANEUVER_MODELS,
    OPERATOR_VIEWS,
    ORBIT_EVOLUTION_MODELS,
    PLANNING_MODELS,
)


DEFAULT_RESULTS_DIR = Path("results/lifecycle_seed_finder")
STOCHASTIC_SCENARIO = "stochastic_post_life_events"
OUTPUT_FIELDS = (
    "seed",
    "survived",
    "loss_reason",
    "lifecycle_events",
    "warnings_generated",
    "responses_uploaded",
    "responses_executed",
    "responses_skipped",
    "resolved_success",
    "resolved_failed",
    "missed_upload_due_to_no_contact",
    "first_warning_hour",
    "first_execution_hour",
    "score",
    "final_health",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find bounded, reproducible seeds with lifecycle warnings"
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
        default="legacy",
    )
    parser.add_argument(
        "--autonomy-model", choices=AUTONOMY_MODELS, default="none"
    )
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--seed-count", type=int, default=100)
    parser.add_argument(
        "--results-dir", type=Path, default=DEFAULT_RESULTS_DIR
    )
    parser.add_argument("--min-warnings", type=int, default=1)
    parser.add_argument("--stop-after-first", action="store_true")
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if not isfinite(args.years) or args.years < 0.0:
        raise SystemExit("--years must be a finite non-negative number")
    if args.seed_count <= 0:
        raise SystemExit("--seed-count must be a positive integer")
    if args.min_warnings < 0:
        raise SystemExit("--min-warnings must be non-negative")


def _plain_loss_reason(result: object) -> str:
    loss_reason = result.state.loss_reason
    return loss_reason.value if loss_reason is not None else ""


def find_lifecycle_seeds(
    args: argparse.Namespace,
) -> tuple[list[dict[str, object]], int]:
    """Run candidate seeds and return qualifying rows plus seeds examined."""
    found: list[dict[str, object]] = []
    examined = 0
    for seed in range(args.seed_start, args.seed_start + args.seed_count):
        result, events, transitions, summary = run_event_lifecycle_report(
            years=args.years,
            policy=args.policy,
            scenario=args.scenario,
            seed=seed,
            contact_model="synthetic",
            operator_view=args.operator_view,
            planning_model=args.planning_model,
            maneuver_model=args.maneuver_model,
            orbit_evolution_model=args.orbit_evolution_model,
            event_lifecycle_model=args.event_lifecycle_model,
            debris_risk_model=args.debris_risk_model,
            autonomy_model=args.autonomy_model,
            results_dir=args.results_dir,
            summary_only=True,
            write_outputs=False,
        )
        examined += 1
        warnings = int(summary["warnings_generated"])
        if warnings < args.min_warnings:
            continue
        warned_ids = {
            transition.event_id
            for transition in transitions
            if transition.new_status == "warned"
        }
        warning_hours = [
            transition.hour
            for transition in transitions
            if transition.new_status == "warned"
        ]
        execution_hours = [
            event.execution_hour
            for event in events
            if event.event_id in warned_ids
        ]
        found.append({
            "seed": seed,
            "survived": result.state.alive,
            "loss_reason": _plain_loss_reason(result),
            "lifecycle_events": summary["lifecycle_events"],
            "warnings_generated": warnings,
            "responses_uploaded": summary["responses_uploaded"],
            "responses_executed": summary["responses_executed"],
            "responses_skipped": summary["responses_skipped"],
            "resolved_success": summary["resolved_success"],
            "resolved_failed": summary["resolved_failed"],
            "missed_upload_due_to_no_contact": summary[
                "missed_upload_due_to_no_contact"
            ],
            "first_warning_hour": (
                min(warning_hours) if warning_hours else None
            ),
            "first_execution_hour": (
                min(execution_hours) if execution_hours else None
            ),
            "score": result.metrics.score,
            "final_health": result.metrics.final_total_health,
        })
        if args.stop_after_first:
            break
    return found, examined


def _write_results(
    results_dir: Path, rows: list[dict[str, object]]
) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "lifecycle_seed_finder.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    rows, examined = find_lifecycle_seeds(args)
    output = _write_results(args.results_dir, rows)
    print(
        f"Lifecycle seed search complete: examined={examined}, "
        f"qualifying={len(rows)}."
    )
    if rows:
        print(
            "Found seeds: "
            + ", ".join(
                f"{row['seed']} ({row['warnings_generated']} warning(s))"
                for row in rows
            )
        )
    else:
        print("No seeds met the requested warning threshold.")
    print(f"Output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
