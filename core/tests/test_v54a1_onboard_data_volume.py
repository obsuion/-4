"""Level-1 onboard acquisition-data volume semantics for V5.4A1."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from decimal import Decimal
from fractions import Fraction
from inspect import Parameter, signature
from pathlib import Path
import subprocess

import numpy as np
import pytest

import ops_sim.v5.onboard_data as onboard_data_module
from ops_sim.v5.ids import ParameterId
from ops_sim.v5.onboard_data import (
    OnboardAcquisitionDataVolumeProposal,
    compute_onboard_acquisition_data_volume_proposal,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionInput,
    OpticalAcquisitionResult,
    compute_optical_acquisition,
)
from ops_sim.v5.payload_config import OpticalAcquisitionConfig
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops_sim" / "v5" / "onboard_data.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
A1_COMMIT = "7f1d7643e60b358f09f5d36b154a1f9e5bc38dc9"


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by the V5.4A1 tests.",
        ),
    )


def _optical_config(
    *,
    bits_per_sample: object = 12,
    simultaneous: bool = True,
) -> OpticalAcquisitionConfig:
    return OpticalAcquisitionConfig(
        _parameter("payload.optical.reference-nadir-swath-width", "m", 20_000.0),
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
            bits_per_sample,
        ),
        _parameter("payload.optical.acquisition-power", "W", 90.0),
        simultaneous,
    )


def _acquisition_result() -> OpticalAcquisitionResult:
    return compute_optical_acquisition(
        _optical_config(),
        OpticalAcquisitionInput(
            20.0,
            40.0,
            60,
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        ),
    )


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _called_names(node: ast.AST) -> tuple[str, ...]:
    names = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            names.append(item.func.id)
        elif isinstance(item.func, ast.Attribute):
            names.append(item.func.attr)
    return tuple(names)


def test_result_contract_is_exact_frozen_slotted_and_required() -> None:
    acquisition = _acquisition_result()
    proposal = compute_onboard_acquisition_data_volume_proposal(acquisition)

    assert tuple(field.name for field in fields(type(proposal))) == (
        "acquisition_result",
        "uncompressed_equivalent_bits",
        "stored_equivalent_bits",
    )
    assert OnboardAcquisitionDataVolumeProposal.__dataclass_params__.frozen
    assert not hasattr(proposal, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(OnboardAcquisitionDataVolumeProposal)
    )
    with pytest.raises(FrozenInstanceError):
        proposal.stored_equivalent_bits = 1.0


def test_public_signature_and_exports_are_exact() -> None:
    parameters = signature(
        compute_onboard_acquisition_data_volume_proposal
    ).parameters

    assert tuple(parameters) == ("acquisition_result",)
    parameter = parameters["acquisition_result"]
    assert parameter.kind is Parameter.POSITIONAL_OR_KEYWORD
    assert parameter.default is Parameter.empty
    assert str(
        signature(compute_onboard_acquisition_data_volume_proposal)
    ) == (
        "(acquisition_result: 'OpticalAcquisitionResult') -> "
        "'OnboardAcquisitionDataVolumeProposal'"
    )
    assert onboard_data_module.__all__ == [
        "OnboardAcquisitionDataVolumeProposal",
        "OnboardAcquisitionDataRecord",
        "compute_onboard_acquisition_data_volume_proposal",
    ]


@pytest.mark.parametrize("invalid", (None, True, object()))
def test_public_function_rejects_nonexact_input_types(invalid) -> None:
    with pytest.raises(TypeError, match="acquisition_result"):
        compute_onboard_acquisition_data_volume_proposal(invalid)


def test_public_function_rejects_acquisition_result_subclass() -> None:
    acquisition = _acquisition_result()

    class AcquisitionResultSubclass(OpticalAcquisitionResult):
        pass

    subclass = AcquisitionResultSubclass(
        *(getattr(acquisition, field.name) for field in fields(acquisition))
    )
    with pytest.raises(TypeError, match="acquisition_result"):
        compute_onboard_acquisition_data_volume_proposal(subclass)


def test_exact_b2_bits_are_copied_and_original_identity_is_retained() -> None:
    acquisition = _acquisition_result()
    proposal = compute_onboard_acquisition_data_volume_proposal(acquisition)

    assert proposal.acquisition_result is acquisition
    assert type(proposal.uncompressed_equivalent_bits) is float
    assert proposal.uncompressed_equivalent_bits == (
        acquisition.uncompressed_equivalent_bits
    )
    assert proposal.stored_equivalent_bits == (
        proposal.uncompressed_equivalent_bits
    )


def test_result_contains_no_deferred_fields() -> None:
    field_names = {field.name for field in fields(OnboardAcquisitionDataVolumeProposal)}
    assert field_names.isdisjoint(
        {
            "uncompressed_equivalent_bytes",
            "stored_equivalent_bytes",
            "compression_factor",
            "compression_profile",
            "algorithm",
            "header_bits",
            "overhead_bits",
            "record_id",
            "stored_status",
            "storage_capacity",
            "admissible",
            "request_id",
            "opportunity_id",
            "product_id",
            "mission_id",
            "storage_state",
        }
    )


def test_binary_exact_fractional_bit_quantity_survives_unchanged() -> None:
    acquisition = compute_optical_acquisition(
        _optical_config(bits_per_sample=1, simultaneous=False),
        OpticalAcquisitionInput(
            3.0,
            2.5,
            60,
            OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY,
        ),
    )
    proposal = compute_onboard_acquisition_data_volume_proposal(acquisition)

    assert acquisition.uncompressed_equivalent_bits == 7.5
    assert acquisition.uncompressed_equivalent_bytes == 0.9375
    assert proposal.uncompressed_equivalent_bits == 7.5
    assert proposal.stored_equivalent_bits == 7.5
    assert not hasattr(proposal, "uncompressed_equivalent_bytes")
    assert not hasattr(proposal, "stored_equivalent_bytes")


def test_twenty_kilometre_reference_bits_are_preserved_exactly() -> None:
    acquisition = compute_optical_acquisition(
        _optical_config(),
        OpticalAcquisitionInput(
            20_000.0,
            20_000.0,
            60,
            OpticalAcquisitionChannelSelection.PAN_AND_MULTISPECTRAL,
        ),
    )
    proposal = compute_onboard_acquisition_data_volume_proposal(acquisition)

    assert acquisition.total_equivalent_samples == 500_000_000.0
    assert acquisition.uncompressed_equivalent_bits == 6_000_000_000.0
    assert acquisition.uncompressed_equivalent_bytes == 750_000_000.0
    assert proposal.uncompressed_equivalent_bits == 6_000_000_000.0
    assert proposal.stored_equivalent_bits == 6_000_000_000.0


@pytest.mark.parametrize("invalid", (float("nan"), 0.0, -1.0))
def test_corrupted_nested_bit_quantity_is_rejected(invalid) -> None:
    acquisition = _acquisition_result()
    object.__setattr__(acquisition, "uncompressed_equivalent_bits", invalid)

    with pytest.raises(ValueError, match="uncompressed_equivalent_bits"):
        compute_onboard_acquisition_data_volume_proposal(acquisition)


def test_inconsistent_corrupted_nested_result_is_rejected() -> None:
    acquisition = _acquisition_result()
    object.__setattr__(
        acquisition,
        "total_equivalent_samples",
        acquisition.total_equivalent_samples + 1.0,
    )

    with pytest.raises(ValueError, match="total_equivalent_samples"):
        compute_onboard_acquisition_data_volume_proposal(acquisition)


def test_direct_proposal_revalidates_the_complete_nested_result() -> None:
    acquisition = _acquisition_result()
    object.__setattr__(
        acquisition,
        "uncompressed_equivalent_bytes",
        acquisition.uncompressed_equivalent_bytes + 1.0,
    )

    with pytest.raises(ValueError, match="divided by eight"):
        OnboardAcquisitionDataVolumeProposal(
            acquisition,
            acquisition.uncompressed_equivalent_bits,
            acquisition.uncompressed_equivalent_bits,
        )


@pytest.mark.parametrize(
    "field_name",
    ("uncompressed_equivalent_bits", "stored_equivalent_bits"),
)
@pytest.mark.parametrize(
    "invalid",
    (1, True, np.float64(1.0), Decimal("1.0"), Fraction(1, 1)),
)
def test_direct_proposal_fields_require_exact_builtin_float(
    field_name,
    invalid,
) -> None:
    acquisition = _acquisition_result()
    proposal = compute_onboard_acquisition_data_volume_proposal(acquisition)

    with pytest.raises(TypeError, match="built-in float"):
        replace(proposal, **{field_name: invalid})


@pytest.mark.parametrize(
    "field_name",
    ("uncompressed_equivalent_bits", "stored_equivalent_bits"),
)
@pytest.mark.parametrize(
    "invalid",
    (float("nan"), float("inf"), float("-inf"), 0.0, -1.0),
)
def test_direct_proposal_fields_require_finite_positive_values(
    field_name,
    invalid,
) -> None:
    acquisition = _acquisition_result()
    proposal = compute_onboard_acquisition_data_volume_proposal(acquisition)
    expected = "finite" if invalid != invalid or abs(invalid) == float("inf") else "greater"

    with pytest.raises(ValueError, match=expected):
        replace(proposal, **{field_name: invalid})


def test_direct_proposal_requires_both_exact_identity_equalities() -> None:
    acquisition = _acquisition_result()
    bits = acquisition.uncompressed_equivalent_bits

    with pytest.raises(ValueError, match="acquisition result value exactly"):
        OnboardAcquisitionDataVolumeProposal(acquisition, bits + 1.0, bits + 1.0)
    with pytest.raises(ValueError, match="must equal.*exactly"):
        OnboardAcquisitionDataVolumeProposal(acquisition, bits, bits + 1.0)


def test_function_is_pure_and_repeated_results_are_deterministic() -> None:
    acquisition = _acquisition_result()
    before = deepcopy(acquisition)

    first = compute_onboard_acquisition_data_volume_proposal(acquisition)
    second = compute_onboard_acquisition_data_volume_proposal(acquisition)

    assert acquisition == before
    assert first == second
    assert first is not second
    assert first.acquisition_result is acquisition
    assert second.acquisition_result is acquisition


def test_public_function_only_copies_bits_without_quantization_or_b2_math() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    function = _function(
        tree,
        "compute_onboard_acquisition_data_volume_proposal",
    )
    calls = _called_names(function)
    attributes = tuple(
        node.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
    )

    assert calls.count("_revalidate_acquisition_result") == 1
    assert calls.count("OnboardAcquisitionDataVolumeProposal") == 1
    assert set(calls).isdisjoint(
        {
            "compute_optical_acquisition",
            "int",
            "round",
            "ceil",
            "floor",
            "fsum",
        }
    )
    assert attributes == ("uncompressed_equivalent_bits",)
    assert not any(
        isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div))
        for node in ast.walk(function)
    )


def test_production_dependencies_and_executable_structure_are_narrow() -> None:
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
    assert "numpy" not in imported_modules
    assert identifiers.isdisjoint(
        {
            "compression_ratio",
            "compression_factor",
            "codec",
            "packet",
            "file",
            "container",
            "header",
            "metadata_overhead",
            "storage_capacity",
            "storage_admission",
            "storage_state",
            "dataproductid",
            "missionrequestid",
            "checkpointstate",
            "simulationengine",
            "communications",
            "downlink",
            "delivery",
            "quantize",
        }
    )


def test_d288_and_s010_semantics_are_recorded_without_changing_s009() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    heading = (
        "## D288 — V5.4A1 preserves V5.3 acquisition data as continuous "
        "equivalent-bit bookkeeping"
    )

    assert decisions.count(heading) == 1
    assert decisions.index("## D287 ") < decisions.index(heading)

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

    s010 = sources.partition("### S010 ")[2].partition(
        "## Rule for Explicit Assumptions"
    )[0]
    normalized = " ".join(s010.lower().split())
    for phrase in (
        "v5.4a1",
        "no new physical source or numerical spacecraft value",
        "derived level-1 sample-grid proxy",
        "identity/no-reduction proposal",
        "not detector truth",
        "file size",
        "stored state",
        "downlink",
        "product truth",
        "capacity",
        "compression",
        "throughput",
        "overhead",
        "storage/obc power",
        "to research",
        "airbus telemetry",
        "wmo 90 w",
        "other-mission naomi memory values",
        "not transferred into production",
    ):
        assert phrase in normalized


def test_a1_adds_exactly_one_production_module_and_preserves_v53_files() -> None:
    production_changes = set(
        subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                "v5.3-final",
                A1_COMMIT,
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
            ["git", "diff", "--name-only", "v5.3-final", A1_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )

    assert production_changes == {"ops_sim/v5/onboard_data.py"}
    assert repository_changes == {
        "V5_DECISION_LOG.md",
        "V5_SOURCE_REGISTER.md",
        "ops_sim/v5/onboard_data.py",
        "tests/test_v54a1_onboard_data_volume.py",
    }
