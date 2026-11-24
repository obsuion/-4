"""Persistent delivery/progress truth and checkpoint schema 5 for V5.5B."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
import json
from pathlib import Path
import subprocess

import pytest

from frozen_release_history import read_blob

import examples.v54_integrated_storage_demo as storage_demo
from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
    GroundDataDeliveryStateSnapshot,
)
from ops_sim.v5.communications import ServiceableGroundContact
from ops_sim.v5.context import SimulationContext
from ops_sim.v5.data_delivery import (
    CompletedAcquisitionDelivery,
    DownlinkTransferProgress,
    GroundDataDeliveryState,
)
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import (
    AcquisitionDataRecordId,
    GroundContactId,
    GroundStationId,
    ImagingRequestId,
    ObservationOpportunityId,
)
from ops_sim.v5.onboard_data import OnboardAcquisitionDataRecord
from ops_sim.v5.payload import OpticalAcquisitionChannelSelection
from ops_sim.v5.state import DataStorageState


ROOT = Path(__file__).resolve().parents[1]
V55A_COMMIT = "b6c42a79c7ed28c6abb6685692e0a117cbdd26dc"
V55B_COMMIT = "aeba9d10493fcf7d5dd36d31556ad42f5f825d7a"


def _record(
    name: str,
    *,
    bits: float = 10.0,
    start: int = 0,
    duration: int = 10,
    request: str = "shared-request",
    opportunity: str = "shared-opportunity",
) -> OnboardAcquisitionDataRecord:
    return OnboardAcquisitionDataRecord(
        AcquisitionDataRecordId(name),
        ImagingRequestId(request),
        ObservationOpportunityId(opportunity),
        start,
        duration,
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        bits,
        bits,
    )


def _contact(
    name: str,
    *,
    start: int = 10,
    end: int = 20,
) -> ServiceableGroundContact:
    return ServiceableGroundContact(
        GroundContactId(name),
        GroundStationId("v55b-station"),
        start,
        end,
    )


def _context(
    *,
    records: tuple[OnboardAcquisitionDataRecord, ...] = (),
    partial: tuple[DownlinkTransferProgress, ...] = (),
    completed: tuple[CompletedAcquisitionDelivery, ...] = (),
    simulation_time_seconds: int = 20,
) -> SimulationContext:
    base = build_demo_context()
    return replace(
        base,
        simulation_time_seconds=simulation_time_seconds,
        spacecraft_state=replace(
            base.spacecraft_state,
            data_storage=DataStorageState(records),
        ),
        ground_data_delivery_state=GroundDataDeliveryState(
            partial,
            completed,
        ),
    )


def _completed(
    name: str,
    *,
    contact_name: str | None = None,
    record_start: int = 0,
    record_duration: int = 10,
    contact_start: int = 10,
    contact_end: int = 20,
    request: str = "shared-request",
    opportunity: str = "shared-opportunity",
) -> CompletedAcquisitionDelivery:
    return CompletedAcquisitionDelivery(
        _record(
            name,
            start=record_start,
            duration=record_duration,
            request=request,
            opportunity=opportunity,
        ),
        _contact(
            name if contact_name is None else contact_name,
            start=contact_start,
            end=contact_end,
        ),
    )


def _valid_partial_context() -> SimulationContext:
    record = _record("partial-record")
    return _context(
        records=(record,),
        partial=(DownlinkTransferProgress(record.record_id, 4.5),),
    )


def _seed_demo_context() -> SimulationContext:
    context = storage_demo._build_demo_context()
    record = _record("preserved-partial", start=0, duration=1)
    return replace(
        context,
        spacecraft_state=replace(
            context.spacecraft_state,
            data_storage=DataStorageState((record,)),
        ),
        ground_data_delivery_state=GroundDataDeliveryState(
            (DownlinkTransferProgress(record.record_id, 4.5),),
            (),
        ),
    )


def test_delivery_dataclass_shapes_slots_mutability_and_defaults_are_exact() -> None:
    progress = DownlinkTransferProgress(
        AcquisitionDataRecordId("record-a"),
        1.0,
    )
    completed = _completed("record-b")
    state = GroundDataDeliveryState((progress,), (completed,))

    assert tuple(field.name for field in fields(DownlinkTransferProgress)) == (
        "record_id",
        "transmitted_equivalent_bits",
    )
    assert tuple(field.name for field in fields(CompletedAcquisitionDelivery)) == (
        "record",
        "completing_contact",
    )
    assert tuple(field.name for field in fields(GroundDataDeliveryState)) == (
        "partial_transfers",
        "completed_deliveries",
    )
    assert DownlinkTransferProgress.__dataclass_params__.frozen
    assert CompletedAcquisitionDelivery.__dataclass_params__.frozen
    assert not GroundDataDeliveryState.__dataclass_params__.frozen
    assert not hasattr(progress, "__dict__")
    assert not hasattr(completed, "__dict__")
    assert not hasattr(state, "__dict__")
    for contract in (
        DownlinkTransferProgress,
        CompletedAcquisitionDelivery,
        GroundDataDeliveryState,
    ):
        assert all(
            field.default is MISSING and field.default_factory is MISSING
            for field in fields(contract)
        )
    with pytest.raises(FrozenInstanceError):
        progress.transmitted_equivalent_bits = 2.0
    state.partial_transfers = ()
    assert state.partial_transfers == ()


@pytest.mark.parametrize(
    "value",
    (0.0, -1.0, float("nan"), float("inf")),
)
def test_progress_rejects_zero_negative_and_nonfinite_values(value) -> None:
    with pytest.raises(ValueError, match="transmitted_equivalent_bits"):
        DownlinkTransferProgress(AcquisitionDataRecordId("record-a"), value)


@pytest.mark.parametrize("value", (1, True, "1.0"))
def test_progress_requires_an_exact_builtin_float(value) -> None:
    with pytest.raises(TypeError, match="built-in float"):
        DownlinkTransferProgress(AcquisitionDataRecordId("record-a"), value)


def test_progress_requires_an_exact_revalidated_record_id() -> None:
    class RecordIdSubclass(AcquisitionDataRecordId):
        pass

    with pytest.raises(TypeError, match="record_id"):
        DownlinkTransferProgress(RecordIdSubclass("record-a"), 1.0)

    record_id = AcquisitionDataRecordId("record-a")
    object.__setattr__(record_id, "value", "CORRUPTED")
    with pytest.raises(ValueError, match="StableId value"):
        DownlinkTransferProgress(record_id, 1.0)


@pytest.mark.parametrize("field_name", ("record", "completing_contact"))
def test_completed_delivery_requires_exact_member_types(field_name) -> None:
    delivery = _completed("record-a")
    with pytest.raises(TypeError, match=field_name):
        replace(delivery, **{field_name: object()})


def test_completed_delivery_revalidates_forged_record_and_contact() -> None:
    record = _record("record-a")
    object.__setattr__(record, "stored_equivalent_bits", float("nan"))
    with pytest.raises(ValueError, match="stored_equivalent_bits"):
        CompletedAcquisitionDelivery(record, _contact("contact-a"))

    contact = _contact("contact-b")
    object.__setattr__(contact, "end_time_seconds", 0)
    with pytest.raises(ValueError, match="end_time_seconds"):
        CompletedAcquisitionDelivery(_record("record-b"), contact)


@pytest.mark.parametrize("field_name", ("partial_transfers", "completed_deliveries"))
def test_delivery_state_requires_exact_tuples(field_name) -> None:
    values = {"partial_transfers": (), "completed_deliveries": ()}
    values[field_name] = []
    with pytest.raises(TypeError, match=field_name):
        GroundDataDeliveryState(**values)


def test_delivery_state_requires_exact_members_and_unique_record_ids() -> None:
    with pytest.raises(TypeError, match="DownlinkTransferProgress"):
        GroundDataDeliveryState((object(),), ())
    with pytest.raises(TypeError, match="CompletedAcquisitionDelivery"):
        GroundDataDeliveryState((), (object(),))

    record_id = AcquisitionDataRecordId("record-a")
    progress = DownlinkTransferProgress(record_id, 1.0)
    with pytest.raises(ValueError, match="partial-transfer record IDs.*unique"):
        GroundDataDeliveryState((progress, replace(progress)), ())

    first = _completed("record-b", contact_name="contact-a")
    second = CompletedAcquisitionDelivery(
        replace(first.record),
        _contact("contact-b"),
    )
    with pytest.raises(ValueError, match="completed-delivery record IDs.*unique"):
        GroundDataDeliveryState((), (first, second))


def test_delivery_state_has_no_redundant_derived_fields() -> None:
    names = {field.name for field in fields(GroundDataDeliveryState)}
    assert names.isdisjoint(
        {
            "remaining_bits",
            "total_transmitted_bits",
            "backlog",
            "utilization",
            "cached_total",
            "counter",
            "data_product_id",
            "mission_request_id",
        }
    )


def test_context_places_delivery_as_required_top_level_authoritative_peer() -> None:
    context = _context()
    assert tuple(field.name for field in fields(SimulationContext)) == (
        "simulation_time_seconds",
        "inputs",
        "spacecraft_state",
        "ground_knowledge_state",
        "ground_data_delivery_state",
        "mission_state",
        "controller_state",
        "diagnostics",
    )
    assert type(context.ground_data_delivery_state) is GroundDataDeliveryState
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(SimulationContext)
    )
    with pytest.raises(TypeError, match="ground_data_delivery_state"):
        replace(context, ground_data_delivery_state=object())


def test_context_rejects_orphan_and_nonpartial_transfer_progress() -> None:
    orphan = DownlinkTransferProgress(
        AcquisitionDataRecordId("missing-record"),
        1.0,
    )
    with pytest.raises(ValueError, match="currently onboard"):
        _context(partial=(orphan,))

    record = _record("record-a")
    for value in (record.stored_equivalent_bits, 11.0):
        progress = DownlinkTransferProgress(record.record_id, value)
        with pytest.raises(ValueError, match="strictly less"):
            _context(records=(record,), partial=(progress,))


def test_context_accepts_strict_partial_progress() -> None:
    context = _valid_partial_context()
    progress = context.ground_data_delivery_state.partial_transfers[0]
    record = context.spacecraft_state.data_storage.stored_records[0]
    assert 0.0 < progress.transmitted_equivalent_bits < record.stored_equivalent_bits


def test_context_rejects_completed_record_that_is_still_onboard() -> None:
    delivery = _completed("record-a")
    with pytest.raises(ValueError, match="currently onboard"):
        _context(records=(delivery.record,), completed=(delivery,))


def test_context_rejects_partial_and_completed_identity_overlap() -> None:
    delivery = _completed("record-a")
    progress = DownlinkTransferProgress(delivery.record.record_id, 1.0)
    with pytest.raises(ValueError, match="disjoint from partial"):
        _context(partial=(progress,), completed=(delivery,))


def test_context_rejects_invalid_delivery_chronology() -> None:
    acquisition_late = _completed(
        "record-a",
        record_start=0,
        record_duration=11,
        contact_start=10,
    )
    with pytest.raises(ValueError, match="acquisition must end"):
        _context(completed=(acquisition_late,))

    contact_future = _completed("record-b", contact_end=21)
    with pytest.raises(ValueError, match="contact end"):
        _context(completed=(contact_future,), simulation_time_seconds=20)


def test_context_allows_repeated_lineage_and_shared_completing_contact() -> None:
    first = _completed("record-a", contact_name="shared-contact")
    second = _completed("record-b", contact_name="shared-contact")
    context = _context(completed=(first, second))
    assert first.record.record_id != second.record.record_id
    assert first.record.imaging_request_id == second.record.imaging_request_id
    assert (
        first.record.observation_opportunity_id
        == second.record.observation_opportunity_id
    )
    assert first.completing_contact == second.completing_contact
    assert context.ground_data_delivery_state.completed_deliveries == (
        first,
        second,
    )


def test_delivery_snapshot_contract_and_fresh_restore_are_exact() -> None:
    source = _valid_partial_context().ground_data_delivery_state
    snapshot = GroundDataDeliveryStateSnapshot.from_state(source)
    restored = snapshot.restore()
    assert tuple(field.name for field in fields(snapshot)) == (
        "partial_transfers",
        "completed_deliveries",
    )
    assert GroundDataDeliveryStateSnapshot.__dataclass_params__.frozen
    assert not hasattr(snapshot, "__dict__")
    assert restored == source
    assert restored is not source
    with pytest.raises(FrozenInstanceError):
        snapshot.partial_transfers = ()


def test_empty_delivery_state_has_exact_schema_five_json_shape() -> None:
    checkpoint = CheckpointState.from_context(_context())
    payload = checkpoint.to_dict()
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == checkpoint.schema_version == 5
    assert tuple(payload) == (
        "schema_version",
        "simulation_time_seconds",
        "input_ids",
        "spacecraft",
        "ground_knowledge",
        "ground_data_delivery",
        "mission",
        "controller",
        "diagnostics",
    )
    assert payload["ground_data_delivery"] == {
        "partial_transfers": [],
        "completed_deliveries": [],
    }
    assert CheckpointState.from_dict(payload).to_dict() == payload


@pytest.mark.parametrize("kind", ("partial", "completed", "mixed"))
def test_delivery_checkpoint_round_trip_preserves_values_order_and_ids(kind) -> None:
    first = _record("partial-a")
    second = _record("partial-b", bits=12.0)
    partial = (
        DownlinkTransferProgress(first.record_id, 1.5),
        DownlinkTransferProgress(second.record_id, 2.5),
    )
    completed = (
        _completed("completed-a", contact_name="contact-a"),
        _completed("completed-b", contact_name="contact-b"),
    )
    records = (first, second) if kind in {"partial", "mixed"} else ()
    active_partial = partial if kind in {"partial", "mixed"} else ()
    active_completed = completed if kind in {"completed", "mixed"} else ()
    context = _context(
        records=records,
        partial=active_partial,
        completed=active_completed,
    )
    payload = CheckpointState.from_context(context).to_dict()
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    parsed = CheckpointState.from_dict(json.loads(encoded))
    restored = parsed.restore(context.inputs)

    assert parsed.to_dict() == payload
    assert restored == context
    assert restored.ground_data_delivery_state is not (
        context.ground_data_delivery_state
    )
    assert restored.ground_data_delivery_state.partial_transfers == active_partial
    assert restored.ground_data_delivery_state.completed_deliveries == (
        active_completed
    )
    assert json.dumps(parsed.to_dict(), allow_nan=False, sort_keys=True) == encoded
    if active_partial:
        wire = payload["ground_data_delivery"]["partial_transfers"][0]
        assert wire["record_id"] == "acquisition-data-record:partial-a"
    if active_completed:
        wire = payload["ground_data_delivery"]["completed_deliveries"][0]
        assert wire["record"]["record_id"] == (
            "acquisition-data-record:completed-a"
        )
        assert wire["completing_contact"] == {
            "contact_id": "ground-contact:contact-a",
            "ground_station_id": "ground-station:v55b-station",
            "start_time_seconds": 10,
            "end_time_seconds": 20,
        }


@pytest.mark.parametrize(
    ("container", "key"),
    (
        ("root", "ground_data_delivery"),
        ("delivery", "partial_transfers"),
        ("progress", "record_id"),
        ("completed", "record"),
        ("contact", "contact_id"),
        ("record", "imaging_request_id"),
    ),
)
def test_parser_rejects_missing_and_extra_delivery_wire_fields(container, key) -> None:
    record = _record("partial-a")
    context = _context(
        records=(record,),
        partial=(DownlinkTransferProgress(record.record_id, 1.5),),
        completed=(_completed("completed-a"),),
    )
    payload = CheckpointState.from_context(context).to_dict()

    targets = {
        "root": payload,
        "delivery": payload["ground_data_delivery"],
        "progress": payload["ground_data_delivery"]["partial_transfers"][0],
        "completed": payload["ground_data_delivery"]["completed_deliveries"][0],
        "contact": payload["ground_data_delivery"]["completed_deliveries"][0][
            "completing_contact"
        ],
        "record": payload["ground_data_delivery"]["completed_deliveries"][0][
            "record"
        ],
    }
    del targets[container][key]
    with pytest.raises(ValueError, match="invalid keys"):
        CheckpointState.from_dict(payload)

    payload = CheckpointState.from_context(context).to_dict()
    payload["ground_data_delivery"]["unexpected"] = None
    with pytest.raises(ValueError, match="invalid keys"):
        CheckpointState.from_dict(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("partial_transfers",), ()),
        (("completed_deliveries",), ()),
        (("partial_transfers", 0, "record_id"), "imaging-request:wrong"),
        (("partial_transfers", 0, "transmitted_equivalent_bits"), 1),
        (("completed_deliveries", 0, "completing_contact", "start_time_seconds"), True),
    ),
)
def test_parser_rejects_malformed_delivery_wire_values(path, value) -> None:
    record = _record("partial-a")
    context = _context(
        records=(record,),
        partial=(DownlinkTransferProgress(record.record_id, 1.5),),
        completed=(_completed("completed-a"),),
    )
    payload = CheckpointState.from_context(context).to_dict()
    target = payload["ground_data_delivery"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises((TypeError, ValueError)):
        CheckpointState.from_dict(payload)


def test_parser_rejects_duplicate_and_cross_domain_corrupt_delivery_state() -> None:
    record = _record("partial-a")
    context = _context(
        records=(record,),
        partial=(DownlinkTransferProgress(record.record_id, 1.5),),
    )
    payload = CheckpointState.from_context(context).to_dict()
    progress = payload["ground_data_delivery"]["partial_transfers"][0]
    payload["ground_data_delivery"]["partial_transfers"].append(dict(progress))
    with pytest.raises(ValueError, match="partial-transfer record IDs.*unique"):
        CheckpointState.from_dict(payload)

    payload = CheckpointState.from_context(context).to_dict()
    payload["spacecraft"]["data_storage"]["stored_records"] = []
    with pytest.raises(ValueError, match="currently onboard"):
        CheckpointState.from_dict(payload)


def test_schema_four_is_rejected_before_schema_five_shape_and_no_migration() -> None:
    payload = CheckpointState.from_context(_context()).to_dict()
    payload["schema_version"] = 4
    del payload["ground_data_delivery"]
    with pytest.raises(ValueError, match="schema_version 4; expected 5"):
        CheckpointState.from_dict(payload)

    payload = CheckpointState.from_context(_context()).to_dict()
    payload["schema_version"] = 6
    with pytest.raises(ValueError, match="schema_version 6; expected 5"):
        CheckpointState.from_dict(payload)


def test_existing_engine_paths_preserve_nonempty_delivery_state() -> None:
    generic = _seed_demo_context()
    generic_before = generic.ground_data_delivery_state
    SimulationEngine().step(generic)
    assert generic.ground_data_delivery_state == generic_before
    assert generic.ground_data_delivery_state is not generic_before

    imaging = _seed_demo_context()
    imaging_before = imaging.ground_data_delivery_state
    arguments = storage_demo._step_arguments(imaging, 0, "v55b-imaging")
    arguments.pop("record_id")
    attempt = SimulationEngine().step_imaging(**arguments)
    assert attempt.step_result is not None
    assert imaging.ground_data_delivery_state == imaging_before

    imaging_storage = _seed_demo_context()
    delivery_before = imaging_storage.ground_data_delivery_state
    attempt = SimulationEngine().step_imaging_to_storage(
        **storage_demo._step_arguments(
            imaging_storage,
            0,
            "v55b-storage",
        )
    )
    assert attempt.step_result is not None
    assert imaging_storage.ground_data_delivery_state == delivery_before
    assert len(imaging_storage.spacecraft_state.data_storage.stored_records) == 2


class _FailAfterDeliveryMutation(SimulationEngine):
    def _action_execution(self, context, interval):
        context.ground_data_delivery_state.partial_transfers = ()
        raise RuntimeError("synthetic delivery-state rollback failure")


def test_unrelated_engine_failure_preserves_delivery_value_and_identity() -> None:
    context = _seed_demo_context()
    before = deepcopy(context)
    original_delivery = context.ground_data_delivery_state
    original_partial = context.ground_data_delivery_state.partial_transfers
    with pytest.raises(RuntimeError, match="delivery-state rollback"):
        _FailAfterDeliveryMutation().step(context)
    assert context == before
    assert context.ground_data_delivery_state is original_delivery
    assert context.ground_data_delivery_state.partial_transfers is original_partial


def test_d298_frozen_docs_source_stability_and_production_scope_are_exact() -> None:
    decisions = subprocess.run(
        ["git", "show", f"{V55B_COMMIT}:V5_DECISION_LOG.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    status = subprocess.run(
        ["git", "show", f"{V55B_COMMIT}:MODEL_STATUS.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    normalized_status = " ".join(status.split())
    source_register = read_blob(ROOT, V55B_COMMIT, "V5_SOURCE_REGISTER.md")
    historical_source_register = subprocess.run(
        ["git", "show", f"{V55A_COMMIT}:V5_SOURCE_REGISTER.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert decisions.count("## D298 ") == 1
    assert "V5.5B" in decisions.partition("## D298 ")[2]
    assert "schema 5" in decisions.partition("## D298 ")[2].lower()
    for phrase in (
        "V5.5 is **IN PROGRESS** through B",
        V55A_COMMIT,
        "live checkpoint schema 5",
        "no transmission evaluator or `step_downlink` exists yet",
        "full onboard record",
        "not customer, product, or mission completion",
    ):
        assert phrase.casefold() in normalized_status.casefold()
    assert source_register == historical_source_register

    tracked_production = set(
        subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                V55A_COMMIT,
                V55B_COMMIT,
                "--",
                "ops_sim/v5",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    assert tracked_production == {
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/context.py",
        "ops_sim/v5/data_delivery.py",
        "ops_sim/v5/engine.py",
    }
