"""Focused tests for V5.0B4 inputs, context, and portable checkpoints."""

import ast
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, is_dataclass, replace
import json
from pathlib import Path

import pytest

from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
    ControllerStateSnapshot,
    DataStorageStateSnapshot,
    DiagnosticsSnapshot,
    GroundDataDeliveryStateSnapshot,
    GroundKnowledgeSnapshot,
    MissionStateSnapshot,
    SpacecraftStateSnapshot,
    ThermalNodeStateSnapshot,
    ThermalStateSnapshot,
)
from ops_sim.v5.configuration import (
    ADCSConfig,
    BatteryConfig,
    CommunicationsConfig,
    DegradationConfig,
    EPSConfig,
    OBCConfig,
    PayloadConfig,
    PayloadFamily,
    PayloadMode,
    PropulsionConfig,
    SolarArrayConfig,
    SpacecraftConfiguration,
    StorageConfig,
    ThermalConfig,
)
from ops_sim.v5.context import SimulationContext, SimulationInputs
from ops_sim.v5.controller_state import ControllerState
from ops_sim.v5.data_delivery import GroundDataDeliveryState
from ops_sim.v5.degradation_config import BatteryAgeingModelConfig
from ops_sim.v5.diagnostics import Diagnostics
from ops_sim.v5.ids import (
    ADCSSlewAnchorId,
    AuthorityId,
    CommandId,
    ControllerId,
    DataProductId,
    EnvironmentId,
    FlightRulesId,
    MissionRequestId,
    ModelManifestId,
    NumericalConfigId,
    ParameterId,
    PlanId,
    ScenarioId,
    SpacecraftConfigurationId,
    SubsystemConfigurationId,
    TelemetrySnapshotId,
    ThermalNodeId,
    WorldEventId,
    WorldId,
)
from ops_sim.v5.knowledge import GroundKnowledgeState, TelemetrySnapshot
from ops_sim.v5.manifest import ModelManifest
from ops_sim.v5.mission import MissionState
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.run_config import (
    EnvironmentConfig,
    FlightRulesConfig,
    NumericalConfig,
    ScenarioConfig,
)
from ops_sim.v5.state import (
    BatteryDegradationState,
    BatteryState,
    DataStorageState,
    DegradationState,
    FDIRState,
    OnboardOperationsState,
    OperationalMode,
    PropulsionState,
    SpacecraftState,
    SolarDegradationState,
    ThermalNodeState,
    ThermalState,
)
from ops_sim.v5.thermal_config import ThermalNetworkConfig, ThermalNodeConfig
from ops_sim.v5.world import CommonWorld


ROOT = Path(__file__).resolve().parents[1]
B4_MODULE_PATHS = tuple(
    ROOT / "ops_sim" / "v5" / name
    for name in (
        "run_config.py",
        "world.py",
        "manifest.py",
        "context.py",
        "checkpoint.py",
    )
)


def _parameter(parameter_id: str, units: str, value: float) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by a focused unit test.",
        ),
    )


def _agile_pointing() -> AgilePointingConfig:
    def anchor(
        anchor_value: str,
        angle_deg: float,
        elapsed_seconds: float,
    ) -> BoresightSlewTimeAnchor:
        prefix = f"adcs.slew-envelope.{anchor_value}"
        return BoresightSlewTimeAnchor(
            ADCSSlewAnchorId(anchor_value),
            _parameter(f"{prefix}.angular-separation", "deg", angle_deg),
            _parameter(f"{prefix}.elapsed-time", "s", elapsed_seconds),
        )

    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir", "deg", 45.0
        ),
        _parameter("adcs.pointing.post-slew-settling-time", "s", 5.0),
        tuple(
            anchor(*values)
            for values in (
                ("zero", 0.0, 0.0),
                ("small", 10.0, 20.0),
                ("medium", 30.0, 50.0),
                ("large", 60.0, 90.0),
                ("extended", 90.0, 130.0),
            )
        ),
    )


def _optical_acquisition() -> OpticalAcquisitionConfig:
    return OpticalAcquisitionConfig(
        _parameter(
            "payload.optical.reference-nadir-swath-width", "m", 1000.0
        ),
        _parameter(
            "payload.optical.panchromatic-reference-sample-spacing",
            "m",
            1.0,
        ),
        _parameter(
            "payload.optical.multispectral-reference-sample-spacing",
            "m",
            4.0,
        ),
        _parameter("payload.optical.multispectral-band-count", "1", 4),
        _parameter(
            "payload.optical.acquisition-bits-per-sample",
            "bit/sample",
            12,
        ),
        _parameter("payload.optical.acquisition-power", "W", 100.0),
        True,
    )


