"""Focused tests for V5.1D transactional EPS engine integration."""

import ast
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields
from inspect import Parameter, signature
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
from ops_sim.v5.engine import SimulationEngine, StepResult
from ops_sim.v5.eps import BatteryTransition
from ops_sim.v5.eps_system import (
    EPSIntervalInputs,
    EPSIntervalResult,
    compute_eps_interval_transition,
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
from ops_sim.v5.power_loads import PowerLoadBreakdown, compose_power_load
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
from ops_sim.v5.solar import SolarGenerationResult
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
EPS_SYSTEM_PATH = ROOT / "ops_sim" / "v5" / "eps_system.py"
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
                _parameter("eps.battery.nominal-energy", "Wh", 2000.0),
                _parameter("eps.battery.charge-efficiency", "1", 1.0),
                _parameter("eps.battery.discharge-efficiency", "1", 1.0),
                _parameter(
                    "eps.battery.max-charge-input-power",
                    "W",
                    1000.0,
                ),
                _parameter(
                    "eps.battery.max-discharge-output-power",
                    "W",
                    1000.0,
                ),
            ),
            SolarArrayConfig(
                SubsystemConfigurationId("solar-array"),
                _parameter(
                    "eps.solar-array.nominal-generation",
                    "W",
                    1000.0,
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


def _simulation_inputs(
    dt_seconds: int,
    horizon_seconds: int,
) -> SimulationInputs:
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
    dt_seconds: int = 300,
    horizon_seconds: int = 3600,
    simulation_time_seconds: int = 0,
    battery_energy_wh: float = 1000.0,
    telemetry_energy_wh: float = 1000.0,
) -> SimulationContext:
    inputs = _simulation_inputs(dt_seconds, horizon_seconds)
    return SimulationContext(
        simulation_time_seconds,
        inputs,
        SpacecraftState(
            BatteryState(battery_energy_wh),
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
                telemetry_energy_wh,
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


def _loads(total_base_w: float = 100.0) -> PowerLoadBreakdown:
    return compose_power_load(
        base_bus_w=total_base_w,
        obc_w=50.0,
        adcs_w=50.0,
        payload_w=100.0,
        communications_w=0.0,
        thermal_control_w=0.0,
        propulsion_w=0.0,
    )


def _eps_inputs(
    *,
    sunlit: bool = True,
    incidence_angle_deg: float = 60.0,
    load_breakdown: PowerLoadBreakdown | None = None,
) -> EPSIntervalInputs:
    return EPSIntervalInputs(
        sunlit,
        incidence_angle_deg,
        _loads() if load_breakdown is None else load_breakdown,
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


def test_eps_interval_inputs_have_exact_transient_structure() -> None:
    inputs = _eps_inputs()

    assert tuple(field.name for field in fields(EPSIntervalInputs)) == (
        "sunlit",
        "incidence_angle_deg",
        "load_breakdown",
    )
    assert {
        "generation_w",
        "total_load_w",
        "dt_seconds",
        "battery_state",
        "soc",
    }.isdisjoint(field.name for field in fields(EPSIntervalInputs))
    assert not hasattr(inputs, "__dict__")
    assert isinstance(hash(inputs), int)
    with pytest.raises(FrozenInstanceError):
        inputs.sunlit = False


def test_eps_interval_inputs_have_no_defaults() -> None:
    for field in fields(EPSIntervalInputs):
        assert field.default is MISSING
        assert field.default_factory is MISSING
    with pytest.raises(TypeError):
        EPSIntervalInputs()


@pytest.mark.parametrize("sunlit", (True, False))
@pytest.mark.parametrize("angle", (0, 30, 60, 90, 120, 180))
def test_eps_interval_inputs_accept_required_geometry(sunlit, angle) -> None:
    inputs = EPSIntervalInputs(sunlit, angle, _loads())

    assert inputs.sunlit is sunlit
    assert inputs.incidence_angle_deg == angle


@pytest.mark.parametrize("invalid", (0, 1, "true", None))
def test_eps_interval_inputs_require_exact_boolean(invalid) -> None:
    with pytest.raises(TypeError):
        EPSIntervalInputs(invalid, 0.0, _loads())


def test_eps_interval_inputs_reject_invalid_incidence() -> None:
    for invalid in (True, False, "60"):
        with pytest.raises(TypeError):
            EPSIntervalInputs(True, invalid, _loads())
    for invalid in (
        -0.001,
        180.001,
        float("nan"),
        float("inf"),
        float("-inf"),
    ):
        with pytest.raises(ValueError):
            EPSIntervalInputs(True, invalid, _loads())


def test_eps_interval_inputs_require_exact_load_breakdown() -> None:
    with pytest.raises(TypeError, match="load_breakdown"):
        EPSIntervalInputs(True, 0.0, object())


def test_eps_interval_result_has_exact_transient_structure() -> None:
    result = compute_eps_interval_transition(
        BatteryState(1000.0),
        _spacecraft_configuration().eps,
        _eps_inputs(),
        dt_seconds=300,
    )

    assert tuple(field.name for field in fields(EPSIntervalResult)) == (
        "solar",
        "loads",
        "battery",
    )
    assert not hasattr(result, "__dict__")
    assert isinstance(hash(result), int)
    for field in fields(EPSIntervalResult):
        assert field.default is MISSING
        assert field.default_factory is MISSING
    with pytest.raises(FrozenInstanceError):
        result.loads = _loads()


@pytest.mark.parametrize(
    "field_name,replacement",
    (
        ("solar", object()),
        ("loads", object()),
        ("battery", object()),
    ),
)
def test_eps_interval_result_requires_exact_nested_types(
    field_name,
    replacement,
) -> None:
    valid = compute_eps_interval_transition(
        BatteryState(1000.0),
        _spacecraft_configuration().eps,
        _eps_inputs(),
        dt_seconds=300,
    )
    values = {
        "solar": valid.solar,
        "loads": valid.loads,
        "battery": valid.battery,
    }
    values[field_name] = replacement

    with pytest.raises(TypeError):
        EPSIntervalResult(**values)


def test_pure_composite_charging_hand_calculation_and_reuse() -> None:
    state = BatteryState(1000.0)
    config = _spacecraft_configuration().eps
    inputs = _eps_inputs()
    state_before = deepcopy(state)
    config_before = deepcopy(config)

    result = compute_eps_interval_transition(
        state,
        config,
        inputs,
        dt_seconds=300,
    )

    assert type(result.solar) is SolarGenerationResult
    assert type(result.loads) is PowerLoadBreakdown
    assert type(result.battery) is BatteryTransition
    assert result.loads is inputs.load_breakdown
    assert result.solar.generation_w == pytest.approx(500.0)
    assert result.loads.total_load_w == 300.0
    assert result.battery.generation_w == pytest.approx(
        result.solar.generation_w
    )
    assert result.battery.load_w == result.loads.total_load_w
    assert result.battery.charge_input_w == pytest.approx(200.0)
    assert result.battery.end_energy_wh == pytest.approx(
        1016.6666666666666
    )
    assert state == state_before
    assert config == config_before
    assert inputs == _eps_inputs()


def test_pure_composite_eclipse_discharge_hand_calculation() -> None:
    result = compute_eps_interval_transition(
        BatteryState(1000.0),
        _spacecraft_configuration().eps,
        _eps_inputs(sunlit=False),
        dt_seconds=300,
    )

    assert result.solar.generation_w == 0.0
    assert result.loads.total_load_w == 300.0
    assert result.battery.discharge_output_w == 300.0
    assert result.battery.end_energy_wh == pytest.approx(975.0)


@pytest.mark.parametrize(
    "field_name,replacement",
    (
        ("state", object()),
        ("config", object()),
        ("inputs", object()),
    ),
)
def test_pure_composite_requires_exact_domain_types(
    field_name,
    replacement,
) -> None:
    values = {
        "state": BatteryState(1000.0),
        "config": _spacecraft_configuration().eps,
        "inputs": _eps_inputs(),
    }
    values[field_name] = replacement

    with pytest.raises(TypeError):
        compute_eps_interval_transition(**values, dt_seconds=300)


def test_pure_composite_requires_positive_exact_integer_duration() -> None:
    arguments = (
        BatteryState(1000.0),
        _spacecraft_configuration().eps,
        _eps_inputs(),
    )
    for invalid in (True, 1.0, "300"):
        with pytest.raises(TypeError):
            compute_eps_interval_transition(
                *arguments,
                dt_seconds=invalid,
            )
    for invalid in (0, -1):
        with pytest.raises(ValueError):
            compute_eps_interval_transition(
                *arguments,
                dt_seconds=invalid,
            )


def test_engine_step_interface_keeps_optional_keyword_only_physics_inputs() -> None:
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
    for name in (
        "eps_inputs",
        "thermal_inputs",
        "heat_source_inputs",
        "solar_degradation_forcing",
    ):
        assert parameters[name].kind is Parameter.KEYWORD_ONLY
        assert parameters[name].default is None


def test_no_eps_compatibility_changes_only_time_and_diagnostics() -> None:
    context = _context()
    battery_before = context.spacecraft_state.battery.energy_wh
    knowledge_before = deepcopy(context.ground_knowledge_state)

    result = SimulationEngine().step(context)

    assert type(result) is StepResult
    assert context.spacecraft_state.battery.energy_wh == battery_before
    assert context.ground_knowledge_state == knowledge_before
    assert context.simulation_time_seconds == 300
    assert context.diagnostics.completed_steps == 1


def test_engine_charging_matches_pure_composite_hand_calculation() -> None:
    context = _context()
    inputs = _eps_inputs()
    expected = compute_eps_interval_transition(
        context.spacecraft_state.battery,
        context.inputs.spacecraft_configuration.eps,
        inputs,
        dt_seconds=300,
    )

    result = SimulationEngine().step(context, eps_inputs=inputs)

    assert result.dt_seconds == 300
    assert context.spacecraft_state.battery.energy_wh == pytest.approx(
        expected.battery.end_energy_wh
    )
    assert context.spacecraft_state.battery.energy_wh == pytest.approx(
        1016.6666666666666
    )


def test_engine_eclipse_discharge_leaves_ground_telemetry_stale() -> None:
    context = _context(battery_energy_wh=1000.0, telemetry_energy_wh=1000.0)
    inputs = _eps_inputs(sunlit=False)

    SimulationEngine().step(context, eps_inputs=inputs)

    assert context.spacecraft_state.battery.energy_wh == pytest.approx(975.0)
    telemetry = context.ground_knowledge_state.latest_telemetry
    assert telemetry is not None
    assert telemetry.battery_energy_wh == 1000.0


def test_successful_eps_step_mutates_no_unrelated_domain_values() -> None:
    context = _context()
    propulsion_before = deepcopy(context.spacecraft_state.propulsion)
    onboard_before = deepcopy(context.spacecraft_state.onboard)
    knowledge_before = deepcopy(context.ground_knowledge_state)
    mission_before = deepcopy(context.mission_state)
    controller_before = deepcopy(context.controller_state)

    SimulationEngine().step(context, eps_inputs=_eps_inputs())

    assert context.spacecraft_state.propulsion == propulsion_before
    assert context.spacecraft_state.onboard == onboard_before
    assert context.spacecraft_state.onboard.operational_mode is (
        OperationalMode.STANDBY
    )
    assert context.spacecraft_state.onboard.fdir_state is FDIRState.NORMAL
    assert context.ground_knowledge_state == knowledge_before
    assert context.mission_state == mission_before
    assert context.controller_state == controller_before
    assert context.simulation_time_seconds == 300
    assert context.diagnostics.completed_steps == 1


def test_full_battery_curtailment_is_a_successful_engine_outcome() -> None:
    context = _context(battery_energy_wh=2000.0)
    inputs = _eps_inputs()
    pure = compute_eps_interval_transition(
        context.spacecraft_state.battery,
        context.inputs.spacecraft_configuration.eps,
        inputs,
        dt_seconds=300,
    )

    SimulationEngine().step(context, eps_inputs=inputs)

    assert pure.battery.curtailed_generation_w == pytest.approx(200.0)
    assert context.spacecraft_state.battery.energy_wh == 2000.0
    assert context.simulation_time_seconds == 300
    assert context.diagnostics.completed_steps == 1


def test_empty_battery_unmet_load_is_a_successful_engine_outcome() -> None:
    context = _context(battery_energy_wh=0.0)
    inputs = _eps_inputs(sunlit=False)
    pure = compute_eps_interval_transition(
        context.spacecraft_state.battery,
        context.inputs.spacecraft_configuration.eps,
        inputs,
        dt_seconds=300,
    )

    SimulationEngine().step(context, eps_inputs=inputs)

    assert pure.battery.unmet_load_w == 300.0
    assert context.spacecraft_state.battery.energy_wh == 0.0
    assert context.spacecraft_state.onboard.operational_mode is (
        OperationalMode.STANDBY
    )
    assert context.spacecraft_state.onboard.fdir_state is FDIRState.NORMAL
    assert context.simulation_time_seconds == 300
    assert context.diagnostics.completed_steps == 1


class RecordingEngine(SimulationEngine):
    __slots__ = ("phases",)

    def __init__(self) -> None:
        self.phases: list[object] = []

    def _execute_phase(
        self,
        phase,
        context,
        interval,
        eps_inputs,
    ) -> None:
        self.phases.append(phase)
        super()._execute_phase(phase, context, interval, eps_inputs)


def test_wrong_eps_inputs_type_is_rejected_before_phase_execution() -> None:
    context = _context()
    checkpoint = CheckpointState.from_context(context)
    references = _mutable_domain_references(context)
    engine = RecordingEngine()

    with pytest.raises(TypeError, match="eps_inputs"):
        engine.step(context, eps_inputs="wrong")

    assert engine.phases == []
    assert CheckpointState.from_context(context) == checkpoint
    assert all(
        current is original
        for current, original in zip(
            _mutable_domain_references(context),
            references,
        )
    )


def test_eps_calculation_failure_rolls_back_without_commit() -> None:
    context = _context(battery_energy_wh=2000.0)
    context.spacecraft_state.battery.energy_wh = 2000.001
    before = deepcopy(context)
    references = _mutable_domain_references(context)

    with pytest.raises(ValueError, match="must not exceed"):
        SimulationEngine().step(context, eps_inputs=_eps_inputs())

    assert context == before
    assert context.spacecraft_state.battery.energy_wh == 2000.001
    assert context.simulation_time_seconds == 0
    assert context.diagnostics.completed_steps == 0
    assert all(
        current is original
        for current, original in zip(
            _mutable_domain_references(context),
            references,
        )
    )


class FailAfterEPSIntegration(SimulationEngine):
    def _failure_capability_resolution(self, context, interval) -> None:
        assert context.spacecraft_state.battery.energy_wh != 1000.0
        raise RuntimeError("synthetic post-EPS failure")


def test_late_failure_rolls_back_real_eps_working_state_mutation() -> None:
    context = _context()
    checkpoint = CheckpointState.from_context(context)
    references = _mutable_domain_references(context)
    inputs = context.inputs

    with pytest.raises(RuntimeError, match="post-EPS"):
        FailAfterEPSIntegration().step(
            context,
            eps_inputs=_eps_inputs(),
        )

    assert CheckpointState.from_context(context) == checkpoint
    assert context.inputs is inputs
    assert context.spacecraft_state.battery.energy_wh == 1000.0
    assert context.simulation_time_seconds == 0
    assert context.diagnostics.completed_steps == 0
    assert all(
        current is original
        for current, original in zip(
            _mutable_domain_references(context),
            references,
        )
    )


def test_checkpoint_after_eps_step_preserves_new_battery_truth() -> None:
    context = _context()

    SimulationEngine().step(context, eps_inputs=_eps_inputs())
    checkpoint = CheckpointState.from_context(context)
    restored = checkpoint.restore(context.inputs)

    assert checkpoint.spacecraft.battery_energy_wh == pytest.approx(
        1016.6666666666666
    )
    assert restored == context
    assert restored.spacecraft_state.battery.energy_wh == pytest.approx(
        context.spacecraft_state.battery.energy_wh
    )


def test_checkpoint_continuation_matches_direct_eps_execution() -> None:
    initial = _context(horizon_seconds=1500)
    checkpoint = CheckpointState.from_context(initial)
    direct = checkpoint.restore(initial.inputs)
    split = checkpoint.restore(initial.inputs)
    engine = SimulationEngine()
    inputs = _eps_inputs()

    for _ in range(5):
        engine.step(direct, eps_inputs=inputs)
    for _ in range(2):
        engine.step(split, eps_inputs=inputs)
    split = CheckpointState.from_context(split).restore(split.inputs)
    for _ in range(3):
        engine.step(split, eps_inputs=inputs)

    assert split == direct


@pytest.mark.parametrize(
    "eps_inputs",
    (
        EPSIntervalInputs(True, 60.0, _loads()),
        EPSIntervalInputs(False, 60.0, _loads()),
    ),
)
def test_one_hour_matches_twelve_five_minute_engine_steps(
    eps_inputs,
) -> None:
    one_hour = _context(dt_seconds=3600, horizon_seconds=3600)
    sequential = _context(dt_seconds=300, horizon_seconds=3600)
    engine = SimulationEngine()

    engine.step(one_hour, eps_inputs=eps_inputs)
    for _ in range(12):
        engine.step(sequential, eps_inputs=eps_inputs)

    assert sequential.spacecraft_state.battery.energy_wh == pytest.approx(
        one_hour.spacecraft_state.battery.energy_wh
    )
    expected = 1200.0 if eps_inputs.sunlit else 700.0
    assert one_hour.spacecraft_state.battery.energy_wh == pytest.approx(
        expected
    )


def test_eps_interval_objects_are_not_authoritative_or_checkpointed() -> None:
    authoritative_types = (
        SimulationContext,
        CheckpointState,
        Diagnostics,
        MissionState,
        GroundKnowledgeState,
        ControllerState,
        SpacecraftState,
        StepResult,
    )
    prohibited = {"EPSIntervalInputs", "EPSIntervalResult"}

    for domain_type in authoritative_types:
        assert prohibited.isdisjoint(
            str(field.type) for field in fields(domain_type)
        )


def test_eps_system_is_pure_composition_without_engine_dependencies() -> None:
    tree = ast.parse(
        EPS_SYSTEM_PATH.read_text(encoding="utf-8"),
        filename=str(EPS_SYSTEM_PATH),
    )
    imported_modules = {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    prohibited_modules = {
        "engine",
        "context",
        "controller_state",
        "mission",
        "diagnostics",
        "knowledge",
        "legacy",
    }
    assert imported_modules.isdisjoint(prohibited_modules)
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))

    prohibited_names = {
        "DEFAULT_CONFIG",
        "SimulationEngine",
        "SimulationContext",
        "OperationalMode",
        "FDIRState",
    }
    assert not any(
        isinstance(node, (ast.Name, ast.Attribute))
        and (
            node.id if isinstance(node, ast.Name) else node.attr
        ) in prohibited_names
        for node in ast.walk(tree)
    )

    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    # Task 04A: both explicit duration APIs must reach the single composition.
    for wrapper in ("compute_eps_interval_transition", "compute_eps_substep_transition"):
        wrapper_calls = [n.func.id for n in ast.walk(functions[wrapper])
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        assert wrapper_calls.count("_compute_eps_transition") == 1
    composite = functions["_compute_eps_transition"]
    called_names = [
        node.func.id
        for node in ast.walk(composite)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert called_names.count("compute_solar_generation") == 1
    assert called_names.count("compute_battery_transition") == 1
    assert not any(
        isinstance(node, ast.BinOp)
        for statement in composite.body
        for node in ast.walk(statement)
    )


def test_engine_eps_path_is_stateless_and_delegates_existing_physics() -> None:
    tree = ast.parse(
        ENGINE_PATH.read_text(encoding="utf-8"),
        filename=str(ENGINE_PATH),
    )
    engine = SimulationEngine()

    assert SimulationEngine.__slots__ == ()
    assert not hasattr(engine, "__dict__")
    with pytest.raises(AttributeError):
        engine.eps_inputs = _eps_inputs()

    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "eps" not in imported_modules
    assert "solar" not in imported_modules
    assert "power_loads" not in imported_modules
    assert "random" not in imported_modules

    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert {
        "DEFAULT_CONFIG",
        "Simulator",
        "SatelliteState",
        "cos",
        "base_bus_w",
        "obc_w",
        "adcs_w",
        "payload_w",
        "communications_w",
        "thermal_control_w",
        "propulsion_w",
    }.isdisjoint(identifiers)
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "eps_inputs"
        for node in ast.walk(tree)
    )

    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    physical = functions["_physical_integration"]
    composite_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "compute_eps_interval_transition"
    ]
    assert len(composite_calls) == 1
    assert composite_calls[0] in set(ast.walk(physical))


def test_eps_system_defines_exact_exports() -> None:
    from ops_sim.v5 import eps_system

    assert eps_system.__all__ == [
        "EPSIntervalInputs",
        "EPSIntervalResult",
        "compute_eps_interval_transition",
    ]
