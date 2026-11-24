"""Completed-state and service chronology across the existing V5 owners."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

import test_v54d2_imaging_storage_engine_integration as imaging
import test_v55b_delivery_state_checkpoint as delivery
import test_v55c_downlink_transmission as transmission
import test_v55d_downlink_engine_integration as downlink
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.data_delivery import DownlinkTransferProgress
import ops_sim.v5.engine as engine_module
from ops_sim.v5.engine import SimulationEngine


@pytest.mark.parametrize("partial", [False, True])
def test_ordinary_future_record_is_valid_but_cannot_be_onboard(partial):
    record = delivery._record("future", start=1000, duration=10)
    assert record.scheduled_start_seconds == 1000
    progress = (DownlinkTransferProgress(record.record_id, 4.0),) if partial else ()
    with pytest.raises(ValueError, match="acquisition must end.*simulation time"):
        delivery._context(
            records=(record,), partial=progress, simulation_time_seconds=100,
        )


@pytest.mark.parametrize("partial", [False, True])
def test_json_checkpoint_rejects_future_onboard_record_without_repair(partial):
    record = delivery._record("future", start=1000, duration=10)
    progress = (DownlinkTransferProgress(record.record_id, 4.0),) if partial else ()
    context = delivery._context(
        records=(record,), partial=progress, simulation_time_seconds=1010,
    )
    payload = CheckpointState.from_context(context).to_dict()
    payload["simulation_time_seconds"] = 100
    payload = json.loads(json.dumps(payload))
    before = deepcopy(payload)
    with pytest.raises(ValueError, match="acquisition must end.*simulation time"):
        CheckpointState.from_dict(payload)
    assert payload == before
    assert context.simulation_time_seconds == 1010


@pytest.mark.parametrize("boundary", ["capture", "context", "engine"])
def test_mutated_completed_clock_is_revalidated_without_state_changes(boundary):
    context = downlink._context(records=(downlink._record("future", start=90, duration=10),))
    context.simulation_time_seconds = 99
    before = deepcopy(context)
    references = downlink._authoritative_references(context)
    with pytest.raises(ValueError, match="acquisition must end.*simulation time"):
        if boundary == "capture":
            CheckpointState.from_context(context)
        elif boundary == "context":
            context.__post_init__()
        else:
            downlink._step(context, contact=downlink._contact(start=99, end=122))
    downlink._assert_rollback(context, before, references)


def test_checkpoint_restore_revalidates_incompatible_completed_time():
    context = downlink._context()
    checkpoint = CheckpointState.from_context(context)
    with pytest.raises(ValueError, match="acquisition must end.*simulation time"):
        replace(checkpoint, simulation_time_seconds=9)
    # Defense-in-depth restore check after bypassing snapshot immutability.
    object.__setattr__(checkpoint, "simulation_time_seconds", 9)
    with pytest.raises(ValueError, match="acquisition must end.*simulation time"):
        checkpoint.restore(context.inputs)
    assert context.simulation_time_seconds == 100


@pytest.mark.parametrize("capacity", [5000.0, 12000.0])
@pytest.mark.parametrize("before", [None, 1000.0])
@pytest.mark.parametrize("start", [91, 1000])
def test_premature_partial_and_complete_transmissions_are_rejected(capacity, before, start):
    record = replace(transmission._record(), scheduled_start_seconds=start)
    with pytest.raises(ValueError, match="acquisition must end.*serviced contact start"):
        transmission._evaluate(
            record=record, capacity=capacity, before=before,
            contact=transmission._contact(duration_seconds=23),
        )


@pytest.mark.parametrize("capacity", [5000.0, 12000.0])
def test_result_construction_and_revalidation_reject_premature_service(capacity):
    valid = transmission._evaluate(capacity=capacity)
    future = replace(valid.record, scheduled_start_seconds=1000)
    with pytest.raises(ValueError, match="acquisition must end.*serviced contact start"):
        replace(valid, record=future)
    object.__setattr__(valid, "record", future)
    with pytest.raises(ValueError, match="acquisition must end.*serviced contact start"):
        valid.__post_init__()


@pytest.mark.parametrize("capacity", [5000.0, 12000.0])
def test_acquisition_end_equal_to_context_and_contact_start_is_valid(capacity):
    record = downlink._record("boundary", start=90, duration=10)
    context = downlink._context(records=(record,), capacity_bits=capacity)
    assert CheckpointState.from_context(context).restore(context.inputs) == context
    downlink._step(context)
    assert context.simulation_time_seconds == 123
    if capacity < record.stored_equivalent_bits:
        assert context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits == capacity
        assert context.spacecraft_state.data_storage.stored_records == (record,)
    else:
        assert context.spacecraft_state.data_storage.stored_records == ()
        assert context.ground_data_delivery_state.completed_deliveries[0].record == record


def _imaged_context():
    # Measure only the fixture's data volume; chronology uses explicit times.
    sizing_context = imaging._context()
    imaging._step_storage(context=sizing_context)
    bits = sizing_context.spacecraft_state.data_storage.stored_records[0].stored_equivalent_bits
    context = imaging._context()
    context.inputs = replace(
        context.inputs,
        spacecraft_configuration=replace(
            context.inputs.spacecraft_configuration,
            communications=downlink._config(bits * 0.75),
        ),
    )
    imaging._step_storage(context=context)
    record = context.spacecraft_state.data_storage.stored_records[0]
    assert record.scheduled_start_seconds == 100
    assert record.acquisition_duration_seconds == 23
    assert context.simulation_time_seconds == 123
    return context, record


def test_imaging_storage_partial_restart_complete_delivery():
    context, record = _imaged_context()
    downlink._step(context, contact=downlink._contact(start=123, end=146))
    assert context.spacecraft_state.data_storage.stored_records == (record,)
    assert len(context.ground_data_delivery_state.partial_transfers) == 1
    assert context.ground_data_delivery_state.completed_deliveries == ()
    checkpoint = CheckpointState.from_dict(json.loads(json.dumps(
        CheckpointState.from_context(context).to_dict()
    )))
    restarted = checkpoint.restore(context.inputs)
    assert restarted == context
    contact = downlink._contact(start=146, end=169, name="completion")
    direct_result = downlink._step(context, contact=contact)
    restarted_result = downlink._step(restarted, contact=contact)
    assert direct_result == restarted_result
    assert restarted == context
    assert context.simulation_time_seconds == 169
    assert context.spacecraft_state.data_storage.stored_records == ()
    assert context.ground_data_delivery_state.partial_transfers == ()
    assert context.ground_data_delivery_state.completed_deliveries[0].record == record
    assert CheckpointState.from_context(context).restore(context.inputs) == context


def test_late_downlink_failure_after_imaging_preserves_original_custody(monkeypatch):
    context, record = _imaged_context()
    before = deepcopy(context)
    references = downlink._authoritative_references(context)

    def reject_result(*args):
        raise RuntimeError("late chronology regression probe")

    monkeypatch.setattr(engine_module, "DownlinkEngineStepResult", reject_result)
    monkeypatch.setattr(
        SimulationEngine, "_commit",
        staticmethod(lambda *args: pytest.fail("commit must not run")),
    )
    with pytest.raises(RuntimeError, match="late chronology regression probe"):
        downlink._step(context, contact=downlink._contact(start=123, end=146))
    downlink._assert_rollback(context, before, references)
    assert context.spacecraft_state.data_storage.stored_records == (record,)
