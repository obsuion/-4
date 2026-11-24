"""Batch and Monte Carlo experiment runner with configurable CSV logging."""

import argparse
import csv
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

from ops_sim.autonomy import AUTONOMY_MODELS
from ops_sim.config import DEFAULT_CONFIG, SimulationConfig
from ops_sim.contacts import (
    ContactModel,
    GeometryContactModel,
    GroundStation,
    SyntheticContactModel,
    default_astana_ground_station,
)
from ops_sim.debris_risk import DEBRIS_RISK_MODELS
from ops_sim.event_catalog import (
    EventCatalog,
    generate_stochastic_event_catalog,
    read_event_catalog,
    write_event_catalog,
)
from ops_sim.models import Mode
from ops_sim.packets import PACKET_DELIVERY_MODELS, PACKET_MODELS
from ops_sim.policies import POLICIES, make_policy
from ops_sim.pointing import POINTING_MODELS
from ops_sim.power import POWER_MODELS
from ops_sim.reporting import print_table
from ops_sim.scenarios import SCENARIOS, make_scenario
from ops_sim.stationkeeping import STATIONKEEPING_PLANNING_MODELS
from ops_sim.thermal import THERMAL_MODELS
from ops_sim.targets import TARGET_MODELS
from ops_sim.simulator import (
    EVENT_LIFECYCLE_MODELS,
    Event,
    HourRecord,
    MANEUVER_MODELS,
    OPERATOR_VIEWS,
    ORBIT_EVOLUTION_MODELS,
    PLANNING_MODELS,
    Simulator,
)


