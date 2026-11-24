"""Transparent decision and risk explanations for the operations proxy.

The scores in this module are bounded diagnostic heuristics, not probabilities,
validated operator reasoning, or flight-software decisions.  They observe the
existing simulator state and constraints without selecting or changing modes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Mapping, Sequence

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import ContactInfo, LossReason, Mode, SatelliteState


RISK_FIELDS: tuple[str, ...] = (
    "power_risk",
    "energy_margin_risk",
    "storage_risk",
    "contact_risk",
    "comms_risk",
    "payload_risk",
    "adcs_risk",
    "thermal_risk",
    "fuel_risk",
    "orbit_drift_risk",
    "debris_risk",
    "telemetry_staleness_risk",
    "backup_or_emergency_risk",
)


def _clamp01(value: float) -> float:
    if not isfinite(value):
        return 1.0
    return max(0.0, min(1.0, value))


def _mode_value(mode: Mode | str | None) -> str | None:
    if isinstance(mode, Mode):
        return mode.value
    return mode


@dataclass(frozen=True)
class RiskSnapshot:
    """Risk scores and supporting state for one decision hour.

    Every ``*_risk`` value follows the convention 0 = low and 1 = critical.
    These values are transparent proxy diagnostics, not event probabilities.
    """

    hour: int
    year: float
    policy: str
    scenario: str
    operator_view: str
    planning_model: str
    maneuver_model: str
    orbit_evolution_model: str
    mode_before: str
    planned_mode: str | None
    selected_mode: str
    executed_mode: str
    main_risk_driver: str
    power_risk: float
    energy_margin_risk: float
    storage_risk: float
    contact_risk: float
    comms_risk: float
    payload_risk: float
    adcs_risk: float
    thermal_risk: float
    fuel_risk: float
    orbit_drift_risk: float
    debris_risk: float
    telemetry_staleness_risk: float
    backup_or_emergency_risk: float
    soc: float
    health: float
    effective_energy_margin: float
    buffer_gb: float
    buffer_fraction: float
    cmd_contact_min: float
    data_contact_min: float
    telemetry_age_hours: int
    hours_since_contact: int
    fuel_remaining_percent: float
    orbit_drift_proxy_km: float

    def risk_scores(self) -> dict[str, float]:
        return {field: getattr(self, field) for field in RISK_FIELDS}

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ModeOptionAssessment:
    """One feasibility and tradeoff estimate for a candidate mode."""

    mode: str
    feasible: bool
    rejection_reason: str | None
    expected_power_effect: str
    expected_data_effect: str
    expected_storage_effect: str
    expected_fuel_effect: str
    risk_penalty: float
    utility_hint: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionExplanation:
    """Auditable explanation emitted after one completed simulator hour."""

    hour: int
    year: float
    policy: str
    scenario: str
    selected_mode: str
    executed_mode: str
    planned_mode: str | None
    main_reason: str
    main_risk_driver: str
    active_constraints: tuple[str, ...]
    rejected_alternatives: tuple[str, ...]
    risk_snapshot: RiskSnapshot
    option_assessments: tuple[ModeOptionAssessment, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "hour": self.hour,
            "year": self.year,
            "policy": self.policy,
            "scenario": self.scenario,
            "selected_mode": self.selected_mode,
            "executed_mode": self.executed_mode,
            "planned_mode": self.planned_mode,
            "main_reason": self.main_reason,
            "main_risk_driver": self.main_risk_driver,
            "active_constraints": "; ".join(self.active_constraints),
            "rejected_alternatives": " | ".join(
                self.rejected_alternatives
            ),
        }

    def option_rows(self) -> list[dict[str, object]]:
        identifiers = {
            "hour": self.hour,
            "year": self.year,
            "policy": self.policy,
            "scenario": self.scenario,
            "selected_mode": self.selected_mode,
            "executed_mode": self.executed_mode,
        }
        return [
            {**identifiers, **assessment.as_dict()}
            for assessment in self.option_assessments
        ]


@dataclass(frozen=True)
class FailureAttribution:
    """End-of-run survival or failure attribution from recent explanations."""

    policy: str
    scenario: str
    survived: bool
    loss_reason: str | None
    loss_hour: int | None
    dominant_pre_failure_risk: str
    last_mode: str | None
    last_planned_mode: str | None
    last_contact_state: str
    last_soc: float
    last_health: float
    last_fuel_remaining_percent: float
    likely_bottleneck: str
    short_explanation: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _main_risk_driver(scores: Mapping[str, float]) -> str:
    if not scores:
        return "none"
    field, value = max(scores.items(), key=lambda item: item[1])
    return field.removesuffix("_risk") if value > 0.0 else "none"


def build_risk_snapshot(
    *,
    hour: int,
    policy: str,
    scenario: str,
    operator_view: str,
    planning_model: str,
    maneuver_model: str,
    orbit_evolution_model: str,
    state: SatelliteState,
    contact: ContactInfo,
    planned_mode: Mode | str | None,
    selected_mode: Mode | str,
    executed_mode: Mode | str,
    telemetry_age_hours: int,
    safe_threshold: float,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> RiskSnapshot:
    """Calculate bounded risk proxies from existing decision inputs only."""

    maximum_percent = max(config.maximum_percent, 1.0)
    soc_fraction = _clamp01(state.soc / maximum_percent)
    energy_margin = max(
        config.minimum_percent,
        min(config.maximum_percent, state.soc * state.battery_health),
    )
    usable_storage = max(
        config.minimum_percent,
        min(
            config.storage_capacity_gb,
            config.storage_capacity_gb * state.storage_health,
        ),
    )
    buffer_fraction = (
        _clamp01(state.data_buffer_gb / usable_storage)
        if usable_storage > config.minimum_percent
        else 1.0
    )
    contact_available = (
        contact.cmd_contact_min > config.minimum_percent
        or contact.data_contact_min > config.minimum_percent
    )
    contact_risk = (
        0.0
        if contact_available
        else max(
            0.25,
            _clamp01(
                state.hours_since_contact
                / max(1, config.emergency_after_hours)
            ),
        )
    )
    maneuver_relevant = maneuver_model == "stationkeeping_proxy"
    budget = config.initial_delta_v_budget_m_per_s
    fuel_remaining_fraction = (
        _clamp01(state.delta_v_remaining_m_per_s / budget)
        if budget > config.minimum_percent
        else 0.0
    )
    fuel_remaining_percent = fuel_remaining_fraction * maximum_percent
    drift_denominator = max(
        config.orbit_drift_critical_threshold_km,
        config.orbit_drift_threshold_km,
        1e-12,
    )
    orbit_risk = (
        _clamp01(state.orbit_drift_proxy_km / drift_denominator)
        if maneuver_relevant
        else 0.0
    )
    telemetry_risk = (
        _clamp01(telemetry_age_hours / max(1, config.plan_duration_hours))
        if operator_view == "delayed_telemetry"
        else 0.0
    )
    backup_risk = (
        1.0
        if state.emergency_beacon_mode
        else 0.75
        if state.backup_mode
        else 0.5
        if operator_view == "delayed_telemetry" and state.current_plan is None
        else 0.0
    )
    debris_risk = (
        1.0
        if state.debris_avoidance_required_this_hour
        else 0.5
        if state.debris_conjunction_active
        else 0.0
    )
    scores = {
        "power_risk": _clamp01(1.0 - soc_fraction),
        "energy_margin_risk": _clamp01(
            1.0 - energy_margin / maximum_percent
        ),
        "storage_risk": buffer_fraction,
        "contact_risk": contact_risk,
        "comms_risk": _clamp01(1.0 - state.comms_health),
        "payload_risk": _clamp01(1.0 - state.payload_health),
        "adcs_risk": _clamp01(1.0 - state.adcs_health),
        "thermal_risk": _clamp01(1.0 - state.thermal_health),
        "fuel_risk": (
            _clamp01(1.0 - fuel_remaining_fraction)
            if maneuver_relevant
            else 0.0
        ),
        "orbit_drift_risk": orbit_risk,
        "debris_risk": debris_risk,
        "telemetry_staleness_risk": telemetry_risk,
        "backup_or_emergency_risk": backup_risk,
    }
    # The threshold is reported through constraints and option feasibility;
    # folding it into this score makes low policy-relative margin visible while
    # retaining the bounded 0..1 convention.
    if safe_threshold > config.minimum_percent and energy_margin < safe_threshold:
        scores["energy_margin_risk"] = max(
            scores["energy_margin_risk"],
            _clamp01(1.0 - energy_margin / safe_threshold),
        )
    return RiskSnapshot(
        hour=hour,
        year=hour / config.hours_per_year,
        policy=policy,
        scenario=scenario,
        operator_view=operator_view,
        planning_model=planning_model,
        maneuver_model=maneuver_model,
        orbit_evolution_model=orbit_evolution_model,
        mode_before=state.mode.value,
        planned_mode=_mode_value(planned_mode),
        selected_mode=_mode_value(selected_mode) or "",
        executed_mode=_mode_value(executed_mode) or "",
        main_risk_driver=_main_risk_driver(scores),
        **scores,
        soc=state.soc,
        health=state.total_health(config),
        effective_energy_margin=energy_margin,
        buffer_gb=state.data_buffer_gb,
        buffer_fraction=buffer_fraction,
        cmd_contact_min=contact.cmd_contact_min,
        data_contact_min=contact.data_contact_min,
        telemetry_age_hours=telemetry_age_hours,
        hours_since_contact=state.hours_since_contact,
        fuel_remaining_percent=fuel_remaining_percent,
        orbit_drift_proxy_km=state.orbit_drift_proxy_km,
    )


def _mode_effects(
    mode: Mode, config: SimulationConfig
) -> tuple[str, str, str, str]:
    power = {
        Mode.SAFE: config.soc_safe_delta,
        Mode.STANDBY: config.soc_standby_delta,
        Mode.IMAGING: config.soc_imaging_delta,
        Mode.DOWNLINK: config.soc_downlink_delta,
        Mode.MANEUVER: config.maneuver_soc_delta,
        Mode.BACKUP: config.soc_backup_delta,
        Mode.EMERGENCY_BEACON: config.soc_emergency_delta,
    }[mode]
    data = {
        Mode.IMAGING: "generates payload data",
        Mode.DOWNLINK: "removes buffered payload data",
        Mode.MANEUVER: "no payload generation or downlink",
    }.get(mode, "no payload generation or downlink")
    storage = {
        Mode.IMAGING: "increases storage use",
        Mode.DOWNLINK: "reduces storage use",
    }.get(mode, "no direct storage change")
    fuel = (
        "consumes configured delta-v when executed"
        if mode == Mode.MANEUVER
        else "no delta-v use"
    )
    return f"SOC delta {power:+.2f} percentage points", data, storage, fuel


def assess_mode_options(
    *,
    state: SatelliteState,
    contact: ContactInfo,
    risk_snapshot: RiskSnapshot,
    maneuver_model: str,
    safe_threshold: float,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> tuple[ModeOptionAssessment, ...]:
    """Assess every current mode using existing physical constraints only."""

    usable_storage = max(
        config.minimum_percent,
        config.storage_capacity_gb * state.storage_health,
    )
    energy_margin = risk_snapshot.effective_energy_margin
    required_delta_v = max(
        config.minimum_delta_v_for_maneuver_m_per_s,
        config.stationkeeping_delta_v_cost_m_per_s,
    )
    assessments: list[ModeOptionAssessment] = []
    for mode in Mode:
        feasible = True
        rejection: str | None = None
        if (
            mode not in (Mode.SAFE, Mode.EMERGENCY_BEACON)
            and energy_margin < safe_threshold
        ):
            feasible = False
            rejection = "low energy margin"
        elif mode == Mode.IMAGING:
            if state.payload_health < config.payload_failure_health:
                feasible = False
                rejection = "payload unavailable"
            elif state.data_buffer_gb >= (
                config.imaging_block_fraction * usable_storage
            ):
                feasible = False
                rejection = "storage buffer near capacity"
        elif mode == Mode.DOWNLINK:
            if contact.data_contact_min <= config.minimum_percent:
                feasible = False
                rejection = "no data contact"
            elif state.data_buffer_gb <= config.minimum_percent:
                feasible = False
                rejection = "no data in buffer"
            elif state.comms_health < config.comms_failure_health:
                feasible = False
                rejection = "communications unavailable"
        elif mode == Mode.MANEUVER:
            required_delta_v = max(
                required_delta_v,
                config.debris_avoidance_delta_v_cost_m_per_s
                if state.debris_avoidance_required_this_hour
                else config.minimum_percent,
            )
            if maneuver_model != "stationkeeping_proxy":
                feasible = False
                rejection = "maneuver model disabled"
            elif state.delta_v_remaining_m_per_s < required_delta_v:
                feasible = False
                rejection = "insufficient fuel"
            elif state.propulsion_health < (
                config.propulsion_maneuver_health_threshold
            ):
                feasible = False
                rejection = "propulsion health below maneuver threshold"
            elif energy_margin + config.maneuver_soc_delta < safe_threshold:
                feasible = False
                rejection = "low energy margin"
        elif mode == Mode.BACKUP and not state.backup_mode:
            feasible = False
            rejection = "backup autonomy not active"
        elif mode == Mode.EMERGENCY_BEACON and not state.emergency_beacon_mode:
            feasible = False
            rejection = "emergency beacon condition not active"

        relevant_risks = {
            Mode.SAFE: (
                risk_snapshot.power_risk,
                risk_snapshot.energy_margin_risk,
            ),
            Mode.STANDBY: (
                risk_snapshot.power_risk,
                risk_snapshot.storage_risk,
            ),
            Mode.IMAGING: (
                risk_snapshot.energy_margin_risk,
                risk_snapshot.storage_risk,
                risk_snapshot.payload_risk,
                risk_snapshot.adcs_risk,
                risk_snapshot.thermal_risk,
            ),
            Mode.DOWNLINK: (
                risk_snapshot.energy_margin_risk,
                risk_snapshot.contact_risk,
                risk_snapshot.comms_risk,
                risk_snapshot.adcs_risk,
            ),
            Mode.MANEUVER: (
                risk_snapshot.energy_margin_risk,
                risk_snapshot.fuel_risk,
                risk_snapshot.orbit_drift_risk,
                risk_snapshot.debris_risk,
            ),
            Mode.BACKUP: (risk_snapshot.backup_or_emergency_risk,),
            Mode.EMERGENCY_BEACON: (
                risk_snapshot.backup_or_emergency_risk,
            ),
        }[mode]
        power, data, storage, fuel = _mode_effects(mode, config)
        utility = {
            Mode.SAFE: "protects energy margin and supports recovery",
            Mode.STANDBY: "preserves resources between activities",
            Mode.IMAGING: "acquires payload data when resources permit",
            Mode.DOWNLINK: "uses a data contact to relieve the buffer",
            Mode.MANEUVER: "services drift or an active avoidance need",
            Mode.BACKUP: "provides fallback behavior without a valid plan",
            Mode.EMERGENCY_BEACON: "prioritizes contact recovery and survival",
        }[mode]
        assessments.append(ModeOptionAssessment(
            mode=mode.value,
            feasible=feasible,
            rejection_reason=rejection,
            expected_power_effect=power,
            expected_data_effect=data,
            expected_storage_effect=storage,
            expected_fuel_effect=fuel,
            risk_penalty=_clamp01(max(relevant_risks, default=0.0)),
            utility_hint=utility,
        ))
    return tuple(assessments)


def _active_constraints(
    state: SatelliteState,
    contact: ContactInfo,
    risk: RiskSnapshot,
    safe_threshold: float,
    maneuver_model: str,
    config: SimulationConfig,
) -> tuple[str, ...]:
    constraints: list[str] = []
    if risk.effective_energy_margin < safe_threshold:
        constraints.append("low_effective_energy_margin")
    if contact.data_contact_min <= config.minimum_percent:
        constraints.append("no_data_contact")
    if state.data_buffer_gb <= config.minimum_percent:
        constraints.append("no_buffered_data")
    if risk.storage_risk >= config.imaging_block_fraction:
        constraints.append("storage_near_capacity")
    if state.payload_health < config.payload_failure_health:
        constraints.append("payload_unavailable")
    if maneuver_model == "none":
        constraints.append("maneuver_model_disabled")
    elif state.delta_v_remaining_m_per_s < max(
        config.minimum_delta_v_for_maneuver_m_per_s,
        config.stationkeeping_delta_v_cost_m_per_s,
    ):
        constraints.append("insufficient_fuel_for_stationkeeping")
    if state.debris_avoidance_required_this_hour:
        constraints.append("debris_avoidance_required")
    if state.maneuver_due:
        constraints.append("stationkeeping_maneuver_due")
    if state.backup_mode:
        constraints.append("backup_mode_active")
    if state.emergency_beacon_mode:
        constraints.append("emergency_beacon_active")
    if risk.telemetry_staleness_risk > 0.0:
        constraints.append("stale_telemetry")
    return tuple(constraints)


def build_decision_explanation(
    *,
    hour: int,
    policy: str,
    scenario: str,
    operator_view: str,
    planning_model: str,
    maneuver_model: str,
    orbit_evolution_model: str,
    state: SatelliteState,
    contact: ContactInfo,
    telemetry_age_hours: int,
    planned_mode: Mode | None,
    selected_mode: Mode,
    executed_mode: Mode,
    safe_threshold: float,
    safe_override: bool = False,
    payload_unavailable: bool = False,
    maneuver_intended: bool = False,
    maneuver_executed: bool = False,
    maneuver_skipped: bool = False,
    debris_executed: bool = False,
    debris_skipped: bool = False,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> DecisionExplanation:
    """Build an explanation from an already-resolved simulator decision."""

    risk = build_risk_snapshot(
        hour=hour,
        policy=policy,
        scenario=scenario,
        operator_view=operator_view,
        planning_model=planning_model,
        maneuver_model=maneuver_model,
        orbit_evolution_model=orbit_evolution_model,
        state=state,
        contact=contact,
        planned_mode=planned_mode,
        selected_mode=selected_mode,
        executed_mode=executed_mode,
        telemetry_age_hours=telemetry_age_hours,
        safe_threshold=safe_threshold,
        config=config,
    )
    assessments = assess_mode_options(
        state=state,
        contact=contact,
        risk_snapshot=risk,
        maneuver_model=maneuver_model,
        safe_threshold=safe_threshold,
        config=config,
    )
    if state.emergency_beacon_mode or executed_mode == Mode.EMERGENCY_BEACON:
        reason = "emergency_beacon"
    elif state.debris_avoidance_required_this_hour or debris_executed or debris_skipped:
        reason = "debris_avoidance_required"
    elif safe_override:
        reason = "critical_power_override"
    elif executed_mode == Mode.BACKUP:
        reason = "backup_plan_expired"
    elif payload_unavailable:
        reason = "payload_unavailable"
    elif (
        executed_mode == Mode.MANEUVER
        or maneuver_intended
        or maneuver_executed
        or maneuver_skipped
    ):
        reason = "maneuver_due"
    elif (
        executed_mode in (Mode.SAFE, Mode.STANDBY, Mode.DOWNLINK)
        and risk.storage_risk >= 0.90
    ):
        reason = "storage_pressure"
    elif (
        operator_view == "delayed_telemetry"
        and planned_mode is not None
        and selected_mode == planned_mode
        and executed_mode == selected_mode
    ):
        reason = "delayed_telemetry_plan"
    elif executed_mode == Mode.DOWNLINK:
        reason = (
            "storage_pressure"
            if risk.storage_risk >= 0.75
            else "downlink_opportunity"
        )
    elif executed_mode == Mode.IMAGING:
        reason = "imaging_opportunity"
    elif (
        executed_mode == Mode.STANDBY
        and contact.data_contact_min <= config.minimum_percent
        and state.data_buffer_gb > config.minimum_percent
    ):
        reason = "no_contact"
    elif executed_mode in (Mode.SAFE, Mode.STANDBY) and (
        risk.power_risk >= 0.5 or risk.energy_margin_risk >= 0.5
    ):
        reason = "conservative_energy_preservation"
    else:
        reason = "policy_selection"

    constraints = _active_constraints(
        state, contact, risk, safe_threshold, maneuver_model, config
    )
    rejected: list[str] = []
    for assessment in assessments:
        if assessment.mode == executed_mode.value:
            continue
        explanation = assessment.rejection_reason or (
            f"feasible but not selected; {executed_mode.value} had current priority"
        )
        rejected.append(f"{assessment.mode} rejected: {explanation}")
    return DecisionExplanation(
        hour=hour,
        year=hour / config.hours_per_year,
        policy=policy,
        scenario=scenario,
        selected_mode=selected_mode.value,
        executed_mode=executed_mode.value,
        planned_mode=_mode_value(planned_mode),
        main_reason=reason,
        main_risk_driver=risk.main_risk_driver,
        active_constraints=constraints,
        rejected_alternatives=tuple(rejected),
        risk_snapshot=risk,
        option_assessments=assessments,
    )


_LOSS_BOTTLENECKS: dict[LossReason, str] = {
    LossReason.CRITICAL_POWER: "power",
    LossReason.EPS_FAILURE: "eps",
    LossReason.COMMUNICATION_FAILURE: "comms",
    LossReason.STORAGE_FAILURE: "storage",
    LossReason.OBC_FAILURE: "obc",
    LossReason.ADCS_FAILURE: "adcs",
    LossReason.THERMAL_FAILURE: "thermal",
}

_RISK_BOTTLENECKS = {
    "power": "power",
    "energy_margin": "power",
    "storage": "storage",
    "contact": "comms",
    "comms": "comms",
    "payload": "payload",
    "adcs": "adcs",
    "thermal": "thermal",
    "fuel": "fuel",
    "orbit_drift": "orbit_drift",
    "debris": "debris",
    "telemetry_staleness": "comms",
    "backup_or_emergency": "comms",
}


def _contact_state(snapshot: RiskSnapshot | None) -> str:
    if snapshot is None:
        return "unknown"
    command = snapshot.cmd_contact_min > 0.0
    data = snapshot.data_contact_min > 0.0
    if command and data:
        return "command_and_data"
    if command:
        return "command_only"
    if data:
        return "data_only"
    return "no_contact"


def build_failure_attribution(
    result,
    explanations: Sequence[DecisionExplanation],
    config: SimulationConfig = DEFAULT_CONFIG,
) -> FailureAttribution:
    """Attribute a completed result using only its recent explanation trace."""

    recent = list(explanations[-24:])
    last = explanations[-1] if explanations else None
    loss_reason = result.state.loss_reason
    if loss_reason is not None:
        pre_failure = list(explanations[-6:])
        maxima = {
            field: (
                max(getattr(item.risk_snapshot, field) for item in pre_failure)
                if pre_failure
                else 0.0
            )
            for field in RISK_FIELDS
        }
        dominant = _main_risk_driver(maxima)
        bottleneck = _LOSS_BOTTLENECKS.get(loss_reason, "unknown")
        short = (
            f"Mission loss at hour {last.hour if last else result.state.hours_completed - 1} "
            f"was recorded as {loss_reason.value}; recent diagnostics were "
            f"dominated by {dominant} risk."
        )
    else:
        drivers = [
            item.main_risk_driver
            for item in recent
            if item.main_risk_driver != "none"
        ]
        if drivers:
            counts = Counter(drivers)
            dominant = max(
                counts,
                key=lambda driver: (
                    counts[driver],
                    max(
                        getattr(item.risk_snapshot, f"{driver}_risk", 0.0)
                        for item in recent
                    ),
                    driver,
                ),
            )
        else:
            dominant = "none"
        bottleneck = _RISK_BOTTLENECKS.get(dominant, "unknown")
        short = (
            "Mission survived the requested horizon; the most frequent "
            f"final-window diagnostic was {dominant} risk."
        )

    if last is not None:
        snapshot = last.risk_snapshot
        last_mode = result.state.mode.value
        last_planned_mode = last.planned_mode
        last_soc = result.state.soc
        last_health = result.state.total_health(config)
        last_fuel = result.fuel_remaining_percent
        loss_hour = last.hour if loss_reason is not None else None
    else:
        snapshot = None
        last_mode = result.state.mode.value if result.state.mode else None
        last_planned_mode = None
        last_soc = result.state.soc
        last_health = result.state.total_health(config)
        budget = config.initial_delta_v_budget_m_per_s
        last_fuel = (
            _clamp01(result.state.delta_v_remaining_m_per_s / budget) * 100.0
            if budget > 0.0
            else 0.0
        )
        loss_hour = (
            result.state.hours_completed - 1
            if loss_reason is not None and result.state.hours_completed
            else None
        )
    return FailureAttribution(
        policy=result.policy_name,
        scenario=result.scenario_name,
        survived=result.state.alive,
        loss_reason=loss_reason.value if loss_reason is not None else None,
        loss_hour=loss_hour,
        dominant_pre_failure_risk=dominant,
        last_mode=last_mode,
        last_planned_mode=last_planned_mode,
        last_contact_state=_contact_state(snapshot),
        last_soc=last_soc,
        last_health=last_health,
        last_fuel_remaining_percent=last_fuel,
        likely_bottleneck=bottleneck,
        short_explanation=short,
    )


__all__ = [
    "DecisionExplanation",
    "FailureAttribution",
    "ModeOptionAssessment",
    "RISK_FIELDS",
    "RiskSnapshot",
    "assess_mode_options",
    "build_decision_explanation",
    "build_failure_attribution",
    "build_risk_snapshot",
]
