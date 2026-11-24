"""Atomic caller-selected downlink engine integration for V5.5D."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from inspect import Parameter, signature
import json
from math import fsum
from pathlib import Path
import subprocess

import pytest

from frozen_release_history import read_blob

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.checkpoint import CURRENT_CHECKPOINT_SCHEMA_VERSION, CheckpointState
from ops_sim.v5.communications import ServiceableGroundContact
from ops_sim.v5.configuration import CommunicationsConfig
from ops_sim.v5.data_delivery import (
    CompletedAcquisitionDelivery,
    DownlinkTransferProgress,
    GroundDataDeliveryState,
)
import ops_sim.v5.engine as engine_module
from ops_sim.v5.engine import (
    STEP_PHASE_ORDER,
    DownlinkEngineStepResult,
    SimulationEngine,
    StepResult,
)
from ops_sim.v5.ids import (
    AcquisitionDataRecordId,
    GroundContactId,
    GroundStationId,
    ImagingRequestId,
    ObservationOpportunityId,
    ParameterId,
    SubsystemConfigurationId,
)
from ops_sim.v5.onboard_data import OnboardAcquisitionDataRecord
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload import OpticalAcquisitionChannelSelection
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import DataStorageState


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
MODEL_STATUS_PATH = ROOT / "MODEL_STATUS.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
V55A_COMMIT = "b6c42a79c7ed28c6abb6685692e0a117cbdd26dc"
V55B_COMMIT = "aeba9d10493fcf7d5dd36d31556ad42f5f825d7a"
V55C_COMMIT = "f1b655c85965168aac4f694f28bdc73e78762b82"
V55D_COMMIT = "2a6674b3b48b34f68d9c2e34be97d63d0c2b2066"


def _config(capacity_bits: float) -> CommunicationsConfig:
    return CommunicationsConfig(
        SubsystemConfigurationId("v55d-communications"),
        ScalarParameter(
            capacity_bits / 23,
            ParameterProvenance(
                ParameterId("communications.nominal-downlink-data-rate"),
                ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
                "bit/s",
                (),
                ProvenanceStatus.TO_RESEARCH,
                rationale="Synthetic rate used only by V5.5D tests.",
            ),
        ),
    )


def _record(
    name: str,
    *,
    bits: float = 12_000.0,
    start: int = 0,
    duration: int = 10,
) -> OnboardAcquisitionDataRecord:
    return OnboardAcquisitionDataRecord(
        AcquisitionDataRecordId(name),
        ImagingRequestId(f"{name}-request"),
        ObservationOpportunityId(f"{name}-opportunity"),
        start,
        duration,
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        bits,
        bits,
    )


def _contact(
    *,
    start: int = 100,
    end: int = 123,
    name: str = "v55d-contact",
) -> ServiceableGroundContact:
    return ServiceableGroundContact(
        GroundContactId(name),
        GroundStationId("v55d-station"),
        start,
        end,
    )


def _completed(name: str) -> CompletedAcquisitionDelivery:
    return CompletedAcquisitionDelivery(
        _record(name, bits=100.0),
        _contact(start=50, end=60, name=f"{name}-contact"),
    )


def _context(
    *,
    records: tuple[OnboardAcquisitionDataRecord, ...] | None = None,
    partial: tuple[DownlinkTransferProgress, ...] = (),
    completed: tuple[CompletedAcquisitionDelivery, ...] = (),
    capacity_bits: float = 5_000.0,
    horizon_seconds: int = 1_000,
):
    active_records = (_record("target"),) if records is None else records
    base = build_demo_context()
    spacecraft_configuration = replace(
        base.inputs.spacecraft_configuration,
        communications=_config(capacity_bits),
    )
    inputs = replace(
        base.inputs,
        spacecraft_configuration=spacecraft_configuration,
        numerical_config=replace(
            base.inputs.numerical_config,
            timestep_seconds=23,
            geometry_sample_seconds=1,
            checkpoint_interval_seconds=23,
        ),
        common_world=replace(
            base.inputs.common_world,
            horizon_seconds=horizon_seconds,
        ),
    )
    return replace(
        base,
        simulation_time_seconds=100,
        inputs=inputs,
        spacecraft_state=replace(
            base.spacecraft_state,
            data_storage=DataStorageState(active_records),
        ),
        ground_data_delivery_state=GroundDataDeliveryState(
            partial,
            completed,
        ),
    )


def _step(
    context,
    *,
    record_id: AcquisitionDataRecordId | None = None,
    contact: ServiceableGroundContact | None = None,
) -> DownlinkEngineStepResult:
    active_record_id = (
        context.spacecraft_state.data_storage.stored_records[0].record_id
        if record_id is None
        else record_id
    )
    return SimulationEngine().step_downlink(
        context,
        _contact() if contact is None else contact,
        record_id=active_record_id,
    )


def _physical_fields(step_result: StepResult) -> tuple[object, ...]:
    return (
        step_result.eps_result,
        step_result.thermal_coupling_result,
        step_result.battery_degradation_result,
        step_result.solar_degradation_result,
        step_result.eps_capability_result,
        step_result.battery_capacity_reconciliation_result,
    )


def _authoritative_references(context) -> tuple[object, ...]:
    spacecraft = context.spacecraft_state
    delivery = context.ground_data_delivery_state
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
        delivery,
        delivery.partial_transfers,
        delivery.completed_deliveries,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def _assert_rollback(context, before, references) -> None:
    assert context == before
    assert all(
        actual is original
        for actual, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def _method(tree: ast.Module, name: str) -> ast.FunctionDef:
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


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def test_result_contract_is_exact_frozen_slotted_and_required() -> None:
    result = _step(_context())

    assert tuple(field.name for field in fields(DownlinkEngineStepResult)) == (
        "transmission_result",
        "step_result",
    )
    assert DownlinkEngineStepResult.__dataclass_params__.frozen
    assert not hasattr(result, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(DownlinkEngineStepResult)
    )
    with pytest.raises(FrozenInstanceError):
        result.step_result = None


def test_public_signature_and_export_are_exact() -> None:
    parameters = signature(SimulationEngine.step_downlink).parameters

    assert tuple(parameters) == ("self", "context", "contact", "record_id")
    assert parameters["context"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["context"].default is Parameter.empty
    assert parameters["contact"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["contact"].default is Parameter.empty
    assert parameters["record_id"].kind is Parameter.KEYWORD_ONLY
    assert parameters["record_id"].default is Parameter.empty
    assert str(signature(SimulationEngine.step_downlink)) == (
        "(self, context: 'SimulationContext', contact: "
        "'ServiceableGroundContact', *, record_id: "
        "'AcquisitionDataRecordId') -> 'DownlinkEngineStepResult'"
    )
    assert engine_module.__all__ == [
        "STEP_PHASE_ORDER",
        "DownlinkEngineStepResult",
        "ImagingEngineStepAttempt",
        "ImagingStorageEngineAttempt",
        "SimulationEngine",
        "SimulationPhase",
        "StepResult",
    ]


@pytest.mark.parametrize(
    "field_name",
    ("transmission_result", "step_result"),
)
def test_result_requires_exact_nested_types(field_name) -> None:
    result = _step(_context())

    with pytest.raises(TypeError, match=field_name):
        replace(result, **{field_name: object()})


def test_result_revalidates_nested_values_interval_and_physical_shape() -> None:
    result = _step(_context())
    corrupt_transmission = deepcopy(result.transmission_result)
    object.__setattr__(
        corrupt_transmission,
        "progress_after_equivalent_bits",
        4_999.0,
    )
    with pytest.raises(ValueError, match="progress_after"):
        replace(result, transmission_result=corrupt_transmission)

    wrong_interval = replace(
        result.step_result,
        start_time_seconds=101,
        end_time_seconds=124,
    )
    with pytest.raises(ValueError, match="contact start"):
        replace(result, step_result=wrong_interval)

    corrupt_step = deepcopy(result.step_result)
    object.__setattr__(corrupt_step, "eps_result", object())
    with pytest.raises(TypeError, match="eps_result"):
        replace(result, step_result=corrupt_step)


def test_accepted_contact_is_exactly_the_full_step() -> None:
    context = _context()
    result = SimulationEngine().step_downlink(
        context,
        _contact(start=100, end=123),
        record_id=AcquisitionDataRecordId("target"),
    )

    assert result.step_result.start_time_seconds == 100
    assert result.step_result.end_time_seconds == 123
    assert result.step_result.dt_seconds == 23
    assert result.step_result.executed_phases == STEP_PHASE_ORDER
    assert context.simulation_time_seconds == 123


@pytest.mark.parametrize(
    ("start", "end", "message"),
    (
        (99, 122, "start"),
        (101, 124, "start"),
        (100, 122, "full step end"),
        (100, 124, "full step end"),
    ),
    ids=("stale", "future-gap", "short", "long"),
)
def test_misaligned_contacts_reject_before_checkpoint(
    start,
    end,
    message,
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        lambda *args: pytest.fail("checkpoint capture must not occur"),
    )

    with pytest.raises(ValueError, match=message):
        SimulationEngine().step_downlink(
            context,
            _contact(start=start, end=end),
            record_id=AcquisitionDataRecordId("target"),
        )

    _assert_rollback(context, before, references)


def test_horizon_crossing_rejects_before_checkpoint(monkeypatch) -> None:
    context = _context(horizon_seconds=122)
    before = deepcopy(context)
    references = _authoritative_references(context)
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        lambda *args: pytest.fail("checkpoint capture must not occur"),
    )

    with pytest.raises(ValueError, match="horizon"):
        _step(context)

    _assert_rollback(context, before, references)


@pytest.mark.parametrize("argument_name", ("context", "contact", "record_id"))
def test_wrong_argument_types_reject_before_checkpoint(
    argument_name,
    monkeypatch,
) -> None:
    context = _context()
    arguments = {
        "context": context,
        "contact": _contact(),
        "record_id": AcquisitionDataRecordId("target"),
    }
    arguments[argument_name] = object()
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        lambda *args: pytest.fail("checkpoint capture must not occur"),
    )

    with pytest.raises(TypeError, match=argument_name):
        SimulationEngine().step_downlink(**arguments)


def test_forged_contact_and_record_id_reject_before_checkpoint(
    monkeypatch,
) -> None:
    context = _context()
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        lambda *args: pytest.fail("checkpoint capture must not occur"),
    )
    contact = _contact()
    object.__setattr__(contact, "end_time_seconds", 100)
    with pytest.raises(ValueError, match="end_time_seconds"):
        SimulationEngine().step_downlink(
            context,
            contact,
            record_id=AcquisitionDataRecordId("target"),
        )

    record_id = AcquisitionDataRecordId("target")
    object.__setattr__(record_id, "value", "INVALID VALUE")
    with pytest.raises(ValueError, match="StableId value"):
        SimulationEngine().step_downlink(
            context,
            _contact(),
            record_id=record_id,
        )


def test_no_progress_partial_commits_only_progress_time_and_diagnostics() -> None:
    before_record = _record("before", bits=100.0)
    target = _record("target")
    after_record = _record("after", bits=200.0)
    records = (before_record, target, after_record)
    context = _context(records=records, capacity_bits=5_000.0)
    before = deepcopy(context)

    result = _step(context, record_id=target.record_id)
    transmission = result.transmission_result

    assert transmission.status.value == "partial"
    assert transmission.record is target
    assert transmission.transmitted_equivalent_bits_this_service == 5_000.0
    assert transmission.progress_before_equivalent_bits == 0.0
    assert transmission.progress_after_equivalent_bits == 5_000.0
    assert transmission.remaining_after_equivalent_bits == 7_000.0
    assert transmission.storage_freed_equivalent_bits == 0.0
    assert context.spacecraft_state.data_storage.stored_records == records
    assert all(
        actual is expected
        for actual, expected in zip(
            context.spacecraft_state.data_storage.stored_records,
            records,
        )
    )
    assert context.ground_data_delivery_state.partial_transfers == (
        DownlinkTransferProgress(target.record_id, 5_000.0),
    )
    assert context.ground_data_delivery_state.completed_deliveries == ()
    assert context.simulation_time_seconds == 123
    assert context.diagnostics.completed_steps == (
        before.diagnostics.completed_steps + 1
    )
    assert _physical_fields(result.step_result) == (None,) * 6


def test_existing_progress_partial_replaces_only_selected_tuple_slot() -> None:
    first = _record("first", bits=20_000.0)
    target = _record("target")
    last = _record("last", bits=30_000.0)
    first_progress = DownlinkTransferProgress(first.record_id, 100.0)
    target_progress = DownlinkTransferProgress(target.record_id, 5_000.0)
    last_progress = DownlinkTransferProgress(last.record_id, 200.0)
    context = _context(
        records=(first, target, last),
        partial=(first_progress, target_progress, last_progress),
        capacity_bits=2_000.0,
    )

    result = _step(context, record_id=target.record_id)
    progress = context.ground_data_delivery_state.partial_transfers

    assert result.transmission_result.status.value == "partial"
    assert result.transmission_result.progress_before_equivalent_bits == 5_000.0
    assert result.transmission_result.progress_after_equivalent_bits == 7_000.0
    assert progress[0] is first_progress
    assert progress[1] == DownlinkTransferProgress(target.record_id, 7_000.0)
    assert progress[1] is not target_progress
    assert progress[2] is last_progress
    assert context.spacecraft_state.data_storage.stored_records == (
        first,
        target,
        last,
    )
    assert context.spacecraft_state.data_storage.stored_records[1] is target


def test_complete_moves_exact_record_and_preserves_all_unaffected_order() -> None:
    first = _record("first", bits=20_000.0)
    target = _record("target")
    last = _record("last", bits=30_000.0)
    first_progress = DownlinkTransferProgress(first.record_id, 100.0)
    target_progress = DownlinkTransferProgress(target.record_id, 5_000.0)
    last_progress = DownlinkTransferProgress(last.record_id, 200.0)
    prior_completed = _completed("prior-completed")
    context = _context(
        records=(first, target, last),
        partial=(first_progress, target_progress, last_progress),
        completed=(prior_completed,),
        capacity_bits=7_000.0,
    )
    before_occupancy = fsum(
        record.stored_equivalent_bits
        for record in context.spacecraft_state.data_storage.stored_records
    )
    contact = _contact()

    result = _step(
        context,
        record_id=target.record_id,
        contact=contact,
    )
    transmission = result.transmission_result
    records = context.spacecraft_state.data_storage.stored_records
    progress = context.ground_data_delivery_state.partial_transfers
    completed = context.ground_data_delivery_state.completed_deliveries

    assert transmission.status.value == "complete"
    assert transmission.progress_before_equivalent_bits == 5_000.0
    assert transmission.transmitted_equivalent_bits_this_service == 7_000.0
    assert transmission.progress_after_equivalent_bits == 12_000.0
    assert transmission.remaining_after_equivalent_bits == 0.0
    assert transmission.storage_freed_equivalent_bits == 12_000.0
    assert records == (first, last)
    assert records[0] is first
    assert records[1] is last
    assert progress == (first_progress, last_progress)
    assert progress[0] is first_progress
    assert progress[1] is last_progress
    assert completed[0] is prior_completed
    assert completed[-1].record is target
    assert completed[-1].completing_contact is contact
    assert before_occupancy - fsum(
        record.stored_equivalent_bits for record in records
    ) == target.stored_equivalent_bits
    assert context.simulation_time_seconds == 123
    assert result.step_result.end_time_seconds == 123
    assert _physical_fields(result.step_result) == (None,) * 6


def test_excess_completion_leaves_capacity_unused_and_second_record_untouched() -> None:
    target = _record("target")
    second = _record("second", bits=2_000.0)
    second_progress = DownlinkTransferProgress(second.record_id, 100.0)
    context = _context(
        records=(target, second),
        partial=(
            DownlinkTransferProgress(target.record_id, 5_000.0),
            second_progress,
        ),
        capacity_bits=10_000.0,
    )

    result = _step(context, record_id=target.record_id)

    assert result.transmission_result.status.value == "complete"
    assert result.transmission_result.transmitted_equivalent_bits_this_service == (
        7_000.0
    )
    assert result.transmission_result.unused_contact_capacity_bits == 3_000.0
    assert context.spacecraft_state.data_storage.stored_records == (second,)
    assert context.spacecraft_state.data_storage.stored_records[0] is second
    assert context.ground_data_delivery_state.partial_transfers == (
        second_progress,
    )
    assert context.ground_data_delivery_state.partial_transfers[0] is (
        second_progress
    )


def test_no_progress_complete_moves_record_without_persisting_zero_progress() -> None:
    target = _record("target")
    context = _context(records=(target,), capacity_bits=12_000.0)

    result = _step(context, record_id=target.record_id)

    assert result.transmission_result.status.value == "complete"
    assert result.transmission_result.progress_before_equivalent_bits == 0.0
    assert context.spacecraft_state.data_storage.stored_records == ()
    assert context.ground_data_delivery_state.partial_transfers == ()
    assert context.ground_data_delivery_state.completed_deliveries[-1].record is (
        target
    )


def test_requested_record_not_onboard_rolls_back() -> None:
    context = _context(records=(_record("other"),))
    before = deepcopy(context)
    references = _authoritative_references(context)

    with pytest.raises(ValueError, match="not onboard"):
        _step(context, record_id=AcquisitionDataRecordId("missing"))

    _assert_rollback(context, before, references)


def test_already_delivered_record_rejects_before_onboard_lookup() -> None:
    delivered = _completed("delivered")
    context = _context(
        records=(_record("other"),),
        completed=(delivered,),
    )
    before = deepcopy(context)
    references = _authoritative_references(context)

    with pytest.raises(ValueError, match="already delivered"):
        _step(context, record_id=delivered.record.record_id)

    _assert_rollback(context, before, references)


def test_corrupted_completed_context_rejects_before_checkpoint(monkeypatch) -> None:
    target = _record("target")
    progress = DownlinkTransferProgress(target.record_id, 1_000.0)
    context = _context(records=(target,), partial=(progress,))
    object.__setattr__(progress, "transmitted_equivalent_bits", float("nan"))
    references = _authoritative_references(context)
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        lambda *args: pytest.fail("checkpoint capture must not occur"),
    )

    with pytest.raises(ValueError, match="transmitted_equivalent_bits"):
        _step(context, record_id=target.record_id)

    assert all(
        actual is original
        for actual, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def test_duplicate_progress_corruption_rejects_before_checkpoint(monkeypatch) -> None:
    target = _record("target")
    progress = DownlinkTransferProgress(target.record_id, 1_000.0)
    context = _context(records=(target,), partial=(progress,))
    context.ground_data_delivery_state.partial_transfers = (progress, progress)
    references = _authoritative_references(context)
    monkeypatch.setattr(
        engine_module.CheckpointState,
        "from_context",
        lambda *args: pytest.fail("checkpoint capture must not occur"),
    )

    with pytest.raises(ValueError, match="unique"):
        _step(context, record_id=target.record_id)

    assert all(
        actual is original
        for actual, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def test_c_evaluator_is_called_once_with_exact_working_inputs(monkeypatch) -> None:
    target = _record("target")
    progress = DownlinkTransferProgress(target.record_id, 5_000.0)
    context = _context(
        records=(target,),
        partial=(progress,),
        capacity_bits=2_000.0,
    )
    contact = _contact()
    active_config = context.inputs.spacecraft_configuration.communications
    original = engine_module.evaluate_downlink_transmission
    calls = []
    returned = []

    def observe(config, supplied_contact, record, supplied_progress):
        calls.append((config, supplied_contact, record, supplied_progress))
        result = original(config, supplied_contact, record, supplied_progress)
        returned.append(result)
        return result

    monkeypatch.setattr(
        engine_module,
        "evaluate_downlink_transmission",
        observe,
    )
    result = _step(context, record_id=target.record_id, contact=contact)

    assert len(calls) == 1
    assert calls[0][0] is active_config
    assert calls[0][1] is contact
    assert calls[0][2] is target
    assert calls[0][3] is progress
    assert result.transmission_result is returned[0]


def test_evaluator_exception_propagates_with_complete_rollback(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    class ExpectedEvaluationError(ValueError):
        pass

    expected = ExpectedEvaluationError("synthetic C numerical failure")
    monkeypatch.setattr(
        engine_module,
        "evaluate_downlink_transmission",
        lambda *args: (_ for _ in ()).throw(expected),
    )

    with pytest.raises(ExpectedEvaluationError) as caught:
        _step(context)

    assert caught.value is expected
    _assert_rollback(context, before, references)


def test_wrong_evaluator_result_type_rolls_back(monkeypatch) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    monkeypatch.setattr(
        engine_module,
        "evaluate_downlink_transmission",
        lambda *args: object(),
    )

    with pytest.raises(TypeError, match="DownlinkTransmissionResult"):
        _step(context)

    _assert_rollback(context, before, references)


def test_forged_evaluator_result_is_revalidated_and_rolls_back(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    original = engine_module.evaluate_downlink_transmission

    def forged(*args):
        result = original(*args)
        object.__setattr__(
            result,
            "progress_after_equivalent_bits",
            4_999.0,
        )
        return result

    monkeypatch.setattr(
        engine_module,
        "evaluate_downlink_transmission",
        forged,
    )

    with pytest.raises(ValueError, match="progress_after"):
        _step(context)

    _assert_rollback(context, before, references)


def test_equal_but_distinct_returned_record_identity_rejects(
    monkeypatch,
) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)
    original = engine_module.evaluate_downlink_transmission

    def replace_record(*args):
        result = original(*args)
        return replace(result, record=deepcopy(result.record))

    monkeypatch.setattr(
        engine_module,
        "evaluate_downlink_transmission",
        replace_record,
    )

    with pytest.raises(ValueError, match="retain the selected"):
        _step(context)

    _assert_rollback(context, before, references)


def test_result_progress_before_must_match_persistent_progress(
    monkeypatch,
) -> None:
    target = _record("target")
    progress = DownlinkTransferProgress(target.record_id, 5_000.0)
    context = _context(records=(target,), partial=(progress,))
    before = deepcopy(context)
    references = _authoritative_references(context)
    original = engine_module.evaluate_downlink_transmission

    def ignore_progress(config, contact, record, supplied_progress):
        assert supplied_progress is progress
        return original(config, contact, record, None)

    monkeypatch.setattr(
        engine_module,
        "evaluate_downlink_transmission",
        ignore_progress,
    )

    with pytest.raises(ValueError, match="persistent progress"):
        _step(context, record_id=target.record_id)

    _assert_rollback(context, before, references)


class _FailAfterPartialMutation(SimulationEngine):
    def _failure_capability_resolution(self, context, interval):
        assert context.ground_data_delivery_state.partial_transfers[-1] == (
            DownlinkTransferProgress(AcquisitionDataRecordId("target"), 5_000.0)
        )
        raise RuntimeError("synthetic post-partial failure")


class _FailAfterCompleteMutation(SimulationEngine):
    def _failure_capability_resolution(self, context, interval):
        assert context.spacecraft_state.data_storage.stored_records == ()
        assert len(context.ground_data_delivery_state.completed_deliveries) == 1
        raise RuntimeError("synthetic post-complete failure")


@pytest.mark.parametrize(
    ("engine", "context", "message"),
    (
        (_FailAfterPartialMutation(), _context(), "post-partial"),
        (
            _FailAfterCompleteMutation(),
            _context(capacity_bits=12_000.0),
            "post-complete",
        ),
    ),
)
def test_exception_after_state_mutation_rolls_back_every_identity(
    engine,
    context,
    message,
) -> None:
    before = deepcopy(context)
    references = _authoritative_references(context)

    with pytest.raises(RuntimeError, match=message):
        engine.step_downlink(
            context,
            _contact(),
            record_id=AcquisitionDataRecordId("target"),
        )

    _assert_rollback(context, before, references)


def test_precommit_result_constructor_failure_prevents_commit(monkeypatch) -> None:
    context = _context()
    before = deepcopy(context)
    references = _authoritative_references(context)

    class ExpectedResultError(RuntimeError):
        pass

    expected = ExpectedResultError("synthetic downlink wrapper failure")

    def fail_result(*args):
        raise expected

    monkeypatch.setattr(engine_module, "DownlinkEngineStepResult", fail_result)
    monkeypatch.setattr(
        SimulationEngine,
        "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )

    with pytest.raises(ExpectedResultError) as caught:
        _step(context)

    assert caught.value is expected
    _assert_rollback(context, before, references)


def test_wrapper_is_constructed_before_exactly_one_commit(monkeypatch) -> None:
    context = _context()
    before = deepcopy(context)
    events = []
    wrappers = []
    original_wrapper = engine_module.DownlinkEngineStepResult
    original_commit = SimulationEngine._commit

    def construct(transmission, step_result):
        assert context == before
        wrapper = original_wrapper(transmission, step_result)
        wrappers.append(wrapper)
        events.append("wrapper")
        return wrapper

    def commit(original, working):
        assert len(wrappers) == 1
        events.append("commit")
        return original_commit(original, working)

    monkeypatch.setattr(engine_module, "DownlinkEngineStepResult", construct)
    monkeypatch.setattr(SimulationEngine, "_commit", staticmethod(commit))

    returned = _step(context)

    assert returned is wrappers[0]
    assert type(returned) is original_wrapper
    assert events == ["wrapper", "commit"]


@pytest.mark.parametrize("capacity", (5_000.0, 12_000.0))
def test_physical_mission_controller_and_knowledge_values_do_not_evolve(
    capacity,
) -> None:
    context = _context(capacity_bits=capacity)
    before = deepcopy(context)

    result = _step(context)

    assert context.spacecraft_state.battery == before.spacecraft_state.battery
    assert context.spacecraft_state.propulsion == before.spacecraft_state.propulsion
    assert context.spacecraft_state.thermal == before.spacecraft_state.thermal
    assert context.spacecraft_state.degradation == (
        before.spacecraft_state.degradation
    )
    assert context.spacecraft_state.onboard == before.spacecraft_state.onboard
    assert context.ground_knowledge_state == before.ground_knowledge_state
    assert context.mission_state == before.mission_state
    assert context.controller_state == before.controller_state
    assert context.simulation_time_seconds == 123
    assert context.diagnostics.completed_steps == (
        before.diagnostics.completed_steps + 1
    )
    assert _physical_fields(result.step_result) == (None,) * 6


def test_schema_five_checkpoint_restart_before_step_replays_exactly() -> None:
    target = _record("target")
    progress = DownlinkTransferProgress(target.record_id, 5_000.0)
    direct = _context(
        records=(target,),
        partial=(progress,),
        capacity_bits=2_000.0,
    )
    checkpoint_source = _context(
        records=(_record("target"),),
        partial=(
            DownlinkTransferProgress(
                AcquisitionDataRecordId("target"),
                5_000.0,
            ),
        ),
        capacity_bits=2_000.0,
    )
    payload = json.loads(
        json.dumps(
            CheckpointState.from_context(checkpoint_source).to_dict(),
            allow_nan=False,
        )
    )
    checkpoint = CheckpointState.from_dict(payload)
    restored = checkpoint.restore(checkpoint_source.inputs)
    contact = _contact()

    direct_result = SimulationEngine().step_downlink(
        direct,
        contact,
        record_id=AcquisitionDataRecordId("target"),
    )
    replay_result = SimulationEngine().step_downlink(
        restored,
        contact,
        record_id=AcquisitionDataRecordId("target"),
    )

    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == checkpoint.schema_version == 5
    assert direct_result == replay_result
    assert direct == restored
    assert restored.ground_data_delivery_state.partial_transfers == (
        DownlinkTransferProgress(AcquisitionDataRecordId("target"), 7_000.0),
    )


def test_downlink_handler_composes_one_c_call_without_arithmetic_duplication() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    prepare = _method(tree, "_prepare_downlink_physical_integration_handler")
    calls = [
        _call_name(node)
        for node in ast.walk(prepare)
        if isinstance(node, ast.Call)
    ]
    identifiers = {
        value.casefold()
        for node in ast.walk(prepare)
        for value in (
            (node.id,)
            if isinstance(node, ast.Name)
            else (node.attr,)
            if isinstance(node, ast.Attribute)
            else ()
        )
    }

    assert calls.count("evaluate_downlink_transmission") == 1
    assert set(calls).isdisjoint(
        {
            "compute_downlink_capacity",
            "fsum",
            "isclose",
            "nextafter",
            "round",
            "min",
        }
    )
    assert identifiers.isdisjoint(
        {
            "nominal_contact_capacity_bits",
            "uncompressed_equivalent_bits",
            "utilization_ratio",
            "mission_state",
            "controller_state",
            "dataproductid",
            "missionrequestid",
        }
    )


def test_common_transaction_kernel_is_unchanged_from_frozen_c() -> None:
    current_tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    historical_source = subprocess.run(
        ["git", "show", f"{V55C_COMMIT}:ops_sim/v5/engine.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    historical_tree = ast.parse(historical_source)

    assert ast.dump(
        _method(current_tree, "_run_transaction"),
        include_attributes=False,
    ) == ast.dump(
        _method(historical_tree, "_run_transaction"),
        include_attributes=False,
    )


def test_d300_docs_history_boundaries_and_scope_are_exact() -> None:
    decisions = subprocess.run(
        ["git", "show", f"{V55D_COMMIT}:V5_DECISION_LOG.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    status = subprocess.run(
        ["git", "show", f"{V55D_COMMIT}:MODEL_STATUS.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    heading = (
        "## D300 — V5.5D atomically applies one caller-selected downlink "
        "result through the shared engine transaction"
    )

    assert decisions.count(heading) == 1
    assert decisions.index("## D299 ") < decisions.index(heading)
    assert "## D301 " not in decisions
    normalized_decision = _normalized(decisions.partition(heading)[2])
    for phrase in (
        "step_downlink",
        "before checkpoint capture",
        "existing `_run_transaction`",
        "evaluate_downlink_transmission` evaluator exactly once",
        "partial replaces the selected progress tuple slot or appends",
        "complete moves the exact full record",
        "unused capacity is not reassigned",
        "constructed before commit",
        "checkpoint schema 5",
        "no transmission arithmetic",
        "mission, product, or customer completion",
    ):
        assert phrase in normalized_decision

    normalized_status = _normalized(status)
    for phrase in (
        "v5.5 is **in progress** through d",
        V55A_COMMIT,
        V55B_COMMIT,
        V55C_COMMIT,
        "atomic `simulationengine.step_downlink` execution",
        "partial updates or appends persistent transfer progress",
        "complete removes the full record from onboard storage",
        "one caller-selected record",
        "unused contact capacity is not automatically reassigned",
        "live checkpoint remains schema 5",
        "communications power and concurrent physical evolution are not modeled during v5.5 downlink bookkeeping.",
        "no orbit-derived contact generation",
        "not mission, product, or customer completion",
    ):
        assert phrase.casefold() in normalized_status

    historical_source_register = subprocess.run(
        ["git", "show", f"{V55C_COMMIT}:V5_SOURCE_REGISTER.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert read_blob(ROOT, V55D_COMMIT, "V5_SOURCE_REGISTER.md") == (
        historical_source_register
    )
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5

    protected_production = (
        "ops_sim/v5/downlink.py",
        "ops_sim/v5/data_delivery.py",
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/context.py",
        "ops_sim/v5/communications.py",
        "ops_sim/v5/storage.py",
        "ops_sim/v5/onboard_data.py",
    )
    assert subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            V55C_COMMIT,
            V55D_COMMIT,
            "--",
            *protected_production,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines() == []

    changes = set(
        subprocess.run(
            ["git", "diff", "--name-only", V55C_COMMIT, V55D_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
    )
    production = {
        path for path in changes if path.startswith("ops_sim/v5/")
    }
    assert production == {"ops_sim/v5/engine.py"}
    assert changes == {
        "MODEL_STATUS.md",
        "V5_DECISION_LOG.md",
        "ops_sim/v5/engine.py",
        "tests/test_v54d2_imaging_storage_engine_integration.py",
        "tests/test_v54f_final_release_audit.py",
        "tests/test_v55c_downlink_transmission.py",
        "tests/test_v55d_downlink_engine_integration.py",
    }
