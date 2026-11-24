"""Deterministic V3.6A sunlight/eclipse and power-budget proxy.

This is a coarse, auditable operational proxy. It is not a real EPS, solar-
array, battery, thermal, or orbit/sun-geometry model, and it uses no ephemeris.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import pi, sqrt

from .config import DEFAULT_CONFIG, SimulationConfig
from .models import Mode


POWER_MODELS = ("legacy", "eclipse_proxy")


@dataclass(frozen=True)
class PowerAssessment:
    """One read-only current-hour power-proxy assessment."""

    power_model: str
    sunlight_factor: float | None
    eclipse: bool | None
    eclipse_fraction_reference: float | None
    power_load_proxy_w: float | None
    power_generation_proxy_w: float | None
    net_power_proxy_w: float | None
    soc_delta_power_model: float


def compute_sunlight_factor(
    hour: int,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> float:
    """Return a binary sunlight factor from a repeating orbit-phase window."""
    if not isinstance(hour, int) or isinstance(hour, bool) or hour < 0:
        raise ValueError("hour must be a non-negative integer")
    eclipse_fraction = config.eclipse_fraction_per_orbit
    if not 0.0 <= eclipse_fraction <= 1.0:
        raise ValueError("eclipse_fraction_per_orbit must be within [0, 1]")

    orbit_radius_km = config.earth_radius_km + config.orbit_altitude_km
    mean_motion_rad_s = sqrt(
        config.earth_mu_km3_s2 / orbit_radius_km**3
    )
    orbit_period_seconds = 2.0 * pi / mean_motion_rad_s
    initial_phase_fraction = (
        config.orbit_initial_phase_deg / config.degrees_per_circle
    )
    phase_fraction = (
        initial_phase_fraction
        + hour * config.seconds_per_hour / orbit_period_seconds
    ) % 1.0
    eclipse_start = 0.5 - eclipse_fraction / 2.0
    eclipse_end = 0.5 + eclipse_fraction / 2.0
    return 0.0 if eclipse_start <= phase_fraction < eclipse_end else 1.0


def _mode_power_load_proxy_w(
    mode: Mode, config: SimulationConfig
) -> float:
    return {
        Mode.SAFE: config.safe_power_load_proxy_w,
        Mode.STANDBY: config.standby_power_load_proxy_w,
        Mode.IMAGING: config.imaging_power_load_proxy_w,
        Mode.DOWNLINK: config.downlink_power_load_proxy_w,
        Mode.MANEUVER: config.maneuver_power_load_proxy_w,
        Mode.BACKUP: config.backup_power_load_proxy_w,
        Mode.EMERGENCY_BEACON: config.emergency_power_load_proxy_w,
    }[mode]


def assess_power_for_hour(
    *,
    power_model: str,
    hour: int,
    mode: Mode,
    base_soc_delta: float,
    generation_efficiency: float,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> PowerAssessment:
    """Assess one hour without mutating simulator or spacecraft state."""
    if power_model not in POWER_MODELS:
        choices = ", ".join(POWER_MODELS)
        raise ValueError(f"power_model must be one of: {choices}")

    legacy_soc_delta = (
        base_soc_delta * generation_efficiency
        if base_soc_delta > config.minimum_percent
        else base_soc_delta
    )
    if power_model == "legacy":
        return PowerAssessment(
            power_model=power_model,
            sunlight_factor=None,
            eclipse=None,
            eclipse_fraction_reference=None,
            power_load_proxy_w=None,
            power_generation_proxy_w=None,
            net_power_proxy_w=None,
            soc_delta_power_model=legacy_soc_delta,
        )

    sunlight_factor = compute_sunlight_factor(hour, config)
    load_w = _mode_power_load_proxy_w(mode, config)
    generation_w = (
        config.solar_generation_proxy_w
        * sunlight_factor
        * generation_efficiency
    )
    soc_delta = (
        legacy_soc_delta * sunlight_factor
        if legacy_soc_delta > config.minimum_percent
        else legacy_soc_delta
    )
    return PowerAssessment(
        power_model=power_model,
        sunlight_factor=sunlight_factor,
        eclipse=sunlight_factor <= config.minimum_percent,
        eclipse_fraction_reference=config.eclipse_fraction_per_orbit,
        power_load_proxy_w=load_w,
        power_generation_proxy_w=generation_w,
        net_power_proxy_w=generation_w - load_w,
        soc_delta_power_model=soc_delta,
    )


__all__ = [
    "POWER_MODELS",
    "PowerAssessment",
    "assess_power_for_hour",
    "compute_sunlight_factor",
]
