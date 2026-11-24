"""Hourly execution engine for the simplified operations proxy."""

from copy import deepcopy
from dataclasses import dataclass, replace
from math import isfinite, pi
from typing import Callable, Optional

from .autonomy import (
    AUTONOMY_MODELS,
    AutonomyAuthority,
    AutonomyDecision,
    OnboardContingencyPlan,
    decide_autonomy,
    inactive_autonomy_decision,
)
from .config import DEFAULT_CONFIG, SimulationConfig
from .contacts import ContactModel, GeometryContactModel, SyntheticContactModel
from .decision import DecisionExplanation, build_decision_explanation
from .debris_risk import (
    DEBRIS_RISK_MODELS,
    DebrisRiskAssessment,
    assess_debris_risk,
)
from .event_catalog import ExternalEvent
from .event_lifecycle import (
    EventLifecycleManager,
    LifecycleDiagnostics,
    LifecycleStatus,
    LifecycleTransition,
)
from .metrics import Metrics, calculate_metrics
from .models import (
    HEALTH_FIELDS,
    ContactInfo,
    DailyPlan,
    LossReason,
    Mode,
    SatelliteState,
)
from .orbit import position_at_hour, position_at_time
from .packets import (
    PACKET_DELIVERY_MODELS,
    PACKET_MODELS,
    PacketHourAssessment,
    assess_packet_delivery,
    assess_packets_for_hour,
)
from .policies import OperatorProfile, Policy
from .pointing import (
    POINTING_MODELS,
    PointingAssessment,
    assess_pointing_for_hour,
)
from .power import (
    POWER_MODELS,
    PowerAssessment,
    assess_power_for_hour,
)
from .scenarios import Scenario
from .stationkeeping import (
    STATIONKEEPING_PLANNING_MODELS,
    StationkeepingAssessment,
    assess_stationkeeping,
)
from .thermal import (
    THERMAL_MODELS,
    ThermalAssessment,
    assess_thermal_for_hour,
)
from .targets import TARGET_MODELS, TargetAssessment, assess_target_for_hour


OPERATOR_VIEWS = ("omniscient", "delayed_telemetry")
PLANNING_MODELS = ("reactive", "risk_aware")
MANEUVER_MODELS = ("none", "stationkeeping_proxy")
ORBIT_EVOLUTION_MODELS = ("fixed", "drift_proxy")
EVENT_LIFECYCLE_MODELS = ("none", "warning_proxy")


@dataclass(frozen=True)
class Checkpoint:
    hour: int
    year: float
    soc: float
    data_buffer_gb: float
    total_health: float
    alive: bool
    mode: str
    data_downlinked_gb: float
    hours_since_contact: int
    daily_plan_age_hours: int
    sat_lat_deg: float
    sat_lon_deg: float
    sat_alt_km: float
    data_lost_gb: float
    overflow_hours: int
    effective_storage_capacity_gb: float


@dataclass(frozen=True)
class Event:
    hour: int
    year: float
    event_type: str
    description: str


@dataclass(frozen=True)
class PlanHourDetails:
    planned_mode: Mode | None
    plan_mode_index: int | None
    plan_modes_remaining: int
    energy_risk: bool | None
    storage_risk: bool | None
    expected_data_contact_min: float | None
    expected_cmd_contact_min: float | None


@dataclass(frozen=True)
class DebrisAvoidanceOutcome:
    mode: Mode
    executed: bool
    skipped: bool
    delta_v_used: float
    damage: float
    failure_reason: str | None = None


@dataclass(frozen=True)
class HourRecord:
    hour: int
    year: float
    mode: str
    soc: float
    health: float
    eps_health: float
    solar_health: float
    battery_health: float
    comms_health: float
    payload_health: float
    storage_health: float
    adcs_health: float
    obc_health: float
    thermal_health: float
    propulsion_health: float
    buffer_gb: float
    data_generated_gb: float
    data_downlinked_gb: float
    cmd_contact_min: float
    data_contact_min: float
    contact_model: str
    base_cmd_contact_min: float
    base_data_contact_min: float
    geometry_raw_visible_seconds: float | None
    geometry_usable_cmd_seconds: float | None
    geometry_usable_data_seconds: float | None
    geometry_max_elevation_deg: float | None
    geometry_min_range_km: float | None
    geometry_first_visible_offset_seconds: float | None
    geometry_last_visible_offset_seconds: float | None
    ground_station_name: str | None
    ground_station_lat_deg: float | None
    ground_station_lon_deg: float | None
    ground_station_minimum_elevation_deg: float | None
    operator_view: str
    planning_model: str
    maneuver_model: str
    orbit_evolution_model: str
    stationkeeping_planning_model: str
    event_lifecycle_model: str
    debris_risk_model: str
    autonomy_model: str
    autonomy_active_this_hour: bool
    autonomy_trigger_this_hour: str | None
    autonomy_authority_this_hour: str | None
    autonomy_selected_mode_this_hour: str | None
    autonomy_reason_this_hour: str | None
    autonomy_pre_authorized_this_hour: bool | None
    autonomy_ground_contact_required_this_hour: bool | None
    autonomy_used_uploaded_response_this_hour: bool | None
    contingency_plan_active: bool
    contingency_plan_age_hours: int | None
    contingency_plan_expires_in_hours: int | None
    lifecycle_ground_known_count: int
    lifecycle_spacecraft_known_count: int
    lifecycle_uploaded_count: int
    lifecycle_pending_count: int
    lifecycle_active_count: int
    lifecycle_missed_upload_count: int
    lifecycle_next_warning_hour: int | None
    lifecycle_next_execution_hour: int | None
    telemetry_updated_this_hour: bool
    last_telemetry_hour: int | None
    telemetry_age_hours: int
    observed_soc: float
    observed_health: float
    observed_buffer_gb: float
    observed_effective_energy_margin: float
    observed_battery_health: float
    observed_solar_health: float
    observed_comms_health: float
    observed_payload_health: float
    observed_storage_health: float
    plan_uploaded_this_hour: bool
    plan_policy: str | None
    plan_based_on_telemetry_hour: int | None
    plan_based_on_telemetry_age_hours: int | None
    planned_mode: str | None
    plan_mode_index: int | None
    plan_modes_remaining: int
    planning_energy_risk: bool | None
    planning_storage_risk: bool | None
    planning_expected_data_contact_min: float | None
    planning_expected_cmd_contact_min: float | None
    delta_v_remaining_m_per_s: float
    delta_v_used_m_per_s: float
    fuel_remaining_percent: float
    fuel_used_percent: float
    stationkeeping_delta_v_cost_percent: float
    debris_avoidance_delta_v_cost_percent: float
    maneuver_count: int
    maneuver_skipped_count: int
    orbit_drift_proxy_km: float
    orbit_altitude_offset_km: float
    orbit_phase_error_deg: float
    orbit_groundtrack_error_km: float
    orbit_geometry_degraded: bool
    orbit_correction_count: int
    orbit_correction_skipped_count: int
    maneuver_due: bool
    maneuver_executed_this_hour: bool
    maneuver_skipped_this_hour: bool
    maneuver_delta_v_used_this_hour: float
    planned_maneuver: bool
    stationkeeping_drift_risk_class_this_hour: str
    stationkeeping_priority_this_hour: int
    stationkeeping_recommended_this_hour: bool
    stationkeeping_feasible_this_hour: bool
    stationkeeping_selected_this_hour: bool
    stationkeeping_reason_this_hour: str
    stationkeeping_deferred_reason_this_hour: str | None
    stationkeeping_blocked_by_priority_this_hour: bool
    debris_conjunction_active: bool
    debris_avoidance_required_this_hour: bool
    debris_avoidance_executed_count: int
    debris_avoidance_skipped_count: int
    debris_avoidance_executed_this_hour: bool
    debris_avoidance_skipped_this_hour: bool
    debris_damage_events: int
    debris_damage_this_hour: float
    debris_damage_accumulated: float
    debris_risk_class_this_hour: str | None
    debris_impact_zone_this_hour: str | None
    debris_risk_score_this_hour: float | None
    debris_object_size_cm_this_hour: float | None
    debris_miss_distance_proxy_m_this_hour: float | None
    debris_damage_targets_this_hour: str | None
    orbit_drift_warning: bool
    orbit_drift_critical: bool
    orbit_drift_damage_events: int
    orbit_drift_damage_this_hour: float
    orbit_drift_damage_accumulated: float
    hours_since_contact: int
    daily_plan_age_hours: int
    valid_daily_plan: bool
    sat_lat_deg: float
    sat_lon_deg: float
    sat_alt_km: float
    orbit_phase_deg: float
    effective_orbit_altitude_km: float
    effective_orbit_phase_deg: float
    fixed_orbit_sat_lat_deg: float
    fixed_orbit_sat_lon_deg: float
    fixed_orbit_alt_km: float
    fixed_orbit_phase_deg: float
    data_lost_gb: float
    overflow_hours: int
    effective_storage_capacity_gb: float
    pointing_efficiency: float
    effective_downlink_rate_gb_per_min: float
    effective_imaging_rate_gb_per_hour: float
    effective_energy_margin: float
    minimum_soc: float
    minimum_health: float
    power_model: str
    sunlight_factor_this_hour: float | None
    eclipse_this_hour: bool | None
    eclipse_fraction_reference: float | None
    power_load_proxy_w_this_hour: float | None
    power_generation_proxy_w_this_hour: float | None
    net_power_proxy_w_this_hour: float | None
    soc_delta_power_model_this_hour: float
    thermal_model: str
    thermal_load_proxy_this_hour: float | None
    thermal_hot_stress_this_hour: float | None
    thermal_cold_stress_this_hour: float | None
    thermal_stress_this_hour: float | None
    thermal_degradation_this_hour: float
    thermal_reason_this_hour: str | None
    target_model: str
    target_opportunity_this_hour: bool | None
    target_selected_this_hour: bool | None
    target_scene_id_this_hour: str | None
    target_scene_area_km2_this_hour: float | None
    target_priority_this_hour: int | None
    target_imagery_mode_this_hour: str | None
    target_data_multiplier_this_hour: float
    target_missed_reason_this_hour: str | None
    target_reason_this_hour: str | None
    pointing_model: str
    pointing_required_this_hour: bool | None
    pointing_quality_this_hour: float | None
    pointing_multiplier_this_hour: float
    pointing_limited_this_hour: bool | None
    pointing_missed_this_hour: bool | None
    pointing_off_nadir_proxy_deg_this_hour: float | None
    pointing_slew_proxy_deg_this_hour: float | None
    pointing_reason_this_hour: str | None
    packet_model: str
    packet_delivery_model: str
    telemetry_packet_generated_this_hour: bool | None
    telemetry_packet_delivery_attempted_this_hour: bool | None
    telemetry_packet_downlinked_this_hour: bool | None
    telemetry_packet_delivery_failed_this_hour: bool | None
    command_packets_attempted_this_hour: int
    command_packets_uploaded_this_hour: int
    command_packets_failed_this_hour: int
    daily_plan_packet_delivery_attempted_this_hour: bool | None
    daily_plan_packet_uploaded_this_hour: bool | None
    daily_plan_packet_delivery_failed_this_hour: bool | None
    packet_uplink_kb_this_hour: float
    packet_downlink_kb_this_hour: float
    packet_reason_this_hour: str | None
    packet_delivery_reason_this_hour: str | None


@dataclass
class SimulationResult:
    policy_name: str
    scenario_name: str
    requested_years: float
    total_hours: int
    state: SatelliteState
    metrics: Metrics
    checkpoints: list[Checkpoint]
    events: list[Event]
    operator_view: str = "omniscient"
    planning_model: str = "reactive"
    maneuver_model: str = "none"
    orbit_evolution_model: str = "fixed"
    stationkeeping_planning_model: str = "legacy"
    event_lifecycle_model: str = "none"
    debris_risk_model: str = "legacy"
    autonomy_model: str = "none"
    autonomous_action_count: int = 0
    autonomous_safe_mode_count: int = 0
    autonomous_standby_count: int = 0
    autonomous_downlink_count: int = 0
    autonomous_maneuver_count: int = 0
    contingency_plan_upload_count: int = 0
    contingency_plan_expired_count: int = 0
    high_or_severe_debris_events: int = 0
    severe_debris_events: int = 0
    max_debris_risk_score: float = 0.0
    most_common_debris_impact_zone: str | None = None
    fuel_remaining_percent: float = 100.0
    fuel_used_percent: float = 0.0
    stationkeeping_delta_v_cost_percent: float = 0.0
    debris_avoidance_delta_v_cost_percent: float = 0.0
    stationkeeping_recommended_count: int = 0
    stationkeeping_selected_count: int = 0
    stationkeeping_deferred_count: int = 0
    stationkeeping_unresolved_critical_drift_hours: int = 0
    max_orbit_drift_proxy_km: float = 0.0
    max_orbit_groundtrack_error_km: float = 0.0
    max_orbit_phase_error_deg: float = 0.0
    power_model: str = "legacy"
    eclipse_hours: int = 0
    sunlight_hours: int = 0
    eclipse_fraction_observed: float | None = None
    min_sunlight_factor: float | None = None
    average_sunlight_factor: float | None = None
    thermal_model: str = "legacy"
    thermal_hot_stress_hours: int = 0
    thermal_cold_stress_hours: int = 0
    thermal_stress_hours: int = 0
    max_thermal_stress: float = 0.0
    total_thermal_degradation: float = 0.0
    min_thermal_health: float = 1.0
    target_model: str = "legacy"
    target_opportunity_hours: int = 0
    target_selected_hours: int = 0
    target_missed_hours: int = 0
    target_area_imaged_km2: float = 0.0
    target_priority_score_total: int = 0
    target_panchromatic_scenes: int = 0
    target_multispectral_scenes: int = 0
    pointing_model: str = "legacy"
    pointing_required_hours: int = 0
    pointing_limited_hours: int = 0
    pointing_missed_hours: int = 0
    min_pointing_quality: float | None = None
    average_pointing_quality: float | None = None
    pointing_imaging_loss_gb_proxy: float = 0.0
    pointing_downlink_loss_gb_proxy: float = 0.0
    packet_model: str = "legacy"
    packet_delivery_model: str = "ideal"
    packet_delivery_seed: int = 0
    packet_drop_fraction_proxy: float = 0.10
    telemetry_packets_generated: int = 0
    telemetry_delivery_attempts: int = 0
    telemetry_packets_downlinked: int = 0
    telemetry_delivery_failures: int = 0
    command_packet_attempts: int = 0
    command_packets_uploaded: int = 0
    command_packet_failures: int = 0
    daily_plan_packet_attempts: int = 0
    daily_plan_packets_uploaded: int = 0
    daily_plan_packet_failures: int = 0
    packet_delivery_failure_events: int = 0
    max_telemetry_age_hours: int = 0
    packet_uplink_kb_total: float = 0.0
    packet_downlink_kb_total: float = 0.0

    def as_dict(self) -> dict:
        return {
            "policy": self.policy_name,
            "scenario": self.scenario_name,
            "operator_view": self.operator_view,
            "planning_model": self.planning_model,
            "maneuver_model": self.maneuver_model,
            "orbit_evolution_model": self.orbit_evolution_model,
            "stationkeeping_planning_model": (
                self.stationkeeping_planning_model
            ),
            "power_model": self.power_model,
            "eclipse_hours": self.eclipse_hours,
            "sunlight_hours": self.sunlight_hours,
            "eclipse_fraction_observed": self.eclipse_fraction_observed,
            "min_sunlight_factor": self.min_sunlight_factor,
            "average_sunlight_factor": self.average_sunlight_factor,
            "thermal_model": self.thermal_model,
            "thermal_hot_stress_hours": self.thermal_hot_stress_hours,
            "thermal_cold_stress_hours": self.thermal_cold_stress_hours,
            "thermal_stress_hours": self.thermal_stress_hours,
            "max_thermal_stress": self.max_thermal_stress,
            "total_thermal_degradation": self.total_thermal_degradation,
            "min_thermal_health": self.min_thermal_health,
            "target_model": self.target_model,
            "target_opportunity_hours": self.target_opportunity_hours,
            "target_selected_hours": self.target_selected_hours,
            "target_missed_hours": self.target_missed_hours,
            "target_area_imaged_km2": self.target_area_imaged_km2,
            "target_priority_score_total": self.target_priority_score_total,
            "target_panchromatic_scenes": self.target_panchromatic_scenes,
            "target_multispectral_scenes": self.target_multispectral_scenes,
            "pointing_model": self.pointing_model,
            "pointing_required_hours": self.pointing_required_hours,
            "pointing_limited_hours": self.pointing_limited_hours,
            "pointing_missed_hours": self.pointing_missed_hours,
            "min_pointing_quality": self.min_pointing_quality,
            "average_pointing_quality": self.average_pointing_quality,
            "pointing_imaging_loss_gb_proxy": (
                self.pointing_imaging_loss_gb_proxy
            ),
            "pointing_downlink_loss_gb_proxy": (
                self.pointing_downlink_loss_gb_proxy
            ),
            "packet_model": self.packet_model,
            "packet_delivery_model": self.packet_delivery_model,
            "packet_delivery_seed": self.packet_delivery_seed,
            "packet_drop_fraction_proxy": self.packet_drop_fraction_proxy,
            "telemetry_packets_generated": (
                self.telemetry_packets_generated
            ),
            "telemetry_delivery_attempts": self.telemetry_delivery_attempts,
            "telemetry_packets_downlinked": (
                self.telemetry_packets_downlinked
            ),
            "telemetry_delivery_failures": (
                self.telemetry_delivery_failures
            ),
            "command_packet_attempts": self.command_packet_attempts,
            "command_packets_uploaded": self.command_packets_uploaded,
            "command_packet_failures": self.command_packet_failures,
            "daily_plan_packet_attempts": self.daily_plan_packet_attempts,
            "daily_plan_packets_uploaded": (
                self.daily_plan_packets_uploaded
            ),
            "daily_plan_packet_failures": self.daily_plan_packet_failures,
            "packet_delivery_failure_events": (
                self.packet_delivery_failure_events
            ),
            "max_telemetry_age_hours": self.max_telemetry_age_hours,
            "packet_uplink_kb_total": self.packet_uplink_kb_total,
            "packet_downlink_kb_total": self.packet_downlink_kb_total,
            "event_lifecycle_model": self.event_lifecycle_model,
            "debris_risk_model": self.debris_risk_model,
            "autonomy_model": self.autonomy_model,
            "autonomous_action_count": self.autonomous_action_count,
            "autonomous_safe_mode_count": self.autonomous_safe_mode_count,
            "autonomous_standby_count": self.autonomous_standby_count,
            "autonomous_downlink_count": self.autonomous_downlink_count,
            "autonomous_maneuver_count": self.autonomous_maneuver_count,
            "contingency_plan_upload_count": (
                self.contingency_plan_upload_count
            ),
            "contingency_plan_expired_count": (
                self.contingency_plan_expired_count
            ),
            "requested_years": self.requested_years,
            "total_hours": self.total_hours,
            "hours_completed": self.state.hours_completed,
            "alive": self.state.alive,
            "loss_reason": self.state.loss_reason.value if self.state.loss_reason else None,
            "final_soc": self.state.soc,
            "final_total_health": self.state.total_health(),
            "data_buffer_gb": self.state.data_buffer_gb,
            "total_data_generated_gb": self.state.total_data_generated_gb,
            "total_data_downlinked_gb": self.state.total_data_downlinked_gb,
            "total_images_taken": self.state.total_images_taken,
            "data_lost_gb": self.state.data_lost_gb,
            "overflow_hours": self.state.overflow_hours,
            "delta_v_remaining_m_per_s": self.state.delta_v_remaining_m_per_s,
            "delta_v_used_m_per_s": self.state.delta_v_used_m_per_s,
            "fuel_remaining_percent": self.fuel_remaining_percent,
            "fuel_used_percent": self.fuel_used_percent,
            "stationkeeping_delta_v_cost_percent": (
                self.stationkeeping_delta_v_cost_percent
            ),
            "debris_avoidance_delta_v_cost_percent": (
                self.debris_avoidance_delta_v_cost_percent
            ),
            "stationkeeping_recommended_count": (
                self.stationkeeping_recommended_count
            ),
            "stationkeeping_selected_count": (
                self.stationkeeping_selected_count
            ),
            "stationkeeping_deferred_count": (
                self.stationkeeping_deferred_count
            ),
            "stationkeeping_unresolved_critical_drift_hours": (
                self.stationkeeping_unresolved_critical_drift_hours
            ),
            "max_orbit_drift_proxy_km": self.max_orbit_drift_proxy_km,
            "max_orbit_groundtrack_error_km": (
                self.max_orbit_groundtrack_error_km
            ),
            "max_orbit_phase_error_deg": self.max_orbit_phase_error_deg,
            "maneuver_count": self.state.maneuver_count,
            "maneuver_skipped_count": self.state.maneuver_skipped_count,
            "orbit_drift_proxy_km": self.state.orbit_drift_proxy_km,
            "orbit_altitude_offset_km": self.state.orbit_altitude_offset_km,
            "orbit_phase_error_deg": self.state.orbit_phase_error_deg,
            "orbit_groundtrack_error_km": (
                self.state.orbit_groundtrack_error_km
            ),
            "orbit_geometry_degraded": self.state.orbit_geometry_degraded,
            "orbit_correction_count": self.state.orbit_correction_count,
            "orbit_correction_skipped_count": (
                self.state.orbit_correction_skipped_count
            ),
            "debris_avoidance_executed_count": (
                self.state.debris_avoidance_executed_count
            ),
            "debris_avoidance_skipped_count": (
                self.state.debris_avoidance_skipped_count
            ),
            "debris_damage_events": self.state.debris_damage_events,
            "debris_damage_accumulated": (
                self.state.debris_damage_accumulated
            ),
            "high_or_severe_debris_events": (
                self.high_or_severe_debris_events
            ),
            "severe_debris_events": self.severe_debris_events,
            "max_debris_risk_score": self.max_debris_risk_score,
            "most_common_debris_impact_zone": (
                self.most_common_debris_impact_zone
            ),
            "orbit_drift_damage_events": self.state.orbit_drift_damage_events,
            "orbit_drift_damage_accumulated": (
                self.state.orbit_drift_damage_accumulated
            ),
            "payload_unavailable_hours": self.state.payload_unavailable_hours,
            "minimum_soc": self.state.minimum_soc,
            "minimum_health": self.state.minimum_health,
            "backup_mode": self.state.backup_mode,
            "emergency_beacon_mode": self.state.emergency_beacon_mode,
            "mode_hours": {mode.value: hours for mode, hours in self.state.mode_hours.items()},
            "metrics": self.metrics.as_dict(),
            "checkpoints": [checkpoint.__dict__ for checkpoint in self.checkpoints],
            "events": [event.__dict__ for event in self.events],
        }


