"""Transactional EPS-to-thermal engine integration for V5.2E1."""

import ast
from copy import deepcopy
from dataclasses import fields
from pathlib import Path

import pytest

from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
import ops_sim.v5.engine as engine_module
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
from ops_sim.v5.engine import SimulationEngine, StepResult
from ops_sim.v5.eps_system import (
    EPSIntervalInputs,
    EPSIntervalResult,
    compute_eps_interval_transition,
)
from ops_sim.v5.eps_capability import compute_eps_capability
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
    ThermalLinkId,
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
from ops_sim.v5.thermal_config import (
    ThermalLinkConfig,
    ThermalNetworkConfig,
    ThermalNodeConfig,
)
from ops_sim.v5.thermal_coupling import (
    EPSThermalCouplingResult,
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
    compute_eps_thermal_interval_transition,
)
from ops_sim.v5.world import CommonWorld


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
NODE_NAMES = ("bus", "battery", "payload")


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


def _node(
    name: str,
    *,
    heat_capacity: object = 1000.0,
    emissivity: object = 0.0,
    area: object = 1.0,
) -> ThermalNodeConfig:
    prefix = f"thermal.node.{name}"
    return ThermalNodeConfig(
        ThermalNodeId(name),
        _parameter(f"{prefix}.heat-capacity", "J/K", heat_capacity),
        _parameter(f"{prefix}.emissivity", "1", emissivity),
        _parameter(f"{prefix}.radiating-area", "m^2", area),
        _parameter(f"{prefix}.operating-min-temperature", "K", 270.0),
        _parameter(f"{prefix}.operating-max-temperature", "K", 320.0),
        _parameter(f"{prefix}.survival-min-temperature", "K", 250.0),
        _parameter(f"{prefix}.survival-max-temperature", "K", 340.0),
    )


def _network(
    *,
    nodes: tuple[ThermalNodeConfig, ...] | None = None,
    links: tuple[ThermalLinkConfig, ...] = (),
) -> ThermalNetworkConfig:
    return ThermalNetworkConfig(
        tuple(_node(name) for name in NODE_NAMES) if nodes is None else nodes,
        links,
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        ThermalNodeId("payload"),
    )


def _configuration(
    network: ThermalNetworkConfig,
    *,
    discharge_efficiency: object = 0.8,
) -> SpacecraftConfiguration:
    return SpacecraftConfiguration(
        SpacecraftConfigurationId("e1-optical"),
        "Synthetic E1 Optical Reference",
        1,
        EPSConfig(
            SubsystemConfigurationId("eps-e1"),
            BatteryConfig(
                SubsystemConfigurationId("battery-e1"),
                _parameter("eps.battery.nominal-energy", "Wh", 1000.0),
                _parameter("eps.battery.charge-efficiency", "1", 1.0),
                _parameter(
                    "eps.battery.discharge-efficiency",
                    "1",
                    discharge_efficiency,
                ),
                _parameter("eps.battery.max-charge-input-power", "W", 100.0),
                _parameter(
                    "eps.battery.max-discharge-output-power", "W", 100.0
                ),
            ),
            SolarArrayConfig(
                SubsystemConfigurationId("solar-e1"),
                _parameter("eps.solar-array.nominal-generation", "W", 100.0),
            ),
        ),
        PayloadConfig(
            SubsystemConfigurationId("payload-e1"),
            PayloadFamily.OPTICAL_EO,
            (PayloadMode.PANCHROMATIC,),
            _optical_acquisition(),
        ),
        StorageConfig(
            SubsystemConfigurationId("storage-e1"),
            _parameter("storage.usable-capacity", "GB", 10.0),
        ),
        CommunicationsConfig(
            SubsystemConfigurationId("communications-e1"),
            _parameter(
                "communications.nominal-downlink-data-rate",
                "bit/s",
                1_000_000.0,
            ),
        ),
        ADCSConfig(SubsystemConfigurationId("adcs-e1"), _agile_pointing()),
        ThermalConfig(SubsystemConfigurationId("thermal-e1"), network),
        DegradationConfig(
            SubsystemConfigurationId("degradation-e1"),
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
            SubsystemConfigurationId("propulsion-e1"),
            _parameter("propulsion.initial-delta-v", "m/s", 10.0),
        ),
        OBCConfig(SubsystemConfigurationId("obc-e1")),
    )


