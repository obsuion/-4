"""Command-line runner for simulation-based remaining useful life estimates."""

import argparse
import csv
from dataclasses import fields
from math import isfinite
from pathlib import Path
from typing import Any

import run as experiment_runner
from ops_sim.autonomy import AUTONOMY_MODELS
from ops_sim.config import DEFAULT_CONFIG, SimulationConfig
from ops_sim.debris_risk import DEBRIS_RISK_MODELS
from ops_sim.packets import PACKET_DELIVERY_MODELS, PACKET_MODELS
from ops_sim.policies import POLICIES
from ops_sim.pointing import POINTING_MODELS
from ops_sim.power import POWER_MODELS
from ops_sim.reliability import (
    DEFAULT_BOOTSTRAP_REPLICATES,
    DEFAULT_BOOTSTRAP_SEED,
    CensoredSurvivorRiskDistributionRow,
    ConditionalRULSummary,
    ConditionalSurvivalCurvePoint,
    FailureModeDistributionRow,
    build_censored_survivor_risk_distribution,
    build_conditional_survival_curve,
    build_failure_mode_distribution,
    summarize_conditional_rul,
)
from ops_sim.rul import estimate_remaining_useful_life
from ops_sim.scenarios import SCENARIOS
from ops_sim.stationkeeping import STATIONKEEPING_PLANNING_MODELS
from ops_sim.targets import TARGET_MODELS
from ops_sim.thermal import THERMAL_MODELS
from ops_sim.simulator import (
    EVENT_LIFECYCLE_MODELS,
    MANEUVER_MODELS,
    OPERATOR_VIEWS,
    ORBIT_EVOLUTION_MODELS,
    PLANNING_MODELS,
)


DEFAULT_RESULTS_DIR = Path("results/rul")


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone RUL CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Estimate simulation-based, horizon-censored remaining useful life"
        )
    )
    parser.add_argument("--start-year", type=float, default=8.0)
    parser.add_argument("--horizon-years", type=float, default=5.0)
    parser.add_argument("--samples", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--policy", choices=[*POLICIES, "all"], default="adaptive")
    parser.add_argument(
        "--scenario", choices=[*SCENARIOS, "all"], default="nominal"
    )
    parser.add_argument(
        "--contact-model",
        choices=("synthetic", "geometry"),
        default="synthetic",
    )
    parser.add_argument(
        "--operator-view", choices=OPERATOR_VIEWS, default="omniscient"
    )
    parser.add_argument(
        "--planning-model", choices=PLANNING_MODELS, default="reactive"
    )
    parser.add_argument(
        "--maneuver-model", choices=MANEUVER_MODELS, default="none"
    )
    parser.add_argument(
        "--orbit-evolution-model",
        choices=ORBIT_EVOLUTION_MODELS,
        default="fixed",
    )
    parser.add_argument(
        "--stationkeeping-planning-model",
        choices=STATIONKEEPING_PLANNING_MODELS,
        default="legacy",
    )
    parser.add_argument(
        "--event-lifecycle-model",
        choices=EVENT_LIFECYCLE_MODELS,
        default="none",
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
        "--power-model", choices=POWER_MODELS, default="legacy"
    )
    parser.add_argument(
        "--thermal-model", choices=THERMAL_MODELS, default="legacy"
    )
    parser.add_argument(
        "--target-model", choices=TARGET_MODELS, default="legacy"
    )
    parser.add_argument(
        "--pointing-model", choices=POINTING_MODELS, default="legacy"
    )
    parser.add_argument(
        "--packet-model", choices=PACKET_MODELS, default="legacy"
    )
    parser.add_argument(
        "--packet-delivery-model",
        choices=PACKET_DELIVERY_MODELS,
        default="ideal",
    )
    parser.add_argument(
        "--packet-drop-fraction-proxy",
        type=float,
        default=DEFAULT_CONFIG.packet_drop_fraction_proxy,
    )
    parser.add_argument(
        "--include-reliability-analysis",
        action="store_true",
        help="write opt-in V3.9B conditional reliability interpretation CSVs",
    )
    parser.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=DEFAULT_BOOTSTRAP_REPLICATES,
    )
    parser.add_argument(
        "--bootstrap-seed",
        type=int,
        default=DEFAULT_BOOTSTRAP_SEED,
    )
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)

    # Keep the geometry surface aligned with run.py. Its action records which
    # defaults were explicitly supplied so synthetic runs can reject them.
    geometry_action = experiment_runner._GeometryOptionAction
    parser.add_argument(
        "--station-lat",
        type=float,
        action=geometry_action,
        help="geometry station latitude in degrees",
    )
    parser.add_argument(
        "--station-lon",
        type=float,
        action=geometry_action,
        help="geometry station longitude in degrees",
    )
    parser.add_argument(
        "--station-name",
        action=geometry_action,
        help="geometry station label (default: astana_proxy or custom_station)",
    )
    parser.add_argument(
        "--minimum-elevation-deg",
        type=float,
        action=geometry_action,
        help="geometry visibility threshold (default: model configuration)",
    )
    parser.add_argument(
        "--geometry-step-seconds", type=int, default=30, action=geometry_action
    )
    parser.add_argument(
        "--command-overhead-seconds", type=int, default=0, action=geometry_action
    )
    parser.add_argument(
        "--data-overhead-seconds", type=int, default=60, action=geometry_action
    )
    parser.add_argument(
        "--min-data-contact-seconds", type=int, default=60, action=geometry_action
    )
    return parser


