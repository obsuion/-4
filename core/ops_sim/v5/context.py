"""Coherent immutable inputs and complete completed-step runtime context."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .configuration import SpacecraftConfiguration
from .controller_state import ControllerState
from .data_delivery import (
    GroundDataDeliveryState,
    _validate_delivery_state_against_storage_and_time,
)
from .diagnostics import Diagnostics
from .knowledge import GroundKnowledgeState
from .manifest import ModelManifest
from .mission import MissionState
from .frames import CartesianState
from .orbit import evaluate_two_body_state
from .orbit_binding import CoastOrbitInputs, derive_coast_manifest_id
from .orbit_config import GeometryInstant
from .orbit_j2_binding import J2CoastOrbitInputs, _validate_bound_coast, derive_j2_coast_manifest_id
from .orbit_j2_enclosure import J2EnclosureResult, evaluate_j2_enclosure
from .run_config import (
    EnvironmentConfig,
    FlightRulesConfig,
    NumericalConfig,
    ScenarioConfig,
)
from .state import (
    BatteryState,
    DataStorageState,
    DegradationState,
    SpacecraftState,
    ThermalState,
)
from .storage import validate_storage_records_against_config
from .world import CommonWorld


@dataclass(frozen=True, slots=True)
class SimulationInputs:
    """Bind every immutable definition used by one coherent simulation run."""

    spacecraft_configuration: SpacecraftConfiguration
    numerical_config: NumericalConfig
    environment_config: EnvironmentConfig
    flight_rules_config: FlightRulesConfig
    scenario_config: ScenarioConfig
    common_world: CommonWorld
    model_manifest: ModelManifest
    coast_orbit: CoastOrbitInputs | J2CoastOrbitInputs | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        contracts = (
            (
                "spacecraft_configuration",
                self.spacecraft_configuration,
                SpacecraftConfiguration,
            ),
            ("numerical_config", self.numerical_config, NumericalConfig),
            (
                "environment_config",
                self.environment_config,
                EnvironmentConfig,
            ),
            (
                "flight_rules_config",
                self.flight_rules_config,
                FlightRulesConfig,
            ),
            ("scenario_config", self.scenario_config, ScenarioConfig),
            ("common_world", self.common_world, CommonWorld),
            ("model_manifest", self.model_manifest, ModelManifest),
        )
        for field_name, value, expected_type in contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )

        identity_contracts = (
            (
                "spacecraft configuration",
                self.model_manifest.spacecraft_configuration_id,
                self.spacecraft_configuration.configuration_id,
            ),
            (
                "numerical configuration",
                self.model_manifest.numerical_config_id,
                self.numerical_config.configuration_id,
            ),
            (
                "environment",
                self.model_manifest.environment_id,
                self.environment_config.environment_id,
            ),
            (
                "flight rules",
                self.model_manifest.flight_rules_id,
                self.flight_rules_config.flight_rules_id,
            ),
            (
                "scenario",
                self.model_manifest.scenario_id,
                self.scenario_config.scenario_id,
            ),
            (
                "world",
                self.model_manifest.world_id,
                self.common_world.world_id,
            ),
            (
                "world scenario",
                self.common_world.scenario_id,
                self.scenario_config.scenario_id,
            ),
        )
        for name, actual, expected in identity_contracts:
            if actual != expected:
                raise ValueError(f"{name} identity mismatch")

        _validate_bound_coast(
            self.coast_orbit, self.model_manifest, self.numerical_config, self.common_world,
        )


def _validate_inputs(inputs: SimulationInputs) -> None:
    """Recheck forged immutable inputs without replacing authoritative references."""
    if type(inputs) is not SimulationInputs:
        raise TypeError("inputs must be SimulationInputs")
    SimulationInputs(
        inputs.spacecraft_configuration, inputs.numerical_config, inputs.environment_config,
        inputs.flight_rules_config, inputs.scenario_config, inputs.common_world,
        inputs.model_manifest, coast_orbit=inputs.coast_orbit,
    )


def with_coast_orbit(inputs: SimulationInputs, coast_orbit: CoastOrbitInputs) -> SimulationInputs:
    """Bind valid inputs immutably, replacing the old manifest label, not its associations.

    Rebinding equal content is deterministic: the previous label is not hashed.
    Stale supplied bindings are rejected before constructing the new definition.
    """
    _validate_inputs(inputs)
    manifest_id = derive_coast_manifest_id(
        coast_orbit, inputs.model_manifest, inputs.numerical_config, inputs.common_world,
    )
    return replace(inputs, model_manifest=replace(inputs.model_manifest, manifest_id=manifest_id),
                   coast_orbit=coast_orbit)


def with_j2_coast_orbit(inputs: SimulationInputs, coast_orbit: J2CoastOrbitInputs) -> SimulationInputs:
    """Bind complete original J2 inputs, rejecting stale supplied definitions."""
    _validate_inputs(inputs)
    manifest_id = derive_j2_coast_manifest_id(
        coast_orbit, inputs.model_manifest, inputs.numerical_config, inputs.common_world,
    )
    return replace(inputs, model_manifest=replace(inputs.model_manifest, manifest_id=manifest_id),
                   coast_orbit=coast_orbit)


@dataclass(slots=True)
class SimulationContext:
    """Own all authoritative state at a completed simulation-step boundary."""

    simulation_time_seconds: int
    inputs: SimulationInputs
    spacecraft_state: SpacecraftState
    ground_knowledge_state: GroundKnowledgeState
    ground_data_delivery_state: GroundDataDeliveryState
    mission_state: MissionState
    controller_state: ControllerState
    diagnostics: Diagnostics

    def __post_init__(self) -> None:
        if type(self.simulation_time_seconds) is not int:
            raise TypeError("simulation_time_seconds must be an integer")
        if self.simulation_time_seconds < 0:
            raise ValueError(
                "simulation_time_seconds must be greater than or equal to zero"
            )
        contracts = (
            ("inputs", self.inputs, SimulationInputs),
            ("spacecraft_state", self.spacecraft_state, SpacecraftState),
            (
                "ground_knowledge_state",
                self.ground_knowledge_state,
                GroundKnowledgeState,
            ),
            (
                "ground_data_delivery_state",
                self.ground_data_delivery_state,
                GroundDataDeliveryState,
            ),
            ("mission_state", self.mission_state, MissionState),
            ("controller_state", self.controller_state, ControllerState),
            ("diagnostics", self.diagnostics, Diagnostics),
        )
        for field_name, value, expected_type in contracts:
            if type(value) is not expected_type:
                raise TypeError(
                    f"{field_name} must be a {expected_type.__name__}"
                )
        _validate_inputs(self.inputs)
        battery_state = self.spacecraft_state.battery
        if type(battery_state) is not BatteryState:
            raise TypeError("spacecraft_state.battery must be a BatteryState")
        BatteryState(battery_state.energy_wh)
        battery_energy_wh = battery_state.energy_wh
        nominal_energy_wh = (
            self.inputs.spacecraft_configuration.eps.battery
            .nominal_energy_wh.value
        )
        if battery_energy_wh > nominal_energy_wh:
            raise ValueError(
                "spacecraft battery energy must not exceed active nominal "
                "battery capacity"
            )
        thermal_state = self.spacecraft_state.thermal
        if type(thermal_state) is not ThermalState:
            raise TypeError("spacecraft_state.thermal must be a ThermalState")
        ThermalState(thermal_state.node_states)
        configured_node_ids = {
            node.node_id
            for node in (
                self.inputs.spacecraft_configuration.thermal.network.nodes
            )
        }
        runtime_node_ids = {
            node_state.node_id for node_state in thermal_state.node_states
        }
        if runtime_node_ids != configured_node_ids:
            raise ValueError(
                "runtime thermal node IDs must exactly match the active "
                "thermal network"
            )
        degradation_state = self.spacecraft_state.degradation
        if type(degradation_state) is not DegradationState:
            raise TypeError(
                "spacecraft_state.degradation must be a DegradationState"
            )
        DegradationState(
            degradation_state.battery,
            degradation_state.solar,
        )
        if self.controller_state.controller_id != (
            self.inputs.model_manifest.controller_id
        ):
            raise ValueError("controller identity mismatch")
        if self.simulation_time_seconds > self.inputs.common_world.horizon_seconds:
            raise ValueError("simulation time exceeds the common-world horizon")

        onboard = self.spacecraft_state.onboard
        for name, value in (
            (
                "last qualifying contact time",
                onboard.last_qualifying_contact_time_seconds,
            ),
            ("critical energy start time", onboard.critical_energy_since_seconds),
        ):
            if value is not None and value > self.simulation_time_seconds:
                raise ValueError(f"{name} cannot be in the future")

        data_storage = self.spacecraft_state.data_storage
        if type(data_storage) is not DataStorageState:
            raise TypeError(
                "spacecraft_state.data_storage must be a DataStorageState"
            )
        DataStorageState(data_storage.stored_records)
        validate_storage_records_against_config(
            self.inputs.spacecraft_configuration.storage,
            data_storage.stored_records,
        )
        _validate_delivery_state_against_storage_and_time(
            self.ground_data_delivery_state,
            data_storage.stored_records,
            self.simulation_time_seconds,
        )

        telemetry = self.ground_knowledge_state.latest_telemetry
        if telemetry is not None:
            if telemetry.received_at_seconds > self.simulation_time_seconds:
                raise ValueError("telemetry receipt time cannot be in the future")
            if telemetry.sampled_at_seconds > self.simulation_time_seconds:
                raise ValueError("telemetry sample time cannot be in the future")


def evaluate_context_coast(context: SimulationContext) -> CartesianState:
    """Recompute coast evidence at the actual clock, without advancing any domain.

    Zero maps to the trajectory's reference TT epoch, not its initial sample.
    The world horizon is fingerprinted, not certified as a valid B1 query span.
    GeometryInstant and B1 numerical/convergence errors remain visible.
    """
    # Reuse the complete engine boundary validator without an import-time cycle.
    from .engine import _validate_completed_context

    _validate_completed_context(context)
    coast = context.inputs.coast_orbit
    if coast is None:
        raise ValueError("context has no coast_orbit binding")
    if type(coast) is not CoastOrbitInputs:
        raise TypeError("two-body context query requires CoastOrbitInputs")
    epoch = coast.trajectory.initial_state.position.instant.epoch
    instant = GeometryInstant(epoch, context.simulation_time_seconds)
    return evaluate_two_body_state(coast.trajectory, instant, coast.solver_config)


def evaluate_context_j2_enclosure(context: SimulationContext) -> J2EnclosureResult:
    """Recompute unchanged F3 at elapsed TT clock time; never reanchor or cache.

    This query neither advances the engine nor supplies environmental forcing.
    Unresolved F3 results retain their explicit status and absent usable bounds.
    """
    from .engine import _validate_completed_context

    _validate_completed_context(context)
    coast = context.inputs.coast_orbit
    if type(coast) is not J2CoastOrbitInputs:
        raise TypeError("J2 context query requires J2CoastOrbitInputs")
    epoch = coast.trajectory.initial_state.position.instant.epoch
    instant = GeometryInstant(epoch, context.simulation_time_seconds)
    return evaluate_j2_enclosure(coast.trajectory, instant, coast.solver_config, coast.enclosure_policy)


# Preserve historical wildcard imports; B2 helpers use explicit named imports.
__all__ = ["SimulationInputs", "SimulationContext"]