def _context(
    *,
    network: ThermalNetworkConfig | None = None,
    dt_seconds: int = 10,
    battery_energy_wh: object = 100.0,
    temperatures: dict[str, object] | None = None,
    runtime_order: tuple[str, ...] = NODE_NAMES,
) -> SimulationContext:
    active_network = _network() if network is None else network
    spacecraft = _configuration(active_network)
    numerical = NumericalConfig(
        NumericalConfigId(f"e1-step-{dt_seconds}"),
        dt_seconds,
        1,
        dt_seconds,
    )
    environment = EnvironmentConfig(EnvironmentId("e1-environment"))
    flight_rules = FlightRulesConfig(FlightRulesId("e1-rules"))
    scenario = ScenarioConfig(ScenarioId("e1-scenario"))
    world = CommonWorld(WorldId("e1-world"), scenario.scenario_id, 1000, ())
    controller_id = ControllerId("e1-controller")
    manifest = ModelManifest(
        ModelManifestId("e1-manifest"),
        1,
        spacecraft.configuration_id,
        numerical.configuration_id,
        environment.environment_id,
        flight_rules.flight_rules_id,
        scenario.scenario_id,
        world.world_id,
        controller_id,
    )
    inputs = SimulationInputs(
        spacecraft,
        numerical,
        environment,
        flight_rules,
        scenario,
        world,
        manifest,
    )
    temperature_by_name = (
        {name: 300.0 for name in NODE_NAMES}
        if temperatures is None
        else temperatures
    )
    return SimulationContext(
        0,
        inputs,
        SpacecraftState(
            BatteryState(battery_energy_wh),
            PropulsionState(9.0),
            ThermalState(
                tuple(
                    ThermalNodeState(
                        ThermalNodeId(name), temperature_by_name[name]
                    )
                    for name in runtime_order
                )
            ),
            DegradationState(
                BatteryDegradationState(0.91, 1234.5),
                SolarDegradationState(0.87),
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
                TelemetrySnapshotId("e1-telemetry"),
                0,
                0,
                battery_energy_wh,
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


def _eps_inputs(load_w: object = 36.0) -> EPSIntervalInputs:
    return EPSIntervalInputs(
        False,
        0.0,
        PowerLoadBreakdown(load_w, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )


def _thermal_inputs(
    sinks: dict[str, object] | None = None,
) -> ThermalIntervalInputs:
    values = {name: 300.0 for name in NODE_NAMES} if sinks is None else sinks
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(ThermalNodeId(name), values[name])
            for name in values
        )
    )


def _heat_sources(
    internal: dict[str, object] | None = None,
) -> ThermalHeatSourceInputs:
    values = {} if internal is None else internal
    return ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(
                ThermalNodeId(name), values.get(name, 0.0), 0.0, 0.0, 0.0
            )
            for name in NODE_NAMES
        )
    )


def _temperatures(context: SimulationContext) -> dict[str, object]:
    return {
        item.node_id.value: item.temperature_k
        for item in context.spacecraft_state.thermal.node_states
    }


