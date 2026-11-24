"""Deterministic V3.7B bounded attitude/pointing constraint proxy.

This is an auditable stress heuristic, not attitude dynamics, pointing control,
observation geometry, a slew model, or ADCS flight software. Assessments are
read-only and never mutate spacecraft state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import Mode, SatelliteState
from .targets import TargetAssessment


POINTING_MODELS = ("legacy", "bounded_pointing_proxy")


@dataclass(frozen=True)
class PointingAssessment:
    pointing_model: str
    pointing_required_this_hour: bool | None
    pointing_quality_this_hour: float | None
    pointing_multiplier_this_hour: float
    pointing_limited_this_hour: bool | None
    pointing_missed_this_hour: bool | None
    pointing_off_nadir_proxy_deg_this_hour: float | None
    pointing_slew_proxy_deg_this_hour: float | None
    pointing_reason_this_hour: str | None


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _validate_config(config: SimulationConfig) -> None:
    critical = config.pointing_quality_critical_threshold
    minimum = config.pointing_quality_min_threshold
    if not 0.0 <= critical <= minimum <= 1.0:
        raise ValueError(
            "pointing quality thresholds must satisfy "
            "0 <= critical <= minimum <= 1"
        )
    if config.pointing_max_off_nadir_proxy_deg < 0.0:
        raise ValueError("pointing_max_off_nadir_proxy_deg must be non-negative")
    if config.pointing_max_slew_proxy_deg < 0.0:
        raise ValueError("pointing_max_slew_proxy_deg must be non-negative")
    for name in (
        "pointing_off_nadir_penalty_scale",
        "pointing_slew_penalty_scale",
        "pointing_geometry_degraded_penalty",
    ):
        if getattr(config, name) < 0.0:
            raise ValueError(f"{name} must be non-negative")


def assess_pointing_for_hour(
    *,
    pointing_model: str,
    hour: int,
    mode: Mode,
    state: SatelliteState,
    target_assessment: TargetAssessment | None = None,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> PointingAssessment:
    """Return one deterministic bounded assessment without mutating state."""
    if pointing_model not in POINTING_MODELS:
        choices = ", ".join(POINTING_MODELS)
        raise ValueError(f"pointing_model must be one of: {choices}")
    if not isinstance(hour, int) or isinstance(hour, bool) or hour < 0:
        raise ValueError("hour must be a non-negative integer")
    if pointing_model == "legacy":
        return PointingAssessment(
            pointing_model=pointing_model,
            pointing_required_this_hour=None,
            pointing_quality_this_hour=None,
            pointing_multiplier_this_hour=1.0,
            pointing_limited_this_hour=None,
            pointing_missed_this_hour=None,
            pointing_off_nadir_proxy_deg_this_hour=None,
            pointing_slew_proxy_deg_this_hour=None,
            pointing_reason_this_hour=None,
        )

    _validate_config(config)
    if mode not in (Mode.IMAGING, Mode.DOWNLINK):
        return PointingAssessment(
            pointing_model=pointing_model,
            pointing_required_this_hour=False,
            pointing_quality_this_hour=None,
            pointing_multiplier_this_hour=1.0,
            pointing_limited_this_hour=False,
            pointing_missed_this_hour=False,
            pointing_off_nadir_proxy_deg_this_hour=None,
            pointing_slew_proxy_deg_this_hour=None,
            pointing_reason_this_hour="pointing_not_required",
        )

    scene_offset = 0
    if mode == Mode.IMAGING and target_assessment is not None:
        scene_id = target_assessment.target_scene_id_this_hour
        if scene_id is not None:
            try:
                scene_offset = int(scene_id.rsplit("_", 1)[-1])
            except ValueError:
                scene_offset = sum(ord(character) for character in scene_id)
    deterministic_index = hour + scene_offset
    off_nadir_fraction = (
        (deterministic_index * 37 + 11) % 101
    ) / 100.0
    slew_fraction = ((deterministic_index * 53 + 7) % 101) / 100.0
    off_nadir_deg = (
        config.pointing_max_off_nadir_proxy_deg * off_nadir_fraction
    )
    slew_deg = config.pointing_max_slew_proxy_deg * slew_fraction
    geometry_penalty = (
        config.pointing_geometry_degraded_penalty
        if state.orbit_geometry_degraded
        else 0.0
    )
    quality = _clamp(
        _clamp(state.adcs_health)
        - off_nadir_fraction * config.pointing_off_nadir_penalty_scale
        - slew_fraction * config.pointing_slew_penalty_scale
        - geometry_penalty
    )
    critical = config.pointing_quality_critical_threshold
    minimum = config.pointing_quality_min_threshold
    if quality <= critical:
        multiplier = 0.0
    elif quality < minimum:
        multiplier = _clamp(
            (quality - critical) / max(minimum - critical, 1e-12)
        )
    else:
        multiplier = 1.0
    limited = multiplier < 1.0
    missed = multiplier <= 0.0
    reason = (
        "critical_pointing_quality"
        if missed
        else "pointing_quality_limited"
        if limited
        else "pointing_quality_nominal"
    )
    return PointingAssessment(
        pointing_model=pointing_model,
        pointing_required_this_hour=True,
        pointing_quality_this_hour=quality,
        pointing_multiplier_this_hour=multiplier,
        pointing_limited_this_hour=limited,
        pointing_missed_this_hour=missed,
        pointing_off_nadir_proxy_deg_this_hour=off_nadir_deg,
        pointing_slew_proxy_deg_this_hour=slew_deg,
        pointing_reason_this_hour=reason,
    )


__all__ = [
    "POINTING_MODELS",
    "PointingAssessment",
    "assess_pointing_for_hour",
]
