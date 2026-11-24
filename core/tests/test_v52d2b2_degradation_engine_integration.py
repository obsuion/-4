"""Transactional degradation evolution integration for V5.2D2B2."""

import ast
from copy import deepcopy
from dataclasses import fields
from inspect import Parameter, signature
import json
from pathlib import Path

import pytest

from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
import ops_sim.v5.engine as engine_module
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
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
from ops_sim.v5.degradation import (
    BatteryDegradationTransition,
    SolarDegradationForcingInput,
    SolarDegradationTransition,
)
from ops_sim.v5.degradation_config import BatteryAgeingModelConfig
from ops_sim.v5.diagnostics import Diagnostics
from ops_sim.v5.engine import STEP_PHASE_ORDER, SimulationEngine, StepResult
from ops_sim.v5.eps_system import EPSIntervalInputs, EPSIntervalResult
from ops_sim.v5.ids import (
    ADCSSlewAnchorId,
    ControllerId,
    EnvironmentId,
    FlightRulesId,
    ModelManifestId,
    NumericalConfigId,
    ParameterId,
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
from ops_sim.v5.power_loads import PowerLoadBreakdown
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
    SolarDegradationState,
    SpacecraftState,
    ThermalNodeState,
    ThermalState,
)
from ops_sim.v5.thermal import (
    ThermalIntervalInputs,
    ThermalNodeBoundaryInput,
)
from ops_sim.v5.thermal_config import ThermalNetworkConfig, ThermalNodeConfig
from ops_sim.v5.thermal_coupling import (
    EPSThermalCouplingResult,
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
)
from ops_sim.v5.world import CommonWorld


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
NODE_NAMES = ("bus", "energy-store", "payload")
RUNTIME_ORDER = ("payload", "bus", "energy-store")
DT_SECONDS = 10


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


def _ageing_model(
    *,
    calendar_rate: object = 0.0,
    cycling_coefficient: object = 0.0,
) -> BatteryAgeingModelConfig:
    return BatteryAgeingModelConfig(
        _parameter(
            "degradation.battery.reference-temperature", "K", 300.0
        ),
        _parameter(
            "degradation.battery.calendar-damage-rate-at-reference",
            "1/s",
            calendar_rate,
        ),
        _parameter(
            "degradation.battery.calendar-activation-energy", "J/mol", 0.0
        ),
        _parameter(
            "degradation.battery.cycling-damage-per-normalized-"
            "throughput-at-reference",
            "1",
            cycling_coefficient,
        ),
        _parameter(
            "degradation.battery.cycling-activation-energy", "J/mol", 0.0
        ),
    )


def _node(name: str) -> ThermalNodeConfig:
    prefix = f"thermal.node.{name}"
    return ThermalNodeConfig(
        ThermalNodeId(name),
        _parameter(f"{prefix}.heat-capacity", "J/K", 1000.0),
        _parameter(f"{prefix}.emissivity", "1", 0.0),
        _parameter(f"{prefix}.radiating-area", "m^2", 1.0),
        _parameter(f"{prefix}.operating-min-temperature", "K", 270.0),
        _parameter(f"{prefix}.operating-max-temperature", "K", 320.0),
        _parameter(f"{prefix}.survival-min-temperature", "K", 250.0),
        _parameter(f"{prefix}.survival-max-temperature", "K", 340.0),
    )


def _network() -> ThermalNetworkConfig:
    return ThermalNetworkConfig(
        tuple(_node(name) for name in NODE_NAMES),
        (),
        ThermalNodeId("bus"),
        ThermalNodeId("energy-store"),
        ThermalNodeId("payload"),
    )