def test_hand_calculation_updates_battery_and_battery_node_once() -> None:
    context = _context()
    battery_retention_before = (
        context.spacecraft_state.degradation.battery
        .usable_capacity_retention
    )
    battery_throughput_before = (
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
    )
    solar_before = deepcopy(context.spacecraft_state.degradation.solar)
    telemetry_before = context.ground_knowledge_state.latest_telemetry

    result = SimulationEngine().step(
        context,
        eps_inputs=_eps_inputs(),
        thermal_inputs=_thermal_inputs(),
        heat_source_inputs=_heat_sources({"battery": 11.0}),
    )

    assert type(result.eps_result) is EPSIntervalResult
    assert type(result.thermal_coupling_result) is EPSThermalCouplingResult
    assert result.eps_result.battery.end_energy_wh == pytest.approx(99.875)
    assert result.eps_result.battery.conversion_loss_wh == pytest.approx(0.025)
    ledgers = {
        item.node_id.value: item
        for item in result.thermal_coupling_result.node_heat_ledgers
    }
    transitions = {
        item.node_id.value: item
        for item in (
            result.thermal_coupling_result.thermal_result.node_transitions
        )
    }
    assert ledgers["battery"].battery_conversion_heat_w == pytest.approx(9.0)
    assert ledgers["battery"].total_applied_heat_w == pytest.approx(20.0)
    assert transitions["battery"].thermal_energy_change_j == pytest.approx(
        200.0
    )
    assert transitions["battery"].end_temperature_k == pytest.approx(300.2)
    assert context.spacecraft_state.battery.energy_wh == pytest.approx(99.875)
    assert _temperatures(context) == pytest.approx(
        {"bus": 300.0, "battery": 300.2, "payload": 300.0}
    )
    assert context.ground_knowledge_state.latest_telemetry is telemetry_before
    assert telemetry_before.battery_energy_wh == 100.0
    assert result.battery_degradation_result is not None
    assert result.solar_degradation_result is None
    assert (
        context.spacecraft_state.degradation.battery
        .usable_capacity_retention
        == battery_retention_before
    )
    assert (
        context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
        == pytest.approx(battery_throughput_before + 0.125)
    )
    assert context.spacecraft_state.degradation.solar == solar_before
    assert context.simulation_time_seconds == 10
    assert context.diagnostics.completed_steps == 1


def test_coupled_calls_are_once_ordered_and_share_dt_and_eps_result(
    monkeypatch,
) -> None:
    context = _context()
    actual_eps = engine_module.compute_eps_interval_transition
    actual_thermal = engine_module.compute_eps_thermal_interval_transition
    events = []
    eps_proposal = None

    def record_eps(*args, **kwargs):
        nonlocal eps_proposal
        events.append(("eps", kwargs["dt_seconds"]))
        eps_proposal = actual_eps(*args, **kwargs)
        return eps_proposal

    def record_thermal(*args, **kwargs):
        events.append(("thermal", kwargs["dt_seconds"]))
        assert args[4] is eps_proposal
        return actual_thermal(*args, **kwargs)

    monkeypatch.setattr(
        engine_module, "compute_eps_interval_transition", record_eps
    )
    monkeypatch.setattr(
        engine_module,
        "compute_eps_thermal_interval_transition",
        record_thermal,
    )

    SimulationEngine().step(
        context,
        eps_inputs=_eps_inputs(),
        thermal_inputs=_thermal_inputs(),
        heat_source_inputs=_heat_sources(),
    )

    assert events == [("eps", 10), ("thermal", 10)]


def test_conduction_radiation_and_applied_heat_match_pure_coupling_by_id() -> None:
    nodes = tuple(
        _node(name, heat_capacity=100_000.0, emissivity=0.7, area=1.2)
        for name in NODE_NAMES
    )
    link = ThermalLinkConfig(
        ThermalLinkId("bus-battery"),
        ThermalNodeId("bus"),
        ThermalNodeId("battery"),
        _parameter("thermal.link.bus-battery.conductance", "W/K", 2.0),
    )
    network = _network(nodes=nodes, links=(link,))
    context = _context(
        network=network,
        temperatures={"bus": 310.0, "battery": 300.0, "payload": 290.0},
        runtime_order=("payload", "bus", "battery"),
    )
    eps_inputs = _eps_inputs(0.0)
    thermal_inputs = _thermal_inputs(
        {"battery": 280.0, "payload": 275.0, "bus": 285.0}
    )
    sources = _heat_sources({"bus": 3.0, "battery": 4.0, "payload": 5.0})
    start_thermal = deepcopy(context.spacecraft_state.thermal)
    expected_eps = compute_eps_interval_transition(
        context.spacecraft_state.battery,
        context.inputs.spacecraft_configuration.eps,
        eps_inputs,
        dt_seconds=10,
        capability=compute_eps_capability(
            context.inputs.spacecraft_configuration.eps,
            context.spacecraft_state.degradation,
        ),
    )
    expected_coupling = compute_eps_thermal_interval_transition(
        start_thermal,
        network,
        thermal_inputs,
        sources,
        expected_eps,
        dt_seconds=10,
    )

    result = SimulationEngine().step(
        context,
        eps_inputs=eps_inputs,
        thermal_inputs=thermal_inputs,
        heat_source_inputs=sources,
    )

    assert result.eps_result == expected_eps
    assert result.thermal_coupling_result == expected_coupling
    expected_by_id = {
        item.node_id.value: item.end_temperature_k
        for item in expected_coupling.thermal_result.node_transitions
    }
    assert _temperatures(context) == pytest.approx(expected_by_id)
    assert tuple(
        item.node_id.value
        for item in context.spacecraft_state.thermal.node_states
    ) == ("payload", "bus", "battery")
    assert all(
        transition.start_temperature_k
        == {
            "bus": 310.0,
            "battery": 300.0,
            "payload": 290.0,
        }[transition.node_id.value]
        for transition in expected_coupling.thermal_result.node_transitions
    )


