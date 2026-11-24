"""Pure current-step imaging authorization for V5.3F2."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from inspect import Parameter, signature
from pathlib import Path
import subprocess

import pytest

from examples.v52_integrated_eps_thermal_demo import build_demo_context
import ops_sim.v5.imaging_authorization as authorization_module
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.adcs_config import (
    AgilePointingConfig,
    BoresightSlewTimeAnchor,
)
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    ADCSSlewAnchorId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
    ThermalNodeId,
)
from ops_sim.v5.imaging_authorization import (
    ImagingExecutionAuthorizationResult,
    evaluate_imaging_engine_step_authorization,
)
from ops_sim.v5.imaging_execution import (
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from ops_sim.v5.imaging_feasibility import ObservationAcquisitionCandidate
from ops_sim.v5.imaging_resources import (
    AcquisitionEPSIntervalEnvironment,
    AcquisitionServiceStatus,
    ObservationAcquisitionEPSResult,
)
from ops_sim.v5.imaging_thermal import (
    ObservationAcquisitionSingleIntervalThermalProposal,
)
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
    ServedPowerLedger,
)


ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_PATH = ROOT / "ops_sim" / "v5" / "imaging_authorization.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
COMPONENTS = tuple(ElectricalLoadComponent)
LOAD_FIELD_BY_COMPONENT = {
    ElectricalLoadComponent.BASE_BUS: "base_bus_w",
    ElectricalLoadComponent.OBC: "obc_w",
    ElectricalLoadComponent.ADCS: "adcs_w",
    ElectricalLoadComponent.PAYLOAD: "payload_w",
    ElectricalLoadComponent.COMMUNICATIONS: "communications_w",
    ElectricalLoadComponent.THERMAL_CONTROL: "thermal_control_w",
    ElectricalLoadComponent.PROPULSION: "propulsion_w",
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


def _fractional_readiness_agile_config() -> AgilePointingConfig:
    return AgilePointingConfig(
        _parameter(
            "adcs.pointing.maximum-view-angle-from-nadir",
            "deg",
            45.0,
        ),
        _parameter("adcs.pointing.post-slew-settling-time", "s", 5.0),
        (_anchor("zero", 0.0, 0.0), _anchor("ninety", 90.0, 75.25)),
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
    adcs_config = spacecraft_config.adcs
    if agile_config is not None:
        adcs_config = replace(adcs_config, agile_pointing=agile_config)
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
) -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId("f2-common-frame"),
        x,
        y,
        z,
    )


def _previous_execution(
    *,
    direction: CommonFrameBoresightDirection | None = None,
) -> ScheduledObservationExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("f2-previous"),
        ImagingRequestId("f2-previous-request"),
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
        ObservationOpportunityId("f2-next"),
        ImagingRequestId("f2-next-request"),
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
        "routing_config": _routing()
        if routing_config is None
        else routing_config,
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
    }


def _evaluate(**changes: object) -> ImagingExecutionAuthorizationResult:
    return evaluate_imaging_engine_step_authorization(
        **_arguments(**changes)
    )


def _full_result() -> ImagingExecutionAuthorizationResult:
    return _evaluate()


def _impossible_result() -> ImagingExecutionAuthorizationResult:
    context = _context(max_discharge_w=60.0)
    return _evaluate(
        context=context,
        environment=_environment(_zero_loads()),
    )


def _allocation_required_result() -> ImagingExecutionAuthorizationResult:
    context = _context(max_discharge_w=150.0)
    return _evaluate(
        context=context,
        environment=_environment(_zero_loads(base_bus_w=100.0)),
    )


def _sequence_infeasible_result() -> ImagingExecutionAuthorizationResult:
    return _evaluate(execution=_execution(view_angle_deg=50.0))


def test_result_has_exact_frozen_slotted_required_fields() -> None:
    result = _full_result()

    assert tuple(
        field.name for field in fields(ImagingExecutionAuthorizationResult)
    ) == (
        "execution",
        "electrical_result",
        "thermal_proposal",
        "status",
    )
    assert ImagingExecutionAuthorizationResult.__dataclass_params__.frozen
    assert not hasattr(result, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(ImagingExecutionAuthorizationResult)
    )
    with pytest.raises(FrozenInstanceError):
        result.status = ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE


def test_public_signature_is_exact_and_requires_active_inputs() -> None:
    parameters = signature(
        evaluate_imaging_engine_step_authorization
    ).parameters

    assert tuple(parameters) == (
        "context",
        "previous_execution",
        "execution",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
    )
    assert all(
        parameter.kind is Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is Parameter.empty
        for parameter in parameters.values()
    )


@pytest.mark.parametrize(
    "argument_name",
    (
        "context",
        "previous_execution",
        "execution",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
    ),
)
def test_public_function_requires_exact_top_level_types(argument_name) -> None:
    arguments = _arguments()
    arguments[argument_name] = object()

    with pytest.raises(TypeError, match=argument_name):
        evaluate_imaging_engine_step_authorization(**arguments)


def test_public_function_rejects_subclassed_execution() -> None:
    class ExecutionSubclass(ScheduledObservationAcquisitionExecution):
        pass

    arguments = _arguments()
    execution = arguments["execution"]
    arguments["execution"] = ExecutionSubclass(
        execution.candidate,
        execution.scheduled_start_seconds,
    )

    with pytest.raises(TypeError, match="execution"):
        evaluate_imaging_engine_step_authorization(**arguments)


@pytest.mark.parametrize(
    ("corruption", "message"),
    (
        ("context_battery", "energy_wh"),
        ("context_numerical", "timestep_seconds"),
        ("context_agile", "maximum_view_angle_from_nadir_deg"),
        ("context_optical", "acquisition_power_w"),
        ("context_eps", "max_discharge_output_power_w"),
        ("context_degradation", "usable_capacity_retention"),
        ("context_thermal_state", "temperature_k"),
        ("context_thermal_config", "heat_capacity_j_per_k"),
        ("previous_execution", "scheduled_start_seconds"),
        ("execution", "effective_cross_track_width_m"),
        ("environment", "base_bus_w"),
        ("routing", "REJECTED"),
        ("thermal_inputs", "radiative_sink_temperature_k"),
        ("external_heat", "absorbed_solar_w"),
    ),
)
def test_nested_inputs_are_revalidated_before_e1(
    corruption,
    message,
    monkeypatch,
) -> None:
    arguments = deepcopy(_arguments())
    if corruption == "context_battery":
        object.__setattr__(
            arguments["context"].spacecraft_state.battery,
            "energy_wh",
            -1.0,
        )
    elif corruption == "context_numerical":
        object.__setattr__(
            arguments["context"].inputs.numerical_config,
            "timestep_seconds",
            0,
        )
    elif corruption == "context_agile":
        parameter = (
            arguments["context"].inputs.spacecraft_configuration.adcs
            .agile_pointing.maximum_view_angle_from_nadir_deg
        )
        object.__setattr__(parameter, "value", -1.0)
    elif corruption == "context_optical":
        parameter = (
            arguments["context"].inputs.spacecraft_configuration.payload
            .optical_acquisition.acquisition_power_w
        )
        object.__setattr__(parameter, "value", -1.0)
    elif corruption == "context_eps":
        parameter = (
            arguments["context"].inputs.spacecraft_configuration.eps.battery
            .max_discharge_output_power_w
        )
        object.__setattr__(parameter, "value", -1.0)
    elif corruption == "context_degradation":
        object.__setattr__(
            arguments["context"].spacecraft_state.degradation.battery,
            "usable_capacity_retention",
            0.0,
        )
    elif corruption == "context_thermal_state":
        object.__setattr__(
            arguments["context"].spacecraft_state.thermal.node_states[0],
            "temperature_k",
            0.0,
        )
    elif corruption == "context_thermal_config":
        node = (
            arguments["context"].inputs.spacecraft_configuration
            .thermal.network.nodes[0]
        )
        object.__setattr__(node.heat_capacity_j_per_k, "value", -1.0)
    elif corruption == "previous_execution":
        object.__setattr__(
            arguments["previous_execution"],
            "scheduled_start_seconds",
            -1,
        )
    elif corruption == "execution":
        object.__setattr__(
            arguments["execution"].candidate.acquisition_input,
            "effective_cross_track_width_m",
            -1.0,
        )
    elif corruption == "environment":
        object.__setattr__(
            arguments["environment"].non_acquisition_loads,
            "base_bus_w",
            -1.0,
        )
    elif corruption == "routing":
        object.__setattr__(
            arguments["routing_config"].routes[0]
            .retained_heat_fraction.provenance,
            "status",
            ProvenanceStatus.REJECTED,
        )
    elif corruption == "thermal_inputs":
        object.__setattr__(
            arguments["thermal_inputs"].node_boundaries[0],
            "radiative_sink_temperature_k",
            float("nan"),
        )
    else:
        object.__setattr__(
            arguments["external_heat_sources"].node_sources[0],
            "absorbed_solar_w",
            -1.0,
        )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_eps",
        lambda *args: pytest.fail("E1 must not be reached"),
    )

    with pytest.raises((TypeError, ValueError), match=message):
        evaluate_imaging_engine_step_authorization(**arguments)


def test_result_requires_exact_nested_types_and_status() -> None:
    result = _full_result()

    for field_name in ("execution", "electrical_result", "thermal_proposal"):
        with pytest.raises(TypeError, match=field_name):
            replace(result, **{field_name: object()})
    with pytest.raises(TypeError, match="status"):
        replace(result, status="authorized")

    class ElectricalSubclass(ObservationAcquisitionEPSResult):
        pass

    electrical = result.electrical_result
    subclass = ElectricalSubclass(
        electrical.acquisition_evaluation,
        electrical.eps_inputs,
        electrical.eps_capability_result,
        electrical.eps_result,
        electrical.service_bounds,
    )
    with pytest.raises(TypeError, match="electrical_result"):
        replace(result, electrical_result=subclass)


def test_result_revalidates_nested_reviewed_results() -> None:
    result = _full_result()
    corrupted_execution = deepcopy(result.execution)
    object.__setattr__(
        corrupted_execution.candidate.acquisition_input,
        "effective_cross_track_width_m",
        -1.0,
    )
    with pytest.raises(ValueError, match="effective_cross_track_width_m"):
        replace(result, execution=corrupted_execution)

    corrupted_electrical = deepcopy(result.electrical_result)
    object.__setattr__(
        corrupted_electrical.eps_result.loads,
        "payload_w",
        -1.0,
    )
    with pytest.raises(ValueError, match="payload_w"):
        replace(result, electrical_result=corrupted_electrical)

    corrupted_thermal = deepcopy(result.thermal_proposal)
    object.__setattr__(
        corrupted_thermal.eps_thermal_coupling_result.node_heat_ledgers[0],
        "total_applied_heat_w",
        999.0,
    )
    with pytest.raises(ValueError, match="total_applied_heat_w"):
        replace(result, thermal_proposal=corrupted_thermal)


def test_result_cross_field_status_invariants_are_exact() -> None:
    authorized = _full_result()
    impossible = _impossible_result()
    sequence = _sequence_infeasible_result()

    with pytest.raises(ValueError, match="infeasible acquisition"):
        replace(
            authorized,
            thermal_proposal=None,
            status=ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE,
        )
    with pytest.raises(ValueError, match="feasible acquisition"):
        replace(
            sequence,
            status=(
                ImagingExecutionAuthorizationStatus
                .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
            ),
        )
    with pytest.raises(ValueError, match="not to be established"):
        replace(
            authorized,
            thermal_proposal=None,
            status=(
                ImagingExecutionAuthorizationStatus
                .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
            ),
        )
    with pytest.raises(ValueError, match="FULLY_SERVED"):
        replace(
            impossible,
            thermal_proposal=authorized.thermal_proposal,
            status=ImagingExecutionAuthorizationStatus.AUTHORIZED,
        )
    with pytest.raises(ValueError, match="thermal_proposal to be None"):
        replace(impossible, thermal_proposal=authorized.thermal_proposal)
    with pytest.raises(ValueError, match="requires a thermal_proposal"):
        replace(authorized, thermal_proposal=None)


def test_authorized_result_requires_same_nested_electrical_object() -> None:
    first = _full_result()
    second = _full_result()
    assert first.electrical_result == second.electrical_result
    assert first.electrical_result is not second.electrical_result

    with pytest.raises(ValueError, match="same electrical_result"):
        replace(first, thermal_proposal=second.thermal_proposal)


def test_result_constructor_recomputes_no_e1_or_e2(monkeypatch) -> None:
    result = _full_result()
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_eps",
        lambda *args: pytest.fail("E1 must not be recomputed"),
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        lambda *args: pytest.fail("E2 must not be recomputed"),
    )

    assert replace(result) == result


def test_current_boundary_mismatch_fails_before_e1(monkeypatch) -> None:
    context = _context(simulation_time_seconds=120)
    arguments = _arguments(
        context=context,
        execution=_execution(scheduled_start_seconds=100),
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_eps",
        lambda *args: pytest.fail("E1 must not be reached"),
    )

    with pytest.raises(ValueError, match="scheduled start.*current context"):
        evaluate_imaging_engine_step_authorization(**arguments)


def test_duration_mismatch_fails_before_e1_without_averaging(monkeypatch) -> None:
    context = _context(dt_seconds=60)
    arguments = _arguments(
        context=context,
        execution=_execution(duration_seconds=20),
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_eps",
        lambda *args: pytest.fail("E1 must not be reached"),
    )

    with pytest.raises(ValueError, match="duration.*engine timestep"):
        evaluate_imaging_engine_step_authorization(**arguments)


def test_exact_current_boundary_and_duration_are_accepted() -> None:
    arguments = _arguments()

    result = evaluate_imaging_engine_step_authorization(**arguments)

    assert arguments["execution"].scheduled_start_seconds == 100
    assert arguments["context"].simulation_time_seconds == 100
    assert (
        arguments["execution"].candidate.acquisition_input
        .imaging_duration_seconds
        == 23
    )
    assert arguments["context"].inputs.numerical_config.timestep_seconds == 23
    assert result.status is ImagingExecutionAuthorizationStatus.AUTHORIZED
    assert (
        result.thermal_proposal.eps_thermal_coupling_result
        .thermal_result.dt_seconds
        == 23
    )


def test_e1_exception_propagates_before_ledger_or_e2_without_mutation(
    monkeypatch,
) -> None:
    class ExpectedE1Error(RuntimeError):
        pass

    arguments = _arguments()
    before = deepcopy(arguments)

    def fail(*args):
        raise ExpectedE1Error("synthetic E1 failure")

    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_eps",
        fail,
    )
    monkeypatch.setattr(
        authorization_module,
        "_all_requested_served_power",
        lambda *args: pytest.fail("ledger must not be built"),
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        lambda *args: pytest.fail("E2 must not be reached"),
    )

    with pytest.raises(ExpectedE1Error, match="synthetic E1 failure"):
        evaluate_imaging_engine_step_authorization(**arguments)
    assert arguments == before


def test_e1_and_e2_are_called_once_in_order_from_active_context(
    monkeypatch,
) -> None:
    arguments = _arguments()
    context = arguments["context"]
    original_e1 = authorization_module.evaluate_observation_acquisition_eps
    original_e2 = (
        authorization_module
        .evaluate_observation_acquisition_single_interval_thermal_proposal
    )
    events = []

    def e1(agile, optical, eps, battery, degradation, previous, candidate, env):
        events.append("e1")
        spacecraft_config = context.inputs.spacecraft_configuration
        assert agile is spacecraft_config.adcs.agile_pointing
        assert optical is spacecraft_config.payload.optical_acquisition
        assert eps is spacecraft_config.eps
        assert battery is context.spacecraft_state.battery
        assert degradation is context.spacecraft_state.degradation
        assert previous is arguments["previous_execution"]
        assert candidate is arguments["execution"].candidate
        assert env is arguments["environment"]
        return original_e1(
            agile,
            optical,
            eps,
            battery,
            degradation,
            previous,
            candidate,
            env,
        )

    def e2(electrical, ledger, routing, state, network, inputs, sources):
        events.append("e2")
        assert events == ["e1", "e2"]
        assert routing is arguments["routing_config"]
        assert state is context.spacecraft_state.thermal
        assert network is context.inputs.spacecraft_configuration.thermal.network
        assert inputs is arguments["thermal_inputs"]
        assert sources is arguments["external_heat_sources"]
        return original_e2(
            electrical,
            ledger,
            routing,
            state,
            network,
            inputs,
            sources,
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

    result = evaluate_imaging_engine_step_authorization(**arguments)

    assert events == ["e1", "e2"]
    assert result.status is ImagingExecutionAuthorizationStatus.AUTHORIZED


def test_sequence_infeasible_returns_without_ledger_or_e2(monkeypatch) -> None:
    monkeypatch.setattr(
        authorization_module,
        "_all_requested_served_power",
        lambda *args: pytest.fail("ledger must not be built"),
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        lambda *args: pytest.fail("E2 must not be reached"),
    )

    result = _sequence_infeasible_result()

    assert result.status is (
        ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE
    )
    assert result.electrical_result.acquisition_evaluation.feasible is False
    assert result.electrical_result.eps_result is None
    assert result.thermal_proposal is None


def test_fractional_c3_readiness_is_rejected_exactly_before_e2(
    monkeypatch,
) -> None:
    context = _context(
        agile_config=_fractional_readiness_agile_config(),
    )
    arguments = _arguments(
        context=context,
        previous_execution=_previous_execution(direction=_direction(1, 0, 0)),
        execution=_execution(direction=_direction(0, 0, 1)),
    )
    original_e1 = authorization_module.evaluate_observation_acquisition_eps
    calls = []

    def e1(*args):
        calls.append("e1")
        result = original_e1(*args)
        assert (
            result.acquisition_evaluation.sequence_result
            .candidate_next_start_seconds
            == 100.25
        )
        return result

    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_eps",
        e1,
    )
    monkeypatch.setattr(
        authorization_module,
        "_all_requested_served_power",
        lambda *args: pytest.fail("ledger must not be built"),
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        lambda *args: pytest.fail("E2 must not be reached"),
    )

    with pytest.raises(ValueError, match="must not precede C3 readiness"):
        evaluate_imaging_engine_step_authorization(**arguments)
    assert calls == ["e1"]


def test_fractional_c3_readiness_allows_next_integer_boundary() -> None:
    context = _context(
        simulation_time_seconds=101,
        agile_config=_fractional_readiness_agile_config(),
    )
    result = _evaluate(
        context=context,
        previous_execution=_previous_execution(direction=_direction(1, 0, 0)),
        execution=_execution(
            scheduled_start_seconds=101,
            direction=_direction(0, 0, 1),
        ),
    )
    candidate_start = (
        result.electrical_result.acquisition_evaluation.sequence_result
        .candidate_next_start_seconds
    )

    assert candidate_start == 100.25
    assert result.execution.scheduled_start_seconds == 101
    assert result.status is ImagingExecutionAuthorizationStatus.AUTHORIZED


@pytest.mark.parametrize("scheduled_start_seconds", (100, 101))
def test_readiness_equality_and_later_start_are_accepted(
    scheduled_start_seconds,
) -> None:
    context = _context(simulation_time_seconds=scheduled_start_seconds)
    result = _evaluate(
        context=context,
        execution=_execution(
            scheduled_start_seconds=scheduled_start_seconds,
        ),
    )
    candidate_start = (
        result.electrical_result.acquisition_evaluation.sequence_result
        .candidate_next_start_seconds
    )

    assert candidate_start == 100
    assert result.execution.scheduled_start_seconds >= candidate_start
    assert result.status is ImagingExecutionAuthorizationStatus.AUTHORIZED


def test_fully_served_zero_unmet_authorizes_and_runs_e2() -> None:
    result = _full_result()

    assert result.electrical_result.service_bounds.status is (
        AcquisitionServiceStatus.FULLY_SERVED
    )
    assert result.electrical_result.eps_result.battery.unmet_load_w == 0
    assert result.status is ImagingExecutionAuthorizationStatus.AUTHORIZED
    assert type(result.thermal_proposal) is (
        ObservationAcquisitionSingleIntervalThermalProposal
    )
    assert result.thermal_proposal.electrical_result is result.electrical_result


@pytest.mark.parametrize(
    ("factory", "expected_service_status"),
    (
        (_impossible_result, AcquisitionServiceStatus.FULL_SERVICE_IMPOSSIBLE),
        (
            _allocation_required_result,
            AcquisitionServiceStatus.SERVICE_ALLOCATION_REQUIRED,
        ),
    ),
)
def test_both_shortfall_statuses_return_without_thermal(
    factory,
    expected_service_status,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        authorization_module,
        "_all_requested_served_power",
        lambda *args: pytest.fail("ledger must not be built"),
    )
    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        lambda *args: pytest.fail("E2 must not be reached"),
    )

    result = factory()

    assert result.electrical_result.service_bounds.status is (
        expected_service_status
    )
    assert result.electrical_result.eps_result.battery.unmet_load_w > 0
    assert result.status is (
        ImagingExecutionAuthorizationStatus
        .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
    )
    assert result.thermal_proposal is None


def test_zero_unmet_ledger_maps_all_seven_requested_components(monkeypatch) -> None:
    arguments = _arguments()
    original_e2 = (
        authorization_module
        .evaluate_observation_acquisition_single_interval_thermal_proposal
    )
    captured = {}

    def e2(electrical, ledger, *remaining):
        captured["electrical"] = electrical
        captured["ledger"] = ledger
        return original_e2(electrical, ledger, *remaining)

    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        e2,
    )

    result = evaluate_imaging_engine_step_authorization(**arguments)
    ledger = captured["ledger"]
    electrical = captured["electrical"]
    loads = electrical.eps_inputs.load_breakdown

    assert type(ledger) is ServedPowerLedger
    assert tuple(item.component for item in ledger.components) == COMPONENTS
    assert len(ledger.components) == 7
    for item in ledger.components:
        expected = getattr(loads, LOAD_FIELD_BY_COMPONENT[item.component])
        assert item.requested_power_w == expected
        assert item.served_power_w == expected
    payload = next(
        item
        for item in ledger.components
        if item.component is ElectricalLoadComponent.PAYLOAD
    )
    assert payload.requested_power_w == 4.0 + 100.0
    assert result.thermal_proposal.routed_internal_heat_result is not None


def test_e2_exception_propagates_without_status_conversion(monkeypatch) -> None:
    class ExpectedE2Error(RuntimeError):
        pass

    arguments = _arguments()
    before = deepcopy(arguments)

    def fail(*args):
        raise ExpectedE2Error("synthetic E2 failure")

    monkeypatch.setattr(
        authorization_module,
        "evaluate_observation_acquisition_single_interval_thermal_proposal",
        fail,
    )

    with pytest.raises(ExpectedE2Error, match="synthetic E2 failure"):
        evaluate_imaging_engine_step_authorization(**arguments)
    assert arguments == before


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


def test_positive_endpoint_beyond_survival_range_remains_authorized() -> None:
    context = _context(thermal_network=_hot_payload_network())

    result = _evaluate(context=context)
    payload_transition = next(
        transition
        for transition in (
            result.thermal_proposal.eps_thermal_coupling_result
            .thermal_result.node_transitions
        )
        if transition.node_id == ThermalNodeId("payload")
    )
    payload_config = next(
        node
        for node in (
            context.inputs.spacecraft_configuration.thermal.network.nodes
        )
        if node.node_id == ThermalNodeId("payload")
    )

    assert payload_transition.end_temperature_k > (
        payload_config.survival_max_temperature_k.value
    )
    assert result.status is ImagingExecutionAuthorizationStatus.AUTHORIZED


@pytest.mark.parametrize("case", ("authorized", "impossible", "sequence"))
def test_evaluation_is_pure_for_every_return_status(case) -> None:
    if case == "authorized":
        arguments = _arguments()
        expected = ImagingExecutionAuthorizationStatus.AUTHORIZED
    elif case == "impossible":
        context = _context(max_discharge_w=60.0)
        arguments = _arguments(
            context=context,
            environment=_environment(_zero_loads()),
        )
        expected = (
            ImagingExecutionAuthorizationStatus
            .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED
        )
    else:
        arguments = _arguments(execution=_execution(view_angle_deg=50.0))
        expected = ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE
    before = deepcopy(arguments)

    result = evaluate_imaging_engine_step_authorization(**arguments)

    assert result.status is expected
    assert arguments == before


def test_requested_image_data_are_preserved_without_storage_scaling() -> None:
    result = _full_result()
    acquisition = result.electrical_result.acquisition_evaluation.acquisition_result
    assert acquisition is not None

    assert acquisition.total_equivalent_samples == 1000.0
    assert acquisition.uncompressed_equivalent_bits == 12000.0
    assert acquisition.uncompressed_equivalent_bytes == 1500.0
    assert {
        field.name for field in fields(ImagingExecutionAuthorizationResult)
    }.isdisjoint(
        {
            "step_result",
            "stored_bytes",
            "data_product_id",
            "mission_request_id",
            "served_power_ledger",
            "committed_state",
            "feasible",
        }
    )


def test_production_has_exact_composition_without_duty_cycle_math() -> None:
    source = AUTHORIZATION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(AUTHORIZATION_PATH))
    public_function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "evaluate_imaging_engine_step_authorization"
    )
    called_names = [
        node.func.id
        for node in ast.walk(public_function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert called_names.count("evaluate_observation_acquisition_eps") == 1
    assert called_names.count(
        "evaluate_observation_acquisition_single_interval_thermal_proposal"
    ) == 1
    assert called_names.count("_all_requested_served_power") == 1
    assert "evaluate_observation_acquisition" not in called_names
    assert not any(
        isinstance(node, ast.BinOp)
        and isinstance(node.op, (ast.Mult, ast.Div, ast.FloorDiv))
        for node in ast.walk(public_function)
    )
    assert identifiers.isdisjoint({"round", "isclose", "epsilon", "StepResult"})
    assert "unmet_load_w" in identifiers
    assert "FULLY_SERVED" in identifiers


def test_production_has_only_pure_authorization_dependencies() -> None:
    source = AUTHORIZATION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(AUTHORIZATION_PATH))
    imported_modules = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert imported_modules <= {
        "__future__",
        "dataclasses",
        "context",
        "imaging_execution",
        "imaging_resources",
        "imaging_thermal",
        "observation_feasibility",
        "thermal",
        "thermal_coupling",
        "thermal_routing",
    }
    assert imported_modules.isdisjoint(
        {
            "numpy",
            "engine",
            "checkpoint",
            "mission",
            "storage",
            "degradation",
        }
    )
    assert called_names.isdisjoint(
        {
            "compute_battery_degradation_transition",
            "compute_battery_throughput_increment",
            "compute_explicit_solar_degradation_transition",
            "compute_battery_capacity_reconciliation",
        }
    )
    assert identifiers.isdisjoint(
        {
            "MissionRequestId",
            "DataProductId",
            "CommandId",
            "CheckpointState",
            "SimulationEngine",
            "StepResult",
        }
    )


def test_module_has_exact_exports() -> None:
    assert authorization_module.__all__ == [
        "ImagingExecutionAuthorizationResult",
        "evaluate_imaging_engine_step_authorization",
    ]


def test_f2_historical_slice_changes_only_imaging_authorization() -> None:
    changed = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "afb8ba20479a36ef3b89a9a63f2e2dd5223b6345",
            "88d53e6f4a3c9875d9eac20644f12dcefb815e0a",
            "--",
            "ops_sim/v5",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert changed == ["A\tops_sim/v5/imaging_authorization.py"]


def test_d245_through_d254_and_f2_source_semantics_are_recorded() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s003 = sources.partition("### S003 ")[2].partition("### S004 ")[0]
    s004 = sources.partition("### S004 ")[2].partition("### S005 ")[0]
    s005 = sources.partition("### S005 ")[2].partition("### S006 ")[0]
    combined = " ".join((s003 + s004 + s005).lower().split())

    for number in range(245, 255):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D244 ") < decisions.index("## D245 ")
    expected_headings = (
        "## D245 — F2 binds authorization to the current context snapshot "
        "without mutation",
        "## D246 — Selected scheduled start must equal current engine-step "
        "boundary",
        "## D247 — Acquisition duration must equal configured engine "
        "timestep",
        "## D248 — F2 performs no duty-cycle averaging or implicit substep",
        "## D249 — E1 is computed internally from active context "
        "configuration/state",
        "## D250 — Supported sequence infeasibility is a non-authorization "
        "result",
        "## D251 — Only exact full electrical service with zero unmet load "
        "proceeds",
        "## D252 — Zero aggregate unmet load uniquely determines all "
        "components fully served",
        "## D253 — F2 computes E2 internally only after exact electrical "
        "authorization",
        "## D254 — AUTHORIZED is a transient prerequisite result, not an "
        "engine commit or mission/product success",
    )
    assert all(decisions.count(heading) == 1 for heading in expected_headings)
    assert "v5.3f2" in combined
    assert "no new physical source or value" in combined
    assert "active context" in combined and "exactly once" in combined
    assert "configured timestep" in combined
    assert "duty-cycle" in combined and "no averaging" in combined
    assert "zero unmet" in combined and "all seven" in combined
    assert "served=requested" in combined
    assert "no shortfall allocation" in combined
    assert "candidate_next_start_seconds" in combined
    assert "no rounding" in combined
    assert "no degradation" in combined
    assert "no mission-request bridge" in combined
    assert "not an engine commit" in combined
    assert "no new literature" in s005.lower()
