"""Deterministic V3.7A synthetic target/scene scheduling proxy.

This module creates auditable scene opportunities without external catalogs,
weather, demand, observation geometry, attitude, or pointing physics.
Assessments are read-only and never mutate spacecraft state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import Mode, SatelliteState


TARGET_MODELS = ("legacy", "scene_scheduling_proxy")


@dataclass(frozen=True)
class TargetAssessment:
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


def assess_target_for_hour(
    *,
    target_model: str,
    hour: int,
    mode: Mode,
    state: SatelliteState,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> TargetAssessment:
    """Return one stable synthetic scene assessment without mutating state."""
    if target_model not in TARGET_MODELS:
        choices = ", ".join(TARGET_MODELS)
        raise ValueError(f"target_model must be one of: {choices}")
    if not isinstance(hour, int) or isinstance(hour, bool) or hour < 0:
        raise ValueError("hour must be a non-negative integer")
    if target_model == "legacy":
        return TargetAssessment(
            target_model=target_model,
            target_opportunity_this_hour=None,
            target_selected_this_hour=None,
            target_scene_id_this_hour=None,
            target_scene_area_km2_this_hour=None,
            target_priority_this_hour=None,
            target_imagery_mode_this_hour=None,
            target_data_multiplier_this_hour=1.0,
            target_missed_reason_this_hour=None,
            target_reason_this_hour=None,
        )

    period = config.target_opportunity_period_hours
    window = config.target_opportunity_window_hours
    if period <= 0:
        raise ValueError("target_opportunity_period_hours must be positive")
    if window < 0 or window > period:
        raise ValueError(
            "target_opportunity_window_hours must be within [0, period]"
        )
    if config.target_priority_max <= 0:
        raise ValueError("target_priority_max must be positive")
    if config.target_multispectral_every_n_opportunities <= 0:
        raise ValueError(
            "target_multispectral_every_n_opportunities must be positive"
        )

    # The state is deliberately read-only. Keeping it in the interface makes
    # the information boundary explicit for later bounded scheduling work.
    _ = state.alive
    opportunity = hour % period < window
    if not opportunity:
        return TargetAssessment(
            target_model=target_model,
            target_opportunity_this_hour=False,
            target_selected_this_hour=False,
            target_scene_id_this_hour=None,
            target_scene_area_km2_this_hour=None,
            target_priority_this_hour=None,
            target_imagery_mode_this_hour=None,
            target_data_multiplier_this_hour=(
                0.0 if mode == Mode.IMAGING else 1.0
            ),
            target_missed_reason_this_hour="no_target_opportunity",
            target_reason_this_hour="no_target_opportunity",
        )

    opportunity_index = hour // period
    area_km2 = max(
        0.0, config.target_scene_width_km * config.target_scene_height_km
    )
    priority = opportunity_index % config.target_priority_max + 1
    multispectral = (
        (opportunity_index + 1)
        % config.target_multispectral_every_n_opportunities
        == 0
    )
    imagery_mode = "multispectral" if multispectral else "panchromatic"
    selected = mode == Mode.IMAGING
    return TargetAssessment(
        target_model=target_model,
        target_opportunity_this_hour=True,
        target_selected_this_hour=selected,
        target_scene_id_this_hour=f"scene_{opportunity_index:08d}",
        target_scene_area_km2_this_hour=area_km2,
        target_priority_this_hour=priority,
        target_imagery_mode_this_hour=imagery_mode,
        target_data_multiplier_this_hour=1.0,
        target_missed_reason_this_hour=(
            None if selected else "not_imaging_mode"
        ),
        target_reason_this_hour=(
            "target_selected" if selected else "opportunity_not_imaged"
        ),
    )


__all__ = [
    "TARGET_MODELS",
    "TargetAssessment",
    "assess_target_for_hour",
]