def test_eps_only_preserves_thermal_and_reports_no_coupling() -> None:
    context = _context()
    thermal_before = deepcopy(context.spacecraft_state.thermal)
    expected = compute_eps_interval_transition(
        context.spacecraft_state.battery,
        context.inputs.spacecraft_configuration.eps,
        _eps_inputs(),
        dt_seconds=10,
        capability=compute_eps_capability(
            context.inputs.spacecraft_configuration.eps,
            context.spacecraft_state.degradation,
        ),
    )

    result = SimulationEngine().step(context, eps_inputs=_eps_inputs())

    assert result.eps_result == expected
    assert result.thermal_coupling_result is None
    assert context.spacecraft_state.thermal == thermal_before
    assert context.spacecraft_state.battery.energy_wh == pytest.approx(
        expected.battery.end_energy_wh
    )


def test_no_physics_preserves_battery_thermal_and_degradation() -> None:
    context = _context()
    physical_before = deepcopy(context.spacecraft_state)

    result = SimulationEngine().step(context)

    assert result.eps_result is None
    assert result.thermal_coupling_result is None
    assert context.spacecraft_state == physical_before
    assert context.simulation_time_seconds == 10
    assert context.diagnostics.completed_steps == 1


@pytest.mark.parametrize(
    "case",
    ("thermal-only", "sources-only", "eps-thermal", "eps-sources"),
)
def test_partial_thermal_combinations_are_rejected_atomically(case) -> None:
    context = _context()
    before = CheckpointState.from_context(context)
    arguments = {
        "thermal-only": {"thermal_inputs": _thermal_inputs()},
        "sources-only": {"heat_source_inputs": _heat_sources()},
        "eps-thermal": {
            "eps_inputs": _eps_inputs(),
            "thermal_inputs": _thermal_inputs(),
        },
        "eps-sources": {
            "eps_inputs": _eps_inputs(),
            "heat_source_inputs": _heat_sources(),
        },
    }[case]

    with pytest.raises(ValueError, match="requires"):
        SimulationEngine().step(context, **arguments)

    assert CheckpointState.from_context(context) == before


class _RecordingEngine(SimulationEngine):
    __slots__ = ("phases",)

    def __init__(self) -> None:
        self.phases = []

    def _execute_phase(
        self,
        phase,
        context,
        interval,
        eps_inputs,
    ):
        self.phases.append(phase)
        return super()._execute_phase(phase, context, interval, eps_inputs)


@pytest.mark.parametrize(
    ("field_name", "arguments"),
    (
        ("eps_inputs", {"eps_inputs": object()}),
        (
            "thermal_inputs",
            {
                "eps_inputs": _eps_inputs(),
                "thermal_inputs": object(),
                "heat_source_inputs": _heat_sources(),
            },
        ),
        (
            "heat_source_inputs",
            {
                "eps_inputs": _eps_inputs(),
                "thermal_inputs": _thermal_inputs(),
                "heat_source_inputs": object(),
            },
        ),
    ),
)
def test_wrong_physics_types_are_rejected_before_phase_execution(
    field_name,
    arguments,
) -> None:
    context = _context()
    before = CheckpointState.from_context(context)
    engine = _RecordingEngine()

    with pytest.raises(TypeError, match=field_name):
        engine.step(context, **arguments)

    assert engine.phases == []
    assert CheckpointState.from_context(context) == before


