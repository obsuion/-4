"""Run one bounded simulation and write V3.1 decision explanations."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import fields
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
from ops_sim.decision import (
    DecisionExplanation,
    FailureAttribution,
    ModeOptionAssessment,
    RiskSnapshot,
    build_failure_attribution,
)
from ops_sim.debris_risk import DEBRIS_RISK_MODELS
from ops_sim.event_catalog import generate_stochastic_event_catalog
from ops_sim.packets import PACKET_DELIVERY_MODELS, PACKET_MODELS
from ops_sim.policies import POLICIES, make_policy
from ops_sim.pointing import POINTING_MODELS
from ops_sim.power import POWER_MODELS
from ops_sim.scenarios import SCENARIOS, make_scenario
from ops_sim.stationkeeping import STATIONKEEPING_PLANNING_MODELS
from ops_sim.thermal import THERMAL_MODELS
from ops_sim.targets import TARGET_MODELS
from ops_sim.simulator import (
    EVENT_LIFECYCLE_MODELS,
    HourRecord,
    MANEUVER_MODELS,
    OPERATOR_VIEWS,
    ORBIT_EVOLUTION_MODELS,
    PLANNING_MODELS,
    Simulator,
)


DEFAULT_RESULTS_DIR = Path("results/decision_report")
STOCHASTIC_SCENARIO = "stochastic_post_life_events"
TRACE_FILES = (
    "decision_trace.csv",
    "risk_trace.csv",
    "option_assessments.csv",
)
LIFECYCLE_TRACE_FIELDS = (
    "lifecycle_ground_known_count",
    "lifecycle_spacecraft_known_count",
    "lifecycle_uploaded_count",
    "lifecycle_pending_count",
    "lifecycle_active_count",
    "lifecycle_missed_upload_count",
    "lifecycle_next_warning_hour",
    "lifecycle_next_execution_hour",
)
AUTONOMY_TRACE_FIELDS = (
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
)
STATIONKEEPING_TRACE_FIELDS = (
    "stationkeeping_planning_model",
    "stationkeeping_drift_risk_class_this_hour",
    "stationkeeping_priority_this_hour",
    "stationkeeping_recommended_this_hour",
    "stationkeeping_feasible_this_hour",
    "stationkeeping_selected_this_hour",
    "stationkeeping_reason_this_hour",
    "stationkeeping_deferred_reason_this_hour",
    "stationkeeping_blocked_by_priority_this_hour",
)
POWER_TRACE_FIELDS = (
    "power_model",
    "sunlight_factor_this_hour",
    "eclipse_this_hour",
    "eclipse_fraction_reference",
    "power_load_proxy_w_this_hour",
    "power_generation_proxy_w_this_hour",
    "net_power_proxy_w_this_hour",
    "soc_delta_power_model_this_hour",
)
THERMAL_TRACE_FIELDS = (
    "thermal_model",
    "thermal_load_proxy_this_hour",
    "thermal_hot_stress_this_hour",
    "thermal_cold_stress_this_hour",
    "thermal_stress_this_hour",
    "thermal_degradation_this_hour",
    "thermal_reason_this_hour",
)
TARGET_TRACE_FIELDS = (
    "target_model",
    "target_opportunity_this_hour",
    "target_selected_this_hour",
    "target_scene_id_this_hour",
    "target_scene_area_km2_this_hour",
    "target_priority_this_hour",
    "target_imagery_mode_this_hour",
    "target_data_multiplier_this_hour",
    "target_missed_reason_this_hour",
    "target_reason_this_hour",
)
POINTING_TRACE_FIELDS = (
    "pointing_model",
    "pointing_required_this_hour",
    "pointing_quality_this_hour",
    "pointing_multiplier_this_hour",
    "pointing_limited_this_hour",
    "pointing_missed_this_hour",
    "pointing_off_nadir_proxy_deg_this_hour",
    "pointing_slew_proxy_deg_this_hour",
    "pointing_reason_this_hour",
)
PACKET_TRACE_FIELDS = (
    "packet_model",
    "packet_delivery_model",
    "telemetry_packet_generated_this_hour",
    "telemetry_packet_delivery_attempted_this_hour",
    "telemetry_packet_downlinked_this_hour",
    "telemetry_packet_delivery_failed_this_hour",
    "command_packets_attempted_this_hour",
    "command_packets_uploaded_this_hour",
    "command_packets_failed_this_hour",
    "daily_plan_packet_delivery_attempted_this_hour",
    "daily_plan_packet_uploaded_this_hour",
    "daily_plan_packet_delivery_failed_this_hour",
    "packet_uplink_kb_this_hour",
    "packet_downlink_kb_this_hour",
    "packet_reason_this_hour",
    "packet_delivery_reason_this_hour",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one simulation and write transparent decision/risk diagnostics"
        )
    )
    parser.add_argument("--years", type=float, default=1.0)
    parser.add_argument("--policy", choices=POLICIES, default="adaptive")
    parser.add_argument("--scenario", choices=SCENARIOS, default="nominal")
    parser.add_argument("--seed", type=int, default=42)
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
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--summary-only", action="store_true")
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if not isfinite(args.years) or args.years < 0:
        raise SystemExit("--years must be a finite non-negative number")
    if args.max_rows is not None and args.max_rows < 0:
        raise SystemExit("--max-rows must be non-negative")
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


def _counter_text(counter: Counter[str], limit: int = 3) -> str:
    if not counter:
        return "none available"
    return ", ".join(
        f"`{name}` ({count})" for name, count in counter.most_common(limit)
    )


def _write_summary(
    path: Path,
    *,
    explanations: Sequence[DecisionExplanation],
    attribution: FailureAttribution,
    years: float,
    event_lifecycle_model: str,
    debris_risk_model: str,
    power_model: str,
    thermal_model: str,
    target_model: str,
    pointing_model: str,
    packet_model: str,
    lifecycle_summary: Mapping[str, int],
    autonomy_summary: Mapping[str, object],
    stationkeeping_summary: Mapping[str, object],
    thermal_summary: Mapping[str, object],
    target_summary: Mapping[str, object],
    pointing_summary: Mapping[str, object],
    packet_summary: Mapping[str, object],
) -> None:
    risks = Counter(item.main_risk_driver for item in explanations)
    modes = Counter(item.executed_mode for item in explanations)
    reasons = Counter(item.main_reason for item in explanations)
    outcome = "survived" if attribution.survived else "failed"
    failure_text = (
        attribution.short_explanation
        if not attribution.survived
        else (
            "The run survived; the final-window likely bottleneck was "
            f"`{attribution.likely_bottleneck}`."
        )
    )
    if event_lifecycle_model == "none":
        lifecycle_section = """## Lifecycle awareness

