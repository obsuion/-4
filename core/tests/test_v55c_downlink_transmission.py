"""Pure partial/complete downlink transmission evaluation for V5.5C."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from enum import Enum
from inspect import Parameter, signature
from math import isfinite
from pathlib import Path
import subprocess

import pytest

from frozen_release_history import read_blob

from ops_sim.v5.communications import (
    DownlinkCapacityProposal,
    ServiceableGroundContact,
)
from ops_sim.v5.configuration import CommunicationsConfig
from ops_sim.v5.data_delivery import DownlinkTransferProgress
import ops_sim.v5.downlink as downlink_module
from ops_sim.v5.downlink import (
    DownlinkTransmissionResult,
    DownlinkTransmissionStatus,
    evaluate_downlink_transmission,
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


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops_sim" / "v5" / "downlink.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
MODEL_STATUS_PATH = ROOT / "MODEL_STATUS.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
V55B_COMMIT = "aeba9d10493fcf7d5dd36d31556ad42f5f825d7a"
V55C_COMMIT = "f1b655c85965168aac4f694f28bdc73e78762b82"


def _config(rate_bps: object) -> CommunicationsConfig:
    return CommunicationsConfig(
        SubsystemConfigurationId("v55c-communications"),
        ScalarParameter(
            rate_bps,
            ParameterProvenance(
                ParameterId("communications.nominal-downlink-data-rate"),
                ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
                "bit/s",
                (),
                ProvenanceStatus.TO_RESEARCH,
                rationale="Synthetic rate used only by V5.5C tests.",
            ),
        ),
    )


def _contact(
    *,
    duration_seconds: int = 1,
    name: str = "v55c-contact",
) -> ServiceableGroundContact:
    return ServiceableGroundContact(
        GroundContactId(name),
        GroundStationId("v55c-station"),
        100,
        100 + duration_seconds,
    )


def _record(
    stored_bits: float = 12_000.0,
    *,
    name: str = "v55c-record",
) -> OnboardAcquisitionDataRecord:
    return OnboardAcquisitionDataRecord(
        AcquisitionDataRecordId(name),
        ImagingRequestId("v55c-request"),
        ObservationOpportunityId("v55c-opportunity"),
        0,
        10,
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        stored_bits,
        stored_bits,
    )


def _progress(
    transmitted_bits: float,
    *,
    record: OnboardAcquisitionDataRecord | None = None,
) -> DownlinkTransferProgress:
    active_record = _record() if record is None else record
    return DownlinkTransferProgress(
        active_record.record_id,
        transmitted_bits,
    )


def _evaluate(
    *,
    total: float = 12_000.0,
    before: float | None = None,
    capacity: float = 5_000.0,
    record: OnboardAcquisitionDataRecord | None = None,
    contact: ServiceableGroundContact | None = None,
) -> DownlinkTransmissionResult:
    active_record = _record(total) if record is None else record
    active_contact = _contact() if contact is None else contact
    progress = (
        None
        if before is None
        else DownlinkTransferProgress(active_record.record_id, before)
    )
    return evaluate_downlink_transmission(
        _config(capacity / (active_contact.end_time_seconds - active_contact.start_time_seconds)),
        active_contact,
        active_record,
        progress,
    )


def _method(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def test_status_members_and_values_are_exact() -> None:
    assert issubclass(DownlinkTransmissionStatus, str)
    assert issubclass(DownlinkTransmissionStatus, Enum)
    assert tuple(DownlinkTransmissionStatus) == (
        DownlinkTransmissionStatus.PARTIAL,
        DownlinkTransmissionStatus.COMPLETE,
    )
    assert tuple(item.value for item in DownlinkTransmissionStatus) == (
        "partial",
        "complete",
    )
    assert not hasattr(DownlinkTransmissionStatus, "NO_CONTACT_CAPACITY")


def test_result_contract_is_exact_frozen_slotted_and_required() -> None:
    result = _evaluate()

    assert tuple(field.name for field in fields(DownlinkTransmissionResult)) == (
        "record",
        "capacity_proposal",
        "status",
        "transmitted_equivalent_bits_this_service",
        "progress_before_equivalent_bits",
        "progress_after_equivalent_bits",
        "remaining_before_equivalent_bits",
        "remaining_after_equivalent_bits",
        "unused_contact_capacity_bits",
        "utilization_ratio",
        "storage_freed_equivalent_bits",
    )
    assert DownlinkTransmissionResult.__dataclass_params__.frozen
    assert not hasattr(result, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(DownlinkTransmissionResult)
    )
    with pytest.raises(FrozenInstanceError):
        result.status = DownlinkTransmissionStatus.COMPLETE


def test_public_signature_and_exports_are_exact() -> None:
    parameters = signature(evaluate_downlink_transmission).parameters

    assert tuple(parameters) == (
        "communications_config",
        "contact",
        "record",
        "progress",
    )
    assert all(
        parameter.kind is Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is Parameter.empty
        for parameter in parameters.values()
    )
    assert str(signature(evaluate_downlink_transmission)) == (
        "(communications_config: 'CommunicationsConfig', contact: "
        "'ServiceableGroundContact', record: 'OnboardAcquisitionDataRecord', "
        "progress: 'DownlinkTransferProgress | None') -> "
        "'DownlinkTransmissionResult'"
    )
    assert downlink_module.__all__ == [
        "DownlinkTransmissionStatus",
        "DownlinkTransmissionResult",
        "evaluate_downlink_transmission",
    ]


def test_production_imports_and_dependencies_are_narrow() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MODULE_PATH))
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported_modules == {
        "__future__",
        "dataclasses",
        "enum",
        "math",
        "communications",
        "configuration",
        "data_delivery",
        "onboard_data",
    }
    assert imported_modules.isdisjoint(
        {
            "context",
            "state",
            "checkpoint",
            "engine",
            "mission",
            "controller_state",
            "storage",
        }
    )
    identifiers = {
        value.casefold()
        for node in ast.walk(tree)
        for value in (
            (node.id,)
            if isinstance(node, ast.Name)
            else (node.attr,)
            if isinstance(node, ast.Attribute)
            else (node.name,)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
            else ()
        )
    }
    assert identifiers.isdisjoint(
        {
            "simulationcontext",
            "simulationengine",
            "checkpointstate",
            "grounddatadeliverystate",
            "completedacquisitiondelivery",
            "step_downlink",
            "stored_records",
            "remove",
            "append",
        }
    )


@pytest.mark.parametrize(
    "argument_name",
    ("communications_config", "contact", "record", "progress"),
)
def test_exact_top_level_argument_types_reject_before_capacity(
    argument_name,
    monkeypatch,
) -> None:
    record = _record()
    arguments = {
        "communications_config": _config(5_000.0),
        "contact": _contact(),
        "record": record,
        "progress": _progress(1.0, record=record),
    }
    arguments[argument_name] = object()
    monkeypatch.setattr(
        downlink_module,
        "compute_downlink_capacity",
        lambda *args: pytest.fail("capacity evaluation must not run"),
    )

    with pytest.raises(TypeError, match=argument_name):
        evaluate_downlink_transmission(**arguments)


def test_no_record_tuple_or_delivery_state_is_accepted() -> None:
    with pytest.raises(TypeError, match="record"):
        evaluate_downlink_transmission(
            _config(5_000.0),
            _contact(),
            (_record(),),
            None,
        )


def test_no_progress_partial_hand_arithmetic_is_exact() -> None:
    result = _evaluate(total=12_000.0, capacity=5_000.0)

    assert result.status is DownlinkTransmissionStatus.PARTIAL
    assert result.transmitted_equivalent_bits_this_service == 5_000.0
    assert result.progress_before_equivalent_bits == 0.0
    assert result.progress_after_equivalent_bits == 5_000.0
    assert result.remaining_before_equivalent_bits == 12_000.0
    assert result.remaining_after_equivalent_bits == 7_000.0
    assert result.unused_contact_capacity_bits == 0.0
    assert result.utilization_ratio == 1.0
    assert result.storage_freed_equivalent_bits == 0.0


def test_existing_progress_exact_completion_hand_arithmetic_is_exact() -> None:
    result = _evaluate(total=12_000.0, before=5_000.0, capacity=7_000.0)

    assert result.status is DownlinkTransmissionStatus.COMPLETE
    assert result.transmitted_equivalent_bits_this_service == 7_000.0
    assert result.progress_before_equivalent_bits == 5_000.0
    assert result.progress_after_equivalent_bits == 12_000.0
    assert result.remaining_before_equivalent_bits == 7_000.0
    assert result.remaining_after_equivalent_bits == 0.0
    assert result.unused_contact_capacity_bits == 0.0
    assert result.utilization_ratio == 1.0
    assert result.storage_freed_equivalent_bits == 12_000.0


def test_existing_progress_excess_completion_hand_arithmetic_is_exact() -> None:
    result = _evaluate(total=12_000.0, before=5_000.0, capacity=10_000.0)

    assert result.status is DownlinkTransmissionStatus.COMPLETE
    assert result.transmitted_equivalent_bits_this_service == 7_000.0
    assert result.progress_after_equivalent_bits == 12_000.0
    assert result.remaining_after_equivalent_bits == 0.0
    assert result.unused_contact_capacity_bits == 3_000.0
    assert result.utilization_ratio == 0.7
    assert result.storage_freed_equivalent_bits == 12_000.0


@pytest.mark.parametrize(
    ("capacity", "expected_unused", "expected_utilization"),
    (
        (12_000.0, 0.0, 1.0),
        (15_000.0, 3_000.0, 0.8),
    ),
    ids=("exact", "excess"),
)
def test_no_progress_exact_and_excess_completion(
    capacity,
    expected_unused,
    expected_utilization,
) -> None:
    result = _evaluate(total=12_000.0, capacity=capacity)

    assert result.status is DownlinkTransmissionStatus.COMPLETE
    assert result.transmitted_equivalent_bits_this_service == 12_000.0
    assert result.progress_before_equivalent_bits == 0.0
    assert result.progress_after_equivalent_bits == 12_000.0
    assert result.remaining_after_equivalent_bits == 0.0
    assert result.unused_contact_capacity_bits == expected_unused
    assert result.utilization_ratio == expected_utilization
    assert result.storage_freed_equivalent_bits == 12_000.0


def test_existing_progress_partial_and_tiny_capacity_are_exact() -> None:
    result = _evaluate(
        total=12_000.0,
        before=5_000.0,
        capacity=0.25,
    )

    assert result.status is DownlinkTransmissionStatus.PARTIAL
    assert result.transmitted_equivalent_bits_this_service == 0.25
    assert result.progress_after_equivalent_bits == 5_000.25
    assert result.remaining_before_equivalent_bits == 7_000.0
    assert result.remaining_after_equivalent_bits == 6_999.75
    assert result.unused_contact_capacity_bits == 0.0
    assert result.utilization_ratio == 1.0
    assert result.storage_freed_equivalent_bits == 0.0


@pytest.mark.parametrize(
    ("capacity", "expected_status"),
    (
        (6_999.0, DownlinkTransmissionStatus.PARTIAL),
        (7_000.0, DownlinkTransmissionStatus.COMPLETE),
        (7_001.0, DownlinkTransmissionStatus.COMPLETE),
    ),
)
def test_status_boundary_is_exact_without_tolerance(
    capacity,
    expected_status,
) -> None:
    result = _evaluate(
        total=12_000.0,
        before=5_000.0,
        capacity=capacity,
    )
    assert result.status is expected_status


def test_transmission_arithmetic_selects_stored_not_uncompressed_bits(
    monkeypatch,
) -> None:
    # The current upstream record contract requires these quantities to be
    # equal. Isolate revalidation only here to prove which field C reads.
    record = _record(12_000.0)
    object.__setattr__(
        record,
        "uncompressed_equivalent_bits",
        9_000_000_000.0,
    )
    monkeypatch.setattr(downlink_module, "_revalidate_record", lambda value: None)

    result = _evaluate(record=record, capacity=5_000.0)

    assert result.status is DownlinkTransmissionStatus.PARTIAL
    assert result.record is record
    assert result.remaining_before_equivalent_bits == 12_000.0
    assert result.progress_after_equivalent_bits == 5_000.0
    assert result.remaining_after_equivalent_bits == 7_000.0
    public_function = _method(
        ast.parse(MODULE_PATH.read_text(encoding="utf-8")),
        "evaluate_downlink_transmission",
    )
    assert "uncompressed_equivalent_bits" not in {
        node.attr
        for node in ast.walk(public_function)
        if isinstance(node, ast.Attribute)
    }


def test_forged_record_is_revalidated_and_rejected() -> None:
    record = _record()
    object.__setattr__(record, "stored_equivalent_bits", float("nan"))

    with pytest.raises(ValueError, match="stored_equivalent_bits"):
        evaluate_downlink_transmission(
            _config(5_000.0),
            _contact(),
            record,
            None,
        )


def test_progress_for_different_record_rejects_before_capacity(monkeypatch) -> None:
    progress = DownlinkTransferProgress(
        AcquisitionDataRecordId("another-record"),
        1.0,
    )
    monkeypatch.setattr(
        downlink_module,
        "compute_downlink_capacity",
        lambda *args: pytest.fail("capacity evaluation must not run"),
    )

    with pytest.raises(ValueError, match="record_id"):
        evaluate_downlink_transmission(
            _config(5_000.0),
            _contact(),
            _record(),
            progress,
        )


@pytest.mark.parametrize("invalid", (0.0, -1.0, float("nan")))
def test_forged_nonpositive_or_nonfinite_progress_rejects(invalid) -> None:
    record = _record()
    progress = _progress(1.0, record=record)
    object.__setattr__(progress, "transmitted_equivalent_bits", invalid)

    with pytest.raises(ValueError, match="transmitted_equivalent_bits"):
        evaluate_downlink_transmission(
            _config(5_000.0),
            _contact(),
            record,
            progress,
        )


@pytest.mark.parametrize("invalid", (12_000.0, 12_001.0))
def test_progress_at_or_above_stored_total_rejects(invalid) -> None:
    record = _record()
    progress = _progress(invalid, record=record)

    with pytest.raises(ValueError, match="progress"):
        evaluate_downlink_transmission(
            _config(5_000.0),
            _contact(),
            record,
            progress,
        )


def test_forged_progress_id_is_revalidated() -> None:
    record = _record()
    progress = _progress(1.0, record=record)
    forged_id = AcquisitionDataRecordId("forged")
    object.__setattr__(forged_id, "value", "INVALID VALUE")
    object.__setattr__(progress, "record_id", forged_id)

    with pytest.raises(ValueError, match="StableId value"):
        evaluate_downlink_transmission(
            _config(5_000.0),
            _contact(),
            record,
            progress,
        )


def test_forged_config_and_contact_are_revalidated_before_capacity() -> None:
    config = _config(5_000.0)
    object.__setattr__(
        config.nominal_downlink_data_rate_bps,
        "value",
        float("nan"),
    )
    with pytest.raises(ValueError):
        evaluate_downlink_transmission(config, _contact(), _record(), None)

    contact = _contact()
    object.__setattr__(contact, "end_time_seconds", 100)
    with pytest.raises(ValueError, match="end_time_seconds"):
        evaluate_downlink_transmission(
            _config(5_000.0),
            contact,
            _record(),
            None,
        )


def test_positive_increment_lost_to_float_resolution_rejects() -> None:
    total = 10_000_000_000_000_002.0
    before = 10_000_000_000_000_000.0
    assert before + 1.0 == before
    assert before < total

    with pytest.raises(ValueError, match="before < progress_after"):
        _evaluate(total=total, before=before, capacity=1.0)


def test_partial_increment_rounding_to_total_rejects() -> None:
    total = 10_000_000_000_000_002.0
    before = 10_000_000_000_000_000.0
    capacity = 1.5
    assert capacity < total - before
    assert before + capacity == total

    with pytest.raises(ValueError, match="before < progress_after"):
        _evaluate(total=total, before=before, capacity=capacity)


def test_nonfinite_represented_capacity_rejects_without_status() -> None:
    with pytest.raises(ValueError, match="capacity.*finite"):
        evaluate_downlink_transmission(
            _config(float.fromhex("0x1.fffffffffffffp+1023")),
            _contact(duration_seconds=2),
            _record(),
            None,
        )


def test_positive_utilization_underflow_rejects_false_zero() -> None:
    smallest_positive = float.fromhex("0x0.0000000000001p-1022")
    assert smallest_positive > 0.0
    assert smallest_positive / 1.0e308 == 0.0

    with pytest.raises(ValueError, match="utilization_ratio"):
        _evaluate(total=smallest_positive, capacity=1.0e308)


def test_capacity_is_obtained_once_through_v55a_api(monkeypatch) -> None:
    config = _config(2_500.0)
    contact = _contact(duration_seconds=2)
    record = _record()
    calls = []
    original = downlink_module.compute_downlink_capacity

    def observe(active_config, active_contact):
        calls.append((active_config, active_contact))
        return original(active_config, active_contact)

    monkeypatch.setattr(downlink_module, "compute_downlink_capacity", observe)
    result = evaluate_downlink_transmission(config, contact, record, None)

    assert calls == [(config, contact)]
    assert result.capacity_proposal.contact is contact
    assert result.capacity_proposal.nominal_contact_capacity_bits == 5_000.0
    public_function = _method(
        ast.parse(MODULE_PATH.read_text(encoding="utf-8")),
        "evaluate_downlink_transmission",
    )
    calls_in_source = [
        node.func.id
        for node in ast.walk(public_function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert calls_in_source.count("compute_downlink_capacity") == 1


def test_capacity_evaluator_wrong_result_type_rejects() -> None:
    original = downlink_module.compute_downlink_capacity
    try:
        downlink_module.compute_downlink_capacity = lambda *args: object()
        with pytest.raises(TypeError, match="DownlinkCapacityProposal"):
            _evaluate()
    finally:
        downlink_module.compute_downlink_capacity = original


@pytest.mark.parametrize("field_name", ("record", "capacity_proposal", "status"))
def test_result_rejects_wrong_exact_member_types(field_name) -> None:
    result = _evaluate()

    with pytest.raises(TypeError, match=field_name):
        replace(result, **{field_name: object()})


@pytest.mark.parametrize(
    "field_name",
    (
        "transmitted_equivalent_bits_this_service",
        "progress_before_equivalent_bits",
        "progress_after_equivalent_bits",
        "remaining_before_equivalent_bits",
        "remaining_after_equivalent_bits",
        "unused_contact_capacity_bits",
        "utilization_ratio",
        "storage_freed_equivalent_bits",
    ),
)
def test_result_numeric_evidence_requires_exact_finite_float(field_name) -> None:
    result = _evaluate()

    with pytest.raises(TypeError, match=field_name):
        replace(result, **{field_name: 1})
    with pytest.raises(ValueError, match=field_name):
        replace(result, **{field_name: float("nan")})


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    (
        ("transmitted_equivalent_bits_this_service", 4_999.0),
        ("progress_after_equivalent_bits", 4_999.0),
        ("remaining_before_equivalent_bits", 11_999.0),
        ("remaining_after_equivalent_bits", 7_001.0),
        ("unused_contact_capacity_bits", 1.0),
        ("utilization_ratio", 0.5),
        ("storage_freed_equivalent_bits", 1.0),
    ),
)
def test_partial_result_rejects_incoherent_arithmetic(field_name, invalid) -> None:
    result = _evaluate()

    with pytest.raises(ValueError):
        replace(result, **{field_name: invalid})


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    (
        ("transmitted_equivalent_bits_this_service", 6_999.0),
        ("progress_after_equivalent_bits", 11_999.0),
        ("remaining_before_equivalent_bits", 6_999.0),
        ("remaining_after_equivalent_bits", 1.0),
        ("unused_contact_capacity_bits", 1.0),
        ("utilization_ratio", 0.5),
        ("storage_freed_equivalent_bits", 0.0),
    ),
)
def test_complete_result_rejects_incoherent_arithmetic(field_name, invalid) -> None:
    result = _evaluate(total=12_000.0, before=5_000.0, capacity=7_000.0)

    with pytest.raises(ValueError):
        replace(result, **{field_name: invalid})


def test_result_rejects_status_inconsistent_with_capacity_branch() -> None:
    partial = _evaluate()
    complete = _evaluate(total=12_000.0, capacity=12_000.0)

    with pytest.raises(ValueError):
        replace(partial, status=DownlinkTransmissionStatus.COMPLETE)
    with pytest.raises(ValueError):
        replace(complete, status=DownlinkTransmissionStatus.PARTIAL)


def test_result_revalidates_nested_record_and_capacity_proposal() -> None:
    result = _evaluate()
    corrupt_record = deepcopy(result.record)
    object.__setattr__(
        corrupt_record,
        "stored_equivalent_bits",
        float("nan"),
    )
    with pytest.raises(ValueError, match="stored_equivalent_bits"):
        replace(result, record=corrupt_record)

    corrupt_capacity = deepcopy(result.capacity_proposal)
    object.__setattr__(
        corrupt_capacity,
        "nominal_contact_capacity_bits",
        4_999.0,
    )
    with pytest.raises(ValueError, match="rate times duration"):
        replace(result, capacity_proposal=corrupt_capacity)


def test_evaluation_is_pure_deterministic_and_retains_input_identities() -> None:
    config = _config(5_000.0)
    contact = _contact()
    record = _record()
    progress = _progress(1_000.0, record=record)
    inputs = (config, contact, record, progress)
    before = deepcopy(inputs)

    first = evaluate_downlink_transmission(*inputs)
    second = evaluate_downlink_transmission(*inputs)

    assert inputs == before
    assert first == second
    assert first is not second
    assert first.record is record
    assert first.capacity_proposal.contact is contact
    assert second.record is record
    assert second.capacity_proposal.contact is contact
    assert all(isfinite(value) for value in (
        first.transmitted_equivalent_bits_this_service,
        first.progress_after_equivalent_bits,
        first.remaining_after_equivalent_bits,
        first.unused_contact_capacity_bits,
        first.utilization_ratio,
        first.storage_freed_equivalent_bits,
    ))


def test_d299_frozen_status_source_stability_and_c_scope_are_exact() -> None:
    decisions = subprocess.run(
        ["git", "show", f"{V55C_COMMIT}:V5_DECISION_LOG.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    status = subprocess.run(
        ["git", "show", f"{V55C_COMMIT}:MODEL_STATUS.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    heading = (
        "## D299 — V5.5C evaluates pure partial or complete service of one "
        "onboard acquisition record"
    )
    assert decisions.count(heading) == 1
    assert decisions.index("## D298 ") < decisions.index(heading)
    assert "## D300 " not in decisions
    normalized_decision = _normalized(decisions.partition(heading)[2])
    for phrase in (
        "record.stored_equivalent_bits",
        "compute_downlink_capacity",
        "partial",
        "complete",
        "math.fsum",
        "no tolerance",
        "no state mutation",
        "no `step_downlink`",
        "not mission, product, or customer completion",
    ):
        assert phrase.casefold() in normalized_decision

    normalized_status = _normalized(status)
    for phrase in (
        "v5.5 is **in progress** through c",
        "b6c42a79c7ed28c6abb6685692e0a117cbdd26dc",
        V55B_COMMIT,
        "pure partial/complete transmission arithmetic only",
        "no state mutation or record movement",
        "no `step_downlink`",
        "live checkpoint remains schema 5",
        "communications power and concurrent physical evolution are not modeled during v5.5 downlink bookkeeping.",
        "not mission, product, or customer completion",
    ):
        assert phrase.casefold() in normalized_status

    historical_source_register = subprocess.run(
        ["git", "show", f"{V55B_COMMIT}:V5_SOURCE_REGISTER.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert read_blob(ROOT, V55C_COMMIT, "V5_SOURCE_REGISTER.md") == (
        historical_source_register
    )

    protected_paths = (
        "KAZEOSAT_PUBLIC_SPEC.md",
        "README.md",
        "V5_4_RELEASE_AUDIT.md",
        "ops_sim/v5/checkpoint.py",
        "ops_sim/v5/context.py",
        "ops_sim/v5/engine.py",
        "ops_sim/v5/state.py",
    )
    protected_changes = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            V55B_COMMIT,
            V55C_COMMIT,
            "--",
            *protected_paths,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()
    assert protected_changes == []

    tracked = set(
        subprocess.run(
            ["git", "diff", "--name-only", V55B_COMMIT, V55C_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
    )
    changes = tracked
    production = {
        path for path in changes if path.startswith("ops_sim/v5/")
    }
    assert production == {"ops_sim/v5/downlink.py"}
    assert changes == {
        "MODEL_STATUS.md",
        "V5_DECISION_LOG.md",
        "ops_sim/v5/downlink.py",
        "tests/test_v55b_delivery_state_checkpoint.py",
        "tests/test_v55c_downlink_transmission.py",
    }
