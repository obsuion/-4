"""Pure imaging-to-storage authorization composition for V5.4C."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from enum import Enum
from inspect import Parameter, signature
from pathlib import Path
import subprocess

import pytest

from frozen_release_history import read_blob

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.adcs import CommonFrameBoresightDirection
from ops_sim.v5.ids import (
    ADCSBoresightFrameId,
    AcquisitionDataRecordId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
    ThermalNodeId,
)
from ops_sim.v5.imaging_authorization import (
    ImagingExecutionAuthorizationResult,
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
    authorize_imaging_storage_execution,
)
from ops_sim.v5.observation import ObservationOpportunity, ObservationPointing
from ops_sim.v5.observation_feasibility import (
    ObservationManeuverCandidate,
    ScheduledObservationExecution,
)
from ops_sim.v5.onboard_data import (
    OnboardAcquisitionDataRecord,
    OnboardAcquisitionDataVolumeProposal,
)
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import DataStorageState
from ops_sim.v5.storage import StorageAdmissionResult, StorageAdmissionStatus
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
MODULE_PATH = ROOT / "ops_sim" / "v5" / "imaging_storage.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
B2_BASELINE = "058eb51dce3825d163c002a002c870e5b6d6e0ad"
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
            rationale="Synthetic value used only by the V5.4C tests.",
        ),
    )


def _direction() -> CommonFrameBoresightDirection:
    return CommonFrameBoresightDirection(
        ADCSBoresightFrameId("v54c-common-frame"),
        0.0,
        0.0,
        1.0,
    )


def _previous_execution() -> ScheduledObservationExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("v54c-previous"),
        ImagingRequestId("v54c-previous-request"),
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
    channel: OpticalAcquisitionChannelSelection = (
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL
    ),
) -> ScheduledObservationAcquisitionExecution:
    opportunity = ObservationOpportunity(
        ObservationOpportunityId("v54c-next"),
        ImagingRequestId("v54c-next-request"),
        100,
        300,
        23,
        ObservationPointing(view_angle_deg, 0.0),
    )
    candidate = ObservationAcquisitionCandidate(
        ObservationManeuverCandidate(opportunity, _direction()),
        OpticalAcquisitionInput(width_m, length_m, 23, channel),
    )
    return ScheduledObservationAcquisitionExecution(candidate, 100)


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


def _zero_loads(*, base_bus_w: float = 0.0) -> PowerLoadBreakdown:
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


def _routing(context) -> ComponentHeatRoutingConfig:
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
            ThermalNodeBoundaryInput(
                node.node_id,
                temperatures[node.node_id],
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


def _record(
    record_id: str,
    *,
    bits: float = 1.0,
    request_id: ImagingRequestId | None = None,
    opportunity_id: ObservationOpportunityId | None = None,
) -> OnboardAcquisitionDataRecord:
    return OnboardAcquisitionDataRecord(
        AcquisitionDataRecordId(record_id),
        ImagingRequestId("stored-request")
        if request_id is None
        else request_id,
        ObservationOpportunityId("stored-opportunity")
        if opportunity_id is None
        else opportunity_id,
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
    fractional_acquisition: bool = False,
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
    eps = replace(spacecraft_config.eps, battery=battery)
    payload = spacecraft_config.payload
    if fractional_acquisition:
        optical = replace(
            payload.optical_acquisition,
            acquisition_bits_per_sample=replace(
                payload.optical_acquisition.acquisition_bits_per_sample,
                value=1,
            ),
            simultaneous_pan_and_multispectral=False,
        )
        payload = replace(payload, optical_acquisition=optical)
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
        eps=eps,
        payload=payload,
        storage=storage,
    )
    numerical = replace(
        base.inputs.numerical_config,
        timestep_seconds=23,
        geometry_sample_seconds=1,
        checkpoint_interval_seconds=23,
    )
    inputs = replace(
        base.inputs,
        spacecraft_configuration=spacecraft_config,
        numerical_config=numerical,
    )
    spacecraft_state = replace(
        base.spacecraft_state,
        data_storage=DataStorageState(records),
    )
    return replace(
        base,
        simulation_time_seconds=100,
        inputs=inputs,
        spacecraft_state=spacecraft_state,
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
) -> dict[str, object]:
    active_context = _context() if context is None else context
    return {
        "context": active_context,
        "previous_execution": _previous_execution()
        if previous_execution is None
        else previous_execution,
        "execution": _execution() if execution is None else execution,
        "record_id": AcquisitionDataRecordId("v54c-record")
        if record_id is None
        else record_id,
        "environment": _environment()
        if environment is None
        else environment,
        "routing_config": _routing(active_context)
        if routing_config is None
        else routing_config,
        "thermal_inputs": _thermal_inputs(active_context)
        if thermal_inputs is None
        else thermal_inputs,
        "external_heat_sources": _external_heat_sources(active_context)
        if external_heat_sources is None
        else external_heat_sources,
    }


def _authorize(**changes: object) -> ImagingStorageAuthorizationResult:
    return authorize_imaging_storage_execution(**_arguments(**changes))


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _authoritative_references(context) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
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
        context.ground_knowledge_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def test_status_members_and_values_are_exact() -> None:
    assert issubclass(ImagingStorageAuthorizationStatus, str)
    assert issubclass(ImagingStorageAuthorizationStatus, Enum)
    assert tuple(ImagingStorageAuthorizationStatus) == (
        ImagingStorageAuthorizationStatus.AUTHORIZED,
        ImagingStorageAuthorizationStatus.IMAGING_NOT_AUTHORIZED,
        ImagingStorageAuthorizationStatus.INSUFFICIENT_STORAGE_CAPACITY,
    )
    assert tuple(item.value for item in ImagingStorageAuthorizationStatus) == (
        "authorized",
        "imaging-not-authorized",
        "insufficient-storage-capacity",
    )


def test_result_contract_is_exact_frozen_slotted_and_required() -> None:
    result = _authorize()

    assert tuple(field.name for field in fields(result)) == (
        "imaging_authorization_result",
        "data_volume_proposal",
        "storage_admission_result",
        "status",
    )
    assert ImagingStorageAuthorizationResult.__dataclass_params__.frozen
    assert not hasattr(result, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(ImagingStorageAuthorizationResult)
    )
    with pytest.raises(FrozenInstanceError):
        result.status = ImagingStorageAuthorizationStatus.IMAGING_NOT_AUTHORIZED


def test_public_signature_and_exports_are_exact() -> None:
    parameters = signature(authorize_imaging_storage_execution).parameters

    assert tuple(parameters) == (
        "context",
        "previous_execution",
        "execution",
        "record_id",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
    )
    assert all(
        parameters[name].kind is Parameter.POSITIONAL_OR_KEYWORD
        and parameters[name].default is Parameter.empty
        for name in ("context", "previous_execution", "execution")
    )
    assert all(
        parameters[name].kind is Parameter.KEYWORD_ONLY
        and parameters[name].default is Parameter.empty
        for name in tuple(parameters)[3:]
    )
    assert str(signature(authorize_imaging_storage_execution)) == (
        "(context: 'SimulationContext', previous_execution: "
        "'ScheduledObservationExecution', execution: "
        "'ScheduledObservationAcquisitionExecution', *, record_id: "
        "'AcquisitionDataRecordId', environment: "
        "'AcquisitionEPSIntervalEnvironment', routing_config: "
        "'ComponentHeatRoutingConfig', thermal_inputs: "
        "'ThermalIntervalInputs', external_heat_sources: "
        "'ThermalHeatSourceInputs') -> "
        "'ImagingStorageAuthorizationResult'"
    )
    assert imaging_storage_module.__all__ == [
        "ImagingStorageAuthorizationStatus",
        "ImagingStorageAuthorizationResult",
        "authorize_imaging_storage_execution",
    ]


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
    ),
)
def test_malformed_top_level_arguments_fail_before_f2(
    argument_name,
    monkeypatch,
) -> None:
    arguments = _arguments()
    arguments[argument_name] = object()
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_imaging_engine_step_authorization",
        lambda *args: pytest.fail("F2 must not be called"),
    )

    with pytest.raises(TypeError, match=argument_name):
        authorize_imaging_storage_execution(**arguments)


def test_corrupted_record_id_fails_before_f2(monkeypatch) -> None:
    record_id = AcquisitionDataRecordId("v54c-record")
    object.__setattr__(record_id, "value", "CORRUPTED")
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_imaging_engine_step_authorization",
        lambda *args: pytest.fail("F2 must not be called"),
    )

    with pytest.raises(ValueError, match="StableId value"):
        _authorize(record_id=record_id)


@pytest.mark.parametrize(
    ("case", "context_factory", "execution_factory", "environment_factory"),
    (
        (
            "sequence-infeasible",
            lambda: _context(),
            lambda: _execution(view_angle_deg=50.0),
            lambda: _environment(),
        ),
        (
            "full-service-impossible",
            lambda: _context(max_discharge_w=60.0),
            lambda: _execution(),
            lambda: _environment(_zero_loads()),
        ),
        (
            "allocation-required",
            lambda: _context(max_discharge_w=150.0),
            lambda: _execution(),
            lambda: _environment(_zero_loads(base_bus_w=100.0)),
        ),
    ),
)
def test_f2_nonauthorization_stops_before_a1_and_b1(
    case,
    context_factory,
    execution_factory,
    environment_factory,
    monkeypatch,
) -> None:
    context = context_factory()
    arguments = _arguments(
        context=context,
        execution=execution_factory(),
        environment=environment_factory(),
    )
    before = deepcopy(context)
    references = _authoritative_references(context)
    original_f2 = (
        imaging_storage_module.evaluate_imaging_engine_step_authorization
    )
    f2_results = []

    def f2(*args):
        result = original_f2(*args)
        f2_results.append(result)
        return result

    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_imaging_engine_step_authorization",
        f2,
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "compute_onboard_acquisition_data_volume_proposal",
        lambda *args: pytest.fail("A1 must not be called"),
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_storage_admission",
        lambda *args: pytest.fail("B1 must not be called"),
    )

    result = authorize_imaging_storage_execution(**arguments)

    assert len(f2_results) == 1, case
    assert result.imaging_authorization_result is f2_results[0]
    assert result.imaging_authorization_result.status is not (
        ImagingExecutionAuthorizationStatus.AUTHORIZED
    )
    assert result.data_volume_proposal is None
    assert result.storage_admission_result is None
    assert result.status is (
        ImagingStorageAuthorizationStatus.IMAGING_NOT_AUTHORIZED
    )
    assert context == before
    assert _authoritative_references(context) == references
    assert all(
        current is original
        for current, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def test_authorized_admissible_path_calls_f2_a1_b1_once_and_reuses_objects(
    monkeypatch,
) -> None:
    arguments = _arguments()
    context = arguments["context"]
    before = deepcopy(context)
    references = _authoritative_references(context)
    originals = (
        imaging_storage_module.evaluate_imaging_engine_step_authorization,
        imaging_storage_module.compute_onboard_acquisition_data_volume_proposal,
        imaging_storage_module.evaluate_storage_admission,
    )
    calls = []
    captured = {}

    def f2(*args):
        calls.append("f2")
        result = originals[0](*args)
        captured["f2"] = result
        return result

    def a1(acquisition):
        calls.append("a1")
        expected = (
            captured["f2"].electrical_result.acquisition_evaluation
            .acquisition_result
        )
        assert acquisition is expected
        result = originals[1](acquisition)
        captured["a1"] = result
        return result

    def b1(config, records, proposed):
        calls.append("b1")
        assert config is context.inputs.spacecraft_configuration.storage
        assert records is context.spacecraft_state.data_storage.stored_records
        captured["record"] = proposed
        result = originals[2](config, records, proposed)
        captured["b1"] = result
        return result

    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_imaging_engine_step_authorization",
        f2,
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "compute_onboard_acquisition_data_volume_proposal",
        a1,
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_storage_admission",
        b1,
    )

    result = authorize_imaging_storage_execution(**arguments)

    assert calls == ["f2", "a1", "b1"]
    assert result.status is ImagingStorageAuthorizationStatus.AUTHORIZED
    assert result.imaging_authorization_result is captured["f2"]
    assert result.data_volume_proposal is captured["a1"]
    assert result.storage_admission_result is captured["b1"]
    assert result.storage_admission_result.proposed_record is captured["record"]
    assert result.data_volume_proposal.acquisition_result is (
        captured["f2"].electrical_result.acquisition_evaluation
        .acquisition_result
    )
    assert context == before
    assert all(
        current is original
        for current, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def test_record_uses_exact_execution_lineage_timing_channel_and_bits() -> None:
    arguments = _arguments()
    result = authorize_imaging_storage_execution(**arguments)
    record = result.storage_admission_result.proposed_record
    execution = arguments["execution"]
    opportunity = execution.candidate.maneuver_candidate.opportunity
    acquisition_input = execution.candidate.acquisition_input

    assert record.record_id is arguments["record_id"]
    assert record.imaging_request_id is opportunity.request_id
    assert record.observation_opportunity_id is opportunity.opportunity_id
    assert record.scheduled_start_seconds == execution.scheduled_start_seconds
    assert record.acquisition_duration_seconds == (
        acquisition_input.imaging_duration_seconds
    )
    assert record.channel_selection is acquisition_input.channel_selection
    assert record.uncompressed_equivalent_bits == (
        result.data_volume_proposal.uncompressed_equivalent_bits
    )
    assert record.stored_equivalent_bits == (
        result.data_volume_proposal.stored_equivalent_bits
    )


def test_repeated_lineage_is_allowed_with_explicit_distinct_record_id() -> None:
    execution = _execution()
    opportunity = execution.candidate.maneuver_candidate.opportunity
    existing = _record(
        "existing-record",
        request_id=opportunity.request_id,
        opportunity_id=opportunity.opportunity_id,
    )
    context = _context(records=(existing,))

    result = _authorize(
        context=context,
        execution=execution,
        record_id=AcquisitionDataRecordId("distinct-record"),
    )
    proposed = result.storage_admission_result.proposed_record

    assert result.status is ImagingStorageAuthorizationStatus.AUTHORIZED
    assert proposed.record_id != existing.record_id
    assert proposed.imaging_request_id is existing.imaging_request_id
    assert proposed.observation_opportunity_id is (
        existing.observation_opportunity_id
    )


def test_insufficient_storage_is_supported_pure_status(monkeypatch) -> None:
    context = _context(capacity_bits=11_999.0)
    arguments = _arguments(context=context)
    before = deepcopy(context)
    references = _authoritative_references(context)
    original_b1 = imaging_storage_module.evaluate_storage_admission
    admissions = []

    def b1(*args):
        result = original_b1(*args)
        admissions.append(result)
        return result

    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_storage_admission",
        b1,
    )

    result = authorize_imaging_storage_execution(**arguments)

    assert len(admissions) == 1
    assert result.imaging_authorization_result.status is (
        ImagingExecutionAuthorizationStatus.AUTHORIZED
    )
    assert type(result.data_volume_proposal) is (
        OnboardAcquisitionDataVolumeProposal
    )
    assert result.storage_admission_result is admissions[0]
    assert admissions[0].status is StorageAdmissionStatus.INSUFFICIENT_CAPACITY
    assert result.status is (
        ImagingStorageAuthorizationStatus.INSUFFICIENT_STORAGE_CAPACITY
    )
    assert context == before
    assert context.spacecraft_state.data_storage.stored_records == ()
    assert all(
        current is original
        for current, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def test_duplicate_record_id_exception_propagates_without_mutation() -> None:
    existing = _record("duplicate", bits=1.0)
    context = _context(records=(existing,))
    before = deepcopy(context)
    references = _authoritative_references(context)

    with pytest.raises(ValueError, match="record ID.*already"):
        _authorize(
            context=context,
            record_id=AcquisitionDataRecordId("duplicate"),
        )

    assert context == before
    assert all(
        current is original
        for current, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def test_fractional_equivalent_bits_survive_exactly() -> None:
    context = _context(fractional_acquisition=True)
    execution = _execution(
        width_m=3.0,
        length_m=2.5,
        channel=OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY,
    )

    result = _authorize(context=context, execution=execution)
    acquisition = (
        result.imaging_authorization_result.electrical_result
        .acquisition_evaluation.acquisition_result
    )
    record = result.storage_admission_result.proposed_record

    assert acquisition.uncompressed_equivalent_bits == 7.5
    assert result.data_volume_proposal.acquisition_result is acquisition
    assert result.data_volume_proposal.uncompressed_equivalent_bits == 7.5
    assert result.data_volume_proposal.stored_equivalent_bits == 7.5
    assert record.uncompressed_equivalent_bits == 7.5
    assert record.stored_equivalent_bits == 7.5


@pytest.mark.parametrize(
    "field_name",
    (
        "imaging_authorization_result",
        "data_volume_proposal",
        "storage_admission_result",
        "status",
    ),
)
def test_result_requires_exact_top_level_types(field_name) -> None:
    result = _authorize()

    with pytest.raises(TypeError, match=field_name):
        replace(result, **{field_name: object()})


def test_result_revalidates_complete_nested_values() -> None:
    result = _authorize()
    corrupted_f2 = deepcopy(result.imaging_authorization_result)
    object.__setattr__(
        corrupted_f2.execution.candidate.acquisition_input,
        "effective_cross_track_width_m",
        -1.0,
    )
    with pytest.raises(ValueError, match="effective_cross_track_width_m"):
        replace(result, imaging_authorization_result=corrupted_f2)

    corrupted_proposal = deepcopy(result.data_volume_proposal)
    object.__setattr__(
        corrupted_proposal,
        "stored_equivalent_bits",
        float("nan"),
    )
    with pytest.raises(ValueError, match="stored_equivalent_bits"):
        replace(result, data_volume_proposal=corrupted_proposal)

    corrupted_admission = deepcopy(result.storage_admission_result)
    object.__setattr__(
        corrupted_admission,
        "available_capacity_bits_before",
        -1.0,
    )
    with pytest.raises(ValueError, match="available_capacity_bits_before"):
        replace(result, storage_admission_result=corrupted_admission)


def test_result_status_shapes_are_exact() -> None:
    authorized = _authorize()
    nonauthorized = _authorize(execution=_execution(view_angle_deg=50.0))
    insufficient = _authorize(context=_context(capacity_bits=11_999.0))

    with pytest.raises(ValueError, match="F2 nonauthorization"):
        replace(
            authorized,
            data_volume_proposal=None,
            storage_admission_result=None,
            status=ImagingStorageAuthorizationStatus.IMAGING_NOT_AUTHORIZED,
        )
    with pytest.raises(ValueError, match="F2 authorization"):
        replace(
            nonauthorized,
            status=ImagingStorageAuthorizationStatus.AUTHORIZED,
        )
    with pytest.raises(ValueError, match="data_volume_proposal"):
        replace(authorized, data_volume_proposal=None)
    with pytest.raises(ValueError, match="storage_admission_result"):
        replace(authorized, storage_admission_result=None)
    with pytest.raises(ValueError, match="storage admission status"):
        replace(
            insufficient,
            status=ImagingStorageAuthorizationStatus.AUTHORIZED,
        )


def test_result_requires_exact_nested_acquisition_and_record_lineage() -> None:
    first = _authorize()
    second = _authorize()
    assert first.data_volume_proposal == second.data_volume_proposal
    assert first.data_volume_proposal.acquisition_result is not (
        second.data_volume_proposal.acquisition_result
    )
    with pytest.raises(ValueError, match="exact F2 acquisition"):
        replace(first, data_volume_proposal=second.data_volume_proposal)

    record = first.storage_admission_result.proposed_record
    wrong_record = replace(
        record,
        imaging_request_id=ImagingRequestId("wrong-lineage"),
    )
    wrong_admission = replace(
        first.storage_admission_result,
        proposed_record=wrong_record,
    )
    with pytest.raises(ValueError, match="imaging request lineage"):
        replace(first, storage_admission_result=wrong_admission)


@pytest.mark.parametrize(
    "case",
    ("authorized", "sequence", "insufficient"),
)
def test_evaluation_is_pure_deterministic_and_preserves_identities(case) -> None:
    if case == "authorized":
        arguments = _arguments()
    elif case == "sequence":
        arguments = _arguments(execution=_execution(view_angle_deg=50.0))
    else:
        arguments = _arguments(context=_context(capacity_bits=11_999.0))
    context = arguments["context"]
    before = deepcopy(arguments)
    references = _authoritative_references(context)

    first = authorize_imaging_storage_execution(**arguments)
    second = authorize_imaging_storage_execution(**arguments)

    assert arguments == before
    assert first == second
    assert first is not second
    assert all(
        current is original
        for current, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def test_f2_result_exception_propagates_before_a1_and_b1(monkeypatch) -> None:
    class ExpectedF2Error(RuntimeError):
        pass

    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_imaging_engine_step_authorization",
        lambda *args: (_ for _ in ()).throw(ExpectedF2Error("synthetic F2")),
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "compute_onboard_acquisition_data_volume_proposal",
        lambda *args: pytest.fail("A1 must not be called"),
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_storage_admission",
        lambda *args: pytest.fail("B1 must not be called"),
    )

    with pytest.raises(ExpectedF2Error, match="synthetic F2"):
        _authorize()


def test_a1_failure_propagates_before_b1_without_mutation(monkeypatch) -> None:
    context = _context()
    before = deepcopy(context)

    class ExpectedA1Error(RuntimeError):
        pass

    monkeypatch.setattr(
        imaging_storage_module,
        "compute_onboard_acquisition_data_volume_proposal",
        lambda *args: (_ for _ in ()).throw(ExpectedA1Error("synthetic A1")),
    )
    monkeypatch.setattr(
        imaging_storage_module,
        "evaluate_storage_admission",
        lambda *args: pytest.fail("B1 must not be called"),
    )

    with pytest.raises(ExpectedA1Error, match="synthetic A1"):
        _authorize(context=context)
    assert context == before


def test_production_composes_exactly_one_f2_a1_record_and_b1_call() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "authorize_imaging_storage_execution"
    )
    calls = [
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]

    assert calls.count("evaluate_imaging_engine_step_authorization") == 1
    assert calls.count(
        "compute_onboard_acquisition_data_volume_proposal"
    ) == 1
    assert calls.count("OnboardAcquisitionDataRecord") == 1
    assert calls.count("evaluate_storage_admission") == 1
    assert set(calls).isdisjoint(
        {
            "compute_optical_acquisition",
            "evaluate_observation_sequence_feasibility",
            "evaluate_observation_acquisition",
            "evaluate_observation_acquisition_eps",
            "evaluate_observation_acquisition_single_interval_thermal_proposal",
            "compute_eps_capability",
            "compute_eps_interval_transition",
            "compute_eps_thermal_interval_transition",
        }
    )


def test_production_dependency_and_deferred_boundaries_are_narrow() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
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
    identifiers = {
        value.lower()
        for node in ast.walk(tree)
        for value in (
            (node.id,)
            if isinstance(node, ast.Name)
            else (node.attr,)
            if isinstance(node, ast.Attribute)
            else (node.name,)
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            else ()
        )
    }

    assert "numpy" not in imported_modules
    assert imported_modules.isdisjoint(
        {"engine", "checkpoint", "mission", "communications"}
    )
    assert identifiers.isdisjoint(
        {
            "simulationengine",
            "checkpointstate",
            "missionrequestid",
            "dataproductid",
            "append",
            "remove",
            "downlink",
            "transmission",
            "delivery",
            "compression_ratio",
            "compression_factor",
            "codec",
            "throughput",
            "storage_power",
            "obc_power",
            "write_rate",
            "latency",
            "uuid",
            "random",
            "hash",
            "counter",
        }
    )
    public_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "authorize_imaging_storage_execution"
    )
    assert not any(
        isinstance(node, (ast.Assign, ast.AugAssign))
        and any(
            isinstance(target, ast.Attribute)
            and target.attr == "stored_records"
            for target in (
                node.targets if isinstance(node, ast.Assign) else (node.target,)
            )
        )
        for node in ast.walk(public_function)
    )


def test_result_has_no_generic_feasible_or_separate_record_field() -> None:
    assert {field.name for field in fields(ImagingStorageAuthorizationResult)} == {
        "imaging_authorization_result",
        "data_volume_proposal",
        "storage_admission_result",
        "status",
    }
    result = _authorize()
    assert not hasattr(result, "feasible")
    assert not hasattr(result, "proposed_record")
    assert result.storage_admission_result.proposed_record is not None


def test_d292_and_s010_record_c_semantics_without_s011() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = read_blob(ROOT, C_COMMIT, "V5_SOURCE_REGISTER.md")
    heading = (
        "## D292 — V5.4C composes physical imaging authorization with "
        "whole-record storage admission without mutation"
    )

    assert decisions.count(heading) == 1
    assert decisions.index("## D291 ") < decisions.index(heading)
    c_decisions = subprocess.run(
        ["git", "show", f"{C_COMMIT}:V5_DECISION_LOG.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert "## D293 " not in c_decisions
    normalized_decision = _normalized(decisions.partition(heading)[2])
    for phrase in (
        "f2 runs exactly once",
        "stops before data-volume or storage-admission work",
        "exact nested `opticalacquisitionresult`",
        "a1 produces the exact equivalent-bit proposal",
        "a2 record uses the caller-supplied `acquisitiondatarecordid`",
        "b1 evaluates admission against current persistent stored-record truth",
        "insufficient capacity is a supported pure nonauthorization result",
        "duplicate record identity remains an exception",
        "no state mutation or engine commit",
    ):
        assert phrase in normalized_decision

    baseline_sources = subprocess.run(
        ["git", "show", "v5.3-final:V5_SOURCE_REGISTER.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    baseline_s009 = baseline_sources.partition("### S009 ")[2].partition(
        "## Rule for Explicit Assumptions"
    )[0].rstrip()
    current_s009 = sources.partition("### S009 ")[2].partition(
        "### S010 "
    )[0].rstrip()
    assert current_s009 == baseline_s009
    assert sources.count("### S010 ") == 1
    assert "### S011 " not in sources
    c_section = sources.partition(
        "#### V5.4C pure imaging/storage authorization composition"
    )[2].partition("Status:")[0]
    normalized_sources = _normalized(c_section)
    for phrase in (
        "no new physical source or numerical spacecraft value",
        "existing v5.3 acquisition, eps, and thermal evidence",
        "level-1 equivalent-bit semantics",
        "storage capacity remains explicit configuration",
        "no recorder hardware truth",
        "no append, downlink, compression, throughput, or power model",
    ):
        assert phrase in normalized_sources


def test_c_historical_scope_is_five_files_and_one_production_module() -> None:
    production_changes = set(
        subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                B2_BASELINE,
                C_COMMIT,
                "--",
                "ops_sim/v5",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    changes = set(
        subprocess.run(
            ["git", "diff", "--name-only", B2_BASELINE, C_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )

    assert production_changes == {"ops_sim/v5/imaging_storage.py"}
    assert changes == {
        "V5_DECISION_LOG.md",
        "V5_SOURCE_REGISTER.md",
        "ops_sim/v5/imaging_storage.py",
        "tests/test_v54b2_persistent_storage_checkpoint.py",
        "tests/test_v54c_imaging_storage_authorization.py",
    }