The lifecycle model was disabled (`none`) for this report. No external-warning
or response-upload awareness diagnostics were active.
"""
    else:
        lifecycle_section = f"""## Lifecycle awareness

- Lifecycle model: `{event_lifecycle_model}`
- Total lifecycle events: `{lifecycle_summary['lifecycle_events']}`
- Warnings known to ground: `{lifecycle_summary['ground_known']}`
- Responses uploaded to spacecraft: `{lifecycle_summary['uploaded']}`
- Missed uploads before TCA: `{lifecycle_summary['missed_upload']}`
- Resolved successfully: `{lifecycle_summary['resolved_success']}`
- Resolved unsuccessfully: `{lifecycle_summary['resolved_failed']}`

External warning awareness does not refresh delayed spacecraft telemetry.
Scheduled future events are not exposed before their `warning_hour`.
"""
    trigger_text = str(autonomy_summary.get("common_triggers") or "none")
    autonomy_section = f"""## Onboard autonomy

- Autonomy model: `{autonomy_summary['autonomy_model']}`
- Autonomous actions: `{autonomy_summary['autonomous_action_count']}`
- Common triggers: {trigger_text}
- Autonomous maneuver actions: `{autonomy_summary['autonomous_maneuver_count']}`
- Contingency plans uploaded: `{autonomy_summary['contingency_plan_upload_count']}`