STOCHASTIC_SCENARIO = "stochastic_post_life_events"
SUMMARY_FIELDS = [
    "policy", "scenario", "operator_view", "planning_model", "maneuver_model",
    "orbit_evolution_model", "event_lifecycle_model", "debris_risk_model",
    "autonomy_model", "stationkeeping_planning_model", "power_model",
    "thermal_model", "target_model", "pointing_model", "packet_model",
    "packet_delivery_model", "packet_delivery_seed",
    "packet_drop_fraction_proxy",
    "years", "survived",
    "survived_hours", "total_hours",
    "final_soc", "final_health", "data_generated_gb", "data_downlinked_gb",
    "final_buffer_gb", "safe_mode_fraction", "backup_mode_fraction",
    "emergency_mode_fraction", "data_lost_gb", "data_loss_fraction",
    "overflow_hours", "payload_unavailable_hours", "minimum_soc",
    "minimum_health", "final_buffer_fraction", "effective_storage_capacity_gb",
    "maneuver_mode_fraction", "final_delta_v_remaining_m_per_s",
    "delta_v_used_m_per_s", "fuel_remaining_percent", "fuel_used_percent",
    "stationkeeping_delta_v_cost_percent",
    "debris_avoidance_delta_v_cost_percent",
    "maneuver_count", "maneuver_skipped_count",
    "final_orbit_drift_proxy_km",
    "stationkeeping_recommended_count", "stationkeeping_selected_count",
    "stationkeeping_deferred_count",
    "stationkeeping_unresolved_critical_drift_hours",
    "max_orbit_drift_proxy_km", "max_orbit_groundtrack_error_km",
    "max_orbit_phase_error_deg",
    "eclipse_hours", "sunlight_hours", "eclipse_fraction_observed",
    "min_sunlight_factor", "average_sunlight_factor",
    "thermal_hot_stress_hours", "thermal_cold_stress_hours",
    "thermal_stress_hours", "max_thermal_stress",
    "total_thermal_degradation", "min_thermal_health",
    "target_opportunity_hours", "target_selected_hours",
    "target_missed_hours", "target_area_imaged_km2",
    "target_priority_score_total", "target_panchromatic_scenes",
    "target_multispectral_scenes",
    "pointing_required_hours", "pointing_limited_hours",
    "pointing_missed_hours", "min_pointing_quality",
    "average_pointing_quality", "pointing_imaging_loss_gb_proxy",
    "pointing_downlink_loss_gb_proxy",
    "telemetry_packets_generated", "telemetry_packets_downlinked",
    "telemetry_delivery_attempts", "telemetry_delivery_failures",
    "command_packet_attempts", "command_packet_failures",
    "command_packets_uploaded", "daily_plan_packets_uploaded",
    "daily_plan_packet_attempts", "daily_plan_packet_failures",
    "packet_delivery_failure_events", "max_telemetry_age_hours",
    "packet_uplink_kb_total", "packet_downlink_kb_total",
    "debris_avoidance_executed_count", "debris_avoidance_skipped_count",
    "debris_damage_events", "debris_damage_accumulated",
    "high_or_severe_debris_events", "severe_debris_events",
    "max_debris_risk_score", "most_common_debris_impact_zone",
    "autonomous_action_count", "autonomous_safe_mode_count",
    "autonomous_standby_count",
    "autonomous_downlink_count", "autonomous_maneuver_count",
    "contingency_plan_upload_count", "contingency_plan_expired_count",
    "orbit_drift_damage_events", "orbit_drift_damage_accumulated",
    "score",
]
STATE_FIELDS = [
    "policy", "scenario", "hour", "year", "mode", "soc", "health",
    "eps_health", "solar_health", "battery_health", "comms_health",
    "payload_health", "storage_health", "adcs_health", "obc_health",
    "thermal_health", "propulsion_health", "buffer_gb", "data_generated_gb",
    "data_downlinked_gb", "cmd_contact_min", "data_contact_min",
    "contact_model", "base_cmd_contact_min", "base_data_contact_min",
    "geometry_raw_visible_seconds", "geometry_usable_cmd_seconds",
    "geometry_usable_data_seconds", "geometry_max_elevation_deg",
    "geometry_min_range_km", "geometry_first_visible_offset_seconds",
    "geometry_last_visible_offset_seconds", "ground_station_name",
    "ground_station_lat_deg", "ground_station_lon_deg",
    "ground_station_minimum_elevation_deg",
    "operator_view", "planning_model", "maneuver_model",
    "orbit_evolution_model", "event_lifecycle_model", "debris_risk_model",
    "autonomy_model", "stationkeeping_planning_model", "power_model",
    "sunlight_factor_this_hour", "eclipse_this_hour",
    "eclipse_fraction_reference", "power_load_proxy_w_this_hour",
    "power_generation_proxy_w_this_hour", "net_power_proxy_w_this_hour",
    "soc_delta_power_model_this_hour",
    "thermal_model", "thermal_load_proxy_this_hour",
    "thermal_hot_stress_this_hour", "thermal_cold_stress_this_hour",
    "thermal_stress_this_hour", "thermal_degradation_this_hour",
    "thermal_reason_this_hour",
    "target_model", "target_opportunity_this_hour",
    "target_selected_this_hour", "target_scene_id_this_hour",
    "target_scene_area_km2_this_hour", "target_priority_this_hour",
    "target_imagery_mode_this_hour", "target_data_multiplier_this_hour",
    "target_missed_reason_this_hour", "target_reason_this_hour",
    "pointing_model", "pointing_required_this_hour",
    "pointing_quality_this_hour", "pointing_multiplier_this_hour",
    "pointing_limited_this_hour", "pointing_missed_this_hour",
    "pointing_off_nadir_proxy_deg_this_hour",
    "pointing_slew_proxy_deg_this_hour", "pointing_reason_this_hour",
    "packet_model", "packet_delivery_model",
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
    "packet_uplink_kb_this_hour", "packet_downlink_kb_this_hour",
    "packet_reason_this_hour", "packet_delivery_reason_this_hour",
    "autonomy_active_this_hour",
    "autonomy_trigger_this_hour", "autonomy_authority_this_hour",
    "autonomy_selected_mode_this_hour", "autonomy_reason_this_hour",
    "autonomy_pre_authorized_this_hour",
    "autonomy_ground_contact_required_this_hour",
    "autonomy_used_uploaded_response_this_hour",
    "contingency_plan_active", "contingency_plan_age_hours",
    "contingency_plan_expires_in_hours",
    "lifecycle_ground_known_count", "lifecycle_spacecraft_known_count",
    "lifecycle_uploaded_count", "lifecycle_pending_count",
    "lifecycle_active_count", "lifecycle_missed_upload_count",
    "lifecycle_next_warning_hour", "lifecycle_next_execution_hour",
    "telemetry_updated_this_hour", "last_telemetry_hour",
    "telemetry_age_hours", "observed_soc", "observed_health",
    "observed_buffer_gb", "observed_effective_energy_margin",
    "observed_battery_health", "observed_solar_health",
    "observed_comms_health", "observed_payload_health",
    "observed_storage_health",
    "plan_uploaded_this_hour", "plan_policy",
    "plan_based_on_telemetry_hour",
    "plan_based_on_telemetry_age_hours",
    "planned_mode", "plan_mode_index", "plan_modes_remaining",
    "planning_energy_risk", "planning_storage_risk",
    "planning_expected_data_contact_min",
    "planning_expected_cmd_contact_min",
    "delta_v_remaining_m_per_s", "delta_v_used_m_per_s",
    "fuel_remaining_percent", "fuel_used_percent",
    "stationkeeping_delta_v_cost_percent",
    "debris_avoidance_delta_v_cost_percent",
    "maneuver_count", "maneuver_skipped_count", "orbit_drift_proxy_km",
    "orbit_altitude_offset_km", "orbit_phase_error_deg",
    "orbit_groundtrack_error_km", "orbit_geometry_degraded",
    "orbit_correction_count", "orbit_correction_skipped_count",
    "maneuver_due", "maneuver_executed_this_hour",
    "maneuver_skipped_this_hour", "maneuver_delta_v_used_this_hour",
    "planned_maneuver",
    "stationkeeping_drift_risk_class_this_hour",
    "stationkeeping_priority_this_hour",
    "stationkeeping_recommended_this_hour",
    "stationkeeping_feasible_this_hour",
    "stationkeeping_selected_this_hour",
    "stationkeeping_reason_this_hour",
    "stationkeeping_deferred_reason_this_hour",
    "stationkeeping_blocked_by_priority_this_hour",
    "debris_conjunction_active", "debris_avoidance_required_this_hour",
    "debris_avoidance_executed_count", "debris_avoidance_skipped_count",
    "debris_avoidance_executed_this_hour",
    "debris_avoidance_skipped_this_hour", "debris_damage_events",
    "debris_damage_this_hour", "debris_damage_accumulated",
    "debris_risk_class_this_hour", "debris_impact_zone_this_hour",
    "debris_risk_score_this_hour", "debris_object_size_cm_this_hour",
    "debris_miss_distance_proxy_m_this_hour",
    "debris_damage_targets_this_hour",
    "orbit_drift_warning", "orbit_drift_critical",
    "orbit_drift_damage_events", "orbit_drift_damage_this_hour",
    "orbit_drift_damage_accumulated",
    "hours_since_contact", "daily_plan_age_hours", "valid_daily_plan",
    "sat_lat_deg", "sat_lon_deg", "sat_alt_km", "orbit_phase_deg",
    "effective_orbit_altitude_km", "effective_orbit_phase_deg",
    "fixed_orbit_sat_lat_deg", "fixed_orbit_sat_lon_deg",
    "fixed_orbit_alt_km", "fixed_orbit_phase_deg",
    "data_lost_gb", "overflow_hours", "effective_storage_capacity_gb",
    "pointing_efficiency", "effective_downlink_rate_gb_per_min",
    "effective_imaging_rate_gb_per_hour", "effective_energy_margin",
    "minimum_soc", "minimum_health",
]
CHECKPOINT_FIELDS = [
    "policy", "scenario", "hour", "year", "mode", "soc", "health",
    "buffer_gb", "data_downlinked_gb", "hours_since_contact",
    "daily_plan_age_hours", "sat_lat_deg", "sat_lon_deg", "sat_alt_km",
    "data_lost_gb", "overflow_hours", "effective_storage_capacity_gb",
]
EVENT_FIELDS = ["policy", "scenario", "hour", "year", "event_type", "description"]
MONTE_CARLO_FIELDS = [
    "seed", "policy", "scenario", "operator_view", "planning_model",
    "maneuver_model", "orbit_evolution_model", "event_lifecycle_model",
    "debris_risk_model",
    "autonomy_model", "stationkeeping_planning_model", "power_model",
    "thermal_model", "target_model", "pointing_model", "packet_model",
    "packet_delivery_model", "packet_delivery_seed",
    "packet_drop_fraction_proxy",
    "survived",
    "survived_hours", "total_hours",
    "final_soc", "final_health", "data_generated_gb", "data_downlinked_gb",
    "final_buffer_gb", "data_lost_gb", "safe_mode_fraction",
    "backup_mode_fraction", "emergency_mode_fraction", "minimum_soc",
    "minimum_health", "maneuver_mode_fraction",
    "final_delta_v_remaining_m_per_s", "delta_v_used_m_per_s",
    "fuel_remaining_percent", "fuel_used_percent",
    "stationkeeping_delta_v_cost_percent",
    "debris_avoidance_delta_v_cost_percent",
    "maneuver_count", "maneuver_skipped_count", "final_orbit_drift_proxy_km",
    "stationkeeping_recommended_count", "stationkeeping_selected_count",
    "stationkeeping_deferred_count",
    "stationkeeping_unresolved_critical_drift_hours",
    "max_orbit_drift_proxy_km", "max_orbit_groundtrack_error_km",
    "max_orbit_phase_error_deg",
    "eclipse_hours", "sunlight_hours", "eclipse_fraction_observed",
    "min_sunlight_factor", "average_sunlight_factor",
    "thermal_hot_stress_hours", "thermal_cold_stress_hours",
    "thermal_stress_hours", "max_thermal_stress",
    "total_thermal_degradation", "min_thermal_health",
    "target_opportunity_hours", "target_selected_hours",
    "target_missed_hours", "target_area_imaged_km2",
    "target_priority_score_total", "target_panchromatic_scenes",
    "target_multispectral_scenes",
    "pointing_required_hours", "pointing_limited_hours",
    "pointing_missed_hours", "min_pointing_quality",
    "average_pointing_quality", "pointing_imaging_loss_gb_proxy",
    "pointing_downlink_loss_gb_proxy",
    "telemetry_packets_generated", "telemetry_packets_downlinked",
    "telemetry_delivery_attempts", "telemetry_delivery_failures",
    "command_packet_attempts", "command_packet_failures",
    "command_packets_uploaded", "daily_plan_packets_uploaded",
    "daily_plan_packet_attempts", "daily_plan_packet_failures",
    "packet_delivery_failure_events", "max_telemetry_age_hours",
    "packet_uplink_kb_total", "packet_downlink_kb_total",
    "debris_avoidance_executed_count", "debris_avoidance_skipped_count",
    "debris_damage_events", "debris_damage_accumulated",
    "high_or_severe_debris_events", "severe_debris_events",
    "max_debris_risk_score", "most_common_debris_impact_zone",
    "autonomous_action_count", "autonomous_safe_mode_count",
    "autonomous_standby_count",
    "autonomous_downlink_count", "autonomous_maneuver_count",
    "contingency_plan_upload_count", "contingency_plan_expired_count",
    "orbit_drift_damage_events", "orbit_drift_damage_accumulated",
    "score", "loss_reason",
]

