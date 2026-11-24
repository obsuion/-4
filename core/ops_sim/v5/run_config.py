"""Immutable controlled experiment inputs outside spacecraft hardware."""

from __future__ import annotations

from dataclasses import dataclass

from .ids import EnvironmentId, FlightRulesId, NumericalConfigId, ScenarioId


@dataclass(frozen=True, slots=True)
class NumericalConfig:
    """Define numerical stepping, geometry sampling, and checkpoint cadence."""

    configuration_id: NumericalConfigId
    timestep_seconds: int
    geometry_sample_seconds: int
    checkpoint_interval_seconds: int

    def __post_init__(self) -> None:
        if type(self.configuration_id) is not NumericalConfigId:
            raise TypeError("configuration_id must be a NumericalConfigId")
        for field_name, value in (
            ("timestep_seconds", self.timestep_seconds),
            ("geometry_sample_seconds", self.geometry_sample_seconds),
            (
                "checkpoint_interval_seconds",
                self.checkpoint_interval_seconds,
            ),
        ):
            if type(value) is not int:
                raise TypeError(f"{field_name} must be an integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be greater than zero")
        if self.geometry_sample_seconds > self.timestep_seconds:
            raise ValueError(
                "geometry_sample_seconds must not exceed timestep_seconds"
            )
        if self.checkpoint_interval_seconds < self.timestep_seconds:
            raise ValueError(
                "checkpoint_interval_seconds must be at least timestep_seconds"
            )
        if self.checkpoint_interval_seconds % self.timestep_seconds != 0:
            raise ValueError(
                "checkpoint_interval_seconds must be an exact multiple of "
                "timestep_seconds"
            )


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    """Identify the immutable environment definition used by a run."""

    environment_id: EnvironmentId

    def __post_init__(self) -> None:
        if type(self.environment_id) is not EnvironmentId:
            raise TypeError("environment_id must be an EnvironmentId")


@dataclass(frozen=True, slots=True)
class FlightRulesConfig:
    """Identify the immutable flight-rule definition used by a run."""

    flight_rules_id: FlightRulesId

    def __post_init__(self) -> None:
        if type(self.flight_rules_id) is not FlightRulesId:
            raise TypeError("flight_rules_id must be a FlightRulesId")


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    """Identify the immutable scenario definition used by a run."""

    scenario_id: ScenarioId

    def __post_init__(self) -> None:
        if type(self.scenario_id) is not ScenarioId:
            raise TypeError("scenario_id must be a ScenarioId")


__all__ = [
    "EnvironmentConfig",
    "FlightRulesConfig",
    "NumericalConfig",
    "ScenarioConfig",
]