def test_heat_source_node_mismatch_uses_pure_contract_and_rolls_back() -> None:
    context = _context()
    before = CheckpointState.from_context(context)
    incomplete_sources = ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(
                ThermalNodeId(name), 0.0, 0.0, 0.0, 0.0
            )
            for name in ("bus", "battery")
        )
    )

    with pytest.raises(ValueError, match="exactly match"):
        SimulationEngine().step(
            context,
            eps_inputs=_eps_inputs(),
            thermal_inputs=_thermal_inputs(),
            heat_source_inputs=incomplete_sources,
        )

    assert CheckpointState.from_context(context) == before


def test_nonpositive_thermal_endpoint_after_eps_proposal_rolls_back(
    monkeypatch,
) -> None:
    network = _network(
        nodes=(
            _node("bus"),
            _node(
                "battery",
                heat_capacity=1.0,
                emissivity=1.0,
                area=1000.0,
            ),
            _node("payload"),
        )
    )
    context = _context(network=network)
    before = CheckpointState.from_context(context)
    original_references = (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.thermal,
        context.spacecraft_state.degradation,
        context.spacecraft_state.data_storage,
        context.diagnostics,
    )
    actual_eps = engine_module.compute_eps_interval_transition
    eps_calls = 0

    def record_eps(*args, **kwargs):
        nonlocal eps_calls
        eps_calls += 1
        return actual_eps(*args, **kwargs)

    monkeypatch.setattr(
        engine_module, "compute_eps_interval_transition", record_eps
    )

    with pytest.raises(ValueError, match="end temperature"):
        SimulationEngine().step(
            context,
            eps_inputs=_eps_inputs(),
            thermal_inputs=_thermal_inputs(
                {"bus": 300.0, "battery": 1.0, "payload": 300.0}
            ),
            heat_source_inputs=_heat_sources(),
        )

    assert eps_calls == 1
    assert CheckpointState.from_context(context) == before
    assert (
        context.spacecraft_state,
        context.spacecraft_state.battery,
        context.spacecraft_state.thermal,
        context.spacecraft_state.degradation,
        context.spacecraft_state.data_storage,
        context.diagnostics,
    ) == original_references


def test_step_result_adds_exact_optional_coupling_result() -> None:
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
    context = _context()
    result = SimulationEngine().step(
        context,
        eps_inputs=_eps_inputs(),
        thermal_inputs=_thermal_inputs(),
        heat_source_inputs=_heat_sources(),
    )
    with pytest.raises(TypeError, match="thermal_coupling_result"):
        StepResult(
            result.start_time_seconds,
            result.end_time_seconds,
            result.dt_seconds,
            result.executed_phases,
            result.eps_result,
            object(),
        )


def test_engine_orchestrates_without_physics_or_c2_duplication() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ENGINE_PATH))
    called_names = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    routing_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").partition(".")[0] == "thermal_routing"
        for alias in node.names
    }
    assert called_names.count("compute_eps_interval_transition") == 1
    assert called_names.count("compute_eps_thermal_interval_transition") == 1
    assert "5.670374419" not in source
    assert "3600" not in source
    assert not any(
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Pow)
        and isinstance(node.right, ast.Constant)
        and node.right.value == 4
        for node in ast.walk(tree)
    )
    assert "ServedPowerLedger" not in source
    assert routing_imports == {"ComponentHeatRoutingConfig"}
    assert "compute_routed_internal_heat" not in source
    assert "compose_routed_internal_heat_sources" not in source
    assert "unmet_load_w" not in source


def test_e1_decisions_and_source_register_contract_are_present() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    for number in range(113, 119):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D112 ") < decisions.index("## D113 ")
    s003 = sources.partition("### S003 ")[2].partition("### S004 ")[0]
    s004 = sources.partition("### S004 ")[2].partition("### S005 ")[0]
    assert "same engine interval" in s003
    assert "same `dt_seconds`" in s004
    assert "start-of-interval temperatures" in s004
    assert "same-step thermal-to-EPS feedback" in s004
    assert "explicit" in s004
    assert "D2B2 now" in s004
    assert "endpoint arithmetic mean" in s004
