"""Circular-orbit and spherical-Earth geometry primitives.

The functions here are deterministic analytical helpers for future contact-window
work. They are not TLE/SGP4 propagation or operational flight dynamics.
"""

from dataclasses import dataclass
from math import asin, atan2, cos, degrees, radians, sin, sqrt

from .config import DEFAULT_CONFIG, SimulationConfig


@dataclass(frozen=True)
class Vector3:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class GroundStation:
    latitude_deg: float
    longitude_deg: float
    minimum_elevation_deg: float = DEFAULT_CONFIG.minimum_elevation_deg
    name: str = "ground_station"


@dataclass(frozen=True)
class VisibilityResult:
    visible: bool
    elevation_deg: float
    range_km: float
    satellite_lat_deg: float
    satellite_lon_deg: float
    satellite_alt_km: float
    station_lat_deg: float
    station_lon_deg: float
    minimum_elevation_deg: float
    hours_since_start: float


@dataclass(frozen=True)
class VisibilityWindowSummary:
    visible_seconds: float
    max_elevation_deg: float | None
    min_range_km: float | None
    first_visible_offset_seconds: float | None
    last_visible_offset_seconds: float | None


def normalize_longitude_deg(lon_deg: float) -> float:
    """Normalize longitude to the half-open interval [-180, 180)."""
    return (lon_deg + 180.0) % 360.0 - 180.0


def spherical_to_ecef(
    latitude_deg: float, longitude_deg: float, radius_km: float
) -> Vector3:
    """Convert spherical latitude/longitude and radius to an ECEF vector."""
    latitude = radians(latitude_deg)
    longitude = radians(longitude_deg)
    cos_latitude = cos(latitude)
    return Vector3(
        radius_km * cos_latitude * cos(longitude),
        radius_km * cos_latitude * sin(longitude),
        radius_km * sin(latitude),
    )


def satellite_eci_at_time(
    hours_since_start: float, config: SimulationConfig = DEFAULT_CONFIG
) -> Vector3:
    """Return circular-orbit satellite position in Earth-centered inertial axes."""
    radius = config.earth_radius_km + config.orbit_altitude_km
    mean_motion = sqrt(config.earth_mu_km3_s2 / radius**3)
    time_seconds = hours_since_start * config.seconds_per_hour
    theta = mean_motion * time_seconds + radians(config.orbit_initial_phase_deg)
    inclination = radians(config.orbit_inclination_deg)
    raan = radians(config.orbit_raan_deg)
    return Vector3(
        radius
        * (cos(raan) * cos(theta) - sin(raan) * sin(theta) * cos(inclination)),
        radius
        * (sin(raan) * cos(theta) + cos(raan) * sin(theta) * cos(inclination)),
        radius * sin(theta) * sin(inclination),
    )


def satellite_ecef_at_time(
    hours_since_start: float, config: SimulationConfig = DEFAULT_CONFIG
) -> Vector3:
    """Rotate the analytical ECI satellite vector into Earth-fixed axes."""
    eci = satellite_eci_at_time(hours_since_start, config)
    rotation = (
        config.earth_rotation_rate_rad_s
        * hours_since_start
        * config.seconds_per_hour
    )
    return Vector3(
        cos(rotation) * eci.x + sin(rotation) * eci.y,
        -sin(rotation) * eci.x + cos(rotation) * eci.y,
        eci.z,
    )


def ground_station_ecef(
    station: GroundStation, config: SimulationConfig = DEFAULT_CONFIG
) -> Vector3:
    """Return a spherical-Earth ground station position in Earth-fixed axes."""
    return spherical_to_ecef(
        station.latitude_deg,
        station.longitude_deg,
        config.earth_radius_km,
    )


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return Vector3(left.x - right.x, left.y - right.y, left.z - right.z)


def _dot(left: Vector3, right: Vector3) -> float:
    return left.x * right.x + left.y * right.y + left.z * right.z