GEOMETRY_OPTION_FLAGS = {
    "station_lat": "--station-lat",
    "station_lon": "--station-lon",
    "station_name": "--station-name",
    "minimum_elevation_deg": "--minimum-elevation-deg",
    "geometry_step_seconds": "--geometry-step-seconds",
    "command_overhead_seconds": "--command-overhead-seconds",
    "data_overhead_seconds": "--data-overhead-seconds",
    "min_data_contact_seconds": "--min-data-contact-seconds",
}


class _GeometryOptionAction(argparse.Action):
    """Store an option while recording that the CLI user supplied it."""

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        supplied = set(getattr(namespace, "_supplied_geometry_options", ()))
        supplied.add(self.dest)
        setattr(namespace, "_supplied_geometry_options", supplied)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one or more simulator experiments")
    parser.add_argument("--years", type=float, default=DEFAULT_CONFIG.default_simulation_years)
    parser.add_argument("--policy", choices=[*POLICIES, "all"], default="adaptive")
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="nominal")
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--event-catalog", type=Path)
    parser.add_argument("--write-event-catalog", type=Path)
    parser.add_argument("--monte-carlo", type=int, metavar="RUNS")
    parser.add_argument(
        "--contact-model",
        choices=("synthetic", "geometry"),
        default="synthetic",
    )
    parser.add_argument(
        "--operator-view",
        choices=OPERATOR_VIEWS,
        default="omniscient",
    )
    parser.add_argument(
        "--planning-model",
        choices=PLANNING_MODELS,
        default="reactive",
    )
    parser.add_argument(
        "--maneuver-model",
        choices=MANEUVER_MODELS,
        default="none",
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
        "--power-model",
        choices=POWER_MODELS,
        default="legacy",
    )
    parser.add_argument(
        "--thermal-model",
        choices=THERMAL_MODELS,
        default="legacy",
    )
    parser.add_argument(
        "--target-model",
        choices=TARGET_MODELS,
        default="legacy",
    )
    parser.add_argument(
        "--pointing-model",
        choices=POINTING_MODELS,
        default="legacy",
    )
    parser.add_argument(
        "--packet-model",
        choices=PACKET_MODELS,
        default="legacy",
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
        "--autonomy-model",
        choices=AUTONOMY_MODELS,
        default="none",
    )
    parser.add_argument(
        "--station-lat", type=float, action=_GeometryOptionAction,
        help="geometry station latitude in degrees",
    )
    parser.add_argument(
        "--station-lon", type=float, action=_GeometryOptionAction,
        help="geometry station longitude in degrees",
    )
    parser.add_argument(
        "--station-name", action=_GeometryOptionAction,
        help="geometry station label (default: astana_proxy or custom_station)",
    )
    parser.add_argument(
        "--minimum-elevation-deg", type=float, action=_GeometryOptionAction,
        help="geometry visibility threshold (default: model configuration)",
    )
    parser.add_argument(
        "--geometry-step-seconds", type=int, default=30,
        action=_GeometryOptionAction,
    )
    parser.add_argument(
        "--command-overhead-seconds", type=int, default=0,
        action=_GeometryOptionAction,
    )
    parser.add_argument(
        "--data-overhead-seconds", type=int, default=60,
        action=_GeometryOptionAction,
    )
    parser.add_argument(
        "--min-data-contact-seconds", type=int, default=60,
        action=_GeometryOptionAction,
    )
    parser.add_argument(
        "--log-level", choices=("full", "checkpoints", "summary"),
        help="default: full for normal runs, summary for Monte Carlo",
    )
    return parser


