"""Pure onboard-storage capacity and whole-record admission for V5.4B1."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from inspect import Parameter, signature
from math import fsum
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from frozen_release_history import read_blob

from ops_sim.v5.configuration import StorageConfig
from ops_sim.v5.ids import (
    AcquisitionDataRecordId,
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
import ops_sim.v5.storage as storage_module
from ops_sim.v5.storage import (
    StorageAdmissionResult,
    StorageAdmissionStatus,
    evaluate_storage_admission,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops_sim" / "v5" / "storage.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
A2_BASELINE = "fcd084ee1ed7af3be81955e58111a8a65de2a3a0"
B1_COMMIT = "45c2771285028c40d0a975b3453f8d182934a38f"


def _parameter(value: object) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId("storage.usable-capacity"),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            "GB",
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by the V5.4B1 tests.",
        ),
    )


def _config(usable_capacity_gb: object = 1.0) -> StorageConfig:
    return StorageConfig(
        SubsystemConfigurationId("storage-b1"),
        _parameter(usable_capacity_gb),
    )


def _record(
    record_id: str = "record-one",
    *,
    bits: float = 1.0,
    request_id: str = "request-one",
    opportunity_id: str = "opportunity-one",
) -> OnboardAcquisitionDataRecord:
    return OnboardAcquisitionDataRecord(
        AcquisitionDataRecordId(record_id),
        ImagingRequestId(request_id),
        ObservationOpportunityId(opportunity_id),
        100,
        60,
        OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        bits,
        bits,
    )


def _direct_result() -> StorageAdmissionResult:
    return StorageAdmissionResult(
        _record(bits=2.0),
        8.0,
        3.0,
        5.0,
        5.0,
        StorageAdmissionStatus.ADMISSIBLE,
    )


def _function(tree: ast.Module | ast.ClassDef, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _normalized(value: str) -> str:
    return " ".join(value.lower().split())


def test_status_members_and_values_are_exact() -> None:
    assert issubclass(StorageAdmissionStatus, str)
    assert issubclass(StorageAdmissionStatus, Enum)
    assert tuple(StorageAdmissionStatus) == (
        StorageAdmissionStatus.ADMISSIBLE,
        StorageAdmissionStatus.INSUFFICIENT_CAPACITY,
    )
    assert tuple(item.value for item in StorageAdmissionStatus) == (
        "admissible",
        "insufficient-capacity",
    )


def test_result_contract_is_exact_frozen_slotted_and_required() -> None:
    result = _direct_result()

    assert tuple(field.name for field in fields(StorageAdmissionResult)) == (
        "proposed_record",
        "configured_usable_capacity_bits",
        "stored_equivalent_bits_before",
        "available_capacity_bits_before",
        "stored_equivalent_bits_after_if_admitted",
        "status",
    )
    assert StorageAdmissionResult.__dataclass_params__.frozen
    assert not hasattr(result, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(StorageAdmissionResult)
    )
    with pytest.raises(FrozenInstanceError):
        result.status = StorageAdmissionStatus.INSUFFICIENT_CAPACITY


def test_public_signature_and_exports_are_exact() -> None:
    parameters = signature(evaluate_storage_admission).parameters

    assert tuple(parameters) == (
        "storage_config",
        "stored_records",
        "proposed_record",
    )
    assert all(
        parameter.kind is Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is Parameter.empty
        for parameter in parameters.values()
    )
    assert str(signature(evaluate_storage_admission)) == (
        "(storage_config: 'StorageConfig', stored_records: "
        "'tuple[OnboardAcquisitionDataRecord, ...]', proposed_record: "
        "'OnboardAcquisitionDataRecord') -> 'StorageAdmissionResult'"
    )
    assert storage_module.__all__ == [
        "StorageAdmissionStatus",
        "StorageAdmissionResult",
        "evaluate_storage_admission",
        "validate_storage_records_against_config",
    ]


@pytest.mark.parametrize(
    ("capacity_gb", "expected_bits"),
    (
        (1.0, 8_000_000_000.0),
        (0.125, 1_000_000_000.0),
        (Fraction(1, 8), 1_000_000_000.0),
        (np.float64(0.5), 4_000_000_000.0),
    ),
)
def test_decimal_gigabytes_convert_to_exact_builtin_float_bits(
    capacity_gb,
    expected_bits,
) -> None:
    result = evaluate_storage_admission(
        _config(capacity_gb),
        (),
        _record(bits=1.0),
    )

    assert type(result.configured_usable_capacity_bits) is float
    assert result.configured_usable_capacity_bits == expected_bits


def test_capacity_is_decimal_bits_without_binary_or_byte_output() -> None:
    result = evaluate_storage_admission(_config(1.0), (), _record(bits=1.0))
    field_names = {field.name for field in fields(result)}

    assert result.configured_usable_capacity_bits == 8_000_000_000.0
    assert result.configured_usable_capacity_bits != float(8 * 1024**3)
    assert all("byte" not in name for name in field_names)
    assert not hasattr(result, "configured_usable_capacity_bytes")


def test_fractional_capacity_is_not_quantized() -> None:
    result = evaluate_storage_admission(
        _config(1.875e-10),
        (),
        _record(bits=1.25),
    )

    assert result.configured_usable_capacity_bits == 1.5
    assert result.stored_equivalent_bits_after_if_admitted == 1.25


def test_nonfinite_converted_capacity_is_rejected() -> None:
    with pytest.raises(ValueError, match="capacity.*finite"):
        evaluate_storage_admission(
            _config(sys.float_info.max),
            (),
            _record(bits=1.0),
        )


def test_empty_storage_reports_full_available_capacity_and_admits_fit() -> None:
    candidate = _record(bits=7.5)
    result = evaluate_storage_admission(_config(1.0), (), candidate)

    assert result.proposed_record is candidate
    assert result.stored_equivalent_bits_before == 0.0
    assert result.available_capacity_bits_before == 8_000_000_000.0
    assert result.stored_equivalent_bits_after_if_admitted == 7.5
    assert result.status is StorageAdmissionStatus.ADMISSIBLE


def test_existing_occupancy_uses_deterministic_fsum_of_stored_bits() -> None:
    existing = (
        _record("large", bits=10_000_000_000_000_000.0),
        _record("small-one", bits=1.0),
        _record("small-two", bits=1.0),
    )
    candidate = _record("candidate", bits=4.0)
    result = evaluate_storage_admission(_config(2_000_000.0), existing, candidate)
    expected_before = fsum(item.stored_equivalent_bits for item in existing)

    assert expected_before == 10_000_000_000_000_002.0
    assert result.stored_equivalent_bits_before == expected_before
    assert result.stored_equivalent_bits_after_if_admitted == fsum(
        tuple(item.stored_equivalent_bits for item in existing) + (4.0,)
    )


def test_candidate_total_uses_authoritative_full_sequence_fsum() -> None:
    existing_values = (10_000_000_000_000_000.0, 0.5)
    candidate_value = 0.75
    whole_sequence = fsum(existing_values + (candidate_value,))
    collapsed_existing = fsum((fsum(existing_values), candidate_value))

    assert whole_sequence == 10_000_000_000_000_002.0
    assert collapsed_existing == 10_000_000_000_000_000.0
    assert whole_sequence != collapsed_existing

    result = evaluate_storage_admission(
        _config(2_000_000.0),
        (
            _record("large", bits=existing_values[0]),
            _record("fractional", bits=existing_values[1]),
        ),
        _record("candidate", bits=candidate_value),
    )

    assert result.stored_equivalent_bits_before == fsum(existing_values)
    assert result.stored_equivalent_bits_after_if_admitted == whole_sequence
    assert result.stored_equivalent_bits_after_if_admitted != collapsed_existing


def test_fractional_existing_records_remain_continuous() -> None:
    existing = (
        _record("quarter", bits=0.25),
        _record("half", bits=0.5),
    )
    result = evaluate_storage_admission(
        _config(1.0e-9),
        existing,
        _record("eighth", bits=0.125),
    )

    assert result.stored_equivalent_bits_before == 0.75
    assert result.stored_equivalent_bits_after_if_admitted == 0.875


def test_repeated_request_and_opportunity_lineage_is_allowed() -> None:
    existing = (
        _record(
            "record-a",
            bits=1.0,
            request_id="shared-request",
            opportunity_id="shared-opportunity",
        ),
        _record(
            "record-b",
            bits=1.0,
            request_id="shared-request",
            opportunity_id="shared-opportunity",
        ),
    )
    candidate = _record(
        "record-c",
        bits=1.0,
        request_id="shared-request",
        opportunity_id="shared-opportunity",
    )

    result = evaluate_storage_admission(_config(), existing, candidate)

    assert result.status is StorageAdmissionStatus.ADMISSIBLE
    assert result.stored_equivalent_bits_before == 2.0


def test_exact_full_boundary_is_admissible() -> None:
    result = evaluate_storage_admission(
        _config(1.0e-9),
        (_record("existing", bits=3.0),),
        _record("candidate", bits=5.0),
    )

    assert result.configured_usable_capacity_bits == 8.0
    assert result.stored_equivalent_bits_after_if_admitted == 8.0
    assert result.status is StorageAdmissionStatus.ADMISSIBLE


def test_representable_shortfall_returns_status_and_hypothetical_total() -> None:
    result = evaluate_storage_admission(
        _config(1.0e-9),
        (_record("existing", bits=3.0),),
        _record("candidate", bits=5.000000000000002),
    )

    assert result.configured_usable_capacity_bits == 8.0
    assert result.stored_equivalent_bits_after_if_admitted > 8.0
    assert result.status is StorageAdmissionStatus.INSUFFICIENT_CAPACITY


def test_duplicate_existing_record_ids_are_rejected() -> None:
    existing = (
        _record("duplicate", bits=1.0),
        _record("duplicate", bits=2.0),
    )

    with pytest.raises(ValueError, match="record IDs.*unique"):
        evaluate_storage_admission(
            _config(),
            existing,
            _record("candidate", bits=1.0),
        )


def test_candidate_record_id_matching_existing_is_rejected() -> None:
    with pytest.raises(ValueError, match="record ID.*already"):
        evaluate_storage_admission(
            _config(),
            (_record("duplicate", bits=1.0),),
            _record("duplicate", bits=2.0),
        )


def test_existing_occupancy_above_capacity_is_invalid_input() -> None:
    with pytest.raises(ValueError, match="existing.*exceeds"):
        evaluate_storage_admission(
            _config(1.0e-9),
            (_record("existing", bits=9.0),),
            _record("candidate", bits=1.0),
        )


def test_existing_occupancy_summation_overflow_is_rejected() -> None:
    capacity_gb = sys.float_info.max / 8_000_000_000.0
    existing = (
        _record("first", bits=sys.float_info.max),
        _record("second", bits=sys.float_info.max),
    )

    with pytest.raises(ValueError, match="stored_equivalent_bits_before.*finite"):
        evaluate_storage_admission(
            _config(capacity_gb),
            existing,
            _record("candidate", bits=1.0),
        )


def test_candidate_total_overflow_is_rejected() -> None:
    capacity_gb = sys.float_info.max / 8_000_000_000.0

    with pytest.raises(
        ValueError,
        match="stored_equivalent_bits_after_if_admitted.*finite",
    ):
        evaluate_storage_admission(
            _config(capacity_gb),
            (_record("existing", bits=sys.float_info.max),),
            _record("candidate", bits=sys.float_info.max),
        )


@pytest.mark.parametrize("target", ("existing", "candidate"))
def test_corrupted_record_is_constructor_revalidated(target) -> None:
    existing = _record("existing", bits=1.0)
    candidate = _record("candidate", bits=1.0)
    corrupt = existing if target == "existing" else candidate
    object.__setattr__(corrupt, "stored_equivalent_bits", float("nan"))

    with pytest.raises(ValueError, match="stored_equivalent_bits"):
        evaluate_storage_admission(
            _config(),
            (existing,) if target == "existing" else (),
            candidate,
        )


def test_corrupted_complete_storage_config_is_revalidated() -> None:
    config = _config()
    object.__setattr__(config.usable_capacity_gb.provenance, "units", "GiB")

    with pytest.raises(ValueError, match="units"):
        evaluate_storage_admission(config, (), _record())


def test_positive_candidate_lost_to_float_significance_is_rejected() -> None:
    with pytest.raises(ValueError, match="numerical resolution"):
        evaluate_storage_admission(
            _config(2_000_000.0),
            (_record("existing", bits=10_000_000_000_000_000.0),),
            _record("candidate", bits=1.0),
        )


def test_storage_config_requires_exact_type() -> None:
    class StorageConfigSubclass(StorageConfig):
        pass

    config = StorageConfigSubclass(
        SubsystemConfigurationId("storage-subclass"),
        _parameter(1.0),
    )
    for invalid in (None, object(), config):
        with pytest.raises(TypeError, match="storage_config"):
            evaluate_storage_admission(invalid, (), _record())


def test_stored_records_requires_exact_builtin_tuple() -> None:
    record = _record("existing")
    invalid_values = ([record], {record}, iter((record,)))

    for invalid in invalid_values:
        with pytest.raises(TypeError, match="stored_records.*tuple"):
            evaluate_storage_admission(_config(), invalid, _record("candidate"))


def test_tuple_member_requires_exact_record_type() -> None:
    class RecordSubclass(OnboardAcquisitionDataRecord):
        pass

    original = _record("subclass")
    subclass = RecordSubclass(
        *(getattr(original, field.name) for field in fields(original))
    )
    for invalid in (object(), subclass):
        with pytest.raises(TypeError, match="stored_records"):
            evaluate_storage_admission(
                _config(),
                (invalid,),
                _record("candidate"),
            )


def test_candidate_requires_exact_record_type() -> None:
    class RecordSubclass(OnboardAcquisitionDataRecord):
        pass

    original = _record("subclass")
    subclass = RecordSubclass(
        *(getattr(original, field.name) for field in fields(original))
    )
    for invalid in (None, object(), subclass):
        with pytest.raises(TypeError, match="proposed_record"):
            evaluate_storage_admission(_config(), (), invalid)


@pytest.mark.parametrize(
    "field_name",
    (
        "configured_usable_capacity_bits",
        "stored_equivalent_bits_before",
        "available_capacity_bits_before",
        "stored_equivalent_bits_after_if_admitted",
    ),
)
@pytest.mark.parametrize(
    "invalid",
    (1, True, np.float64(1.0), Decimal("1.0"), Fraction(1, 1)),
)
def test_result_numeric_fields_require_exact_builtin_float(
    field_name,
    invalid,
) -> None:
    with pytest.raises(TypeError, match="built-in float"):
        replace(_direct_result(), **{field_name: invalid})


@pytest.mark.parametrize(
    "field_name",
    (
        "configured_usable_capacity_bits",
        "stored_equivalent_bits_before",
        "available_capacity_bits_before",
        "stored_equivalent_bits_after_if_admitted",
    ),
)
@pytest.mark.parametrize("invalid", (float("nan"), float("inf"), float("-inf")))
def test_result_numeric_fields_require_finite_values(field_name, invalid) -> None:
    with pytest.raises(ValueError, match="finite"):
        replace(_direct_result(), **{field_name: invalid})


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"configured_usable_capacity_bits": 0.0}, "greater than zero"),
        ({"stored_equivalent_bits_before": -1.0}, "greater than or equal"),
        ({"available_capacity_bits_before": -1.0}, "greater than or equal"),
        ({"stored_equivalent_bits_after_if_admitted": 0.0}, "greater than zero"),
        (
            {
                "configured_usable_capacity_bits": 2.0,
                "stored_equivalent_bits_before": 3.0,
            },
            "must not exceed",
        ),
    ),
)
def test_result_numeric_ranges_are_enforced(changes, message) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_direct_result(), **changes)


def test_result_requires_exact_available_and_candidate_lower_bound() -> None:
    with pytest.raises(ValueError, match="available_capacity_bits_before"):
        replace(_direct_result(), available_capacity_bits_before=4.0)
    with pytest.raises(ValueError, match="proposed record volume"):
        StorageAdmissionResult(
            _record(bits=4.0),
            8.0,
            1.0,
            7.0,
            3.0,
            StorageAdmissionStatus.ADMISSIBLE,
        )


def test_result_requires_exact_status_type_and_classification() -> None:
    with pytest.raises(TypeError, match="StorageAdmissionStatus"):
        replace(_direct_result(), status="admissible")
    with pytest.raises(ValueError, match="inconsistent"):
        replace(
            _direct_result(),
            status=StorageAdmissionStatus.INSUFFICIENT_CAPACITY,
        )


def test_result_revalidates_proposed_record_and_retains_identity() -> None:
    record = _record(bits=2.0)
    result = StorageAdmissionResult(
        record,
        8.0,
        0.0,
        8.0,
        2.0,
        StorageAdmissionStatus.ADMISSIBLE,
    )

    assert result.proposed_record is record
    object.__setattr__(record, "record_id", "corrupt")
    with pytest.raises(TypeError, match="record_id"):
        StorageAdmissionResult(
            record,
            8.0,
            0.0,
            8.0,
            2.0,
            StorageAdmissionStatus.ADMISSIBLE,
        )


def test_evaluation_is_pure_deterministic_and_retains_all_inputs() -> None:
    config = _config(1.0e-9)
    existing = (
        _record("existing-a", bits=1.25),
        _record("existing-b", bits=2.5),
    )
    candidate = _record("candidate", bits=3.0)
    before = deepcopy((config, existing, candidate))
    identities = tuple(map(id, (config, *existing, candidate)))

    first = evaluate_storage_admission(config, existing, candidate)
    second = evaluate_storage_admission(config, existing, candidate)

    assert (config, existing, candidate) == before
    assert tuple(map(id, (config, *existing, candidate))) == identities
    assert first == second
    assert first is not second
    assert first.proposed_record is candidate
    assert existing == (
        _record("existing-a", bits=1.25),
        _record("existing-b", bits=2.5),
    )


def test_storage_arithmetic_uses_fsum_stored_bits_and_no_quantization() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    evaluation = _function(tree, "evaluate_storage_admission")
    finite_sum = _function(tree, "_finite_fsum")
    evaluation_calls = {
        node.func.id
        for node in ast.walk(evaluation)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    finite_sum_calls = {
        node.func.id
        for node in ast.walk(finite_sum)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attributes = {
        node.attr
        for node in ast.walk(evaluation)
        if isinstance(node, ast.Attribute)
    }

    assert "_finite_fsum" in evaluation_calls
    assert "fsum" in finite_sum_calls
    assert "sum" not in evaluation_calls | finite_sum_calls
    assert "stored_equivalent_bits" in attributes
    assert "uncompressed_equivalent_bits" not in attributes
    assert evaluation_calls.isdisjoint({"int", "round", "ceil", "floor"})


def test_capacity_conversion_uses_only_decimal_gigabyte_constant() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}
    }

    assert 8_000_000_000.0 in constants
    assert 1024 not in constants
    assert 1024.0 not in constants


def test_production_dependencies_and_deferred_boundaries_are_narrow() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
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

    assert imported_modules == {
        "__future__",
        "configuration",
        "dataclasses",
        "enum",
        "math",
        "onboard_data",
    }
    assert "numpy" not in imported_modules
    assert identifiers.isdisjoint(
        {
            "datastoragestate",
            "append",
            "remove",
            "delete",
            "checkpointstate",
            "simulationengine",
            "missionstate",
            "controllerstate",
            "knowledge",
            "communications",
            "downlink",
            "transmission",
            "delivery",
            "compression_ratio",
            "compression_factor",
            "codec",
            "packet",
            "container",
            "overwrite",
            "eviction",
            "priority",
            "garbage_collection",
            "reserved_capacity",
            "record_count_limit",
            "storage_power",
            "obc_power",
            "thermal",
            "throughput",
            "write_rate",
            "latency",
            "queue",
            "quantize",
            "isclose",
            "epsilon",
            "tolerance",
        }
    )


def test_result_has_no_state_mutation_or_deferred_fields() -> None:
    field_names = {field.name for field in fields(StorageAdmissionResult)}

    assert field_names.isdisjoint(
        {
            "storage_state",
            "stored_records_after",
            "evicted_records",
            "partial_record_bits",
            "checkpoint_schema_version",
            "mission_request_id",
            "product_id",
            "compressed_bits",
            "write_power_w",
            "write_duration_seconds",
        }
    )


def test_d290_and_s010_b1_semantics_preserve_s009() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = read_blob(ROOT, B1_COMMIT, "V5_SOURCE_REGISTER.md")
    heading = (
        "## D290 — V5.4B1 uses decimal-GB whole-record storage admission "
        "in equivalent bits"
    )

    assert decisions.count(heading) == 1
    assert decisions.index("## D289 ") < decisions.index(heading)
    b1_decisions = subprocess.run(
        ["git", "show", f"{B1_COMMIT}:V5_DECISION_LOG.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert "## D291 " not in b1_decisions
    normalized_decision = _normalized(decisions.partition(heading)[2])
    for phrase in (
        "storageconfig.usable_capacity_gb",
        "decimal gb",
        "8,000,000,000 bits",
        "math.fsum",
        "complete ordered sequence",
        "not reconstructed from the rounded stored-before subtotal",
        "less than or equal to capacity",
        "exact-full boundary is admitted",
        "duplicate record ids reject",
        "no overwrite, eviction, partial storage",
        "not yet an engine nonauthorization outcome",
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
    assert sources.count("### S009 ") == 1
    assert sources.count("### S010 ") == 1
    assert "### S011 " not in sources

    s010 = sources.partition("### S010 ")[2].partition(
        "## Rule for Explicit Assumptions"
    )[0]
    normalized_s010 = _normalized(s010)
    for phrase in (
        "v5.4a1 continuous equivalent-bit proposal",
        "v5.4a2 explicit acquisition-data record identity",
        "v5.4b1 decimal-gb whole-record storage admission",
        "no new spacecraft numerical storage value",
        "existing `gb` configuration unit as decimal gb",
        "8,000,000,000 bits",
        "deterministic occupancy summation",
        "whole-record admission",
        "model- architecture decisions",
        "not real file, packet, container, or filesystem semantics",
        "no compression model",
        "overwrite or eviction policy",
        "recorder throughput",
        "storage/obc power",
        "kazeosat storage capacity remains to research",
    ):
        assert phrase in normalized_s010


def test_b1_historical_scope_is_exactly_seven_files_and_one_production_module() -> None:
    tracked_changes = set(
        subprocess.run(
            ["git", "diff", "--name-only", A2_BASELINE, B1_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    changes = tracked_changes
    production_changes = {
        path for path in changes if path.startswith("ops_sim/v5/")
    }

    assert production_changes == {"ops_sim/v5/storage.py"}
    assert changes == {
        "V5_DECISION_LOG.md",
        "V5_SOURCE_REGISTER.md",
        "ops_sim/v5/storage.py",
        "tests/test_v53f4a_integrated_imaging_demo.py",
        "tests/test_v54a1_onboard_data_volume.py",
        "tests/test_v54a2_acquisition_data_record.py",
        "tests/test_v54b1_storage_admission.py",
    }