def build_contact_model(args, config: SimulationConfig = DEFAULT_CONFIG):
    """Delegate contact construction to the normal experiment runner."""
    return experiment_runner.build_contact_model(args, config)


def _validate_args(args: argparse.Namespace) -> None:
    if not isfinite(args.start_year) or args.start_year < 0:
        raise SystemExit("--start-year must be a finite non-negative number")
    if not isfinite(args.horizon_years) or args.horizon_years < 0:
        raise SystemExit("--horizon-years must be a finite non-negative number")
    if args.samples <= 0:
        raise SystemExit("--samples must be a positive integer")
    if args.bootstrap_replicates <= 0:
        raise SystemExit("--bootstrap-replicates must be a positive integer")
    if (
        not isfinite(args.packet_drop_fraction_proxy)
        or not 0.0 <= args.packet_drop_fraction_proxy <= 1.0
    ):
        raise SystemExit("--packet-drop-fraction-proxy must be in [0, 1]")
    if (
        args.packet_model == "legacy"
        and args.packet_delivery_model != "ideal"
    ):
        raise SystemExit(
            "--packet-delivery-model loss_retry_proxy requires "
            "--packet-model packet_proxy"
        )

    supplied_geometry_options = getattr(args, "_supplied_geometry_options", set())
    if args.contact_model == "synthetic" and supplied_geometry_options:
        supplied_flags = ", ".join(
            experiment_runner.GEOMETRY_OPTION_FLAGS[dest]
            for dest in sorted(supplied_geometry_options)
        )
        raise SystemExit(f"{supplied_flags} require --contact-model geometry")
    if (args.station_lat is None) != (args.station_lon is None):
        raise SystemExit("--station-lat and --station-lon must be supplied together")