def _spacecraft(ageing_model: BatteryAgeingModelConfig) -> SpacecraftConfiguration:
    return SpacecraftConfiguration(
        SpacecraftConfigurationId("d2b2-optical"),
        "Synthetic D2B2 Optical Reference",
        1,
        EPSConfig(
            SubsystemConfigurationId("d2b2-eps"),
            BatteryConfig(
                SubsystemConfigurationId("d2b2-battery"),
                _parameter("eps.battery.nominal-energy", "Wh", 1000.0),
                _parameter("eps.battery.charge-efficiency", "1", 1.0),
                _parameter("eps.battery.discharge-efficiency", "1", 0.8),
                _parameter(
                    "eps.battery.max-charge-input-power", "W", 100.0
                ),
                _parameter(
                    "eps.battery.max-discharge-output-power", "W", 100.0
                ),
            ),
            SolarArrayConfig(
                SubsystemConfigurationId("d2b2-solar"),
                _parameter(
                    "eps.solar-array.nominal-generation", "W", 100.0
                ),
            ),
        ),
        PayloadConfig(
            SubsystemConfigurationId("d2b2-payload"),
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC,),
            _optical_acquisition(),
        ),
        StorageConfig(
            SubsystemConfigurationId("d2b2-storage"),
            _parameter("storage.usable-capacity", "GB", 10.0),
        ),
        CommunicationsConfig(
            SubsystemConfigurationId("d2b2-comms"),
            _parameter(
                "communications.nominal-downlink-data-rate",
                "bit/s",
                1_000_000.0,
            ),
        ),
        ADCSConfig(
            SubsystemConfigurationId("d2b2-adcs"), _agile_pointing()
        ),
        ThermalConfig(SubsystemConfigurationId("d2b2-thermal"), _network()),
        DegradationConfig(
            SubsystemConfigurationId("d2b2-degradation"),
            _parameter(
                "degradation.battery.initial-usable-capacity-retention",
                "1",
                0.9,
            ),
            _parameter(
                "degradation.solar.initial-generation-retention", "1", 0.8
            ),
            _parameter(
                "degradation.battery.initial-energy-throughput", "Wh", 100.0
            ),
            ageing_model,
        ),
        PropulsionConfig(
            SubsystemConfigurationId("d2b2-propulsion"),
            _parameter("propulsion.initial-delta-v", "m/s", 10.0),
        ),
        OBCConfig(SubsystemConfigurationId("d2b2-obc")),
    )


def _context(
    *,
    calendar_rate: object = 0.0,
    cycling_coefficient: object = 0.0,
) -> SimulationContext:
    spacecraft = _spacecraft(
        _ageing_model(
            calendar_rate=calendar_rate,
            cycling_coefficient=cycling_coefficient,
        )
    )
    numerical = NumericalConfig(
        NumericalConfigId("d2b2-step"), DT_SECONDS, 1, DT_SECONDS
    )
    environment = EnvironmentConfig(EnvironmentId("d2b2-environment"))
    rules = FlightRulesConfig(FlightRulesId("d2b2-rules"))
    scenario = ScenarioConfig(ScenarioId("d2b2-scenario"))
    world = CommonWorld(WorldId("d2b2-world"), scenario.scenario_id, 10_000, ())
    controller_id = ControllerId("d2b2-controller")
    manifest = ModelManifest(
        ModelManifestId("d2b2-manifest"),
        1,
        spacecraft.configuration_id,
        numerical.configuration_id,
        environment.environment_id,
        rules.flight_rules_id,
        scenario.scenario_id,
        world.world_id,
        controller_id,
    )
    inputs = SimulationInputs(
        spacecraft,
        numerical,
        environment,
        rules,
        scenario,
        world,
        manifest,
    )
    temperatures = {"bus": 280.0, "energy-store": 300.0, "payload": 290.0}
    return SimulationContext(
        0,
        inputs,
        SpacecraftState(
            BatteryState(100.0),
            PropulsionState(9.0),
            ThermalState(
                tuple(
                    ThermalNodeState(
                        ThermalNodeId(name), temperatures[name]
                    )
                    for name in RUNTIME_ORDER
                )
            ),
            DegradationState(
                BatteryDegradationState(0.9, 100.0),
                SolarDegradationState(0.8),
            ),
            OnboardOperationsState(
                OperationalMode.STANDBY,
                FDIRState.NORMAL,
                None,
                None,
                None,
                None,
            ),
            DataStorageState(()),
        ),
        GroundKnowledgeState(
            TelemetrySnapshot(
                TelemetrySnapshotId("d2b2-telemetry"),
                0,
                0,
                100.0,
                9.0,
                OperationalMode.STANDBY,
            ),
            (),
        ),
        GroundDataDeliveryState((), ()),
        MissionState((), (), (), None, (), ()),
        ControllerState(controller_id, None, 0),
        Diagnostics(0),
    )


def _eps_inputs() -> EPSIntervalInputs:
    return EPSIntervalInputs(
        False,
        0.0,
        PowerLoadBreakdown(36.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def _thermal_inputs() -> ThermalIntervalInputs:
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(ThermalNodeId(name), 300.0)
            for name in NODE_NAMES
        )
    )


