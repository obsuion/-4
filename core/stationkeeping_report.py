"""Run one bounded V3.5 stationkeeping/drift-planning report."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from math import isfinite
from pathlib import Path
from typing import Mapping, Sequence

from ops_sim.autonomy import AUTONOMY_MODELS
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.contacts import (
    GeometryContactModel,
    SyntheticContactModel,
    default_astana_ground_station,
)
from ops_sim.debris_risk import DEBRIS_RISK_MODELS
from ops_sim.event_catalog import EventCatalog, generate_stochastic_event_catalog
from ops_sim.policies import POLICIES, make_policy
from ops_sim.scenarios import SCENARIOS, make_scenario
from ops_sim.simulator import (
    EVENT_LIFECYCLE_MODELS,
    HourRecord,
    MANEUVER_MODELS,
    OPERATOR_VIEWS,
    ORBIT_EVOLUTION_MODELS,
    PLANNING_MODELS,
    Simulator,
)
from ops_sim.stationkeeping import STATIONKEEPING_PLANNING_MODELS


DEFAULT_RESULTS_DIR = Path("results/stationkeeping_report")
STOCHASTIC_SCENARIO = "stochastic_post_life_events"

TRACE_FIELDS = (
    "hour",
    "year",
    "mode",
    "planned_mode",
    "stationkeeping_planning_model",
    "stationkeeping_drift_risk_class_this_hour",
    "stationkeeping_priority_this_hour",
    "stationkeeping_recommended_this_hour",
    "stationkeeping_feasible_this_hour",
    "stationkeeping_selected_this_hour",
    "stationkeeping_reason_this_hour",
    "stationkeeping_deferred_reason_this_hour",
    "stationkeeping_blocked_by_priority_this_hour",
    "maneuver_executed_this_hour",
    "maneuver_skipped_this_hour",
    "maneuver_delta_v_used_this_hour",
    "orbit_drift_proxy_km",
    "orbit_drift_warning",
    "orbit_drift_critical",
    "orbit_geometry_degraded",
    "orbit_groundtrack_error_km",
    "orbit_phase_error_deg",
    "delta_v_remaining_m_per_s",
    "effective_energy_margin",
    "propulsion_health",
    "base_cmd_contact_min",
    "base_data_contact_min",
    "cmd_contact_min",
    "data_contact_min",
    "telemetry_updated_this_hour",
    "telemetry_age_hours",
    "debris_avoidance_required_this_hour",
    "debris_avoidance_executed_this_hour",
)

SUMMARY_FIELDS = (
    "policy",
    "scenario",
    "years",
    "seed",
    "contact_model",
    "operator_view",
    "planning_model",
    "maneuver_model",
    "orbit_evolution_model",
    "stationkeeping_planning_model",
    "stationkeeping_recommended_count",
    "stationkeeping_selected_count",
    "stationkeeping_deferred_count",
    "stationkeeping_unresolved_critical_drift_hours",
    "max_orbit_drift_proxy_km",
    "max_orbit_groundtrack_error_km",
    "max_orbit_phase_error_deg",
    "maneuver_count",
    "final_orbit_drift_proxy_km",
    "final_delta_v_remaining_m_per_s",
    "survived",
    "loss_reason",
    "score",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write bounded stationkeeping and drift-planning diagnostics"
    )
    parser.add_argument("--years", type=float, default=1.0)
    parser.add_argument("--policy", choices=POLICIES, default="adaptive")
    parser.add_argument("--scenario", choices=SCENARIOS, default="nominal")
    parser.add_argument(
        "--contact-model",
        choices=("synthetic", "geometry"),
        default="geometry",
    )
    parser.add_argument(
        "--operator-view", choices=OPERATOR_VIEWS,
        default="delayed_telemetry",
    )
    parser.add_argument(
        "--planning-model", choices=PLANNING_MODELS, default="risk_aware"
    )
    parser.add_argument(
        "--maneuver-model", choices=MANEUVER_MODELS,
        default="stationkeeping_proxy",
    )
    parser.add_argument(
        "--orbit-evolution-model", choices=ORBIT_EVOLUTION_MODELS,
        default="drift_proxy",
    )
    parser.add_argument(
        "--stationkeeping-planning-model",
        choices=STATIONKEEPING_PLANNING_MODELS,
        default="drift_aware",
    )
    parser.add_argument(
        "--event-lifecycle-model", choices=EVENT_LIFECYCLE_MODELS,
        default="none",
    )
    parser.add_argument(
        "--debris-risk-model", choices=DEBRIS_RISK_MODELS,
        default="legacy",
    )
    parser.add_argument(
        "--autonomy-model", choices=AUTONOMY_MODELS, default="none"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--results-dir", type=Path, default=DEFAULT_RESULTS_DIR
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if not isfinite(args.years) or args.years < 0.0:
        raise SystemExit("--years must be a finite non-negative number")


def _contact_model(name: str):
    if name == "synthetic":
        return SyntheticContactModel(DEFAULT_CONFIG)
    return GeometryContactModel(
        default_astana_ground_station(DEFAULT_CONFIG), DEFAULT_CONFIG
    )


def _write_rows(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fieldnames: Sequence[str],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(
    path: Path,
    summary: Mapping[str, object],
    records: Sequence[HourRecord],
) -> None:
    deferred = Counter(
        record.stationkeeping_deferred_reason_this_hour
        for record in records
        if record.stationkeeping_deferred_reason_this_hour is not None
    )
    deferred_text = (
        ", ".join(
            f"`{reason}` ({count})"
            for reason, count in deferred.most_common(3)
        )
        if deferred else "none"
    )
    outcome = "survived" if summary["survived"] else "failed"
    markdown = f"""# Stationkeeping and drift-planning summary

