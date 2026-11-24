from math import isfinite

import pytest

import ops_sim.contacts as contacts_module
from ops_sim.config import DEFAULT_CONFIG, SimulationConfig
from ops_sim.contacts import (
    GeometryContactModel,
    GeometryContactSummary,
    GroundStation,
    SyntheticContactModel,
    contact_info_from_visible_seconds,
    default_astana_ground_station,
)
from ops_sim.geometry import GroundStation as GeometryGroundStation
from ops_sim.models import ContactInfo
from ops_sim.policies import AggressivePolicy
from ops_sim.scenarios import Scenario
from ops_sim.simulator import Simulator


def test_synthetic_contact_model_is_unchanged():
    model = SyntheticContactModel()
    assert model.contact_at_hour(0) == ContactInfo(15, 15)
    assert model.contact_at_hour(1) == ContactInfo()
    assert model.contact_at_hour(4) == ContactInfo(15, 15)


def test_contact_conversion_applies_short_window_rules():
    contact = contact_info_from_visible_seconds(
        30,
        command_overhead_seconds=0,
        data_overhead_seconds=60,
    )
    assert contact.cmd_contact_min == pytest.approx(0.5)
    assert contact.data_contact_min == 0


def test_contact_conversion_applies_data_overhead_and_minimum_duration():
    contact = contact_info_from_visible_seconds(
        600,
        data_overhead_seconds=60,
        min_data_contact_seconds=60,
    )
    assert contact.data_contact_min == pytest.approx(9)


def test_contact_conversion_handles_zero_and_caps_one_hour():
    assert contact_info_from_visible_seconds(0) == ContactInfo()
    contact = contact_info_from_visible_seconds(10_000)
    assert contact.cmd_contact_min == 60
    assert contact.data_contact_min == 60
    assert isfinite(contact.cmd_contact_min)
    assert isfinite(contact.data_contact_min)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"raw_visible_seconds": -1}, "raw_visible_seconds must be non-negative"),
        (
            {"raw_visible_seconds": 1, "command_overhead_seconds": -1},
            "command_overhead_seconds must be non-negative",
        ),
        (
            {"raw_visible_seconds": 1, "data_overhead_seconds": -1},
            "data_overhead_seconds must be non-negative",
        ),
        (
            {"raw_visible_seconds": 1, "min_data_contact_seconds": -1},
            "min_data_contact_seconds must be non-negative",
        ),
        ({"raw_visible_seconds": float("inf")}, "must be finite"),
        ({"raw_visible_seconds": float("nan")}, "must be finite"),
    ],
)
def test_contact_conversion_rejects_invalid_arguments(kwargs, match):
    with pytest.raises(ValueError, match=match):
        contact_info_from_visible_seconds(**kwargs)


@pytest.mark.parametrize("step_seconds", [0, -1, float("inf"), float("nan")])
def test_geometry_contact_model_requires_positive_step(step_seconds):
    with pytest.raises(ValueError, match="step_seconds must be positive"):
        GeometryContactModel(GroundStation(0, 0), step_seconds=step_seconds)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        (
            {"command_overhead_seconds": -1},
            "command_overhead_seconds must be non-negative",
        ),
        (
            {"data_overhead_seconds": -1},
            "data_overhead_seconds must be non-negative",
        ),
        (
            {"min_data_contact_seconds": -1},
            "min_data_contact_seconds must be non-negative",
        ),
    ],
)
def test_geometry_contact_model_rejects_negative_durations(kwargs, match):
    with pytest.raises(ValueError, match=match):
        GeometryContactModel(GroundStation(0, 0), **kwargs)


def test_geometry_contact_model_returns_bounded_finite_contact_info():
    contact = GeometryContactModel(default_astana_ground_station()).contact_at_hour(0)
    assert isinstance(contact, ContactInfo)
    assert 0 <= contact.cmd_contact_min <= 60
    assert 0 <= contact.data_contact_min <= 60
    assert isfinite(contact.cmd_contact_min)
    assert isfinite(contact.data_contact_min)


def test_geometry_contact_summary_exposes_visibility_and_contact_fields():
    summary = GeometryContactModel(
        default_astana_ground_station()
    ).contact_summary_at_hour(0)
    assert isinstance(summary, GeometryContactSummary)
    assert summary.hour == 0
    assert 0 <= summary.raw_visible_seconds <= DEFAULT_CONFIG.seconds_per_hour
    assert summary.usable_cmd_seconds == pytest.approx(
        summary.cmd_contact_min * DEFAULT_CONFIG.seconds_per_minute
    )
    assert summary.usable_data_seconds == pytest.approx(
        summary.data_contact_min * DEFAULT_CONFIG.seconds_per_minute
    )
    assert summary.max_elevation_deg is None or isfinite(summary.max_elevation_deg)
    assert summary.min_range_km is None or summary.min_range_km > 0
    assert (
        summary.first_visible_offset_seconds is None
        or summary.first_visible_offset_seconds >= 0
    )
    assert (
        summary.last_visible_offset_seconds is None
        or summary.last_visible_offset_seconds >= summary.first_visible_offset_seconds
    )


def test_geometry_contact_summary_is_cached_by_hour(monkeypatch):
    calls = 0
    real_sampler = contacts_module.sample_visibility_window

    def counted_sampler(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_sampler(*args, **kwargs)

    monkeypatch.setattr(contacts_module, "sample_visibility_window", counted_sampler)
    model = GeometryContactModel(default_astana_ground_station())
    first = model.contact_summary_at_hour(3)
    contact = model.contact_at_hour(3)
    second = model.contact_summary_at_hour(3)

    assert calls == 1
    assert first is second
    assert contact == ContactInfo(first.cmd_contact_min, first.data_contact_min)


def test_geometry_contact_model_can_be_injected_into_short_simulation():
    config = DEFAULT_CONFIG
    contact_model = GeometryContactModel(default_astana_ground_station(config), config)
    simulator = Simulator(
        AggressivePolicy(config),
        Scenario(),
        config,
        contact_model=contact_model,
    )
    result = simulator.run(4 / config.hours_per_year)
    assert result.state.hours_completed > 0


def test_geometry_contacts_do_not_repeat_the_fixed_synthetic_schedule():
    geometry_model = GeometryContactModel(
        default_astana_ground_station(), step_seconds=60
    )
    synthetic_model = SyntheticContactModel()
    geometry_pattern = [geometry_model.contact_at_hour(hour) for hour in range(72)]
    synthetic_pattern = [synthetic_model.contact_at_hour(hour) for hour in range(72)]
    assert geometry_pattern != synthetic_pattern


def test_default_astana_ground_station_is_a_geometry_station_proxy():
    config = SimulationConfig(minimum_elevation_deg=12.5)
    station = default_astana_ground_station(config)
    assert GroundStation is GeometryGroundStation
    assert station.latitude_deg == pytest.approx(51.16)
    assert station.longitude_deg == pytest.approx(71.47)
    assert station.minimum_elevation_deg == config.minimum_elevation_deg
    assert station.name == "astana_proxy"