def _heat_sources() -> ThermalHeatSourceInputs:
    return ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(
                ThermalNodeId(name),
                1.0 if name == "energy-store" else 0.0,
                0.0,
                0.0,
                0.0,
            )
            for name in NODE_NAMES
        )
    )


def _coupled_arguments() -> dict[str, object]:
    return {
        "eps_inputs": _eps_inputs(),
        "thermal_inputs": _thermal_inputs(),
        "heat_source_inputs": _heat_sources(),
    }


def _run_steps(context: SimulationContext, start: int, count: int) -> None:
    engine = SimulationEngine()
    for _ in range(start, start + count):
        engine.step(context, **_coupled_arguments())


def _assert_original_references(context, references) -> None:
    actual = (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.thermal,
        *context.spacecraft_state.thermal.node_states,
        context.spacecraft_state.degradation,
        context.spacecraft_state.degradation.battery,
        context.spacecraft_state.degradation.solar,
        context.spacecraft_state.data_storage,
        context.diagnostics,
    )
    assert all(current is original for current, original in zip(actual, references))


def test_public_step_signature_and_step_result_extension_are_compatible() -> None:
    parameters = signature(SimulationEngine.step).parameters
    assert tuple(parameters) == (
        "self",
        "context",
        "eps_inputs",
        "thermal_inputs",
        "heat_source_inputs",
        "solar_degradation_forcing",
    )
    assert parameters["context"].kind is Parameter.POSITIONAL_OR_KEYWORD
    for name in tuple(parameters)[2:]:
        assert parameters[name].kind is Parameter.KEYWORD_ONLY
        assert parameters[name].default is None

    legacy = StepResult(0, 10, 10, STEP_PHASE_ORDER)
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
    assert legacy.battery_degradation_result is None
    assert legacy.solar_degradation_result is None
    assert legacy.eps_capability_result is None
    assert legacy.battery_capacity_reconciliation_result is None
    with pytest.raises(TypeError, match="battery_degradation_result"):
        StepResult(0, 10, 10, STEP_PHASE_ORDER, None, None, object())
    with pytest.raises(TypeError, match="solar_degradation_result"):
        StepResult(0, 10, 10, STEP_PHASE_ORDER, None, None, None, object())


def test_coupled_hand_calculation_uses_configured_battery_role_and_exact_mean() -> None:
    context = _context(calendar_rate=1.0e-6, cycling_coefficient=0.02)
    telemetry_before = context.ground_knowledge_state.latest_telemetry

    result = SimulationEngine().step(context, **_coupled_arguments())

    assert type(result.eps_result) is EPSIntervalResult
    assert type(result.thermal_coupling_result) is EPSThermalCouplingResult
    assert type(result.battery_degradation_result) is BatteryDegradationTransition
    assert result.solar_degradation_result is None
    assert result.eps_result.battery.end_energy_wh == pytest.approx(99.875)
    assert result.eps_result.battery.conversion_loss_wh == pytest.approx(0.025)

    thermal_by_id = {
        item.node_id: item
        for item in result.thermal_coupling_result.thermal_result.node_transitions
    }
    battery_transition = thermal_by_id[ThermalNodeId("energy-store")]
    assert battery_transition.start_temperature_k == 300.0
    assert battery_transition.end_temperature_k == pytest.approx(300.1)

    degradation = result.battery_degradation_result
    expected_throughput_wh = 36.0 * (10 / 3600) / 0.8
    expected_temperature_k = 300.0 + (300.1 - 300.0) / 2
    expected_calendar_damage = 1.0e-6 * 10
    expected_cycling_damage = 0.02 * (expected_throughput_wh / 1000.0)
    expected_total_damage = expected_calendar_damage + expected_cycling_damage
    assert degradation.throughput_increment_wh == pytest.approx(
        expected_throughput_wh
    )
    assert degradation.representative_temperature_k == pytest.approx(
        expected_temperature_k
    )
    assert degradation.calendar_temperature_acceleration == 1.0
    assert degradation.cycling_temperature_acceleration == 1.0
    assert degradation.calendar_damage == pytest.approx(expected_calendar_damage)
    assert degradation.cycling_damage == pytest.approx(expected_cycling_damage)
    assert degradation.total_damage == pytest.approx(expected_total_damage)
    assert degradation.end_cumulative_energy_throughput_wh == pytest.approx(
        100.0 + expected_throughput_wh
    )
    assert degradation.end_usable_capacity_retention == pytest.approx(
        0.9 - expected_total_damage
    )
    assert context.spacecraft_state.degradation.battery == (
        BatteryDegradationState(
            degradation.end_usable_capacity_retention,
            degradation.end_cumulative_energy_throughput_wh,
        )
    )
    assert tuple(
        node.node_id.value for node in context.spacecraft_state.thermal.node_states
    ) == RUNTIME_ORDER
    assert context.spacecraft_state.degradation.solar.generation_retention == 0.8
    assert context.ground_knowledge_state.latest_telemetry is telemetry_before
    assert telemetry_before is not None and telemetry_before.battery_energy_wh == 100.0