class Simulator:
    def __init__(
        self,
        policy: Policy,
        scenario: Optional[Scenario] = None,
        config: SimulationConfig = DEFAULT_CONFIG,
        contact_model: Optional[ContactModel] = None,
        operator_view: str = "omniscient",
        planning_model: str = "reactive",
        maneuver_model: str = "none",
        orbit_evolution_model: str = "fixed",
        stationkeeping_planning_model: str = "legacy",
        event_lifecycle_model: str = "none",
        debris_risk_model: str = "legacy",
        autonomy_model: str = "none",
        power_model: str = "legacy",
        thermal_model: str = "legacy",
        target_model: str = "legacy",
        pointing_model: str = "legacy",
        packet_model: str = "legacy",
        packet_delivery_model: str = "ideal",
        packet_delivery_seed: int = 0,
        packet_drop_fraction_proxy: float | None = None,
    ) -> None:
        if operator_view not in OPERATOR_VIEWS:
            choices = ", ".join(OPERATOR_VIEWS)
            raise ValueError(
                f"operator_view must be one of: {choices}"
            )
        if planning_model not in PLANNING_MODELS:
            choices = ", ".join(PLANNING_MODELS)
            raise ValueError(f"planning_model must be one of: {choices}")
        if maneuver_model not in MANEUVER_MODELS:
            choices = ", ".join(MANEUVER_MODELS)
            raise ValueError(f"maneuver_model must be one of: {choices}")
        if orbit_evolution_model not in ORBIT_EVOLUTION_MODELS:
            choices = ", ".join(ORBIT_EVOLUTION_MODELS)
            raise ValueError(
                f"orbit_evolution_model must be one of: {choices}"
            )
        if stationkeeping_planning_model not in STATIONKEEPING_PLANNING_MODELS:
            choices = ", ".join(STATIONKEEPING_PLANNING_MODELS)
            raise ValueError(
                "stationkeeping_planning_model must be one of: " + choices
            )
        if power_model not in POWER_MODELS:
            choices = ", ".join(POWER_MODELS)
            raise ValueError(f"power_model must be one of: {choices}")
        if thermal_model not in THERMAL_MODELS:
            choices = ", ".join(THERMAL_MODELS)
            raise ValueError(f"thermal_model must be one of: {choices}")
        if target_model not in TARGET_MODELS:
            choices = ", ".join(TARGET_MODELS)
            raise ValueError(f"target_model must be one of: {choices}")
        if pointing_model not in POINTING_MODELS:
            choices = ", ".join(POINTING_MODELS)
            raise ValueError(f"pointing_model must be one of: {choices}")
        if packet_model not in PACKET_MODELS:
            choices = ", ".join(PACKET_MODELS)
            raise ValueError(f"packet_model must be one of: {choices}")
        if packet_delivery_model not in PACKET_DELIVERY_MODELS:
            choices = ", ".join(PACKET_DELIVERY_MODELS)
            raise ValueError(
                f"packet_delivery_model must be one of: {choices}"
            )
        if packet_model == "legacy" and packet_delivery_model != "ideal":
            raise ValueError(
                "non-ideal packet delivery requires packet_model='packet_proxy'"
            )
        if not isinstance(packet_delivery_seed, int) or isinstance(
            packet_delivery_seed, bool
        ):
            raise ValueError("packet_delivery_seed must be an integer")
        resolved_drop_fraction = (
            config.packet_drop_fraction_proxy
            if packet_drop_fraction_proxy is None
            else packet_drop_fraction_proxy
        )
        if (
            not isinstance(resolved_drop_fraction, (int, float))
            or isinstance(resolved_drop_fraction, bool)
            or not isfinite(resolved_drop_fraction)
            or not 0.0 <= resolved_drop_fraction <= 1.0
        ):
            raise ValueError("packet_drop_fraction_proxy must be in [0, 1]")
        if event_lifecycle_model not in EVENT_LIFECYCLE_MODELS:
            choices = ", ".join(EVENT_LIFECYCLE_MODELS)
            raise ValueError(
                f"event_lifecycle_model must be one of: {choices}"
            )
        if debris_risk_model not in DEBRIS_RISK_MODELS:
            choices = ", ".join(DEBRIS_RISK_MODELS)
            raise ValueError(
                f"debris_risk_model must be one of: {choices}"
            )
        if autonomy_model not in AUTONOMY_MODELS:
            choices = ", ".join(AUTONOMY_MODELS)
            raise ValueError(f"autonomy_model must be one of: {choices}")
        self.policy = policy
        self.scenario = scenario or Scenario()
        self.config = config
        self.contact_model = contact_model or SyntheticContactModel(config)
        self.operator_view = operator_view
        self.planning_model = planning_model
        self.maneuver_model = maneuver_model
        self.orbit_evolution_model = orbit_evolution_model
        self.stationkeeping_planning_model = stationkeeping_planning_model
        self.power_model = power_model
        self.thermal_model = thermal_model
        self.target_model = target_model
        self.pointing_model = pointing_model
        self.packet_model = packet_model
        self.packet_delivery_model = packet_delivery_model
        self.packet_delivery_seed = packet_delivery_seed
        self.packet_drop_fraction_proxy = resolved_drop_fraction
        self.event_lifecycle_model = event_lifecycle_model
        self.debris_risk_model = debris_risk_model
        self.autonomy_model = autonomy_model
        self.observed_state: SatelliteState | None = None
        self.last_telemetry_hour: int | None = None
        self.telemetry_age_hours = 0
        self.telemetry_updated_this_hour = False
        self._resolved_debris_conjunctions: set[ExternalEvent] = set()
        self._state_aware_geometry_summaries: dict[int, object] = {}
        self._last_run_completed_hour: int | None = None
        self.lifecycle_manager = self._new_lifecycle_manager()
        self.contingency_plan: OnboardContingencyPlan | None = None
        self.autonomous_action_count = 0
        self.autonomous_safe_mode_count = 0
        self.autonomous_standby_count = 0
        self.autonomous_downlink_count = 0
        self.autonomous_maneuver_count = 0
        self.contingency_plan_upload_count = 0
        self.contingency_plan_expired_count = 0
        self._reset_stationkeeping_context()

    def _reset_stationkeeping_context(self) -> None:
        self.stationkeeping_recommended_count = 0
        self.stationkeeping_selected_count = 0
        self.stationkeeping_deferred_count = 0
        self.stationkeeping_unresolved_critical_drift_hours = 0
        self.max_orbit_drift_proxy_km = 0.0
        self.max_orbit_groundtrack_error_km = 0.0
        self.max_orbit_phase_error_deg = 0.0

    def _stationkeeping_resource_flags(
        self, state: SatelliteState
    ) -> tuple[bool, bool, bool]:
        required_delta_v = max(
            self.config.minimum_delta_v_for_maneuver_m_per_s,
            self.config.stationkeeping_delta_v_cost_m_per_s,
        )
        return (
            state.delta_v_remaining_m_per_s >= required_delta_v,
            self._maneuver_energy_sufficient(state),
            state.propulsion_health
            >= self.config.propulsion_maneuver_health_threshold,
        )

    def _stationkeeping_assessment(
        self,
        state: SatelliteState,
        proposed_mode: Mode,
        *,
        emergency_beacon_active: bool = False,
        critical_energy_safe_priority: bool = False,
        debris_avoidance_priority: bool = False,
        projected_critical_within_plan: bool = False,
    ) -> StationkeepingAssessment:
        delta_v, energy, propulsion = self._stationkeeping_resource_flags(
            state
        )
        return assess_stationkeeping(
            state=state,
            proposed_mode=proposed_mode,
            maneuver_model=self.maneuver_model,
            orbit_evolution_model=self.orbit_evolution_model,
            stationkeeping_planning_model=(
                self.stationkeeping_planning_model
            ),
            delta_v_available=delta_v,
            energy_available=energy,
            propulsion_available=propulsion,
            emergency_beacon_active=emergency_beacon_active,
            critical_energy_safe_priority=critical_energy_safe_priority,
            debris_avoidance_priority=debris_avoidance_priority,
            projected_critical_within_plan=projected_critical_within_plan,
            config=self.config,
        )

    def _record_stationkeeping_assessment(
        self, assessment: StationkeepingAssessment
    ) -> None:
        if assessment.recommended:
            self.stationkeeping_recommended_count += 1
        if assessment.selected:
            self.stationkeeping_selected_count += 1
        elif assessment.recommended:
            self.stationkeeping_deferred_count += 1

    def _update_stationkeeping_extrema(
        self, state: SatelliteState
    ) -> None:
        self.max_orbit_drift_proxy_km = max(
            self.max_orbit_drift_proxy_km,
            state.orbit_drift_proxy_km,
        )
        self.max_orbit_groundtrack_error_km = max(
            self.max_orbit_groundtrack_error_km,
            abs(state.orbit_groundtrack_error_km),
        )
        self.max_orbit_phase_error_deg = max(
            self.max_orbit_phase_error_deg,
            abs(state.orbit_phase_error_deg),
        )

    def _new_lifecycle_manager(self) -> EventLifecycleManager | None:
        if self.event_lifecycle_model != "warning_proxy":
            return None
        catalog_or_events = getattr(self.scenario, "event_catalog", ()) or ()
        return EventLifecycleManager(
            catalog_or_events,
            hours_per_year=self.config.hours_per_year,
        )

    def lifecycle_diagnostics(
        self, current_hour: int | None = None
    ) -> LifecycleDiagnostics:
        """Return read-only awareness counters for reports and state logs."""
        if self.lifecycle_manager is None:
            return LifecycleDiagnostics()
        return self.lifecycle_manager.diagnostics(current_hour)

    def assess_debris_event(
        self, event: ExternalEvent
    ) -> DebrisRiskAssessment:
        """Return the deterministic proxy assessment for one catalog event."""
        event_id: str | None = None
        if self.lifecycle_manager is not None:
            try:
                event_id = self.lifecycle_manager.event_id_for_source(event)
            except (KeyError, ValueError):
                event_id = None
        return assess_debris_risk(event, event_id)

    def debris_risk_assessments(self) -> tuple[DebrisRiskAssessment, ...]:
        """Assess debris events in the bounded scenario catalog for reports."""
        if self.debris_risk_model != "severity_proxy":
            return ()
        catalog = getattr(self.scenario, "event_catalog", None)
        source_events = getattr(catalog, "events", ()) if catalog else ()
        return tuple(
            self.assess_debris_event(event)
            for event in source_events
            if event.event_type.lower() == "debris_conjunction"
        )

    def _debris_damage_for_event(
        self, event: ExternalEvent
    ) -> tuple[tuple[str, ...], float, DebrisRiskAssessment | None]:
        """Select legacy or impact-zone damage without changing gating."""
        if self.debris_risk_model == "legacy":
            targets = tuple(
                target.strip() for target in event.target.split(",")
                if target.strip()
            )
            return (
                targets,
                max(self.config.minimum_percent, event.effect),
                None,
            )
        assessment = self.assess_debris_event(event)
        return (
            assessment.damage_targets,
            assessment.damage_effect,
            assessment,
        )

    def _highest_debris_assessment(
        self, events: tuple[ExternalEvent, ...]
    ) -> DebrisRiskAssessment | None:
        if self.debris_risk_model != "severity_proxy" or not events:
            return None
        return max(
            (self.assess_debris_event(event) for event in events),
            key=lambda assessment: (
                assessment.risk_score,
                -assessment.source_event_hour,
                assessment.event_id or "",
            ),
        )

    def _reset_autonomy_context(self) -> None:
        self.contingency_plan = None
        self.autonomous_action_count = 0
        self.autonomous_safe_mode_count = 0
        self.autonomous_standby_count = 0
        self.autonomous_downlink_count = 0
        self.autonomous_maneuver_count = 0
        self.contingency_plan_upload_count = 0
        self.contingency_plan_expired_count = 0

    def _update_contingency_plan(
        self,
        contact: ContactInfo,
        hour: int,
        *,
        upload_allowed: bool = True,
    ) -> tuple[bool, bool]:
        """Expire or upload the bounded authority envelope using final contact."""
        uploaded = False
        expired = False
        if self.contingency_plan is not None and not self.contingency_plan.is_active(
            hour
        ):
            self.contingency_plan = None
            self.contingency_plan_expired_count += 1
            expired = True
        if self.autonomy_model not in (
            "contingency_plan",
            "limited_maneuver_authority",
        ):
            return uploaded, expired
        if (
            self.contingency_plan is None
            and contact.cmd_contact_min > self.config.minimum_percent
            and upload_allowed
        ):
            limited = self.autonomy_model == "limited_maneuver_authority"
            self.contingency_plan = OnboardContingencyPlan(
                uploaded_hour=hour,
                expires_hour=hour + self.config.plan_duration_hours,
                authority=(
                    AutonomyAuthority.LIMITED_MANEUVER.value
                    if limited
                    else AutonomyAuthority.MODE_SELECTION.value
                ),
                allow_safe_mode=True,
                allow_storage_protection=True,
                allow_thermal_protection=True,
                allow_limited_maneuver=limited,
                source_policy=self.policy.name,
            )
            self.contingency_plan_upload_count += 1
            uploaded = True
        return uploaded, expired

    def _contingency_upload_needed(
        self, contact: ContactInfo, hour: int
    ) -> bool:
        return (
            self.autonomy_model in (
                "contingency_plan",
                "limited_maneuver_authority",
            )
            and contact.cmd_contact_min > self.config.minimum_percent
            and (
                self.contingency_plan is None
                or not self.contingency_plan.is_active(hour)
            )
        )

    @staticmethod
    def _stored_daily_plan_valid(state: SatelliteState) -> bool:
        return (
            state.current_plan is not None
            and state.daily_plan_age_hours < state.current_plan.duration_hours
            and state.daily_plan_age_hours < len(state.current_plan.planned_modes)
        )

    def _autonomy_decision(
        self,
        state: SatelliteState,
        contact: ContactInfo,
        hour: int,
        proposed_mode: Mode,
        lifecycle_eligible_ids: tuple[str, ...],
    ) -> AutonomyDecision:
        if self.autonomy_model == "none":
            return inactive_autonomy_decision(self.autonomy_model)
        delta_v_cost = (
            self.config.debris_avoidance_delta_v_cost_m_per_s
            * len(lifecycle_eligible_ids)
            if lifecycle_eligible_ids
            else self.config.stationkeeping_delta_v_cost_m_per_s
        )
        return decide_autonomy(
            autonomy_model=self.autonomy_model,
            state=state,
            contact=contact,
            proposed_mode=proposed_mode,
            contingency_plan=self.contingency_plan,
            hour=hour,
            effective_energy_margin=self.effective_energy_margin(state),
            effective_storage_capacity_gb=(
                self.effective_storage_capacity_gb(state)
            ),
            stored_daily_plan_valid=self._stored_daily_plan_valid(state),
            uploaded_debris_response_eligible=bool(lifecycle_eligible_ids),
            maneuver_model=self.maneuver_model,
            maneuver_resources_available=self._maneuver_resources_available(
                state, delta_v_cost
            ),
            config=self.config,
        )

    def _record_autonomy_decision(
        self, decision: AutonomyDecision
    ) -> None:
        if not decision.active or decision.selected_mode is None:
            return
        self.autonomous_action_count += 1
        selected = Mode(decision.selected_mode)
        if selected == Mode.SAFE:
            self.autonomous_safe_mode_count += 1
        elif selected == Mode.STANDBY:
            self.autonomous_standby_count += 1
        elif selected == Mode.DOWNLINK:
            self.autonomous_downlink_count += 1
        elif selected == Mode.MANEUVER:
            self.autonomous_maneuver_count += 1

    def _contingency_plan_diagnostics(
        self, hour: int
    ) -> tuple[bool, int | None, int | None]:
        plan = self.contingency_plan
        if plan is None or not plan.is_active(hour):
            return False, None, None
        return (
            True,
            hour - plan.uploaded_hour,
            plan.expires_hour - hour,
        )

    def nominal_contact(
        self,
        hour: int,
        state: SatelliteState | None = None,
        record_diagnostics: bool = True,
    ) -> ContactInfo:
        if (
            isinstance(self.contact_model, GeometryContactModel)
            and self.orbit_evolution_model == "drift_proxy"
            and state is not None
        ):
            summary = self.contact_model.contact_summary_at_hour_for_config(
                hour, self._effective_orbit_config(state)
            )
            if record_diagnostics:
                self._state_aware_geometry_summaries[hour] = summary
            return ContactInfo(
                summary.cmd_contact_min, summary.data_contact_min
            )
        return self.contact_model.contact_at_hour(hour)

    def _uses_state_aware_geometry(self) -> bool:
        return (
            isinstance(self.contact_model, GeometryContactModel)
            and self.orbit_evolution_model == "drift_proxy"
        )

    def _effective_orbit_config(
        self, state: SatelliteState
    ) -> SimulationConfig:
        """Build one immutable config for the selected proxy orbit state."""
        if self.orbit_evolution_model != "drift_proxy":
            return self.config
        circumference_km = 2.0 * pi * self.config.earth_radius_km
        groundtrack_degrees = (
            state.orbit_groundtrack_error_km
            / circumference_km
            * self.config.degrees_per_circle
        )
        altitude_km = max(
            self.config.minimum_percent,
            self.config.orbit_altitude_km
            + state.orbit_altitude_offset_km,
        )
        return replace(
            self.config,
            orbit_altitude_km=altitude_km,
            orbit_initial_phase_deg=(
                self.config.orbit_initial_phase_deg
                + state.orbit_phase_error_deg
            ),
            orbit_raan_deg=(
                self.config.orbit_raan_deg + groundtrack_degrees
            ),
        )

    def _active_orbit_position(
        self, state: SatelliteState, hours_since_start: float
    ):
        return position_at_time(
            hours_since_start, self._effective_orbit_config(state)
        )

    def _contact_diagnostics(
        self, hour: int, base_contact: ContactInfo
    ) -> dict[str, object]:
        if isinstance(self.contact_model, SyntheticContactModel):
            model_name = "synthetic"
        elif isinstance(self.contact_model, GeometryContactModel):
            model_name = "geometry"
        else:
            model_name = self.contact_model.__class__.__name__

        diagnostics: dict[str, object] = {
            "contact_model": model_name,
            "base_cmd_contact_min": base_contact.cmd_contact_min,
            "base_data_contact_min": base_contact.data_contact_min,
            "geometry_raw_visible_seconds": None,
            "geometry_usable_cmd_seconds": None,
            "geometry_usable_data_seconds": None,
            "geometry_max_elevation_deg": None,
            "geometry_min_range_km": None,
            "geometry_first_visible_offset_seconds": None,
            "geometry_last_visible_offset_seconds": None,
            "ground_station_name": None,
            "ground_station_lat_deg": None,
            "ground_station_lon_deg": None,
            "ground_station_minimum_elevation_deg": None,
        }
        if (
            isinstance(self.contact_model, GeometryContactModel)
            and self.orbit_evolution_model == "drift_proxy"
            and hour in self._state_aware_geometry_summaries
        ):
            summary = self._state_aware_geometry_summaries[hour]
        else:
            summary_method = getattr(
                self.contact_model, "contact_summary_at_hour", None
            )
            if not callable(summary_method):
                return diagnostics
            # The fixed geometry model has already cached this hour through
            # contact_at_hour, so this lookup does not repeat visibility sampling.
            summary = summary_method(hour)
        diagnostics.update({
            "geometry_raw_visible_seconds": getattr(
                summary, "raw_visible_seconds", None
            ),
            "geometry_usable_cmd_seconds": getattr(
                summary, "usable_cmd_seconds", None
            ),
            "geometry_usable_data_seconds": getattr(
                summary, "usable_data_seconds", None
            ),
            "geometry_max_elevation_deg": getattr(
                summary, "max_elevation_deg", None
            ),
            "geometry_min_range_km": getattr(summary, "min_range_km", None),
            "geometry_first_visible_offset_seconds": getattr(
                summary, "first_visible_offset_seconds", None
            ),
            "geometry_last_visible_offset_seconds": getattr(
                summary, "last_visible_offset_seconds", None
            ),
        })
        station = getattr(self.contact_model, "station", None)
        if station is not None:
            diagnostics.update({
                "ground_station_name": getattr(station, "name", None),
                "ground_station_lat_deg": getattr(
                    station, "latitude_deg", None
                ),
                "ground_station_lon_deg": getattr(
                    station, "longitude_deg", None
                ),
                "ground_station_minimum_elevation_deg": getattr(
                    station, "minimum_elevation_deg", None
                ),
            })
        return diagnostics

    def _update_observed_state(
        self,
        real_state: SatelliteState,
        contact: ContactInfo,
        hour: int,
        *,
        delivery_allowed: bool = True,
    ) -> None:
        self.telemetry_updated_this_hour = False
        if (
            contact.cmd_contact_min > self.config.minimum_percent
            and delivery_allowed
        ):
            self.observed_state = deepcopy(real_state)
            self.last_telemetry_hour = hour
            self.telemetry_updated_this_hour = True
        if self.last_telemetry_hour is None:
            self.telemetry_age_hours = 0
        else:
            self.telemetry_age_hours = hour - self.last_telemetry_hour

    def _policy_state(self, real_state: SatelliteState) -> SatelliteState:
        source = (
            real_state
            if self.operator_view == "omniscient"
            else self.observed_state
        )
        if source is None:
            raise RuntimeError("observed state must be initialized before selection")
        # Policies receive a defensive copy, never the persistent observation or
        # the mutable real onboard state.
        return deepcopy(source)

    def _operator_diagnostics(
        self, policy_state: SatelliteState
    ) -> dict[str, object]:
        return {
            "operator_view": self.operator_view,
            "telemetry_updated_this_hour": self.telemetry_updated_this_hour,
            "last_telemetry_hour": self.last_telemetry_hour,
            "telemetry_age_hours": self.telemetry_age_hours,
            "observed_soc": policy_state.soc,
            "observed_health": policy_state.total_health(self.config),
            "observed_buffer_gb": policy_state.data_buffer_gb,
            "observed_effective_energy_margin": self.effective_energy_margin(
                policy_state
            ),
            "observed_battery_health": policy_state.battery_health,
            "observed_solar_health": policy_state.solar_health,
            "observed_comms_health": policy_state.comms_health,
            "observed_payload_health": policy_state.payload_health,
            "observed_storage_health": policy_state.storage_health,
        }

    def run(
        self,
        years: float,
        state: Optional[SatelliteState] = None,
        on_checkpoint: Optional[Callable[[Checkpoint], None]] = None,
        on_hour: Optional[Callable[[HourRecord], None]] = None,
        on_event: Optional[Callable[[Event], None]] = None,
        start_hour: int = 0,
        on_decision_explanation: Optional[
            Callable[[DecisionExplanation], None]
        ] = None,
        on_lifecycle_transition: Optional[
            Callable[[LifecycleTransition], None]
        ] = None,
    ) -> SimulationResult:
        if years < self.config.minimum_percent:
            raise ValueError("years must be non-negative")
        if (
            not isinstance(start_hour, int)
            or isinstance(start_hour, bool)
            or start_hour < 0
        ):
            raise ValueError("start_hour must be a non-negative integer")
        if state is None and start_hour != 0:
            raise ValueError(
                "state is required when start_hour is non-zero"
            )
        if state is not None and state.hours_completed != start_hour:
            raise ValueError(
                "state.hours_completed must equal start_hour"
            )
        duration_hours = int(round(years * self.config.hours_per_year))
        end_hour = start_hour + duration_hours
        current = state or SatelliteState(
            soc=self.config.initial_soc,
            delta_v_remaining_m_per_s=(
                self.config.initial_delta_v_budget_m_per_s
            ),
        )
        if self.maneuver_model == "none":
            current.maneuver_due = False
        current.minimum_soc = min(current.minimum_soc, current.soc)
        current.minimum_health = min(
            current.minimum_health, current.total_health(self.config)
        )
        continuing_with_operator_context = (
            start_hour > 0
            and self._last_run_completed_hour == start_hour
            and self.observed_state is not None
            and self.last_telemetry_hour is not None
        )
        continuing_with_lifecycle_context = (
            self.event_lifecycle_model == "warning_proxy"
            and start_hour > 0
            and self._last_run_completed_hour == start_hour
            and self.lifecycle_manager is not None
        )
        continuing_with_autonomy_context = (
            self.autonomy_model != "none"
            and start_hour > 0
            and self._last_run_completed_hour == start_hour
        )
        continuing_with_stationkeeping_context = (
            start_hour > 0
            and self._last_run_completed_hour == start_hour
        )
        if continuing_with_operator_context:
            # Reusing (or deep-copying) a warmed-up Simulator preserves the
            # genuinely stale ground snapshot across a continuation boundary.
            self.telemetry_age_hours = max(
                0, start_hour - self.last_telemetry_hour
            )
        else:
            # A standalone supplied state has no serialized ground-observation
            # companion. Treat its boundary snapshot as known, but do not count
            # that initialization as a received telemetry packet.
            self.observed_state = deepcopy(current)
            self.last_telemetry_hour = start_hour
            self.telemetry_age_hours = 0
        self.telemetry_updated_this_hour = False
        if start_hour == 0:
            self._resolved_debris_conjunctions = set()
        elif not continuing_with_operator_context:
            # A conjunction that began before a standalone continuation must
            # already have been resolved in the supplied state's prior hours.
            self._resolved_debris_conjunctions = {
                event
                for event in self.scenario.debris_conjunctions_at_hour(
                    start_hour
                )
                if event.hour < start_hour
            }
        if (
            self.event_lifecycle_model == "warning_proxy"
            and not continuing_with_lifecycle_context
        ):
            # A warmed Simulator preserves lifecycle awareness across a true
            # continuation. A fresh or restarted run rebuilds deterministic
            # external warnings from the scenario catalog. Standalone supplied
            # state has no serialized pre-boundary lifecycle/upload history.
            self.lifecycle_manager = self._new_lifecycle_manager()
        if not continuing_with_autonomy_context:
            self._reset_autonomy_context()
        if not continuing_with_stationkeeping_context:
            self._reset_stationkeeping_context()
        self._update_stationkeeping_extrema(current)
        self._state_aware_geometry_summaries = {}
        checkpoints: list[Checkpoint] = []
        events: list[Event] = []
        eclipse_hours = 0
        sunlight_hours = 0
        sunlight_factor_sum = 0.0
        min_sunlight_factor: float | None = None
        thermal_hot_stress_hours = 0
        thermal_cold_stress_hours = 0
        thermal_stress_hours = 0
        max_thermal_stress = 0.0
        total_thermal_degradation = 0.0
        min_thermal_health = current.thermal_health
        target_opportunity_hours = 0
        target_selected_hours = 0
        target_missed_hours = 0
        target_area_imaged_km2 = 0.0
        target_priority_score_total = 0
        target_panchromatic_scenes = 0
        target_multispectral_scenes = 0
        pointing_required_hours = 0
        pointing_limited_hours = 0
        pointing_missed_hours = 0
        pointing_quality_samples = 0
        pointing_quality_sum = 0.0
        min_pointing_quality: float | None = None
        pointing_imaging_loss_gb_proxy = 0.0
        pointing_downlink_loss_gb_proxy = 0.0
        telemetry_packets_generated = 0
        telemetry_packets_downlinked = 0
        command_packets_uploaded = 0
        daily_plan_packets_uploaded = 0
        packet_uplink_kb_total = 0.0
        packet_downlink_kb_total = 0.0
        telemetry_delivery_attempts = 0
        telemetry_delivery_failures = 0
        command_packet_attempts = 0
        command_packet_failures = 0
        daily_plan_packet_attempts = 0
        daily_plan_packet_failures = 0
        packet_delivery_failure_events = 0
        max_telemetry_age_hours = 0
        payload_event_emitted = current.payload_health < self.config.payload_failure_health

        def emit(hour: int, event_type: str, description: str) -> None:
            event = Event(hour, hour / self.config.hours_per_year, event_type, description)
            events.append(event)
            if on_event:
                on_event(event)

        for hour in range(start_hour, end_hour):
            if not current.alive:
                break
            for event_type, description in self.scenario.events_at_hour(hour):
                emit(hour, event_type, description)
            overflow_hours_at_start = current.overflow_hours
            current.debris_conjunction_active = False
            current.debris_avoidance_required_this_hour = False
            self.scenario.apply_pre_hour(current, hour)
            self._advance_orbit_drift_proxy(current)
            self._update_stationkeeping_extrema(current)
            active_debris = self.scenario.debris_conjunctions_at_hour(hour)
            lifecycle_eligible_ids: tuple[str, ...] = ()
            lifecycle_upload_failed_ids: tuple[str, ...] = ()
            lifecycle_response_upload_count = 0
            unresolved_debris = tuple(
                event for event in active_debris
                if event not in self._resolved_debris_conjunctions
            )
            current.debris_conjunction_active = bool(active_debris)
            current.debris_avoidance_required_this_hour = bool(
                unresolved_debris
            )
            self._enforce_storage_capacity(current, increment_hour=True)
            base_contact = self.nominal_contact(hour, current)
            contact = self.scenario.modify_contacts(base_contact, current, hour)
            physical_command_contact = (
                contact.cmd_contact_min > self.config.minimum_percent
            )
            lifecycle_delivery = assess_packet_delivery(
                packet_delivery_model=self.packet_delivery_model,
                attempted=(
                    self.packet_model == "packet_proxy"
                    and physical_command_contact
                    and self.lifecycle_manager is not None
                    and bool(
                        self.lifecycle_manager.upload_candidate_event_ids(hour)
                    )
                ),
                packet_delivery_seed=self.packet_delivery_seed,
                hour=hour,
                packet_kind="lifecycle_response_channel",
                direction="uplink",
                packet_drop_fraction_proxy=self.packet_drop_fraction_proxy,
            )
            if self.lifecycle_manager is not None:
                lifecycle_context = self.lifecycle_manager.advance(
                    hour,
                    contact,
                    command_upload_allowed=(
                        lifecycle_delivery.delivered
                        if lifecycle_delivery.attempted
                        else True
                    ),
                )
                for transition in lifecycle_context.transitions:
                    if on_lifecycle_transition is not None:
                        on_lifecycle_transition(transition)
                lifecycle_response_upload_count = sum(
                    transition.new_status
                    == LifecycleStatus.UPLOADED_TO_SPACECRAFT.value
                    for transition in lifecycle_context.transitions
                )
                lifecycle_response_attempt_count = len(
                    lifecycle_context.upload_attempted_event_ids
                )
                lifecycle_eligible_ids = tuple(
                    event_id
                    for event_id in (
                        lifecycle_context.avoidance_eligible_event_ids
                    )
                    if self.lifecycle_manager.source_event(event_id)
                    not in self._resolved_debris_conjunctions
                )
                lifecycle_upload_failed_ids = tuple(
                    event_id
                    for event_id in lifecycle_context.upload_failed_event_ids
                    if self.lifecycle_manager.source_event(event_id)
                    not in self._resolved_debris_conjunctions
                )
                unresolved_debris = tuple(
                    self.lifecycle_manager.source_event(event_id)
                    for event_id in (
                        *lifecycle_upload_failed_ids,
                        *lifecycle_eligible_ids,
                    )
                )
                current.debris_avoidance_required_this_hour = bool(
                    unresolved_debris
                )
            else:
                lifecycle_response_attempt_count = 0
            debris_assessment = self._highest_debris_assessment(
                unresolved_debris
            )
            telemetry_delivery = assess_packet_delivery(
                packet_delivery_model=self.packet_delivery_model,
                attempted=(
                    self.packet_model == "packet_proxy"
                    and physical_command_contact
                ),
                packet_delivery_seed=self.packet_delivery_seed,
                hour=hour,
                packet_kind="housekeeping_telemetry",
                direction="downlink",
                packet_drop_fraction_proxy=self.packet_drop_fraction_proxy,
            )
            self._update_observed_state(
                current,
                contact,
                hour,
                delivery_allowed=(
                    telemetry_delivery.delivered
                    if telemetry_delivery.attempted
                    else not physical_command_contact
                    or self.packet_model == "legacy"
                ),
            )
            policy_state = self._policy_state(current)
            was_backup = current.backup_mode
            was_emergency = current.emergency_beacon_mode
            daily_plan_attempted = (
                self.packet_model == "packet_proxy"
                and self._daily_plan_upload_needed(current, contact, hour)
            )
            daily_plan_delivery = assess_packet_delivery(
                packet_delivery_model=self.packet_delivery_model,
                attempted=daily_plan_attempted,
                packet_delivery_seed=self.packet_delivery_seed,
                hour=hour,
                packet_kind="daily_plan",
                direction="uplink",
                packet_drop_fraction_proxy=self.packet_drop_fraction_proxy,
            )
            plan_uploaded = self._update_plan_and_contact_state(
                current,
                contact,
                hour,
                policy_state,
                upload_allowed=(
                    daily_plan_delivery.delivered
                    if daily_plan_delivery.attempted
                    else True
                ),
            )
            contingency_attempted = (
                self.packet_model == "packet_proxy"
                and self._contingency_upload_needed(contact, hour)
            )
            contingency_delivery = assess_packet_delivery(
                packet_delivery_model=self.packet_delivery_model,
                attempted=contingency_attempted,
                packet_delivery_seed=self.packet_delivery_seed,
                hour=hour,
                packet_kind="contingency_plan",
                direction="uplink",
                packet_drop_fraction_proxy=self.packet_drop_fraction_proxy,
            )
            contingency_uploaded, contingency_expired = (
                self._update_contingency_plan(
                    contact,
                    hour,
                    upload_allowed=(
                        contingency_delivery.delivered
                        if contingency_delivery.attempted
                        else True
                    ),
                )
            )
            packet_assessment = assess_packets_for_hour(
                packet_model=self.packet_model,
                packet_delivery_model=self.packet_delivery_model,
                telemetry_updated_this_hour=(
                    self.telemetry_updated_this_hour
                ),
                telemetry_delivery_attempted_this_hour=(
                    telemetry_delivery.attempted
                ),
                plan_uploaded_this_hour=plan_uploaded,
                daily_plan_delivery_attempted_this_hour=(
                    daily_plan_delivery.attempted
                ),
                lifecycle_response_upload_count=(
                    lifecycle_response_upload_count
                ),
                lifecycle_response_attempt_count=(
                    lifecycle_response_attempt_count
                ),
                contingency_plan_uploaded_this_hour=contingency_uploaded,
                contingency_plan_delivery_attempted_this_hour=(
                    contingency_delivery.attempted
                ),
                config=self.config,
            )
            telemetry_packets_generated += int(
                bool(
                    packet_assessment.telemetry_packet_generated_this_hour
                )
            )
            telemetry_packets_downlinked += int(
                bool(
                    packet_assessment.telemetry_packet_downlinked_this_hour
                )
            )
            telemetry_delivery_attempts += int(
                bool(
                    packet_assessment.telemetry_packet_delivery_attempted_this_hour
                )
            )
            telemetry_delivery_failures += int(
                bool(
                    packet_assessment.telemetry_packet_delivery_failed_this_hour
                )
            )
            command_packet_attempts += (
                packet_assessment.command_packets_attempted_this_hour
            )
            command_packets_uploaded += (
                packet_assessment.command_packets_uploaded_this_hour
            )
            command_packet_failures += (
                packet_assessment.command_packets_failed_this_hour
            )
            daily_plan_packet_attempts += int(
                bool(
                    packet_assessment.daily_plan_packet_delivery_attempted_this_hour
                )
            )
            daily_plan_packets_uploaded += int(
                bool(
                    packet_assessment.daily_plan_packet_uploaded_this_hour
                )
            )
            daily_plan_packet_failures += int(
                bool(
                    packet_assessment.daily_plan_packet_delivery_failed_this_hour
                )
            )
            packet_delivery_failure_events += (
                int(
                    bool(
                        packet_assessment.telemetry_packet_delivery_failed_this_hour
                    )
                )
                + packet_assessment.command_packets_failed_this_hour
                + int(
                    bool(
                        packet_assessment.daily_plan_packet_delivery_failed_this_hour
                    )
                )
            )
            if self.packet_model == "packet_proxy":
                max_telemetry_age_hours = max(
                    max_telemetry_age_hours, self.telemetry_age_hours
                )
            packet_uplink_kb_total += (
                packet_assessment.packet_uplink_kb_this_hour
            )
            packet_downlink_kb_total += (
                packet_assessment.packet_downlink_kb_this_hour
            )
            if plan_uploaded:
                emit(hour, "daily_plan_uploaded", "New 24-hour daily plan uploaded")
            if contingency_uploaded:
                emit(
                    hour,
                    "contingency_plan_uploaded",
                    "Bounded onboard contingency authority uploaded",
                )
            if contingency_expired:
                emit(
                    hour,
                    "contingency_plan_expired",
                    "Onboard contingency authority expired",
                )
            if current.backup_mode and not was_backup:
                emit(hour, "backup_mode", "Daily plan expired; switched to BACKUP")
            if current.emergency_beacon_mode and not was_emergency:
                emit(hour, "emergency_beacon_mode", "No command contact for 14 days")

            operator_diagnostics = self._operator_diagnostics(policy_state)
            plan_details = self._plan_mode_details(current)
            explanation_state = (
                deepcopy(current)
                if on_decision_explanation is not None
                else None
            )
            (
                mode,
                safe_override,
                payload_unavailable,
                maneuver_intended,
            ) = self._select_mode_details(
                current, contact, policy_state, plan_details.planned_mode
            )
            selected_mode = mode
            autonomy_decision = self._autonomy_decision(
                current,
                contact,
                hour,
                selected_mode,
                lifecycle_eligible_ids,
            )
            if (
                autonomy_decision.active
                and autonomy_decision.selected_mode is not None
            ):
                mode = Mode(autonomy_decision.selected_mode)
                self._record_autonomy_decision(autonomy_decision)
                emit(
                    hour,
                    "autonomy_action",
                    autonomy_decision.reason or "Bounded autonomy action",
                )
            stationkeeping_assessment = self._stationkeeping_assessment(
                current,
                mode,
                emergency_beacon_active=(
                    current.emergency_beacon_mode
                    or mode == Mode.EMERGENCY_BEACON
                ),
                critical_energy_safe_priority=(
                    mode == Mode.SAFE
                    and (
                        safe_override
                        or autonomy_decision.selected_mode == Mode.SAFE.value
                        or self.effective_energy_margin(current)
                        < self.policy.safe_threshold
                    )
                ),
                debris_avoidance_priority=bool(unresolved_debris),
                projected_critical_within_plan=(
                    self.stationkeeping_planning_model == "drift_aware"
                    and plan_details.planned_mode == Mode.MANEUVER
                ),
            )
            self._record_stationkeeping_assessment(
                stationkeeping_assessment
            )
            if stationkeeping_assessment.selected:
                mode = Mode.MANEUVER
                emit(
                    hour,
                    "stationkeeping_selected",
                    stationkeeping_assessment.reason,
                )
            if safe_override and current.mode != Mode.SAFE:
                emit(
                    hour,
                    "safe_mode_override",
                    "Effective energy margin below policy safe threshold",
                )
            if payload_unavailable and not payload_event_emitted:
                emit(hour, "payload_unavailable", "Payload health below imaging threshold")
                payload_event_emitted = True
            debris_outcome = DebrisAvoidanceOutcome(
                mode, False, False, self.config.minimum_percent,
                self.config.minimum_percent,
            )
            if unresolved_debris:
                if self.lifecycle_manager is None:
                    debris_outcome = self._resolve_debris_avoidance(
                        current, mode, unresolved_debris, hour
                    )
                else:
                    debris_outcome = self._resolve_lifecycle_debris(
                        current,
                        mode,
                        hour,
                        contact,
                        lifecycle_eligible_ids,
                        lifecycle_upload_failed_ids,
                        on_lifecycle_transition,
                    )
                mode = debris_outcome.mode
                maneuver_executed = debris_outcome.executed
                maneuver_skipped = debris_outcome.skipped
                maneuver_delta_v_used = debris_outcome.delta_v_used
                if debris_outcome.executed:
                    emit(
                        hour,
                        "debris_avoidance_executed",
                        "Synthetic debris/conjunction avoidance maneuver executed",
                    )
                if debris_outcome.skipped:
                    emit(
                        hour,
                        "debris_avoidance_skipped",
                        "Avoidance unavailable; synthetic subsystem damage applied",
                    )
            else:
                (
                    mode,
                    maneuver_executed,
                    maneuver_skipped,
                    maneuver_delta_v_used,
                ) = self._resolve_maneuver_mode(
                    current,
                    mode,
                    hour,
                    planned_maneuver=(
                        plan_details.planned_mode == Mode.MANEUVER
                        or maneuver_intended
                        or autonomy_decision.selected_mode
                        == Mode.MANEUVER.value
                        or stationkeeping_assessment.selected
                    ),
                )
                if (
                    stationkeeping_assessment.selected
                    and maneuver_executed
                ):
                    emit(
                        hour,
                        "stationkeeping_executed",
                        "Drift-aware stationkeeping used the existing maneuver path",
                    )
            decision_explanation = None
            if explanation_state is not None:
                decision_explanation = build_decision_explanation(
                    hour=hour,
                    policy=self.policy.name,
                    scenario=self.scenario.name,
                    operator_view=self.operator_view,
                    planning_model=self.planning_model,
                    maneuver_model=self.maneuver_model,
                    orbit_evolution_model=self.orbit_evolution_model,
                    state=explanation_state,
                    contact=contact,
                    telemetry_age_hours=self.telemetry_age_hours,
                    planned_mode=plan_details.planned_mode,
                    selected_mode=selected_mode,
                    executed_mode=mode,
                    safe_threshold=self.policy.safe_threshold,
                    safe_override=safe_override,
                    payload_unavailable=payload_unavailable,
                    maneuver_intended=maneuver_intended,
                    maneuver_executed=maneuver_executed,
                    maneuver_skipped=maneuver_skipped,
                    debris_executed=debris_outcome.executed,
                    debris_skipped=debris_outcome.skipped,
                    config=self.config,
                )
            current.mode = mode
            target_assessment = assess_target_for_hour(
                target_model=self.target_model,
                hour=hour,
                mode=mode,
                state=current,
                config=self.config,
            )
            target_opportunity = bool(
                target_assessment.target_opportunity_this_hour
            )
            target_selected = bool(
                target_assessment.target_selected_this_hour
            )
            target_enabled = self.target_model == "scene_scheduling_proxy"
            target_opportunity_hours += int(
                target_enabled and target_opportunity
            )
            target_selected_hours += int(target_enabled and target_selected)
            target_missed_hours += int(
                target_enabled
                and (
                    (target_opportunity and not target_selected)
                    or (mode == Mode.IMAGING and not target_opportunity)
                )
            )
            if target_enabled and target_selected:
                target_priority_score_total += (
                    target_assessment.target_priority_this_hour or 0
                )
                if (
                    target_assessment.target_imagery_mode_this_hour
                    == "panchromatic"
                ):
                    target_panchromatic_scenes += 1
                elif (
                    target_assessment.target_imagery_mode_this_hour
                    == "multispectral"
                ):
                    target_multispectral_scenes += 1
            pointing_assessment = assess_pointing_for_hour(
                pointing_model=self.pointing_model,
                hour=hour,
                mode=mode,
                state=current,
                target_assessment=target_assessment,
                config=self.config,
            )
            pointing_required_hours += int(
                bool(pointing_assessment.pointing_required_this_hour)
            )
            pointing_limited_hours += int(
                bool(pointing_assessment.pointing_limited_this_hour)
            )
            pointing_missed_hours += int(
                bool(pointing_assessment.pointing_missed_this_hour)
            )
            pointing_quality = (
                pointing_assessment.pointing_quality_this_hour
            )
            if pointing_quality is not None:
                pointing_quality_samples += 1
                pointing_quality_sum += pointing_quality
                min_pointing_quality = (
                    pointing_quality
                    if min_pointing_quality is None
                    else min(min_pointing_quality, pointing_quality)
                )
            pointing_multiplier = self._clamp(
                pointing_assessment.pointing_multiplier_this_hour,
                self.config.minimum_health,
                self.config.maximum_health,
            )
            if target_enabled and target_selected:
                target_area_imaged_km2 += (
                    target_assessment.target_scene_area_km2_this_hour or 0.0
                ) * pointing_multiplier
            if mode == Mode.IMAGING:
                target_multiplier = self._clamp(
                    target_assessment.target_data_multiplier_this_hour,
                    self.config.minimum_health,
                    self.config.maximum_health,
                )
                imaging_without_pointing = (
                    self.effective_imaging_rate_gb_per_hour(current)
                    * target_multiplier
                )
                pointing_imaging_loss_gb_proxy += (
                    imaging_without_pointing * (1.0 - pointing_multiplier)
                )
            elif (
                mode == Mode.DOWNLINK
                and contact.data_contact_min > self.config.minimum_percent
            ):
                downlink_without_pointing = min(
                    current.data_buffer_gb,
                    self.effective_downlink_rate_gb_per_min(current)
                    * contact.data_contact_min,
                )
                downlink_with_pointing = min(
                    current.data_buffer_gb,
                    self.effective_downlink_rate_gb_per_min(current)
                    * contact.data_contact_min
                    * pointing_multiplier,
                )
                pointing_downlink_loss_gb_proxy += max(
                    self.config.minimum_percent,
                    downlink_without_pointing - downlink_with_pointing,
                )
            power_assessment = self._execute_mode(
                current,
                mode,
                contact,
                count_overflow=current.overflow_hours == overflow_hours_at_start,
                hour=hour,
                target_data_multiplier=(
                    target_assessment.target_data_multiplier_this_hour
                ),
                pointing_multiplier=(
                    pointing_assessment.pointing_multiplier_this_hour
                ),
            )
            if power_assessment.sunlight_factor is not None:
                sunlight_factor = power_assessment.sunlight_factor
                sunlight_factor_sum += sunlight_factor
                min_sunlight_factor = (
                    sunlight_factor
                    if min_sunlight_factor is None
                    else min(min_sunlight_factor, sunlight_factor)
                )
                if power_assessment.eclipse:
                    eclipse_hours += 1
                else:
                    sunlight_hours += 1
            thermal_assessment = assess_thermal_for_hour(
                thermal_model=self.thermal_model,
                mode=mode,
                power_assessment=power_assessment,
                config=self.config,
            )
            hot_stress = thermal_assessment.thermal_hot_stress_this_hour or 0.0
            cold_stress = thermal_assessment.thermal_cold_stress_this_hour or 0.0
            thermal_stress = thermal_assessment.thermal_stress_this_hour or 0.0
            thermal_hot_stress_hours += int(hot_stress > 0.0)
            thermal_cold_stress_hours += int(cold_stress > 0.0)
            thermal_stress_hours += int(thermal_stress > 0.0)
            max_thermal_stress = max(max_thermal_stress, thermal_stress)
            payload_health_before = current.payload_health
            requested_thermal_degradation = (
                thermal_assessment.thermal_degradation_this_hour
            )
            applied_thermal_degradation = min(
                current.thermal_health, requested_thermal_degradation
            )
            current.thermal_health = self._clamp(
                current.thermal_health - applied_thermal_degradation,
                self.config.minimum_health,
                self.config.maximum_health,
            )
            thermal_assessment = replace(
                thermal_assessment,
                thermal_degradation_this_hour=applied_thermal_degradation,
            )
            total_thermal_degradation += applied_thermal_degradation
            self._degrade_health(current, mode)
            self.scenario.apply_post_hour(current, hour)
            orbit_drift_damage = self._apply_orbit_drift_damage(current)
            self._update_stationkeeping_extrema(current)
            if (
                current.orbit_drift_proxy_km
                >= self.config.orbit_drift_critical_threshold_km
            ):
                self.stationkeeping_unresolved_critical_drift_hours += 1
            if orbit_drift_damage > self.config.minimum_percent:
                emit(
                    hour,
                    "orbit_drift_damage",
                    "Uncorrected critical drift applied synthetic subsystem damage",
                )
            self._enforce_storage_capacity(
                current,
                increment_hour=current.overflow_hours == overflow_hours_at_start,
            )
            current.minimum_soc = min(current.minimum_soc, current.soc)
            current.minimum_health = min(
                current.minimum_health, current.total_health(self.config)
            )
            min_thermal_health = min(
                min_thermal_health, current.thermal_health
            )
            if current.payload_health < self.config.payload_failure_health:
                current.payload_unavailable_hours += 1
            self._check_survival(current)
            current.hours_completed += 1
            current.mode_hours[mode] += 1
            if mode == Mode.SAFE:
                current.safe_mode_hours += 1
            if (
                payload_health_before >= self.config.payload_failure_health
                and current.payload_health < self.config.payload_failure_health
            ):
                emit(hour, "payload_unavailable", "Payload health below imaging threshold")
                payload_event_emitted = True
            if not current.alive and current.loss_reason:
                loss_events = {
                    LossReason.CRITICAL_POWER: ("critical_power_loss", "Critical SOC persisted for more than 6 hours"),
                    LossReason.EPS_FAILURE: ("eps_failure", "EPS health below failure threshold"),
                    LossReason.COMMUNICATION_FAILURE: ("comms_failure", "Communications health below failure threshold"),
                    LossReason.STORAGE_FAILURE: ("storage_failure", "Storage health below failure threshold"),
                    LossReason.OBC_FAILURE: ("obc_failure", "OBC health below failure threshold"),
                    LossReason.ADCS_FAILURE: ("adcs_failure", "ADCS health below failure threshold"),
                    LossReason.THERMAL_FAILURE: ("thermal_failure", "Thermal health below failure threshold"),
                }
                emit(hour, *loss_events[current.loss_reason])

            if on_decision_explanation and decision_explanation is not None:
                on_decision_explanation(decision_explanation)

            if on_hour:
                on_hour(
                    self._hour_record(
                        current,
                        base_contact,
                        contact,
                        hour,
                        operator_diagnostics,
                        plan_uploaded,
                        plan_details,
                        maneuver_executed,
                        maneuver_skipped,
                        maneuver_delta_v_used,
                        debris_outcome,
                        debris_assessment,
                        autonomy_decision,
                        stationkeeping_assessment,
                        power_assessment,
                        thermal_assessment,
                        target_assessment,
                        pointing_assessment,
                        packet_assessment,
                        orbit_drift_damage,
                    )
                )

            completed_hour = hour + 1
            if completed_hour % self.config.checkpoint_hours == 0:
                checkpoint = self._checkpoint(current, completed_hour)
                checkpoints.append(checkpoint)
                if on_checkpoint:
                    on_checkpoint(checkpoint)

        metrics = calculate_metrics(current, end_hour, self.config)
        fuel = self._fuel_percentages(current)
        risk_assessments = self.debris_risk_assessments()
        high_or_severe = sum(
            assessment.risk_class in ("high", "severe")
            for assessment in risk_assessments
        )
        severe = sum(
            assessment.risk_class == "severe"
            for assessment in risk_assessments
        )
        zone_counts: dict[str, int] = {}
        for assessment in risk_assessments:
            zone_counts[assessment.impact_zone] = (
                zone_counts.get(assessment.impact_zone, 0) + 1
            )
        most_common_zone = (
            min(
                zone_counts,
                key=lambda zone: (-zone_counts[zone], zone),
            )
            if zone_counts
            else None
        )
        self._last_run_completed_hour = current.hours_completed
        return SimulationResult(
            policy_name=self.policy.name,
            scenario_name=self.scenario.name,
            operator_view=self.operator_view,
            requested_years=years,
            total_hours=end_hour,
            state=current,
            metrics=metrics,
            checkpoints=checkpoints,
            events=events,
            planning_model=self.planning_model,
            maneuver_model=self.maneuver_model,
            orbit_evolution_model=self.orbit_evolution_model,
            stationkeeping_planning_model=(
                self.stationkeeping_planning_model
            ),
            power_model=self.power_model,
            event_lifecycle_model=self.event_lifecycle_model,
            debris_risk_model=self.debris_risk_model,
            autonomy_model=self.autonomy_model,
            autonomous_action_count=self.autonomous_action_count,
            autonomous_safe_mode_count=self.autonomous_safe_mode_count,
            autonomous_standby_count=self.autonomous_standby_count,
            autonomous_downlink_count=self.autonomous_downlink_count,
            autonomous_maneuver_count=self.autonomous_maneuver_count,
            contingency_plan_upload_count=(
                self.contingency_plan_upload_count
            ),
            contingency_plan_expired_count=(
                self.contingency_plan_expired_count
            ),
            high_or_severe_debris_events=high_or_severe,
            severe_debris_events=severe,
            max_debris_risk_score=max(
                (
                    assessment.risk_score
                    for assessment in risk_assessments
                ),
                default=0.0,
            ),
            most_common_debris_impact_zone=most_common_zone,
            fuel_remaining_percent=fuel["fuel_remaining_percent"],
            fuel_used_percent=fuel["fuel_used_percent"],
            stationkeeping_delta_v_cost_percent=(
                fuel["stationkeeping_delta_v_cost_percent"]
            ),
            debris_avoidance_delta_v_cost_percent=(
                fuel["debris_avoidance_delta_v_cost_percent"]
            ),
            stationkeeping_recommended_count=(
                self.stationkeeping_recommended_count
            ),
            stationkeeping_selected_count=(
                self.stationkeeping_selected_count
            ),
            stationkeeping_deferred_count=(
                self.stationkeeping_deferred_count
            ),
            stationkeeping_unresolved_critical_drift_hours=(
                self.stationkeeping_unresolved_critical_drift_hours
            ),
            max_orbit_drift_proxy_km=self.max_orbit_drift_proxy_km,
            max_orbit_groundtrack_error_km=(
                self.max_orbit_groundtrack_error_km
            ),
            max_orbit_phase_error_deg=self.max_orbit_phase_error_deg,
            eclipse_hours=eclipse_hours,
            sunlight_hours=sunlight_hours,
            eclipse_fraction_observed=(
                eclipse_hours / (eclipse_hours + sunlight_hours)
                if eclipse_hours + sunlight_hours
                else None
            ),
            min_sunlight_factor=min_sunlight_factor,
            average_sunlight_factor=(
                sunlight_factor_sum / (eclipse_hours + sunlight_hours)
                if eclipse_hours + sunlight_hours
                else None
            ),
            thermal_model=self.thermal_model,
            thermal_hot_stress_hours=thermal_hot_stress_hours,
            thermal_cold_stress_hours=thermal_cold_stress_hours,
            thermal_stress_hours=thermal_stress_hours,
            max_thermal_stress=max_thermal_stress,
            total_thermal_degradation=total_thermal_degradation,
            min_thermal_health=min_thermal_health,
            target_model=self.target_model,
            target_opportunity_hours=target_opportunity_hours,
            target_selected_hours=target_selected_hours,
            target_missed_hours=target_missed_hours,
            target_area_imaged_km2=target_area_imaged_km2,
            target_priority_score_total=target_priority_score_total,
            target_panchromatic_scenes=target_panchromatic_scenes,
            target_multispectral_scenes=target_multispectral_scenes,
            pointing_model=self.pointing_model,
            pointing_required_hours=pointing_required_hours,
            pointing_limited_hours=pointing_limited_hours,
            pointing_missed_hours=pointing_missed_hours,
            min_pointing_quality=min_pointing_quality,
            average_pointing_quality=(
                pointing_quality_sum / pointing_quality_samples
                if pointing_quality_samples
                else None
            ),
            pointing_imaging_loss_gb_proxy=(
                pointing_imaging_loss_gb_proxy
            ),
            pointing_downlink_loss_gb_proxy=(
                pointing_downlink_loss_gb_proxy
            ),
            packet_model=self.packet_model,
            packet_delivery_model=self.packet_delivery_model,
            packet_delivery_seed=self.packet_delivery_seed,
            packet_drop_fraction_proxy=self.packet_drop_fraction_proxy,
            telemetry_packets_generated=telemetry_packets_generated,
            telemetry_delivery_attempts=telemetry_delivery_attempts,
            telemetry_packets_downlinked=telemetry_packets_downlinked,
            telemetry_delivery_failures=telemetry_delivery_failures,
            command_packet_attempts=command_packet_attempts,
            command_packets_uploaded=command_packets_uploaded,
            command_packet_failures=command_packet_failures,
            daily_plan_packet_attempts=daily_plan_packet_attempts,
            daily_plan_packets_uploaded=daily_plan_packets_uploaded,
            daily_plan_packet_failures=daily_plan_packet_failures,
            packet_delivery_failure_events=packet_delivery_failure_events,
            max_telemetry_age_hours=max_telemetry_age_hours,
            packet_uplink_kb_total=packet_uplink_kb_total,
            packet_downlink_kb_total=packet_downlink_kb_total,
        )

    def _advance_orbit_drift_proxy(self, state: SatelliteState) -> None:
        """Advance drift and, when selected, its V2.8 geometry proxy."""
        if self.maneuver_model == "none":
            state.maneuver_due = False
            state.orbit_drift_warning = False
            state.orbit_drift_critical = False
            self._synchronize_orbit_proxy_from_drift(state)
            return
        state.orbit_drift_proxy_km += (
            self.config.orbit_drift_proxy_km_per_day
            / self.config.hours_per_day
        )
        self._synchronize_orbit_proxy_from_drift(state)
        self._update_maneuver_due(state)

    def _synchronize_orbit_proxy_from_drift(
        self, state: SatelliteState
    ) -> None:
        """Map only new drift into errors so maneuver impulses persist."""
        if self.orbit_evolution_model != "drift_proxy":
            return
        drift_delta = (
            state.orbit_drift_proxy_km
            - state._orbit_proxy_mapped_drift_km
        )
        state.orbit_phase_error_deg = self._clamp_signed(
            state.orbit_phase_error_deg
            + drift_delta
            * self.config.orbit_phase_error_deg_per_drift_km,
            self.config.maximum_orbit_phase_error_deg,
        )
        state.orbit_altitude_offset_km = self._clamp_signed(
            state.orbit_altitude_offset_km
            + drift_delta
            * self.config.orbit_altitude_offset_km_per_drift_km,
            self.config.maximum_orbit_altitude_offset_km,
        )
        state.orbit_groundtrack_error_km = self._clamp_signed(
            state.orbit_groundtrack_error_km
            + drift_delta
            * self.config.orbit_groundtrack_error_km_per_drift_km,
            self.config.maximum_orbit_groundtrack_error_km,
        )
        state._orbit_proxy_mapped_drift_km = state.orbit_drift_proxy_km
        self._update_orbit_geometry_degraded(state)

    def _orbit_geometry_error_km(self, state: SatelliteState) -> float:
        phase_arc_km = (
            abs(state.orbit_phase_error_deg)
            / self.config.degrees_per_circle
            * 2.0
            * pi
            * (
                self.config.earth_radius_km
                + self.config.orbit_altitude_km
            )
        )
        return max(
            abs(state.orbit_groundtrack_error_km),
            abs(state.orbit_altitude_offset_km),
            phase_arc_km,
        )

    def _update_orbit_geometry_degraded(
        self, state: SatelliteState
    ) -> None:
        state.orbit_geometry_degraded = (
            self.orbit_evolution_model == "drift_proxy"
            and self._orbit_geometry_error_km(state)
            >= self.config.orbit_geometry_degraded_threshold_km
        )

    def _orbit_correction_needed(self, state: SatelliteState) -> bool:
        return (
            self.orbit_evolution_model == "drift_proxy"
            and (
                state.maneuver_due
                or state.orbit_geometry_degraded
                or self._orbit_geometry_error_km(state)
                >= self.config.orbit_geometry_degraded_threshold_km
            )
        )

    def _apply_stationkeeping_orbit_correction(
        self, state: SatelliteState
    ) -> None:
        if self.orbit_evolution_model != "drift_proxy":
            return
        state.orbit_phase_error_deg *= (
            1.0
            - self._clamp(
                self.config.stationkeeping_phase_correction_fraction,
                self.config.minimum_health,
                self.config.maximum_health,
            )
        )
        state.orbit_altitude_offset_km *= (
            1.0
            - self._clamp(
                self.config.stationkeeping_altitude_correction_fraction,
                self.config.minimum_health,
                self.config.maximum_health,
            )
        )
        state.orbit_groundtrack_error_km *= (
            1.0
            - self._clamp(
                self.config.stationkeeping_groundtrack_correction_fraction,
                self.config.minimum_health,
                self.config.maximum_health,
            )
        )
        state.orbit_correction_count += 1
        self._update_orbit_geometry_degraded(state)

    def _apply_debris_avoidance_geometry_impulse(
        self, state: SatelliteState, event_count: int
    ) -> None:
        if self.orbit_evolution_model != "drift_proxy":
            return
        state.orbit_phase_error_deg = self._clamp_signed(
            state.orbit_phase_error_deg
            + self.config.debris_avoidance_phase_impulse_deg * event_count,
            self.config.maximum_orbit_phase_error_deg,
        )
        state.orbit_altitude_offset_km = self._clamp_signed(
            state.orbit_altitude_offset_km
            + self.config.debris_avoidance_altitude_impulse_km * event_count,
            self.config.maximum_orbit_altitude_offset_km,
        )
        state.orbit_groundtrack_error_km = self._clamp_signed(
            state.orbit_groundtrack_error_km
            + self.config.debris_avoidance_groundtrack_impulse_km * event_count,
            self.config.maximum_orbit_groundtrack_error_km,
        )
        self._update_orbit_geometry_degraded(state)

    def _update_maneuver_due(self, state: SatelliteState) -> None:
        if self.maneuver_model != "stationkeeping_proxy":
            state.maneuver_due = False
            state.orbit_drift_warning = False
            state.orbit_drift_critical = False
            return
        state.orbit_drift_warning = (
            state.orbit_drift_proxy_km
            >= self.config.orbit_drift_warning_threshold_km
        )
        state.orbit_drift_critical = (
            state.orbit_drift_proxy_km
            >= self.config.orbit_drift_critical_threshold_km
        )
        due_threshold = min(
            self.config.orbit_drift_threshold_km,
            self.config.orbit_drift_warning_threshold_km,
        )
        state.maneuver_due = (
            state.orbit_drift_proxy_km >= due_threshold
        )

    def _maneuver_energy_sufficient(self, state: SatelliteState) -> bool:
        return (
            self.effective_energy_margin(state)
            + self.config.maneuver_soc_delta
            >= self.policy.safe_threshold
        )

    def _maneuver_resources_available(
        self,
        state: SatelliteState,
        delta_v_cost: float | None = None,
    ) -> bool:
        if delta_v_cost is None:
            delta_v_cost = self.config.stationkeeping_delta_v_cost_m_per_s
        required_delta_v = max(
            self.config.minimum_delta_v_for_maneuver_m_per_s,
            delta_v_cost,
        )
        return (
            state.delta_v_remaining_m_per_s >= required_delta_v
            and state.propulsion_health
            >= self.config.propulsion_maneuver_health_threshold
            and self._maneuver_energy_sufficient(state)
        )

    def _consume_maneuver_resources(
        self,
        state: SatelliteState,
        hour: int,
        delta_v_cost: float | None = None,
        drift_reduction_km: float | None = None,
        count_stationkeeping: bool = True,
    ) -> float:
        delta_v = (
            self.config.stationkeeping_delta_v_cost_m_per_s
            if delta_v_cost is None
            else delta_v_cost
        )
        drift_reduction = (
            self.config.orbit_drift_reduction_per_maneuver_km
            if drift_reduction_km is None
            else drift_reduction_km
        )
        state.delta_v_remaining_m_per_s = max(
            self.config.minimum_percent,
            state.delta_v_remaining_m_per_s - delta_v,
        )
        state.delta_v_used_m_per_s += delta_v
        if count_stationkeeping:
            state.maneuver_count += 1
        state.orbit_drift_proxy_km = max(
            self.config.minimum_percent,
            state.orbit_drift_proxy_km
            - drift_reduction,
        )
        if self.orbit_evolution_model == "drift_proxy":
            # Drift has already been mapped before mode selection. Record the
            # post-burn value so the reduction is not mapped a second time.
            state._orbit_proxy_mapped_drift_km = state.orbit_drift_proxy_km
            if count_stationkeeping:
                self._apply_stationkeeping_orbit_correction(state)
        state.last_maneuver_hour = hour
        state.propulsion_health = self._clamp(
            state.propulsion_health
            - self.config.maneuver_propulsion_degradation,
            self.config.minimum_health,
            self.config.maximum_health,
        )
        self._update_maneuver_due(state)
        return delta_v

    def _apply_health_damage(
        self,
        state: SatelliteState,
        targets: tuple[str, ...],
        effect: float,
    ) -> None:
        invalid_targets = sorted(set(targets) - HEALTH_FIELDS)
        if invalid_targets:
            raise ValueError(
                "Invalid health damage target(s): "
                f"{', '.join(invalid_targets)}"
            )
        for field_name in targets:
            current = getattr(state, field_name)
            setattr(
                state,
                field_name,
                self._clamp(
                    current - effect,
                    self.config.minimum_health,
                    self.config.maximum_health,
                ),
            )

    def _debris_avoidance_failure_reason(
        self,
        state: SatelliteState,
        selected_mode: Mode,
        delta_v_cost: float,
    ) -> str:
        if (
            state.emergency_beacon_mode
            or selected_mode == Mode.EMERGENCY_BEACON
        ):
            return "emergency_beacon_active"
        if self.maneuver_model != "stationkeeping_proxy":
            return "maneuver_model_disabled"
        if not self._maneuver_energy_sufficient(state):
            return "insufficient_energy"
        required_delta_v = max(
            self.config.minimum_delta_v_for_maneuver_m_per_s,
            delta_v_cost,
        )
        if state.delta_v_remaining_m_per_s < required_delta_v:
            return "insufficient_delta_v"
        if (
            state.propulsion_health
            < self.config.propulsion_maneuver_health_threshold
        ):
            return "propulsion_health_below_threshold"
        return "avoidance_resources_unavailable"

    @staticmethod
    def _combine_debris_outcomes(
        selected_mode: Mode,
        outcomes: list[DebrisAvoidanceOutcome],
    ) -> DebrisAvoidanceOutcome:
        if not outcomes:
            return DebrisAvoidanceOutcome(
                selected_mode, False, False, 0.0, 0.0
            )
        if len(outcomes) == 1:
            return outcomes[0]
        executed = any(outcome.executed for outcome in outcomes)
        skipped = any(outcome.skipped for outcome in outcomes)
        if executed:
            mode = Mode.MANEUVER
        else:
            priority = {
                Mode.EMERGENCY_BEACON: 3,
                Mode.SAFE: 2,
                Mode.STANDBY: 1,
            }
            mode = max(
                (outcome.mode for outcome in outcomes),
                key=lambda candidate: priority.get(candidate, 0),
            )
        return DebrisAvoidanceOutcome(
            mode=mode,
            executed=executed,
            skipped=skipped,
            delta_v_used=sum(
                outcome.delta_v_used for outcome in outcomes
            ),
            damage=sum(outcome.damage for outcome in outcomes),
            failure_reason=next(
                (
                    outcome.failure_reason
                    for outcome in outcomes
                    if outcome.failure_reason is not None
                ),
                None,
            ),
        )

    def _resolve_lifecycle_debris(
        self,
        state: SatelliteState,
        selected_mode: Mode,
        hour: int,
        contact: ContactInfo,
        eligible_event_ids: tuple[str, ...],
        upload_failed_event_ids: tuple[str, ...],
        on_lifecycle_transition: Optional[
            Callable[[LifecycleTransition], None]
        ],
    ) -> DebrisAvoidanceOutcome:
        """Gate existing avoidance on an uploaded lifecycle response."""
        if self.lifecycle_manager is None:
            raise RuntimeError("lifecycle manager is not enabled")
        outcomes: list[DebrisAvoidanceOutcome] = []

        if eligible_event_ids:
            eligible_events = tuple(
                self.lifecycle_manager.source_event(event_id)
                for event_id in eligible_event_ids
            )
            eligible_outcome = self._resolve_debris_avoidance(
                state, selected_mode, eligible_events, hour
            )
            outcomes.append(eligible_outcome)
            for event_id in eligible_event_ids:
                transition = self.lifecycle_manager.resolve_avoidance(
                    event_id,
                    hour,
                    success=eligible_outcome.executed,
                    failure_reason=eligible_outcome.failure_reason,
                    contact=contact,
                )
                if on_lifecycle_transition is not None:
                    on_lifecycle_transition(transition)

        if upload_failed_event_ids:
            upload_failed_events = tuple(
                self.lifecycle_manager.source_event(event_id)
                for event_id in upload_failed_event_ids
            )
            outcomes.append(
                self._resolve_debris_avoidance(
                    state,
                    selected_mode,
                    upload_failed_events,
                    hour,
                    force_failure_reason=(
                        "no_command_upload_before_tca"
                    ),
                )
            )

        return self._combine_debris_outcomes(selected_mode, outcomes)

    def _resolve_debris_avoidance(
        self,
        state: SatelliteState,
        selected_mode: Mode,
        events: tuple[ExternalEvent, ...],
        hour: int,
        force_failure_reason: str | None = None,
    ) -> DebrisAvoidanceOutcome:
        """Resolve current conjunctions without forecasting later catalog events."""
        self._resolved_debris_conjunctions.update(events)
        event_count = len(events)
        delta_v_cost = (
            self.config.debris_avoidance_delta_v_cost_m_per_s * event_count
        )
        emergency = (
            state.emergency_beacon_mode
            or selected_mode == Mode.EMERGENCY_BEACON
        )
        energy_sufficient = self._maneuver_energy_sufficient(state)
        can_execute = (
            force_failure_reason is None
            and not emergency
            and self.maneuver_model == "stationkeeping_proxy"
            and self._maneuver_resources_available(state, delta_v_cost)
        )
        if can_execute:
            used = self._consume_maneuver_resources(
                state,
                hour,
                delta_v_cost=delta_v_cost,
                drift_reduction_km=(
                    self.config.debris_avoidance_drift_reduction_km
                    * event_count
                ),
                count_stationkeeping=False,
            )
            state.debris_avoidance_executed_count += event_count
            self._apply_debris_avoidance_geometry_impulse(
                state, event_count
            )
            return DebrisAvoidanceOutcome(
                Mode.MANEUVER, True, False, used,
                self.config.minimum_percent,
            )

        failure_reason = force_failure_reason or (
            self._debris_avoidance_failure_reason(
                state, selected_mode, delta_v_cost
            )
        )
        state.debris_avoidance_skipped_count += event_count
        damage = self.config.minimum_percent
        for event in events:
            targets, event_damage, _assessment = (
                self._debris_damage_for_event(event)
            )
            self._apply_health_damage(state, targets, event_damage)
            damage += event_damage
        state.debris_damage_events += event_count
        state.debris_damage_accumulated += damage
        if emergency:
            fallback = Mode.EMERGENCY_BEACON
        elif not energy_sufficient:
            fallback = Mode.SAFE
        else:
            fallback = Mode.STANDBY
        return DebrisAvoidanceOutcome(
            fallback,
            False,
            True,
            self.config.minimum_percent,
            damage,
            failure_reason,
        )

    def _apply_orbit_drift_damage(self, state: SatelliteState) -> float:
        self._update_maneuver_due(state)
        if not state.orbit_drift_critical:
            return self.config.minimum_percent
        damage = self.config.orbit_drift_damage_per_hour
        self._apply_health_damage(
            state, self.config.orbit_drift_damage_targets, damage
        )
        state.orbit_drift_damage_events += 1
        state.orbit_drift_damage_accumulated += damage
        return damage

    def _resolve_maneuver_mode(
        self,
        state: SatelliteState,
        selected_mode: Mode,
        hour: int,
        planned_maneuver: bool,
    ) -> tuple[Mode, bool, bool, float]:
        """Validate a maneuver against real onboard state before execution."""
        if self.maneuver_model == "none":
            fallback = (
                Mode.STANDBY
                if selected_mode == Mode.MANEUVER
                else selected_mode
            )
            return fallback, False, False, self.config.minimum_percent

        if selected_mode != Mode.MANEUVER:
            if planned_maneuver:
                state.maneuver_skipped_count += 1
                if self._orbit_correction_needed(state):
                    state.orbit_correction_skipped_count += 1
                return selected_mode, False, True, self.config.minimum_percent
            return selected_mode, False, False, self.config.minimum_percent

        if self._maneuver_resources_available(state):
            delta_v = self._consume_maneuver_resources(state, hour)
            return Mode.MANEUVER, True, False, delta_v

        state.maneuver_skipped_count += 1
        if self._orbit_correction_needed(state):
            state.orbit_correction_skipped_count += 1
        fallback = (
            Mode.SAFE
            if not self._maneuver_energy_sufficient(state)
            else Mode.STANDBY
        )
        return fallback, False, True, self.config.minimum_percent

    def _update_plan_and_contact_state(
        self,
        state: SatelliteState,
        contact: ContactInfo,
        hour: int,
        policy_state: SatelliteState | None = None,
        *,
        upload_allowed: bool = True,
    ) -> bool:
        plan_uploaded = False
        if self.operator_view == "delayed_telemetry" and state.current_plan:
            state.daily_plan_age_hours = max(
                0, hour - state.current_plan.uploaded_hour
            )

        if contact.cmd_contact_min > self.config.minimum_percent:
            needs_plan = self._daily_plan_upload_needed(
                state, contact, hour
            )
            state.hours_since_contact = 0
            state.emergency_beacon_mode = False
            if needs_plan and upload_allowed:
                plan_state = (
                    policy_state
                    if policy_state is not None
                    else self._policy_state(state)
                )
                state.current_plan = self._build_daily_plan(
                    plan_state, hour, contact
                )
                state.daily_plan_age_hours = 0
                state.backup_mode = False
                state.emergency_beacon_mode = False
                plan_uploaded = True
        else:
            state.hours_since_contact += 1
            if not (
                self.operator_view == "delayed_telemetry"
                and state.current_plan is not None
            ):
                state.daily_plan_age_hours += 1

        if state.hours_since_contact >= self.config.emergency_after_hours:
            state.emergency_beacon_mode = True
            state.backup_mode = False
        elif self.operator_view == "delayed_telemetry":
            state.backup_mode = self._plan_mode_details(state).planned_mode is None
        elif state.daily_plan_age_hours > self.config.plan_duration_hours:
            state.backup_mode = True
        return plan_uploaded

    def _daily_plan_upload_needed(
        self, state: SatelliteState, contact: ContactInfo, hour: int
    ) -> bool:
        if contact.cmd_contact_min <= self.config.minimum_percent:
            return False
        plan_age = state.daily_plan_age_hours
        if self.operator_view == "delayed_telemetry" and state.current_plan:
            plan_age = max(0, hour - state.current_plan.uploaded_hour)
        return (
            state.current_plan is None
            or plan_age >= self.config.plan_duration_hours
            or (
                self.operator_view == "delayed_telemetry"
                and state.current_plan is not None
                and plan_age >= len(state.current_plan.planned_modes)
            )
        )

    def _build_daily_plan(
        self,
        policy_state: SatelliteState,
        upload_hour: int,
        contact: ContactInfo,
    ) -> DailyPlan:
        """Build a lightweight mode sequence from current operator knowledge.

        The upload-hour contact is known after scenario modification. Future
        contacts use only the base contact model; future disruptions are not
        forecast. A projected copy advances with existing mode effects so the
        policy can react to estimated SOC and buffer changes without mutating
        either real or observed state.
        """
        projected_state = deepcopy(policy_state)
        planning_policy = (
            self.policy
            if self.operator_view == "delayed_telemetry"
            else deepcopy(self.policy)
        )
        planned_modes: list[Mode] = []
        energy_risks: list[bool | None] = []
        storage_risks: list[bool | None] = []
        expected_data_contact_minutes: list[float] = []
        expected_cmd_contact_minutes: list[float] = []
        state_aware_geometry = self._uses_state_aware_geometry()
        planning_contact_cache: dict[
            tuple[object, ...], ContactInfo
        ] = {}
        fixed_data_contact_fraction = None
        if self.planning_model == "risk_aware" and not state_aware_geometry:
            # Preserve the established whole-plan contact fraction for contact
            # models whose output is independent of projected orbit state.
            fixed_data_contact_fraction = (
                self._forecast_remaining_data_contact_fraction(
                    projected_state,
                    upload_hour,
                    0,
                    contact,
                    planning_contact_cache,
                )
            )
        for plan_index in range(self.config.plan_duration_hours):
            expected_contact = (
                contact
                if plan_index == 0
                else self._planning_base_contact(
                    upload_hour + plan_index,
                    projected_state,
                    planning_contact_cache,
                )
            )
            expected_data_contact_minutes.append(
                expected_contact.data_contact_min
            )
            expected_cmd_contact_minutes.append(
                expected_contact.cmd_contact_min
            )
            if self.planning_model == "risk_aware":
                data_contact_fraction = fixed_data_contact_fraction
                if state_aware_geometry:
                    data_contact_fraction = (
                        self._forecast_remaining_data_contact_fraction(
                            projected_state,
                            upload_hour,
                            plan_index,
                            expected_contact,
                            planning_contact_cache,
                        )
                    )
                if data_contact_fraction is None:
                    raise RuntimeError(
                        "risk-aware contact fraction was not initialized"
                    )
                planned_mode, energy_risk, storage_risk = (
                    self._risk_aware_planned_mode(
                        projected_state,
                        expected_contact,
                        plan_index,
                        data_contact_fraction,
                        self.policy.operator_profile,
                    )
                )
            else:
                planned_mode = planning_policy.select_mode(
                    deepcopy(projected_state), expected_contact
                )
                energy_risk = None
                storage_risk = None
            planned_modes.append(planned_mode)
            energy_risks.append(energy_risk)
            storage_risks.append(storage_risk)
            projected_state.mode = planned_mode
            if planned_mode == Mode.MANEUVER:
                self._consume_maneuver_resources(
                    projected_state, upload_hour + plan_index
                )
            self._execute_mode(
                projected_state,
                planned_mode,
                expected_contact,
                count_overflow=False,
                hour=upload_hour + plan_index,
            )
            if plan_index + 1 < self.config.plan_duration_hours:
                self._advance_orbit_drift_proxy(projected_state)

        return DailyPlan(
            uploaded_hour=upload_hour,
            duration_hours=self.config.plan_duration_hours,
            planned_modes=tuple(planned_modes),
            energy_risk_by_hour=tuple(energy_risks),
            storage_risk_by_hour=tuple(storage_risks),
            expected_data_contact_min_by_hour=tuple(
                expected_data_contact_minutes
            ),
            expected_cmd_contact_min_by_hour=tuple(
                expected_cmd_contact_minutes
            ),
            policy_name=self.policy.name,
            based_on_telemetry_hour=self.last_telemetry_hour,
            based_on_telemetry_age_hours=self.telemetry_age_hours,
        )

    def _forecast_remaining_data_contact_fraction(
        self,
        projected_state: SatelliteState,
        upload_hour: int,
        plan_index: int,
        current_contact: ContactInfo,
        contact_cache: dict[tuple[object, ...], ContactInfo],
    ) -> float:
        """Estimate remaining base data contacts from a defensive projection.

        The current planned hour uses its already selected contact. Later hours
        use only the base contact model after advancing a private orbit/drift
        projection. Scenario disruptions and external events are deliberately
        absent from this planning forecast.
        """
        remaining_hours = self.config.plan_duration_hours - plan_index
        if remaining_hours <= 0:
            return self.config.minimum_percent

        forecast_state = deepcopy(projected_state)
        data_contact_hours = int(
            current_contact.data_contact_min > self.config.minimum_percent
        )
        for future_index in range(
            plan_index + 1, self.config.plan_duration_hours
        ):
            self._advance_orbit_drift_proxy(forecast_state)
            future_contact = self._planning_base_contact(
                upload_hour + future_index,
                forecast_state,
                contact_cache,
            )
            data_contact_hours += int(
                future_contact.data_contact_min
                > self.config.minimum_percent
            )
        return data_contact_hours / remaining_hours

    def _planning_base_contact(
        self,
        hour: int,
        projected_state: SatelliteState,
        contact_cache: dict[tuple[object, ...], ContactInfo],
    ) -> ContactInfo:
        """Return one base forecast contact, reusing only identical orbit states."""
        if not self._uses_state_aware_geometry():
            return self.nominal_contact(
                hour, projected_state, record_diagnostics=False
            )

        key = (
            hour,
            projected_state.orbit_altitude_offset_km,
            projected_state.orbit_phase_error_deg,
            projected_state.orbit_groundtrack_error_km,
        )
        if key not in contact_cache:
            contact_cache[key] = self.nominal_contact(
                hour, projected_state, record_diagnostics=False
            )
        return contact_cache[key]

    def _risk_aware_planned_mode(
        self,
        state: SatelliteState,
        contact: ContactInfo,
        plan_index: int,
        data_contact_fraction: float,
        profile: OperatorProfile,
    ) -> tuple[Mode, bool, bool]:
        """Choose one projected mode with a readable forward-risk heuristic."""
        energy_margin = self.effective_energy_margin(state)
        usable_storage = self.effective_storage_capacity_gb(state)
        buffer_fraction = (
            state.data_buffer_gb / usable_storage
            if usable_storage > self.config.minimum_percent
            else self.config.maximum_health
        )
        storage_remaining = max(
            self.config.minimum_percent,
            usable_storage - state.data_buffer_gb,
        )
        battery_deficit = self.config.maximum_health - self._clamp(
            state.battery_health,
            self.config.minimum_health,
            self.config.maximum_health,
        )
        solar_deficit = self.config.maximum_health - self._clamp(
            state.solar_health,
            self.config.minimum_health,
            self.config.maximum_health,
        )
        projected_telemetry_age = self.telemetry_age_hours + plan_index
        contact_scarcity = self.config.maximum_health - data_contact_fraction
        battery_reserve = (
            20.0 * battery_deficit * profile.battery_protection_bias
        )
        outage_reserve = profile.outage_reserve_bias * (
            10.0 * contact_scarcity
            + 5.0
            * min(
                2.0,
                projected_telemetry_age / self.config.hours_per_day,
            )
        )
        solar_reserve = 10.0 * solar_deficit * profile.outage_reserve_bias
        energy_floor = (
            profile.energy_floor
            + battery_reserve
            + outage_reserve
            + solar_reserve
        )
        imaging_floor = max(
            energy_floor,
            profile.imaging_energy_floor + battery_reserve + solar_reserve,
        )
        energy_risk = energy_margin < imaging_floor
        storage_risk = (
            buffer_fraction >= profile.buffer_high_fraction
            or storage_remaining
            < self.effective_imaging_rate_gb_per_hour(state)
        )

        if self._risk_aware_maneuver_allowed(
            state, energy_floor, profile, plan_index
        ):
            return Mode.MANEUVER, energy_risk, storage_risk

        if energy_margin < energy_floor:
            if (
                profile.standby_bias >= 0.75
                or energy_margin < energy_floor - 5.0
            ):
                return Mode.SAFE, energy_risk, storage_risk
            return Mode.STANDBY, energy_risk, storage_risk

        has_data_contact = contact.data_contact_min > self.config.minimum_percent
        if has_data_contact and state.data_buffer_gb > self.config.minimum_percent:
            downlink_score = (
                profile.downlink_bias
                + 0.50 * buffer_fraction
                + 0.25 * contact_scarcity
            )
            if storage_risk or downlink_score >= 0.75:
                return Mode.DOWNLINK, energy_risk, storage_risk

        high_data_tolerance = self.policy.name in (
            "aggressive", "data_maximizer"
        )
        if storage_risk and not (
            high_data_tolerance
            and buffer_fraction < profile.buffer_critical_fraction
            and energy_margin >= imaging_floor + 10.0
        ):
            return Mode.STANDBY, energy_risk, storage_risk

        if (
            state.battery_health < 0.60
            and profile.battery_protection_bias >= 0.70
        ):
            return Mode.STANDBY, energy_risk, storage_risk

        imaging_score = (
            profile.imaging_bias
            + (
                0.10 * profile.imaging_bias
                if contact.cmd_contact_min > self.config.minimum_percent
                else 0.0
            )
            - 0.30 * contact_scarcity * profile.outage_reserve_bias
            - 0.30 * battery_deficit * profile.battery_protection_bias
        )
        standby_score = profile.standby_bias + (0.25 if energy_risk else 0.0)
        imaging_interval = max(
            1,
            round(
                2.0
                + 6.0 * (1.0 - profile.imaging_bias)
                + 2.0 * profile.standby_bias
                + 2.0 * profile.outage_reserve_bias
            ),
        )
        sparse_imaging_opportunity = plan_index % imaging_interval == 0
        if (
            energy_margin >= imaging_floor
            and buffer_fraction < profile.buffer_critical_fraction
            and (
                imaging_score > standby_score
                or sparse_imaging_opportunity
            )
        ):
            return Mode.IMAGING, energy_risk, storage_risk
        return Mode.STANDBY, energy_risk, storage_risk

    def _risk_aware_maneuver_allowed(
        self,
        state: SatelliteState,
        energy_floor: float,
        profile: OperatorProfile,
        plan_index: int,
    ) -> bool:
        """Apply operator-style reserves to an otherwise feasible maneuver."""
        if self.maneuver_model != "stationkeeping_proxy":
            return False
        # The projected plan state advances drift and geometry error between
        # entries. Fixed-orbit planning retains the V2.7 drift-only trigger.
        geometry_correction_due = (
            self.orbit_evolution_model == "drift_proxy"
            and (
                state.orbit_geometry_degraded
                or abs(state.orbit_groundtrack_error_km)
                >= self.config.orbit_geometry_degraded_threshold_km
                or abs(state.orbit_altitude_offset_km)
                >= self.config.orbit_geometry_degraded_threshold_km
                or self._orbit_geometry_error_km(state)
                >= self.config.orbit_geometry_degraded_threshold_km
            )
        )
        if self.stationkeeping_planning_model == "drift_aware":
            remaining_hours = max(
                0, self.config.plan_duration_hours - plan_index - 1
            )
            projected_drift = (
                state.orbit_drift_proxy_km
                + self.config.orbit_drift_proxy_km_per_day
                / self.config.hours_per_day
                * remaining_hours
            )
            stationkeeping = self._stationkeeping_assessment(
                state,
                Mode.MANEUVER,
                projected_critical_within_plan=(
                    projected_drift
                    >= self.config.orbit_drift_critical_threshold_km
                ),
            )
            if not stationkeeping.selected:
                return False
        else:
            # Preserve the complete V3.4.2 trigger path under the default
            # legacy selector, including fixed-orbit drift-only planning.
            if not (state.maneuver_due or geometry_correction_due):
                return False
            if not self._maneuver_resources_available(state):
                return False

        urgent = (
            state.orbit_drift_critical
            or (
                self.orbit_evolution_model == "drift_proxy"
                and self._orbit_geometry_error_km(state)
                >= self.config.orbit_geometry_critical_threshold_km
            )
        )
        reserve_by_policy = {
            "aggressive": -5.0,
            "data_maximizer": -5.0,
            "balanced": 0.0,
            "contact_opportunist": 0.0,
            "adaptive": 3.0,
            "downlink_priority": 3.0,
            "storage_guardian": 4.0,
            "conservative": 6.0,
            "survival_first": 2.0 if urgent else 12.0,
            "power_saver": 12.0,
            "battery_protective": 10.0,
            "outage_resilient": 4.0 if urgent else 10.0,
        }
        if (
            self.policy.name == "battery_protective"
            and state.battery_health < 0.60
            and not urgent
        ):
            return False
        maneuver_floor = max(
            self.policy.safe_threshold,
            energy_floor + reserve_by_policy.get(self.policy.name, 5.0),
        ) + abs(self.config.maneuver_soc_delta)
        return self.effective_energy_margin(state) >= maneuver_floor

    @staticmethod
    def _plan_mode_details(
        state: SatelliteState,
    ) -> PlanHourDetails:
        plan = state.current_plan
        if plan is None:
            return PlanHourDetails(None, None, 0, None, None, None, None)
        plan_index = state.daily_plan_age_hours
        modes_remaining = max(0, len(plan.planned_modes) - plan_index)
        if plan_index < 0 or plan_index >= len(plan.planned_modes):
            return PlanHourDetails(
                None, plan_index, modes_remaining, None, None, None, None
            )

        def at(values, default=None):
            return values[plan_index] if plan_index < len(values) else default

        return PlanHourDetails(
            planned_mode=plan.planned_modes[plan_index],
            plan_mode_index=plan_index,
            plan_modes_remaining=modes_remaining,
            energy_risk=at(plan.energy_risk_by_hour),
            storage_risk=at(plan.storage_risk_by_hour),
            expected_data_contact_min=at(
                plan.expected_data_contact_min_by_hour
            ),
            expected_cmd_contact_min=at(
                plan.expected_cmd_contact_min_by_hour
            ),
        )

    def _select_mode(self, state: SatelliteState, contact: ContactInfo) -> Mode:
        selected, _, _, _ = self._select_mode_details(state, contact)
        state.mode = selected
        return selected

    def _select_mode_details(
        self,
        state: SatelliteState,
        contact: ContactInfo,
        policy_state: SatelliteState | None = None,
        planned_mode: Mode | None = None,
    ) -> tuple[Mode, bool, bool, bool]:
        if state.emergency_beacon_mode:
            selected = Mode.EMERGENCY_BEACON
        elif state.backup_mode:
            selected = Mode.BACKUP
        elif self.operator_view == "delayed_telemetry":
            selected = planned_mode if planned_mode is not None else Mode.BACKUP
        else:
            decision_state = policy_state if policy_state is not None else state
            selected = self.policy.select_mode(decision_state, contact)

        maneuver_intended = selected == Mode.MANEUVER
        energy_margin = self.effective_energy_margin(state)
        safe_override = (
            not state.emergency_beacon_mode
            and energy_margin < self.policy.safe_threshold
            and selected != Mode.SAFE
        )
        if (
            not state.emergency_beacon_mode
            and energy_margin < self.policy.safe_threshold
        ):
            selected = Mode.SAFE
        payload_unavailable = False
        if selected == Mode.IMAGING and (
            state.payload_health < self.config.payload_failure_health
            or state.data_buffer_gb
            >= self.config.imaging_block_fraction * self.effective_storage_capacity_gb(state)
        ):
            payload_unavailable = state.payload_health < self.config.payload_failure_health
            selected = Mode.STANDBY
        return selected, safe_override, payload_unavailable, maneuver_intended

    def _execute_mode(
        self,
        state: SatelliteState,
        mode: Mode,
        contact: ContactInfo,
        count_overflow: bool = True,
        hour: int = 0,
        target_data_multiplier: float = 1.0,
        pointing_multiplier: float = 1.0,
    ) -> PowerAssessment:
        if mode == Mode.MANEUVER and self.maneuver_model == "none":
            mode = Mode.STANDBY
        overflow_before_mode = state.overflow_hours
        self._enforce_storage_capacity(state, increment_hour=count_overflow)
        overflow_already_counted = state.overflow_hours > overflow_before_mode
        deltas = {
            Mode.SAFE: self.config.soc_safe_delta,
            Mode.STANDBY: self.config.soc_standby_delta,
            Mode.IMAGING: self.config.soc_imaging_delta,
            Mode.DOWNLINK: self.config.soc_downlink_delta,
            Mode.MANEUVER: self.config.maneuver_soc_delta,
            Mode.BACKUP: self.config.soc_backup_delta,
            Mode.EMERGENCY_BEACON: self.config.soc_emergency_delta,
        }
        power_assessment = assess_power_for_hour(
            power_model=self.power_model,
            hour=hour,
            mode=mode,
            base_soc_delta=deltas[mode],
            generation_efficiency=(
                state.solar_health * state.eps_health(self.config)
            ),
            config=self.config,
        )
        soc_before = state.soc
        state.soc = self._clamp(
            state.soc + power_assessment.soc_delta_power_model,
            self.config.minimum_percent,
            self.config.maximum_percent,
        )
        power_assessment = replace(
            power_assessment,
            soc_delta_power_model=state.soc - soc_before,
        )
        state.minimum_soc = min(state.minimum_soc, state.soc)

        if mode == Mode.IMAGING:
            clamped_target_data_multiplier = self._clamp(
                target_data_multiplier,
                self.config.minimum_health,
                self.config.maximum_health,
            )
            clamped_pointing_multiplier = self._clamp(
                pointing_multiplier,
                self.config.minimum_health,
                self.config.maximum_health,
            )
            combined_imaging_multiplier = (
                clamped_target_data_multiplier * clamped_pointing_multiplier
            )
            generated = (
                self.effective_imaging_rate_gb_per_hour(state)
                * combined_imaging_multiplier
            )
            state.total_data_generated_gb += generated
            if combined_imaging_multiplier > self.config.minimum_percent:
                state.total_images_taken += 1
            available = max(
                self.config.minimum_percent,
                self.effective_storage_capacity_gb(state) - state.data_buffer_gb,
            )
            stored = min(generated, available)
            state.data_buffer_gb += stored
            lost = generated - stored
            if lost > self.config.minimum_percent:
                state.data_lost_gb += lost
                if count_overflow and not overflow_already_counted:
                    state.overflow_hours += 1
                    overflow_already_counted = True
        elif mode == Mode.DOWNLINK and contact.data_contact_min > self.config.minimum_percent:
            downlinked = min(
                state.data_buffer_gb,
                self.effective_downlink_rate_gb_per_min(state)
                * contact.data_contact_min
                * self._clamp(
                    pointing_multiplier,
                    self.config.minimum_health,
                    self.config.maximum_health,
                ),
            )
            state.data_buffer_gb -= downlinked
            state.total_data_downlinked_gb += downlinked
        state.data_buffer_gb = max(
            self.config.minimum_percent,
            state.data_buffer_gb,
        )
        self._enforce_storage_capacity(
            state,
            increment_hour=count_overflow and not overflow_already_counted,
        )
        return power_assessment

    def _degrade_health(self, state: SatelliteState, mode: Mode) -> None:
        load_multiplier = self.high_load_degradation_multiplier(state, mode)
        state.solar_health -= (
            self.config.solar_annual_degradation
            * self.scenario.solar_degradation_multiplier
            / self.config.hours_per_year
        )
        state.battery_health -= (
            self.config.battery_annual_degradation
            * self.scenario.battery_degradation_multiplier
            * load_multiplier
            / self.config.hours_per_year
        )
        state.payload_health -= (
            self.config.payload_annual_degradation
            * self.scenario.payload_degradation_multiplier
            * load_multiplier
            / self.config.hours_per_year
        )
        state.storage_health -= (
            self.config.storage_annual_degradation
            * self.scenario.storage_degradation_multiplier
            * load_multiplier
            / self.config.hours_per_year
        )
        state.comms_health -= (
            self.config.comms_annual_degradation
            * self.scenario.comms_degradation_multiplier
            * load_multiplier
            / self.config.hours_per_year
        )
        placeholder_loss = self.config.placeholder_annual_degradation / self.config.hours_per_year
        state.adcs_health -= placeholder_loss
        state.obc_health -= placeholder_loss
        state.thermal_health -= placeholder_loss
        state.propulsion_health -= placeholder_loss
        if mode == Mode.IMAGING:
            state.payload_health -= (
                self.config.payload_imaging_degradation_per_hour
                * self.scenario.payload_degradation_multiplier
                * load_multiplier
            )
        if state.data_buffer_gb > self.config.storage_stress_fraction * self.config.storage_capacity_gb:
            state.storage_health -= (
                self.config.storage_stress_degradation_per_hour
                * self.scenario.storage_degradation_multiplier
                * load_multiplier
            )

        for field_name in (
            "solar_health", "battery_health", "payload_health", "storage_health",
            "comms_health", "adcs_health", "obc_health", "thermal_health",
            "propulsion_health",
        ):
            setattr(
                state,
                field_name,
                self._clamp(
                    getattr(state, field_name),
                    self.config.minimum_health,
                    self.config.maximum_health,
                ),
            )

    def _check_survival(self, state: SatelliteState) -> None:
        if state.soc <= self.config.critical_soc:
            state.critical_soc_hours += 1
        else:
            state.critical_soc_hours = 0
        if state.critical_soc_hours > self.config.critical_soc_max_consecutive_hours:
            state.alive = False
            state.loss_reason = LossReason.CRITICAL_POWER
        elif state.eps_health(self.config) < self.config.eps_failure_health:
            state.alive = False
            state.loss_reason = LossReason.EPS_FAILURE
        elif state.comms_health < self.config.comms_failure_health:
            state.alive = False
            state.loss_reason = LossReason.COMMUNICATION_FAILURE
        elif state.storage_health < self.config.storage_failure_health:
            state.alive = False
            state.loss_reason = LossReason.STORAGE_FAILURE
        elif state.obc_health < self.config.obc_failure_health:
            state.alive = False
            state.loss_reason = LossReason.OBC_FAILURE
        elif state.adcs_health < self.config.adcs_failure_health:
            state.alive = False
            state.loss_reason = LossReason.ADCS_FAILURE
        elif state.thermal_health < self.config.thermal_failure_health:
            state.alive = False
            state.loss_reason = LossReason.THERMAL_FAILURE

    def _checkpoint(self, state: SatelliteState, completed_hour: int) -> Checkpoint:
        fixed_orbit = position_at_hour(completed_hour, self.config)
        orbit = (
            fixed_orbit
            if self.orbit_evolution_model == "fixed"
            else self._active_orbit_position(state, completed_hour)
        )
        return Checkpoint(
            completed_hour,
            completed_hour / self.config.hours_per_year,
            state.soc,
            state.data_buffer_gb,
            state.total_health(self.config),
            state.alive,
            state.mode.value,
            state.total_data_downlinked_gb,
            state.hours_since_contact,
            state.daily_plan_age_hours,
            orbit.latitude_deg,
            orbit.longitude_deg,
            orbit.altitude_km,
            state.data_lost_gb,
            state.overflow_hours,
            self.effective_storage_capacity_gb(state),
        )

    def _hour_record(
        self,
        state: SatelliteState,
        base_contact: ContactInfo,
        contact: ContactInfo,
        hour: int,
        operator_diagnostics: dict[str, object],
        plan_uploaded_this_hour: bool,
        plan_details: PlanHourDetails,
        maneuver_executed_this_hour: bool,
        maneuver_skipped_this_hour: bool,
        maneuver_delta_v_used_this_hour: float,
        debris_outcome: DebrisAvoidanceOutcome,
        debris_assessment: DebrisRiskAssessment | None,
        autonomy_decision: AutonomyDecision,
        stationkeeping_assessment: StationkeepingAssessment,
        power_assessment: PowerAssessment,
        thermal_assessment: ThermalAssessment,
        target_assessment: TargetAssessment,
        pointing_assessment: PointingAssessment,
        packet_assessment: PacketHourAssessment,
        orbit_drift_damage_this_hour: float,
    ) -> HourRecord:
        fixed_orbit = position_at_hour(hour, self.config)
        orbit = (
            fixed_orbit
            if self.orbit_evolution_model == "fixed"
            else self._active_orbit_position(state, hour)
        )
        contact_diagnostics = self._contact_diagnostics(hour, base_contact)
        fuel = self._fuel_percentages(state)
        lifecycle = self.lifecycle_diagnostics(hour)
        (
            contingency_active,
            contingency_age,
            contingency_expires_in,
        ) = self._contingency_plan_diagnostics(hour)
        current_plan = state.current_plan
        return HourRecord(
            hour=hour,
            year=hour / self.config.hours_per_year,
            mode=state.mode.value,
            soc=state.soc,
            health=state.total_health(self.config),
            eps_health=state.eps_health(self.config),
            solar_health=state.solar_health,
            battery_health=state.battery_health,
            comms_health=state.comms_health,
            payload_health=state.payload_health,
            storage_health=state.storage_health,
            adcs_health=state.adcs_health,
            obc_health=state.obc_health,
            thermal_health=state.thermal_health,
            propulsion_health=state.propulsion_health,
            buffer_gb=state.data_buffer_gb,
            data_generated_gb=state.total_data_generated_gb,
            data_downlinked_gb=state.total_data_downlinked_gb,
            cmd_contact_min=contact.cmd_contact_min,
            data_contact_min=contact.data_contact_min,
            **contact_diagnostics,
            **operator_diagnostics,
            planning_model=self.planning_model,
            maneuver_model=self.maneuver_model,
            orbit_evolution_model=self.orbit_evolution_model,
            stationkeeping_planning_model=(
                self.stationkeeping_planning_model
            ),
            power_model=self.power_model,
            sunlight_factor_this_hour=(
                power_assessment.sunlight_factor
            ),
            eclipse_this_hour=power_assessment.eclipse,
            eclipse_fraction_reference=(
                power_assessment.eclipse_fraction_reference
            ),
            power_load_proxy_w_this_hour=(
                power_assessment.power_load_proxy_w
            ),
            power_generation_proxy_w_this_hour=(
                power_assessment.power_generation_proxy_w
            ),
            net_power_proxy_w_this_hour=(
                power_assessment.net_power_proxy_w
            ),
            soc_delta_power_model_this_hour=(
                power_assessment.soc_delta_power_model
            ),
            thermal_model=self.thermal_model,
            thermal_load_proxy_this_hour=(
                thermal_assessment.thermal_load_proxy_this_hour
            ),
            thermal_hot_stress_this_hour=(
                thermal_assessment.thermal_hot_stress_this_hour
            ),
            thermal_cold_stress_this_hour=(
                thermal_assessment.thermal_cold_stress_this_hour
            ),
            thermal_stress_this_hour=(
                thermal_assessment.thermal_stress_this_hour
            ),
            thermal_degradation_this_hour=(
                thermal_assessment.thermal_degradation_this_hour
            ),
            thermal_reason_this_hour=(
                thermal_assessment.thermal_reason_this_hour
            ),
            target_model=self.target_model,
            target_opportunity_this_hour=(
                target_assessment.target_opportunity_this_hour
            ),
            target_selected_this_hour=(
                target_assessment.target_selected_this_hour
            ),
            target_scene_id_this_hour=(
                target_assessment.target_scene_id_this_hour
            ),
            target_scene_area_km2_this_hour=(
                target_assessment.target_scene_area_km2_this_hour
            ),
            target_priority_this_hour=(
                target_assessment.target_priority_this_hour
            ),
            target_imagery_mode_this_hour=(
                target_assessment.target_imagery_mode_this_hour
            ),
            target_data_multiplier_this_hour=(
                target_assessment.target_data_multiplier_this_hour
            ),
            target_missed_reason_this_hour=(
                target_assessment.target_missed_reason_this_hour
            ),
            target_reason_this_hour=(
                target_assessment.target_reason_this_hour
            ),
            pointing_model=self.pointing_model,
            pointing_required_this_hour=(
                pointing_assessment.pointing_required_this_hour
            ),
            pointing_quality_this_hour=(
                pointing_assessment.pointing_quality_this_hour
            ),
            pointing_multiplier_this_hour=(
                pointing_assessment.pointing_multiplier_this_hour
            ),
            pointing_limited_this_hour=(
                pointing_assessment.pointing_limited_this_hour
            ),
            pointing_missed_this_hour=(
                pointing_assessment.pointing_missed_this_hour
            ),
            pointing_off_nadir_proxy_deg_this_hour=(
                pointing_assessment.pointing_off_nadir_proxy_deg_this_hour
            ),
            pointing_slew_proxy_deg_this_hour=(
                pointing_assessment.pointing_slew_proxy_deg_this_hour
            ),
            pointing_reason_this_hour=(
                pointing_assessment.pointing_reason_this_hour
            ),
            packet_model=self.packet_model,
            packet_delivery_model=self.packet_delivery_model,
            telemetry_packet_generated_this_hour=(
                packet_assessment.telemetry_packet_generated_this_hour
            ),
            telemetry_packet_delivery_attempted_this_hour=(
                packet_assessment.telemetry_packet_delivery_attempted_this_hour
            ),
            telemetry_packet_downlinked_this_hour=(
                packet_assessment.telemetry_packet_downlinked_this_hour
            ),
            telemetry_packet_delivery_failed_this_hour=(
                packet_assessment.telemetry_packet_delivery_failed_this_hour
            ),
            command_packets_attempted_this_hour=(
                packet_assessment.command_packets_attempted_this_hour
            ),
            command_packets_uploaded_this_hour=(
                packet_assessment.command_packets_uploaded_this_hour
            ),
            command_packets_failed_this_hour=(
                packet_assessment.command_packets_failed_this_hour
            ),
            daily_plan_packet_delivery_attempted_this_hour=(
                packet_assessment.daily_plan_packet_delivery_attempted_this_hour
            ),
            daily_plan_packet_uploaded_this_hour=(
                packet_assessment.daily_plan_packet_uploaded_this_hour
            ),
            daily_plan_packet_delivery_failed_this_hour=(
                packet_assessment.daily_plan_packet_delivery_failed_this_hour
            ),
            packet_uplink_kb_this_hour=(
                packet_assessment.packet_uplink_kb_this_hour
            ),
            packet_downlink_kb_this_hour=(
                packet_assessment.packet_downlink_kb_this_hour
            ),
            packet_reason_this_hour=(
                packet_assessment.packet_reason_this_hour
            ),
            packet_delivery_reason_this_hour=(
                packet_assessment.packet_delivery_reason_this_hour
            ),
            event_lifecycle_model=self.event_lifecycle_model,
            debris_risk_model=self.debris_risk_model,
            autonomy_model=self.autonomy_model,
            autonomy_active_this_hour=autonomy_decision.active,
            autonomy_trigger_this_hour=autonomy_decision.trigger,
            autonomy_authority_this_hour=autonomy_decision.authority,
            autonomy_selected_mode_this_hour=(
                autonomy_decision.selected_mode
            ),
            autonomy_reason_this_hour=autonomy_decision.reason,
            autonomy_pre_authorized_this_hour=(
                autonomy_decision.pre_authorized
            ),
            autonomy_ground_contact_required_this_hour=(
                autonomy_decision.ground_contact_required
            ),
            autonomy_used_uploaded_response_this_hour=(
                autonomy_decision.used_uploaded_response
            ),
            contingency_plan_active=contingency_active,
            contingency_plan_age_hours=contingency_age,
            contingency_plan_expires_in_hours=contingency_expires_in,
            lifecycle_ground_known_count=(
                lifecycle.lifecycle_ground_known_count
            ),
            lifecycle_spacecraft_known_count=(
                lifecycle.lifecycle_spacecraft_known_count
            ),
            lifecycle_uploaded_count=lifecycle.lifecycle_uploaded_count,
            lifecycle_pending_count=lifecycle.lifecycle_pending_count,
            lifecycle_active_count=lifecycle.lifecycle_active_count,
            lifecycle_missed_upload_count=(
                lifecycle.lifecycle_missed_upload_count
            ),
            lifecycle_next_warning_hour=(
                lifecycle.lifecycle_next_warning_hour
            ),
            lifecycle_next_execution_hour=(
                lifecycle.lifecycle_next_execution_hour
            ),
            plan_uploaded_this_hour=plan_uploaded_this_hour,
            plan_policy=(
                current_plan.policy_name if current_plan is not None else None
            ),
            plan_based_on_telemetry_hour=(
                current_plan.based_on_telemetry_hour
                if current_plan is not None
                else None
            ),
            plan_based_on_telemetry_age_hours=(
                current_plan.based_on_telemetry_age_hours
                if current_plan is not None
                else None
            ),
            planned_mode=(
                plan_details.planned_mode.value
                if plan_details.planned_mode is not None
                else None
            ),
            plan_mode_index=plan_details.plan_mode_index,
            plan_modes_remaining=plan_details.plan_modes_remaining,
            planning_energy_risk=plan_details.energy_risk,
            planning_storage_risk=plan_details.storage_risk,
            planning_expected_data_contact_min=(
                plan_details.expected_data_contact_min
            ),
            planning_expected_cmd_contact_min=(
                plan_details.expected_cmd_contact_min
            ),
            delta_v_remaining_m_per_s=state.delta_v_remaining_m_per_s,
            delta_v_used_m_per_s=state.delta_v_used_m_per_s,
            fuel_remaining_percent=fuel["fuel_remaining_percent"],
            fuel_used_percent=fuel["fuel_used_percent"],
            stationkeeping_delta_v_cost_percent=(
                fuel["stationkeeping_delta_v_cost_percent"]
            ),
            debris_avoidance_delta_v_cost_percent=(
                fuel["debris_avoidance_delta_v_cost_percent"]
            ),
            maneuver_count=state.maneuver_count,
            maneuver_skipped_count=state.maneuver_skipped_count,
            orbit_drift_proxy_km=state.orbit_drift_proxy_km,
            orbit_altitude_offset_km=state.orbit_altitude_offset_km,
            orbit_phase_error_deg=state.orbit_phase_error_deg,
            orbit_groundtrack_error_km=state.orbit_groundtrack_error_km,
            orbit_geometry_degraded=state.orbit_geometry_degraded,
            orbit_correction_count=state.orbit_correction_count,
            orbit_correction_skipped_count=(
                state.orbit_correction_skipped_count
            ),
            maneuver_due=state.maneuver_due,
            maneuver_executed_this_hour=maneuver_executed_this_hour,
            maneuver_skipped_this_hour=maneuver_skipped_this_hour,
            maneuver_delta_v_used_this_hour=(
                maneuver_delta_v_used_this_hour
            ),
            planned_maneuver=plan_details.planned_mode == Mode.MANEUVER,
            stationkeeping_drift_risk_class_this_hour=(
                stationkeeping_assessment.drift_risk_class
            ),
            stationkeeping_priority_this_hour=(
                stationkeeping_assessment.priority
            ),
            stationkeeping_recommended_this_hour=(
                stationkeeping_assessment.recommended
            ),
            stationkeeping_feasible_this_hour=(
                stationkeeping_assessment.feasible
            ),
            stationkeeping_selected_this_hour=(
                stationkeeping_assessment.selected
            ),
            stationkeeping_reason_this_hour=(
                stationkeeping_assessment.reason
            ),
            stationkeeping_deferred_reason_this_hour=(
                stationkeeping_assessment.deferred_reason
            ),
            stationkeeping_blocked_by_priority_this_hour=(
                stationkeeping_assessment.blocked_by_priority
            ),
            debris_conjunction_active=state.debris_conjunction_active,
            debris_avoidance_required_this_hour=(
                state.debris_avoidance_required_this_hour
            ),
            debris_avoidance_executed_count=(
                state.debris_avoidance_executed_count
            ),
            debris_avoidance_skipped_count=(
                state.debris_avoidance_skipped_count
            ),
            debris_avoidance_executed_this_hour=debris_outcome.executed,
            debris_avoidance_skipped_this_hour=debris_outcome.skipped,
            debris_damage_events=state.debris_damage_events,
            debris_damage_this_hour=debris_outcome.damage,
            debris_damage_accumulated=state.debris_damage_accumulated,
            debris_risk_class_this_hour=(
                debris_assessment.risk_class
                if debris_assessment is not None else None
            ),
            debris_impact_zone_this_hour=(
                debris_assessment.impact_zone
                if debris_assessment is not None else None
            ),
            debris_risk_score_this_hour=(
                debris_assessment.risk_score
                if debris_assessment is not None else None
            ),
            debris_object_size_cm_this_hour=(
                debris_assessment.object_size_cm
                if debris_assessment is not None else None
            ),
            debris_miss_distance_proxy_m_this_hour=(
                debris_assessment.miss_distance_proxy_m
                if debris_assessment is not None else None
            ),
            debris_damage_targets_this_hour=(
                ",".join(debris_assessment.damage_targets)
                if debris_assessment is not None else None
            ),
            orbit_drift_warning=state.orbit_drift_warning,
            orbit_drift_critical=state.orbit_drift_critical,
            orbit_drift_damage_events=state.orbit_drift_damage_events,
            orbit_drift_damage_this_hour=orbit_drift_damage_this_hour,
            orbit_drift_damage_accumulated=(
                state.orbit_drift_damage_accumulated
            ),
            hours_since_contact=state.hours_since_contact,
            daily_plan_age_hours=state.daily_plan_age_hours,
            valid_daily_plan=(
                state.current_plan is not None
                and state.daily_plan_age_hours < state.current_plan.duration_hours
                and state.daily_plan_age_hours < len(state.current_plan.planned_modes)
            ),
            sat_lat_deg=orbit.latitude_deg,
            sat_lon_deg=orbit.longitude_deg,
            sat_alt_km=orbit.altitude_km,
            orbit_phase_deg=orbit.phase_deg,
            effective_orbit_altitude_km=orbit.altitude_km,
            effective_orbit_phase_deg=orbit.phase_deg,
            fixed_orbit_sat_lat_deg=fixed_orbit.latitude_deg,
            fixed_orbit_sat_lon_deg=fixed_orbit.longitude_deg,
            fixed_orbit_alt_km=fixed_orbit.altitude_km,
            fixed_orbit_phase_deg=fixed_orbit.phase_deg,
            data_lost_gb=state.data_lost_gb,
            overflow_hours=state.overflow_hours,
            effective_storage_capacity_gb=self.effective_storage_capacity_gb(state),
            pointing_efficiency=self.pointing_efficiency(state),
            effective_downlink_rate_gb_per_min=self.effective_downlink_rate_gb_per_min(state),
            effective_imaging_rate_gb_per_hour=self.effective_imaging_rate_gb_per_hour(state),
            effective_energy_margin=self.effective_energy_margin(state),
            minimum_soc=state.minimum_soc,
            minimum_health=state.minimum_health,
        )

    def effective_storage_capacity_gb(self, state: SatelliteState) -> float:
        """Usable storage proxy; storage health linearly scales physical capacity."""
        return self._clamp(
            self.config.storage_capacity_gb * state.storage_health,
            self.config.minimum_percent,
            self.config.storage_capacity_gb,
        )

    def _fuel_percentages(
        self, state: SatelliteState
    ) -> dict[str, float]:
        """Return readable percentages relative to the proxy delta-v budget."""
        budget = self.config.initial_delta_v_budget_m_per_s
        if budget <= self.config.minimum_percent:
            return {
                "fuel_remaining_percent": self.config.minimum_percent,
                "fuel_used_percent": self.config.minimum_percent,
                "stationkeeping_delta_v_cost_percent": (
                    self.config.minimum_percent
                ),
                "debris_avoidance_delta_v_cost_percent": (
                    self.config.minimum_percent
                ),
            }
        scale = self.config.maximum_percent / budget
        return {
            "fuel_remaining_percent": self._clamp(
                state.delta_v_remaining_m_per_s * scale,
                self.config.minimum_percent,
                self.config.maximum_percent,
            ),
            "fuel_used_percent": self._clamp(
                state.delta_v_used_m_per_s * scale,
                self.config.minimum_percent,
                self.config.maximum_percent,
            ),
            "stationkeeping_delta_v_cost_percent": (
                self.config.stationkeeping_delta_v_cost_m_per_s * scale
            ),
            "debris_avoidance_delta_v_cost_percent": (
                self.config.debris_avoidance_delta_v_cost_m_per_s * scale
            ),
        }

    def pointing_efficiency(self, state: SatelliteState) -> float:
        """ADCS-health proxy for imaging and antenna pointing efficiency."""
        # TODO: replace with attitude dynamics, slew, stabilization, and geometry.
        return self._clamp(
            state.adcs_health,
            self.config.minimum_health,
            self.config.maximum_health,
        )

    def effective_downlink_rate_gb_per_min(self, state: SatelliteState) -> float:
        return max(
            self.config.minimum_percent,
            self.config.x_band_downlink_rate_gb_per_min
            * self.scenario.downlink_capacity_multiplier
            * self._clamp(
                state.comms_health,
                self.config.minimum_health,
                self.config.maximum_health,
            )
            * self.pointing_efficiency(state),
        )

    def effective_imaging_rate_gb_per_hour(self, state: SatelliteState) -> float:
        return max(
            self.config.minimum_percent,
            self.config.imaging_rate_gb_per_hour
            * self.scenario.imaging_rate_multiplier
            * self._clamp(
                state.payload_health,
                self.config.minimum_health,
                self.config.maximum_health,
            )
            * self.pointing_efficiency(state),
        )

    def effective_energy_margin(self, state: SatelliteState) -> float:
        """Usable-energy proxy used for safety decisions; raw SOC is unchanged."""
        return self._clamp(
            state.soc * state.battery_health,
            self.config.minimum_percent,
            self.config.maximum_percent,
        )

    def high_load_degradation_multiplier(
        self, state: SatelliteState, mode: Mode
    ) -> float:
        if mode not in (Mode.IMAGING, Mode.DOWNLINK, Mode.MANEUVER):
            return self.config.maximum_health
        # TODO: replace with an orbital heat-balance and component-temperature model.
        thermal_deficit = self.config.maximum_health - self._clamp(
            state.thermal_health,
            self.config.minimum_health,
            self.config.maximum_health,
        )
        return (
            self.config.maximum_health
            + self.config.thermal_high_load_sensitivity * thermal_deficit
        )

    def _enforce_storage_capacity(
        self, state: SatelliteState, increment_hour: bool
    ) -> None:
        usable_capacity = self.effective_storage_capacity_gb(state)
        if state.data_buffer_gb <= usable_capacity:
            return
        lost = state.data_buffer_gb - usable_capacity
        state.data_buffer_gb = usable_capacity
        state.data_lost_gb += lost
        if increment_hour:
            state.overflow_hours += 1

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    @staticmethod
    def _clamp_signed(value: float, maximum_magnitude: float) -> float:
        maximum = abs(maximum_magnitude)
        return max(-maximum, min(maximum, value))