def build_contact_model(
    args, config: SimulationConfig = DEFAULT_CONFIG
) -> ContactModel:
    """Build the selected base contact provider without mutating CLI arguments."""
    if args.contact_model == "synthetic":
        return SyntheticContactModel(config)
    if args.contact_model != "geometry":
        raise ValueError(f"Unknown contact model {args.contact_model!r}")
    if (args.station_lat is None) != (args.station_lon is None):
        raise ValueError(
            "--station-lat and --station-lon must be supplied together"
        )

    custom_coordinates = args.station_lat is not None
    if custom_coordinates:
        station = GroundStation(
            latitude_deg=args.station_lat,
            longitude_deg=args.station_lon,
            minimum_elevation_deg=(
                args.minimum_elevation_deg
                if args.minimum_elevation_deg is not None
                else config.minimum_elevation_deg
            ),
            name=args.station_name or "custom_station",
        )
    else:
        default_station = default_astana_ground_station(config)
        station = GroundStation(
            latitude_deg=default_station.latitude_deg,
            longitude_deg=default_station.longitude_deg,
            minimum_elevation_deg=(
                args.minimum_elevation_deg
                if args.minimum_elevation_deg is not None
                else default_station.minimum_elevation_deg
            ),
            name=args.station_name or default_station.name,
        )

    return GeometryContactModel(
        station,
        config,
        step_seconds=args.geometry_step_seconds,
        command_overhead_seconds=args.command_overhead_seconds,
        data_overhead_seconds=args.data_overhead_seconds,
        min_data_contact_seconds=args.min_data_contact_seconds,
    )