def _selected(value: str, available: dict[str, Any]) -> list[str]:
    return list(available) if value == "all" else [value]


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows available for {path.name}")
    fieldnames = list(rows[0])
    expected_fields = set(fieldnames)
    if any(set(row) != expected_fields for row in rows[1:]):
        raise ValueError(f"Inconsistent columns while writing {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_analysis_rows(
    path: Path,
    rows: list[dict[str, object]],
    row_type: type,
) -> None:
    """Write a typed V3.9B table, including headers when it has no rows."""
    fieldnames = [field.name for field in fields(row_type)]
    expected_fields = set(fieldnames)
    if any(set(row) != expected_fields for row in rows):
        raise ValueError(f"Inconsistent columns while writing {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    try:
        # Validate station coordinates and geometry sampling before starting a
        # potentially expensive sample matrix. Each estimator sample gets a
        # fresh model from the factory below.
        build_contact_model(args, DEFAULT_CONFIG)
    except ValueError as exc:
        raise SystemExit(f"Invalid geometry contact configuration: {exc}") from exc

    policies = _selected(args.policy, POLICIES)
    scenarios = _selected(args.scenario, SCENARIOS)
    args.results_dir.mkdir(parents=True, exist_ok=True)
    sample_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    survival_rows: list[dict[str, object]] = []
    conditional_summary_rows: list[dict[str, object]] = []
    conditional_survival_rows: list[dict[str, object]] = []
    failure_mode_rows: list[dict[str, object]] = []
    survivor_risk_rows: list[dict[str, object]] = []

    def contact_model_factory(config: SimulationConfig):
        return build_contact_model(args, config)

    for policy_name in policies:
        for scenario_name in scenarios:
            samples, summary, survival_curve = estimate_remaining_useful_life(
                policy_name=policy_name,
                scenario_name=scenario_name,
                start_year=args.start_year,
                horizon_years=args.horizon_years,
                samples=args.samples,
                seed=args.seed,
                config=DEFAULT_CONFIG,
                contact_model_name=args.contact_model,
                contact_model_factory=contact_model_factory,
                operator_view=args.operator_view,
                planning_model=args.planning_model,
                maneuver_model=args.maneuver_model,
                orbit_evolution_model=args.orbit_evolution_model,
                stationkeeping_planning_model=(
                    args.stationkeeping_planning_model
                ),
                event_lifecycle_model=args.event_lifecycle_model,
                debris_risk_model=args.debris_risk_model,
                autonomy_model=args.autonomy_model,
                power_model=args.power_model,
                thermal_model=args.thermal_model,
                target_model=args.target_model,
                pointing_model=args.pointing_model,
                packet_model=args.packet_model,
                packet_delivery_model=args.packet_delivery_model,
                packet_drop_fraction_proxy=(
                    args.packet_drop_fraction_proxy
                ),
            )
            sample_rows.extend(sample.as_dict() for sample in samples)
            summary_rows.append(summary.as_dict())
            survival_rows.extend(point.as_dict() for point in survival_curve)
            if args.include_reliability_analysis:
                analysis_options = {
                    "bootstrap_replicates": args.bootstrap_replicates,
                    "bootstrap_seed": args.bootstrap_seed,
                }
                conditional_summary_rows.append(
                    summarize_conditional_rul(
                        samples, **analysis_options
                    ).as_dict()
                )
                conditional_survival_rows.extend(
                    point.as_dict()
                    for point in build_conditional_survival_curve(
                        samples, **analysis_options
                    )
                )
                failure_mode_rows.extend(
                    row.as_dict()
                    for row in build_failure_mode_distribution(
                        samples, **analysis_options
                    )
                )
                survivor_risk_rows.extend(
                    row.as_dict()
                    for row in build_censored_survivor_risk_distribution(
                        samples, **analysis_options
                    )
                )

    _write_rows(args.results_dir / "rul_samples.csv", sample_rows)
    _write_rows(args.results_dir / "rul_summary.csv", summary_rows)
    _write_rows(args.results_dir / "rul_survival_curve.csv", survival_rows)
    if args.include_reliability_analysis:
        _write_analysis_rows(
            args.results_dir / "rul_conditional_summary.csv",
            conditional_summary_rows,
            ConditionalRULSummary,
        )
        _write_analysis_rows(
            args.results_dir / "rul_conditional_survival_curve.csv",
            conditional_survival_rows,
            ConditionalSurvivalCurvePoint,
        )
        _write_analysis_rows(
            args.results_dir / "rul_failure_modes.csv",
            failure_mode_rows,
            FailureModeDistributionRow,
        )
        _write_analysis_rows(
            args.results_dir / "rul_censored_survivor_risk_drivers.csv",
            survivor_risk_rows,
            CensoredSurvivorRiskDistributionRow,
        )
    print(
        f"RUL estimation complete: {len(sample_rows)} samples across "
        f"{len(summary_rows)} policy/scenario combinations."
    )
    print(f"Results written to {args.results_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