def test_pure_calls_are_once_ordered_and_share_active_objects(monkeypatch) -> None:
    context = _context(calendar_rate=1.0e-8, cycling_coefficient=0.001)
    active_spacecraft = context.inputs.spacecraft_configuration
    active_battery = active_spacecraft.eps.battery
    active_ageing = active_spacecraft.degradation.battery_ageing_model
    actual_eps = engine_module.compute_eps_interval_transition
    actual_thermal = engine_module.compute_eps_thermal_interval_transition
    actual_throughput = engine_module.compute_battery_throughput_increment
    actual_battery = engine_module.compute_battery_degradation_transition
    actual_solar = engine_module.compute_explicit_solar_degradation_transition
    events = []
    eps_proposal = None

    def record_eps(state, config, inputs, *, dt_seconds, capability):
        nonlocal eps_proposal
        events.append("eps")
        assert config is active_spacecraft.eps
        assert capability.battery_capacity_retention == 0.9
        assert capability.solar_generation_retention == 0.8
        eps_proposal = actual_eps(
            state,
            config,
            inputs,
            dt_seconds=dt_seconds,
            capability=capability,
        )
        return eps_proposal

    def record_thermal(*args, **kwargs):
        events.append("thermal")
        assert args[4] is eps_proposal
        return actual_thermal(*args, **kwargs)

    def record_throughput(eps_result, battery_config):
        events.append("throughput")
        assert eps_result is eps_proposal
        assert battery_config is active_battery
        return actual_throughput(eps_result, battery_config)

    def record_battery(state, battery_config, ageing_config, interval_input):
        events.append("battery-degradation")
        assert battery_config is active_battery
        assert ageing_config is active_ageing
        assert interval_input.battery_temperature_k == pytest.approx(300.05)
        return actual_battery(
            state, battery_config, ageing_config, interval_input
        )

    def record_solar(state, forcing):
        events.append("solar-degradation")
        return actual_solar(state, forcing)

    monkeypatch.setattr(engine_module, "compute_eps_interval_transition", record_eps)
    monkeypatch.setattr(
        engine_module, "compute_eps_thermal_interval_transition", record_thermal
    )
    monkeypatch.setattr(
        engine_module, "compute_battery_throughput_increment", record_throughput
    )
    monkeypatch.setattr(
        engine_module, "compute_battery_degradation_transition", record_battery
    )
    monkeypatch.setattr(
        engine_module,
        "compute_explicit_solar_degradation_transition",
        record_solar,
    )

    SimulationEngine().step(
        context,
        **_coupled_arguments(),
        solar_degradation_forcing=SolarDegradationForcingInput(0.01),
    )

    assert events == [
        "eps",
        "thermal",
        "throughput",
        "battery-degradation",
        "solar-degradation",
    ]


def test_current_degradation_endpoint_has_no_same_interval_feedback() -> None:
    low_damage = _context(calendar_rate=1.0e-8, cycling_coefficient=0.001)
    high_damage = _context(calendar_rate=1.0e-6, cycling_coefficient=0.02)

    low_result = SimulationEngine().step(low_damage, **_coupled_arguments())
    high_result = SimulationEngine().step(high_damage, **_coupled_arguments())

    assert low_result.eps_result == high_result.eps_result
    assert low_result.thermal_coupling_result == (
        high_result.thermal_coupling_result
    )
    assert low_result.battery_degradation_result is not None
    assert high_result.battery_degradation_result is not None
    assert (
        low_result.battery_degradation_result.end_usable_capacity_retention
        != high_result.battery_degradation_result.end_usable_capacity_retention
    )