def _selected(value: str, available: dict[str, object]) -> list[str]:
    return list(available) if value == "all" else [value]


def _catalog_default_path(results_dir: Path, seed: int | None) -> Path:
    seed_label = "none" if seed is None else str(seed)
    return (
        results_dir / "event_catalogs"
        / f"{STOCHASTIC_SCENARIO}_seed{seed_label}.csv"
    )


def _summary_row(result, years: float) -> dict[str, object]:
    state = result.state
    completed = state.hours_completed

    def fraction(mode: Mode) -> float:
        return state.mode_hours[mode] / completed if completed else 0.0

    return {
        "policy": result.policy_name,
        "scenario": result.scenario_name,
        "operator_view": result.operator_view,
        "planning_model": result.planning_model,
        "maneuver_model": result.maneuver_model,
        "orbit_evolution_model": result.orbit_evolution_model,
        "stationkeeping_planning_model": (
            result.stationkeeping_planning_model
        ),
        "power_model": result.power_model,
        "thermal_model": result.thermal_model,
        "target_model": result.target_model,
        "pointing_model": result.pointing_model,
        "packet_model": result.packet_model,
        "packet_delivery_model": result.packet_delivery_model,
        "packet_delivery_seed": result.packet_delivery_seed,
        "packet_drop_fraction_proxy": result.packet_drop_fraction_proxy,
        "event_lifecycle_model": result.event_lifecycle_model,
        "debris_risk_model": result.debris_risk_model,
        "autonomy_model": result.autonomy_model,
        "years": years,
        "survived": state.alive,
        "survived_hours": completed,
        "total_hours": result.total_hours,
        "final_soc": state.soc,
        "final_health": result.metrics.final_total_health,
        "data_generated_gb": state.total_data_generated_gb,
        "data_downlinked_gb": state.total_data_downlinked_gb,
        "final_buffer_gb": state.data_buffer_gb,
        "safe_mode_fraction": fraction(Mode.SAFE),
        "backup_mode_fraction": fraction(Mode.BACKUP),
        "emergency_mode_fraction": fraction(Mode.EMERGENCY_BEACON),
        "maneuver_mode_fraction": fraction(Mode.MANEUVER),
        "data_lost_gb": result.metrics.data_lost_gb,
        "data_loss_fraction": result.metrics.data_loss_fraction,
        "overflow_hours": result.metrics.overflow_hours,
        "payload_unavailable_hours": result.metrics.payload_unavailable_hours,
        "minimum_soc": result.metrics.minimum_soc,
        "minimum_health": result.metrics.minimum_health,
        "final_buffer_fraction": result.metrics.final_buffer_fraction,
        "effective_storage_capacity_gb": result.metrics.effective_storage_capacity_gb,
        "final_delta_v_remaining_m_per_s": state.delta_v_remaining_m_per_s,
        "delta_v_used_m_per_s": state.delta_v_used_m_per_s,
        "fuel_remaining_percent": result.fuel_remaining_percent,
        "fuel_used_percent": result.fuel_used_percent,
        "stationkeeping_delta_v_cost_percent": (
            result.stationkeeping_delta_v_cost_percent
        ),
        "debris_avoidance_delta_v_cost_percent": (
            result.debris_avoidance_delta_v_cost_percent
        ),
        "maneuver_count": state.maneuver_count,
        "maneuver_skipped_count": state.maneuver_skipped_count,
        "final_orbit_drift_proxy_km": state.orbit_drift_proxy_km,
        "stationkeeping_recommended_count": (
            result.stationkeeping_recommended_count
        ),
        "stationkeeping_selected_count": (
            result.stationkeeping_selected_count
        ),
        "stationkeeping_deferred_count": (
            result.stationkeeping_deferred_count
        ),
        "stationkeeping_unresolved_critical_drift_hours": (
            result.stationkeeping_unresolved_critical_drift_hours
        ),
        "max_orbit_drift_proxy_km": result.max_orbit_drift_proxy_km,
        "max_orbit_groundtrack_error_km": (
            result.max_orbit_groundtrack_error_km
        ),
        "max_orbit_phase_error_deg": result.max_orbit_phase_error_deg,
        "eclipse_hours": result.eclipse_hours,
        "sunlight_hours": result.sunlight_hours,
        "eclipse_fraction_observed": result.eclipse_fraction_observed,
        "min_sunlight_factor": result.min_sunlight_factor,
        "average_sunlight_factor": result.average_sunlight_factor,
        "thermal_hot_stress_hours": result.thermal_hot_stress_hours,
        "thermal_cold_stress_hours": result.thermal_cold_stress_hours,
        "thermal_stress_hours": result.thermal_stress_hours,
        "max_thermal_stress": result.max_thermal_stress,
        "total_thermal_degradation": result.total_thermal_degradation,
        "min_thermal_health": result.min_thermal_health,
        "target_opportunity_hours": result.target_opportunity_hours,
        "target_selected_hours": result.target_selected_hours,
        "target_missed_hours": result.target_missed_hours,
        "target_area_imaged_km2": result.target_area_imaged_km2,
        "target_priority_score_total": result.target_priority_score_total,
        "target_panchromatic_scenes": result.target_panchromatic_scenes,
        "target_multispectral_scenes": result.target_multispectral_scenes,
        "pointing_required_hours": result.pointing_required_hours,
        "pointing_limited_hours": result.pointing_limited_hours,
        "pointing_missed_hours": result.pointing_missed_hours,
        "min_pointing_quality": result.min_pointing_quality,
        "average_pointing_quality": result.average_pointing_quality,
        "pointing_imaging_loss_gb_proxy": (
            result.pointing_imaging_loss_gb_proxy
        ),
        "pointing_downlink_loss_gb_proxy": (
            result.pointing_downlink_loss_gb_proxy
        ),
        "telemetry_packets_generated": (
            result.telemetry_packets_generated
        ),
        "telemetry_delivery_attempts": result.telemetry_delivery_attempts,
        "telemetry_packets_downlinked": (
            result.telemetry_packets_downlinked
        ),
        "telemetry_delivery_failures": result.telemetry_delivery_failures,
        "command_packet_attempts": result.command_packet_attempts,
        "command_packets_uploaded": result.command_packets_uploaded,
        "command_packet_failures": result.command_packet_failures,
        "daily_plan_packet_attempts": result.daily_plan_packet_attempts,
        "daily_plan_packets_uploaded": (
            result.daily_plan_packets_uploaded
        ),
        "daily_plan_packet_failures": result.daily_plan_packet_failures,
        "packet_delivery_failure_events": (
            result.packet_delivery_failure_events
        ),
        "max_telemetry_age_hours": result.max_telemetry_age_hours,
        "packet_uplink_kb_total": result.packet_uplink_kb_total,
        "packet_downlink_kb_total": result.packet_downlink_kb_total,
        "debris_avoidance_executed_count": (
            state.debris_avoidance_executed_count
        ),
        "debris_avoidance_skipped_count": state.debris_avoidance_skipped_count,
        "debris_damage_events": state.debris_damage_events,
        "debris_damage_accumulated": state.debris_damage_accumulated,
        "high_or_severe_debris_events": (
            result.high_or_severe_debris_events
        ),
        "severe_debris_events": result.severe_debris_events,
        "max_debris_risk_score": result.max_debris_risk_score,
        "most_common_debris_impact_zone": (
            result.most_common_debris_impact_zone
        ),
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
        "orbit_drift_damage_events": state.orbit_drift_damage_events,
        "orbit_drift_damage_accumulated": (
            state.orbit_drift_damage_accumulated
        ),
        "score": result.metrics.score,
    }