Autonomy diagnostics describe a bounded proxy only. They are not real flight
software, FDIR, or onboard AI, and they do not make the operator smarter.
Autonomy is layered on top of the existing daily-plan -> BACKUP ->
EMERGENCY_BEACON ladder; it does not replace that ladder, and emergency beacon
remains the terminal no-contact fallback. The local `no_contact_timeout`
diagnostic is not the 14-day emergency mechanism.
"""
    stationkeeping_section = f"""## Stationkeeping planning

- Planning model: `{stationkeeping_summary['planning_model']}`
- Recommended/selected/deferred: `{stationkeeping_summary['recommended']}` / `{stationkeeping_summary['selected']}` / `{stationkeeping_summary['deferred']}`
- Unresolved critical-drift hours: `{stationkeeping_summary['unresolved_critical']}`

This is a bounded drift-planning diagnostic layered on the existing maneuver
path, not real stationkeeping or flight dynamics.
"""
    thermal_section = f"""## Thermal/load stress

- Thermal model: `{thermal_summary['thermal_model']}`
- Hot/cold/any stress hours: `{thermal_summary['hot_hours']}` / `{thermal_summary['cold_hours']}` / `{thermal_summary['stress_hours']}`
- Maximum bounded stress: `{thermal_summary['max_stress']}`
- Total added thermal degradation: `{thermal_summary['total_degradation']}`
- Minimum thermal health: `{thermal_summary['min_health']}`

These are bounded proxy diagnostics, not temperatures or thermal-balance results.
"""
    target_section = f"""## Target/scene scheduling

- Target model: `{target_summary['target_model']}`
- Opportunity/selected/missed hours: `{target_summary['opportunities']}` / `{target_summary['selected']}` / `{target_summary['missed']}`
- Synthetic area imaged: `{target_summary['area_km2']}` km2
- Panchromatic/multispectral scenes: `{target_summary['panchromatic']}` / `{target_summary['multispectral']}`

These are deterministic synthetic tasking diagnostics, not a real target
catalog, demand model, observation geometry, attitude model, or tasking system.
"""
    pointing_section = f"""## Attitude/pointing constraints

- Pointing model: `{pointing_summary['pointing_model']}`
- Required/limited/missed hours: `{pointing_summary['required']}` / `{pointing_summary['limited']}` / `{pointing_summary['missed']}`
- Minimum/average quality: `{pointing_summary['minimum_quality']}` / `{pointing_summary['average_quality']}`
- Imaging/downlink loss proxies: `{pointing_summary['imaging_loss_gb']}` / `{pointing_summary['downlink_loss_gb']}` GB

These are bounded deterministic stress diagnostics, not attitude dynamics,
pointing control, observation geometry, a slew model, or ADCS flight software.
"""
    packet_section = f"""## Command/telemetry packet accounting

- Packet model: `{packet_summary['packet_model']}`
- Delivery model/seed/drop fraction: `{packet_summary['delivery_model']}` / `{packet_summary['delivery_seed']}` / `{packet_summary['drop_fraction']}`
- Telemetry generated/downlinked: `{packet_summary['telemetry_generated']}` / `{packet_summary['telemetry_downlinked']}`
- Telemetry attempts/failures: `{packet_summary['telemetry_attempts']}` / `{packet_summary['telemetry_failures']}`
- Command/daily-plan packets uploaded: `{packet_summary['commands_uploaded']}` / `{packet_summary['daily_plans_uploaded']}`
- Command/daily-plan failures: `{packet_summary['command_failures']}` / `{packet_summary['daily_plan_failures']}`
- Packet uplink/downlink: `{packet_summary['uplink_kb']}` / `{packet_summary['downlink_kb']}` KB

These are bounded accounting and delivery-stress diagnostics, not CCSDS, a real
command link, RF propagation, BER/FER, modulation, a link budget,
ground-network behavior, or flight software. Delivery delay means retry at a
later eligible contact, not an in-flight queue. Packet KB does not compete with
payload imagery capacity.
"""
    markdown = f"""# Decision and risk summary

- Policy: `{attribution.policy}`
- Scenario: `{attribution.scenario}`
- Requested duration: `{years:g}` years
- Outcome: **{outcome}**
- Completed explanation hours: `{len(explanations)}`
- Debris risk model: `{debris_risk_model}`
- Power model: `{power_model}`
- Thermal model: `{thermal_model}`
- Target model: `{target_model}`
- Pointing model: `{pointing_model}`
- Packet model: `{packet_model}`