def _zero_damage_ageing_model() -> BatteryAgeingModelConfig:
    return BatteryAgeingModelConfig(
        _parameter(
            "degradation.battery.reference-temperature", "K", 300.0
        ),
        _parameter(
            "degradation.battery.calendar-damage-rate-at-reference",
            "1/s",
            0.0,
        ),
        _parameter(
            "degradation.battery.calendar-activation-energy", "J/mol", 0.0
        ),
        _parameter(
            "degradation.battery.cycling-damage-per-normalized-"
            "throughput-at-reference",
            "1",
            0.0,
        ),
        _parameter(
            "degradation.battery.cycling-activation-energy", "J/mol", 0.0
        ),
    )


def _thermal_network() -> ThermalNetworkConfig:
    def node(node_name: str) -> ThermalNodeConfig:
        prefix = f"thermal.node.{node_name}"
        return ThermalNodeConfig(
            ThermalNodeId(node_name),
            _parameter(f"{prefix}.heat-capacity", "J/K", 1000.0),
            _parameter(f"{prefix}.emissivity", "1", 0.8),
            _parameter(f"{prefix}.radiating-area", "m^2", 1.0),
            _parameter(
                f"{prefix}.operating-min-temperature", "K", 270.0
            ),
            _parameter(
                f"{prefix}.operating-max-temperature", "K", 320.0
            ),
            _parameter(
                f"{prefix}.survival-min-temperature", "K", 250.0
            ),
            _parameter(
                f"{prefix}.survival-max-temperature", "K", 340.0
            ),
        )

    nodes = tuple(node(name) for name in ("bus", "battery", "payload"))
    return ThermalNetworkConfig(
        nodes,
        (),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _thermal_state() -> ThermalState:
    return ThermalState(
        (
            ThermalNodeState(ThermalNodeId("bus"), 300.0),
            ThermalNodeState(ThermalNodeId("battery"), 295.0),
            ThermalNodeState(ThermalNodeId("payload"), 290.0),
        )
    )


def _spacecraft_configuration(
    configuration_id: str = "reference-optical"
) -> SpacecraftConfiguration:
    battery = BatteryConfig(
        SubsystemConfigurationId("battery"),
        _parameter("eps.battery.nominal-energy", "Wh", 120.0),
        _parameter("eps.battery.charge-efficiency", "1", 0.90),
        _parameter("eps.battery.discharge-efficiency", "1", 0.90),
        _parameter("eps.battery.max-charge-input-power", "W", 50.0),
        _parameter("eps.battery.max-discharge-output-power", "W", 50.0),
    )
    solar = SolarArrayConfig(
        SubsystemConfigurationId("solar-array"),
        _parameter("eps.solar-array.nominal-generation", "W", 240.0),
    )
    return SpacecraftConfiguration(
        SpacecraftConfigurationId(configuration_id),
        "Synthetic Optical Reference",
        1,
        EPSConfig(SubsystemConfigurationId("eps"), battery, solar),
        PayloadConfig(
            SubsystemConfigurationId("payload"),
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC, PayloadMode.MULTISPECTRAL),
            _optical_acquisition(),
        ),
        StorageConfig(
            SubsystemConfigurationId("storage"),
            _parameter("storage.usable-capacity", "GB", 80.0),
        ),
        CommunicationsConfig(
            SubsystemConfigurationId("communications"),
            _parameter(
                "communications.nominal-downlink-data-rate",
                "bit/s",
                1_000_000.0,
            ),
        ),
        ADCSConfig(SubsystemConfigurationId("adcs"), _agile_pointing()),
        ThermalConfig(
            SubsystemConfigurationId("thermal"),
            _thermal_network(),
        ),
        DegradationConfig(
            SubsystemConfigurationId("degradation"),
            _parameter(
                "degradation.battery.initial-usable-capacity-retention",
                "1",
                1.0,
            ),
            _parameter(
                "degradation.solar.initial-generation-retention", "1", 1.0
            ),
            _parameter(
                "degradation.battery.initial-energy-throughput", "Wh", 0.0
            ),
            _zero_damage_ageing_model(),
        ),
        PropulsionConfig(
            SubsystemConfigurationId("propulsion"),
            _parameter("propulsion.initial-delta-v", "m/s", 12.0),
        ),
        OBCConfig(SubsystemConfigurationId("obc")),
    )


def _input_values() -> dict[str, object]:
    spacecraft = _spacecraft_configuration()
    numerical = NumericalConfig(
        NumericalConfigId("primary-step"), 60, 15, 300
    )
    environment = EnvironmentConfig(EnvironmentId("level1-environment"))
    flight_rules = FlightRulesConfig(
        FlightRulesId("primary-flight-rules")
    )
    scenario = ScenarioConfig(ScenarioId("nominal-world"))
    world = CommonWorld(
        WorldId("world-0001"),
        scenario.scenario_id,
        600,
        (WorldEventId("event-0001"),),
    )
    manifest = ModelManifest(
        ModelManifestId("manifest-0001"),
        1,
        spacecraft.configuration_id,
        numerical.configuration_id,
        environment.environment_id,
        flight_rules.flight_rules_id,
        scenario.scenario_id,
        world.world_id,
        ControllerId("rolling-horizon"),
    )
    return {
        "spacecraft_configuration": spacecraft,
        "numerical_config": numerical,
        "environment_config": environment,
        "flight_rules_config": flight_rules,
        "scenario_config": scenario,
        "common_world": world,
        "model_manifest": manifest,
    }