def _monte_carlo_row(seed: int, result, summary: dict[str, object]) -> dict[str, object]:
    return {
        "seed": seed,
        **{field: summary[field] for field in MONTE_CARLO_FIELDS if field in summary},
        "loss_reason": (
            result.state.loss_reason.value if result.state.loss_reason else ""
        ),
    }


def _open_log_writers(results_dir: Path, log_level: str, stack: ExitStack):
    writers = {"state": None, "checkpoints": None, "events": None}
    if log_level == "full":
        handle = stack.enter_context(
            (results_dir / "state_log.csv").open("w", newline="", encoding="utf-8")
        )
        writers["state"] = csv.DictWriter(handle, fieldnames=STATE_FIELDS)
        writers["state"].writeheader()
    if log_level in ("full", "checkpoints"):
        checkpoint_handle = stack.enter_context(
            (results_dir / "checkpoints.csv").open("w", newline="", encoding="utf-8")
        )
        event_handle = stack.enter_context(
            (results_dir / "events_log.csv").open("w", newline="", encoding="utf-8")
        )
        writers["checkpoints"] = csv.DictWriter(
            checkpoint_handle, fieldnames=CHECKPOINT_FIELDS
        )
        writers["events"] = csv.DictWriter(event_handle, fieldnames=EVENT_FIELDS)
        writers["checkpoints"].writeheader()
        writers["events"].writeheader()
    return writers


def _remove_logs_excluded_by_level(results_dir: Path, log_level: str) -> None:
    excluded = []
    if log_level == "summary":
        excluded.extend(("state_log.csv", "checkpoints.csv", "events_log.csv"))
    elif log_level == "checkpoints":
        excluded.append("state_log.csv")
    for filename in excluded:
        path = results_dir / filename
        if path.exists():
            path.unlink()


