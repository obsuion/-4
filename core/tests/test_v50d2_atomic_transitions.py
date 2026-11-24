"""Focused tests for V5.0D2 half-open transactional transitions."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.checkpoint import CheckpointState
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
from ops_sim.v5.engine import (
    STEP_PHASE_ORDER,
    SimulationEngine,
    SimulationPhase,
    StepInterval,
    StepResult,
)
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
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"


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


def _spacecraft_configuration() -> SpacecraftConfiguration:
    return SpacecraftConfiguration(
        SpacecraftConfigurationId("reference-optical"),
        "Synthetic Optical Reference",
        1,
        EPSConfig(
            SubsystemConfigurationId("eps"),
            BatteryConfig(
                SubsystemConfigurationId("battery"),
                _parameter("eps.battery.nominal-energy", "Wh", 120.0),
                _parameter("eps.battery.charge-efficiency", "1", 0.90),
                _parameter("eps.battery.discharge-efficiency", "1", 0.90),
                _parameter(
                    "eps.battery.max-charge-input-power",
                    "W",
                    50.0,
                ),
                _parameter(
                    "eps.battery.max-discharge-output-power",
                    "W",
                    50.0,
                ),
            ),
            SolarArrayConfig(
                SubsystemConfigurationId("solar-array"),
                _parameter(
                    "eps.solar-array.nominal-generation",
                    "W",
                    240.0,
                ),
            ),
        ),
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
            SubsystemConfigurationId("propulsion"),
            _parameter("propulsion.initial-delta-v", "m/s", 12.0),
        ),
        OBCConfig(SubsystemConfigurationId("obc")),
    )


def _inputs(dt_seconds: int, horizon_seconds: int) -> SimulationInputs:
    spacecraft = _spacecraft_configuration()
    numerical = NumericalConfig(
        NumericalConfigId(f"step-{dt_seconds}"),
        dt_seconds,
        1,
        dt_seconds,
    )
    environment = EnvironmentConfig(EnvironmentId("level1-environment"))
    flight_rules = FlightRulesConfig(
        FlightRulesId("primary-flight-rules")
    )
    scenario = ScenarioConfig(ScenarioId("nominal-world"))
    world = CommonWorld(
        WorldId("world-0001"),
        scenario.scenario_id,
        horizon_seconds,
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
    dt_seconds: int = 60,
    horizon_seconds: int = 600,
    simulation_time_seconds: int = 0,
) -> SimulationContext:
    inputs = _inputs(dt_seconds, horizon_seconds)
    return SimulationContext(
        simulation_time_seconds,
        inputs,
        SpacecraftState(
            BatteryState(110.0),
            PropulsionState(11.0),
            _thermal_state(),
            DegradationState(
                BatteryDegradationState(1.0, 0.0),
                SolarDegradationState(1.0),
            ),
            OnboardOperationsState(
                OperationalMode.STANDBY,
                FDIRState.NORMAL,
                PlanId("plan-0001"),
                AuthorityId("ground-authority-0001"),
                0,
                0,
            ),
            DataStorageState(()),
        ),
        GroundKnowledgeState(
            TelemetrySnapshot(
                TelemetrySnapshotId("snapshot-0001"),
                0,
                0,
                110.0,
                11.0,
                OperationalMode.STANDBY,
            ),
            (WorldEventId("event-0001"),),
        ),
        GroundDataDeliveryState((), ()),
        MissionState(
            (MissionRequestId("request-0001"),),
            (MissionRequestId("request-0002"),),
            (DataProductId("product-0001"),),
            PlanId("plan-0001"),
            (CommandId("command-0001"),),
            (WorldEventId("event-0001"),),
        ),
        ControllerState(
            inputs.model_manifest.controller_id,
            PlanId("plan-0001"),
            2,
        ),
        Diagnostics(0),
    )


def _mutable_domain_references(
    context: SimulationContext,
) -> tuple[object, ...]:
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


def _assert_unchanged(
    context: SimulationContext,
    checkpoint: CheckpointState,
    references: tuple[object, ...],
) -> None:
    assert CheckpointState.from_context(context) == checkpoint
    assert _mutable_domain_references(context) == references
    assert all(
        current is original
        for current, original in zip(
            _mutable_domain_references(context),
            references,
        )
    )


def test_step_interval_is_frozen_slotted_and_derives_duration() -> None:
    interval = StepInterval(100, 200)

    assert tuple(field.name for field in fields(StepInterval)) == (
        "start_time_seconds",
        "end_time_seconds",
    )
    assert interval.dt_seconds == 100
    assert not hasattr(interval, "__dict__")
    with pytest.raises(FrozenInstanceError):
        interval.start_time_seconds = 101


@pytest.mark.parametrize("field_name", ("start_time_seconds", "end_time_seconds"))
@pytest.mark.parametrize("invalid", (True, 1.5, "1"))
def test_step_interval_rejects_noninteger_boundaries(
    field_name,
    invalid,
) -> None:
    values = {"start_time_seconds": 0, "end_time_seconds": 1}

    with pytest.raises(TypeError):
        StepInterval(**{**values, field_name: invalid})


def test_step_interval_accepts_zero_start_and_rejects_invalid_order() -> None:
    assert StepInterval(0, 1).start_time_seconds == 0
    with pytest.raises(ValueError):
        StepInterval(-1, 1)
    with pytest.raises(ValueError):
        StepInterval(1, 1)
    with pytest.raises(ValueError):
        StepInterval(2, 1)


@pytest.mark.parametrize(
    "timestamp_seconds,expected",
    ((100, True), (101, True), (199, True), (200, False), (201, False)),
)
def test_step_interval_contains_uses_half_open_boundaries(
    timestamp_seconds,
    expected,
) -> None:
    assert StepInterval(100, 200).contains(timestamp_seconds) is expected


def test_step_interval_contains_supports_zero_and_rejects_invalid_values() -> None:
    interval = StepInterval(0, 7)

    assert interval.contains(0)
    assert not interval.contains(7)
    for invalid in (True, 1.5, "1"):
        with pytest.raises(TypeError):
            interval.contains(invalid)
    with pytest.raises(ValueError):
        interval.contains(-1)


def test_step_result_fields_remain_compatible_and_interval_is_derived() -> None:
    result = StepResult(100, 200, 100, STEP_PHASE_ORDER)

    assert tuple(field.name for field in fields(StepResult)) == (
        "start_time_seconds",
        "end_time_seconds",
        "dt_seconds",
        "executed_phases",
        "eps_result",
        "thermal_coupling_result",
        "battery_degradation_result",
        "solar_degradation_result",
        "eps_capability_result",
        "battery_capacity_reconciliation_result",
    )
    assert result.eps_result is None
    assert result.thermal_coupling_result is None
    assert result.battery_degradation_result is None
    assert result.solar_degradation_result is None
    assert result.eps_capability_result is None
    assert result.battery_capacity_reconciliation_result is None
    assert result.interval == StepInterval(100, 200)
    assert "interval" not in {field.name for field in fields(StepResult)}


class RecordingEngine(SimulationEngine):
    __slots__ = ("received",)

    def __init__(self) -> None:
        self.received: list[tuple[SimulationPhase, StepInterval]] = []

    def _record(
        self,
        phase: SimulationPhase,
        interval: StepInterval,
    ) -> None:
        self.received.append((phase, interval))

    def _world_environment(self, context, interval) -> None:
        self._record(SimulationPhase.WORLD_ENVIRONMENT, interval)
        super()._world_environment(context, interval)

    def _knowledge_update(self, context, interval) -> None:
        self._record(SimulationPhase.KNOWLEDGE_UPDATE, interval)
        super()._knowledge_update(context, interval)

    def _planning(self, context, interval) -> None:
        self._record(SimulationPhase.PLANNING, interval)
        super()._planning(context, interval)

    def _onboard_arbitration(self, context, interval) -> None:
        self._record(SimulationPhase.ONBOARD_ARBITRATION, interval)
        super()._onboard_arbitration(context, interval)

    def _action_execution(self, context, interval) -> None:
        self._record(SimulationPhase.ACTION_EXECUTION, interval)
        super()._action_execution(context, interval)

    def _physical_integration(self, context, interval, eps_inputs) -> None:
        self._record(SimulationPhase.PHYSICAL_INTEGRATION, interval)
        return super()._physical_integration(context, interval, eps_inputs)

    def _failure_capability_resolution(self, context, interval) -> None:
        self._record(SimulationPhase.FAILURE_CAPABILITY_RESOLUTION, interval)
        super()._failure_capability_resolution(context, interval)

    def _diagnostics(self, context, interval) -> None:
        self._record(SimulationPhase.DIAGNOSTICS, interval)
        super()._diagnostics(context, interval)

    def _advance_clock(self, context, interval) -> None:
        self._record(SimulationPhase.ADVANCE_CLOCK, interval)
        super()._advance_clock(context, interval)


def test_all_phases_receive_one_identical_interval_in_canonical_order() -> None:
    engine = RecordingEngine()

    result = engine.step(_context(dt_seconds=7, horizon_seconds=7))

    assert tuple(phase for phase, _ in engine.received) == STEP_PHASE_ORDER
    first_interval = engine.received[0][1]
    assert all(interval is first_interval for _, interval in engine.received)
    assert first_interval == StepInterval(0, 7)
    assert result.interval == first_interval


def test_successful_step_commits_fresh_domains_and_preserves_inputs() -> None:
    context = _context()
    original_context = context
    original_inputs = context.inputs
    original_references = _mutable_domain_references(context)
    spacecraft_before = deepcopy(context.spacecraft_state)
    knowledge_before = deepcopy(context.ground_knowledge_state)
    mission_before = deepcopy(context.mission_state)
    controller_before = deepcopy(context.controller_state)

    result = SimulationEngine().step(context)

    assert context is original_context
    assert context.inputs is original_inputs
    assert all(
        current is not original
        for current, original in zip(
            _mutable_domain_references(context),
            original_references,
        )
    )
    assert context.spacecraft_state == spacecraft_before
    assert context.ground_knowledge_state == knowledge_before
    assert context.mission_state == mission_before
    assert context.controller_state == controller_before
    assert context.simulation_time_seconds == 60
    assert context.diagnostics.completed_steps == 1
    assert result.interval == StepInterval(0, 60)
    checkpoint = CheckpointState.from_context(context)
    assert checkpoint.restore(context.inputs) == context


class FailingPhysicalEngine(SimulationEngine):
    def _physical_integration(self, context, interval, eps_inputs) -> None:
        context.spacecraft_state.battery.energy_wh = 1.0
        context.mission_state.pending_request_ids = ()
        context.controller_state.replan_count = 99
        context.diagnostics.completed_steps = 99
        raise RuntimeError("synthetic phase failure")


class FailingPlanningEngine(SimulationEngine):
    def _planning(self, context, interval) -> None:
        context.mission_state.completed_request_ids = ()
        raise RuntimeError("synthetic planning failure")


@pytest.mark.parametrize("engine_type", (FailingPhysicalEngine, FailingPlanningEngine))
def test_phase_exception_propagates_and_rolls_back_every_domain(
    engine_type,
) -> None:
    context = _context()
    checkpoint = CheckpointState.from_context(context)
    references = _mutable_domain_references(context)
    inputs = context.inputs

    with pytest.raises(RuntimeError, match="synthetic"):
        engine_type().step(context)

    _assert_unchanged(context, checkpoint, references)
    assert context.inputs is inputs


class InvalidBatteryEngine(SimulationEngine):
    def _physical_integration(self, context, interval, eps_inputs) -> None:
        context.spacecraft_state.battery.energy_wh = -1.0


class InvalidMissionEngine(SimulationEngine):
    def _action_execution(self, context, interval) -> None:
        context.mission_state.command_ids = [CommandId("command-0001")]


class InvalidControllerEngine(SimulationEngine):
    def _planning(self, context, interval) -> None:
        context.controller_state.replan_count = -1


@pytest.mark.parametrize(
    "engine_type",
    (InvalidBatteryEngine, InvalidMissionEngine, InvalidControllerEngine),
)
def test_invalid_post_step_state_is_rejected_without_commit(engine_type) -> None:
    context = _context()
    checkpoint = CheckpointState.from_context(context)
    references = _mutable_domain_references(context)

    with pytest.raises((TypeError, ValueError)):
        engine_type().step(context)

    _assert_unchanged(context, checkpoint, references)


def test_invalid_original_context_fails_before_transaction_or_commit() -> None:
    context = _context()
    context.spacecraft_state.battery.energy_wh = -1.0
    before = deepcopy(context)
    references = _mutable_domain_references(context)
    engine = RecordingEngine()

    with pytest.raises(ValueError):
        engine.step(context)

    assert context == before
    assert all(
        current is original
        for current, original in zip(
            _mutable_domain_references(context),
            references,
        )
    )
    assert engine.received == []


def test_horizon_rejection_occurs_before_any_phase_execution() -> None:
    context = _context(
        dt_seconds=20,
        horizon_seconds=60,
        simulation_time_seconds=50,
    )
    checkpoint = CheckpointState.from_context(context)
    references = _mutable_domain_references(context)
    engine = RecordingEngine()

    with pytest.raises(ValueError, match="cross the common-world horizon"):
        engine.step(context)

    assert engine.received == []
    _assert_unchanged(context, checkpoint, references)


def test_transactional_continuation_matches_direct_execution() -> None:
    initial = _context(dt_seconds=7, horizon_seconds=35)
    checkpoint = CheckpointState.from_context(initial)
    direct = checkpoint.restore(initial.inputs)
    split = checkpoint.restore(initial.inputs)
    engine = SimulationEngine()

    for _ in range(5):
        engine.step(direct)
    for _ in range(2):
        engine.step(split)
    split = CheckpointState.from_context(split).restore(split.inputs)
    for _ in range(3):
        engine.step(split)

    assert split == direct


def test_repeated_unusual_steps_return_adjacent_half_open_intervals() -> None:
    context = _context(dt_seconds=7, horizon_seconds=35)
    engine = SimulationEngine()

    intervals = tuple(engine.step(context).interval for _ in range(5))

    assert intervals == (
        StepInterval(0, 7),
        StepInterval(7, 14),
        StepInterval(14, 21),
        StepInterval(21, 28),
        StepInterval(28, 35),
    )
    assert context.simulation_time_seconds == 35
    assert context.diagnostics.completed_steps == 5


def test_engine_transaction_path_uses_checkpoint_without_opaque_copying() -> None:
    tree = ast.parse(
        ENGINE_PATH.read_text(encoding="utf-8"),
        filename=str(ENGINE_PATH),
    )
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }

    assert "CheckpointState" in imported_names
    assert "deepcopy" not in imported_names
    assert {"from_context", "restore"} <= called_attributes
    assert SimulationEngine.__slots__ == ()


def test_engine_retains_structural_restrictions_outside_physical_phase() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    forbidden_names = {"DEFAULT_CONFIG", "Simulator", "SatelliteState"}
    forbidden_modules = {"random", "policies", "scenarios"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_names
        if isinstance(node, ast.Import):
            assert all(
                alias.name.partition(".")[0] not in forbidden_modules
                for alias in node.names
            )
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").partition(".")[0] not in (
                forbidden_modules
            )
        if isinstance(node, ast.Constant) and type(node.value) is int:
            assert node.value != 3600

    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in (
        "_world_environment",
        "_knowledge_update",
        "_planning",
        "_onboard_arbitration",
        "_action_execution",
        "_failure_capability_resolution",
    ):
        assert not any(
            isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
            for node in ast.walk(functions[name])
        )