def _inputs(**changes) -> SimulationInputs:
    values = _input_values()
    values.update(changes)
    return SimulationInputs(**values)


def _context(**changes) -> SimulationContext:
    default_inputs = _inputs()
    inputs = changes.pop("inputs", default_inputs)
    controller_id = (
        inputs.model_manifest.controller_id
        if type(inputs) is SimulationInputs
        else default_inputs.model_manifest.controller_id
    )
    onboard = OnboardOperationsState(
        OperationalMode.STANDBY,
        FDIRState.NORMAL,
        PlanId("plan-0001"),
        AuthorityId("ground-authority-0001"),
        90,
        80,
    )
    telemetry = TelemetrySnapshot(
        TelemetrySnapshotId("snapshot-0001"),
        90,
        100,
        110.0,
        11.0,
        OperationalMode.STANDBY,
    )
    values = {
        "simulation_time_seconds": 120,
        "inputs": inputs,
        "spacecraft_state": SpacecraftState(
            BatteryState(110.0),
            PropulsionState(11.0),
            _thermal_state(),
            DegradationState(
                BatteryDegradationState(1.0, 0.0),
                SolarDegradationState(1.0),
            ),
            onboard,
            DataStorageState(()),
        ),
        "ground_knowledge_state": GroundKnowledgeState(
            telemetry,
            (WorldEventId("event-0001"),),
        ),
        "ground_data_delivery_state": GroundDataDeliveryState((), ()),
        "mission_state": MissionState(
            (MissionRequestId("request-0001"),),
            (MissionRequestId("request-0002"),),
            (DataProductId("product-0001"),),
            PlanId("plan-0001"),
            (CommandId("command-0001"),),
            (WorldEventId("event-0001"),),
        ),
        "controller_state": ControllerState(
            controller_id,
            PlanId("plan-0001"),
            2,
        ),
        "diagnostics": Diagnostics(2),
    }
    values.update(changes)
    return SimulationContext(**values)


def _checkpoint() -> CheckpointState:
    return CheckpointState.from_context(_context())


def test_new_controlled_input_id_prefixes() -> None:
    assert NumericalConfigId("primary-step").canonical == (
        "numerical-config:primary-step"
    )
    assert EnvironmentId("level1-environment").canonical == (
        "environment:level1-environment"
    )
    assert FlightRulesId("primary-flight-rules").canonical == (
        "flight-rules:primary-flight-rules"
    )
    assert ScenarioId("nominal-world").canonical == "scenario:nominal-world"


def test_numerical_config_accepts_valid_completed_step_policy() -> None:
    configuration = NumericalConfig(
        NumericalConfigId("primary-step"), 60, 15, 300
    )

    assert configuration.geometry_sample_seconds <= configuration.timestep_seconds
    assert configuration.checkpoint_interval_seconds % 60 == 0
    assert not hasattr(configuration, "__dict__")
    with pytest.raises(FrozenInstanceError):
        configuration.timestep_seconds = 30


def test_numerical_config_rejects_wrong_identity_type() -> None:
    with pytest.raises(TypeError):
        NumericalConfig(EnvironmentId("wrong-id"), 60, 15, 300)


@pytest.mark.parametrize(
    "field_name",
    (
        "timestep_seconds",
        "geometry_sample_seconds",
        "checkpoint_interval_seconds",
    ),
)
def test_numerical_config_requires_positive_exact_integers(field_name) -> None:
    values = {
        "configuration_id": NumericalConfigId("primary-step"),
        "timestep_seconds": 60,
        "geometry_sample_seconds": 15,
        "checkpoint_interval_seconds": 300,
    }
    for invalid in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            NumericalConfig(**{**values, field_name: invalid})
    for invalid in (0, -1):
        with pytest.raises(ValueError):
            NumericalConfig(**{**values, field_name: invalid})


def test_numerical_config_rejects_invalid_cadence_relationships() -> None:
    config_id = NumericalConfigId("primary-step")
    with pytest.raises(ValueError):
        NumericalConfig(config_id, 60, 61, 300)
    with pytest.raises(ValueError):
        NumericalConfig(config_id, 60, 15, 30)
    with pytest.raises(ValueError):
        NumericalConfig(config_id, 60, 15, 310)


