from math import isfinite, sqrt

import pytest

from ops_sim.config import DEFAULT_CONFIG
from ops_sim.geometry import (
    GroundStation,
    Vector3,
    VisibilityResult,
    elevation_angle_deg,
    ground_station_ecef,
    normalize_longitude_deg,
    range_km,
    sample_visibility_window,
    satellite_ecef_at_time,
    satellite_eci_at_time,
    spherical_to_ecef,
    summarize_visibility_window,
    visibility_at_time,
)
from ops_sim.orbit import position_at_hour, position_at_time


def test_existing_position_at_hour_zero_and_period():
    position = position_at_hour(0)
    assert position.latitude_deg == pytest.approx(0)
    assert position.longitude_deg == pytest.approx(0)
    assert position.altitude_km == pytest.approx(750)
    assert 90 < position.period_minutes < 110


def test_position_at_time_supports_fractional_hours_with_valid_bounds():
    position = position_at_time(0.5)
    assert -90 <= position.latitude_deg <= 90
    assert -180 <= position.longitude_deg < 180
    assert 0 <= position.phase_deg < 360
    assert position.altitude_km == DEFAULT_CONFIG.orbit_altitude_km
    assert 90 < position.period_minutes < 110
    assert all(isfinite(value) for value in position.__dict__.values())


def test_position_at_hour_delegates_consistently_to_fractional_api():
    hourly = position_at_hour(3)
    fractional = position_at_time(3.0)
    assert hourly.latitude_deg == pytest.approx(fractional.latitude_deg)
    assert hourly.longitude_deg == pytest.approx(fractional.longitude_deg)
    assert hourly.altitude_km == pytest.approx(fractional.altitude_km)
    assert hourly.phase_deg == pytest.approx(fractional.phase_deg)
    assert hourly.period_minutes == pytest.approx(fractional.period_minutes)


@pytest.mark.parametrize(
    ("longitude", "expected"),
    [(181, -179), (-181, 179), (360, 0), (0, 0)],
)
def test_longitude_normalization(longitude, expected):
    assert normalize_longitude_deg(longitude) == pytest.approx(expected)


def test_spherical_to_ecef_axis_sanity():
    radius = DEFAULT_CONFIG.earth_radius_km
    x_axis = spherical_to_ecef(0, 0, radius)
    y_axis = spherical_to_ecef(0, 90, radius)
    z_axis = spherical_to_ecef(90, 0, radius)
    assert (x_axis.x, x_axis.y, x_axis.z) == pytest.approx((radius, 0, 0), abs=1e-9)
    assert (y_axis.x, y_axis.y, y_axis.z) == pytest.approx((0, radius, 0), abs=1e-9)
    assert (z_axis.x, z_axis.y, z_axis.z) == pytest.approx((0, 0, radius), abs=1e-9)


def test_satellite_eci_and_ecef_are_x_aligned_at_time_zero():
    expected_radius = DEFAULT_CONFIG.earth_radius_km + DEFAULT_CONFIG.orbit_altitude_km
    eci = satellite_eci_at_time(0)
    ecef = satellite_ecef_at_time(0)
    assert eci == pytest.approx(Vector3(expected_radius, 0, 0))
    assert ecef == pytest.approx(Vector3(expected_radius, 0, 0))
    assert sqrt(eci.x**2 + eci.y**2 + eci.z**2) == pytest.approx(expected_radius)
    assert sqrt(ecef.x**2 + ecef.y**2 + ecef.z**2) == pytest.approx(expected_radius)


def test_fractional_geometry_vectors_range_and_elevation_are_finite():
    station = GroundStation(51.16, 71.47, 5.0)
    satellite_eci = satellite_eci_at_time(7.5)
    satellite_ecef = satellite_ecef_at_time(7.5)
    station_ecef = ground_station_ecef(station)

    for vector in (satellite_eci, satellite_ecef, station_ecef):
        assert all(isfinite(value) for value in vector.__dict__.values())
    assert range_km(satellite_ecef, station_ecef) > 0
    assert isfinite(elevation_angle_deg(satellite_ecef, station_ecef))


