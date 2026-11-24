"""Persistent onboard storage truth and checkpoint schema 4 for V5.4B2."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
import json
from inspect import Parameter, signature
from math import fsum
from pathlib import Path
import subprocess

import pytest

from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
    DataStorageStateSnapshot,
    SpacecraftStateSnapshot,
)
from ops_sim.v5.context import SimulationContext
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import (
    AcquisitionDataRecordId,
    ImagingRequestId,
    ObservationOpportunityId,
)
from ops_sim.v5.onboard_data import OnboardAcquisitionDataRecord
from ops_sim.v5.payload import OpticalAcquisitionChannelSelection
from ops_sim.v5.state import DataStorageState, SpacecraftState
import ops_sim.v5.storage as storage_module
from ops_sim.v5.storage import validate_storage_records_against_config


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "ops_sim" / "v5" / "state.py"
CONTEXT_PATH = ROOT / "ops_sim" / "v5" / "context.py"
CHECKPOINT_PATH = ROOT / "ops_sim" / "v5" / "checkpoint.py"
ENGINE_PATH = ROOT / "ops_sim" / "v5" / "engine.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
MODEL_STATUS_PATH = ROOT / "MODEL_STATUS.md"
B1_BASELINE = "45c2771285028c40d0a975b3453f8d182934a38f"
B2_COMMIT = "058eb51dce3825d163c002a002c870e5b6d6e0ad"


def _record(
    record_id: str,
    *,
    bits: float = 7.5,
    request_id: str = "shared-request",
    opportunity_id: str = "shared-opportunity",
    start_seconds: int = 100,
    duration_seconds: int = 60,
    channel: OpticalAcquisitionChannelSelection = (
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL
    ),
) -> OnboardAcquisitionDataRecord:
    return OnboardAcquisitionDataRecord(
        AcquisitionDataRecordId(record_id),
        ImagingRequestId(request_id),
        ObservationOpportunityId(opportunity_id),
        start_seconds,
        duration_seconds,
        channel,
        bits,
        bits,
    )


def _context(
    records: tuple[OnboardAcquisitionDataRecord, ...] = (),
    *,
    capacity_bits: float | None = None,
) -> SimulationContext:
    base = build_demo_context()
    inputs = base.inputs
    if capacity_bits is not None:
        storage = inputs.spacecraft_configuration.storage
        storage = replace(
            storage,
            usable_capacity_gb=replace(
                storage.usable_capacity_gb,
                value=capacity_bits / 8_000_000_000.0,
            ),
        )
        inputs = replace(
            inputs,
            spacecraft_configuration=replace(
                inputs.spacecraft_configuration,
                storage=storage,
            ),
        )
    base.spacecraft_state.data_storage = DataStorageState(records)
    return SimulationContext(
        500,  # All fixture acquisitions end by 479 s before this checkpoint.
        inputs,
        base.spacecraft_state,
        base.ground_knowledge_state,
        base.ground_data_delivery_state,
        base.mission_state,
        base.controller_state,
        base.diagnostics,
    )


def _reconstruct(context: SimulationContext) -> SimulationContext:
    return SimulationContext(
        context.simulation_time_seconds,
        context.inputs,
        context.spacecraft_state,
        context.ground_knowledge_state,
        context.ground_data_delivery_state,
        context.mission_state,
        context.controller_state,
        context.diagnostics,
    )


def test_data_storage_state_contract_is_exact_mutable_slotted_and_required() -> None:
    records = (_record("record-a"), _record("record-b"))
    state = DataStorageState(records)

    assert tuple(field.name for field in fields(DataStorageState)) == (
        "stored_records",
    )
    field = fields(DataStorageState)[0]
    assert field.default is MISSING
    assert field.default_factory is MISSING
    assert not DataStorageState.__dataclass_params__.frozen
    assert not hasattr(state, "__dict__")
    assert state.stored_records is records
    assert DataStorageState(()).stored_records == ()

    replacement = (_record("record-c"),)
    state.stored_records = replacement
    assert state.stored_records is replacement


@pytest.mark.parametrize(
    "invalid_collection",
    (
        lambda record: [record],
        lambda record: iter((record,)),
        lambda record: {record},
    ),
    ids=("list", "generator", "set"),
)
def test_data_storage_state_requires_exact_builtin_tuple(
    invalid_collection,
) -> None:
    record = _record("record-a")

    with pytest.raises(TypeError, match="tuple"):
        DataStorageState(invalid_collection(record))


def test_data_storage_state_requires_exact_record_members() -> None:
    record = _record("record-a")

    with pytest.raises(TypeError, match="OnboardAcquisitionDataRecord"):
        DataStorageState((object(),))

    class RecordSubclass(OnboardAcquisitionDataRecord):
        pass

    subclass = RecordSubclass(
        *(getattr(record, field.name) for field in fields(record))
    )
    with pytest.raises(TypeError, match="OnboardAcquisitionDataRecord"):
        DataStorageState((subclass,))


def test_data_storage_state_constructor_revalidates_complete_records() -> None:
    record = _record("record-a")
    object.__setattr__(record, "stored_equivalent_bits", float("nan"))

    with pytest.raises(ValueError, match="stored_equivalent_bits"):
        DataStorageState((record,))


def test_duplicate_record_ids_reject_but_repeated_lineage_is_allowed() -> None:
    first = _record("record-a")
    second = _record("record-b")
    state = DataStorageState((first, second))

    assert state.stored_records == (first, second)
    assert first.imaging_request_id == second.imaging_request_id
    assert (
        first.observation_opportunity_id
        == second.observation_opportunity_id
    )
    with pytest.raises(ValueError, match="record IDs.*unique"):
        DataStorageState((first, _record("record-a")))


def test_data_storage_state_has_no_redundant_or_deferred_fields() -> None:
    assert {field.name for field in fields(DataStorageState)}.isdisjoint(
        {
            "stored_equivalent_bits",
            "occupancy_bits",
            "capacity_bits",
            "available_capacity_bits",
            "communications_status",
            "downlink_status",
            "mission_status",
            "product_status",
            "compressed_bits",
            "write_power_w",
            "throughput",
        }
    )


def test_spacecraft_state_has_explicit_final_data_storage_peer() -> None:
    storage = DataStorageState((_record("record-a"),))
    spacecraft = replace(_context().spacecraft_state, data_storage=storage)

    assert tuple(field.name for field in fields(SpacecraftState)) == (
        "battery",
        "propulsion",
        "thermal",
        "degradation",
        "onboard",
        "data_storage",
    )
    assert type(spacecraft.data_storage) is DataStorageState
    assert spacecraft.data_storage is storage
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(SpacecraftState)
    )
    with pytest.raises(TypeError, match="data_storage"):
        replace(spacecraft, data_storage=object())


def test_spacecraft_and_context_revalidate_mutated_storage_truth() -> None:
    context = _context((_record("record-a"),))
    context.spacecraft_state.data_storage.stored_records = []

    with pytest.raises(TypeError, match="stored_records.*tuple"):
        replace(
            context.spacecraft_state,
            data_storage=context.spacecraft_state.data_storage,
        )
    with pytest.raises(TypeError, match="stored_records.*tuple"):
        _reconstruct(context)


def test_public_storage_validator_signature_and_export_are_exact() -> None:
    parameters = signature(validate_storage_records_against_config).parameters

    assert tuple(parameters) == ("storage_config", "stored_records")
    assert all(
        parameter.kind is Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is Parameter.empty
        for parameter in parameters.values()
    )
    assert str(signature(validate_storage_records_against_config)) == (
        "(storage_config: 'StorageConfig', stored_records: "
        "'tuple[OnboardAcquisitionDataRecord, ...]') -> 'None'"
    )
    assert storage_module.__all__ == [
        "StorageAdmissionStatus",
        "StorageAdmissionResult",
        "evaluate_storage_admission",
        "validate_storage_records_against_config",
    ]


def test_storage_validator_and_context_admit_exact_capacity_boundary() -> None:
    records = (_record("record-a", bits=3.0), _record("record-b", bits=5.0))
    config = _context(capacity_bits=8.0).inputs.spacecraft_configuration.storage

    assert validate_storage_records_against_config(config, records) is None
    context = _context(records, capacity_bits=8.0)
    assert context.spacecraft_state.data_storage.stored_records == records


def test_public_storage_validator_handles_empty_duplicate_and_corrupt_records() -> None:
    config = _context(capacity_bits=8.0).inputs.spacecraft_configuration.storage

    assert validate_storage_records_against_config(config, ()) is None
    duplicate = _record("duplicate", bits=1.0)
    with pytest.raises(ValueError, match="record IDs.*unique"):
        validate_storage_records_against_config(
            config,
            (duplicate, _record("duplicate", bits=1.0)),
        )

    corrupt = _record("corrupt", bits=1.0)
    object.__setattr__(corrupt, "stored_equivalent_bits", float("nan"))
    with pytest.raises(ValueError, match="stored_equivalent_bits"):
        validate_storage_records_against_config(config, (corrupt,))


def test_context_capacity_uses_authoritative_complete_sequence_fsum() -> None:
    values = (10_000_000_000_000_000.0, 0.5, 0.75)
    complete_sequence = fsum(values)
    collapsed_prefix = fsum((fsum(values[:-1]), values[-1]))
    records = tuple(
        _record(f"record-{index}", bits=value)
        for index, value in enumerate(values)
    )

    assert complete_sequence == 10_000_000_000_000_002.0
    assert collapsed_prefix == 10_000_000_000_000_000.0
    assert complete_sequence != collapsed_prefix

    config = _context(
        capacity_bits=collapsed_prefix
    ).inputs.spacecraft_configuration.storage
    with pytest.raises(ValueError, match="occupancy exceeds"):
        validate_storage_records_against_config(config, records)
    with pytest.raises(ValueError, match="occupancy exceeds"):
        _context(records, capacity_bits=collapsed_prefix)

    admitted = _context(records, capacity_bits=complete_sequence)
    assert fsum(
        record.stored_equivalent_bits
        for record in admitted.spacecraft_state.data_storage.stored_records
    ) == complete_sequence


def test_context_delegates_capacity_validation_without_duplicate_arithmetic() -> None:
    tree = ast.parse(CONTEXT_PATH.read_text(encoding="utf-8"))
    context_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "SimulationContext"
    )
    post_init = next(
        node
        for node in context_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    calls = [
        node.func.id
        for node in ast.walk(post_init)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    attributes = {
        node.attr
        for node in ast.walk(post_init)
        if isinstance(node, ast.Attribute)
    }
    numeric_constants = {
        node.value
        for node in ast.walk(post_init)
        if isinstance(node, ast.Constant)
        and type(node.value) in {int, float}
    }

    assert calls.count("validate_storage_records_against_config") == 1
    assert "fsum" not in calls
    assert "usable_capacity_gb" not in attributes
    assert 8_000_000_000 not in numeric_constants


def test_storage_snapshot_is_exact_frozen_slotted_and_restores_fresh_state() -> None:
    state = DataStorageState((_record("record-a"), _record("record-b")))
    snapshot = DataStorageStateSnapshot.from_state(state)
    restored = snapshot.restore()

    assert tuple(field.name for field in fields(DataStorageStateSnapshot)) == (
        "stored_records",
    )
    field = fields(DataStorageStateSnapshot)[0]
    assert field.default is MISSING
    assert field.default_factory is MISSING
    assert DataStorageStateSnapshot.__dataclass_params__.frozen
    assert not hasattr(snapshot, "__dict__")
    assert restored == state
    assert restored is not state
    assert restored.stored_records == state.stored_records
    with pytest.raises(FrozenInstanceError):
        snapshot.stored_records = ()


def test_storage_snapshot_requires_exact_state_and_revalidates_records() -> None:
    with pytest.raises(TypeError, match="DataStorageState"):
        DataStorageStateSnapshot.from_state(object())

    record = _record("record-a")
    object.__setattr__(record, "uncompressed_equivalent_bits", float("nan"))
    with pytest.raises(ValueError, match="uncompressed_equivalent_bits"):
        DataStorageStateSnapshot((record,))


def test_storage_snapshot_preserves_order_and_rejects_duplicate_record_ids() -> None:
    first = _record("record-a")
    second = _record("record-b")
    snapshot = DataStorageStateSnapshot((first, second))

    assert snapshot.stored_records == (first, second)
    with pytest.raises(ValueError, match="record IDs.*unique"):
        DataStorageStateSnapshot((first, _record("record-a")))


def test_spacecraft_snapshot_has_exact_final_storage_field() -> None:
    snapshot = SpacecraftStateSnapshot.from_state(_context().spacecraft_state)

    assert tuple(field.name for field in fields(SpacecraftStateSnapshot)) == (
        "battery_energy_wh",
        "delta_v_remaining_m_per_s",
        "thermal",
        "degradation",
        "operational_mode",
        "fdir_state",
        "accepted_plan_id",
        "accepted_authority_id",
        "last_qualifying_contact_time_seconds",
        "critical_energy_since_seconds",
        "data_storage",
    )
    assert type(snapshot.data_storage) is DataStorageStateSnapshot
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(SpacecraftStateSnapshot)
    )


def test_live_schema_five_captures_ordered_storage_and_fresh_restore() -> None:
    records = (
        _record("record-a", bits=7.5),
        _record("record-b", bits=11.25, start_seconds=200),
    )
    context = _context(records)
    checkpoint = CheckpointState.from_context(context)
    restored = checkpoint.restore(context.inputs)

    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    assert checkpoint.schema_version == 5
    assert checkpoint.spacecraft.data_storage.stored_records == records
    assert restored == context
    assert restored.spacecraft_state is not context.spacecraft_state
    assert restored.spacecraft_state.data_storage is not (
        context.spacecraft_state.data_storage
    )
    assert restored.spacecraft_state.data_storage.stored_records == records


def test_checkpoint_json_storage_shape_and_encodings_are_exact() -> None:
    records = (
        _record(
            "record-a",
            bits=7.5,
            request_id="request-a",
            opportunity_id="opportunity-a",
            start_seconds=123,
            duration_seconds=17,
            channel=OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY,
        ),
        _record(
            "record-b",
            bits=11.25,
            request_id="request-b",
            opportunity_id="opportunity-b",
            start_seconds=456,
            duration_seconds=23,
            channel=OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY,
        ),
    )
    payload = CheckpointState.from_context(_context(records)).to_dict()
    storage_payload = payload["spacecraft"]["data_storage"]

    assert tuple(storage_payload) == ("stored_records",)
    assert storage_payload["stored_records"] == [
        {
            "record_id": "acquisition-data-record:record-a",
            "imaging_request_id": "imaging-request:request-a",
            "observation_opportunity_id": (
                "observation-opportunity:opportunity-a"
            ),
            "scheduled_start_seconds": 123,
            "acquisition_duration_seconds": 17,
            "channel_selection": "panchromatic-only",
            "uncompressed_equivalent_bits": 7.5,
            "stored_equivalent_bits": 7.5,
        },
        {
            "record_id": "acquisition-data-record:record-b",
            "imaging_request_id": "imaging-request:request-b",
            "observation_opportunity_id": (
                "observation-opportunity:opportunity-b"
            ),
            "scheduled_start_seconds": 456,
            "acquisition_duration_seconds": 23,
            "channel_selection": "multispectral-only",
            "uncompressed_equivalent_bits": 11.25,
            "stored_equivalent_bits": 11.25,
        },
    ]
    first_record = storage_payload["stored_records"][0]
    assert tuple(first_record) == (
        "record_id",
        "imaging_request_id",
        "observation_opportunity_id",
        "scheduled_start_seconds",
        "acquisition_duration_seconds",
        "channel_selection",
        "uncompressed_equivalent_bits",
        "stored_equivalent_bits",
    )
    assert type(first_record["scheduled_start_seconds"]) is int
    assert type(first_record["acquisition_duration_seconds"]) is int
    assert type(first_record["uncompressed_equivalent_bits"]) is float
    assert type(first_record["stored_equivalent_bits"]) is float


def test_checkpoint_dict_json_parse_restore_round_trip_is_deterministic() -> None:
    records = (_record("record-a"), _record("record-b", bits=11.25))
    context = _context(records)
    first = CheckpointState.from_context(context).to_dict()
    second = CheckpointState.from_context(_context(records)).to_dict()
    encoded = json.dumps(first, allow_nan=False, sort_keys=True)
    parsed = CheckpointState.from_dict(json.loads(encoded))

    assert first == second
    assert parsed.to_dict() == first
    assert parsed.restore(context.inputs) == context
    assert json.dumps(parsed.to_dict(), allow_nan=False, sort_keys=True) == encoded


def test_current_parser_rejects_schema_three_before_shape_without_migration() -> None:
    payload = CheckpointState.from_context(_context()).to_dict()
    payload["schema_version"] = 3
    del payload["spacecraft"]["data_storage"]

    with pytest.raises(ValueError, match="schema_version 3; expected 5"):
        CheckpointState.from_dict(payload)


@pytest.mark.parametrize("schema_version", (2, 4, 6, 999))
def test_current_parser_rejects_previous_and_future_schema_versions(
    schema_version,
) -> None:
    payload = CheckpointState.from_context(_context()).to_dict()
    payload["schema_version"] = schema_version

    with pytest.raises(
        ValueError,
        match=rf"schema_version {schema_version}; expected 5",
    ):
        CheckpointState.from_dict(payload)


def test_parser_rejects_missing_malformed_and_extra_storage_container() -> None:
    payload = CheckpointState.from_context(_context()).to_dict()
    del payload["spacecraft"]["data_storage"]
    with pytest.raises(ValueError, match="missing"):
        CheckpointState.from_dict(payload)

    payload = CheckpointState.from_context(_context()).to_dict()
    payload["spacecraft"]["data_storage"] = ()
    with pytest.raises(TypeError, match="data_storage must be a dict"):
        CheckpointState.from_dict(payload)

    payload = CheckpointState.from_context(_context()).to_dict()
    payload["spacecraft"]["data_storage"]["unexpected"] = None
    with pytest.raises(ValueError, match="invalid keys"):
        CheckpointState.from_dict(payload)


def test_parser_requires_exact_storage_container_and_record_keys() -> None:
    payload = CheckpointState.from_context(
        _context((_record("record-a"),))
    ).to_dict()
    payload["spacecraft"]["data_storage"]["stored_records"] = tuple(
        payload["spacecraft"]["data_storage"]["stored_records"]
    )
    with pytest.raises(TypeError, match="stored_records must be a list"):
        CheckpointState.from_dict(payload)

    for mutation in ("missing", "extra"):
        payload = CheckpointState.from_context(
            _context((_record("record-a"),))
        ).to_dict()
        record = payload["spacecraft"]["data_storage"]["stored_records"][0]
        if mutation == "missing":
            del record["record_id"]
        else:
            record["unexpected"] = None
        with pytest.raises(ValueError, match="invalid keys"):
            CheckpointState.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    (
        ("record_id", "imaging-request:wrong-prefix"),
        ("imaging_request_id", "request-without-prefix"),
        (
            "observation_opportunity_id",
            "imaging-request:wrong-prefix",
        ),
        ("channel_selection", "not-a-channel"),
        ("scheduled_start_seconds", True),
        ("scheduled_start_seconds", 1.0),
        ("acquisition_duration_seconds", True),
        ("uncompressed_equivalent_bits", 7),
        ("stored_equivalent_bits", 7),
        ("stored_equivalent_bits", float("nan")),
    ),
)
def test_parser_rejects_malformed_record_values(field_name, invalid) -> None:
    payload = CheckpointState.from_context(
        _context((_record("record-a"),))
    ).to_dict()
    record = payload["spacecraft"]["data_storage"]["stored_records"][0]
    record[field_name] = invalid

    with pytest.raises((TypeError, ValueError)):
        CheckpointState.from_dict(payload)


def test_parser_rejects_duplicate_record_ids_after_reconstruction() -> None:
    payload = CheckpointState.from_context(
        _context((_record("record-a"),))
    ).to_dict()
    records = payload["spacecraft"]["data_storage"]["stored_records"]
    records.append(dict(records[0]))

    with pytest.raises(ValueError, match="record IDs.*unique"):
        CheckpointState.from_dict(payload)


def test_parser_is_config_independent_but_restore_enforces_active_capacity() -> None:
    context = _context((_record("record-a", bits=7.5),), capacity_bits=8.0)
    payload = CheckpointState.from_context(context).to_dict()
    record = payload["spacecraft"]["data_storage"]["stored_records"][0]
    record["uncompressed_equivalent_bits"] = 9.0
    record["stored_equivalent_bits"] = 9.0

    parsed = CheckpointState.from_dict(payload)
    assert parsed.spacecraft.data_storage.stored_records[0].stored_equivalent_bits == 9.0
    with pytest.raises(ValueError, match="occupancy exceeds"):
        parsed.restore(context.inputs)


def test_checkpoint_capture_rejects_mutated_over_capacity_context() -> None:
    context = _context(capacity_bits=8.0)
    storage = DataStorageState((_record("record-a", bits=9.0),))
    context.spacecraft_state.data_storage = storage

    with pytest.raises(ValueError, match="occupancy exceeds"):
        CheckpointState.from_context(context)
    assert context.spacecraft_state.data_storage is storage


@pytest.mark.parametrize(
    "records",
    (
        (),
        (_record("record-a"), _record("record-b", bits=11.25)),
    ),
    ids=("empty", "multiple-records"),
)
def test_empty_and_populated_storage_restart_preserves_values_and_order(
    records,
) -> None:
    context = _context(records)
    restored = CheckpointState.from_dict(
        json.loads(
            json.dumps(
                CheckpointState.from_context(context).to_dict(),
                allow_nan=False,
            )
        )
    ).restore(context.inputs)

    assert restored == context
    assert restored.spacecraft_state.data_storage is not (
        context.spacecraft_state.data_storage
    )
    assert restored.spacecraft_state.data_storage.stored_records == records


def test_repeated_checkpoint_restore_cycles_keep_order_and_fresh_state() -> None:
    records = tuple(
        _record(f"record-{index}", bits=float(index) + 0.5)
        for index in range(1, 5)
    )
    context = _context(records)
    generations = [
        (
            context,
            context.spacecraft_state,
            context.spacecraft_state.data_storage,
        )
    ]

    for _ in range(4):
        previous_context, previous_spacecraft, previous_storage = (
            generations[-1]
        )
        context = CheckpointState.from_dict(
            CheckpointState.from_context(context).to_dict()
        ).restore(context.inputs)
        assert context is not previous_context
        assert context.spacecraft_state is not previous_spacecraft
        assert context.spacecraft_state.data_storage is not previous_storage
        assert context.spacecraft_state.data_storage.stored_records == records
        generations.append(
            (
                context,
                context.spacecraft_state,
                context.spacecraft_state.data_storage,
            )
        )

    assert all(
        current[2] is not earlier[2]
        for index, current in enumerate(generations)
        for earlier in generations[:index]
    )


def _run_steps(context: SimulationContext, count: int) -> None:
    engine = SimulationEngine()
    for _ in range(count):
        engine.step(context)


def test_populated_midpoint_restart_matches_uninterrupted_execution() -> None:
    records = (_record("record-a"), _record("record-b", bits=11.25))
    direct = _context(records)
    split = _context(records)

    _run_steps(direct, 4)
    _run_steps(split, 2)
    restored = CheckpointState.from_context(split).restore(split.inputs)
    _run_steps(restored, 2)

    assert restored == direct
    assert restored.spacecraft_state.data_storage.stored_records == records


def test_successful_engine_step_carries_storage_as_fresh_equal_state() -> None:
    records = (_record("record-a"), _record("record-b", bits=11.25))
    context = _context(records)
    original_storage = context.spacecraft_state.data_storage

    SimulationEngine().step(context)

    assert context.spacecraft_state.data_storage == original_storage
    assert context.spacecraft_state.data_storage is not original_storage
    assert context.spacecraft_state.data_storage.stored_records == records


class _FailAfterStorageWorkingMutation(SimulationEngine):
    def _action_execution(self, context, interval):
        context.spacecraft_state.data_storage.stored_records = ()

    def _failure_capability_resolution(self, context, interval):
        raise RuntimeError("synthetic post-storage working failure")


def test_failed_engine_transaction_preserves_storage_value_and_identity() -> None:
    records = (_record("record-a"), _record("record-b", bits=11.25))
    context = _context(records)
    before = deepcopy(context)
    original_spacecraft = context.spacecraft_state
    original_storage = context.spacecraft_state.data_storage

    with pytest.raises(RuntimeError, match="post-storage"):
        _FailAfterStorageWorkingMutation().step(context)

    assert context == before
    assert context.spacecraft_state is original_spacecraft
    assert context.spacecraft_state.data_storage is original_storage
    assert context.spacecraft_state.data_storage.stored_records == records


def test_engine_validation_and_checkpoint_clone_explicitly_carry_storage() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ENGINE_PATH))
    spacecraft_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SpacecraftState"
    ]

    assert len(spacecraft_calls) == 1
    attributes = {
        node.attr
        for node in ast.walk(spacecraft_calls[0])
        if isinstance(node, ast.Attribute)
    }
    assert "data_storage" in attributes
    assert source.count("CheckpointState.from_context(context)") == 1
    assert source.count("checkpoint.restore(context.inputs)") == 1


def test_b2_production_boundaries_contain_no_deferred_storage_behavior() -> None:
    fields_by_type = {
        DataStorageState: {field.name for field in fields(DataStorageState)},
        DataStorageStateSnapshot: {
            field.name for field in fields(DataStorageStateSnapshot)
        },
    }
    forbidden_fields = {
        "record_creation",
        "append_result",
        "removed_records",
        "downlink_status",
        "communications_status",
        "mission_status",
        "product_status",
        "overwrite_policy",
        "evicted_records",
        "compressed_bits",
        "storage_power_w",
        "throughput_bps",
    }
    assert all(names.isdisjoint(forbidden_fields) for names in fields_by_type.values())

    historical_sources = tuple(
        subprocess.run(
            ["git", "show", f"{B2_COMMIT}:{relative_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
        for relative_path in (
            "ops_sim/v5/state.py",
            "ops_sim/v5/context.py",
            "ops_sim/v5/checkpoint.py",
        )
    )
    historical_trees = tuple(ast.parse(source) for source in historical_sources)
    imported_roots = {
        (node.module or "").partition(".")[0]
        for tree in historical_trees
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported_roots.isdisjoint(
        {"communications", "mission_completion", "controller_policy"}
    )


def test_d291_s010_and_current_model_status_record_b2_boundaries() -> None:
    decisions = " ".join(
        DECISION_LOG_PATH.read_text(encoding="utf-8").lower().split()
    )
    sources = " ".join(
        SOURCE_REGISTER_PATH.read_text(encoding="utf-8").lower().split()
    )
    status = " ".join(
        MODEL_STATUS_PATH.read_text(encoding="utf-8").lower().split()
    )

    assert decisions.count("## d291 ") == 1
    for phrase in (
        "datastoragestate",
        "no hidden empty default",
        "complete-sequence `math.fsum`",
        "schema advances from 3 to 4",
        "accepts schema 4 only and rejects schema 3",
        "no admission- policy change",
    ):
        assert phrase in decisions
    for phrase in (
        "v5.4b2 persistent storage state and checkpoint schema 4",
        "no new physical source or spacecraft numerical value",
        "complete ordered-sequence `math.fsum`",
        "rejects schema 3",
        "no record creation from imaging",
        "communications or downlink",
    ):
        assert phrase in sources
    assert "explicit persistent spacecraft truth" in status
    assert "checkpoint schema 4" in status


def test_historical_schema_tags_remain_unchanged_while_live_schema_is_five() -> None:
    historical_checkpoint = subprocess.run(
        ["git", "show", "v5.3-final:ops_sim/v5/checkpoint.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout

    historical_v54_checkpoint = subprocess.run(
        ["git", "show", "v5.4-final:ops_sim/v5/checkpoint.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout

    assert "CURRENT_CHECKPOINT_SCHEMA_VERSION = 3" in historical_checkpoint
    assert "DataStorageStateSnapshot" not in historical_checkpoint
    assert "CURRENT_CHECKPOINT_SCHEMA_VERSION = 4" in historical_v54_checkpoint
    assert "GroundDataDeliveryStateSnapshot" not in historical_v54_checkpoint
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5


def test_b2_historical_scope_is_exactly_forty_files_and_five_production_modules() -> None:
    production_changes = set(
        subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                B1_BASELINE,
                B2_COMMIT,
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
            ["git", "diff", "--name-only", B1_BASELINE, B2_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )

    assert production_changes == {
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/context.py",
        "ops_sim/v5/engine.py",
        "ops_sim/v5/state.py",
        "ops_sim/v5/storage.py",
    }
    assert changes == {
        "MODEL_STATUS.md",
        "V5_DECISION_LOG.md",
        "V5_SOURCE_REGISTER.md",
        "examples/v52_integrated_eps_thermal_demo.py",
        "examples/v53_integrated_imaging_demo.py",
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/context.py",
        "ops_sim/v5/engine.py",
        "ops_sim/v5/state.py",
        "ops_sim/v5/storage.py",
        "tests/test_v50b3_state_domains.py",
        "tests/test_v50b4_context_checkpoint.py",
        "tests/test_v50d1_time_engine.py",
        "tests/test_v50d2_atomic_transitions.py",
        "tests/test_v51d_eps_engine_integration.py",
        "tests/test_v51e_eps_validation.py",
        "tests/test_v51f_eps_release_hardening.py",
        "tests/test_v52a2_thermal_state_checkpoint.py",
        "tests/test_v52d1_degradation_state.py",
        "tests/test_v52d2b1_degradation_config_ownership.py",
        "tests/test_v52d2b2_degradation_engine_integration.py",
        "tests/test_v52e1_eps_thermal_engine.py",
        "tests/test_v52e2_degradation_capability_coupling.py",
        "tests/test_v52f1_integrated_release.py",
        "tests/test_v52f2_final_release_audit.py",
        "tests/test_v53b1_payload_acquisition_config.py",
        "tests/test_v53c1_adcs_maneuver_config.py",
        "tests/test_v53c2_adcs_boresight_transition.py",
        "tests/test_v53c3_observation_transition_feasibility.py",
        "tests/test_v53d_observation_acquisition_composition.py",
        "tests/test_v53e1_imaging_eps_resources.py",
        "tests/test_v53e2_imaging_thermal_proposal.py",
        "tests/test_v53f1_imaging_execution_contracts.py",
        "tests/test_v53f2_imaging_authorization.py",
        "tests/test_v53f3a_engine_transaction_refactor.py",
        "tests/test_v53f3b_imaging_engine_integration.py",
        "tests/test_v53f4a_integrated_imaging_demo.py",
        "tests/test_v53f4b_final_release_audit.py",
        "tests/test_v54b1_storage_admission.py",
        "tests/test_v54b2_persistent_storage_checkpoint.py",
    }
