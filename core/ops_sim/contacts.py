"""Contact-model interfaces and optional geometry-backed contact sampling.

The synthetic model remains the simulator default.  The geometry model is an
opt-in circular-orbit/spherical-Earth proxy; it does not model a link budget or
an operational ground-station schedule.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from .config import DEFAULT_CONFIG, SimulationConfig
from .geometry import (
    GroundStation,
    sample_visibility_window,
    summarize_visibility_window,
)
from .models import ContactInfo


class ContactModel(Protocol):
    def contact_at_hour(self, hour: int) -> ContactInfo: ...


class SyntheticContactModel:
    """Six fixed 15-minute command/data opportunities per 24-hour day."""

    def __init__(self, config: SimulationConfig = DEFAULT_CONFIG) -> None:
        self.config = config

    def contact_at_hour(self, hour: int) -> ContactInfo:
        if hour % self.config.contact_interval_hours == 0:
            return ContactInfo(
                self.config.cmd_contact_minutes,
                self.config.data_contact_minutes,
            )
        return ContactInfo()


@dataclass(frozen=True)
class GeometryContactSummary:
    """Auditable conversion of one sampled visibility window into contacts."""

    hour: int
    raw_visible_seconds: float
    usable_cmd_seconds: float
    usable_data_seconds: float
    cmd_contact_min: float
    data_contact_min: float
    max_elevation_deg: float | None
    min_range_km: float | None
    first_visible_offset_seconds: float | None
    last_visible_offset_seconds: float | None


def _validated_usable_seconds(
    raw_visible_seconds: float,
    command_overhead_seconds: int,
    data_overhead_seconds: int,
    min_data_contact_seconds: int,
) -> tuple[float, float]:
    values = {
        "raw_visible_seconds": raw_visible_seconds,
        "command_overhead_seconds": command_overhead_seconds,
        "data_overhead_seconds": data_overhead_seconds,
        "min_data_contact_seconds": min_data_contact_seconds,
    }
    for name, value in values.items():
        if not isfinite(value):
            raise ValueError(f"{name} must be finite")
        if value < 0:
            raise ValueError(f"{name} must be non-negative")

    max_contact_seconds = float(DEFAULT_CONFIG.seconds_per_hour)
    usable_cmd_seconds = min(
        max_contact_seconds,
        max(0.0, raw_visible_seconds - command_overhead_seconds),
    )
    usable_data_seconds = min(
        max_contact_seconds,
        max(0.0, raw_visible_seconds - data_overhead_seconds),
    )
    if usable_data_seconds < min_data_contact_seconds:
        usable_data_seconds = 0.0
    return usable_cmd_seconds, usable_data_seconds


def contact_info_from_visible_seconds(
    raw_visible_seconds: float,
    command_overhead_seconds: int = 0,
    data_overhead_seconds: int = 60,
    min_data_contact_seconds: int = 60,
) -> ContactInfo:
    """Apply simple setup overheads to visibility seconds for one hour.

    Negative or non-finite inputs are rejected.  Durations are capped at one
    hour so discretization at the edge of a sampled window cannot yield more
    than 60 contact minutes.
    """
    usable_cmd_seconds, usable_data_seconds = _validated_usable_seconds(
        raw_visible_seconds,
        command_overhead_seconds,
        data_overhead_seconds,
        min_data_contact_seconds,
    )
    return ContactInfo(
        cmd_contact_min=usable_cmd_seconds / DEFAULT_CONFIG.seconds_per_minute,
        data_contact_min=usable_data_seconds / DEFAULT_CONFIG.seconds_per_minute,
    )


def default_astana_ground_station(
    config: SimulationConfig = DEFAULT_CONFIG,
) -> GroundStation:
    """Return an Astana-like proxy station, not operational infrastructure."""
    return GroundStation(
        latitude_deg=51.16,
        longitude_deg=71.47,
        minimum_elevation_deg=config.minimum_elevation_deg,
        name="astana_proxy",
    )


class GeometryContactModel:
    """Lazily sample and cache geometric visibility for each simulated hour."""

    def __init__(
        self,
        station: GroundStation,
        config: SimulationConfig = DEFAULT_CONFIG,
        step_seconds: int = 30,
        command_overhead_seconds: int = 0,
        data_overhead_seconds: int = 60,
        min_data_contact_seconds: int = 60,
    ) -> None:
        if not isfinite(step_seconds) or step_seconds <= 0:
            raise ValueError("step_seconds must be positive")
        # Reuse the conversion validation for all duration arguments.
        _validated_usable_seconds(
            0.0,
            command_overhead_seconds,
            data_overhead_seconds,
            min_data_contact_seconds,
        )
        self.station = station
        self.config = config
        self.step_seconds = step_seconds
        self.command_overhead_seconds = command_overhead_seconds
        self.data_overhead_seconds = data_overhead_seconds
        self.min_data_contact_seconds = min_data_contact_seconds
        self._summary_cache: dict[int, GeometryContactSummary] = {}

    def contact_summary_at_hour(self, hour: int) -> GeometryContactSummary:
        if hour in self._summary_cache:
            return self._summary_cache[hour]

        summary = self._build_contact_summary(hour, self.config)
        self._summary_cache[hour] = summary
        return summary

    def contact_summary_at_hour_for_config(
        self,
        hour: int,
        orbit_config: SimulationConfig,
    ) -> GeometryContactSummary:
        """Sample one state-dependent hour without the fixed-orbit cache.

        V2.8 orbit-proxy geometry can differ for the same mission hour as the
        projected state changes. Bypassing the legacy hour-only cache keeps that
        opt-in path correct while leaving fixed-orbit caching unchanged.
        """
        return self._build_contact_summary(hour, orbit_config)

    def _build_contact_summary(
        self,
        hour: int,
        orbit_config: SimulationConfig,
    ) -> GeometryContactSummary:

        visibility_results = sample_visibility_window(
            hour,
            60,
            self.step_seconds,
            self.station,
            orbit_config,
        )
        visibility_summary = summarize_visibility_window(
            visibility_results,
            self.step_seconds,
        )
        contact = contact_info_from_visible_seconds(
            visibility_summary.visible_seconds,
            self.command_overhead_seconds,
            self.data_overhead_seconds,
            self.min_data_contact_seconds,
        )
        summary = GeometryContactSummary(
            hour=hour,
            raw_visible_seconds=visibility_summary.visible_seconds,
            usable_cmd_seconds=(
                contact.cmd_contact_min * DEFAULT_CONFIG.seconds_per_minute
            ),
            usable_data_seconds=(
                contact.data_contact_min * DEFAULT_CONFIG.seconds_per_minute
            ),
            cmd_contact_min=contact.cmd_contact_min,
            data_contact_min=contact.data_contact_min,
            max_elevation_deg=visibility_summary.max_elevation_deg,
            min_range_km=visibility_summary.min_range_km,
            first_visible_offset_seconds=(
                visibility_summary.first_visible_offset_seconds
            ),
            last_visible_offset_seconds=visibility_summary.last_visible_offset_seconds,
        )
        return summary

    def contact_at_hour(self, hour: int) -> ContactInfo:
        summary = self.contact_summary_at_hour(hour)
        return ContactInfo(summary.cmd_contact_min, summary.data_contact_min)