def _write_checkpoints(writer, result) -> None:
    if writer is None:
        return
    for checkpoint in result.checkpoints:
        writer.writerow({
            "policy": result.policy_name,
            "scenario": result.scenario_name,
            "hour": checkpoint.hour,
            "year": checkpoint.year,
            "mode": checkpoint.mode,
            "soc": checkpoint.soc,
            "health": checkpoint.total_health,
            "buffer_gb": checkpoint.data_buffer_gb,
            "data_downlinked_gb": checkpoint.data_downlinked_gb,
            "hours_since_contact": checkpoint.hours_since_contact,
            "daily_plan_age_hours": checkpoint.daily_plan_age_hours,
            "sat_lat_deg": checkpoint.sat_lat_deg,
            "sat_lon_deg": checkpoint.sat_lon_deg,
            "sat_alt_km": checkpoint.sat_alt_km,
            "data_lost_gb": checkpoint.data_lost_gb,
            "overflow_hours": checkpoint.overflow_hours,
            "effective_storage_capacity_gb": checkpoint.effective_storage_capacity_gb,
        })


def _run_one(
    policy_name: str,
    scenario_name: str,
    years: float,
    total_hours: int,
    catalog: EventCatalog | None,
    writers,
    contact_model: ContactModel | None = None,
    operator_view: str = "omniscient",
    planning_model: str = "reactive",
    maneuver_model: str = "none",
    orbit_evolution_model: str = "fixed",
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
    packet_delivery_seed: int = 0,
    packet_drop_fraction_proxy: float | None = None,
):
    scenario = make_scenario(
        scenario_name,
        seed=catalog.seed if catalog else None,
        total_hours=total_hours,
        event_catalog=catalog,
    )
    simulator = Simulator(
        make_policy(policy_name),
        scenario,
        contact_model=contact_model,
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
        packet_delivery_seed=packet_delivery_seed,
        packet_drop_fraction_proxy=packet_drop_fraction_proxy,
    )

    def write_hour(record: HourRecord) -> None:
        writers["state"].writerow({
            "policy": policy_name, "scenario": scenario_name, **asdict(record)
        })

    def write_event(event: Event) -> None:
        writers["events"].writerow({
            "policy": policy_name, "scenario": scenario_name, **asdict(event)
        })

    result = simulator.run(
        years,
        on_hour=write_hour if writers["state"] else None,
        on_event=write_event if writers["events"] else None,
    )
    _write_checkpoints(writers["checkpoints"], result)
    return result


