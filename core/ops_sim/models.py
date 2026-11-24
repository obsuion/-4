"""State and value objects for the Version 1 simulator."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .config import DEFAULT_CONFIG, SimulationConfig


class Mode(str, Enum):
    SAFE = "SAFE"
    STANDBY = "STANDBY"
    IMAGING = "IMAGING"
    DOWNLINK = "DOWNLINK"
    MANEUVER = "MANEUVER"
    BACKUP = "BACKUP"
    EMERGENCY_BEACON = "EMERGENCY_BEACON"


class LossReason(str, Enum):
    CRITICAL_POWER = "critical_power"
    EPS_FAILURE = "eps_failure"
    COMMUNICATION_FAILURE = "communication_failure"
    STORAGE_FAILURE = "storage_failure"
    OBC_FAILURE = "obc_failure"
    ADCS_FAILURE = "adcs_failure"
    THERMAL_FAILURE = "thermal_failure"


HEALTH_FIELDS = frozenset({
    "solar_health",
    "battery_health",
    "payload_health",
    "storage_health",
    "comms_health",
    "adcs_health",
    "obc_health",
    "thermal_health",
    "propulsion_health",
})


@dataclass
class ContactInfo:
    cmd_contact_min: float = 0.0
    data_contact_min: float = 0.0


@dataclass
class DailyPlan:
    uploaded_hour: int
    duration_hours: int
    planned_modes: tuple[Mode, ...] = ()
    energy_risk_by_hour: tuple[bool | None, ...] = ()
    storage_risk_by_hour: tuple[bool | None, ...] = ()
    expected_data_contact_min_by_hour: tuple[float, ...] = ()
    expected_cmd_contact_min_by_hour: tuple[float, ...] = ()
    policy_name: str | None = None
    based_on_telemetry_hour: int | None = None
    based_on_telemetry_age_hours: int | None = None


@dataclass
class SatelliteState:
    soc: float = DEFAULT_CONFIG.initial_soc
    data_buffer_gb: float = 0.0
    solar_health: float = 1.0
    battery_health: float = 1.0
    payload_health: float = 1.0
    storage_health: float = 1.0
    comms_health: float = 1.0
    adcs_health: float = 1.0
    obc_health: float = 1.0
    thermal_health: float = 1.0
    propulsion_health: float = 1.0
    delta_v_remaining_m_per_s: float = (
        DEFAULT_CONFIG.initial_delta_v_budget_m_per_s
    )
    delta_v_used_m_per_s: float = 0.0
    maneuver_count: int = 0
    maneuver_skipped_count: int = 0
    orbit_drift_proxy_km: float = 0.0
    orbit_altitude_offset_km: float = 0.0
    orbit_phase_error_deg: float = 0.0
    orbit_groundtrack_error_km: float = 0.0
    orbit_geometry_degraded: bool = False
    orbit_correction_count: int = 0
    orbit_correction_skipped_count: int = 0
    _orbit_proxy_mapped_drift_km: float = field(
        default=0.0, repr=False, compare=False
    )
    orbit_drift_warning: bool = False
    orbit_drift_critical: bool = False
    orbit_drift_damage_events: int = 0
    orbit_drift_damage_accumulated: float = 0.0
    debris_conjunction_active: bool = False
    debris_avoidance_required_this_hour: bool = False
    debris_avoidance_executed_count: int = 0
    debris_avoidance_skipped_count: int = 0
    debris_damage_events: int = 0
    debris_damage_accumulated: float = 0.0
    last_maneuver_hour: int | None = None
    maneuver_due: bool = False
    mode: Mode = Mode.STANDBY
    current_plan: Optional[DailyPlan] = None
    hours_since_contact: int = 0
    daily_plan_age_hours: int = 0
    backup_mode: bool = False
    emergency_beacon_mode: bool = False
    critical_soc_hours: int = 0
    alive: bool = True
    loss_reason: Optional[LossReason] = None
    total_data_generated_gb: float = 0.0
    total_data_downlinked_gb: float = 0.0
    total_images_taken: int = 0
    data_lost_gb: float = 0.0
    overflow_hours: int = 0
    payload_unavailable_hours: int = 0
    minimum_soc: float = DEFAULT_CONFIG.maximum_percent
    minimum_health: float = DEFAULT_CONFIG.maximum_health
    hours_completed: int = 0
    safe_mode_hours: int = 0
    mode_hours: dict[Mode, int] = field(
        default_factory=lambda: {mode: 0 for mode in Mode}
    )

    def eps_health(self, config: SimulationConfig = DEFAULT_CONFIG) -> float:
        return (
            config.eps_battery_weight * self.battery_health
            + config.eps_solar_weight * self.solar_health
        )

    def average_placeholder_health(self) -> float:
        return (
            self.adcs_health
            + self.obc_health
            + self.thermal_health
            + self.propulsion_health
        ) / DEFAULT_CONFIG.placeholder_subsystem_count

    def total_health(self, config: SimulationConfig = DEFAULT_CONFIG) -> float:
        placeholders = (
            self.adcs_health
            + self.obc_health
            + self.thermal_health
            + self.propulsion_health
        ) / config.placeholder_subsystem_count
        return (
            config.total_eps_weight * self.eps_health(config)
            + config.total_comms_weight * self.comms_health
            + config.total_payload_weight * self.payload_health
            + config.total_storage_weight * self.storage_health
            + config.total_placeholder_weight * placeholders
        )