## Dominant diagnostics

- Top main risks: {_counter_text(risks)}
- Most common executed modes: {_counter_text(modes)}
- Most common main reasons: {_counter_text(reasons)}

## Failure or survival attribution

{failure_text}

The attribution row records dominant risk `{attribution.dominant_pre_failure_risk}`
and likely bottleneck `{attribution.likely_bottleneck}`.

{lifecycle_section}

{autonomy_section}

{stationkeeping_section}

{thermal_section}

{target_section}

{pointing_section}

{packet_section}

## Limitations

These explanations are transparent proxy diagnostics over the existing
simplified simulator state and constraints. Risk scores are bounded values, not
probabilities. They are not validated operator reasoning, real flight-software
explanations, real KazEOSat-1 operational logic, or new spacecraft physics.
Lifecycle fields are also diagnostics only and do not make policies smarter.
"""
    path.write_text(markdown, encoding="utf-8")


def run_decision_report(
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
    results_dir: Path,
    event_lifecycle_model: str = "none",
    debris_risk_model: str = "legacy",
    autonomy_model: str = "none",
    stationkeeping_planning_model: str = "legacy",
    power_model: str = "legacy",
    thermal_model: str = "legacy",
    target_model: str = "legacy",
    pointing_model: str = "legacy",
    packet_model: str = "legacy",
    packet_delivery_model: str = "ideal",
    packet_drop_fraction_proxy: float | None = None,
    max_rows: int | None = None,
    summary_only: bool = False,
) -> tuple[object, list[DecisionExplanation], FailureAttribution]:
    """Run and write one report; returned objects support bounded integration."""

    total_hours = int(round(years * DEFAULT_CONFIG.hours_per_year))
    catalog = (
        generate_stochastic_event_catalog(
            seed, STOCHASTIC_SCENARIO, total_hours, DEFAULT_CONFIG
        )
        if scenario == STOCHASTIC_SCENARIO
        else None
    )
    scenario_model = make_scenario(
        scenario,
        DEFAULT_CONFIG,
        seed=seed if catalog is not None else None,
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
        stationkeeping_planning_model=stationkeeping_planning_model,
        power_model=power_model,
        thermal_model=thermal_model,
        target_model=target_model,
        pointing_model=pointing_model,
        packet_model=packet_model,
        packet_delivery_model=packet_delivery_model,
        packet_delivery_seed=seed,
        packet_drop_fraction_proxy=packet_drop_fraction_proxy,
    )
    explanations: list[DecisionExplanation] = []
    hour_records: list[HourRecord] = []
    result = simulator.run(
        years,
        on_decision_explanation=explanations.append,
        on_hour=hour_records.append,
    )
    attribution = build_failure_attribution(
        result, explanations, DEFAULT_CONFIG
    )
    results_dir.mkdir(parents=True, exist_ok=True)
    if summary_only:
        for filename in TRACE_FILES:
            path = results_dir / filename
            if path.is_file():
                path.unlink()
    else:
        selected = (
            explanations
            if max_rows is None
            else explanations[:max_rows]
        )
        records_by_hour = {record.hour: record for record in hour_records}

        def diagnostic_fields(hour: int) -> dict[str, object]:
            record = records_by_hour.get(hour)
            if record is None:
                lifecycle = {
                    field: None if field.startswith("lifecycle_next_") else 0
                    for field in LIFECYCLE_TRACE_FIELDS
                }
                autonomy = {
                    field: (
                        "none" if field == "autonomy_model"
                        else False if field in (
                            "autonomy_active_this_hour",
                            "contingency_plan_active",
                        ) else None
                    )
                    for field in AUTONOMY_TRACE_FIELDS
                }
                stationkeeping = {
                    field: (
                        "legacy"
                        if field == "stationkeeping_planning_model"
                        else False
                        if field.endswith("_this_hour")
                        and field in (
                            "stationkeeping_recommended_this_hour",
                            "stationkeeping_feasible_this_hour",
                            "stationkeeping_selected_this_hour",
                            "stationkeeping_blocked_by_priority_this_hour",
                        )
                        else None
                    )
                    for field in STATIONKEEPING_TRACE_FIELDS
                }
                power = {
                    field: power_model if field == "power_model" else None
                    for field in POWER_TRACE_FIELDS
                }
                thermal = {
                    field: thermal_model if field == "thermal_model" else None
                    for field in THERMAL_TRACE_FIELDS
                }
                target = {
                    field: target_model if field == "target_model" else None
                    for field in TARGET_TRACE_FIELDS
                }
                pointing = {
                    field: (
                        pointing_model if field == "pointing_model" else None
                    )
                    for field in POINTING_TRACE_FIELDS
                }
                packet = {
                    field: (
                        packet_model
                        if field == "packet_model"
                        else packet_delivery_model
                        if field == "packet_delivery_model"
                        else None
                    )
                    for field in PACKET_TRACE_FIELDS
                }
                return {
                    **lifecycle,
                    **autonomy,
                    **stationkeeping,
                    **power,
                    **thermal,
                    **target,
                    **pointing,
                    **packet,
                }
            return {
                field: getattr(record, field)
                for field in (
                    *LIFECYCLE_TRACE_FIELDS,
                    *AUTONOMY_TRACE_FIELDS,
                    *STATIONKEEPING_TRACE_FIELDS,
                    *POWER_TRACE_FIELDS,
                    *THERMAL_TRACE_FIELDS,
                    *TARGET_TRACE_FIELDS,
                    *POINTING_TRACE_FIELDS,
                    *PACKET_TRACE_FIELDS,
                )
            }

        _write_rows(
            results_dir / "decision_trace.csv",
            [
                {**item.as_dict(), **diagnostic_fields(item.hour)}
                for item in selected
            ],
            [field.name for field in fields(DecisionExplanation) if field.name not in {
                "risk_snapshot", "option_assessments"
            }]
            + list(LIFECYCLE_TRACE_FIELDS)
            + list(AUTONOMY_TRACE_FIELDS)
            + list(STATIONKEEPING_TRACE_FIELDS)
            + list(POWER_TRACE_FIELDS)
            + list(THERMAL_TRACE_FIELDS)
            + list(TARGET_TRACE_FIELDS)
            + list(POINTING_TRACE_FIELDS)
            + list(PACKET_TRACE_FIELDS),
        )
        _write_rows(
            results_dir / "risk_trace.csv",
            [
                {
                    **item.risk_snapshot.as_dict(),
                    **diagnostic_fields(item.hour),
                }
                for item in selected
            ],
            [field.name for field in fields(RiskSnapshot)]
            + list(LIFECYCLE_TRACE_FIELDS)
            + list(AUTONOMY_TRACE_FIELDS)
            + list(STATIONKEEPING_TRACE_FIELDS)
            + list(POWER_TRACE_FIELDS)
            + list(THERMAL_TRACE_FIELDS)
            + list(TARGET_TRACE_FIELDS)
            + list(POINTING_TRACE_FIELDS)
            + list(PACKET_TRACE_FIELDS),
        )
        _write_rows(
            results_dir / "option_assessments.csv",
            [row for item in selected for row in item.option_rows()],
            [
                "hour", "year", "policy", "scenario", "selected_mode",
                "executed_mode",
                *[field.name for field in fields(ModeOptionAssessment)],
            ],
        )
    _write_rows(
        results_dir / "failure_attribution.csv",
        [attribution.as_dict()],
        [field.name for field in fields(FailureAttribution)],
    )
    final_lifecycle = simulator.lifecycle_diagnostics()
    _write_summary(
        results_dir / "decision_summary.md",
        explanations=explanations,
        attribution=attribution,
        years=years,
        event_lifecycle_model=event_lifecycle_model,
        debris_risk_model=debris_risk_model,
        power_model=power_model,
        thermal_model=thermal_model,
        target_model=target_model,
        pointing_model=pointing_model,
        packet_model=packet_model,
        autonomy_summary={
            "autonomy_model": autonomy_model,
            "autonomous_action_count": result.autonomous_action_count,
            "autonomous_maneuver_count": result.autonomous_maneuver_count,
            "contingency_plan_upload_count": (
                result.contingency_plan_upload_count
            ),
            "common_triggers": _counter_text(Counter(
                record.autonomy_trigger_this_hour
                for record in hour_records
                if record.autonomy_active_this_hour
                and record.autonomy_trigger_this_hour is not None
            )),
        },
        stationkeeping_summary={
            "planning_model": stationkeeping_planning_model,
            "recommended": result.stationkeeping_recommended_count,
            "selected": result.stationkeeping_selected_count,
            "deferred": result.stationkeeping_deferred_count,
            "unresolved_critical": (
                result.stationkeeping_unresolved_critical_drift_hours
            ),
        },
        thermal_summary={
            "thermal_model": result.thermal_model,
            "hot_hours": result.thermal_hot_stress_hours,
            "cold_hours": result.thermal_cold_stress_hours,
            "stress_hours": result.thermal_stress_hours,
            "max_stress": result.max_thermal_stress,
            "total_degradation": result.total_thermal_degradation,
            "min_health": result.min_thermal_health,
        },
        target_summary={
            "target_model": result.target_model,
            "opportunities": result.target_opportunity_hours,
            "selected": result.target_selected_hours,
            "missed": result.target_missed_hours,
            "area_km2": result.target_area_imaged_km2,
            "panchromatic": result.target_panchromatic_scenes,
            "multispectral": result.target_multispectral_scenes,
        },
        pointing_summary={
            "pointing_model": result.pointing_model,
            "required": result.pointing_required_hours,
            "limited": result.pointing_limited_hours,
            "missed": result.pointing_missed_hours,
            "minimum_quality": result.min_pointing_quality,
            "average_quality": result.average_pointing_quality,
            "imaging_loss_gb": result.pointing_imaging_loss_gb_proxy,
            "downlink_loss_gb": result.pointing_downlink_loss_gb_proxy,
        },
        packet_summary={
            "packet_model": result.packet_model,
            "delivery_model": result.packet_delivery_model,
            "delivery_seed": result.packet_delivery_seed,
            "drop_fraction": result.packet_drop_fraction_proxy,
            "telemetry_generated": result.telemetry_packets_generated,
            "telemetry_attempts": result.telemetry_delivery_attempts,
            "telemetry_downlinked": result.telemetry_packets_downlinked,
            "telemetry_failures": result.telemetry_delivery_failures,
            "commands_uploaded": result.command_packets_uploaded,
            "command_failures": result.command_packet_failures,
            "daily_plans_uploaded": result.daily_plan_packets_uploaded,
            "daily_plan_failures": result.daily_plan_packet_failures,
            "uplink_kb": result.packet_uplink_kb_total,
            "downlink_kb": result.packet_downlink_kb_total,
        },
        lifecycle_summary={
            "lifecycle_events": (
                len(simulator.lifecycle_manager.events)
                if simulator.lifecycle_manager is not None
                else 0
            ),
            "ground_known": final_lifecycle.lifecycle_ground_known_count,
            "uploaded": final_lifecycle.lifecycle_uploaded_count,
            "missed_upload": final_lifecycle.lifecycle_missed_upload_count,
            "resolved_success": (
                final_lifecycle.lifecycle_resolved_success_count
            ),
            "resolved_failed": (
                final_lifecycle.lifecycle_resolved_failed_count
            ),
        },
    )
    return result, explanations, attribution


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    result, explanations, attribution = run_decision_report(
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
        stationkeeping_planning_model=(
            args.stationkeeping_planning_model
        ),
        power_model=args.power_model,
        thermal_model=args.thermal_model,
        target_model=args.target_model,
        pointing_model=args.pointing_model,
        packet_model=args.packet_model,
        packet_delivery_model=args.packet_delivery_model,
        packet_drop_fraction_proxy=args.packet_drop_fraction_proxy,
        results_dir=args.results_dir,
        max_rows=args.max_rows,
        summary_only=args.summary_only,
    )
    print(
        "Decision report complete: "
        f"{len(explanations)} completed hours, "
        f"survived={result.state.alive}, "
        f"likely_bottleneck={attribution.likely_bottleneck}."
    )
    print(f"Outputs: {args.results_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
