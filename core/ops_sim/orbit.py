"""Simplified analytical circular-orbit proxy.

This module is intended for experiment logging and visualization.  It is not a
TLE propagator and does not model perturbations or provide operational accuracy.
The existing synthetic contact schedule remains independent of this position.
"""

from dataclasses import dataclass
from math import asin, atan2, degrees, pi, radians, sqrt

from .config import DEFAULT_CONFIG, SimulationConfig
from .geometry import normalize_longitude_deg, satellite_eci_at_time


@dataclass(frozen=True)
class OrbitPosition:
    latitude_deg: float
    longitude_deg: float
    altitude_km: float
    phase_deg: float
    period_minutes: float


def position_at_time(
    hours_since_start: float, config: SimulationConfig = DEFAULT_CONFIG
) -> OrbitPosition:
    """Return approximate position at an arbitrary fractional mission hour."""
    radius = config.earth_radius_km + config.orbit_altitude_km
    mean_motion = sqrt(config.earth_mu_km3_s2 / radius**3)
    period_seconds = 2 * pi / mean_motion
    time_seconds = hours_since_start * config.seconds_per_hour
    initial_phase = radians(config.orbit_initial_phase_deg)
    theta = mean_motion * time_seconds + initial_phase
    eci = satellite_eci_at_time(hours_since_start, config)
    latitude = asin(max(-1.0, min(1.0, eci.z / radius)))
    # Subtracting the Earth rotation angle is the analytical z-axis ECI-to-ECEF
    # rotation for spherical longitude and preserves the established hour output.
    earth_rotation = config.earth_rotation_rate_rad_s * time_seconds
    longitude_deg = normalize_longitude_deg(
        degrees(atan2(eci.y, eci.x) - earth_rotation)
    )
    phase_deg = degrees(theta) % config.degrees_per_circle
    return OrbitPosition(
        degrees(latitude),
        longitude_deg,
        config.orbit_altitude_km,
        phase_deg,
        period_seconds / config.seconds_per_minute,
    )


def position_at_hour(
    hour: int, config: SimulationConfig = DEFAULT_CONFIG
) -> OrbitPosition:
    """Return position at an integer hour through the fractional-time API."""
    return position_at_time(float(hour), config)