def test_no_physics_and_eps_only_do_not_evolve_degradation() -> None:
    no_physics = _context(calendar_rate=1.0e-6, cycling_coefficient=0.02)
    no_physics_before = deepcopy(no_physics.spacecraft_state.degradation)
    no_physics_result = SimulationEngine().step(no_physics)
    assert no_physics.spacecraft_state.degradation == no_physics_before
    assert no_physics_result.battery_degradation_result is None
    assert no_physics_result.solar_degradation_result is None

    eps_only = _context(calendar_rate=1.0e-6, cycling_coefficient=0.02)
    eps_only_before = deepcopy(eps_only.spacecraft_state.degradation)
    thermal_before = deepcopy(eps_only.spacecraft_state.thermal)
    eps_only_result = SimulationEngine().step(
        eps_only, eps_inputs=_eps_inputs()
    )
    assert eps_only.spacecraft_state.degradation == eps_only_before
    assert eps_only.spacecraft_state.thermal == thermal_before
    assert eps_only_result.eps_result is not None
    assert eps_only_result.battery_degradation_result is None
    assert eps_only_result.solar_degradation_result is None


def test_zero_damage_preserves_retention_but_accumulates_throughput() -> None:
    context = _context()
    result = SimulationEngine().step(context, **_coupled_arguments())

    assert result.battery_degradation_result is not None
    assert result.battery_degradation_result.calendar_damage == 0.0
    assert result.battery_degradation_result.cycling_damage == 0.0
    assert context.spacecraft_state.degradation.battery.usable_capacity_retention == (
        0.9
    )
    assert context.spacecraft_state.degradation.battery.cumulative_energy_throughput_wh == pytest.approx(
        100.125
    )
    assert context.spacecraft_state.degradation.solar.generation_retention == 0.8


def test_solar_degradation_is_explicit_only() -> None:
    without_forcing = _context()
    without_result = SimulationEngine().step(
        without_forcing, **_coupled_arguments()
    )
    assert without_result.solar_degradation_result is None
    assert without_forcing.spacecraft_state.degradation.solar == (
        SolarDegradationState(0.8)
    )

    with_forcing = _context()
    with_result = SimulationEngine().step(
        with_forcing,
        **_coupled_arguments(),
        solar_degradation_forcing=SolarDegradationForcingInput(0.05),
    )
    assert with_result.solar_degradation_result == (
        SolarDegradationTransition(0.8, 0.05, 0.75)
    )
    assert with_forcing.spacecraft_state.degradation.solar == (
        SolarDegradationState(0.75)
    )


@pytest.mark.parametrize(
    "arguments,error_type",
    (
        (
            {"solar_degradation_forcing": SolarDegradationForcingInput(0.01)},
            ValueError,
        ),
        (
            {
                "eps_inputs": _eps_inputs(),
                "solar_degradation_forcing": SolarDegradationForcingInput(0.01),
            },
            ValueError,
        ),
        (
            {
                "thermal_inputs": _thermal_inputs(),
                "heat_source_inputs": _heat_sources(),
                "solar_degradation_forcing": SolarDegradationForcingInput(0.01),
            },
            ValueError,
        ),
        ({"solar_degradation_forcing": object()}, TypeError),
        (
            {
                **_coupled_arguments(),
                "solar_degradation_forcing": object(),
            },
            TypeError,
        ),
    ),
)
def test_invalid_solar_forcing_input_matrix_is_atomic(arguments, error_type) -> None:
    context = _context()
    before = CheckpointState.from_context(context)
    with pytest.raises(error_type, match="solar_degradation_forcing"):
        SimulationEngine().step(context, **arguments)
    assert CheckpointState.from_context(context) == before


def test_invalid_battery_degradation_endpoint_rolls_back_everything() -> None:
    context = _context(calendar_rate=0.1)
    before = CheckpointState.from_context(context)
    references = (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.thermal,
        *context.spacecraft_state.thermal.node_states,
        context.spacecraft_state.degradation,
        context.spacecraft_state.degradation.battery,
        context.spacecraft_state.degradation.solar,
        context.spacecraft_state.data_storage,
        context.diagnostics,
    )

    with pytest.raises(ValueError, match="battery degradation candidate"):
        SimulationEngine().step(context, **_coupled_arguments())

    assert CheckpointState.from_context(context) == before
    _assert_original_references(context, references)


