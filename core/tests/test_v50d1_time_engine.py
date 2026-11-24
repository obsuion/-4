"""Focused tests for the stateless V5.0D1 seconds-based engine."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
import subprocess

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
V50D1_COMMIT = "4f6c989011bc33ba879db8567393752e7f33134a"

EXPECTED_PHASE_VALUES = (
    "world-environment",
    "knowledge-update",
    "planning",
    "onboard-arbitration",
    "action-execution",
    "physical-integration",
    "failure-capability-resolution",
    "diagnostics",
    "advance-clock",
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
    completed_steps: int = 0,
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
        Diagnostics(completed_steps),
    )


def test_simulation_phase_values_and_order_are_exact() -> None:
    assert tuple(phase.value for phase in SimulationPhase) == (
        EXPECTED_PHASE_VALUES
    )
    assert STEP_PHASE_ORDER == tuple(SimulationPhase)
    assert len(STEP_PHASE_ORDER) == len(set(STEP_PHASE_ORDER)) == 9
    with pytest.raises(TypeError):
        STEP_PHASE_ORDER[0] = SimulationPhase.PLANNING


def test_engine_is_explicitly_stateless_and_slotted() -> None:
    engine = SimulationEngine()

    assert SimulationEngine.__slots__ == ()
    assert not hasattr(engine, "__dict__")
    with pytest.raises(AttributeError):
        engine.clock = 0
    with pytest.raises(AttributeError):
        engine.step_count = 0


@pytest.mark.parametrize("dt_seconds", (3600, 60, 7))
def test_one_step_uses_the_configured_integer_seconds(dt_seconds) -> None:
    context = _context(dt_seconds=dt_seconds, horizon_seconds=dt_seconds)

    result = SimulationEngine().step(context)

    assert result == StepResult(
        0,
        dt_seconds,
        dt_seconds,
        STEP_PHASE_ORDER,
    )
    assert context.simulation_time_seconds == dt_seconds
    assert context.diagnostics.completed_steps == 1
    assert result.executed_phases == STEP_PHASE_ORDER


def test_d1_step_changes_only_time_and_completed_steps() -> None:
    context = _context()
    inputs = context.inputs
    spacecraft_before = deepcopy(context.spacecraft_state)
    knowledge_before = deepcopy(context.ground_knowledge_state)
    mission_before = deepcopy(context.mission_state)
    controller_before = deepcopy(context.controller_state)

    SimulationEngine().step(context)

    assert context.inputs is inputs
    assert context.spacecraft_state == spacecraft_before
    assert context.ground_knowledge_state == knowledge_before
    assert context.mission_state == mission_before
    assert context.controller_state == controller_before
    assert context.simulation_time_seconds == 60
    assert context.diagnostics.completed_steps == 1


def test_exact_horizon_landing_succeeds_and_next_step_is_atomic() -> None:
    context = _context(dt_seconds=60, horizon_seconds=60)
    engine = SimulationEngine()

    assert engine.step(context).end_time_seconds == 60
    before_rejection = deepcopy(context)
    with pytest.raises(ValueError, match="cross the common-world horizon"):
        engine.step(context)

    assert context == before_rejection


def test_horizon_crossing_is_rejected_without_partial_step() -> None:
    context = _context(
        dt_seconds=20,
        horizon_seconds=60,
        simulation_time_seconds=50,
        completed_steps=3,
    )
    before_rejection = deepcopy(context)

    with pytest.raises(ValueError, match="cross the common-world horizon"):
        SimulationEngine().step(context)

    assert context == before_rejection
    assert context.simulation_time_seconds == 50
    assert context.diagnostics.completed_steps == 3


def _negative_battery(context: SimulationContext) -> None:
    context.spacecraft_state.battery.energy_wh = -1.0


def _negative_propulsion(context: SimulationContext) -> None:
    context.spacecraft_state.propulsion.delta_v_remaining_m_per_s = -1.0


def _malformed_mission(context: SimulationContext) -> None:
    context.mission_state.command_ids = [CommandId("command-0001")]


def _negative_diagnostics(context: SimulationContext) -> None:
    context.diagnostics.completed_steps = -1


def _future_onboard_timestamp(context: SimulationContext) -> None:
    context.spacecraft_state.onboard.critical_energy_since_seconds = 1


def _wrong_controller(context: SimulationContext) -> None:
    context.controller_state.controller_id = ControllerId("wrong-controller")


@pytest.mark.parametrize(
    "corrupt",
    (
        _negative_battery,
        _negative_propulsion,
        _malformed_mission,
        _negative_diagnostics,
        _future_onboard_timestamp,
        _wrong_controller,
    ),
)
def test_pre_step_validation_rejects_corruption_before_any_phase_mutation(
    corrupt,
) -> None:
    context = _context()
    corrupt(context)
    before_rejection = deepcopy(context)

    with pytest.raises((TypeError, ValueError)):
        SimulationEngine().step(context)

    assert context == before_rejection


def test_step_requires_an_exact_simulation_context() -> None:
    with pytest.raises(TypeError, match="context must be a SimulationContext"):
        SimulationEngine().step(object())


def test_every_completed_step_is_checkpoint_valid_and_restorable() -> None:
    context = _context(dt_seconds=7, horizon_seconds=21)
    engine = SimulationEngine()

    for expected_steps in range(1, 4):
        engine.step(context)
        checkpoint = CheckpointState.from_context(context)
        restored = checkpoint.restore(context.inputs)
        assert restored == context
        assert checkpoint.diagnostics.completed_steps == expected_steps


def test_checkpoint_continuation_matches_direct_execution() -> None:
    initial = _context(dt_seconds=7, horizon_seconds=35)
    initial_checkpoint = CheckpointState.from_context(initial)
    direct = initial_checkpoint.restore(initial.inputs)
    split = initial_checkpoint.restore(initial.inputs)
    engine = SimulationEngine()

    for _ in range(5):
        engine.step(direct)
    for _ in range(2):
        engine.step(split)
    split = CheckpointState.from_context(split).restore(split.inputs)
    for _ in range(3):
        engine.step(split)

    assert split == direct


def test_unusual_timestep_runs_exactly_to_horizon() -> None:
    context = _context(dt_seconds=7, horizon_seconds=35)
    engine = SimulationEngine()

    results = [engine.step(context) for _ in range(5)]

    assert [result.end_time_seconds for result in results] == [7, 14, 21, 28, 35]
    assert context.simulation_time_seconds == 35
    assert context.diagnostics.completed_steps == 5
    before_rejection = deepcopy(context)
    with pytest.raises(ValueError):
        engine.step(context)
    assert context == before_rejection


def test_step_result_is_frozen_slotted_and_exact() -> None:
    result = StepResult(10, 17, 7, STEP_PHASE_ORDER)

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
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.dt_seconds = 8


@pytest.mark.parametrize(
    "field_name",
    ("start_time_seconds", "end_time_seconds", "dt_seconds"),
)
@pytest.mark.parametrize("invalid", (True, 1.5, "1"))
def test_step_result_rejects_noninteger_time_values(
    field_name,
    invalid,
) -> None:
    values = {
        "start_time_seconds": 10,
        "end_time_seconds": 17,
        "dt_seconds": 7,
        "executed_phases": STEP_PHASE_ORDER,
    }

    with pytest.raises(TypeError):
        StepResult(**{**values, field_name: invalid})


def test_step_result_rejects_invalid_time_relationships() -> None:
    with pytest.raises(ValueError):
        StepResult(-1, 6, 7, STEP_PHASE_ORDER)
    with pytest.raises(ValueError):
        StepResult(0, 0, 0, STEP_PHASE_ORDER)
    with pytest.raises(ValueError):
        StepResult(7, 0, -7, STEP_PHASE_ORDER)
    with pytest.raises(ValueError):
        StepResult(10, 18, 7, STEP_PHASE_ORDER)


def test_step_result_requires_the_exact_complete_phase_tuple() -> None:
    with pytest.raises(TypeError):
        StepResult(0, 7, 7, list(STEP_PHASE_ORDER))
    with pytest.raises(TypeError):
        StepResult(
            0,
            7,
            7,
            STEP_PHASE_ORDER[:-1] + ("advance-clock",),
        )
    with pytest.raises(ValueError):
        StepResult(0, 7, 7, tuple(reversed(STEP_PHASE_ORDER)))
    with pytest.raises(ValueError):
        StepResult(0, 7, 7, STEP_PHASE_ORDER[:-1])


def test_step_result_is_not_authoritative_runtime_or_checkpoint_state() -> None:
    for domain_type in (SimulationContext, Diagnostics, CheckpointState):
        assert "StepResult" not in {
            str(field.type) for field in fields(domain_type)
        }


def test_engine_source_has_no_legacy_random_or_special_hour_behavior() -> None:
    tree = ast.parse(
        ENGINE_PATH.read_text(encoding="utf-8"),
        filename=str(ENGINE_PATH),
    )
    forbidden_names = {"DEFAULT_CONFIG", "Simulator", "SatelliteState"}
    forbidden_modules = {"policies", "random", "scenarios"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_names
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"id", "hash"}
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


def test_engine_has_tuple_phase_contract_and_no_mutable_phase_registry() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    phase_assignments = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and (
            (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "STEP_PHASE_ORDER"
                    for target in node.targets
                )
            )
            or (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "STEP_PHASE_ORDER"
            )
        )
    ]

    assert len(phase_assignments) == 1
    assert isinstance(phase_assignments[0].value, ast.Tuple)
    assert not any(
        isinstance(node.value, (ast.List, ast.Dict, ast.Set))
        for node in phase_assignments
    )


def test_v50d1_engine_exports_are_historical_and_remain_live() -> None:
    from ops_sim.v5 import engine

    expected_exports = [
        "STEP_PHASE_ORDER",
        "SimulationEngine",
        "SimulationPhase",
        "StepResult",
    ]
    historical_source = subprocess.run(
        ["git", "show", f"{V50D1_COMMIT}:ops_sim/v5/engine.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    historical_tree = ast.parse(historical_source)
    historical_exports = next(
        node
        for node in historical_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )

    assert ast.literal_eval(historical_exports.value) == expected_exports
    assert all(name in engine.__all__ for name in expected_exports)
