"""Bounded onboard-autonomy and contingency-plan proxy.

This module implements deterministic, explicitly limited mode selection from
current onboard facts.  It is not flight software, FDIR, onboard AI, or a
validated spacecraft autonomy design.  It never receives future catalog data
or ground-only lifecycle warnings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import ContactInfo, Mode, SatelliteState


AUTONOMY_MODELS = (
    "none",
    "safe_mode_only",
    "contingency_plan",
    "limited_maneuver_authority",
)

AUTONOMY_LOW_ENERGY_MARGIN = 35.0
AUTONOMY_CRITICAL_ENERGY_MARGIN = 10.0
AUTONOMY_THERMAL_PROTECTION_HEALTH = 0.30
# This is only a local contingency diagnostic.  The simulator's authoritative
# no-contact ladder remains daily-plan expiry -> BACKUP -> EMERGENCY_BEACON at
# config.emergency_after_hours (336 hours by default).  The standard 24-hour
# authority envelope normally expires before this diagnostic can become active.
AUTONOMY_NO_CONTACT_TIMEOUT_HOURS = 48


class AutonomyTrigger(str, Enum):
    NONE = "none"
    LOW_EFFECTIVE_ENERGY = "low_effective_energy"
    CRITICAL_ENERGY = "critical_energy"
    STALE_PLAN = "stale_plan"
    NO_CONTACT_TIMEOUT = "no_contact_timeout"
    HIGH_STORAGE_PRESSURE = "high_storage_pressure"
    THERMAL_PROTECTION = "thermal_protection"
    PAYLOAD_UNAVAILABLE = "payload_unavailable"
    UPLOADED_DEBRIS_RESPONSE = "uploaded_debris_response"
    CRITICAL_ORBIT_DRIFT = "critical_orbit_drift"


class AutonomyAuthority(str, Enum):
    NONE = "none"
    SAFE_MODE = "safe_mode"
    MODE_SELECTION = "mode_selection"
    LIMITED_MANEUVER = "limited_maneuver"


@dataclass(frozen=True)
class AutonomyDecision:
    """One auditable current-hour autonomy decision."""

    autonomy_model: str
    active: bool
    trigger: str | None
    authority: str | None
    selected_mode: str | None
    reason: str | None
    pre_authorized: bool | None
    ground_contact_required: bool | None
    used_uploaded_response: bool | None
    notes: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OnboardContingencyPlan:
    """Small pre-authorized authority envelope uploaded during command contact."""

    uploaded_hour: int
    expires_hour: int
    authority: str
    allow_safe_mode: bool
    allow_storage_protection: bool
    allow_thermal_protection: bool
    allow_limited_maneuver: bool
    source_policy: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def is_active(self, hour: int) -> bool:
        return self.uploaded_hour <= hour < self.expires_hour


def inactive_autonomy_decision(autonomy_model: str) -> AutonomyDecision:
    """Return the blank diagnostics required when autonomy takes no action."""
    return AutonomyDecision(
        autonomy_model=autonomy_model,
        active=False,
        trigger=None,
        authority=None,
        selected_mode=None,
        reason=None,
        pre_authorized=None,
        ground_contact_required=None,
        used_uploaded_response=None,
        notes=None,
    )


def _active_decision(
    *,
    autonomy_model: str,
    trigger: AutonomyTrigger,
    authority: AutonomyAuthority,
    selected_mode: Mode,
    reason: str,
    used_uploaded_response: bool = False,
) -> AutonomyDecision:
    return AutonomyDecision(
        autonomy_model=autonomy_model,
        active=True,
        trigger=trigger.value,
        authority=authority.value,
        selected_mode=selected_mode.value,
        reason=reason,
        pre_authorized=True,
        ground_contact_required=False,
        used_uploaded_response=used_uploaded_response,
        notes=(
            "Bounded current-state proxy; not flight software, FDIR, or "
            "onboard AI."
        ),
    )


def decide_autonomy(
    *,
    autonomy_model: str,
    state: SatelliteState,
    contact: ContactInfo,
    proposed_mode: Mode,
    contingency_plan: OnboardContingencyPlan | None,
    hour: int,
    effective_energy_margin: float,
    effective_storage_capacity_gb: float,
    stored_daily_plan_valid: bool,
    uploaded_debris_response_eligible: bool,
    maneuver_model: str,
    maneuver_resources_available: bool,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> AutonomyDecision:
    """Select a bounded action using only current onboard inputs.

    The caller deliberately supplies only already-uploaded debris eligibility;
    ground-only or scheduled lifecycle information is not an input.  Existing
    maneuver and debris resolvers remain responsible for final execution.
    """

    if autonomy_model not in AUTONOMY_MODELS:
        choices = ", ".join(AUTONOMY_MODELS)
        raise ValueError(f"autonomy_model must be one of: {choices}")
    inactive = inactive_autonomy_decision(autonomy_model)
    if autonomy_model == "none" or state.emergency_beacon_mode:
        return inactive

    if effective_energy_margin <= AUTONOMY_CRITICAL_ENERGY_MARGIN:
        return _active_decision(
            autonomy_model=autonomy_model,
            trigger=AutonomyTrigger.CRITICAL_ENERGY,
            authority=AutonomyAuthority.SAFE_MODE,
            selected_mode=Mode.SAFE,
            reason="Real onboard effective energy reached the autonomy critical threshold.",
        )
    if effective_energy_margin < AUTONOMY_LOW_ENERGY_MARGIN:
        return _active_decision(
            autonomy_model=autonomy_model,
            trigger=AutonomyTrigger.LOW_EFFECTIVE_ENERGY,
            authority=AutonomyAuthority.SAFE_MODE,
            selected_mode=Mode.SAFE,
            reason="Real onboard effective energy is below the conservative autonomy reserve.",
        )
    if state.thermal_health < AUTONOMY_THERMAL_PROTECTION_HEALTH:
        return _active_decision(
            autonomy_model=autonomy_model,
            trigger=AutonomyTrigger.THERMAL_PROTECTION,
            authority=AutonomyAuthority.SAFE_MODE,
            selected_mode=Mode.SAFE,
            reason="Real onboard thermal health crossed the protective autonomy threshold.",
        )
    if autonomy_model == "safe_mode_only":
        return inactive

    plan_active = (
        contingency_plan is not None and contingency_plan.is_active(hour)
    )
    if autonomy_model == "limited_maneuver_authority":
        can_maneuver = (
            maneuver_model == "stationkeeping_proxy"
            and maneuver_resources_available
        )
        if uploaded_debris_response_eligible and can_maneuver:
            return _active_decision(
                autonomy_model=autonomy_model,
                trigger=AutonomyTrigger.UPLOADED_DEBRIS_RESPONSE,
                authority=AutonomyAuthority.LIMITED_MANEUVER,
                selected_mode=Mode.MANEUVER,
                reason="An already uploaded debris response authorizes the current TCA maneuver.",
                used_uploaded_response=True,
            )
        # BACKUP remains the established post-plan-expiry fallback.  Apart
        # from real-state protection above and an already-uploaded TCA response,
        # contingency autonomy must not replace it with another mode.
        if state.backup_mode:
            return inactive
        if (
            plan_active
            and contingency_plan is not None
            and contingency_plan.allow_limited_maneuver
            and state.orbit_drift_critical
            and can_maneuver
        ):
            return _active_decision(
                autonomy_model=autonomy_model,
                trigger=AutonomyTrigger.CRITICAL_ORBIT_DRIFT,
                authority=AutonomyAuthority.LIMITED_MANEUVER,
                selected_mode=Mode.MANEUVER,
                reason="The uploaded authority envelope permits one current-state critical-drift maneuver.",
            )

    if state.backup_mode:
        return inactive

    if not plan_active or contingency_plan is None:
        return inactive
    if not stored_daily_plan_valid:
        return _active_decision(
            autonomy_model=autonomy_model,
            trigger=AutonomyTrigger.STALE_PLAN,
            authority=AutonomyAuthority.MODE_SELECTION,
            selected_mode=Mode.STANDBY,
            reason="The ground daily plan is stale; the active contingency plan selects standby.",
        )
    if state.payload_health < config.payload_failure_health:
        return _active_decision(
            autonomy_model=autonomy_model,
            trigger=AutonomyTrigger.PAYLOAD_UNAVAILABLE,
            authority=AutonomyAuthority.MODE_SELECTION,
            selected_mode=Mode.STANDBY,
            reason="The payload is unavailable in real onboard state.",
        )

    storage_fraction = (
        state.data_buffer_gb / effective_storage_capacity_gb
        if effective_storage_capacity_gb > config.minimum_percent
        else config.maximum_health
    )
    if storage_fraction >= config.storage_stress_fraction:
        selected = (
            Mode.DOWNLINK
            if contact.data_contact_min > config.minimum_percent
            and state.data_buffer_gb > config.minimum_percent
            else Mode.STANDBY
        )
        return _active_decision(
            autonomy_model=autonomy_model,
            trigger=AutonomyTrigger.HIGH_STORAGE_PRESSURE,
            authority=AutonomyAuthority.MODE_SELECTION,
            selected_mode=selected,
            reason=(
                "Current data contact permits storage-protection downlink."
                if selected == Mode.DOWNLINK
                else "Storage is pressured without a current data contact; standby prevents additional payload work."
            ),
        )
    if state.hours_since_contact >= AUTONOMY_NO_CONTACT_TIMEOUT_HOURS:
        return _active_decision(
            autonomy_model=autonomy_model,
            trigger=AutonomyTrigger.NO_CONTACT_TIMEOUT,
            authority=AutonomyAuthority.MODE_SELECTION,
            selected_mode=Mode.STANDBY,
            reason=(
                "The local contingency no-contact diagnostic exceeded its "
                "threshold; this is not the 14-day emergency mechanism."
            ),
        )
    return inactive


__all__ = [
    "AUTONOMY_CRITICAL_ENERGY_MARGIN",
    "AUTONOMY_LOW_ENERGY_MARGIN",
    "AUTONOMY_MODELS",
    "AUTONOMY_NO_CONTACT_TIMEOUT_HOURS",
    "AUTONOMY_THERMAL_PROTECTION_HEALTH",
    "AutonomyAuthority",
    "AutonomyDecision",
    "AutonomyTrigger",
    "OnboardContingencyPlan",
    "decide_autonomy",
    "inactive_autonomy_decision",
]