def _write_rows(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _validate_args(args) -> str:
    if args.years < DEFAULT_CONFIG.minimum_percent:
        raise SystemExit("--years must be non-negative")
    if args.monte_carlo is not None:
        if args.monte_carlo <= 0:
            raise SystemExit("--monte-carlo must be a positive integer")
        if args.scenario != STOCHASTIC_SCENARIO:
            raise SystemExit(
                "--monte-carlo currently requires --scenario stochastic_post_life_events"
            )
        if args.event_catalog:
            raise SystemExit("--event-catalog cannot be combined with --monte-carlo")
        if args.write_event_catalog:
            raise SystemExit(
                "--write-event-catalog is not supported with --monte-carlo; "
                "seed catalogs are written under results/event_catalogs"
            )
    if args.event_catalog and args.scenario != STOCHASTIC_SCENARIO:
        raise SystemExit(
            "--event-catalog requires --scenario stochastic_post_life_events"
        )
    if not 0.0 <= args.packet_drop_fraction_proxy <= 1.0:
        raise SystemExit("--packet-drop-fraction-proxy must be in [0, 1]")
    if (
        args.packet_model == "legacy"
        and args.packet_delivery_model != "ideal"
    ):
        raise SystemExit(
            "--packet-delivery-model loss_retry_proxy requires "
            "--packet-model packet_proxy"
        )
    if args.write_event_catalog and args.scenario not in (
        STOCHASTIC_SCENARIO, "all"
    ):
        raise SystemExit(
            "--write-event-catalog requires a stochastic scenario"
        )
    supplied_geometry_options = getattr(args, "_supplied_geometry_options", set())
    if args.contact_model == "synthetic" and supplied_geometry_options:
        supplied_flags = ", ".join(
            GEOMETRY_OPTION_FLAGS[dest]
            for dest in sorted(supplied_geometry_options)
        )
        raise SystemExit(
            f"{supplied_flags} require --contact-model geometry"
        )
    if (args.station_lat is None) != (args.station_lon is None):
        raise SystemExit(
            "--station-lat and --station-lon must be supplied together"
        )
    return args.log_level or ("summary" if args.monte_carlo else "full")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log_level = _validate_args(args)
    try:
        contact_model = build_contact_model(args, DEFAULT_CONFIG)
    except ValueError as exc:
        raise SystemExit(f"Invalid geometry contact configuration: {exc}") from exc
    args.results_dir.mkdir(parents=True, exist_ok=True)
    _remove_logs_excluded_by_level(args.results_dir, log_level)
    total_hours = int(round(args.years * DEFAULT_CONFIG.hours_per_year))
    policies = _selected(args.policy, POLICIES)
    scenarios = _selected(args.scenario, SCENARIOS)
    summaries: list[dict[str, object]] = []
    monte_carlo_rows: list[dict[str, object]] = []
    optional_model_kwargs = {}
    if args.event_lifecycle_model != "none":
        optional_model_kwargs["event_lifecycle_model"] = (
            args.event_lifecycle_model
        )
    if args.debris_risk_model != "legacy":
        optional_model_kwargs["debris_risk_model"] = args.debris_risk_model
    if args.autonomy_model != "none":
        optional_model_kwargs["autonomy_model"] = args.autonomy_model
    if args.stationkeeping_planning_model != "legacy":
        optional_model_kwargs["stationkeeping_planning_model"] = (
            args.stationkeeping_planning_model
        )
    if args.power_model != "legacy":
        optional_model_kwargs["power_model"] = args.power_model
    if args.thermal_model != "legacy":
        optional_model_kwargs["thermal_model"] = args.thermal_model
    if args.target_model != "legacy":
        optional_model_kwargs["target_model"] = args.target_model
    if args.pointing_model != "legacy":
        optional_model_kwargs["pointing_model"] = args.pointing_model
    if args.packet_model != "legacy":
        optional_model_kwargs["packet_model"] = args.packet_model
        optional_model_kwargs["packet_drop_fraction_proxy"] = (
            args.packet_drop_fraction_proxy
        )
        if args.packet_delivery_model != "ideal":
            optional_model_kwargs["packet_delivery_model"] = (
                args.packet_delivery_model
            )

    if args.seed is not None and args.event_catalog:
        print("Note: --event-catalog provided; --seed is ignored.")

    with ExitStack() as stack:
        writers = _open_log_writers(args.results_dir, log_level, stack)
        if args.monte_carlo is not None:
            first_seed = args.seed if args.seed is not None else 0
            for seed in range(first_seed, first_seed + args.monte_carlo):
                catalog = generate_stochastic_event_catalog(
                    seed, STOCHASTIC_SCENARIO, total_hours
                )
                write_event_catalog(
                    _catalog_default_path(args.results_dir, seed), catalog
                )
                for policy_name in policies:
                    result = _run_one(
                        policy_name, STOCHASTIC_SCENARIO, args.years,
                        total_hours, catalog, writers, contact_model,
                        args.operator_view,
                        args.planning_model,
                        args.maneuver_model,
                        args.orbit_evolution_model,
                        **(
                            {
                                **optional_model_kwargs,
                                "packet_delivery_seed": seed,
                            }
                            if args.packet_model == "packet_proxy"
                            else optional_model_kwargs
                        ),
                    )
                    summary = _summary_row(result, args.years)
                    summaries.append(summary)
                    monte_carlo_rows.append(_monte_carlo_row(seed, result, summary))
        else:
            catalogs: dict[str, EventCatalog] = {}
            if STOCHASTIC_SCENARIO in scenarios:
                if args.event_catalog:
                    catalogs[STOCHASTIC_SCENARIO] = read_event_catalog(args.event_catalog)
                    if args.write_event_catalog:
                        write_event_catalog(
                            args.write_event_catalog, catalogs[STOCHASTIC_SCENARIO]
                        )
                else:
                    catalog = generate_stochastic_event_catalog(
                        args.seed, STOCHASTIC_SCENARIO, total_hours
                    )
                    catalogs[STOCHASTIC_SCENARIO] = catalog
                    if args.write_event_catalog:
                        catalog_path = args.write_event_catalog
                    elif args.scenario == STOCHASTIC_SCENARIO:
                        catalog_path = _catalog_default_path(args.results_dir, args.seed)
                    else:
                        catalog_path = None
                    if catalog_path:
                        write_event_catalog(catalog_path, catalog)

            for policy_name in policies:
                for scenario_name in scenarios:
                    result = _run_one(
                        policy_name, scenario_name, args.years, total_hours,
                        catalogs.get(scenario_name), writers, contact_model,
                        args.operator_view,
                        args.planning_model,
                        args.maneuver_model,
                        args.orbit_evolution_model,
                        **(
                            {
                                **optional_model_kwargs,
                                "packet_delivery_seed": (
                                    catalogs[scenario_name].seed
                                    if scenario_name in catalogs
                                    and catalogs[scenario_name].seed is not None
                                    else args.seed
                                    if args.seed is not None
                                    else 0
                                ),
                            }
                            if args.packet_model == "packet_proxy"
                            else optional_model_kwargs
                        ),
                    )
                    summaries.append(_summary_row(result, args.years))

    _write_rows(args.results_dir / "summary.csv", SUMMARY_FIELDS, summaries)
    if args.monte_carlo is not None:
        _write_rows(
            args.results_dir / "monte_carlo_summary.csv",
            MONTE_CARLO_FIELDS,
            monte_carlo_rows,
        )
        print(
            f"Monte Carlo complete: {len(monte_carlo_rows)} policy runs across "
            f"{args.monte_carlo} seeds."
        )
    else:
        print_table(
            ["Policy", "Scenario", "Survived", "SOC", "Health", "Downlinked GB", "Score"],
            [[row["policy"], row["scenario"], row["survived"],
              f'{row["final_soc"]:.2f}', f'{row["final_health"]:.4f}',
              f'{row["data_downlinked_gb"]:.2f}', f'{row["score"]:.4f}']
             for row in summaries],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