def _norm(vector: Vector3) -> float:
    return sqrt(_dot(vector, vector))


def range_km(satellite_ecef: Vector3, station_ecef: Vector3) -> float:
    """Return Euclidean satellite-to-station range in kilometers."""
    return _norm(_subtract(satellite_ecef, station_ecef))


def elevation_angle_deg(
    satellite_ecef: Vector3, station_ecef: Vector3
) -> float:
    """Return spherical-Earth elevation above the station's local horizon."""
    station_radius = _norm(station_ecef)
    if station_radius == 0.0:
        raise ValueError("station ECEF vector must have non-zero length")
    line_of_sight = _subtract(satellite_ecef, station_ecef)
    line_of_sight_range = _norm(line_of_sight)
    if line_of_sight_range == 0.0:
        raise ValueError("satellite and station ECEF vectors must differ")
    up = Vector3(
        station_ecef.x / station_radius,
        station_ecef.y / station_radius,
        station_ecef.z / station_radius,
    )
    sine_elevation = _dot(line_of_sight, up) / line_of_sight_range
    sine_elevation = max(-1.0, min(1.0, sine_elevation))
    return degrees(asin(sine_elevation))


def visibility_at_time(
    hours_since_start: float,
    station: GroundStation,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> VisibilityResult:
    """Evaluate range, elevation, and threshold visibility at one simulation time."""
    satellite = satellite_ecef_at_time(hours_since_start, config)
    station_vector = ground_station_ecef(station, config)
    radius = config.earth_radius_km + config.orbit_altitude_km
    latitude = degrees(asin(max(-1.0, min(1.0, satellite.z / radius))))
    longitude = normalize_longitude_deg(degrees(atan2(satellite.y, satellite.x)))
    elevation = elevation_angle_deg(satellite, station_vector)
    distance = range_km(satellite, station_vector)
    return VisibilityResult(
        visible=bool(elevation >= station.minimum_elevation_deg),
        elevation_deg=elevation,
        range_km=distance,
        satellite_lat_deg=latitude,
        satellite_lon_deg=longitude,
        satellite_alt_km=config.orbit_altitude_km,
        station_lat_deg=station.latitude_deg,
        station_lon_deg=station.longitude_deg,
        minimum_elevation_deg=station.minimum_elevation_deg,
        hours_since_start=hours_since_start,
    )


def sample_visibility_window(
    start_hour: int,
    duration_minutes: int,
    step_seconds: int,
    station: GroundStation,
    config: SimulationConfig = DEFAULT_CONFIG,
) -> list[VisibilityResult]:
    """Sample visibility inside a half-open time window at a fixed resolution."""
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    if duration_minutes < 0:
        raise ValueError("duration_minutes must be non-negative")
    duration_seconds = duration_minutes * config.seconds_per_minute
    return [
        visibility_at_time(
            start_hour + offset_seconds / config.seconds_per_hour,
            station,
            config,
        )
        for offset_seconds in range(0, duration_seconds, step_seconds)
    ]


def summarize_visibility_window(
    results: list[VisibilityResult], step_seconds: int
) -> VisibilityWindowSummary:
    """Summarize sampled visible duration, peak elevation, range, and offsets."""
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    visible = [result for result in results if result.visible]
    if not visible:
        return VisibilityWindowSummary(0.0, None, None, None, None)
    first_sample_hour = results[0].hours_since_start
    offsets = [
        (result.hours_since_start - first_sample_hour)
        * DEFAULT_CONFIG.seconds_per_hour
        for result in visible
    ]
    return VisibilityWindowSummary(
        visible_seconds=float(len(visible) * step_seconds),
        max_elevation_deg=max(result.elevation_deg for result in visible),
        min_range_km=min(result.range_km for result in visible),
        first_visible_offset_seconds=offsets[0],
        last_visible_offset_seconds=offsets[-1],
    )
