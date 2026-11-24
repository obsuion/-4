"""Deterministic V3.6B bounded thermal/load stress proxy.

This is an auditable stress heuristic, not a temperature, heat-transfer, or
thermal-balance model. Assessments are read-only; the simulator applies the
reported bounded health decrement separately.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import Mode
from .power import PowerAssessment


THERMAL_MODELS = ("legacy", "load_stress_proxy")


@dataclass(frozen=True)
class ThermalAssessment:
    thermal_model: str
    thermal_load_proxy_this_hour: float | None
    thermal_hot_stress_this_hour: float | None
    thermal_cold_stress_this_hour: float | None
    thermal_stress_this_hour: float | None
    thermal_degradation_this_hour: float
    thermal_reason_this_hour: str | None


def _mode_load_w(mode: Mode, config: SimulationConfig) -> float:
    return {
        Mode.SAFE: config.safe_power_load_proxy_w,
        Mode.STANDBY: config.standby_power_load_proxy_w,
        Mode.IMAGING: config.imaging_power_load_proxy_w,
        Mode.DOWNLINK: config.downlink_power_load_proxy_w,
        Mode.MANEUVER: config.maneuver_power_load_proxy_w,
        Mode.BACKUP: config.backup_power_load_proxy_w,
        Mode.EMERGENCY_BEACON: config.emergency_power_load_proxy_w,
    }[mode]


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def assess_thermal_for_hour(
    *,
    thermal_model: str,
    mode: Mode,
    power_assessment: PowerAssessment,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> ThermalAssessment:
    """Return one bounded thermal assessment without mutating state."""
    if thermal_model not in THERMAL_MODELS:
        choices = ", ".join(THERMAL_MODELS)
        raise ValueError(f"thermal_model must be one of: {choices}")
    if thermal_model == "legacy":
        return ThermalAssessment(
            thermal_model, None, None, None, None, 0.0, None
        )

    load_w = (
        power_assessment.power_load_proxy_w
        if power_assessment.power_load_proxy_w is not None
        else _mode_load_w(mode, config)
    )
    max_load_w = max(
        config.safe_power_load_proxy_w,
        config.standby_power_load_proxy_w,
        config.imaging_power_load_proxy_w,
        config.downlink_power_load_proxy_w,
        config.maneuver_power_load_proxy_w,
        config.backup_power_load_proxy_w,
        config.emergency_power_load_proxy_w,
        1.0,
    )
    load_proxy = _clamp(load_w / max_load_w)
    high_load_modes = {Mode.IMAGING, Mode.DOWNLINK, Mode.MANEUVER}
    low_load_modes = {
        Mode.SAFE,
        Mode.STANDBY,
        Mode.BACKUP,
        Mode.EMERGENCY_BEACON,
    }
    hot_denominator = max(
        1.0, max_load_w - config.thermal_model_hot_load_threshold_w
    )
    high_load_stress = (
        _clamp(
            (load_w - config.thermal_model_hot_load_threshold_w)
            / hot_denominator
        )
        if mode in high_load_modes
        else 0.0
    )
    hot_stress = (
        high_load_stress
        if power_assessment.sunlight_factor is not None
        and power_assessment.sunlight_factor > 0.0
        and mode in high_load_modes
        else 0.0
    )
    if (
        power_assessment.net_power_proxy_w is not None
        and power_assessment.net_power_proxy_w < 0.0
        and mode in high_load_modes
    ):
        high_load_stress = _clamp(
            high_load_stress
            + abs(power_assessment.net_power_proxy_w) / max_load_w
        )
    cold_denominator = max(1.0, config.thermal_model_cold_load_threshold_w)
    cold_stress = (
        _clamp(
            (config.thermal_model_cold_load_threshold_w - load_w)
            / cold_denominator
        )
        if power_assessment.eclipse is True and mode in low_load_modes
        else 0.0
    )
    stress = _clamp(max(hot_stress, cold_stress, high_load_stress))
    degradation = min(
        config.thermal_stress_max_per_hour,
        hot_stress * config.thermal_hot_stress_degradation_per_hour
        + cold_stress * config.thermal_cold_stress_degradation_per_hour
        + high_load_stress
        * config.thermal_high_load_stress_degradation_per_hour,
    )
    reasons = []
    if hot_stress > 0.0:
        reasons.append("sunlit_high_load")
    if cold_stress > 0.0:
        reasons.append("eclipse_low_load")
    if high_load_stress > 0.0:
        reasons.append("high_mode_load")
    return ThermalAssessment(
        thermal_model=thermal_model,
        thermal_load_proxy_this_hour=load_proxy,
        thermal_hot_stress_this_hour=hot_stress,
        thermal_cold_stress_this_hour=cold_stress,
        thermal_stress_this_hour=stress,
        thermal_degradation_this_hour=max(0.0, degradation),
        thermal_reason_this_hour=(
            "+".join(reasons) if reasons else "no_thermal_stress"
        ),
    )


__all__ = [
    "THERMAL_MODELS",
    "ThermalAssessment",
    "assess_thermal_for_hour",
]
