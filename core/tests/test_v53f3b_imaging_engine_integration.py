"""Transactional imaging-engine integration for V5.3F3B."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from inspect import Parameter, signature
from pathlib import Path
import subprocess

import pytest

from examples.v52_integrated_eps_thermal_demo import (
    build_demo_context,
    build_step_inputs,
)
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.degradation import SolarDegradationForcingInput
import ops_sim.v5.engine as engine_module
from ops_sim.v5.engine import (
    STEP_PHASE_ORDER,
    ImagingEngineStepAttempt,
    SimulationEngine,
    SimulationPhase,
    StepResult,
)
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ADCSSlewAnchorId,
    CommandId,
    DataProductId,
    ImagingRequestId,
    MissionRequestId,
    ObservationOpportunityId,
    ParameterId,
    PlanId,
    ThermalNodeId,
    WorldEventId,
)
import ops_sim.v5.imaging_authorization as authorization_module
from ops_sim.v5.imaging_authorization import (
    ImagingExecutionAuthorizationResult,
)
from ops_sim.v5.imaging_execution import (
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from ops_sim.v5.imaging_feasibility import ObservationAcquisitionCandidate
from ops_sim.v5.imaging_resources import AcquisitionEPSIntervalEnvironment
from ops_sim.v5.mission import MissionState
from ops_sim.v5.observation import ObservationOpportunity, ObservationPointing
from ops_sim.v5.observation_feasibility import (
    ObservationManeuverCandidate,
    ScheduledObservationExecution,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
)
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.thermal import (
    ThermalIntervalInputs,
    ThermalNodeBoundaryInput,
)
from ops_sim.v5.thermal_coupling import (
    ThermalHeatSourceInputs,
    ThermalNodeHeatSourceInput,
)
from ops_sim.v5.thermal_routing import (
    ComponentHeatRoute,
    ComponentHeatRoutingConfig,
    ElectricalLoadComponent,
)


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
F3B_COMMIT = "c74e52faedf9af804277d93c83f46ebc318df893"
COMPONENTS = tuple(ElectricalLoadComponent)


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


def _anchor(
    name: str,
    angle_deg: object,
    elapsed_seconds: object,
) -> BoresightSlewTimeAnchor:
    prefix = f"adcs.slew-envelope.{name}"
    return BoresightSlewTimeAnchor(
        ADCSSlewAnchorId(name),
        _parameter(f"{prefix}.angular-separation", "deg", angle_deg),
        _parameter(f"{prefix}.elapsed-time", "s", elapsed_seconds),
    )


def _agile_config() -> AgilePointingConfig:
    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir",
            "deg",
            45.0,
        ),
        _parameter("adcs.pointing.post-slew-settling-time", "s", 5.0),
        (_anchor("zero", 0.0, 0.0), _anchor("ninety", 90.0, 75.0)),
    )


def _context(
    *,
    simulation_time_seconds: int = 100,
    dt_seconds: int = 23,
    max_discharge_w: object = 150.0,
    agile_config: AgilePointingConfig | None = None,
    thermal_network=None,
):
    context = build_demo_context()
    spacecraft_config = context.inputs.spacecraft_configuration
    battery_config = spacecraft_config.eps.battery
    battery_config = replace(
        battery_config,
        max_discharge_output_power_w=replace(
            battery_config.max_discharge_output_power_w,
            value=max_discharge_w,
        ),
    )
    eps_config = replace(spacecraft_config.eps, battery=battery_config)
    adcs_config = replace(
        spacecraft_config.adcs,
        agile_pointing=(
            _agile_config() if agile_config is None else agile_config
        ),
    )
    thermal_config = spacecraft_config.thermal
    if thermal_network is not None:
        thermal_config = replace(thermal_config, network=thermal_network)
    spacecraft_config = replace(
        spacecraft_config,
        eps=eps_config,
        adcs=adcs_config,
        thermal=thermal_config,
    )
    numerical_config = replace(
        context.inputs.numerical_config,
        timestep_seconds=dt_seconds,
        geometry_sample_seconds=1,
        checkpoint_interval_seconds=dt_seconds,
    )
    inputs = replace(
        context.inputs,
        spacecraft_configuration=spacecraft_config,
        numerical_config=numerical_config,
    )
    return replace(
        context,
        simulation_time_seconds=simulation_time_seconds,
        inputs=inputs,
    )


def _direction(
    x: object = 0.0,
    y: object = 0.0,
    z: object = 1.0,
    *,
    frame: str = "f3b-common-frame",
) -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId(frame),
        x,
        y,
        z,
    )


def _previous_execution(
    *,
    direction: CommonFrameBoresightDirection | None = None,
) -> ScheduledObservationExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("f3b-previous"),
        ImagingRequestId("f3b-previous-request"),
        0,
        60,
        20,
        ObservationPointing(10.0, 0.0),
    )
    return ScheduledObservationExecution(
        ObservationManeuverCandidate(
            opportunity,
            _direction() if direction is None else direction,
        ),
        0,
    )


def _execution(
    *,
    scheduled_start_seconds: int = 100,
    duration_seconds: int = 23,
    view_angle_deg: object = 10.0,
    direction: CommonFrameBoresightDirection | None = None,
) -> ScheduledObservationAcquisitionExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("f3b-next"),
        ImagingRequestId("f3b-next-request"),
        100,
        300,
        duration_seconds,
        ObservationPointing(view_angle_deg, 0.0),
    )
    candidate = ObservationAcquisitionCandidate(
        ObservationManeuverCandidate(
            opportunity,
            _direction() if direction is None else direction,
        ),
        OpticalAcquisitionInput(
            20.0,
            40.0,
            duration_seconds,
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        ),
    )
    return ScheduledObservationAcquisitionExecution(
        candidate,
        scheduled_start_seconds,
    )


def _loads(
    *,
    base_bus_w: object = 1.0,
    obc_w: object = 2.0,
    adcs_w: object = 3.0,
    payload_w: object = 4.0,
    communications_w: object = 5.0,
    thermal_control_w: object = 6.0,
    propulsion_w: object = 7.0,
) -> PowerLoadBreakdown:
    return PowerLoadBreakdown(
        base_bus_w,
        obc_w,
        adcs_w,
        payload_w,
        communications_w,
        thermal_control_w,
        propulsion_w,
    )


def _zero_loads(*, base_bus_w: object = 0.0) -> PowerLoadBreakdown:
    return _loads(
        base_bus_w=base_bus_w,
        obc_w=0.0,
        adcs_w=0.0,
        payload_w=0.0,
        communications_w=0.0,
        thermal_control_w=0.0,
        propulsion_w=0.0,
    )


def _environment(
    loads: PowerLoadBreakdown | None = None,
) -> AcquisitionEPSIntervalEnvironment:
    return AcquisitionEPSIntervalEnvironment(
        False,
        0.0,
        _loads() if loads is None else loads,
    )


def _routing() -> ComponentHeatRoutingConfig:
    return ComponentHeatRoutingConfig(
        tuple(
            ComponentHeatRoute(
                component,
                ThermalNodeId(
                    "payload"
                    if component is ElectricalLoadComponent.PAYLOAD
                    else "bus"
                ),
                _parameter(
                    f"thermal.routing.{component.value}.retained-heat-fraction",
                    "1",
                    0.5,
                ),
            )
            for component in COMPONENTS
        )
    )


def _thermal_inputs(context) -> ThermalIntervalInputs:
    temperature_by_id = {
        node.node_id: node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
    }
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(
                node.node_id,
                temperature_by_id[node.node_id],
            )
            for node in (
                context.inputs.spacecraft_configuration.thermal.network.nodes
            )
        )
    )


def _external_heat_sources(context) -> ThermalHeatSourceInputs:
    return ThermalHeatSourceInputs(
        tuple(
            ThermalNodeHeatSourceInput(node.node_id, 0.0, 0.0, 0.0, 0.0)
            for node in (
                context.inputs.spacecraft_configuration.thermal.network.nodes
            )
        )
    )


def _arguments(
    *,
    context=None,
    previous_execution=None,
    execution=None,
    environment=None,
    routing_config=None,
    thermal_inputs=None,
    external_heat_sources=None,
    solar_degradation_forcing=None,
) -> dict[str, object]:
    active_context = _context() if context is None else context
    return {
        "context": active_context,
        "previous_execution": (
            _previous_execution()
            if previous_execution is None
            else previous_execution
        ),
        "execution": (
            _execution(
                scheduled_start_seconds=(
                    active_context.simulation_time_seconds
                ),
                duration_seconds=(
                    active_context.inputs.numerical_config.timestep_seconds
                ),
            )
            if execution is None
            else execution
        ),
        "environment": (
            _environment() if environment is None else environment
        ),
        "routing_config": (
            _routing() if routing_config is None else routing_config
        ),
        "thermal_inputs": (
            _thermal_inputs(active_context)
            if thermal_inputs is None
            else thermal_inputs
        ),
        "external_heat_sources": (
            _external_heat_sources(active_context)
            if external_heat_sources is None
            else external_heat_sources
        ),
        "solar_degradation_forcing": solar_degradation_forcing,
    }


def _step(
    *,
    engine: SimulationEngine | None = None,
    **changes: object,
) -> ImagingEngineStepAttempt:
    active_engine = SimulationEngine() if engine is None else engine
    return active_engine.step_imaging(**_arguments(**changes))


def _authoritative_references(context) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
    knowledge = context.ground_knowledge_state
    return (
        spacecraft,
        spacecraft.battery,
        spacecraft.propulsion,
        spacecraft.thermal,
        *spacecraft.thermal.node_states,
        spacecraft.degradation,
        spacecraft.degradation.battery,
        spacecraft.degradation.solar,
        spacecraft.onboard,
        spacecraft.data_storage,
        knowledge,
        knowledge.latest_telemetry,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _assert_authoritative_rollback(context, before, references) -> None:
    assert context == before
    assert all(
        actual is original
        for actual, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def _hot_payload_network():
    network = _context().inputs.spacecraft_configuration.thermal.network
    nodes = []
    for node in network.nodes:
        if node.node_id == ThermalNodeId("payload"):
            node = replace(
                node,
                heat_capacity_j_per_k=replace(
                    node.heat_capacity_j_per_k,
                    value=1.0,
                ),
                emissivity=replace(node.emissivity, value=0.0),
            )
        nodes.append(node)
    return replace(network, nodes=tuple(nodes))


def _populated_context():
    return replace(
        _context(),
        mission_state=MissionState(
            (MissionRequestId("f3b-pending"),),
            (MissionRequestId("f3b-completed"),),
            (DataProductId("f3b-existing-product"),),
            PlanId("f3b-active-plan"),
            (CommandId("f3b-existing-command"),),
            (WorldEventId("f3b-resolved-event"),),
        ),
    )


def _parse_engine() -> ast.Module:
    return ast.parse(
        ENGINE_PATH.read_text(encoding="utf-8"),
        filename=str(ENGINE_PATH),
    )


def _engine_method(tree: ast.Module, name: str) -> ast.FunctionDef:
    engine = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SimulationEngine"
    )
    return next(
        node
        for node in engine.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _called_names(node: ast.AST) -> tuple[str, ...]:
    names = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            names.append(item.func.id)
        elif isinstance(item.func, ast.Attribute):
            names.append(item.func.attr)
    return tuple(names)


def test_step_imaging_and_generic_step_signatures_are_exact() -> None:
    imaging_parameters = signature(SimulationEngine.step_imaging).parameters
    assert tuple(imaging_parameters) == (
        "self",
        "context",
        "previous_execution",
        "execution",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
        "solar_degradation_forcing",
    )
    for name in ("self", "context", "previous_execution", "execution"):
        assert imaging_parameters[name].kind is Parameter.POSITIONAL_OR_KEYWORD
        assert imaging_parameters[name].default is Parameter.empty
    for name in (
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
    ):
        assert imaging_parameters[name].kind is Parameter.KEYWORD_ONLY
        assert imaging_parameters[name].default is Parameter.empty
    solar = imaging_parameters["solar_degradation_forcing"]
    assert solar.kind is Parameter.KEYWORD_ONLY
    assert solar.default is None

    generic_parameters = signature(SimulationEngine.step).parameters
    assert tuple(generic_parameters) == (
        "self",
        "context",
        "eps_inputs",
        "thermal_inputs",
        "heat_source_inputs",
        "solar_degradation_forcing",
    )
    assert generic_parameters["context"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        parameter.kind is Parameter.KEYWORD_ONLY
        and parameter.default is None
        for name, parameter in generic_parameters.items()
        if name not in {"self", "context"}
    )


def test_attempt_has_exact_frozen_slotted_required_fields() -> None:
    attempt = _step()

    assert tuple(field.name for field in fields(ImagingEngineStepAttempt)) == (
        "authorization_result",
        "step_result",
    )
    assert ImagingEngineStepAttempt.__dataclass_params__.frozen
    assert not hasattr(attempt, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(ImagingEngineStepAttempt)
    )
    with pytest.raises(FrozenInstanceError):
        attempt.step_result = None


def test_attempt_requires_exact_types_and_status_result_pairing() -> None:
    authorized = _step()
    sequence = _step(execution=_execution(view_angle_deg=50.0))
    shortfall_context = _context(max_discharge_w=60.0)
    shortfall = _step(
        context=shortfall_context,
        environment=_environment(_zero_loads()),
    )

    with pytest.raises(TypeError, match="authorization_result"):
        ImagingEngineStepAttempt(object(), None)
    with pytest.raises(TypeError, match="step_result"):
        replace(authorized, step_result=object())
    with pytest.raises(ValueError):
        replace(authorized, step_result=None)
    with pytest.raises(ValueError):
        ImagingEngineStepAttempt(
            sequence.authorization_result,
            authorized.step_result,
        )
    with pytest.raises(ValueError):
        ImagingEngineStepAttempt(
            shortfall.authorization_result,
            authorized.step_result,
        )


def test_authorized_attempt_enforces_exact_timing_and_proposal_identities() -> None:
    attempt = _step()
    authorization = attempt.authorization_result
    step = attempt.step_result
    assert step is not None

    mismatched_steps = (
        replace(
            step,
            start_time_seconds=step.start_time_seconds + 1,
            end_time_seconds=step.end_time_seconds + 1,
        ),
        replace(
            step,
            end_time_seconds=step.start_time_seconds + step.dt_seconds + 1,
            dt_seconds=step.dt_seconds + 1,
        ),
        replace(step, eps_result=deepcopy(step.eps_result)),
        replace(
            step,
            eps_capability_result=deepcopy(step.eps_capability_result),
        ),
        replace(
            step,
            thermal_coupling_result=(
                deepcopy(step.thermal_coupling_result)
            ),
        ),
    )
    for mismatched in mismatched_steps:
        with pytest.raises(ValueError):
            ImagingEngineStepAttempt(authorization, mismatched)


@pytest.mark.parametrize(
    "argument_name",
    (
        "previous_execution",
        "execution",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
        "solar_degradation_forcing",
    ),
)
def test_imaging_preflight_requires_exact_reviewed_input_types(
    argument_name,
    monkeypatch,
) -> None:
    arguments = _arguments()
    arguments[argument_name] = object()
    monkeypatch.setattr(
        engine_module,
        "evaluate_imaging_engine_step_authorization",
        lambda *args: pytest.fail("F2 must not be reached"),
    )

    with pytest.raises(TypeError, match=argument_name):
        SimulationEngine().step_imaging(**arguments)


def test_completed_context_validation_precedes_imaging_preflight(
    monkeypatch,
) -> None:
    context = _context()
    object.__setattr__(context.spacecraft_state.battery, "energy_wh", -1.0)
    arguments = _arguments(context=context)
    arguments["previous_execution"] = object()

    def fail_prepare(*args, **kwargs):
        pytest.fail("imaging preflight must follow context validation")

    monkeypatch.setattr(
        SimulationEngine,
        "_prepare_imaging_physical_integration_handler",
        fail_prepare,
    )

    with pytest.raises(ValueError, match="energy_wh"):
        SimulationEngine().step_imaging(**arguments)


def test_f2_runs_only_in_physical_phase_on_restored_working_context(
    monkeypatch,
) -> None:
    authoritative = _context()
    arguments = _arguments(context=authoritative)
    original_f2 = engine_module.evaluate_imaging_engine_step_authorization
    events = []

    class ObservingEngine(SimulationEngine):
        def _execute_phase(self, phase, context, interval, handler):
            events.append(("phase", phase, context, interval))
            return super()._execute_phase(phase, context, interval, handler)

    def f2(context, *args, **kwargs):
        events.append(("f2", context))
        assert events[-2][0:2] == (
            "phase",
            SimulationPhase.PHYSICAL_INTEGRATION,
        )
        assert context is not authoritative
        assert context.inputs is authoritative.inputs
        assert context == authoritative
        return original_f2(context, *args, **kwargs)

    monkeypatch.setattr(
        engine_module,
        "evaluate_imaging_engine_step_authorization",
        f2,
    )

    attempt = ObservingEngine().step_imaging(**arguments)

    assert attempt.step_result is not None
    assert sum(event[0] == "f2" for event in events) == 1
    assert tuple(
        event[1] for event in events if event[0] == "phase"
    ) == STEP_PHASE_ORDER


def test_authorized_path_has_one_causal_chain_and_one_commit(
    monkeypatch,
) -> None:
    calls = []
    original_f2 = engine_module.evaluate_imaging_engine_step_authorization
    original_e1 = authorization_module.evaluate_observation_acquisition_eps
    original_e2 = (
        authorization_module
        .evaluate_observation_acquisition_single_interval_thermal_proposal
    )
    original_tail = engine_module._complete_coupled_physical_integration
    original_commit = SimulationEngine._commit

    def f2(*args, **kwargs):
        calls.append("f2")
        return original_f2(*args, **kwargs)

    def e1(*args, **kwargs):
        calls.append("e1")
        return original_e1(*args, **kwargs)

    def e2(*args, **kwargs):
        calls.append("e2")
        return original_e2(*args, **kwargs)

    def tail(*args, **kwargs):
        calls.append("tail")
        return original_tail(*args, **kwargs)

    def commit(original, working):
        calls.append("commit")
        return original_commit(original, working)

    def generic_physical(*args, **kwargs):
        pytest.fail("generic _physical_integration must not run")

    monkeypatch.setattr(
        engine_module,
        "evaluate_imaging_engine_step_authorization",
        f2,
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_eps",
        e1,
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        e2,
    )
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        tail,
    )
    monkeypatch.setattr(
        SimulationEngine,
        "_physical_integration",
        staticmethod(generic_physical),
    )
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(commit),
    )

    attempt = _step()

    assert attempt.step_result is not None
    assert {name: calls.count(name) for name in set(calls)} == {
        "f2": 1,
        "e1": 1,
        "e2": 1,
        "tail": 1,
        "commit": 1,
    }
    assert calls.index("f2") < calls.index("e1")
    assert calls.index("e1") < calls.index("e2")
    assert calls.index("e2") < calls.index("tail")
    assert calls[-1] == "commit"


def test_authorized_attempt_reuses_exact_f2_proposals_and_commits_endpoint() -> None:
    context = _context()
    original_battery_energy = context.spacecraft_state.battery.energy_wh

    attempt = _step(context=context)
    authorization = attempt.authorization_result
    result = attempt.step_result

    assert authorization.status is ImagingExecutionAuthorizationStatus.AUTHORIZED
    assert type(result) is StepResult
    assert result.start_time_seconds == 100
    assert result.end_time_seconds == 123
    assert result.dt_seconds == 23
    assert result.executed_phases == STEP_PHASE_ORDER
    assert result.start_time_seconds == (
        authorization.execution.scheduled_start_seconds
    )
    assert result.dt_seconds == (
        authorization.execution.candidate.acquisition_input
        .imaging_duration_seconds
    )
    assert result.eps_result is authorization.electrical_result.eps_result
    assert result.eps_capability_result is (
        authorization.electrical_result.eps_capability_result
    )
    assert result.thermal_coupling_result is (
        authorization.thermal_proposal.eps_thermal_coupling_result
    )
    assert result.battery_degradation_result is not None
    assert result.battery_capacity_reconciliation_result is not None
    assert result.battery_degradation_result.throughput_increment_wh > 0
    assert (
        result.battery_degradation_result.end_cumulative_energy_throughput_wh
        == context.spacecraft_state.degradation.battery
        .cumulative_energy_throughput_wh
    )
    assert context.spacecraft_state.battery.energy_wh == (
        result.battery_capacity_reconciliation_result
        .authoritative_end_energy_wh
    )
    assert context.spacecraft_state.battery.energy_wh < original_battery_energy
    transition_by_id = {
        item.node_id: item.end_temperature_k
        for item in result.thermal_coupling_result.thermal_result.node_transitions
    }
    assert {
        item.node_id: item.temperature_k
        for item in context.spacecraft_state.thermal.node_states
    } == transition_by_id
    assert context.simulation_time_seconds == 123
    assert context.diagnostics.completed_steps == 1


def test_optional_solar_degradation_is_applied_once_after_f2(
    monkeypatch,
) -> None:
    context = _context()
    calls = []
    original = engine_module.compute_explicit_solar_degradation_transition

    def solar(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        engine_module,
        "compute_explicit_solar_degradation_transition",
        solar,
    )

    attempt = _step(
        context=context,
        solar_degradation_forcing=SolarDegradationForcingInput(0.01),
    )
    result = attempt.step_result

    assert result is not None
    assert len(calls) == 1
    assert result.solar_degradation_result is not None
    assert result.solar_degradation_result.start_generation_retention == 1.0
    assert result.solar_degradation_result.end_generation_retention == 0.99
    assert context.spacecraft_state.degradation.solar.generation_retention == 0.99
    assert result.eps_capability_result.solar_generation_retention == 1.0


@pytest.mark.parametrize(
    ("case", "expected_electrical_status"),
    (
        ("sequence", None),
        ("impossible", "full-service-impossible"),
        ("allocation", "service-allocation-required"),
    ),
)
def test_supported_nonauthorization_returns_without_any_commit_work(
    case,
    expected_electrical_status,
    monkeypatch,
) -> None:
    if case == "sequence":
        context = _context()
        changes = {"execution": _execution(view_angle_deg=50.0)}
        expected_status = ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE
    elif case == "impossible":
        context = _context(max_discharge_w=60.0)
        changes = {"environment": _environment(_zero_loads())}
        expected_status = (
            ImagingExecutionAuthorizationStatus
            .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
        )
    else:
        context = _context(max_discharge_w=150.0)
        changes = {
            "environment": _environment(_zero_loads(base_bus_w=100.0))
        }
        expected_status = (
            ImagingExecutionAuthorizationStatus
            .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
        )
    before = deepcopy(context)
    references = _authoritative_references(context)

    def forbidden(*args, **kwargs):
        pytest.fail("post-authorization transaction work must not run")

    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        forbidden,
    )
    monkeypatch.setattr(
        engine_module,
        "compute_battery_degradation_transition",
        forbidden,
    )
    monkeypatch.setattr(
        engine_module,
        "compute_battery_capacity_reconciliation",
        forbidden,
    )
    monkeypatch.setattr(StepResult, "__post_init__", forbidden)
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(forbidden),
    )

    attempt = _step(context=context, **changes)

    assert type(attempt) is ImagingEngineStepAttempt
    assert attempt.authorization_result.status is expected_status
    assert attempt.step_result is None
    if expected_electrical_status is None:
        assert attempt.authorization_result.electrical_result.eps_result is None
    else:
        assert (
            attempt.authorization_result.electrical_result.service_bounds
            .status.value
            == expected_electrical_status
        )
    _assert_authoritative_rollback(context, before, references)


def test_current_boundary_failure_propagates_with_complete_rollback(
    monkeypatch,
) -> None:
    context = _context(simulation_time_seconds=101)
    before = deepcopy(context)
    references = _authoritative_references(context)
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        lambda *args, **kwargs: pytest.fail("tail must not be reached"),
    )

    with pytest.raises(ValueError, match="scheduled start.*current context"):
        _step(
            context=context,
            execution=_execution(scheduled_start_seconds=100),
        )

    _assert_authoritative_rollback(context, before, references)


def test_duration_mismatch_propagates_with_complete_rollback(
    monkeypatch,
) -> None:
    context = _context(dt_seconds=23)
    before = deepcopy(context)
    references = _authoritative_references(context)
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        lambda *args, **kwargs: pytest.fail("tail must not be reached"),
    )

    with pytest.raises(ValueError, match="duration.*engine timestep"):
        _step(context=context, execution=_execution(duration_seconds=22))

    _assert_authoritative_rollback(context, before, references)


def test_unsupported_adcs_frame_failure_propagates_with_rollback(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    previous = _previous_execution(
        direction=_direction(frame="f3b-other-frame"),
    )
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        lambda *args, **kwargs: pytest.fail("tail must not be reached"),
    )

    with pytest.raises(ValueError, match="frame"):
        _step(context=context, previous_execution=previous)

    _assert_authoritative_rollback(context, before, references)


def test_invalid_nested_acquisition_composition_fails_before_physics(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    execution = deepcopy(_execution())
    object.__setattr__(
        execution.candidate.acquisition_input,
        "effective_cross_track_width_m",
        -1.0,
    )
    monkeypatch.setattr(
        engine_module,
        "evaluate_imaging_engine_step_authorization",
        lambda *args: pytest.fail("F2 must not receive invalid composition"),
    )
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        lambda *args, **kwargs: pytest.fail("tail must not be reached"),
    )

    with pytest.raises(ValueError, match="effective_cross_track_width_m"):
        _step(context=context, execution=execution)

    _assert_authoritative_rollback(context, before, references)


def test_f2_e2_failure_propagates_with_complete_rollback(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    class ExpectedE2Error(RuntimeError):
        pass

    def fail(*args, **kwargs):
        raise ExpectedE2Error("synthetic E2 failure")

    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        fail,
    )
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        lambda *args, **kwargs: pytest.fail("tail must not be reached"),
    )

    with pytest.raises(ExpectedE2Error, match="synthetic E2 failure"):
        _step(context=context)

    _assert_authoritative_rollback(context, before, references)


def test_degradation_failure_after_authorization_rolls_back(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    f2_calls = []
    original_f2 = engine_module.evaluate_imaging_engine_step_authorization

    class ExpectedDegradationError(RuntimeError):
        pass

    def f2(*args, **kwargs):
        f2_calls.append(1)
        return original_f2(*args, **kwargs)

    def fail(*args, **kwargs):
        raise ExpectedDegradationError("synthetic degradation failure")

    monkeypatch.setattr(
        engine_module,
        "evaluate_imaging_engine_step_authorization",
        f2,
    )
    monkeypatch.setattr(
        engine_module,
        "compute_battery_degradation_transition",
        fail,
    )

    with pytest.raises(
        ExpectedDegradationError,
        match="synthetic degradation failure",
    ):
        _step(context=context)

    assert f2_calls == [1]
    _assert_authoritative_rollback(context, before, references)


def test_reconciliation_failure_after_authorization_rolls_back(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    class ExpectedReconciliationError(RuntimeError):
        pass

    def fail(*args, **kwargs):
        raise ExpectedReconciliationError("synthetic reconciliation failure")

    monkeypatch.setattr(
        engine_module,
        "compute_battery_capacity_reconciliation",
        fail,
    )

    with pytest.raises(
        ExpectedReconciliationError,
        match="synthetic reconciliation failure",
    ):
        _step(context=context)

    _assert_authoritative_rollback(context, before, references)


def test_final_working_context_failure_rolls_back_authorized_proposal() -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    class CorruptingEngine(SimulationEngine):
        @staticmethod
        def _advance_clock(working, interval):
            SimulationEngine._advance_clock(working, interval)
            working.spacecraft_state.battery.energy_wh = -1.0

    with pytest.raises(ValueError, match="energy_wh"):
        _step(engine=CorruptingEngine(), context=context)

    _assert_authoritative_rollback(context, before, references)


def test_step_result_failure_rolls_back_authorized_proposal(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    commit_calls = []

    class ExpectedStepResultError(RuntimeError):
        pass

    def fail_result(self):
        raise ExpectedStepResultError("synthetic StepResult failure")

    def commit(*args):
        commit_calls.append(args)
        pytest.fail("commit must not be reached")

    monkeypatch.setattr(StepResult, "__post_init__", fail_result)
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(commit),
    )

    with pytest.raises(ExpectedStepResultError, match="StepResult"):
        _step(context=context)

    assert commit_calls == []
    _assert_authoritative_rollback(context, before, references)


def test_positive_endpoint_beyond_survival_range_can_commit() -> None:
    context = _context(thermal_network=_hot_payload_network())

    attempt = _step(context=context)
    result = attempt.step_result
    payload_transition = next(
        transition
        for transition in result.thermal_coupling_result.thermal_result
        .node_transitions
        if transition.node_id == ThermalNodeId("payload")
    )
    payload_config = next(
        node
        for node in context.inputs.spacecraft_configuration.thermal.network.nodes
        if node.node_id == ThermalNodeId("payload")
    )

    assert attempt.authorization_result.status is (
        ImagingExecutionAuthorizationStatus.AUTHORIZED
    )
    assert payload_transition.end_temperature_k > (
        payload_config.survival_max_temperature_k.value
    )
    assert next(
        node.temperature_k
        for node in context.spacecraft_state.thermal.node_states
        if node.node_id == ThermalNodeId("payload")
    ) == payload_transition.end_temperature_k


def test_success_preserves_mission_and_data_boundaries() -> None:
    context = _populated_context()
    mission_before = deepcopy(context.mission_state)
    controller_before = deepcopy(context.controller_state)
    knowledge_before = deepcopy(context.ground_knowledge_state)
    propulsion_before = deepcopy(context.spacecraft_state.propulsion)
    onboard_before = deepcopy(context.spacecraft_state.onboard)

    attempt = _step(context=context)
    authorization = attempt.authorization_result
    acquisition = (
        authorization.electrical_result.acquisition_evaluation
        .acquisition_result
    )

    assert context.mission_state == mission_before
    assert context.controller_state == controller_before
    assert context.ground_knowledge_state == knowledge_before
    assert context.spacecraft_state.propulsion == propulsion_before
    assert context.spacecraft_state.onboard == onboard_before
    assert context.mission_state.pending_request_ids == (
        MissionRequestId("f3b-pending"),
    )
    assert context.mission_state.completed_request_ids == (
        MissionRequestId("f3b-completed"),
    )
    assert context.mission_state.data_product_ids == (
        DataProductId("f3b-existing-product"),
    )
    assert type(
        authorization.execution.candidate.maneuver_candidate.opportunity
        .request_id
    ) is ImagingRequestId
    assert authorization.execution.candidate.maneuver_candidate.opportunity.request_id != (
        MissionRequestId("f3b-next-request")
    )
    assert acquisition.total_equivalent_samples == 1000.0
    assert acquisition.uncompressed_equivalent_bits == 12000.0
    assert acquisition.uncompressed_equivalent_bytes == 1500.0
    assert {
        field.name for field in fields(ImagingEngineStepAttempt)
    } == {"authorization_result", "step_result"}
    assert {
        field.name for field in fields(StepResult)
    }.isdisjoint(
        {
            "stored_bytes",
            "data_product_id",
            "mission_request_id",
            "request_completed",
            "controller_decision",
        }
    )


def test_checkpoint_schema_four_and_explicit_replay_are_equivalent() -> None:
    direct_context = _populated_context()
    checkpoint_source = _populated_context()
    checkpoint = CheckpointState.from_context(checkpoint_source)
    restored_context = checkpoint.restore(checkpoint_source.inputs)
    shared_inputs = _arguments(context=direct_context)
    shared_inputs.pop("context")

    direct_attempt = SimulationEngine().step_imaging(
        direct_context,
        **shared_inputs,
    )
    replay_attempt = SimulationEngine().step_imaging(
        restored_context,
        **shared_inputs,
    )

    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    assert checkpoint.schema_version == 5
    assert direct_attempt == replay_attempt
    assert direct_context == restored_context
    assert {
        field.name for field in fields(CheckpointState)
    }.isdisjoint(
        {
            "imaging_execution",
            "imaging_attempt",
            "authorization_result",
            "stored_image",
        }
    )


def test_generic_f3a_coupled_characterization_remains_exact() -> None:
    context = build_demo_context()
    eps_inputs, thermal_inputs, heat_inputs = build_step_inputs(0)

    result = SimulationEngine().step(
        context,
        eps_inputs=eps_inputs,
        thermal_inputs=thermal_inputs,
        heat_source_inputs=heat_inputs,
    )

    assert result.eps_result.battery.end_energy_wh == pytest.approx(
        251.68666666666667
    )
    assert result.eps_result.battery.charge_input_w == 110
    assert result.eps_result.battery.unmet_load_w == 0.0
    assert [
        transition.end_temperature_k
        for transition in result.thermal_coupling_result.thermal_result
        .node_transitions
    ] == pytest.approx(
        [294.9711357979018, 292.9738083288189, 290.964853888334]
    )
    assert result.battery_degradation_result.throughput_increment_wh == (
        pytest.approx(1.6866666666666668)
    )
    assert result.battery_capacity_reconciliation_result is not None
    assert context.simulation_time_seconds == 60
    assert context.diagnostics.completed_steps == 1


def test_f3b_engine_exports_are_historical_and_remain_live() -> None:
    expected_f3b_exports = [
        "STEP_PHASE_ORDER",
        "ImagingEngineStepAttempt",
        "SimulationEngine",
        "SimulationPhase",
        "StepResult",
    ]
    historical_source = subprocess.run(
        ["git", "show", f"{F3B_COMMIT}:ops_sim/v5/engine.py"],
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

    assert ast.literal_eval(historical_exports.value) == expected_f3b_exports
    assert all(name in engine_module.__all__ for name in expected_f3b_exports)
    assert SimulationEngine.__slots__ == ()
    assert "_ImagingExecutionNotAuthorized" not in engine_module.__all__
    assert "_prepare_imaging_physical_integration_handler" not in (
        engine_module.__all__
    )


def test_step_imaging_catches_only_private_nonauthorization_control() -> None:
    step_imaging = _engine_method(_parse_engine(), "step_imaging")
    handlers = [
        handler
        for node in ast.walk(step_imaging)
        if isinstance(node, ast.Try)
        for handler in node.handlers
    ]

    assert len(handlers) == 1
    assert isinstance(handlers[0].type, ast.Name)
    assert handlers[0].type.id == "_ImagingExecutionNotAuthorized"


def test_imaging_path_uses_one_transaction_loop_and_one_shared_tail() -> None:
    tree = _parse_engine()
    step_imaging = _engine_method(tree, "step_imaging")
    prepare = _engine_method(
        tree,
        "_prepare_imaging_physical_integration_handler",
    )
    kernel = _engine_method(tree, "_run_transaction")
    generic_physical = _engine_method(tree, "_physical_integration")

    assert _called_names(step_imaging).count("_run_transaction") == 1
    assert not any(
        isinstance(node, (ast.For, ast.While))
        for node in ast.walk(step_imaging)
    )
    phase_loops = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "STEP_PHASE_ORDER"
    ]
    assert len(phase_loops) == 1
    assert phase_loops[0] in tuple(ast.walk(kernel))
    assert _called_names(kernel).count("StepResult") == 1
    assert _called_names(prepare).count(
        "evaluate_imaging_engine_step_authorization"
    ) == 1
    assert _called_names(prepare).count(
        "_complete_coupled_physical_integration"
    ) == 1
    assert "_physical_integration" not in _called_names(prepare)
    assert _called_names(generic_physical).count(
        "_complete_coupled_physical_integration"
    ) == 1
    assert sum(
        isinstance(node, ast.FunctionDef)
        and node.name == "_complete_coupled_physical_integration"
        for node in ast.walk(tree)
    ) == 1


def test_imaging_integration_adds_no_equation_duty_cycle_or_substep_logic() -> None:
    tree = _parse_engine()
    step_imaging = _engine_method(tree, "step_imaging")
    prepare = _engine_method(
        tree,
        "_prepare_imaging_physical_integration_handler",
    )
    integration_nodes = (step_imaging, prepare)
    calls = tuple(
        name for node in integration_nodes for name in _called_names(node)
    )
    identifiers = {
        item.id
        for node in integration_nodes
        for item in ast.walk(node)
        if isinstance(item, ast.Name)
    } | {
        item.attr
        for node in integration_nodes
        for item in ast.walk(node)
        if isinstance(item, ast.Attribute)
    }

    assert not any(
        isinstance(item, ast.BinOp)
        and isinstance(item.op, (ast.Mult, ast.Div, ast.FloorDiv))
        for node in integration_nodes
        for item in ast.walk(node)
    )
    assert identifiers.isdisjoint(
        {"round", "isclose", "duty_cycle", "substep", "partial_step"}
    )
    assert set(calls).isdisjoint(
        {
            "evaluate_observation_acquisition",
            "evaluate_observation_acquisition_eps",
            "evaluate_observation_acquisition_single_interval_thermal_proposal",
            "compute_eps_capability",
            "compute_eps_interval_transition",
            "compute_eps_thermal_interval_transition",
            "compute_battery_degradation_transition",
            "compute_battery_capacity_reconciliation",
        }
    )


def test_engine_dependency_direction_has_no_reverse_imaging_import() -> None:
    engine_tree = _parse_engine()
    imported_modules = {
        (node.module or "").partition(".")[0]
        for node in ast.walk(engine_tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert {
        "imaging_authorization",
        "imaging_execution",
        "imaging_resources",
        "thermal_routing",
    } <= imported_modules

    for name in (
        "imaging_authorization.py",
        "imaging_execution.py",
        "imaging_resources.py",
        "imaging_thermal.py",
    ):
        tree = ast.parse(
            (ROOT / "ops_sim" / "v5" / name).read_text(encoding="utf-8")
        )
        reverse_imports = {
            (node.module or "").partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert "engine" not in reverse_imports


def test_d263_through_d273_and_f3b_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s003 = sources.partition("### S003 ")[2].partition("### S004 ")[0]
    s004 = sources.partition("### S004 ")[2].partition("### S005 ")[0]
    s005 = sources.partition("### S005 ")[2].partition("### S006 ")[0]
    combined = " ".join((s003 + s004 + s005).lower().split())

    for number in range(263, 274):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D262 ") < decisions.index("## D263 ")
    expected_headings = (
        "## D263 — F3B adds dedicated step_imaging on the shared transaction "
        "kernel",
        "## D264 — F2 authorization is computed inside the restored working "
        "transaction",
        "## D265 — Supported nonauthorization aborts the transaction with no "
        "commit",
        "## D266 — Authorized imaging reuses exact F2 EPS/capability/thermal "
        "proposal objects",
        "## D267 — Imaging never recomputes generic EPS or thermal "
        "integration",
        "## D268 — Shared degradation/reconciliation tail completes authorized "
        "imaging once",
        "## D269 — Ordinary imaging/physical failures propagate with atomic "
        "rollback",
        "## D270 — Successful result means resource-served imaging interval "
        "committed",
        "## D271 — Mission completion, product/storage, and controller policy "
        "remain deferred",
        "## D272 — Imaging attempt evidence is transient; checkpoint schema "
        "remains 3",
        "## D273 — Variable-duration imaging remains deferred to V5.8",
    )
    assert all(decisions.count(heading) == 1 for heading in expected_headings)
    assert "v5.3f3b" in combined
    assert "no new physical source or value" in combined
    assert "no new equation" in combined
    assert "f2" in combined and "e1" in combined and "e2" in combined
    assert "reuse" in combined
    assert "degradation" in combined and "reconciliation" in combined
    assert "supported nonauthorization" in combined
    assert "no physical commit" in combined
    assert "resource-served imaging interval" in combined
    assert "mission" in combined and "product" in combined
    assert "storage" in combined
    assert "variable-duration" in combined and "averaging" in combined
    assert "schema 3" in combined
