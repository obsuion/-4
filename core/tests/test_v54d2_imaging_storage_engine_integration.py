"""Atomic imaging-to-storage engine integration for V5.4D2."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
import json
from inspect import Parameter, signature
from pathlib import Path
import subprocess

import pytest

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.degradation import SolarDegradationForcingInput
import ops_sim.v5.engine as engine_module
from ops_sim.v5.engine import (
    STEP_PHASE_ORDER,
    ImagingEngineStepAttempt,
    ImagingStorageEngineAttempt,
    SimulationEngine,
    SimulationPhase,
    StepResult,
)
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    AcquisitionDataRecordId,
    DataProductId,
    ImagingRequestId,
    MissionRequestId,
    ObservationOpportunityId,
    ParameterId,
    PlanId,
    ThermalNodeId,
)
from ops_sim.v5.imaging_execution import (
    ImagingExecutionAuthorizationStatus,
    ScheduledObservationAcquisitionExecution,
)
from ops_sim.v5.imaging_feasibility import ObservationAcquisitionCandidate
from ops_sim.v5.imaging_resources import AcquisitionEPSIntervalEnvironment
import ops_sim.v5.imaging_storage as imaging_storage_module
from ops_sim.v5.imaging_storage import (
    ImagingStorageAuthorizationResult,
    ImagingStorageAuthorizationStatus,
)
from ops_sim.v5.mission import MissionState
from ops_sim.v5.observation import ObservationOpportunity, ObservationPointing
from ops_sim.v5.observation_feasibility import (
    ObservationManeuverCandidate,
    ScheduledObservationExecution,
)
from ops_sim.v5.onboard_data import OnboardAcquisitionDataRecord
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
from ops_sim.v5.state import DataStorageState
from ops_sim.v5.thermal import ThermalIntervalInputs, ThermalNodeBoundaryInput
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
CHECKPOINT_PATH = ROOT / "ops_sim" / "v5" / "checkpoint.py"
D1_COMMIT = "ed7fd889f53339bf0fb220df76b69c53c36a448e"
D2_COMMIT = "537291dc787adb18137dba550be4e82501f2e3b1"
C_COMMIT = "c294a794f811532deb9d5666d0ca01999c90951f"
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
            rationale="Synthetic value used only by the V5.4D2 tests.",
        ),
    )


def _direction() -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId("v54d2-common-frame"),
        0.0,
        0.0,
        1.0,
    )


def _previous_execution() -> ScheduledObservationExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("v54d2-previous"),
        ImagingRequestId("v54d2-previous-request"),
        0,
        60,
        20,
        ObservationPointing(10.0, 0.0),
    )
    return ScheduledObservationExecution(
        ObservationManeuverCandidate(opportunity, _direction()),
        0,
    )


def _execution(
    *,
    view_angle_deg: float = 10.0,
    width_m: float = 20.0,
    length_m: float = 40.0,
) -> ScheduledObservationAcquisitionExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("v54d2-next"),
        ImagingRequestId("v54d2-next-request"),
        100,
        300,
        23,
        ObservationPointing(view_angle_deg, 0.0),
    )
    return ScheduledObservationAcquisitionExecution(
        ObservationAcquisitionCandidate(
            ObservationManeuverCandidate(opportunity, _direction()),
            OpticalAcquisitionInput(
                width_m,
                length_m,
                23,
                OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
            ),
        ),
        100,
    )


def _loads(
    *,
    base_bus_w: float = 1.0,
    obc_w: float = 2.0,
    adcs_w: float = 3.0,
    payload_w: float = 4.0,
    communications_w: float = 5.0,
    thermal_control_w: float = 6.0,
    propulsion_w: float = 7.0,
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


def _zero_loads() -> PowerLoadBreakdown:
    return _loads(
        base_bus_w=0.0,
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
    temperatures = {
        state.node_id: state.temperature_k
        for state in context.spacecraft_state.thermal.node_states
    }
    return ThermalIntervalInputs(
        tuple(
            ThermalNodeBoundaryInput(node.node_id, temperatures[node.node_id])
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


def _record(
    record_id: str | AcquisitionDataRecordId,
    *,
    bits: float = 1.0,
) -> OnboardAcquisitionDataRecord:
    stable_id = (
        AcquisitionDataRecordId(record_id)
        if type(record_id) is str
        else record_id
    )
    return OnboardAcquisitionDataRecord(
        stable_id,
        ImagingRequestId(f"stored-request-{stable_id.value}"),
        ObservationOpportunityId(f"stored-opportunity-{stable_id.value}"),
        0,
        1,
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        bits,
        bits,
    )


def _context(
    *,
    max_discharge_w: float = 150.0,
    capacity_bits: float | None = None,
    records: tuple[OnboardAcquisitionDataRecord, ...] = (),
    populated_mission: bool = False,
):
    base = build_demo_context()
    spacecraft_config = base.inputs.spacecraft_configuration
    battery = replace(
        spacecraft_config.eps.battery,
        max_discharge_output_power_w=replace(
            spacecraft_config.eps.battery.max_discharge_output_power_w,
            value=max_discharge_w,
        ),
    )
    storage = spacecraft_config.storage
    if capacity_bits is not None:
        storage = replace(
            storage,
            usable_capacity_gb=replace(
                storage.usable_capacity_gb,
                value=capacity_bits / 8_000_000_000.0,
            ),
        )
    spacecraft_config = replace(
        spacecraft_config,
        eps=replace(spacecraft_config.eps, battery=battery),
        storage=storage,
    )
    inputs = replace(
        base.inputs,
        spacecraft_configuration=spacecraft_config,
        numerical_config=replace(
            base.inputs.numerical_config,
            timestep_seconds=23,
            geometry_sample_seconds=1,
            checkpoint_interval_seconds=23,
        ),
    )
    mission = base.mission_state
    if populated_mission:
        mission = MissionState(
            (MissionRequestId("v54d2-pending"),),
            (MissionRequestId("v54d2-completed"),),
            (DataProductId("v54d2-product"),),
            PlanId("v54d2-plan"),
            (),
            (),
        )
    return replace(
        base,
        simulation_time_seconds=100,
        inputs=inputs,
        spacecraft_state=replace(
            base.spacecraft_state,
            data_storage=DataStorageState(records),
        ),
        mission_state=mission,
    )


def _arguments(
    *,
    context=None,
    previous_execution=None,
    execution=None,
    record_id=None,
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
        "execution": _execution() if execution is None else execution,
        "record_id": (
            AcquisitionDataRecordId("v54d2-record")
            if record_id is None
            else record_id
        ),
        "environment": _environment() if environment is None else environment,
        "routing_config": _routing() if routing_config is None else routing_config,
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


def _step_storage(**changes: object) -> ImagingStorageEngineAttempt:
    return SimulationEngine().step_imaging_to_storage(**_arguments(**changes))


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
        spacecraft.data_storage.stored_records,
        knowledge,
        knowledge.latest_telemetry,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _assert_rollback(context, before, references) -> None:
    assert context == before
    assert all(
        current is original
        for current, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def _engine_method(tree: ast.Module, name: str) -> ast.FunctionDef:
    engine_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SimulationEngine"
    )
    return next(
        node
        for node in engine_class.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _module_class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _called_names(node: ast.AST) -> tuple[str, ...]:
    return tuple(
        name
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        for name in (_call_name(child),)
        if name is not None
    )


def test_attempt_contract_is_exact_frozen_slotted_required_and_retains_objects(
) -> None:
    attempt = _step_storage()
    result_fields = fields(ImagingStorageEngineAttempt)

    assert tuple(field.name for field in result_fields) == (
        "authorization_result",
        "step_result",
    )
    assert ImagingStorageEngineAttempt.__dataclass_params__.frozen
    assert not hasattr(attempt, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in result_fields
    )
    assert type(attempt.authorization_result) is ImagingStorageAuthorizationResult
    assert type(attempt.step_result) is StepResult
    assert attempt.step_result.eps_result is (
        attempt.authorization_result.imaging_authorization_result
        .electrical_result.eps_result
    )
    with pytest.raises(FrozenInstanceError):
        attempt.step_result = None
    assert not hasattr(attempt, "proposed_record")
    assert not hasattr(attempt, "feasible")
    assert not hasattr(attempt, "context")


def test_attempt_requires_exact_types_and_exact_status_shapes() -> None:
    authorized = _step_storage()
    imaging_rejected = _step_storage(execution=_execution(view_angle_deg=50.0))
    insufficient = _step_storage(context=_context(capacity_bits=11_999.0))

    with pytest.raises(TypeError, match="authorization_result"):
        ImagingStorageEngineAttempt(object(), None)
    with pytest.raises(TypeError, match="step_result"):
        replace(authorized, step_result=object())

    class StepSubclass(StepResult):
        pass

    step = authorized.step_result
    subclass_step = StepSubclass(
        *(getattr(step, field.name) for field in fields(StepResult))
    )
    with pytest.raises(TypeError, match="step_result"):
        replace(authorized, step_result=subclass_step)

    class AuthorizationSubclass(ImagingStorageAuthorizationResult):
        pass

    authorization = authorized.authorization_result
    subclass_authorization = AuthorizationSubclass(
        *(getattr(authorization, field.name) for field in fields(authorization))
    )
    with pytest.raises(TypeError, match="authorization_result"):
        ImagingStorageEngineAttempt(subclass_authorization, step)

    with pytest.raises(ValueError, match="AUTHORIZED"):
        replace(authorized, step_result=None)
    with pytest.raises(ValueError, match="non-authorized"):
        ImagingStorageEngineAttempt(imaging_rejected.authorization_result, step)
    with pytest.raises(ValueError, match="non-authorized"):
        ImagingStorageEngineAttempt(insufficient.authorization_result, step)
    assert imaging_rejected.step_result is None
    assert insufficient.step_result is None


def test_attempt_revalidates_complete_c_result_and_step_result() -> None:
    attempt = _step_storage()
    corrupted_authorization = deepcopy(attempt.authorization_result)
    object.__setattr__(
        corrupted_authorization.storage_admission_result,
        "available_capacity_bits_before",
        -1.0,
    )
    with pytest.raises(ValueError, match="available_capacity_bits_before"):
        ImagingStorageEngineAttempt(
            corrupted_authorization,
            attempt.step_result,
        )

    corrupted_step = deepcopy(attempt.step_result)
    object.__setattr__(corrupted_step, "dt_seconds", 0)
    with pytest.raises(ValueError, match="dt_seconds"):
        ImagingStorageEngineAttempt(attempt.authorization_result, corrupted_step)


def test_authorized_attempt_requires_exact_timing_and_physical_identities() -> None:
    attempt = _step_storage()
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
            end_time_seconds=step.end_time_seconds + 1,
            dt_seconds=step.dt_seconds + 1,
        ),
        replace(step, eps_result=deepcopy(step.eps_result)),
        replace(
            step,
            eps_capability_result=deepcopy(step.eps_capability_result),
        ),
        replace(
            step,
            thermal_coupling_result=deepcopy(step.thermal_coupling_result),
        ),
    )
    for mismatched in mismatched_steps:
        with pytest.raises(ValueError):
            ImagingStorageEngineAttempt(authorization, mismatched)

    f2 = authorization.imaging_authorization_result
    assert step.start_time_seconds == f2.execution.scheduled_start_seconds
    assert step.dt_seconds == (
        f2.execution.candidate.acquisition_input.imaging_duration_seconds
    )
    assert step.end_time_seconds == step.start_time_seconds + step.dt_seconds
    assert step.eps_result is f2.electrical_result.eps_result
    assert step.eps_capability_result is (
        f2.electrical_result.eps_capability_result
    )
    assert step.thermal_coupling_result is (
        f2.thermal_proposal.eps_thermal_coupling_result
    )


def test_public_storage_step_signature_and_engine_exports_are_exact() -> None:
    historical_engine_tree = ast.parse(
        subprocess.run(
            ["git", "show", f"{D2_COMMIT}:ops_sim/v5/engine.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    )
    exports_assignment = next(
        node
        for node in historical_engine_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )
    historical_exports = ast.literal_eval(exports_assignment.value)
    parameters = signature(SimulationEngine.step_imaging_to_storage).parameters

    assert tuple(parameters) == (
        "self",
        "context",
        "previous_execution",
        "execution",
        "record_id",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
        "solar_degradation_forcing",
    )
    for name in ("self", "context", "previous_execution", "execution"):
        assert parameters[name].kind is Parameter.POSITIONAL_OR_KEYWORD
        assert parameters[name].default is Parameter.empty
    for name in (
        "record_id",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
    ):
        assert parameters[name].kind is Parameter.KEYWORD_ONLY
        assert parameters[name].default is Parameter.empty
    solar = parameters["solar_degradation_forcing"]
    assert solar.kind is Parameter.KEYWORD_ONLY
    assert solar.default is None
    assert str(signature(SimulationEngine.step_imaging_to_storage)) == (
        "(self, context: 'SimulationContext', previous_execution: "
        "'ScheduledObservationExecution', execution: "
        "'ScheduledObservationAcquisitionExecution', *, record_id: "
        "'AcquisitionDataRecordId', environment: "
        "'AcquisitionEPSIntervalEnvironment', routing_config: "
        "'ComponentHeatRoutingConfig', thermal_inputs: "
        "'ThermalIntervalInputs', external_heat_sources: "
        "'ThermalHeatSourceInputs', solar_degradation_forcing: "
        "'SolarDegradationForcingInput | None' = None) -> "
        "'ImagingStorageEngineAttempt'"
    )
    assert historical_exports == [
        "STEP_PHASE_ORDER",
        "ImagingEngineStepAttempt",
        "ImagingStorageEngineAttempt",
        "SimulationEngine",
        "SimulationPhase",
        "StepResult",
    ]
    assert set(historical_exports).issubset(engine_module.__all__)
    assert "_ImagingStorageExecutionNotAuthorized" not in engine_module.__all__
    assert "_prepare_imaging_storage_physical_integration_handler" not in (
        engine_module.__all__
    )


def test_private_storage_nonauthorization_control_is_exact_distinct_and_private(
) -> None:
    imaging_rejected = _step_storage(execution=_execution(view_angle_deg=50.0))
    insufficient = _step_storage(context=_context(capacity_bits=11_999.0))
    control_type = engine_module._ImagingStorageExecutionNotAuthorized

    assert control_type is not engine_module._ImagingExecutionNotAuthorized
    assert control_type.__slots__ == ("authorization_result",)
    for result in (
        imaging_rejected.authorization_result,
        insufficient.authorization_result,
    ):
        error = control_type(result)
        assert error.authorization_result is result
        assert str(error) == result.status.value
    with pytest.raises(TypeError, match="authorization_result"):
        control_type(object())
    with pytest.raises(ValueError, match="non-authorized"):
        control_type(_step_storage().authorization_result)


@pytest.mark.parametrize(
    "argument_name",
    (
        "context",
        "previous_execution",
        "execution",
        "record_id",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
        "solar_degradation_forcing",
    ),
)
def test_malformed_top_level_arguments_fail_before_checkpoint_and_c(
    argument_name,
    monkeypatch,
) -> None:
    arguments = _arguments()
    arguments[argument_name] = object()

    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        lambda *args: pytest.fail("checkpoint must not be captured"),
    )
    monkeypatch.setattr(
        engine_module,
        "authorize_imaging_storage_execution",
        lambda *args, **kwargs: pytest.fail("C must not be called"),
    )

    with pytest.raises(TypeError, match=argument_name if argument_name != "context" else "context"):
        SimulationEngine().step_imaging_to_storage(**arguments)


def test_corrupted_record_id_fails_before_checkpoint_and_c(monkeypatch) -> None:
    record_id = AcquisitionDataRecordId("v54d2-corrupt")
    object.__setattr__(record_id, "value", "CORRUPTED")
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        lambda *args: pytest.fail("checkpoint must not be captured"),
    )
    monkeypatch.setattr(
        engine_module,
        "authorize_imaging_storage_execution",
        lambda *args, **kwargs: pytest.fail("C must not be called"),
    )

    with pytest.raises(ValueError, match="StableId value"):
        _step_storage(record_id=record_id)


def test_corrupted_nested_input_is_revalidated_before_checkpoint_and_c(
    monkeypatch,
) -> None:
    execution = deepcopy(_execution())
    object.__setattr__(
        execution.candidate.acquisition_input,
        "effective_cross_track_width_m",
        -1.0,
    )
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        lambda *args: pytest.fail("checkpoint must not be captured"),
    )
    monkeypatch.setattr(
        engine_module,
        "authorize_imaging_storage_execution",
        lambda *args, **kwargs: pytest.fail("C must not be called"),
    )

    with pytest.raises(ValueError, match="effective_cross_track_width_m"):
        _step_storage(execution=execution)


def test_context_validation_precedes_storage_step_preflight(monkeypatch) -> None:
    context = _context()
    context.spacecraft_state.battery.energy_wh = -1.0
    arguments = _arguments(context=context)
    arguments["previous_execution"] = object()
    monkeypatch.setattr(
        SimulationEngine,
        "_prepare_imaging_storage_physical_integration_handler",
        lambda *args, **kwargs: pytest.fail("preflight must follow context"),
    )

    with pytest.raises(ValueError, match="energy_wh"):
        SimulationEngine().step_imaging_to_storage(**arguments)


@pytest.mark.parametrize(
    ("case", "context_factory", "execution_factory", "environment_factory", "f2_status"),
    (
        (
            "sequence-infeasible",
            lambda: _context(),
            lambda: _execution(view_angle_deg=50.0),
            lambda: _environment(),
            ImagingExecutionAuthorizationStatus.SEQUENCE_INFEASIBLE,
        ),
        (
            "electrical-full-service-not-established",
            lambda: _context(max_discharge_w=60.0),
            lambda: _execution(),
            lambda: _environment(_zero_loads()),
            ImagingExecutionAuthorizationStatus
            .ELECTRICAL_FULL_SERVICE_NOT_ESTABLISHED,
        ),
    ),
)
def test_supported_imaging_nonauthorization_has_exact_zero_commit_cardinality(
    case,
    context_factory,
    execution_factory,
    environment_factory,
    f2_status,
    monkeypatch,
) -> None:
    context = context_factory()
    before = deepcopy(context)
    references = _authoritative_references(context)
    original_c = engine_module.authorize_imaging_storage_execution
    original_f2 = imaging_storage_module.evaluate_imaging_engine_step_authorization
    counts = {"c": 0, "f2": 0, "a1": 0, "b1": 0}

    def c(*args, **kwargs):
        counts["c"] += 1
        return original_c(*args, **kwargs)

    def f2(*args, **kwargs):
        counts["f2"] += 1
        return original_f2(*args, **kwargs)

    def forbidden(name):
        def fail(*args, **kwargs):
            counts[name] += 1
            pytest.fail(f"{name} must not run for {case}")

        return fail

    monkeypatch.setattr(engine_module, "authorize_imaging_storage_execution", c)
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_imaging_engine_step_authorization",
        f2,
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "compute_onboard_acquisition_data_volume_proposal",
        forbidden("a1"),
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_storage_admission",
        forbidden("b1"),
    )
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        forbidden("tail"),
    )
    monkeypatch.setattr(engine_module, "StepResult", forbidden("step-result"))
    monkeypatch.setattr(
        engine_module,
        "compute_explicit_solar_degradation_transition",
        forbidden("solar"),
    )
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(forbidden("commit")),
    )

    attempt = SimulationEngine().step_imaging_to_storage(
        **_arguments(
            context=context,
            execution=execution_factory(),
            environment=environment_factory(),
            solar_degradation_forcing=SolarDegradationForcingInput(0.01),
        )
    )

    assert type(attempt) is ImagingStorageEngineAttempt
    assert attempt.authorization_result.status is (
        ImagingStorageAuthorizationStatus.IMAGING_NOT_AUTHORIZED
    )
    assert (
        attempt.authorization_result.imaging_authorization_result.status
        is f2_status
    )
    assert attempt.step_result is None
    assert counts == {"c": 1, "f2": 1, "a1": 0, "b1": 0}
    _assert_rollback(context, before, references)


def test_insufficient_storage_is_supported_with_no_tail_or_commit(
    monkeypatch,
) -> None:
    context = _context(capacity_bits=11_999.0)
    before = deepcopy(context)
    references = _authoritative_references(context)
    originals = (
        engine_module.authorize_imaging_storage_execution,
        imaging_storage_module.evaluate_imaging_engine_step_authorization,
        imaging_storage_module.compute_onboard_acquisition_data_volume_proposal,
        imaging_storage_module.evaluate_storage_admission,
    )
    counts = {"c": 0, "f2": 0, "a1": 0, "b1": 0}

    def counted(name, function):
        def wrapper(*args, **kwargs):
            counts[name] += 1
            return function(*args, **kwargs)

        return wrapper

    def forbidden(*args, **kwargs):
        pytest.fail("post-admission transaction work must not run")

    monkeypatch.setattr(
        engine_module,
        "authorize_imaging_storage_execution",
        counted("c", originals[0]),
    )
    for module, name, key, original in (
        (
            imaging_storage_module,
            "evaluate_imaging_engine_step_authorization",
            "f2",
            originals[1],
        ),
        (
            imaging_storage_module,
            "compute_onboard_acquisition_data_volume_proposal",
            "a1",
            originals[2],
        ),
        (
            imaging_storage_module,
            "evaluate_storage_admission",
            "b1",
            originals[3],
        ),
    ):
        monkeypatch.setattr(module, name, counted(key, original))
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        forbidden,
    )
    monkeypatch.setattr(engine_module, "StepResult", forbidden)
    monkeypatch.setattr(
        engine_module,
        "compute_explicit_solar_degradation_transition",
        forbidden,
    )
    monkeypatch.setattr(SimulationEngine, "_commit", staticmethod(forbidden))

    attempt = SimulationEngine().step_imaging_to_storage(
        **_arguments(
            context=context,
            solar_degradation_forcing=SolarDegradationForcingInput(0.01),
        )
    )

    assert attempt.authorization_result.status is (
        ImagingStorageAuthorizationStatus.INSUFFICIENT_STORAGE_CAPACITY
    )
    assert attempt.authorization_result.imaging_authorization_result.status is (
        ImagingExecutionAuthorizationStatus.AUTHORIZED
    )
    assert attempt.step_result is None
    assert counts == {"c": 1, "f2": 1, "a1": 1, "b1": 1}
    _assert_rollback(context, before, references)


def test_authorized_path_is_one_working_transaction_and_one_atomic_commit(
    monkeypatch,
) -> None:
    existing = (_record("existing-a"), _record("existing-b", bits=2.0))
    context = _context(records=existing, populated_mission=True)
    before = deepcopy(context)
    references = _authoritative_references(context)
    record_id = AcquisitionDataRecordId("authorized-new")
    counts = {
        "c": 0,
        "f2": 0,
        "a1": 0,
        "b1": 0,
        "tail": 0,
        "append": 0,
        "step-result": 0,
        "attempt": 0,
        "commit": 0,
    }
    events: list[str] = []
    captured: dict[str, object] = {}
    originals = {
        "c": engine_module.authorize_imaging_storage_execution,
        "f2": imaging_storage_module.evaluate_imaging_engine_step_authorization,
        "a1": imaging_storage_module.compute_onboard_acquisition_data_volume_proposal,
        "b1": imaging_storage_module.evaluate_storage_admission,
        "tail": engine_module._complete_coupled_physical_integration,
        "step": engine_module.StepResult,
        "attempt": engine_module.ImagingStorageEngineAttempt,
        "validate": engine_module._validate_completed_context,
        "commit": SimulationEngine._commit,
    }

    class ObservingEngine(SimulationEngine):
        def __init__(self):
            self.active_phase = None

        def _execute_phase(self, phase, working, interval, handler):
            self.active_phase = phase
            return super()._execute_phase(phase, working, interval, handler)

    engine = ObservingEngine()

    def c(working, *args, **kwargs):
        counts["c"] += 1
        events.append("c")
        assert engine.active_phase is SimulationPhase.PHYSICAL_INTEGRATION
        assert working is not context
        assert working.inputs is context.inputs
        assert working == context
        assert "solar_degradation_forcing" not in kwargs
        result = originals["c"](working, *args, **kwargs)
        captured["c"] = result
        return result

    def counted(name, function):
        def wrapper(*args, **kwargs):
            counts[name] += 1
            events.append(name)
            return function(*args, **kwargs)

        return wrapper

    def tail(working, interval, **kwargs):
        counts["tail"] += 1
        events.append("tail")
        c_result = captured["c"]
        f2 = c_result.imaging_authorization_result
        assert working.spacecraft_state.data_storage.stored_records == existing
        assert kwargs["eps_result"] is f2.electrical_result.eps_result
        assert kwargs["eps_capability_result"] is (
            f2.electrical_result.eps_capability_result
        )
        assert kwargs["thermal_coupling_result"] is (
            f2.thermal_proposal.eps_thermal_coupling_result
        )
        result = originals["tail"](working, interval, **kwargs)
        captured["physical"] = result
        return result

    class CountingStepResult(originals["step"]):
        def __new__(cls, *args, **kwargs):
            counts["step-result"] += 1
            events.append("step-result")
            return super().__new__(cls)

    class CountingAttempt(originals["attempt"]):
        def __new__(cls, authorization, step_result):
            counts["attempt"] += 1
            events.append("attempt")
            assert authorization is captured["c"]
            assert type(step_result) is CountingStepResult
            assert context == before
            assert _authoritative_references(context) == references
            return super().__new__(cls)

    validate_calls = 0

    def validate(candidate):
        nonlocal validate_calls
        validate_calls += 1
        if candidate is not context:
            proposed = captured["c"].storage_admission_result.proposed_record
            assert candidate.spacecraft_state.data_storage.stored_records == (
                existing + (proposed,)
            )
            assert candidate.spacecraft_state.data_storage.stored_records[-1] is (
                proposed
            )
            counts["append"] += 1
            events.append("final-validation")
        return originals["validate"](candidate)

    def commit(original, working):
        counts["commit"] += 1
        events.append("commit")
        assert original is context
        assert original == before
        assert counts["attempt"] == 1
        return originals["commit"](original, working)

    monkeypatch.setattr(engine_module, "authorize_imaging_storage_execution", c)
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_imaging_engine_step_authorization",
        counted("f2", originals["f2"]),
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "compute_onboard_acquisition_data_volume_proposal",
        counted("a1", originals["a1"]),
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_storage_admission",
        counted("b1", originals["b1"]),
    )
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        tail,
    )
    monkeypatch.setattr(engine_module, "StepResult", CountingStepResult)
    monkeypatch.setattr(
        engine_module,
        "ImagingStorageEngineAttempt",
        CountingAttempt,
    )
    monkeypatch.setattr(engine_module, "_validate_completed_context", validate)
    monkeypatch.setattr(SimulationEngine, "_commit", staticmethod(commit))

    attempt = engine.step_imaging_to_storage(
        **_arguments(context=context, record_id=record_id)
    )

    assert type(attempt) is CountingAttempt
    assert attempt.authorization_result is captured["c"]
    assert type(attempt.step_result) is CountingStepResult
    assert counts == {
        "c": 1,
        "f2": 1,
        "a1": 1,
        "b1": 1,
        "tail": 1,
        "append": 1,
        "step-result": 1,
        "attempt": 1,
        "commit": 1,
    }
    assert validate_calls == 2
    assert events == [
        "c",
        "f2",
        "a1",
        "b1",
        "tail",
        "final-validation",
        "step-result",
        "attempt",
        "commit",
    ]
    c_result = attempt.authorization_result
    step = attempt.step_result
    proposed = c_result.storage_admission_result.proposed_record
    assert c_result.status is ImagingStorageAuthorizationStatus.AUTHORIZED
    assert step.eps_result is c_result.imaging_authorization_result.electrical_result.eps_result
    assert step.eps_capability_result is (
        c_result.imaging_authorization_result.electrical_result
        .eps_capability_result
    )
    assert step.thermal_coupling_result is (
        c_result.imaging_authorization_result.thermal_proposal
        .eps_thermal_coupling_result
    )
    assert context.spacecraft_state.data_storage.stored_records == (
        existing + (proposed,)
    )
    assert context.spacecraft_state.data_storage.stored_records[0] is existing[0]
    assert context.spacecraft_state.data_storage.stored_records[1] is existing[1]
    assert context.spacecraft_state.data_storage.stored_records[-1] is proposed
    assert proposed.record_id is record_id
    assert context.simulation_time_seconds == 123
    assert context.diagnostics.completed_steps == 1
    assert context.mission_state == before.mission_state
    assert context.controller_state == before.controller_state


def test_success_preserves_prior_order_identities_and_appends_exact_record() -> None:
    existing = tuple(_record(f"prior-{index}", bits=float(index)) for index in range(1, 4))
    context = _context(records=existing)
    record_id = AcquisitionDataRecordId("new-last")

    attempt = _step_storage(context=context, record_id=record_id)
    proposed = attempt.authorization_result.storage_admission_result.proposed_record
    stored = context.spacecraft_state.data_storage.stored_records

    assert stored == existing + (proposed,)
    assert all(current is original for current, original in zip(stored, existing))
    assert stored[-1] is proposed
    assert proposed.record_id is record_id
    assert len(stored) == len(existing) + 1


def test_physical_endpoint_matches_existing_step_imaging_exactly() -> None:
    old_context = _context()
    storage_context = _context()
    old_arguments = _arguments(context=old_context)
    storage_arguments = _arguments(context=storage_context)
    old_arguments.pop("record_id")
    storage_arguments["record_id"] = AcquisitionDataRecordId("equivalence")

    old_attempt = SimulationEngine().step_imaging(**old_arguments)
    storage_attempt = SimulationEngine().step_imaging_to_storage(
        **storage_arguments
    )

    assert type(old_attempt) is ImagingEngineStepAttempt
    assert old_attempt.step_result == storage_attempt.step_result
    assert old_context.simulation_time_seconds == storage_context.simulation_time_seconds
    assert old_context.diagnostics == storage_context.diagnostics
    assert old_context.spacecraft_state.battery == (
        storage_context.spacecraft_state.battery
    )
    assert old_context.spacecraft_state.thermal == (
        storage_context.spacecraft_state.thermal
    )
    assert old_context.spacecraft_state.degradation == (
        storage_context.spacecraft_state.degradation
    )
    assert old_context.spacecraft_state.data_storage.stored_records == ()
    assert len(storage_context.spacecraft_state.data_storage.stored_records) == 1


def test_solar_forcing_is_excluded_from_c_and_used_once_only_in_tail(
    monkeypatch,
) -> None:
    context = _context()
    forcing = SolarDegradationForcingInput(0.01)
    original_c = engine_module.authorize_imaging_storage_execution
    original_tail = engine_module._complete_coupled_physical_integration
    original_solar = engine_module.compute_explicit_solar_degradation_transition
    calls = {"c": 0, "tail": 0, "solar": 0}

    def c(*args, **kwargs):
        calls["c"] += 1
        assert "solar_degradation_forcing" not in kwargs
        return original_c(*args, **kwargs)

    def tail(*args, **kwargs):
        calls["tail"] += 1
        assert kwargs["solar_degradation_forcing"] is forcing
        return original_tail(*args, **kwargs)

    def solar(*args, **kwargs):
        calls["solar"] += 1
        return original_solar(*args, **kwargs)

    monkeypatch.setattr(engine_module, "authorize_imaging_storage_execution", c)
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        tail,
    )
    monkeypatch.setattr(
        engine_module,
        "compute_explicit_solar_degradation_transition",
        solar,
    )

    attempt = _step_storage(
        context=context,
        solar_degradation_forcing=forcing,
    )

    assert calls == {"c": 1, "tail": 1, "solar": 1}
    assert attempt.step_result.solar_degradation_result is not None
    assert context.spacecraft_state.degradation.solar.generation_retention == 0.99
    assert attempt.authorization_result.storage_admission_result.status.value == (
        "admissible"
    )


def test_duplicate_record_id_propagates_original_b1_exception_without_commit(
    monkeypatch,
) -> None:
    duplicate_id = AcquisitionDataRecordId("duplicate")
    existing = _record(duplicate_id)
    context = _context(records=(existing,))
    before = deepcopy(context)
    references = _authoritative_references(context)
    original_c = engine_module.authorize_imaging_storage_execution
    calls = []

    def c(*args, **kwargs):
        calls.append("c")
        return original_c(*args, **kwargs)

    monkeypatch.setattr(engine_module, "authorize_imaging_storage_execution", c)
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        lambda *args, **kwargs: pytest.fail("tail must not run"),
    )
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    with pytest.raises(ValueError, match="record ID.*already"):
        _step_storage(context=context, record_id=duplicate_id)

    assert calls == ["c"]
    _assert_rollback(context, before, references)


def test_c_exception_propagates_without_tail_append_or_commit(monkeypatch) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    class ExpectedCError(RuntimeError):
        pass

    expected = ExpectedCError("synthetic C failure")

    def fail_c(*args, **kwargs):
        raise expected

    monkeypatch.setattr(
        engine_module,
        "authorize_imaging_storage_execution",
        fail_c,
    )
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        lambda *args, **kwargs: pytest.fail("tail must not run"),
    )
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    with pytest.raises(ExpectedCError) as caught:
        _step_storage(context=context)

    assert caught.value is expected
    _assert_rollback(context, before, references)


def test_tail_failure_after_c_authorization_rolls_back_before_append(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    original_c = engine_module.authorize_imaging_storage_execution
    observed_working = []

    class ExpectedTailError(RuntimeError):
        pass

    expected = ExpectedTailError("synthetic tail failure")

    def c(working, *args, **kwargs):
        result = original_c(working, *args, **kwargs)
        observed_working.append((working, result))
        return result

    def fail_tail(working, *args, **kwargs):
        assert working is observed_working[0][0]
        assert working.spacecraft_state.data_storage.stored_records == ()
        raise expected

    monkeypatch.setattr(engine_module, "authorize_imaging_storage_execution", c)
    monkeypatch.setattr(
        engine_module,
        "_complete_coupled_physical_integration",
        fail_tail,
    )
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    with pytest.raises(ExpectedTailError) as caught:
        _step_storage(context=context)

    assert caught.value is expected
    assert len(observed_working) == 1
    assert observed_working[0][0].spacecraft_state.data_storage.stored_records == ()
    _assert_rollback(context, before, references)


def test_postappend_final_validation_failure_is_fully_isolated(
    monkeypatch,
) -> None:
    context = _context(records=(_record("prior"),))
    before = deepcopy(context)
    references = _authoritative_references(context)
    original_c = engine_module.authorize_imaging_storage_execution
    original_validate = engine_module._validate_completed_context
    captured = {}

    class ExpectedValidationError(RuntimeError):
        pass

    expected = ExpectedValidationError("synthetic postappend validation failure")

    def c(working, *args, **kwargs):
        result = original_c(working, *args, **kwargs)
        captured["working"] = working
        captured["result"] = result
        return result

    calls = 0

    def validate(candidate):
        nonlocal calls
        calls += 1
        if candidate is context:
            return original_validate(candidate)
        proposed = captured["result"].storage_admission_result.proposed_record
        assert candidate is captured["working"]
        assert candidate.spacecraft_state.data_storage.stored_records[-1] is proposed
        assert candidate.spacecraft_state.battery.energy_wh != (
            context.spacecraft_state.battery.energy_wh
        )
        raise expected

    monkeypatch.setattr(engine_module, "authorize_imaging_storage_execution", c)
    monkeypatch.setattr(engine_module, "_validate_completed_context", validate)
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    with pytest.raises(ExpectedValidationError) as caught:
        _step_storage(context=context)

    assert caught.value is expected
    assert calls == 2
    assert len(captured["working"].spacecraft_state.data_storage.stored_records) == 2
    _assert_rollback(context, before, references)


def test_step_result_failure_after_append_rolls_back_everything(monkeypatch) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    original_c = engine_module.authorize_imaging_storage_execution
    original_validate = engine_module._validate_completed_context
    captured = {}
    result_calls = []

    class ExpectedStepResultError(RuntimeError):
        pass

    expected = ExpectedStepResultError("synthetic D2 StepResult failure")

    def c(working, *args, **kwargs):
        result = original_c(working, *args, **kwargs)
        captured["working"] = working
        captured["result"] = result
        return result

    def validate(candidate):
        if candidate is not context:
            proposed = captured["result"].storage_admission_result.proposed_record
            assert candidate.spacecraft_state.data_storage.stored_records == (
                proposed,
            )
        return original_validate(candidate)

    def fail_result(*args, **kwargs):
        result_calls.append((args, kwargs))
        raise expected

    monkeypatch.setattr(engine_module, "authorize_imaging_storage_execution", c)
    monkeypatch.setattr(engine_module, "_validate_completed_context", validate)
    monkeypatch.setattr(engine_module, "StepResult", fail_result)
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    with pytest.raises(ExpectedStepResultError) as caught:
        _step_storage(context=context)

    assert caught.value is expected
    assert len(result_calls) == 1
    assert len(captured["working"].spacecraft_state.data_storage.stored_records) == 1
    _assert_rollback(context, before, references)


def test_outer_attempt_failure_after_step_result_and_append_rolls_back(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    original_c = engine_module.authorize_imaging_storage_execution
    original_validate = engine_module._validate_completed_context
    captured = {}

    class ExpectedAttemptError(RuntimeError):
        pass

    expected = ExpectedAttemptError("synthetic D2 outer-attempt failure")

    def c(working, *args, **kwargs):
        result = original_c(working, *args, **kwargs)
        captured["working"] = working
        captured["result"] = result
        return result

    def validate(candidate):
        if candidate is not context:
            proposed = captured["result"].storage_admission_result.proposed_record
            assert candidate.spacecraft_state.data_storage.stored_records[-1] is proposed
        return original_validate(candidate)

    def fail_attempt(authorization, step_result):
        captured["step"] = step_result
        assert authorization is captured["result"]
        assert type(step_result) is StepResult
        assert captured["working"].spacecraft_state.data_storage.stored_records
        assert context == before
        raise expected

    monkeypatch.setattr(engine_module, "authorize_imaging_storage_execution", c)
    monkeypatch.setattr(engine_module, "_validate_completed_context", validate)
    monkeypatch.setattr(engine_module, "ImagingStorageEngineAttempt", fail_attempt)
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    with pytest.raises(ExpectedAttemptError) as caught:
        _step_storage(context=context)

    assert caught.value is expected
    assert type(captured["step"]) is StepResult
    _assert_rollback(context, before, references)


def test_generic_step_remains_storage_free_and_never_calls_c(monkeypatch) -> None:
    existing = (_record("generic-prior"),)
    context = _context(records=existing)

    monkeypatch.setattr(
        engine_module,
        "authorize_imaging_storage_execution",
        lambda *args, **kwargs: pytest.fail("generic step must not call C"),
    )

    result = SimulationEngine().step(context)

    assert type(result) is StepResult
    assert context.spacecraft_state.data_storage.stored_records == existing
    assert context.spacecraft_state.data_storage.stored_records[0] is existing[0]
    assert context.simulation_time_seconds == 123
    assert context.diagnostics.completed_steps == 1


def test_existing_step_imaging_remains_storage_free_and_never_calls_c(
    monkeypatch,
) -> None:
    existing = (_record("imaging-prior"),)
    context = _context(records=existing)
    arguments = _arguments(context=context)
    arguments.pop("record_id")

    monkeypatch.setattr(
        engine_module,
        "authorize_imaging_storage_execution",
        lambda *args, **kwargs: pytest.fail("old step_imaging must not call C"),
    )

    attempt = SimulationEngine().step_imaging(**arguments)

    assert type(attempt) is ImagingEngineStepAttempt
    assert type(attempt.step_result) is StepResult
    assert context.spacecraft_state.data_storage.stored_records == existing
    assert context.spacecraft_state.data_storage.stored_records[0] is existing[0]
    assert "record_id" not in signature(SimulationEngine.step_imaging).parameters


def test_successful_record_round_trips_through_schema_four_json_restart() -> None:
    existing = (_record("checkpoint-prior", bits=2.5),)
    context = _context(records=existing)
    attempt = _step_storage(
        context=context,
        record_id=AcquisitionDataRecordId("checkpoint-new"),
    )
    proposed = attempt.authorization_result.storage_admission_result.proposed_record

    checkpoint = CheckpointState.from_context(context)
    payload = json.loads(
        json.dumps(checkpoint.to_dict(), allow_nan=False, sort_keys=True)
    )
    restored = CheckpointState.from_dict(payload).restore(context.inputs)

    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == checkpoint.schema_version == 5
    assert restored == context
    assert restored.spacecraft_state.data_storage.stored_records == (
        existing + (proposed,)
    )
    assert restored.spacecraft_state.data_storage.stored_records[-1].record_id == (
        proposed.record_id
    )
    assert restored.spacecraft_state.data_storage is not (
        context.spacecraft_state.data_storage
    )
    checkpoint_at_d1 = subprocess.run(
        ["git", "show", f"{D1_COMMIT}:ops_sim/v5/checkpoint.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    checkpoint_at_d2 = subprocess.run(
        ["git", "show", f"{D2_COMMIT}:ops_sim/v5/checkpoint.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert checkpoint_at_d2 == checkpoint_at_d1


def test_success_preserves_mission_controller_and_onboard_boundaries() -> None:
    context = _context(populated_mission=True)
    mission_before = deepcopy(context.mission_state)
    controller_before = deepcopy(context.controller_state)
    onboard_before = deepcopy(context.spacecraft_state.onboard)
    knowledge_before = deepcopy(context.ground_knowledge_state)
    propulsion_before = deepcopy(context.spacecraft_state.propulsion)

    attempt = _step_storage(context=context)

    assert attempt.step_result is not None
    assert context.mission_state == mission_before
    assert context.mission_state.pending_request_ids == (
        MissionRequestId("v54d2-pending"),
    )
    assert context.mission_state.completed_request_ids == (
        MissionRequestId("v54d2-completed"),
    )
    assert context.mission_state.data_product_ids == (
        DataProductId("v54d2-product"),
    )
    assert context.controller_state == controller_before
    assert context.spacecraft_state.onboard == onboard_before
    assert context.ground_knowledge_state == knowledge_before
    assert context.spacecraft_state.propulsion == propulsion_before
    assert len(context.spacecraft_state.data_storage.stored_records) == 1


def test_storage_step_calls_one_transaction_and_c_once_on_working_context_ast(
) -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    public = _engine_method(tree, "step_imaging_to_storage")
    prepare = _engine_method(
        tree,
        "_prepare_imaging_storage_physical_integration_handler",
    )
    kernel = _engine_method(tree, "_run_transaction")

    assert _called_names(public).count("_run_transaction") == 1
    assert _called_names(public).count("step_imaging") == 0
    assert not any(
        isinstance(node, (ast.For, ast.While)) for node in ast.walk(public)
    )
    public_kernel_call = next(
        node
        for node in ast.walk(public)
        if isinstance(node, ast.Call) and _call_name(node) == "_run_transaction"
    )
    assert {keyword.arg for keyword in public_kernel_call.keywords} == {
        "physical_integration_handler_factory",
        "precommit_result_factory",
    }
    build_attempt = next(
        node
        for node in public.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_attempt"
    )
    assert _called_names(build_attempt).count("ImagingStorageEngineAttempt") == 1
    assert _called_names(prepare).count(
        "authorize_imaging_storage_execution"
    ) == 1
    assert _called_names(prepare).count(
        "_complete_coupled_physical_integration"
    ) == 1
    assert set(_called_names(prepare)).isdisjoint(
        {
            "evaluate_imaging_engine_step_authorization",
            "compute_onboard_acquisition_data_volume_proposal",
            "evaluate_storage_admission",
        }
    )
    assert set(_called_names(public)).isdisjoint(
        {"from_context", "restore", "StepResult", "_commit"}
    )
    assert _called_names(kernel).count("StepResult") == 1
    assert _called_names(kernel).count("_commit") == 1


def test_handler_appends_exact_c_record_after_tail_to_working_storage_ast() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    prepare = _engine_method(
        tree,
        "_prepare_imaging_storage_physical_integration_handler",
    )
    handler = next(
        node
        for node in prepare.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "imaging_storage_physical_integration_handler"
    )
    tail_call = next(
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and _call_name(node) == "_complete_coupled_physical_integration"
    )
    record_assignment = next(
        node
        for node in handler.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "record"
            for target in node.targets
        )
    )
    storage_assignment = next(
        node
        for node in handler.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "storage"
            for target in node.targets
        )
    )
    append_assignment = next(
        node
        for node in handler.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and target.attr == "stored_records"
            for target in node.targets
        )
    )

    assert ast.unparse(record_assignment.value) == (
        "c_result.storage_admission_result.proposed_record"
    )
    assert ast.unparse(storage_assignment.value) == (
        "working_context.spacecraft_state.data_storage"
    )
    assert ast.unparse(append_assignment.targets[0]) == "storage.stored_records"
    assert ast.unparse(append_assignment.value) == (
        "storage.stored_records + (record,)"
    )
    assert tail_call.lineno < record_assignment.lineno < append_assignment.lineno
    final_return = handler.body[-1]
    assert isinstance(final_return, ast.Return)
    assert isinstance(final_return.value, ast.Name)
    assert final_return.value.id == "physical_result"


def test_d2_engine_has_no_second_admission_capacity_or_deferred_semantics() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    public = _engine_method(tree, "step_imaging_to_storage")
    prepare = _engine_method(
        tree,
        "_prepare_imaging_storage_physical_integration_handler",
    )
    attempt = _module_class(tree, "ImagingStorageEngineAttempt")
    control = _module_class(tree, "_ImagingStorageExecutionNotAuthorized")
    scope = (public, prepare, attempt, control)
    calls = tuple(name for node in scope for name in _called_names(node))
    identifiers = {
        value.lower()
        for node in scope
        for child in ast.walk(node)
        for value in (
            (child.id,)
            if isinstance(child, ast.Name)
            else (child.attr,)
            if isinstance(child, ast.Attribute)
            else (child.name,)
            if isinstance(child, (ast.FunctionDef, ast.ClassDef))
            else ()
        )
    }
    constants = {
        child.value
        for node in scope
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
    }

    assert calls.count("authorize_imaging_storage_execution") == 1
    assert set(calls).isdisjoint(
        {
            "evaluate_imaging_engine_step_authorization",
            "compute_onboard_acquisition_data_volume_proposal",
            "evaluate_storage_admission",
            "fsum",
            "from_context",
            "restore",
            "step_imaging",
        }
    )
    assert "usable_capacity_gb" not in identifiers
    assert 8_000_000_000 not in constants
    assert identifiers.isdisjoint(
        {
            "missionrequestid",
            "dataproductid",
            "communications",
            "downlink",
            "transmission",
            "delivery",
            "remove",
            "evict",
            "compression_ratio",
            "compressed_bits",
            "throughput_bps",
            "storage_power_w",
            "obc_power_w",
            "write_energy",
            "write_heat",
            "write_rate",
            "latency",
            "duty_cycle",
        }
    )
    imported_from_storage = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").partition(".")[0] == "storage"
    ]
    assert imported_from_storage == []
    assert "StorageAdmissionResult" not in source
    assert "evaluate_storage_admission" not in source
    assert len(tuple(ElectricalLoadComponent)) == 7


def test_d1_kernel_still_has_factory_then_commit_then_bare_return() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    kernel = _engine_method(tree, "_run_transaction")
    factory_call = next(
        node
        for node in ast.walk(kernel)
        if isinstance(node, ast.Call)
        and _call_name(node) == "precommit_result_factory"
    )
    commit_call = next(
        node
        for node in ast.walk(kernel)
        if isinstance(node, ast.Call) and _call_name(node) == "_commit"
    )

    assert factory_call.lineno < commit_call.lineno
    commit_index = next(
        index
        for index, statement in enumerate(kernel.body)
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and _call_name(statement.value) == "_commit"
    )
    assert len(kernel.body[commit_index + 1 :]) == 1
    final_return = kernel.body[-1]
    assert isinstance(final_return, ast.Return)
    assert isinstance(final_return.value, ast.Name)
    assert final_return.value.id == "completion_result"


def test_d294_d1_history_and_source_register_are_exact() -> None:
    decisions = subprocess.run(
        ["git", "show", f"{D2_COMMIT}:V5_DECISION_LOG.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    heading = (
        "## D294 — V5.4D2 atomically commits one storage-authorized imaging "
        "interval and one onboard acquisition-data record"
    )

    assert decisions.count(heading) == 1
    assert decisions.index("## D293 ") < decisions.index(heading)
    assert "## D295 " not in decisions
    normalized = " ".join(decisions.partition(heading)[2].lower().split())
    for phrase in (
        "exactly once during `physical_integration`",
        "restored working context",
        "either supported c nonauthorization status",
        "exact v5.3 eps and thermal evidence",
        "shared physical and degradation tail exactly once",
        "exact c-proposed record",
        "final completed-context validation",
        "d1 precommit seam",
        "physical endpoint and record therefore commit atomically",
        "duplicate record identity and ordinary failures propagate with",
        "existing `step` and `step_imaging` apis",
        "no second admission evaluation or capacity arithmetic",
        "no mission, communications, record-removal, compression, throughput",
    ):
        assert phrase in normalized

    d1_engine = subprocess.run(
        ["git", "show", f"{D1_COMMIT}:ops_sim/v5/engine.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    d1_decisions = subprocess.run(
        ["git", "show", f"{D1_COMMIT}:V5_DECISION_LOG.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert "step_imaging_to_storage" not in d1_engine
    assert "ImagingStorageEngineAttempt" not in d1_engine
    assert "from .imaging_storage import" not in d1_engine
    assert "## D294 " not in d1_decisions

    historical_changes = set(
        subprocess.run(
            ["git", "diff", "--name-only", C_COMMIT, D1_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    historical_production = set(
        subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                C_COMMIT,
                D1_COMMIT,
                "--",
                "ops_sim/v5",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    assert historical_production == {"ops_sim/v5/engine.py"}
    assert historical_changes == {
        "V5_DECISION_LOG.md",
        "ops_sim/v5/engine.py",
        "tests/test_v53f3a_engine_transaction_refactor.py",
        "tests/test_v54c_imaging_storage_authorization.py",
        "tests/test_v54d1_engine_precommit_result.py",
    }

    d1_source_register = subprocess.run(
        ["git", "show", f"{D1_COMMIT}:V5_SOURCE_REGISTER.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    d2_source_register = subprocess.run(
        ["git", "show", f"{D2_COMMIT}:V5_SOURCE_REGISTER.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert d2_source_register == d1_source_register


def test_d2_historical_scope_is_exactly_nine_files_and_one_production_module() -> None:
    changes = set(
        subprocess.run(
            ["git", "diff", "--name-only", D1_COMMIT, D2_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    production_changes = set(
        subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                D1_COMMIT,
                D2_COMMIT,
                "--",
                "ops_sim/v5",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )

    assert production_changes == {"ops_sim/v5/engine.py"}
    assert changes == {
        "V5_DECISION_LOG.md",
        "ops_sim/v5/engine.py",
        "tests/test_v50d1_time_engine.py",
        "tests/test_v51f_eps_release_hardening.py",
        "tests/test_v53f3a_engine_transaction_refactor.py",
        "tests/test_v53f3b_imaging_engine_integration.py",
        "tests/test_v53f4b_final_release_audit.py",
        "tests/test_v54d1_engine_precommit_result.py",
        "tests/test_v54d2_imaging_storage_engine_integration.py",
    }
