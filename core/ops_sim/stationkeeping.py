"""Bounded drift-aware stationkeeping assessment and diagnostics.

The helper in this module is read-only.  It recommends or defers use of the
existing stationkeeping maneuver path from current or defensively projected
state; it does not implement orbit dynamics, maneuver execution, or event
forecasting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import Mode, SatelliteState


STATIONKEEPING_PLANNING_MODELS = ("legacy", "drift_aware")


class StationkeepingRiskClass(str, Enum):
    NONE = "none"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"


class StationkeepingAction(str, Enum):
    NONE = "none"
    DEFER = "defer"
    STATIONKEEPING_MANEUVER = "stationkeeping_maneuver"


@dataclass(frozen=True)
class StationkeepingAssessment:
    """One auditable stationkeeping recommendation from onboard state."""

    planning_model: str
    drift_risk_class: str
    recommended: bool
    feasible: bool
    selected: bool
    priority: int
    action: str
    reason: str
    deferred_reason: str | None
    drift_km: float
    warning_threshold_km: float
    critical_threshold_km: float
    delta_v_available: bool
    energy_available: bool
    propulsion_available: bool
    geometry_degraded: bool
    blocked_by_priority: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_stationkeeping(
    *,
    state: SatelliteState,
    proposed_mode: Mode,
    maneuver_model: str,
    orbit_evolution_model: str,
    stationkeeping_planning_model: str,
    delta_v_available: bool,
    energy_available: bool,
    propulsion_available: bool,
    emergency_beacon_active: bool,
    critical_energy_safe_priority: bool,
    debris_avoidance_priority: bool,
    projected_critical_within_plan: bool = False,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> StationkeepingAssessment:
    """Assess stationkeeping without mutating state or inspecting events."""

    if stationkeeping_planning_model not in STATIONKEEPING_PLANNING_MODELS:
        choices = ", ".join(STATIONKEEPING_PLANNING_MODELS)
        raise ValueError(
            "stationkeeping_planning_model must be one of: " + choices
        )

    drift_km = max(config.minimum_percent, state.orbit_drift_proxy_km)
    critical = (
        state.orbit_drift_critical
        or drift_km >= config.orbit_drift_critical_threshold_km
    )
    warning = (
        state.orbit_drift_warning
        or drift_km >= config.orbit_drift_warning_threshold_km
        or state.orbit_geometry_degraded
        or projected_critical_within_plan
    )
    if critical:
        risk_class = StationkeepingRiskClass.CRITICAL
    elif warning:
        risk_class = StationkeepingRiskClass.WARNING
    elif drift_km > config.minimum_percent:
        risk_class = StationkeepingRiskClass.WATCH
    else:
        risk_class = StationkeepingRiskClass.NONE

    recommended = risk_class in (
        StationkeepingRiskClass.WARNING,
        StationkeepingRiskClass.CRITICAL,
    )
    model_enabled = (
        stationkeeping_planning_model == "drift_aware"
        and maneuver_model == "stationkeeping_proxy"
        and orbit_evolution_model == "drift_proxy"
    )
    feasible = (
        model_enabled
        and delta_v_available
        and energy_available
        and propulsion_available
    )

    deferred_reason: str | None = None
    blocked_by_priority = False
    if recommended:
        if stationkeeping_planning_model == "legacy":
            deferred_reason = "legacy_planning"
        elif maneuver_model != "stationkeeping_proxy":
            deferred_reason = "maneuver_model_disabled"
        elif orbit_evolution_model != "drift_proxy":
            deferred_reason = "orbit_evolution_fixed"
        elif emergency_beacon_active:
            deferred_reason = "emergency_beacon_priority"
            blocked_by_priority = True
        elif critical_energy_safe_priority:
            deferred_reason = "critical_energy_safe_priority"
            blocked_by_priority = True
        elif debris_avoidance_priority:
            deferred_reason = "debris_avoidance_priority"
            blocked_by_priority = True
        elif not delta_v_available:
            deferred_reason = "insufficient_delta_v"
        elif not energy_available:
            deferred_reason = "insufficient_energy"
        elif not propulsion_available:
            deferred_reason = "propulsion_health_below_threshold"

    priority_clear = not (
        emergency_beacon_active
        or critical_energy_safe_priority
        or debris_avoidance_priority
    )
    selected = (
        recommended
        and feasible
        and priority_clear
        and (
            proposed_mode == Mode.MANEUVER
            or risk_class == StationkeepingRiskClass.CRITICAL
        )
    )
    if recommended and not selected and deferred_reason is None:
        deferred_reason = "not_selected_by_current_plan"

    if selected:
        action = StationkeepingAction.STATIONKEEPING_MANEUVER
        reason = (
            "Critical drift requires current-hour stationkeeping."
            if risk_class == StationkeepingRiskClass.CRITICAL
            else "The drift-aware plan selected feasible stationkeeping."
        )
    elif recommended:
        action = StationkeepingAction.DEFER
        reason = (
            "Stationkeeping is recommended but deferred: "
            f"{deferred_reason}."
        )
    else:
        action = StationkeepingAction.NONE
        reason = "Current drift remains below the stationkeeping warning level."

    return StationkeepingAssessment(
        planning_model=stationkeeping_planning_model,
        drift_risk_class=risk_class.value,
        recommended=recommended,
        feasible=feasible,
        selected=selected,
        priority=5 if recommended else 0,
        action=action.value,
        reason=reason,
        deferred_reason=deferred_reason,
        drift_km=drift_km,
        warning_threshold_km=config.orbit_drift_warning_threshold_km,
        critical_threshold_km=config.orbit_drift_critical_threshold_km,
        delta_v_available=delta_v_available,
        energy_available=energy_available,
        propulsion_available=propulsion_available,
        geometry_degraded=state.orbit_geometry_degraded,
        blocked_by_priority=blocked_by_priority,
    )


__all__ = [
    "STATIONKEEPING_PLANNING_MODELS",
    "StationkeepingAction",
    "StationkeepingAssessment",
    "StationkeepingRiskClass",
    "assess_stationkeeping",
]
