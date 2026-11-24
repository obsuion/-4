"""Immutable identity manifest for one coherent V5 model/run definition."""

from __future__ import annotations

from dataclasses import dataclass

from .ids import (
    ControllerId,
    EnvironmentId,
    FlightRulesId,
    ModelManifestId,
    NumericalConfigId,
    ScenarioId,
    SpacecraftConfigurationId,
    WorldId,
)


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """Record stable identities of immutable inputs that produced a result."""

    manifest_id: ModelManifestId
    schema_version: int
    spacecraft_configuration_id: SpacecraftConfigurationId
    numerical_config_id: NumericalConfigId
    environment_id: EnvironmentId
    flight_rules_id: FlightRulesId
    scenario_id: ScenarioId
    world_id: WorldId
    controller_id: ControllerId

    def __post_init__(self) -> None:
        contracts = (
            ("manifest_id", self.manifest_id, ModelManifestId),
            (
                "spacecraft_configuration_id",
                self.spacecraft_configuration_id,
                SpacecraftConfigurationId,
            ),
            (
                "numerical_config_id",
                self.numerical_config_id,
                NumericalConfigId,
            ),
            ("environment_id", self.environment_id, EnvironmentId),
            ("flight_rules_id", self.flight_rules_id, FlightRulesId),
            ("scenario_id", self.scenario_id, ScenarioId),
            ("world_id", self.world_id, WorldId),
            ("controller_id", self.controller_id, ControllerId),
        )
        for field_name, value, expected_type in contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )
        if type(self.schema_version) is not int:
            raise TypeError("schema_version must be an integer")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be greater than zero")


__all__ = ["ModelManifest"]