def test_invalid_solar_endpoint_rolls_back_all_valid_prior_proposals() -> None:
    context = _context(calendar_rate=1.0e-8, cycling_coefficient=0.001)
    before = CheckpointState.from_context(context)
    references = (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.thermal,
        *context.spacecraft_state.thermal.node_states,
        context.spacecraft_state.degradation,
        context.spacecraft_state.degradation.battery,
        context.spacecraft_state.degradation.solar,
        context.spacecraft_state.data_storage,
        context.diagnostics,
    )

    with pytest.raises(ValueError, match="solar degradation candidate"):
        SimulationEngine().step(
            context,
            **_coupled_arguments(),
            solar_degradation_forcing=SolarDegradationForcingInput(0.8),
        )

    assert CheckpointState.from_context(context) == before
    _assert_original_references(context, references)


def test_twenty_four_steps_age_monotonically_and_leave_telemetry_stale() -> None:
    context = _context(calendar_rate=1.0e-8, cycling_coefficient=0.001)
    telemetry_before = context.ground_knowledge_state.latest_telemetry
    retentions = [
        context.spacecraft_state.degradation.battery.usable_capacity_retention
    ]
    throughputs = [
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
    ]

    for _ in range(24):
        result = SimulationEngine().step(context, **_coupled_arguments())
        assert result.battery_degradation_result is not None
        assert result.solar_degradation_result is None
        retentions.append(
            context.spacecraft_state.degradation.battery
            .usable_capacity_retention
        )
        throughputs.append(
            context.spacecraft_state.degradation.battery
            .cumulative_energy_throughput_wh
        )
        assert context.spacecraft_state.degradation.solar.generation_retention == (
            0.8
        )
        assert context.ground_knowledge_state.latest_telemetry is telemetry_before

    assert all(left > right > 0 for left, right in zip(retentions, retentions[1:]))
    assert all(left < right for left, right in zip(throughputs, throughputs[1:]))
    assert context.simulation_time_seconds == 24 * DT_SECONDS
    assert context.diagnostics.completed_steps == 24
    assert telemetry_before is not None and telemetry_before.battery_energy_wh == 100.0


def test_schema_four_json_restart_matches_uninterrupted_ageing() -> None:
    direct = _context(calendar_rate=1.0e-8, cycling_coefficient=0.001)
    split = _context(calendar_rate=1.0e-8, cycling_coefficient=0.001)
    _run_steps(direct, 0, 24)
    _run_steps(split, 0, 9)
    checkpoint = CheckpointState.from_context(split)
    assert checkpoint.schema_version == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    encoded = json.dumps(checkpoint.to_dict(), allow_nan=False, sort_keys=True)
    restored = CheckpointState.from_dict(json.loads(encoded)).restore(split.inputs)
    _run_steps(restored, 9, 15)

    assert restored.spacecraft_state.battery == direct.spacecraft_state.battery
    assert restored.spacecraft_state.thermal == direct.spacecraft_state.thermal
    assert restored.spacecraft_state.degradation == (
        direct.spacecraft_state.degradation
    )
    assert restored.simulation_time_seconds == direct.simulation_time_seconds
    assert restored.diagnostics == direct.diagnostics


def test_engine_orchestrates_without_duplicate_degradation_equations() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ENGINE_PATH))
    called_names = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    for name in (
        "compute_eps_interval_transition",
        "compute_eps_thermal_interval_transition",
        "compute_battery_throughput_increment",
        "compute_battery_degradation_transition",
        "compute_explicit_solar_degradation_transition",
    ):
        assert called_names.count(name) == 1
    assert "8.31446261815324" not in source
    assert "Arrhenius" not in source
    assert "calendar_damage_rate_per_second_at_reference.value *" not in source
    assert "cycling_damage_per_normalized_energy_throughput" not in source
    assert "3600" not in source
    assert "exp(" not in source
    assert "clip" not in source


def test_d2b2_decisions_and_numerical_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    for number in range(134, 141):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D133 ") < decisions.index("## D134 ")
    s003 = sources.partition("### S003 ")[2].partition("### S004 ")[0]
    s004 = sources.partition("### S004 ")[2].partition("### S005 ")[0]
    s009 = sources.partition("### S009 ")[2]
    assert "same EPS interval result" in s003
    assert "active `BatteryConfig`" in s003
    assert "endpoint arithmetic mean" in s004
    assert "representative" in s004 and "convergence" in s004
    assert "explicit solar" in s009
    assert "schema 3" in s009.lower()
    assert "same-step" in s009
