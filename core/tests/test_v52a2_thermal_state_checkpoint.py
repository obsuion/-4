"""Focused tests for V5.2A2 thermal truth and checkpoint integration."""

import ast
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, replace
import json
from pathlib import Path

import numpy as np
import pytest

from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
    DataStorageStateSnapshot,
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
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import (
    ADCSSlewAnchorId,
    AuthorityId,
    ControllerId,
    EnvironmentId,
    FlightRulesId,
    ModelManifestId,
    NumericalConfigId,
    ParameterId,
    PlanId,
    ScenarioId,
    SpacecraftConfigurationId,
    SubsystemConfigurationId,
    TelemetrySnapshotId,
    ThermalNodeId,
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
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
A2_PRODUCTION_PATHS = tuple(
    ROOT / "ops_sim" / "v5" / name
    for name in (
        "configuration.py",
        "state.py",
        "context.py",
        "checkpoint.py",
        "engine.py",
    )
)
BASELINE_NODE_NAMES = ("bus", "battery", "payload")
FOUR_NODE_NAMES = (*BASELINE_NODE_NAMES, "radiator")
DEFAULT_TEMPERATURES = {
    "bus": 300.0,
    "battery": 295.0,
    "payload": 290.0,
    "radiator": 280.0,
}


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
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


def _node_config(node_name: str) -> ThermalNodeConfig:
    prefix = f"thermal.node.{node_name}"
    return ThermalNodeConfig(
        ThermalNodeId(node_name),
        _parameter(f"{prefix}.heat-capacity", "J/K", 1000.0),
        _parameter(f"{prefix}.emissivity", "1", 0.8),
        _parameter(f"{prefix}.radiating-area", "m^2", 1.0),
        _parameter(f"{prefix}.operating-min-temperature", "K", 270.0),
        _parameter(f"{prefix}.operating-max-temperature", "K", 320.0),
        _parameter(f"{prefix}.survival-min-temperature", "K", 250.0),
        _parameter(f"{prefix}.survival-max-temperature", "K", 340.0),
    )


def _thermal_network(
    node_names: tuple[str, ...] = BASELINE_NODE_NAMES,
) -> ThermalNetworkConfig:
    return ThermalNetworkConfig(
        tuple(_node_config(name) for name in node_names),
        (),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _thermal_state(
    node_names: tuple[str, ...] = BASELINE_NODE_NAMES,
    *,
    temperatures: dict[str, object] | None = None,
) -> ThermalState:
    values = {**DEFAULT_TEMPERATURES, **(temperatures or {})}
    return ThermalState(
        tuple(
            ThermalNodeState(ThermalNodeId(name), values.get(name, 285.0))
            for name in node_names
        )
    )


def _spacecraft_configuration(
    node_names: tuple[str, ...] = BASELINE_NODE_NAMES,
) -> SpacecraftConfiguration:
    return SpacecraftConfiguration(
        SpacecraftConfigurationId("thermal-state-optical"),
        "Synthetic Thermal-State Optical Reference",
        1,
        EPSConfig(
            SubsystemConfigurationId("eps-thermal-state"),
            BatteryConfig(
                SubsystemConfigurationId("battery-thermal-state"),
                _parameter("eps.battery.nominal-energy", "Wh", 120.0),
                _parameter("eps.battery.charge-efficiency", "1", 0.9),
                _parameter("eps.battery.discharge-efficiency", "1", 0.9),
                _parameter(
                    "eps.battery.max-charge-input-power", "W", 50.0
                ),
                _parameter(
                    "eps.battery.max-discharge-output-power", "W", 50.0
                ),
            ),
            SolarArrayConfig(
                SubsystemConfigurationId("solar-thermal-state"),
                _parameter(
                    "eps.solar-array.nominal-generation", "W", 240.0
                ),
            ),
        ),
        PayloadConfig(
            SubsystemConfigurationId("payload-thermal-state"),
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC, PayloadMode.MULTISPECTRAL),
            _optical_acquisition(),
        ),
        StorageConfig(
            SubsystemConfigurationId("storage-thermal-state"),
            _parameter("storage.usable-capacity", "GB", 80.0),
        ),
        CommunicationsConfig(
            SubsystemConfigurationId("communications-thermal-state"),
            _parameter(
                "communications.nominal-downlink-data-rate",
                "bit/s",
                1_000_000.0,
            ),
        ),
        ADCSConfig(
            SubsystemConfigurationId("adcs-thermal-state"), _agile_pointing()
        ),
        ThermalConfig(
            SubsystemConfigurationId("thermal-state"),
            _thermal_network(node_names),
        ),
        DegradationConfig(
            SubsystemConfigurationId("degradation-thermal-state"),
            _parameter(
                "degradation.battery.initial-usable-capacity-retention",
                "1", 1.0,
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
            SubsystemConfigurationId("propulsion-thermal-state"),
            _parameter("propulsion.initial-delta-v", "m/s", 12.0),
        ),
        OBCConfig(SubsystemConfigurationId("obc-thermal-state")),
    )


def _inputs(
    node_names: tuple[str, ...] = BASELINE_NODE_NAMES,
    *,
    dt_seconds: int = 60,
    horizon_seconds: int = 600,
) -> SimulationInputs:
    spacecraft = _spacecraft_configuration(node_names)
    numerical = NumericalConfig(
        NumericalConfigId(f"thermal-step-{dt_seconds}"),
        dt_seconds,
        1,
        dt_seconds,
    )
    environment = EnvironmentConfig(EnvironmentId("thermal-environment"))
    flight_rules = FlightRulesConfig(FlightRulesId("thermal-flight-rules"))
    scenario = ScenarioConfig(ScenarioId("thermal-scenario"))
    world = CommonWorld(
        WorldId("thermal-world"),
        scenario.scenario_id,
        horizon_seconds,
        (),
    )
    manifest = ModelManifest(
        ModelManifestId("thermal-manifest"),
        1,
        spacecraft.configuration_id,
        numerical.configuration_id,
        environment.environment_id,
        flight_rules.flight_rules_id,
        scenario.scenario_id,
        world.world_id,
        ControllerId("thermal-controller"),
    )
    return SimulationInputs(
        spacecraft,
        numerical,
        environment,
        flight_rules,
        scenario,
        world,
        manifest,
    )


def _context(
    *,
    configured_node_names: tuple[str, ...] = BASELINE_NODE_NAMES,
    runtime_node_names: tuple[str, ...] | None = None,
    temperatures: dict[str, object] | None = None,
    battery_energy_wh: object = 110.0,
    propulsion_delta_v: object = 11.0,
    telemetry_battery_energy_wh: object = 110.0,
    telemetry_delta_v: object = 11.0,
    dt_seconds: int = 60,
    horizon_seconds: int = 600,
) -> SimulationContext:
    inputs = _inputs(
        configured_node_names,
        dt_seconds=dt_seconds,
        horizon_seconds=horizon_seconds,
    )
    return SimulationContext(
        0,
        inputs,
        SpacecraftState(
            BatteryState(battery_energy_wh),
            PropulsionState(propulsion_delta_v),
            _thermal_state(
                configured_node_names
                if runtime_node_names is None
                else runtime_node_names,
                temperatures=temperatures,
            ),
            DegradationState(
                BatteryDegradationState(1.0, 0.0),
                SolarDegradationState(1.0),
            ),
            OnboardOperationsState(
                OperationalMode.STANDBY,
                FDIRState.NORMAL,
                PlanId("thermal-plan"),
                AuthorityId("thermal-authority"),
                0,
                None,
            ),
            DataStorageState(()),
        ),
        GroundKnowledgeState(
            TelemetrySnapshot(
                TelemetrySnapshotId("thermal-telemetry"),
                0,
                0,
                telemetry_battery_energy_wh,
                telemetry_delta_v,
                OperationalMode.STANDBY,
            ),
            (),
        ),
        GroundDataDeliveryState((), ()),
        MissionState((), (), (), PlanId("thermal-plan"), (), ()),
        ControllerState(
            inputs.model_manifest.controller_id,
            PlanId("thermal-plan"),
            0,
        ),
        Diagnostics(0),
    )


def _reconstruct(context: SimulationContext) -> SimulationContext:
    return SimulationContext(
        context.simulation_time_seconds,
        context.inputs,
        context.spacecraft_state,
        context.ground_knowledge_state,
        context.ground_data_delivery_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _mutable_references(context: SimulationContext) -> tuple[object, ...]:
    return (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.propulsion,
        context.spacecraft_state.thermal,
        *context.spacecraft_state.thermal.node_states,
        context.spacecraft_state.onboard,
        context.spacecraft_state.data_storage,
        context.ground_knowledge_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def test_thermal_config_binds_one_required_exact_network() -> None:
    network = _thermal_network()
    configuration = ThermalConfig(
        SubsystemConfigurationId("thermal-state"), network
    )

    assert tuple(field.name for field in fields(ThermalConfig)) == (
        "configuration_id",
        "network",
    )
    assert configuration.network is network
    assert not hasattr(configuration, "__dict__")
    assert isinstance(hash(configuration), int)
    for field in fields(ThermalConfig):
        assert field.default is MISSING
        assert field.default_factory is MISSING
    with pytest.raises(FrozenInstanceError):
        configuration.network = _thermal_network()
    with pytest.raises(TypeError):
        ThermalConfig(SubsystemConfigurationId("thermal-state"))
    with pytest.raises(TypeError, match="ThermalNetworkConfig"):
        ThermalConfig(SubsystemConfigurationId("thermal-state"), object())


@pytest.mark.parametrize(
    "temperature",
    (1, 1.5, np.int64(300), np.float64(300.5)),
)
def test_thermal_node_state_accepts_positive_finite_reals(
    temperature,
) -> None:
    state = ThermalNodeState(ThermalNodeId("bus"), temperature)

    assert tuple(field.name for field in fields(ThermalNodeState)) == (
        "node_id",
        "temperature_k",
    )
    assert state.temperature_k is temperature
    assert not hasattr(state, "__dict__")
    assert not ThermalNodeState.__dataclass_params__.frozen
    state.temperature_k = 301.0
    assert state.temperature_k == 301.0


@pytest.mark.parametrize(
    ("temperature", "error_type"),
    (
        (0, ValueError),
        (-0.001, ValueError),
        (True, TypeError),
        ("300", TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (float("-inf"), ValueError),
    ),
)
def test_thermal_node_state_rejects_invalid_temperature(
    temperature,
    error_type,
) -> None:
    with pytest.raises(error_type):
        ThermalNodeState(ThermalNodeId("bus"), temperature)


def test_thermal_node_state_requires_exact_identity_and_no_defaults() -> None:
    with pytest.raises(TypeError, match="ThermalNodeId"):
        ThermalNodeState(ParameterId("bus"), 300.0)
    for field in fields(ThermalNodeState):
        assert field.default is MISSING
        assert field.default_factory is MISSING


def test_thermal_state_is_generic_mutable_slotted_and_required() -> None:
    node_states = (
        ThermalNodeState(ThermalNodeId("bus"), 300.0),
        ThermalNodeState(ThermalNodeId("radiator"), 280.0),
    )
    state = ThermalState(node_states)

    assert tuple(field.name for field in fields(ThermalState)) == (
        "node_states",
    )
    assert state.node_states is node_states
    assert not hasattr(state, "__dict__")
    assert not ThermalState.__dataclass_params__.frozen
    field = fields(ThermalState)[0]
    assert field.default is MISSING
    assert field.default_factory is MISSING


def test_thermal_state_validates_collection_members_and_unique_ids() -> None:
    node = ThermalNodeState(ThermalNodeId("bus"), 300.0)
    with pytest.raises(TypeError, match="tuple"):
        ThermalState([node])
    with pytest.raises(ValueError, match="empty"):
        ThermalState(())
    with pytest.raises(TypeError, match="ThermalNodeState"):
        ThermalState((object(),))
    with pytest.raises(ValueError, match="unique"):
        ThermalState((node, ThermalNodeState(ThermalNodeId("bus"), 301.0)))


@pytest.mark.parametrize(
    ("field_name", "invalid", "error_type"),
    (
        ("temperature_k", 0.0, ValueError),
        ("temperature_k", float("nan"), ValueError),
        ("node_id", ParameterId("bus"), TypeError),
    ),
)
def test_thermal_state_revalidates_mutated_node_values(
    field_name,
    invalid,
    error_type,
) -> None:
    node = ThermalNodeState(ThermalNodeId("bus"), 300.0)
    setattr(node, field_name, invalid)

    with pytest.raises(error_type):
        ThermalState((node,))


def test_spacecraft_state_requires_exact_thermal_state() -> None:
    spacecraft = _context().spacecraft_state

    assert tuple(field.name for field in fields(SpacecraftState)) == (
        "battery",
        "propulsion",
        "thermal",
        "degradation",
        "onboard",
        "data_storage",
    )
    assert type(spacecraft.thermal) is ThermalState
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(SpacecraftState)
    )
    with pytest.raises(TypeError, match="thermal"):
        SpacecraftState(
            spacecraft.battery,
            spacecraft.propulsion,
            object(),
            spacecraft.degradation,
            spacecraft.onboard,
            spacecraft.data_storage,
        )


def test_context_matches_runtime_nodes_by_set_not_tuple_order() -> None:
    reordered = ("payload", "bus", "battery")
    context = _context(runtime_node_names=reordered)

    assert tuple(
        node.node_id.value for node in context.spacecraft_state.thermal.node_states
    ) == reordered


@pytest.mark.parametrize(
    "runtime_names",
    (
        ("bus", "battery"),
        ("bus", "battery", "payload", "radiator"),
        ("bus", "battery", "unknown"),
    ),
    ids=("missing", "extra", "wrong-identity"),
)
def test_context_rejects_runtime_node_set_mismatch(runtime_names) -> None:
    with pytest.raises(ValueError, match="thermal node IDs"):
        _context(runtime_node_names=runtime_names)


@pytest.mark.parametrize(
    "temperature",
    (300.0, 260.0, 350.0, 240.0),
    ids=(
        "inside-operating",
        "outside-operating-inside-survival",
        "above-survival",
        "below-survival-positive",
    ),
)
def test_context_accepts_positive_temperature_outside_configured_limits(
    temperature,
) -> None:
    context = _context(temperatures={"bus": temperature})

    assert context.spacecraft_state.thermal.node_states[0].temperature_k == (
        temperature
    )


@pytest.mark.parametrize(
    ("field_name", "invalid", "error_type"),
    (
        ("temperature_k", 0.0, ValueError),
        ("temperature_k", -1.0, ValueError),
        ("temperature_k", True, TypeError),
        ("temperature_k", float("nan"), ValueError),
        ("temperature_k", float("inf"), ValueError),
        ("node_id", ParameterId("bus"), TypeError),
        ("node_id", ThermalNodeId("unconfigured"), ValueError),
    ),
)
def test_context_revalidates_mutated_thermal_node(
    field_name,
    invalid,
    error_type,
) -> None:
    context = _context()
    setattr(context.spacecraft_state.thermal.node_states[0], field_name, invalid)

    with pytest.raises(error_type):
        _reconstruct(context)


class RecordingEngine(SimulationEngine):
    __slots__ = ("phases",)

    def __init__(self) -> None:
        self.phases = []

    def _execute_phase(self, phase, context, interval, eps_inputs):
        self.phases.append(phase)
        return super()._execute_phase(phase, context, interval, eps_inputs)


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    (
        ("temperature_k", float("nan")),
        ("temperature_k", 0.0),
        ("node_id", ThermalNodeId("unconfigured")),
    ),
)
def test_engine_rejects_corrupted_thermal_truth_before_phases_atomically(
    field_name,
    invalid,
) -> None:
    context = _context()
    node = context.spacecraft_state.thermal.node_states[0]
    setattr(node, field_name, invalid)
    references = _mutable_references(context)
    corrupted_temperature = node.temperature_k
    corrupted_node_id = node.node_id
    battery_before = context.spacecraft_state.battery.energy_wh
    propulsion_before = context.spacecraft_state.propulsion.delta_v_remaining_m_per_s
    knowledge_before = deepcopy(context.ground_knowledge_state)
    mission_before = deepcopy(context.mission_state)
    controller_before = deepcopy(context.controller_state)
    engine = RecordingEngine()

    with pytest.raises((TypeError, ValueError)):
        engine.step(context)

    assert engine.phases == []
    assert context.simulation_time_seconds == 0
    assert context.diagnostics.completed_steps == 0
    assert context.spacecraft_state.battery.energy_wh == battery_before
    assert context.spacecraft_state.propulsion.delta_v_remaining_m_per_s == (
        propulsion_before
    )
    assert node.temperature_k is corrupted_temperature
    assert node.node_id is corrupted_node_id
    assert context.ground_knowledge_state == knowledge_before
    assert context.mission_state == mission_before
    assert context.controller_state == controller_before
    assert all(
        current is original
        for current, original in zip(_mutable_references(context), references)
    )


def test_valid_engine_step_does_not_evolve_thermal_temperature() -> None:
    context = _context()
    before = tuple(
        (node.node_id, node.temperature_k)
        for node in context.spacecraft_state.thermal.node_states
    )

    SimulationEngine().step(context)

    after = tuple(
        (node.node_id, node.temperature_k)
        for node in context.spacecraft_state.thermal.node_states
    )
    assert after == before
    assert context.simulation_time_seconds == 60
    assert context.diagnostics.completed_steps == 1


def test_thermal_snapshot_structure_capture_and_fresh_restore() -> None:
    original = _context(
        configured_node_names=FOUR_NODE_NAMES,
    ).spacecraft_state.thermal
    snapshot = ThermalStateSnapshot.from_state(original)
    restored = snapshot.restore()

    assert tuple(field.name for field in fields(ThermalNodeStateSnapshot)) == (
        "node_id",
        "temperature_k",
    )
    assert tuple(field.name for field in fields(ThermalStateSnapshot)) == (
        "node_states",
    )
    assert snapshot.__dataclass_params__.frozen
    assert not hasattr(snapshot, "__dict__")
    assert restored == original
    assert restored is not original
    assert all(
        restored_node is not original_node
        for restored_node, original_node in zip(
            restored.node_states,
            original.node_states,
        )
    )
    assert tuple(node.node_id.value for node in restored.node_states) == (
        FOUR_NODE_NAMES
    )


def test_current_checkpoint_has_explicit_deterministic_thermal_payload() -> None:
    context = _context()
    checkpoint = CheckpointState.from_context(context)
    payload = checkpoint.to_dict()

    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    assert checkpoint.schema_version == 5
    assert payload["schema_version"] == 5
    assert payload["spacecraft"]["thermal"] == {
        "nodes": [
            {"node_id": "thermal-node:bus", "temperature_k": 300.0},
            {"node_id": "thermal-node:battery", "temperature_k": 295.0},
            {"node_id": "thermal-node:payload", "temperature_k": 290.0},
        ]
    }
    assert CheckpointState.from_dict(payload) == checkpoint
    assert CheckpointState.from_dict(payload).restore(context.inputs) == context


def test_schema_one_is_rejected_without_inventing_thermal_truth() -> None:
    payload = CheckpointState.from_context(_context()).to_dict()
    payload["schema_version"] = 1
    del payload["spacecraft"]["thermal"]

    with pytest.raises(ValueError, match="unsupported checkpoint schema_version"):
        CheckpointState.from_dict(payload)


def test_checkpoint_parser_rejects_missing_or_malformed_thermal_payload() -> None:
    payload = CheckpointState.from_context(_context()).to_dict()
    del payload["spacecraft"]["thermal"]
    with pytest.raises(ValueError, match="missing"):
        CheckpointState.from_dict(payload)

    payload = CheckpointState.from_context(_context()).to_dict()
    payload["spacecraft"]["thermal"]["nodes"] = tuple(
        payload["spacecraft"]["thermal"]["nodes"]
    )
    with pytest.raises(TypeError, match="must be a list"):
        CheckpointState.from_dict(payload)

    payload = CheckpointState.from_context(_context()).to_dict()
    del payload["spacecraft"]["thermal"]["nodes"][0]["temperature_k"]
    with pytest.raises(ValueError, match="missing"):
        CheckpointState.from_dict(payload)

    payload = CheckpointState.from_context(_context()).to_dict()
    payload["spacecraft"]["thermal"]["nodes"][0]["temperature_k"] = 0.0
    with pytest.raises(ValueError, match="temperature_k"):
        CheckpointState.from_dict(payload)


def test_checkpoint_parser_rejects_duplicate_thermal_node_ids() -> None:
    payload = CheckpointState.from_context(_context()).to_dict()
    duplicate = dict(payload["spacecraft"]["thermal"]["nodes"][0])
    payload["spacecraft"]["thermal"]["nodes"].append(duplicate)

    with pytest.raises(ValueError, match="unique"):
        CheckpointState.from_dict(payload)


@pytest.mark.parametrize("mutation", ("missing", "extra", "renamed"))
def test_checkpoint_restore_enforces_active_thermal_network(mutation) -> None:
    context = _context()
    checkpoint = CheckpointState.from_context(context)
    node_states = checkpoint.spacecraft.thermal.node_states
    if mutation == "missing":
        replacement_nodes = node_states[:-1]
    elif mutation == "extra":
        replacement_nodes = (
            *node_states,
            ThermalNodeStateSnapshot(ThermalNodeId("radiator"), 280.0),
        )
    else:
        replacement_nodes = (
            replace(node_states[0], node_id=ThermalNodeId("renamed")),
            *node_states[1:],
        )
    invalid = replace(
        checkpoint,
        spacecraft=replace(
            checkpoint.spacecraft,
            thermal=ThermalStateSnapshot(replacement_nodes),
        ),
    )

    with pytest.raises(ValueError, match="thermal node IDs"):
        invalid.restore(context.inputs)


@pytest.mark.parametrize("use_numpy", (False, True))
def test_checkpoint_json_round_trip_normalizes_all_physical_reals(
    use_numpy,
) -> None:
    if use_numpy:
        context = _context(
            temperatures={
                "bus": np.int64(300),
                "battery": np.float64(295.5),
                "payload": np.int64(290),
            },
            battery_energy_wh=np.int64(110),
            propulsion_delta_v=np.float64(11.5),
            telemetry_battery_energy_wh=np.int64(109),
            telemetry_delta_v=np.float64(11.25),
        )
    else:
        context = _context()
    checkpoint = CheckpointState.from_context(context)
    payload = checkpoint.to_dict()
    encoded = json.dumps(payload, sort_keys=True)
    decoded = json.loads(encoded)
    restored_checkpoint = CheckpointState.from_dict(decoded)
    restored = restored_checkpoint.restore(context.inputs)

    assert type(payload["spacecraft"]["battery_energy_wh"]) in {int, float}
    assert type(payload["spacecraft"]["delta_v_remaining_m_per_s"]) in {
        int,
        float,
    }
    telemetry = payload["ground_knowledge"]["latest_telemetry"]
    assert type(telemetry["battery_energy_wh"]) in {int, float}
    assert type(telemetry["delta_v_remaining_m_per_s"]) in {int, float}
    assert all(
        type(node["temperature_k"]) in {int, float}
        for node in payload["spacecraft"]["thermal"]["nodes"]
    )
    assert tuple(
        (node.node_id, node.temperature_k)
        for node in restored.spacecraft_state.thermal.node_states
    ) == tuple(
        (node.node_id, node.temperature_k)
        for node in context.spacecraft_state.thermal.node_states
    )
    assert restored.spacecraft_state.battery.energy_wh == (
        context.spacecraft_state.battery.energy_wh
    )
    assert restored.spacecraft_state.propulsion.delta_v_remaining_m_per_s == (
        context.spacecraft_state.propulsion.delta_v_remaining_m_per_s
    )


def test_checkpoint_restore_creates_fresh_complete_runtime_graph() -> None:
    original = _context(configured_node_names=FOUR_NODE_NAMES)
    checkpoint = CheckpointState.from_context(original)
    restored = checkpoint.restore(original.inputs)

    assert restored.spacecraft_state is not original.spacecraft_state
    assert restored.spacecraft_state.battery is not original.spacecraft_state.battery
    assert restored.spacecraft_state.propulsion is not (
        original.spacecraft_state.propulsion
    )
    assert restored.spacecraft_state.thermal is not original.spacecraft_state.thermal
    assert restored.spacecraft_state.onboard is not original.spacecraft_state.onboard
    assert restored.spacecraft_state.data_storage is not (
        original.spacecraft_state.data_storage
    )
    assert all(
        restored_node is not original_node
        for restored_node, original_node in zip(
            restored.spacecraft_state.thermal.node_states,
            original.spacecraft_state.thermal.node_states,
        )
    )

    restored.spacecraft_state.thermal.node_states[0].temperature_k = 999.0
    assert checkpoint.spacecraft.thermal.node_states[0].temperature_k == 300.0
    assert original.spacecraft_state.thermal.node_states[0].temperature_k == 300.0


class FailAfterThermalWorkingMutation(SimulationEngine):
    def _physical_integration(self, context, interval, eps_inputs):
        context.spacecraft_state.thermal.node_states[0].temperature_k = 999.0
        return super()._physical_integration(context, interval, eps_inputs)

    def _failure_capability_resolution(self, context, interval):
        raise RuntimeError("synthetic post-thermal failure")


def test_transaction_rollback_preserves_original_thermal_truth_and_identity() -> None:
    context = _context()
    checkpoint = CheckpointState.from_context(context)
    references = _mutable_references(context)

    with pytest.raises(RuntimeError, match="post-thermal"):
        FailAfterThermalWorkingMutation().step(context)

    assert CheckpointState.from_context(context) == checkpoint
    assert all(
        current is original
        for current, original in zip(_mutable_references(context), references)
    )


def test_thermal_truth_does_not_refresh_ground_telemetry() -> None:
    context = _context()
    telemetry = context.ground_knowledge_state.latest_telemetry
    assert telemetry is not None
    telemetry_before = deepcopy(telemetry)

    context.spacecraft_state.thermal.node_states[0].temperature_k = 330.0
    SimulationEngine().step(context)

    assert context.ground_knowledge_state.latest_telemetry == telemetry_before
    assert not hasattr(context.ground_knowledge_state.latest_telemetry, "thermal")


def test_four_node_context_checkpoint_and_engine_continuation_are_extensible() -> None:
    context = _context(
        configured_node_names=FOUR_NODE_NAMES,
        horizon_seconds=120,
    )
    checkpoint = CheckpointState.from_context(context)
    restored = checkpoint.restore(context.inputs)

    assert tuple(
        node.node_id.value
        for node in restored.spacecraft_state.thermal.node_states
    ) == FOUR_NODE_NAMES
    SimulationEngine().step(restored)
    assert tuple(
        node.temperature_k
        for node in restored.spacecraft_state.thermal.node_states
    ) == (300.0, 295.0, 290.0, 280.0)


def test_a2_production_has_no_thermal_physics_degradation_or_numpy() -> None:
    prohibited_identifiers = {
        "stefan_boltzmann_constant",
        "sigma",
        "heat_flow_w",
        "conductive_heat_flow_w",
        "external_heat_w",
        "internal_heat_w",
        "heater_power_w",
        "thermal_substeps",
        "capacity_fade",
        "solar_retention",
        "activation_energy",
        "cycle_count",
        "health_scalar",
    }
    for path in A2_PRODUCTION_PATHS:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        import_roots = {
            alias.name.partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        identifiers = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }

        assert "numpy" not in import_roots
        assert identifiers.isdisjoint(prohibited_identifiers)
        assert "** 4" not in source


def test_a2_decisions_are_appended_once_and_exports_are_exact() -> None:
    decision_log = DECISION_LOG_PATH.read_text(encoding="utf-8")
    for decision_number in range(85, 91):
        assert decision_log.count(f"## D{decision_number:03d} ") == 1
    assert decision_log.index("## D084 ") < decision_log.index("## D085 ")

    from ops_sim.v5 import checkpoint, state

    assert state.__all__ == [
        "BatteryDegradationState",
        "BatteryState",
        "DataStorageState",
        "DegradationState",
        "FDIRState",
        "OnboardOperationsState",
        "OperationalMode",
        "PropulsionState",
        "SpacecraftState",
        "SolarDegradationState",
        "ThermalNodeState",
        "ThermalState",
    ]
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