def test_elevation_angle_directly_above_and_opposite_side():
    earth_radius = DEFAULT_CONFIG.earth_radius_km
    orbit_radius = earth_radius + DEFAULT_CONFIG.orbit_altitude_km
    station = Vector3(earth_radius, 0, 0)
    overhead = Vector3(orbit_radius, 0, 0)
    opposite = Vector3(-orbit_radius, 0, 0)

    assert elevation_angle_deg(overhead, station) == pytest.approx(90)
    assert elevation_angle_deg(opposite, station) < 0
    assert range_km(overhead, station) == pytest.approx(DEFAULT_CONFIG.orbit_altitude_km)


def test_elevation_angle_rejects_zero_length_geometry():
    with pytest.raises(ValueError, match="station ECEF vector"):
        elevation_angle_deg(Vector3(1, 0, 0), Vector3(0, 0, 0))
    with pytest.raises(ValueError, match="must differ"):
        elevation_angle_deg(Vector3(1, 0, 0), Vector3(1, 0, 0))


def test_visibility_at_time_returns_sane_values():
    result = visibility_at_time(0.5, GroundStation(51.1694, 71.4491))
    assert isinstance(result.visible, bool)
    assert isfinite(result.elevation_deg)
    assert result.range_km > 0
    assert -90 <= result.satellite_lat_deg <= 90
    assert -180 <= result.satellite_lon_deg < 180
    assert result.satellite_alt_km == DEFAULT_CONFIG.orbit_altitude_km


def test_sample_visibility_window_is_chronological_and_half_open():
    results = sample_visibility_window(
        start_hour=2,
        duration_minutes=10,
        step_seconds=60,
        station=GroundStation(0, 0),
    )
    assert len(results) == 10
    assert results[0].hours_since_start == pytest.approx(2)
    assert results[-1].hours_since_start == pytest.approx(2 + 9 / 60)
    assert results[-1].hours_since_start < 2 + 10 / 60
    assert all(
        current.hours_since_start < following.hours_since_start
        for current, following in zip(results, results[1:])
    )


@pytest.mark.parametrize(
    "duration_minutes,step_seconds,match",
    [(1, 0, "step_seconds must be positive"), (1, -1, "step_seconds must be positive"),
     (-1, 60, "duration_minutes must be non-negative")],
)
def test_sample_visibility_window_rejects_invalid_arguments(
    duration_minutes, step_seconds, match
):
    with pytest.raises(ValueError, match=match):
        sample_visibility_window(
            0, duration_minutes, step_seconds, GroundStation(0, 0)
        )


def visibility_result(
    *, visible: bool, elevation: float, distance: float, hours: float
) -> VisibilityResult:
    return VisibilityResult(
        visible=visible,
        elevation_deg=elevation,
        range_km=distance,
        satellite_lat_deg=0,
        satellite_lon_deg=0,
        satellite_alt_km=750,
        station_lat_deg=0,
        station_lon_deg=0,
        minimum_elevation_deg=5,
        hours_since_start=hours,
    )


def test_summarize_visibility_window_with_no_visible_samples():
    summary = summarize_visibility_window(
        [visibility_result(visible=False, elevation=-5, distance=2000, hours=1)],
        step_seconds=10,
    )
    assert summary.visible_seconds == 0
    assert summary.max_elevation_deg is None
    assert summary.min_range_km is None
    assert summary.first_visible_offset_seconds is None
    assert summary.last_visible_offset_seconds is None


def test_summarize_visibility_window_with_visible_samples():
    seconds_per_hour = DEFAULT_CONFIG.seconds_per_hour
    results = [
        visibility_result(visible=False, elevation=-2, distance=1500, hours=1),
        visibility_result(
            visible=True, elevation=20, distance=900, hours=1 + 10 / seconds_per_hour
        ),
        visibility_result(
            visible=True, elevation=30, distance=700, hours=1 + 20 / seconds_per_hour
        ),
    ]
    summary = summarize_visibility_window(results, step_seconds=10)
    assert summary.visible_seconds == 20
    assert summary.max_elevation_deg == 30
    assert summary.min_range_km == 700
    assert summary.first_visible_offset_seconds == pytest.approx(10)
    assert summary.last_visible_offset_seconds == pytest.approx(20)