@pytest.mark.parametrize(
    "config_type,id_type,field_name,value",
    (
        (
            EnvironmentConfig,
            EnvironmentId,
            "environment_id",
            "level1-environment",
        ),
        (
            FlightRulesConfig,
            FlightRulesId,
            "flight_rules_id",
            "primary-flight-rules",
        ),
        (ScenarioConfig, ScenarioId, "scenario_id", "nominal-world"),
    ),
)
def test_identity_only_configs_are_typed_frozen_and_slotted(
    config_type,
    id_type,
    field_name,
    value,
) -> None:
    configuration = config_type(id_type(value))

    assert type(getattr(configuration, field_name)) is id_type
    assert not hasattr(configuration, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(configuration, field_name, id_type("replacement"))
    with pytest.raises(TypeError):
        config_type(ParameterId("wrong-id"))


def test_common_world_accepts_empty_and_populated_horizons() -> None:
    empty = CommonWorld(
        WorldId("world-empty"), ScenarioId("nominal-world"), 0, ()
    )
    events = (WorldEventId("event-0001"), WorldEventId("event-0002"))
    populated = CommonWorld(
        WorldId("world-full"), ScenarioId("nominal-world"), 600, events
    )

    assert empty.horizon_seconds == 0
    assert populated.event_ids is events
    assert not hasattr(populated, "__dict__")
    with pytest.raises(FrozenInstanceError):
        populated.horizon_seconds = 700


def test_common_world_validates_identity_horizon_and_events() -> None:
    world_id = WorldId("world-0001")
    scenario_id = ScenarioId("nominal-world")
    event_id = WorldEventId("event-0001")
    with pytest.raises(TypeError):
        CommonWorld(ScenarioId("wrong-world"), scenario_id, 0, ())
    with pytest.raises(TypeError):
        CommonWorld(world_id, WorldId("wrong-scenario"), 0, ())
    for value in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            CommonWorld(world_id, scenario_id, value, ())
    with pytest.raises(ValueError):
        CommonWorld(world_id, scenario_id, -1, ())
    with pytest.raises(TypeError):
        CommonWorld(world_id, scenario_id, 0, [event_id])
    with pytest.raises(TypeError):
        CommonWorld(world_id, scenario_id, 0, (PlanId("wrong-event"),))
    with pytest.raises(ValueError):
        CommonWorld(world_id, scenario_id, 0, (event_id, event_id))


def test_model_manifest_accepts_complete_typed_identity_record() -> None:
    manifest = _inputs().model_manifest

    assert manifest.schema_version == 1
    assert not hasattr(manifest, "__dict__")
    with pytest.raises(FrozenInstanceError):
        manifest.schema_version = 2


@pytest.mark.parametrize(
    "field_name",
    (
        "manifest_id",
        "spacecraft_configuration_id",
        "numerical_config_id",
        "environment_id",
        "flight_rules_id",
        "scenario_id",
        "world_id",
        "controller_id",
    ),
)
def test_model_manifest_rejects_every_wrong_id_type(field_name) -> None:
    manifest = _inputs().model_manifest
    with pytest.raises(TypeError):
        replace(manifest, **{field_name: ParameterId("wrong-id")})


@pytest.mark.parametrize("schema_version", (0, -1))
def test_model_manifest_rejects_nonpositive_schema(schema_version) -> None:
    with pytest.raises(ValueError):
        replace(_inputs().model_manifest, schema_version=schema_version)


@pytest.mark.parametrize("schema_version", (True, 1.0, "1"))
def test_model_manifest_rejects_noninteger_schema(schema_version) -> None:
    with pytest.raises(TypeError):
        replace(_inputs().model_manifest, schema_version=schema_version)


def test_simulation_inputs_accepts_one_coherent_deeply_immutable_bundle() -> None:
    inputs = _inputs()

    assert inputs.model_manifest.world_id == inputs.common_world.world_id
    assert not hasattr(inputs, "__dict__")
    with pytest.raises(FrozenInstanceError):
        inputs.common_world = replace(
            inputs.common_world, world_id=WorldId("replacement-world")
        )
    with pytest.raises(FrozenInstanceError):
        inputs.numerical_config.timestep_seconds = 30


@pytest.mark.parametrize(
    "field_name",
    (
        "spacecraft_configuration",
        "numerical_config",
        "environment_config",
        "flight_rules_config",
        "scenario_config",
        "common_world",
        "model_manifest",
    ),
)
def test_simulation_inputs_rejects_every_wrong_nested_type(field_name) -> None:
    with pytest.raises(TypeError):
        _inputs(**{field_name: object()})


@pytest.mark.parametrize(
    "manifest_field,replacement_id",
    (
        (
            "spacecraft_configuration_id",
            SpacecraftConfigurationId("wrong-spacecraft"),
        ),
        ("numerical_config_id", NumericalConfigId("wrong-numerical")),
        ("environment_id", EnvironmentId("wrong-environment")),
        ("flight_rules_id", FlightRulesId("wrong-flight-rules")),
        ("scenario_id", ScenarioId("wrong-scenario")),
        ("world_id", WorldId("wrong-world")),
    ),
)
def test_simulation_inputs_rejects_each_manifest_identity_mismatch(
    manifest_field,
    replacement_id,
) -> None:
    manifest = replace(
        _input_values()["model_manifest"],
        **{manifest_field: replacement_id},
    )
    with pytest.raises(ValueError):
        _inputs(model_manifest=manifest)


def test_simulation_inputs_rejects_world_scenario_mismatch() -> None:
    world = replace(
        _input_values()["common_world"],
        scenario_id=ScenarioId("wrong-scenario"),
    )
    with pytest.raises(ValueError):
        _inputs(common_world=world)


def test_simulation_context_owns_exact_completed_step_domains() -> None:
    context = _context()

    assert tuple(field.name for field in fields(SimulationContext)) == (
        "simulation_time_seconds",
        "inputs",
        "spacecraft_state",
        "ground_knowledge_state",
        "ground_data_delivery_state",
        "mission_state",
        "controller_state",
        "diagnostics",
    )
    assert not hasattr(context, "__dict__")
    context.simulation_time_seconds = 121
    assert context.simulation_time_seconds == 121


@pytest.mark.parametrize(
    "field_name",
    (
        "inputs",
        "spacecraft_state",
        "ground_knowledge_state",
        "ground_data_delivery_state",
        "mission_state",
        "controller_state",
        "diagnostics",
    ),
)
def test_simulation_context_rejects_every_wrong_nested_type(field_name) -> None:
    with pytest.raises(TypeError):
        _context(**{field_name: object()})


def test_simulation_context_validates_time_horizon_and_controller() -> None:
    with pytest.raises(ValueError):
        _context(simulation_time_seconds=-1)
    for value in (True, 1.0, "1"):
        with pytest.raises(TypeError):
            _context(simulation_time_seconds=value)
    with pytest.raises(ValueError):
        _context(simulation_time_seconds=601)
    with pytest.raises(ValueError):
        _context(
            controller_state=ControllerState(
                ControllerId("wrong-controller"), None, 0
            )
        )


@pytest.mark.parametrize(
    "timestamp_field",
    (
        "last_qualifying_contact_time_seconds",
        "critical_energy_since_seconds",
    ),
)
def test_context_allows_equal_and_rejects_future_onboard_time(
    timestamp_field,
) -> None:
    equal_state = _context().spacecraft_state
    setattr(equal_state.onboard, timestamp_field, 120)
    assert _context(spacecraft_state=equal_state)

    future_state = _context().spacecraft_state
    setattr(future_state.onboard, timestamp_field, 121)
    with pytest.raises(ValueError):
        _context(spacecraft_state=future_state)


def test_context_allows_equal_and_rejects_future_telemetry_time() -> None:
    equal = _context().ground_knowledge_state
    equal.latest_telemetry = replace(
        equal.latest_telemetry,
        sampled_at_seconds=120,
        received_at_seconds=120,
    )
    assert _context(ground_knowledge_state=equal)

    future_receipt = _context().ground_knowledge_state
    future_receipt.latest_telemetry = replace(
        future_receipt.latest_telemetry,
        received_at_seconds=121,
    )
    with pytest.raises(ValueError):
        _context(ground_knowledge_state=future_receipt)

    future_sample = _context().ground_knowledge_state
    future_sample.latest_telemetry = replace(
        future_sample.latest_telemetry,
        sampled_at_seconds=121,
        received_at_seconds=121,
    )
    with pytest.raises(ValueError):
        _context(ground_knowledge_state=future_sample)


def test_snapshot_types_capture_restore_and_are_frozen_slotted() -> None:
    context = _context()
    cases = (
        (
            SpacecraftStateSnapshot.from_state(context.spacecraft_state),
            context.spacecraft_state,
        ),
        (
            DataStorageStateSnapshot.from_state(
                context.spacecraft_state.data_storage
            ),
            context.spacecraft_state.data_storage,
        ),
        (
            GroundKnowledgeSnapshot.from_state(
                context.ground_knowledge_state
            ),
            context.ground_knowledge_state,
        ),
        (
            GroundDataDeliveryStateSnapshot.from_state(
                context.ground_data_delivery_state
            ),
            context.ground_data_delivery_state,
        ),
        (MissionStateSnapshot.from_state(context.mission_state), context.mission_state),
        (
            ControllerStateSnapshot.from_state(context.controller_state),
            context.controller_state,
        ),
        (DiagnosticsSnapshot.from_state(context.diagnostics), context.diagnostics),
    )
    for snapshot, original in cases:
        restored = snapshot.restore()
        assert restored == original
        assert restored is not original
        assert not hasattr(snapshot, "__dict__")
        assert snapshot.__dataclass_params__.frozen


def test_spacecraft_snapshot_restores_fresh_nested_state() -> None:
    original = _context().spacecraft_state
    restored = SpacecraftStateSnapshot.from_state(original).restore()

    assert restored.battery is not original.battery
    assert restored.propulsion is not original.propulsion
    assert restored.thermal is not original.thermal
    assert all(
        restored_node is not original_node
        for restored_node, original_node in zip(
            restored.thermal.node_states,
            original.thermal.node_states,
        )
    )
    assert restored.onboard is not original.onboard
    assert restored.data_storage is not original.data_storage


def test_snapshot_creation_rejects_corrupted_mutable_state() -> None:
    context = _context()
    context.spacecraft_state.battery.energy_wh = -1.0
    with pytest.raises(ValueError):
        SpacecraftStateSnapshot.from_state(context.spacecraft_state)

    mission = _context().mission_state
    request_id = MissionRequestId("request-duplicate")
    mission.pending_request_ids = (request_id, request_id)
    with pytest.raises(ValueError):
        MissionStateSnapshot.from_state(mission)

    diagnostics = Diagnostics(0)
    diagnostics.completed_steps = -1
    with pytest.raises(ValueError):
        DiagnosticsSnapshot.from_state(diagnostics)


def test_checkpoint_from_context_captures_all_state_and_input_ids() -> None:
    context = _context()
    checkpoint = CheckpointState.from_context(context)
    manifest = context.inputs.model_manifest

    assert checkpoint.schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION
    assert checkpoint.simulation_time_seconds == context.simulation_time_seconds
    assert checkpoint.model_manifest_id == manifest.manifest_id
    assert checkpoint.spacecraft_configuration_id == (
        manifest.spacecraft_configuration_id
    )
    assert checkpoint.diagnostics.completed_steps == 2
    assert not hasattr(checkpoint, "__dict__")
    with pytest.raises(FrozenInstanceError):
        checkpoint.simulation_time_seconds = 180


def test_checkpoint_accepts_only_the_current_schema_version() -> None:
    checkpoint = _checkpoint()

    assert checkpoint.schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION
    with pytest.raises(ValueError, match="unsupported checkpoint schema_version"):
        replace(checkpoint, schema_version=1)
    with pytest.raises(TypeError, match="schema_version must be an integer"):
        replace(checkpoint, schema_version=True)


def _assert_no_mutable_containers(value: object) -> None:
    assert not isinstance(value, (list, dict, set))
    if isinstance(value, tuple):
        for item in value:
            _assert_no_mutable_containers(item)
    elif is_dataclass(value) and not isinstance(value, type):
        assert value.__dataclass_params__.frozen
        for field in fields(value):
            _assert_no_mutable_containers(getattr(value, field.name))


def test_checkpoint_graph_is_deeply_immutable_without_mutable_containers() -> None:
    _assert_no_mutable_containers(_checkpoint())


def test_checkpoint_restore_is_value_equivalent_and_mutably_independent() -> None:
    original = _context()
    checkpoint = CheckpointState.from_context(original)
    restored = checkpoint.restore(original.inputs)

    assert restored == original
    assert restored is not original
    for field_name in (
        "spacecraft_state",
        "ground_knowledge_state",
        "ground_data_delivery_state",
        "mission_state",
        "controller_state",
        "diagnostics",
    ):
        assert getattr(restored, field_name) is not getattr(original, field_name)
    assert restored.spacecraft_state.battery is not original.spacecraft_state.battery
    assert restored.spacecraft_state.propulsion is not (
        original.spacecraft_state.propulsion
    )
    assert restored.spacecraft_state.onboard is not original.spacecraft_state.onboard


def test_checkpoint_is_independent_of_original_and_restored_mutation() -> None:
    original = _context()
    checkpoint = CheckpointState.from_context(original)
    restored = checkpoint.restore(original.inputs)

    original.spacecraft_state.battery.energy_wh = 1.0
    original.mission_state.pending_request_ids = ()
    restored.spacecraft_state.battery.energy_wh = 2.0
    restored.controller_state.replan_count = 99

    assert checkpoint.spacecraft.battery_energy_wh == 110.0
    assert checkpoint.mission.pending_request_ids == (
        MissionRequestId("request-0001"),
    )
    assert checkpoint.controller.replan_count == 2
    assert original.spacecraft_state.battery.energy_wh == 1.0


def _coherent_alternate_inputs(kind: str) -> SimulationInputs:
    values = _input_values()
    manifest = values["model_manifest"]
    assert type(manifest) is ModelManifest
    if kind == "model_manifest":
        values["model_manifest"] = replace(
            manifest, manifest_id=ModelManifestId("manifest-0002")
        )
    elif kind == "spacecraft_configuration":
        spacecraft = _spacecraft_configuration("alternate-optical")
        values["spacecraft_configuration"] = spacecraft
        values["model_manifest"] = replace(
            manifest, spacecraft_configuration_id=spacecraft.configuration_id
        )
    elif kind == "numerical_config":
        numerical = replace(
            values["numerical_config"],
            configuration_id=NumericalConfigId("alternate-step"),
        )
        values["numerical_config"] = numerical
        values["model_manifest"] = replace(
            manifest, numerical_config_id=numerical.configuration_id
        )
    elif kind == "environment":
        environment = EnvironmentConfig(EnvironmentId("alternate-environment"))
        values["environment_config"] = environment
        values["model_manifest"] = replace(
            manifest, environment_id=environment.environment_id
        )
    elif kind == "flight_rules":
        flight_rules = FlightRulesConfig(FlightRulesId("alternate-rules"))
        values["flight_rules_config"] = flight_rules
        values["model_manifest"] = replace(
            manifest, flight_rules_id=flight_rules.flight_rules_id
        )
    elif kind == "scenario":
        scenario = ScenarioConfig(ScenarioId("alternate-scenario"))
        world = replace(values["common_world"], scenario_id=scenario.scenario_id)
        values["scenario_config"] = scenario
        values["common_world"] = world
        values["model_manifest"] = replace(
            manifest, scenario_id=scenario.scenario_id
        )
    elif kind == "world":
        world = replace(values["common_world"], world_id=WorldId("world-0002"))
        values["common_world"] = world
        values["model_manifest"] = replace(manifest, world_id=world.world_id)
    else:
        values["model_manifest"] = replace(
            manifest, controller_id=ControllerId("alternate-controller")
        )
    return SimulationInputs(**values)


@pytest.mark.parametrize(
    "kind",
    (
        "model_manifest",
        "spacecraft_configuration",
        "numerical_config",
        "environment",
        "flight_rules",
        "scenario",
        "world",
        "controller",
    ),
)
def test_checkpoint_restore_rejects_each_immutable_identity_mismatch(kind) -> None:
    with pytest.raises(ValueError):
        _checkpoint().restore(_coherent_alternate_inputs(kind))


def test_checkpoint_dictionary_is_json_safe_canonical_and_deterministic() -> None:
    checkpoint = _checkpoint()
    first = checkpoint.to_dict()
    second = CheckpointState.from_context(_context()).to_dict()

    assert json.loads(json.dumps(first, sort_keys=True)) == first
    assert first == second
    assert first["input_ids"]["world_id"] == "world:world-0001"
    assert first["spacecraft"]["operational_mode"] == "standby"
    assert first["spacecraft"]["fdir_state"] == "normal"
    assert type(first["mission"]["pending_request_ids"]) is list
    assert type(first["ground_knowledge"]["known_world_event_ids"]) is list


def test_checkpoint_dictionary_round_trips_exactly() -> None:
    checkpoint = _checkpoint()

    assert CheckpointState.from_dict(checkpoint.to_dict()) == checkpoint


@pytest.mark.parametrize("schema_version", (0, -1, 1, 2, 3, 4, 999))
def test_checkpoint_parser_rejects_unsupported_schema_versions(
    schema_version,
) -> None:
    payload = _checkpoint().to_dict()
    payload["schema_version"] = schema_version

    with pytest.raises(ValueError, match="unsupported checkpoint schema_version"):
        CheckpointState.from_dict(payload)


def test_checkpoint_parser_rejects_non_dict_missing_and_extra_top_keys() -> None:
    with pytest.raises(TypeError):
        CheckpointState.from_dict([])
    payload = _checkpoint().to_dict()
    missing = deepcopy(payload)
    del missing["mission"]
    with pytest.raises(ValueError):
        CheckpointState.from_dict(missing)
    extra = deepcopy(payload)
    extra["unexpected"] = None
    with pytest.raises(ValueError):
        CheckpointState.from_dict(extra)


@pytest.mark.parametrize(
    "section,key",
    (
        ("input_ids", "world_id"),
        ("spacecraft", "operational_mode"),
        ("ground_knowledge", "known_world_event_ids"),
        ("mission", "command_ids"),
        ("controller", "replan_count"),
        ("diagnostics", "completed_steps"),
    ),
)
def test_checkpoint_parser_rejects_missing_and_extra_nested_keys(
    section,
    key,
) -> None:
    payload = _checkpoint().to_dict()
    missing = deepcopy(payload)
    del missing[section][key]
    with pytest.raises(ValueError):
        CheckpointState.from_dict(missing)
    extra = deepcopy(payload)
    extra[section]["unexpected"] = None
    with pytest.raises(ValueError):
        CheckpointState.from_dict(extra)


def test_checkpoint_parser_rejects_wrong_prefix_and_malformed_enum() -> None:
    payload = _checkpoint().to_dict()
    payload["input_ids"]["world_id"] = "scenario:world-0001"
    with pytest.raises(ValueError):
        CheckpointState.from_dict(payload)

    payload = _checkpoint().to_dict()
    payload["spacecraft"]["operational_mode"] = "not-a-mode"
    with pytest.raises(ValueError):
        CheckpointState.from_dict(payload)


@pytest.mark.parametrize(
    "path,value",
    (
        (("schema_version",), True),
        (("simulation_time_seconds",), "120"),
        (("spacecraft", "battery_energy_wh"), "110"),
        (("controller", "replan_count"), True),
        (("diagnostics", "completed_steps"), 1.0),
    ),
)
def test_checkpoint_parser_rejects_wrong_scalar_types(path, value) -> None:
    payload = _checkpoint().to_dict()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises((TypeError, ValueError)):
        CheckpointState.from_dict(payload)


def test_checkpoint_parser_requires_lists_for_tuple_collections() -> None:
    payload = _checkpoint().to_dict()
    payload["mission"]["pending_request_ids"] = tuple(
        payload["mission"]["pending_request_ids"]
    )
    with pytest.raises(TypeError):
        CheckpointState.from_dict(payload)


def test_checkpoint_parser_rejects_duplicate_and_overlapping_request_ids() -> None:
    payload = _checkpoint().to_dict()
    request = payload["mission"]["pending_request_ids"][0]
    payload["mission"]["pending_request_ids"] = [request, request]
    with pytest.raises(ValueError):
        CheckpointState.from_dict(payload)

    payload = _checkpoint().to_dict()
    payload["mission"]["completed_request_ids"] = list(
        payload["mission"]["pending_request_ids"]
    )
    with pytest.raises(ValueError):
        CheckpointState.from_dict(payload)


def test_checkpoint_parser_rejects_malformed_telemetry() -> None:
    payload = _checkpoint().to_dict()
    del payload["ground_knowledge"]["latest_telemetry"]["snapshot_id"]
    with pytest.raises(ValueError):
        CheckpointState.from_dict(payload)

    payload = _checkpoint().to_dict()
    payload["ground_knowledge"]["latest_telemetry"][
        "sampled_at_seconds"
    ] = True
    with pytest.raises(TypeError):
        CheckpointState.from_dict(payload)


def test_checkpoint_from_context_rejects_corrupted_runtime_context() -> None:
    context = _context()
    context.mission_state.command_ids = [CommandId("command-0001")]
    with pytest.raises(TypeError):
        CheckpointState.from_context(context)


def test_new_controlled_and_checkpoint_dataclasses_have_no_defaults() -> None:
    dataclass_types = (
        NumericalConfig,
        EnvironmentConfig,
        FlightRulesConfig,
        ScenarioConfig,
        CommonWorld,
        ModelManifest,
        SimulationInputs,
        SimulationContext,
        ThermalNodeStateSnapshot,
        ThermalStateSnapshot,
        DataStorageStateSnapshot,
        SpacecraftStateSnapshot,
        GroundKnowledgeSnapshot,
        GroundDataDeliveryStateSnapshot,
        MissionStateSnapshot,
        ControllerStateSnapshot,
        DiagnosticsSnapshot,
        CheckpointState,
    )
    for dataclass_type in dataclass_types:
        for field in fields(dataclass_type):
            if dataclass_type is SimulationInputs and field.name == "coast_orbit":
                # B2 preserves the original seven positional required fields.
                assert field.default is None
                assert field.kw_only is True
            else:
                assert field.default is MISSING
            assert field.default_factory is MISSING


def test_b4_modules_have_no_legacy_or_opaque_identity_references() -> None:
    forbidden_names = {
        "DEFAULT_CONFIG",
        "Simulator",
        "SatelliteState",
    }
    for path in B4_MODULE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden_names
            if isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_names
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"id", "hash"}


def test_b4_modules_define_explicit_exports() -> None:
    from ops_sim.v5 import checkpoint, context, manifest, run_config, world

    assert run_config.__all__ == [
        "EnvironmentConfig",
        "FlightRulesConfig",
        "NumericalConfig",
        "ScenarioConfig",
    ]
    assert world.__all__ == ["CommonWorld"]
    assert manifest.__all__ == ["ModelManifest"]
    assert context.__all__ == ["SimulationInputs", "SimulationContext"]
    assert checkpoint.__all__ == [
        "BatteryDegradationStateSnapshot",
        "CURRENT_CHECKPOINT_SCHEMA_VERSION",
        "CheckpointState",
        "ControllerStateSnapshot",
        "DataStorageStateSnapshot",
        "DiagnosticsSnapshot",
        "DegradationStateSnapshot",
        "GroundDataDeliveryStateSnapshot",
        "GroundKnowledgeSnapshot",
        "MissionStateSnapshot",
        "SpacecraftStateSnapshot",
        "SolarDegradationStateSnapshot",
        "ThermalNodeStateSnapshot",
        "ThermalStateSnapshot",
    ]
