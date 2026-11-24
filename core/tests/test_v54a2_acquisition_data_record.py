"""Explicit acquisition-data record identity and contract for V5.4A2."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from inspect import signature
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from frozen_release_history import read_blob

import ops_sim.v5.ids as ids_module
import ops_sim.v5.onboard_data as onboard_data_module
from ops_sim.v5.ids import (
    AcquisitionDataRecordId,
    DataProductId,
    ImagingRequestId,
    MissionRequestId,
    ObservationOpportunityId,
    ParameterId,
)
from ops_sim.v5.onboard_data import (
    OnboardAcquisitionDataRecord,
    OnboardAcquisitionDataVolumeProposal,
    compute_onboard_acquisition_data_volume_proposal,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
    compute_optical_acquisition,
)
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)


ROOT = Path(__file__).resolve().parents[1]
IDS_PATH = ROOT / "ops_sim" / "v5" / "ids.py"
MODULE_PATH = ROOT / "ops_sim" / "v5" / "onboard_data.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
A1_BASELINE = "7f1d7643e60b358f09f5d36b154a1f9e5bc38dc9"
A2_COMMIT = "fcd084ee1ed7af3be81955e58111a8a65de2a3a0"


def _record(**changes: object) -> OnboardAcquisitionDataRecord:
    values = {
        "record_id": AcquisitionDataRecordId("record-one"),
        "imaging_request_id": ImagingRequestId("request-one"),
        "observation_opportunity_id": ObservationOpportunityId(
            "opportunity-one"
        ),
        "scheduled_start_seconds": 0,
        "acquisition_duration_seconds": 1,
        "channel_selection": (
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL
        ),
        "uncompressed_equivalent_bits": 7.5,
        "stored_equivalent_bits": 7.5,
    }
    values.update(changes)
    return OnboardAcquisitionDataRecord(**values)


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by the V5.4A2 tests.",
        ),
    )


def _fractional_acquisition_result():
    config = OpticalAcquisitionConfig(
        _parameter("payload.optical.reference-nadir-swath-width", "m", 20.0),
        _parameter(
            "payload.optical.panchromatic-reference-sample-spacing",
            "m",
            1.0,
        ),
        _parameter(
            "payload.optical.multispectral-reference-sample-spacing",
            "m",
            4.0,
        ),
        _parameter("payload.optical.multispectral-band-count", "1", 4),
        _parameter(
            "payload.optical.acquisition-bits-per-sample",
            "bit/sample",
            1,
        ),
        _parameter("payload.optical.acquisition-power", "W", 90.0),
        False,
    )
    return compute_optical_acquisition(
        config,
        OpticalAcquisitionInput(
            3.0,
            2.5,
            60,
            OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY,
        ),
    )


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _normalized(value: str) -> str:
    return " ".join(value.lower().split())


def test_acquisition_data_record_id_has_exact_stable_identity_behavior() -> None:
    identifier = AcquisitionDataRecordId("record-one")

    assert identifier.prefix == "acquisition-data-record"
    assert identifier.value == "record-one"
    assert identifier.canonical == "acquisition-data-record:record-one"
    assert str(identifier) == identifier.canonical
    assert AcquisitionDataRecordId.from_canonical(identifier.canonical) == (
        identifier
    )
    assert type(
        AcquisitionDataRecordId.from_canonical(identifier.canonical)
    ) is AcquisitionDataRecordId
    assert not hasattr(identifier, "__dict__")
    with pytest.raises(FrozenInstanceError):
        identifier.value = "replacement"


@pytest.mark.parametrize(
    "invalid",
    (
        "",
        " leading",
        "trailing ",
        "UPPERCASE",
        "contains:colon",
        "contains/slash",
        "two..segments",
        "-leading",
        "trailing-",
    ),
)
def test_acquisition_data_record_id_rejects_malformed_values(invalid) -> None:
    with pytest.raises(ValueError):
        AcquisitionDataRecordId(invalid)


@pytest.mark.parametrize(
    "invalid",
    (None, True, 1, 1.0, Decimal("1"), Fraction(1, 1), object()),
)
def test_acquisition_data_record_id_rejects_non_strings_without_conversion(
    invalid,
) -> None:
    with pytest.raises(TypeError, match="string"):
        AcquisitionDataRecordId(invalid)


def test_record_id_is_distinct_from_all_lineage_and_product_ids() -> None:
    record_id = AcquisitionDataRecordId("shared")

    assert record_id != ImagingRequestId("shared")
    assert record_id != ObservationOpportunityId("shared")
    assert record_id != MissionRequestId("shared")
    assert record_id != DataProductId("shared")
    assert len(
        {
            record_id.canonical,
            ImagingRequestId("shared").canonical,
            ObservationOpportunityId("shared").canonical,
            MissionRequestId("shared").canonical,
            DataProductId("shared").canonical,
        }
    ) == 5


def test_record_id_has_no_model_generation_helpers() -> None:
    tree = ast.parse(IDS_PATH.read_text(encoding="utf-8"))
    record_id_class = _class(tree, "AcquisitionDataRecordId")
    imports = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in record_id_class.body
    )
    assert imports.isdisjoint(
        {"uuid", "random", "time", "datetime", "hashlib", "secrets"}
    )
    assert "AcquisitionDataRecordId" in ids_module.__all__


def test_record_has_exact_frozen_slotted_required_contract() -> None:
    record = _record()
    expected_fields = (
        "record_id",
        "imaging_request_id",
        "observation_opportunity_id",
        "scheduled_start_seconds",
        "acquisition_duration_seconds",
        "channel_selection",
        "uncompressed_equivalent_bits",
        "stored_equivalent_bits",
    )

    assert tuple(field.name for field in fields(OnboardAcquisitionDataRecord)) == (
        expected_fields
    )
    assert OnboardAcquisitionDataRecord.__dataclass_params__.frozen
    assert not hasattr(record, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(OnboardAcquisitionDataRecord)
    )
    assert str(signature(OnboardAcquisitionDataRecord)) == (
        "(record_id: 'AcquisitionDataRecordId', imaging_request_id: "
        "'ImagingRequestId', observation_opportunity_id: "
        "'ObservationOpportunityId', scheduled_start_seconds: 'int', "
        "acquisition_duration_seconds: 'int', channel_selection: "
        "'OpticalAcquisitionChannelSelection', uncompressed_equivalent_bits: "
        "'float', stored_equivalent_bits: 'float') -> None"
    )
    with pytest.raises(FrozenInstanceError):
        record.stored_equivalent_bits = 8.0


def test_record_retains_original_id_objects_and_lineage_may_repeat() -> None:
    record_id = AcquisitionDataRecordId("record-one")
    request_id = ImagingRequestId("request-one")
    opportunity_id = ObservationOpportunityId("opportunity-one")
    first = _record(
        record_id=record_id,
        imaging_request_id=request_id,
        observation_opportunity_id=opportunity_id,
    )
    second = _record(
        record_id=AcquisitionDataRecordId("record-two"),
        imaging_request_id=request_id,
        observation_opportunity_id=opportunity_id,
    )

    assert first.record_id is record_id
    assert first.imaging_request_id is request_id
    assert first.observation_opportunity_id is opportunity_id
    assert second.imaging_request_id is request_id
    assert second.observation_opportunity_id is opportunity_id
    assert first.record_id != second.record_id


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    (
        ("record_id", ImagingRequestId("wrong")),
        ("imaging_request_id", AcquisitionDataRecordId("wrong")),
        (
            "observation_opportunity_id",
            ImagingRequestId("wrong"),
        ),
    ),
)
def test_record_requires_exact_id_types(field_name, invalid) -> None:
    with pytest.raises(TypeError, match=field_name):
        _record(**{field_name: invalid})


@pytest.mark.parametrize(
    ("field_name", "identifier"),
    (
        ("record_id", AcquisitionDataRecordId("record")),
        ("imaging_request_id", ImagingRequestId("request")),
        (
            "observation_opportunity_id",
            ObservationOpportunityId("opportunity"),
        ),
    ),
)
def test_record_revalidates_corrupted_nested_ids(field_name, identifier) -> None:
    object.__setattr__(identifier, "value", "CORRUPTED")

    with pytest.raises(ValueError, match="StableId value"):
        _record(**{field_name: identifier})


def test_record_rejects_id_subclasses() -> None:
    class RecordIdSubclass(AcquisitionDataRecordId):
        pass

    with pytest.raises(TypeError, match="record_id"):
        _record(record_id=RecordIdSubclass("record"))


@pytest.mark.parametrize(
    "changes",
    (
        {"scheduled_start_seconds": 0},
        {"acquisition_duration_seconds": 1},
        {"scheduled_start_seconds": 10**1000},
        {"acquisition_duration_seconds": 10**1000},
    ),
)
def test_record_accepts_timestamp_boundaries_and_large_builtin_ints(
    changes,
) -> None:
    record = _record(**changes)

    for field_name, value in changes.items():
        assert getattr(record, field_name) == value
        assert type(getattr(record, field_name)) is int


@pytest.mark.parametrize(
    "field_name",
    ("scheduled_start_seconds", "acquisition_duration_seconds"),
)
@pytest.mark.parametrize(
    "invalid",
    (True, 1.0, np.int64(1), Decimal("1"), Fraction(1, 1), "1"),
)
def test_record_timestamps_require_exact_builtin_ints(
    field_name,
    invalid,
) -> None:
    with pytest.raises(TypeError, match=field_name):
        _record(**{field_name: invalid})


def test_record_rejects_negative_start_and_nonpositive_duration() -> None:
    with pytest.raises(ValueError, match="scheduled_start_seconds"):
        _record(scheduled_start_seconds=-1)
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="acquisition_duration_seconds"):
            _record(acquisition_duration_seconds=invalid)


class _ForeignChannel(Enum):
    PANCHROMATIC_ONLY = "panchromatic-only"


@pytest.mark.parametrize(
    "invalid",
    (
        "pan-and-multispectral",
        _ForeignChannel.PANCHROMATIC_ONLY,
        1,
        True,
    ),
)
def test_record_requires_exact_channel_enum(invalid) -> None:
    with pytest.raises(TypeError, match="channel_selection"):
        _record(channel_selection=invalid)


@pytest.mark.parametrize(
    "field_name",
    ("uncompressed_equivalent_bits", "stored_equivalent_bits"),
)
@pytest.mark.parametrize(
    "invalid",
    (1, True, np.float64(1.0), Decimal("1.0"), Fraction(1, 1)),
)
def test_record_bit_quantities_require_exact_builtin_floats(
    field_name,
    invalid,
) -> None:
    with pytest.raises(TypeError, match="built-in float"):
        _record(**{field_name: invalid})


@pytest.mark.parametrize(
    "field_name",
    ("uncompressed_equivalent_bits", "stored_equivalent_bits"),
)
@pytest.mark.parametrize(
    "invalid",
    (float("nan"), float("inf"), float("-inf"), 0.0, -0.0, -1.0),
)
def test_record_bit_quantities_require_finite_positive_values(
    field_name,
    invalid,
) -> None:
    message = "finite" if not (-float("inf") < invalid < float("inf")) else "greater"
    with pytest.raises(ValueError, match=message):
        _record(**{field_name: invalid})


@pytest.mark.parametrize(
    "value",
    (
        7.5,
        sys.float_info.min,
        float.fromhex("0x0.0000000000001p-1022"),
    ),
)
def test_record_preserves_positive_fractional_normal_and_subnormal_bits(
    value,
) -> None:
    record = _record(
        uncompressed_equivalent_bits=value,
        stored_equivalent_bits=value,
    )

    assert record.uncompressed_equivalent_bits == value
    assert record.stored_equivalent_bits == value
    assert type(record.uncompressed_equivalent_bits) is float


def test_record_requires_exact_no_reduction_equality() -> None:
    with pytest.raises(ValueError, match="must equal.*exactly"):
        _record(stored_equivalent_bits=7.500000000000001)


def test_record_contains_no_transient_graph_or_deferred_fields() -> None:
    field_names = {field.name for field in fields(OnboardAcquisitionDataRecord)}

    assert field_names.isdisjoint(
        {
            "acquisition_result",
            "volume_proposal",
            "uncompressed_equivalent_bytes",
            "stored_equivalent_bytes",
            "stored",
            "committed",
            "admissible",
            "delivered",
            "downlinked",
            "completed",
            "product_id",
            "mission_request_id",
            "file_path",
            "packet_id",
            "compression_algorithm",
            "storage_location",
            "storage_partition",
            "checksum",
            "deletion_status",
            "storage_state",
        }
    )
    assert not any(
        field.type
        in {
            "OpticalAcquisitionResult",
            "OnboardAcquisitionDataVolumeProposal",
        }
        for field in fields(OnboardAcquisitionDataRecord)
    )


def test_a1_function_signature_export_and_exact_fractional_copy_remain() -> None:
    acquisition = _fractional_acquisition_result()
    proposal = compute_onboard_acquisition_data_volume_proposal(acquisition)

    assert str(signature(compute_onboard_acquisition_data_volume_proposal)) == (
        "(acquisition_result: 'OpticalAcquisitionResult') -> "
        "'OnboardAcquisitionDataVolumeProposal'"
    )
    assert onboard_data_module.__all__ == [
        "OnboardAcquisitionDataVolumeProposal",
        "OnboardAcquisitionDataRecord",
        "compute_onboard_acquisition_data_volume_proposal",
    ]
    assert type(proposal) is OnboardAcquisitionDataVolumeProposal
    assert proposal.acquisition_result is acquisition
    assert acquisition.uncompressed_equivalent_bits == 7.5
    assert proposal.uncompressed_equivalent_bits == 7.5
    assert proposal.stored_equivalent_bits == 7.5


def test_a1_function_still_only_copies_bits_without_recomputation() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    function = _function(
        tree,
        "compute_onboard_acquisition_data_volume_proposal",
    )
    calls = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert calls == {
        "_revalidate_acquisition_result",
        "OnboardAcquisitionDataVolumeProposal",
        "TypeError",
        "type",
    }
    assert not any(
        isinstance(node, ast.BinOp)
        and isinstance(node.op, (ast.Mult, ast.Div))
        for node in ast.walk(function)
    )
    assert {
        node.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
    } == {"uncompressed_equivalent_bits"}


def test_production_structure_has_only_the_narrow_a1_a2_dependencies() -> None:
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
            (node.id,) if isinstance(node, ast.Name) else
            (node.attr,) if isinstance(node, ast.Attribute) else
            (node.name,) if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
            ()
        )
    }

    assert imported_modules == {
        "__future__",
        "dataclasses",
        "ids",
        "math",
        "payload",
    }
    assert identifiers.isdisjoint(
        {
            "uuid",
            "random",
            "hashlib",
            "digest",
            "datastoragestate",
            "storage_capacity",
            "storage_admission",
            "append",
            "remove",
            "overwrite",
            "eviction",
            "checkpointstate",
            "simulationengine",
            "missionstate",
            "controllerstate",
            "dataproductid",
            "missionrequestid",
            "communications",
            "downlink",
            "transmission",
            "delivery",
            "compression_ratio",
            "codec",
            "packet",
            "container",
            "header",
            "throughput",
            "latency",
            "storage_power",
            "obc_power",
            "quantize",
            "round",
            "isclose",
        }
    )
    assert tuple(
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    ) == (
        "_revalidate_acquisition_result",
        "_validate_positive_builtin_float",
        "compute_onboard_acquisition_data_volume_proposal",
    )


def test_record_validation_does_not_generate_identity_or_quantize() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    record_class = _class(tree, "OnboardAcquisitionDataRecord")
    post_init = _function(record_class, "__post_init__")
    called_names = {
        node.func.id
        for node in ast.walk(post_init)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert called_names.isdisjoint(
        {
            "uuid4",
            "random",
            "hash",
            "digest",
            "int",
            "float",
            "round",
            "ceil",
            "floor",
            "isclose",
        }
    )
    assert not any(
        isinstance(node, (ast.JoinedStr, ast.BinOp))
        for node in ast.walk(post_init)
    )


def test_d289_and_s010_a2_semantics_preserve_s009_and_a1() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = read_blob(ROOT, A2_COMMIT, "V5_SOURCE_REGISTER.md")
    heading = (
        "## D289 — V5.4A2 gives each onboard acquisition-data record an "
        "explicit caller-supplied identity"
    )

    assert decisions.count("## D288 ") == 1
    assert decisions.count(heading) == 1
    assert decisions.index("## D288 ") < decisions.index(heading)
    a2_decisions = subprocess.run(
        ["git", "show", f"{A2_COMMIT}:V5_DECISION_LOG.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert "## D290 " not in a2_decisions

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
    assert sources.count("### S010 — Onboard data, storage, and OBC evidence") == 1
    assert "### S011 " not in sources

    s010 = sources.partition("### S010 ")[2].partition(
        "## Rule for Explicit Assumptions"
    )[0]
    normalized = _normalized(s010)
    for phrase in (
        "v5.4a1 continuous equivalent-bit proposal",
        "derived level-1 sample-grid proxy",
        "identity/no-reduction proposal",
        "v5.4a2 explicit acquisition-data record identity",
        "no new physical source or spacecraft numerical value",
        "model-architecture decision",
        "supplied by the caller",
        "not a `dataproductid`",
        "immutable eight-field record",
        "level-1 request and opportunity lineage",
        "file, container, or packet format",
        "downlink",
        "mission/product completion",
        "capacity, compression, recorder throughput",
        "storage/obc power",
        "recorder hardware remain to research",
    ):
        assert phrase in normalized


def test_a2_historical_commit_changes_exactly_two_v5_modules_and_eleven_repository_files() -> None:
    production_changes = set(
        subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                A1_BASELINE,
                A2_COMMIT,
                "--",
                "ops_sim/v5",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    repository_changes = set(
        subprocess.run(
            ["git", "diff", "--name-only", A1_BASELINE, A2_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )

    assert production_changes == {
        "ops_sim/v5/ids.py",
        "ops_sim/v5/onboard_data.py",
    }
    assert repository_changes == {
        "V5_DECISION_LOG.md",
        "V5_SOURCE_REGISTER.md",
        "ops_sim/v5/ids.py",
        "ops_sim/v5/onboard_data.py",
        "tests/test_v53c3_observation_transition_feasibility.py",
        "tests/test_v53d_observation_acquisition_composition.py",
        "tests/test_v53f1_imaging_execution_contracts.py",
        "tests/test_v53f2_imaging_authorization.py",
        "tests/test_v53f4a_integrated_imaging_demo.py",
        "tests/test_v54a1_onboard_data_volume.py",
        "tests/test_v54a2_acquisition_data_record.py",
    }