- Policy/scenario: `{summary['policy']}` / `{summary['scenario']}`
- Requested duration: `{float(summary['years']):g}` years
- Planning selector: `{summary['stationkeeping_planning_model']}`
- Recommended/selected/deferred: `{summary['stationkeeping_recommended_count']}` / `{summary['stationkeeping_selected_count']}` / `{summary['stationkeeping_deferred_count']}`
- Unresolved critical-drift hours: `{summary['stationkeeping_unresolved_critical_drift_hours']}`
- Maximum drift: `{float(summary['max_orbit_drift_proxy_km']):.6g}` km
- Common defer reasons: {deferred_text}
- Outcome: **{outcome}**

## Model boundary

This is a bounded stationkeeping/drift-planning proxy. It is not real
stationkeeping or flight dynamics. It does not add TLE/SGP4 propagation, J2 or
atmospheric-drag modeling, or operational KazEOSat-1 logic. It reuses the
existing maneuver, delta-v, drift-correction, and geometry paths without adding
orbital physics.

Geometry + `drift_proxy` is the final research direction. Synthetic contacts
remain baseline/regression controls only. Drift-aware planning does not refresh
delayed telemetry, inspect future event catalogs, or bypass emergency, critical
energy, or uploaded debris-response priorities.
"""
    path.write_text(markdown, encoding="utf-8")


def run_stationkeeping_report(
    *,
    years: float,
    policy: str,
    scenario: str,
    contact_model: str,
    operator_view: str,
    planning_model: str,
    maneuver_model: str,
    orbit_evolution_model: str,
    stationkeeping_planning_model: str,
    event_lifecycle_model: str,
    debris_risk_model: str,
    autonomy_model: str,
    seed: int,
    results_dir: Path,
    event_catalog: EventCatalog | None = None,
):
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
        contact_model=_contact_model(contact_model),
        operator_view=operator_view,
        planning_model=planning_model,
        maneuver_model=maneuver_model,
        orbit_evolution_model=orbit_evolution_model,
        stationkeeping_planning_model=stationkeeping_planning_model,
        event_lifecycle_model=event_lifecycle_model,
        debris_risk_model=debris_risk_model,
        autonomy_model=autonomy_model,
    )
    records: list[HourRecord] = []
    result = simulator.run(years, on_hour=records.append)
    loss_reason = result.state.loss_reason
    summary: dict[str, object] = {
        "policy": policy,
        "scenario": scenario,
        "years": years,
        "seed": seed,
        "contact_model": contact_model,
        "operator_view": operator_view,
        "planning_model": planning_model,
        "maneuver_model": maneuver_model,
        "orbit_evolution_model": orbit_evolution_model,
        "stationkeeping_planning_model": stationkeeping_planning_model,
        "stationkeeping_recommended_count": (
            result.stationkeeping_recommended_count
        ),
        "stationkeeping_selected_count": result.stationkeeping_selected_count,
        "stationkeeping_deferred_count": result.stationkeeping_deferred_count,
        "stationkeeping_unresolved_critical_drift_hours": (
            result.stationkeeping_unresolved_critical_drift_hours
        ),
        "max_orbit_drift_proxy_km": result.max_orbit_drift_proxy_km,
        "max_orbit_groundtrack_error_km": (
            result.max_orbit_groundtrack_error_km
        ),
        "max_orbit_phase_error_deg": result.max_orbit_phase_error_deg,
        "maneuver_count": result.state.maneuver_count,
        "final_orbit_drift_proxy_km": result.state.orbit_drift_proxy_km,
        "final_delta_v_remaining_m_per_s": (
            result.state.delta_v_remaining_m_per_s
        ),
        "survived": result.state.alive,
        "loss_reason": loss_reason.value if loss_reason is not None else "",
        "score": result.metrics.score,
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(
        results_dir / "stationkeeping_trace.csv",
        [{field: getattr(record, field) for field in TRACE_FIELDS}
         for record in records],
        TRACE_FIELDS,
    )
    _write_rows(
        results_dir / "stationkeeping_summary.csv",
        [summary],
        SUMMARY_FIELDS,
    )
    _write_markdown(
        results_dir / "stationkeeping_summary.md", summary, records
    )
    return result, records, summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    result, records, summary = run_stationkeeping_report(
        years=args.years,
        policy=args.policy,
        scenario=args.scenario,
        contact_model=args.contact_model,
        operator_view=args.operator_view,
        planning_model=args.planning_model,
        maneuver_model=args.maneuver_model,
        orbit_evolution_model=args.orbit_evolution_model,
        stationkeeping_planning_model=args.stationkeeping_planning_model,
        event_lifecycle_model=args.event_lifecycle_model,
        debris_risk_model=args.debris_risk_model,
        autonomy_model=args.autonomy_model,
        seed=args.seed,
        results_dir=args.results_dir,
    )
    print(
        "Stationkeeping report complete: "
        f"hours={len(records)}, "
        f"selected={summary['stationkeeping_selected_count']}, "
        f"survived={result.state.alive}."
    )
    print(f"Outputs: {args.results_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
