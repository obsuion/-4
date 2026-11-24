"""Run one bounded V3.4 onboard-autonomy proxy report."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from math import isfinite
from pathlib import Path
from typing import Mapping, Sequence

from ops_sim.autonomy import AUTONOMY_MODELS
from ops_sim.config import DEFAULT_CONFIG
from ops_sim.contacts import SyntheticContactModel
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


DEFAULT_RESULTS_DIR = Path("results/autonomy_report")
STOCHASTIC_SCENARIO = "stochastic_post_life_events"

TRACE_FIELDS = (
    "hour",
    "year",
    "mode",
    "planned_mode",
    "autonomy_model",
    "autonomy_active_this_hour",
    "autonomy_trigger_this_hour",
    "autonomy_authority_this_hour",
    "autonomy_selected_mode_this_hour",
    "autonomy_reason_this_hour",
    "autonomy_pre_authorized_this_hour",
    "autonomy_ground_contact_required_this_hour",
    "autonomy_used_uploaded_response_this_hour",
    "contingency_plan_active",
    "contingency_plan_age_hours",
    "contingency_plan_expires_in_hours",
    "soc",
    "health",
    "effective_energy_margin",
    "thermal_health",
    "payload_health",
    "buffer_gb",
    "cmd_contact_min",
    "data_contact_min",
    "event_lifecycle_model",
    "debris_risk_model",
    "debris_conjunction_active",
    "debris_avoidance_required_this_hour",
    "debris_avoidance_executed_this_hour",
    "debris_avoidance_skipped_this_hour",
)

SUMMARY_FIELDS = (
    "policy",
    "scenario",
    "years",
    "seed",
    "autonomy_model",
    "event_lifecycle_model",
    "debris_risk_model",
    "autonomous_action_count",
    "autonomous_safe_mode_count",
    "autonomous_standby_count",
    "autonomous_downlink_count",
    "autonomous_maneuver_count",
    "contingency_plan_upload_count",
    "contingency_plan_expired_count",
    "survived",
    "loss_reason",
    "final_health",
    "score",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one bounded simulation and write onboard-autonomy proxy "
            "diagnostics"
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
        "--autonomy-model",
        choices=AUTONOMY_MODELS,
        default="contingency_plan",
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


def _trace_row(record: HourRecord) -> dict[str, object]:
    return {field: getattr(record, field) for field in TRACE_FIELDS}


def _write_summary_markdown(
    path: Path,
    summary: Mapping[str, object],
    records: Sequence[HourRecord],
) -> None:
    triggers = Counter(
        record.autonomy_trigger_this_hour
        for record in records
        if record.autonomy_active_this_hour
        and record.autonomy_trigger_this_hour is not None
    )
    trigger_text = (
        ", ".join(f"`{name}` ({count})" for name, count in triggers.most_common(3))
        if triggers else "none"
    )
    outcome = "survived" if summary["survived"] else "failed"
    loss_reason = summary["loss_reason"] or "none"
    markdown = f"""# Onboard autonomy summary

- Policy: `{summary['policy']}`
- Scenario: `{summary['scenario']}`
- Requested duration: `{float(summary['years']):g}` years
- Autonomy model: `{summary['autonomy_model']}`
- Autonomous actions: `{summary['autonomous_action_count']}`
- Autonomous SAFE/STANDBY/DOWNLINK/MANEUVER: `{summary['autonomous_safe_mode_count']}` / `{summary['autonomous_standby_count']}` / `{summary['autonomous_downlink_count']}` / `{summary['autonomous_maneuver_count']}`
- Contingency plans uploaded/expired: `{summary['contingency_plan_upload_count']}` / `{summary['contingency_plan_expired_count']}`
- Common triggers: {trigger_text}
- Outcome: **{outcome}** (loss reason: `{loss_reason}`)

## Model boundary

This is a bounded onboard-autonomy proxy. It is not real flight software, real
FDIR, or onboard AI. It does not know future external events and it does not refresh delayed telemetry. It does not turn a ground-only warning into
spacecraft knowledge. Decisions use only current real onboard state, current
contact, current stored authority, and already uploaded/pre-authorized
spacecraft awareness. Autonomy is layered on top of the existing daily-plan ->
BACKUP -> EMERGENCY_BEACON ladder; it does not replace that ladder, and
EMERGENCY_BEACON remains the terminal no-contact fallback. The local
`no_contact_timeout` diagnostic is not the 14-day emergency mechanism. This is
not KazEOSat-1 operational logic.
"""
    path.write_text(markdown, encoding="utf-8")


def run_autonomy_report(
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
    autonomy_model: str,
    seed: int,
    results_dir: Path,
    event_catalog: EventCatalog | None = None,
) -> tuple[object, list[HourRecord], dict[str, object]]:
    """Run one bounded configuration and write all autonomy diagnostics."""
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
    records: list[HourRecord] = []
    result = simulator.run(years, on_hour=records.append)
    loss_reason = result.state.loss_reason
    summary: dict[str, object] = {
        "policy": policy,
        "scenario": scenario,
        "years": years,
        "seed": seed,
        "autonomy_model": autonomy_model,
        "event_lifecycle_model": event_lifecycle_model,
        "debris_risk_model": debris_risk_model,
        "autonomous_action_count": result.autonomous_action_count,
        "autonomous_safe_mode_count": result.autonomous_safe_mode_count,
        "autonomous_standby_count": result.autonomous_standby_count,
        "autonomous_downlink_count": result.autonomous_downlink_count,
        "autonomous_maneuver_count": result.autonomous_maneuver_count,
        "contingency_plan_upload_count": (
            result.contingency_plan_upload_count
        ),
        "contingency_plan_expired_count": (
            result.contingency_plan_expired_count
        ),
        "survived": result.state.alive,
        "loss_reason": loss_reason.value if loss_reason is not None else "",
        "final_health": result.metrics.final_total_health,
        "score": result.metrics.score,
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(
        results_dir / "autonomy_trace.csv",
        [_trace_row(record) for record in records],
        TRACE_FIELDS,
    )
    _write_rows(
        results_dir / "autonomy_summary.csv",
        [summary],
        SUMMARY_FIELDS,
    )
    _write_summary_markdown(
        results_dir / "autonomy_summary.md", summary, records
    )
    return result, records, summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    result, records, summary = run_autonomy_report(
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
        "Autonomy report complete: "
        f"hours={len(records)}, actions={summary['autonomous_action_count']}, "
        f"survived={result.state.alive}."
    )
    print(f"Outputs: {args.results_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
