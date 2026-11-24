"""Final cross-slice release audit for the frozen V5.4 implementation."""

from __future__ import annotations

import ast
from dataclasses import fields, replace
import json
from inspect import Parameter, signature
from math import fsum
from pathlib import Path
import subprocess

import pytest

import examples.v54_integrated_storage_demo as demo
from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
import ops_sim.v5.engine as engine_module
from ops_sim.v5.engine import (
    ImagingEngineStepAttempt,
    ImagingStorageEngineAttempt,
    SimulationEngine,
    StepResult,
)
from ops_sim.v5.ids import (
    AcquisitionDataRecordId,
    ImagingRequestId,
    ObservationOpportunityId,
)
import ops_sim.v5.imaging_storage as imaging_storage_module
from ops_sim.v5.onboard_data import (
    OnboardAcquisitionDataRecord,
    compute_onboard_acquisition_data_volume_proposal,
)
from ops_sim.v5.payload import (
    OpticalAcquisitionChannelSelection,
    OpticalAcquisitionResult,
)
from ops_sim.v5.state import DataStorageState
import ops_sim.v5.storage as storage_module
from ops_sim.v5.storage import (
    StorageAdmissionStatus,
    evaluate_storage_admission,
)


ROOT = Path(__file__).resolve().parents[1]
V5_DIR = ROOT / "ops_sim" / "v5"
AUDIT_PATH = ROOT / "V5_4_RELEASE_AUDIT.md"
MODEL_STATUS_PATH = ROOT / "MODEL_STATUS.md"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
EXAMPLE_PATH = ROOT / "examples" / "v54_integrated_storage_demo.py"
B2_TEST_PATH = ROOT / "tests" / "test_v54b2_persistent_storage_checkpoint.py"
D1_TEST_PATH = ROOT / "tests" / "test_v54d1_engine_precommit_result.py"
D2_TEST_PATH = (
    ROOT / "tests" / "test_v54d2_imaging_storage_engine_integration.py"
)
E_TEST_PATH = ROOT / "tests" / "test_v54e_integrated_storage_demo.py"

V53_FINAL = "72e35594c8f53b93bda789f1cf3ce909088ca88c"
A1_COMMIT = "7f1d7643e60b358f09f5d36b154a1f9e5bc38dc9"
A2_COMMIT = "fcd084ee1ed7af3be81955e58111a8a65de2a3a0"
B1_COMMIT = "45c2771285028c40d0a975b3453f8d182934a38f"
B2_COMMIT = "058eb51dce3825d163c002a002c870e5b6d6e0ad"
C_COMMIT = "c294a794f811532deb9d5666d0ca01999c90951f"
D1_COMMIT = "ed7fd889f53339bf0fb220df76b69c53c36a448e"
D2_COMMIT = "537291dc787adb18137dba550be4e82501f2e3b1"
E_COMMIT = "20d2b4079e6f44460032865eacbd4cd25204c243"
F_COMMIT = "526d131a8ca2df7fdce25d90619f5545806eac1d"

APPROVED_F_CHANGES = {
    "MODEL_STATUS.md",
    "V5_4_RELEASE_AUDIT.md",
    "V5_DECISION_LOG.md",
    "tests/test_v54b2_persistent_storage_checkpoint.py",
    "tests/test_v54d1_engine_precommit_result.py",
    "tests/test_v54d2_imaging_storage_engine_integration.py",
    "tests/test_v54e_integrated_storage_demo.py",
    "tests/test_v54f_final_release_audit.py",
}


@pytest.fixture(scope="module")
def report():
    """Run the public V5.4E integration evidence once for this audit."""
    return demo.run_v54_integrated_storage_demo()


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _git_bytes(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _git_show(commit: str, relative_path: str) -> str:
    return _git("show", f"{commit}:{relative_path}")


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


def _top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    return ast.get_source_segment(source, function) or ""


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _record(
    record_id: str,
    *,
    bits: float,
    request_id: str = "release-request",
    opportunity_id: str = "release-opportunity",
) -> OnboardAcquisitionDataRecord:
    return OnboardAcquisitionDataRecord(
        AcquisitionDataRecordId(record_id),
        ImagingRequestId(request_id),
        ObservationOpportunityId(opportunity_id),
        100,
        1,
        OpticalAcquisitionChannelSelection.PANCHROMATIC_ONLY,
        bits,
        bits,
    )


def test_release_anchors_branch_and_tag_state_are_exact() -> None:
    anchors = (
        V53_FINAL,
        A1_COMMIT,
        A2_COMMIT,
        B1_COMMIT,
        B2_COMMIT,
        C_COMMIT,
        D1_COMMIT,
        D2_COMMIT,
        E_COMMIT,
        F_COMMIT,
    )

    assert _git("rev-parse", "v5.3-final^{}").strip() == V53_FINAL
    for earlier, later in zip(anchors, anchors[1:]):
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", earlier, later],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        assert completed.returncode == 0
    assert _git("show", "-s", "--format=%s", E_COMMIT).strip() == (
        "Add V5.4E integrated storage demonstration"
    )
    assert _git("show", "-s", "--format=%s", F_COMMIT).strip() == (
        "Add V5.4F final release audit"
    )
    committed_changes = set(
        _git("diff", "--name-only", E_COMMIT, F_COMMIT).splitlines()
    )
    assert committed_changes == APPROVED_F_CHANGES
    assert not any(
        path.startswith(("ops_sim/v5/", "examples/"))
        for path in committed_changes
    )
    assert "V5_SOURCE_REGISTER.md" not in committed_changes
    assert _git("tag", "--list", "v5.4-final").strip() == "v5.4-final"
    assert _git("cat-file", "-t", "v5.4-final").strip() == "tag"
    assert _git("rev-parse", "v5.4-final^{}").strip() == F_COMMIT


def test_production_and_v54e_example_are_frozen_to_e() -> None:
    production_changes = _git(
        "diff",
        "--name-only",
        E_COMMIT,
        F_COMMIT,
        "--",
        "ops_sim/v5",
    ).splitlines()

    assert production_changes == []
    production_paths = _git(
        "ls-tree",
        "-r",
        "--name-only",
        E_COMMIT,
        "--",
        "ops_sim/v5",
    ).splitlines()
    assert production_paths
    for relative_path in production_paths:
        assert _git_bytes(
            "show",
            f"{F_COMMIT}:{relative_path}",
        ) == _git_bytes(
            "show",
            f"{E_COMMIT}:{relative_path}",
        )
    assert _git_bytes(
        "show",
        f"{F_COMMIT}:examples/v54_integrated_storage_demo.py",
    ) == _git_bytes(
        "show",
        f"{E_COMMIT}:examples/v54_integrated_storage_demo.py",
    )


def test_source_register_is_frozen_and_v54_has_one_source_family() -> None:
    sources = _git_show(F_COMMIT, "V5_SOURCE_REGISTER.md")
    historical_sources = _git_show(E_COMMIT, "V5_SOURCE_REGISTER.md")
    v53_sources = _git_show(V53_FINAL, "V5_SOURCE_REGISTER.md")
    historical_s009 = v53_sources.partition("### S009 ")[2].partition(
        "## Rule for Explicit Assumptions"
    )[0].rstrip()
    current_s009 = sources.partition("### S009 ")[2].partition(
        "### S010 "
    )[0].rstrip()

    assert sources == historical_sources
    assert current_s009 == historical_s009
    assert sources.count("### S010 ") == 1
    assert "### S011 " not in sources
    normalized = _normalized(
        sources.partition("### S010 ")[2].partition(
            "## Rule for Explicit Assumptions"
        )[0]
    )
    for phrase in (
        "continuous equivalent-bit proposal",
        "explicit acquisition-data record identity",
        "decimal-gb whole-record storage admission",
        "persistent storage state and checkpoint schema 4",
        "pure imaging/storage authorization composition",
        "kazEOSat storage capacity remains to research".lower(),
    ):
        assert phrase in normalized


def test_causal_architecture_has_one_owner_per_boundary() -> None:
    payload_source = (V5_DIR / "payload.py").read_text(encoding="utf-8")
    onboard_source = (V5_DIR / "onboard_data.py").read_text(encoding="utf-8")
    storage_source = (V5_DIR / "storage.py").read_text(encoding="utf-8")
    context_source = (V5_DIR / "context.py").read_text(encoding="utf-8")
    payload_tree = ast.parse(payload_source)
    onboard_tree = ast.parse(onboard_source)
    state_tree = ast.parse(
        (V5_DIR / "state.py").read_text(encoding="utf-8")
    )

    payload_owner = _top_level_function(
        payload_tree,
        "compute_optical_acquisition",
    )
    payload_return = next(
        node
        for node in ast.walk(payload_owner)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Call)
        and _call_name(node.value) == "OpticalAcquisitionResult"
    )
    assert ast.unparse(payload_return.value.args[5]) == "uncompressed_bits"

    a1_owner = _top_level_function(
        onboard_tree,
        "compute_onboard_acquisition_data_volume_proposal",
    )
    a1_assignment = next(
        node
        for node in a1_owner.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "equivalent_bits"
            for target in node.targets
        )
    )
    a1_return = next(
        node
        for node in a1_owner.body
        if isinstance(node, ast.Return)
    )
    assert ast.unparse(a1_assignment.value) == (
        "acquisition_result.uncompressed_equivalent_bits"
    )
    assert isinstance(a1_return.value, ast.Call)
    assert _call_name(a1_return.value) == "OnboardAcquisitionDataVolumeProposal"
    assert tuple(ast.unparse(arg) for arg in a1_return.value.args) == (
        "acquisition_result",
        "equivalent_bits",
        "equivalent_bits",
    )
    assert "acquisition_result.uncompressed_equivalent_bits" in onboard_source
    assert onboard_source.count(
        "compute_onboard_acquisition_data_volume_proposal"
    ) == 2
    assert storage_source.count(
        "_BITS_PER_DECIMAL_GIGABYTE = 8_000_000_000.0"
    ) == 1
    assert storage_source.count("def _finite_fsum(") == 1
    assert storage_source.count("def evaluate_storage_admission(") == 1
    assert context_source.count(
        "validate_storage_records_against_config("
    ) == 1
    data_storage = next(
        node
        for node in state_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DataStorageState"
    )
    annotated_fields = {
        node.target.id
        for node in data_storage.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    }
    assert annotated_fields == {"stored_records"}


def test_continuous_decimal_fsum_and_exact_full_semantics_are_frozen() -> None:
    context = build_demo_context()
    storage_config = context.inputs.spacecraft_configuration.storage
    storage_config = replace(
        storage_config,
        usable_capacity_gb=replace(
            storage_config.usable_capacity_gb,
            value=8.0 / 8_000_000_000.0,
        ),
    )
    first = _record("exact-full-first", bits=3.0)
    second = _record("exact-full-second", bits=5.0)
    admission = evaluate_storage_admission(
        storage_config,
        (first,),
        second,
    )
    onboard_tree = ast.parse(
        (V5_DIR / "onboard_data.py").read_text(encoding="utf-8")
    )
    storage_tree = ast.parse(
        (V5_DIR / "storage.py").read_text(encoding="utf-8")
    )
    trees = (onboard_tree, storage_tree)
    calls = {
        _call_name(node)
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }

    assert type(first.stored_equivalent_bits) is float
    assert first.stored_equivalent_bits == 3.0
    assert storage_module._BITS_PER_DECIMAL_GIGABYTE == 8_000_000_000.0
    assert admission.configured_usable_capacity_bits == 8.0
    assert admission.stored_equivalent_bits_after_if_admitted == 8.0
    assert admission.status is StorageAdmissionStatus.ADMISSIBLE
    assert calls.isdisjoint({"round", "ceil", "floor", "isclose"})
    finite_fsum = _top_level_function(storage_tree, "_finite_fsum")
    assert sum(
        _call_name(node) == "fsum"
        for node in ast.walk(finite_fsum)
        if isinstance(node, ast.Call)
    ) == 1
    identifiers = {
        value.lower()
        for tree in trees
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
    assert identifiers.isdisjoint(
        {"epsilon", "eps", "tolerance", "tol", "quantize"}
    )
    authoritative_fields = {
        field.name
        for owner in (OnboardAcquisitionDataRecord, DataStorageState)
        for field in fields(owner)
    }
    assert not any("byte" in name for name in authoritative_fields)

    fractional_acquisition = OpticalAcquisitionResult(
        7.5,
        7.5,
        0.0,
        0.0,
        7.5,
        7.5,
        0.9375,
        1.0,
        1.0 / 3_600.0,
    )
    fractional_proposal = compute_onboard_acquisition_data_volume_proposal(
        fractional_acquisition
    )
    assert fractional_proposal.acquisition_result is fractional_acquisition
    assert fractional_proposal.uncompressed_equivalent_bits == 7.5
    assert fractional_proposal.stored_equivalent_bits == 7.5

    adversarial_values = (10_000_000_000_000_000.0, 0.5, 0.75)
    complete_total = fsum(adversarial_values)
    collapsed_prefix_total = fsum(
        (fsum(adversarial_values[:-1]), adversarial_values[-1])
    )
    adversarial_records = tuple(
        _record(f"adversarial-{index}", bits=value)
        for index, value in enumerate(adversarial_values)
    )
    assert complete_total == 10_000_000_000_000_002.0
    assert collapsed_prefix_total == 10_000_000_000_000_000.0
    collapsed_config = replace(
        storage_config,
        usable_capacity_gb=replace(
            storage_config.usable_capacity_gb,
            value=collapsed_prefix_total / 8_000_000_000.0,
        ),
    )
    complete_config = replace(
        storage_config,
        usable_capacity_gb=replace(
            storage_config.usable_capacity_gb,
            value=complete_total / 8_000_000_000.0,
        ),
    )
    assert evaluate_storage_admission(
        collapsed_config,
        adversarial_records[:-1],
        adversarial_records[-1],
    ).status is StorageAdmissionStatus.INSUFFICIENT_CAPACITY
    assert evaluate_storage_admission(
        complete_config,
        adversarial_records[:-1],
        adversarial_records[-1],
    ).status is StorageAdmissionStatus.ADMISSIBLE
    b1_tests = (
        ROOT / "tests" / "test_v54b1_storage_admission.py"
    ).read_text(encoding="utf-8")
    assert "test_candidate_total_uses_authoritative_full_sequence_fsum" in (
        b1_tests
    )
    assert "test_storage_arithmetic_uses_fsum_stored_bits_and_no_quantization" in (
        b1_tests
    )


def test_record_identity_lineage_and_persistent_state_contracts_are_exact() -> None:
    first = _record("record-one", bits=7.5)
    repeated_lineage = _record("record-two", bits=11.25)

    assert OnboardAcquisitionDataRecord.__dataclass_params__.frozen
    assert tuple(field.name for field in fields(OnboardAcquisitionDataRecord)) == (
        "record_id",
        "imaging_request_id",
        "observation_opportunity_id",
        "scheduled_start_seconds",
        "acquisition_duration_seconds",
        "channel_selection",
        "uncompressed_equivalent_bits",
        "stored_equivalent_bits",
    )
    assert first.imaging_request_id == repeated_lineage.imaging_request_id
    assert first.observation_opportunity_id == (
        repeated_lineage.observation_opportunity_id
    )
    assert DataStorageState((first, repeated_lineage)).stored_records == (
        first,
        repeated_lineage,
    )
    with pytest.raises(ValueError, match="record IDs.*unique"):
        DataStorageState((first, replace(first)))


def test_live_schema_five_populated_json_restart_is_ordered_fresh_and_strict() -> None:
    records = (
        _record("restart-one", bits=7.5),
        _record("restart-two", bits=11.25),
    )
    source = build_demo_context()
    source = replace(
        source,
        simulation_time_seconds=101,  # Both stored acquisitions have ended.
        spacecraft_state=replace(
            source.spacecraft_state,
            data_storage=DataStorageState(records),
        ),
    )
    checkpoint = CheckpointState.from_context(source)
    encoded = json.dumps(
        checkpoint.to_dict(),
        allow_nan=False,
        sort_keys=True,
    )
    parsed = CheckpointState.from_dict(json.loads(encoded))
    restored = parsed.restore(source.inputs)

    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == checkpoint.schema_version == 5
    assert restored == source
    assert restored is not source
    assert restored.spacecraft_state is not source.spacecraft_state
    assert restored.spacecraft_state.data_storage is not (
        source.spacecraft_state.data_storage
    )
    assert restored.spacecraft_state.data_storage.stored_records == records
    assert json.dumps(
        parsed.to_dict(),
        allow_nan=False,
        sort_keys=True,
    ) == encoded

    legacy = json.loads(encoded)
    legacy["schema_version"] = 3
    del legacy["spacecraft"]["data_storage"]
    with pytest.raises(ValueError, match="schema_version 3; expected 5"):
        CheckpointState.from_dict(legacy)

    future = json.loads(encoded)
    future["schema_version"] = 6
    with pytest.raises(ValueError, match="schema_version 6; expected 5"):
        CheckpointState.from_dict(future)

    storage_config = source.inputs.spacecraft_configuration.storage
    too_small_storage = replace(
        storage_config,
        usable_capacity_gb=replace(
            storage_config.usable_capacity_gb,
            value=10.0 / 8_000_000_000.0,
        ),
    )
    too_small_inputs = replace(
        source.inputs,
        spacecraft_configuration=replace(
            source.inputs.spacecraft_configuration,
            storage=too_small_storage,
        ),
    )
    with pytest.raises(ValueError, match="occupancy exceeds"):
        parsed.restore(too_small_inputs)


def test_c_composes_f2_a1_record_and_b1_once_without_mutation_path() -> None:
    source = (V5_DIR / "imaging_storage.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = _top_level_function(
        tree,
        "authorize_imaging_storage_execution",
    )
    calls = [
        _call_name(node)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    imported_modules = {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    public = imaging_storage_module.authorize_imaging_storage_execution
    parameters = signature(public).parameters
    result_type = imaging_storage_module.ImagingStorageAuthorizationResult
    status_type = imaging_storage_module.ImagingStorageAuthorizationStatus

    assert calls.count("evaluate_imaging_engine_step_authorization") == 1
    assert calls.count(
        "compute_onboard_acquisition_data_volume_proposal"
    ) == 1
    assert calls.count("OnboardAcquisitionDataRecord") == 1
    assert calls.count("evaluate_storage_admission") == 1
    assert imported_modules.isdisjoint(
        {"engine", "checkpoint", "mission", "communications"}
    )
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
        for name in tuple(parameters)[:3]
    )
    assert all(
        parameters[name].kind is Parameter.KEYWORD_ONLY
        for name in tuple(parameters)[3:]
    )
    assert tuple(field.name for field in fields(result_type)) == (
        "imaging_authorization_result",
        "data_volume_proposal",
        "storage_admission_result",
        "status",
    )
    assert result_type.__dataclass_params__.frozen
    assert tuple(member.value for member in status_type) == (
        "authorized",
        "imaging-not-authorized",
        "insufficient-storage-capacity",
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
        for node in ast.walk(function)
    )
    assert not any(
        isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Attribute)
            for target in (
                node.targets
                if isinstance(node, ast.Assign)
                else (node.target,)
            )
        )
        for node in ast.walk(function)
    )
    assert {name for name in calls}.isdisjoint({"setattr", "delattr"})


def test_d1_kernel_keeps_factory_before_commit_and_bare_return() -> None:
    tree = ast.parse((V5_DIR / "engine.py").read_text(encoding="utf-8"))
    kernel = _method(tree, "_run_transaction")
    calls = [node for node in ast.walk(kernel) if isinstance(node, ast.Call)]
    step_result_calls = [
        call for call in calls if _call_name(call) == "StepResult"
    ]
    factory_calls = [
        call
        for call in calls
        if _call_name(call) == "precommit_result_factory"
    ]
    commit_calls = [call for call in calls if _call_name(call) == "_commit"]
    assignments = {
        target.id: node
        for node in kernel.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert len(step_result_calls) == len(factory_calls) == len(commit_calls) == 1
    assert "proposed_result" in assignments
    assert "completion_result" in assignments
    completion_assignment = assignments["completion_result"]
    assert isinstance(completion_assignment.value, ast.IfExp)
    conditional = completion_assignment.value
    assert ast.unparse(conditional.test) == "precommit_result_factory is None"
    assert ast.unparse(conditional.body) == "proposed_result"
    assert ast.unparse(conditional.orelse) == (
        "precommit_result_factory(proposed_result)"
    )
    assert (
        step_result_calls[0].lineno
        < completion_assignment.lineno
        <= factory_calls[0].lineno
        < commit_calls[0].lineno
    )
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


def test_d2_api_and_atomic_append_path_remain_additive_and_singular() -> None:
    source = (V5_DIR / "engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    public_method = _method(tree, "step_imaging_to_storage")
    prepare = _method(
        tree,
        "_prepare_imaging_storage_physical_integration_handler",
    )
    handler = next(
        node
        for node in prepare.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "imaging_storage_physical_integration_handler"
    )
    public_calls = [
        _call_name(node)
        for node in ast.walk(public_method)
        if isinstance(node, ast.Call)
    ]
    handler_calls = [
        _call_name(node)
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
    ]
    appends = [
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and target.attr == "stored_records"
            for target in node.targets
        )
    ]

    assert public_calls.count("_run_transaction") == 1
    assert handler_calls.count("authorize_imaging_storage_execution") == 1
    assert handler_calls.count("_complete_coupled_physical_integration") == 1
    assert set(handler_calls).isdisjoint(
        {
            "evaluate_imaging_engine_step_authorization",
            "compute_onboard_acquisition_data_volume_proposal",
            "evaluate_storage_admission",
        }
    )
    assert len(appends) == 1
    c_call = next(
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and _call_name(node) == "authorize_imaging_storage_execution"
    )
    assert len(c_call.args) == 3
    assert isinstance(c_call.args[0], ast.Name)
    assert c_call.args[0].id == "working_context"
    record_assignment = next(
        node
        for node in handler.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "record"
            for target in node.targets
        )
    )
    assert ast.unparse(record_assignment.value) == (
        "c_result.storage_admission_result.proposed_record"
    )
    assert ast.unparse(appends[0].value) == (
        "storage.stored_records + (record,)"
    )
    physical_call = next(
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and _call_name(node) == "_complete_coupled_physical_integration"
    )
    assert physical_call.lineno < appends[0].lineno

    kernel = _method(tree, "_run_transaction")
    phase_loop = next(node for node in kernel.body if isinstance(node, ast.For))
    completed_context_calls = [
        node
        for node in ast.walk(kernel)
        if isinstance(node, ast.Call)
        and _call_name(node) == "_validate_completed_context"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "working_context"
    ]
    step_result_calls = [
        node
        for node in ast.walk(kernel)
        if isinstance(node, ast.Call) and _call_name(node) == "StepResult"
    ]
    assert len(completed_context_calls) == len(step_result_calls) == 1
    assert (
        phase_loop.end_lineno
        < completed_context_calls[0].lineno
        < step_result_calls[0].lineno
    )

    regression_source = D2_TEST_PATH.read_text(encoding="utf-8")
    for test_name in (
        "test_supported_imaging_nonauthorization_has_exact_zero_commit_cardinality",
        "test_insufficient_storage_is_supported_with_no_tail_or_commit",
        "test_authorized_path_is_one_working_transaction_and_one_atomic_commit",
        "test_duplicate_record_id_propagates_original_b1_exception_without_commit",
        "test_tail_failure_after_c_authorization_rolls_back_before_append",
        "test_postappend_final_validation_failure_is_fully_isolated",
        "test_step_result_failure_after_append_rolls_back_everything",
        "test_outer_attempt_failure_after_step_result_and_append_rolls_back",
    ):
        assert f"def {test_name}(" in regression_source


def test_public_api_preserves_v53_and_adds_storage_surface() -> None:
    historical_tree = ast.parse(_git_show(V53_FINAL, "ops_sim/v5/engine.py"))
    exports_assignment = next(
        node
        for node in historical_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )
    historical_exports = ast.literal_eval(exports_assignment.value)
    v54_tree = ast.parse(_git_show(F_COMMIT, "ops_sim/v5/engine.py"))
    v54_exports_assignment = next(
        node
        for node in v54_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )
    v54_exports = ast.literal_eval(v54_exports_assignment.value)
    generic = signature(SimulationEngine.step).parameters
    imaging = signature(SimulationEngine.step_imaging).parameters
    storage = signature(SimulationEngine.step_imaging_to_storage).parameters

    assert set(historical_exports).issubset(v54_exports)
    assert v54_exports == [
        "STEP_PHASE_ORDER",
        "ImagingEngineStepAttempt",
        "ImagingStorageEngineAttempt",
        "SimulationEngine",
        "SimulationPhase",
        "StepResult",
    ]
    assert set(v54_exports).issubset(engine_module.__all__)
    assert imaging_storage_module.__all__ == [
        "ImagingStorageAuthorizationStatus",
        "ImagingStorageAuthorizationResult",
        "authorize_imaging_storage_execution",
    ]
    assert tuple(generic) == (
        "self",
        "context",
        "eps_inputs",
        "thermal_inputs",
        "heat_source_inputs",
        "solar_degradation_forcing",
    )
    assert tuple(imaging) == (
        "self",
        "context",
        "previous_execution",
        "execution",
        "environment",
        "routing_config",
        "thermal_inputs",
        "external_heat_sources",
        "solar_degradation_forcing",
    )
    assert tuple(storage) == (
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
    assert all(
        storage[name].kind is Parameter.KEYWORD_ONLY
        for name in tuple(storage)[4:]
    )
    assert tuple(field.name for field in fields(ImagingEngineStepAttempt)) == (
        "authorization_result",
        "step_result",
    )
    assert tuple(field.name for field in fields(ImagingStorageEngineAttempt)) == (
        "authorization_result",
        "step_result",
    )
    assert tuple(field.name for field in fields(StepResult)) == (
        "start_time_seconds",
        "end_time_seconds",
        "dt_seconds",
        "executed_phases",
        "eps_result",
        "thermal_coupling_result",
        "battery_degradation_result",
        "solar_degradation_result",
        "eps_capability_result",
        "battery_capacity_reconciliation_result",
    )
    assert StepResult.__dataclass_params__.frozen
    assert not hasattr(
        StepResult(0, 1, 1, engine_module.STEP_PHASE_ORDER),
        "__dict__",
    )
    for old_method in (
        _method(ast.parse((V5_DIR / "engine.py").read_text(encoding="utf-8")), "step"),
        _method(
            ast.parse((V5_DIR / "engine.py").read_text(encoding="utf-8")),
            "step_imaging",
        ),
    ):
        old_names = {
            _call_name(node)
            for node in ast.walk(old_method)
            if isinstance(node, ast.Call)
        }
        old_attributes = {
            node.attr
            for node in ast.walk(old_method)
            if isinstance(node, ast.Attribute)
        }
        assert "authorize_imaging_storage_execution" not in old_names
        assert old_attributes.isdisjoint({"data_storage", "stored_records"})


def test_v54e_accumulation_and_restart_evidence_is_exact(report) -> None:
    assert len(report.direct_rows) == demo.ACCUMULATION_STEPS == 12
    assert len(report.restarted_rows) == 12
    assert report.direct_restart_rows_equal is True
    assert report.direct_restart_context_equal is True
    assert report.restart_mutable_state_fresh is True
    assert report.checkpoint_split_step == demo.CHECKPOINT_SPLIT_STEP == 6
    assert report.checkpoint_schema_version == 5
    assert report.final_record_count == 12
    assert report.final_occupancy_equivalent_bits == 144_000.0
    assert all(
        row.stored_occupancy_equivalent_bits == 12_000.0 * row.step_index
        for row in report.direct_rows
    )
    assert all(row.physical_evidence_reused for row in report.direct_rows)


def test_v54e_exact_full_capacity_and_atomic_rejection_are_exact(report) -> None:
    capacity = report.capacity_boundary

    assert len(capacity.successful_rows) == 3
    assert capacity.represented_capacity_equivalent_bits == 36_000.0
    assert capacity.full_occupancy_equivalent_bits == 36_000.0
    assert capacity.rejected_status.value == "insufficient-storage-capacity"
    assert capacity.rejected_step_result_present is False
    assert capacity.rejection_context_unchanged is True
    assert capacity.rejection_authoritative_identities_unchanged is True


def test_v54e_demo_uses_only_the_public_storage_engine_api() -> None:
    source = EXAMPLE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    assert calls.count("step_imaging_to_storage") == 1
    assert set(calls).isdisjoint(
        {
            "_run_transaction",
            "_prepare_imaging_storage_physical_integration_handler",
            "authorize_imaging_storage_execution",
        }
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
        for node in ast.walk(tree)
    )


def test_v54_production_surface_excludes_deferred_storage_behavior() -> None:
    paths = (
        V5_DIR / "onboard_data.py",
        V5_DIR / "storage.py",
        V5_DIR / "imaging_storage.py",
    )
    identifiers = {
        value.lower()
        for path in paths
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
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
    checkpoint_tree = ast.parse(
        (V5_DIR / "checkpoint.py").read_text(encoding="utf-8")
    )
    state_tree = ast.parse(
        (V5_DIR / "state.py").read_text(encoding="utf-8")
    )
    context_tree = ast.parse(
        (V5_DIR / "context.py").read_text(encoding="utf-8")
    )
    engine_tree = ast.parse(
        (V5_DIR / "engine.py").read_text(encoding="utf-8")
    )
    scoped_nodes = (
        next(
            node
            for node in state_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "DataStorageState"
        ),
        next(
            node
            for node in ast.walk(context_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "__post_init__"
            and any(
                isinstance(candidate, ast.Attribute)
                and candidate.attr == "data_storage"
                for candidate in ast.walk(node)
            )
        ),
        next(
            node
            for node in checkpoint_tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "DataStorageStateSnapshot"
        ),
        _top_level_function(
            checkpoint_tree,
            "_parse_data_storage_state_snapshot",
        ),
        _method(engine_tree, "step_imaging_to_storage"),
        _method(
            engine_tree,
            "_prepare_imaging_storage_physical_integration_handler",
        ),
    )
    identifiers.update(
        value.lower()
        for scoped in scoped_nodes
        for node in ast.walk(scoped)
        for value in (
            (node.id,)
            if isinstance(node, ast.Name)
            else (node.attr,)
            if isinstance(node, ast.Attribute)
            else (node.name,)
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            else ()
        )
    )
    forbidden = {
        "compression_ratio",
        "compression_factor",
        "codec",
        "packet_overhead",
        "file_overhead",
        "throughput_bps",
        "write_rate_bps",
        "storage_power_w",
        "storage_heat_w",
        "overwrite",
        "evict",
        "downlink",
        "transmission",
        "delivery",
        "dataproductid",
        "mission_completion",
        "controller_policy",
        "substep",
        "multirate",
        "compress",
        "decompress",
        "packetize",
        "file_header",
        "recorder_latency",
        "write_power",
        "storage_temperature",
        "delete_record",
        "remove_record",
    }

    assert identifiers.isdisjoint(forbidden)
    record_fields = {
        field.name for field in fields(OnboardAcquisitionDataRecord)
    }
    storage_fields = {field.name for field in fields(DataStorageState)}
    assert (record_fields | storage_fields).isdisjoint(forbidden)


def test_historical_guard_corrections_use_only_fixed_endpoints() -> None:
    d1 = _function_source(
        D1_TEST_PATH,
        "test_d293_source_register_and_d1_historical_scope_are_exact",
    )
    d2 = _function_source(
        D2_TEST_PATH,
        "test_d294_d1_history_and_source_register_are_exact",
    )
    e_production = _function_source(
        E_TEST_PATH,
        "test_e_historical_production_tree_is_byte_unchanged_from_d2",
    )
    e_decision = _function_source(
        E_TEST_PATH,
        "test_d295_records_e_scope_once_without_d296",
    )
    e_status = _function_source(
        E_TEST_PATH,
        "test_e_model_status_active_section_and_history_are_exact",
    )
    e_sources = _function_source(
        E_TEST_PATH,
        "test_e_source_register_is_byte_identical_to_d2",
    )
    e_scope = _function_source(
        E_TEST_PATH,
        "test_e_historical_scope_is_exactly_five_files_with_zero_production_changes",
    )
    e_meta = _function_source(
        E_TEST_PATH,
        "test_d2_guards_use_committed_history_not_current_dirty_state",
    )

    normalized_d1 = " ".join(d1.split())
    assert 'C_COMMIT, "V5_SOURCE_REGISTER.md"' in normalized_d1
    assert 'D1_COMMIT, "V5_SOURCE_REGISTER.md"' in normalized_d1
    assert normalized_d1.count('"V5_SOURCE_REGISTER.md"') == 2
    assert "SOURCE_REGISTER_PATH.read_text" not in d1
    assert 'f"{D1_COMMIT}:V5_SOURCE_REGISTER.md"' in d2
    assert 'f"{D2_COMMIT}:V5_SOURCE_REGISTER.md"' in d2
    assert "SOURCE_REGISTER_PATH.read_text" not in d2
    assert all(
        "E_COMMIT" in source
        for source in (
            e_production,
            e_decision,
            e_status,
            e_sources,
            e_scope,
        )
    )
    assert "D2_COMMIT" in e_production
    assert "D2_COMMIT" in e_sources
    assert "D2_COMMIT" in e_scope
    assert '"git", "diff", "--name-only", D2_COMMIT, E_COMMIT' in (
        " ".join(e_scope.split())
    )
    assert '"git", "diff", "--name-only", D2_COMMIT, E_COMMIT' in (
        " ".join(e_production.split())
    )
    assert "ls-files" not in e_scope
    assert "--others" not in e_scope
    assert "DECISION_LOG_PATH" not in e_decision
    assert "MODEL_STATUS_PATH" not in e_status
    assert "SOURCE_REGISTER_PATH" not in e_sources
    assert '_git_show(E_COMMIT, "V5_DECISION_LOG.md")' in e_decision
    assert '_git_show(E_COMMIT, "MODEL_STATUS.md")' in e_status
    assert '_git_show(E_COMMIT, "V5_SOURCE_REGISTER.md")' in e_sources
    assert 'D2_COMMIT, "V5_SOURCE_REGISTER.md"' in " ".join(
        e_sources.split()
    )
    assert 'f"{D1_COMMIT}:V5_SOURCE_REGISTER.md"' in e_meta
    assert 'f"{D2_COMMIT}:V5_SOURCE_REGISTER.md"' in e_meta
    assert '"SOURCE_REGISTER_PATH.read_text" not in decision_source' in e_meta
    assert _git_bytes(
        "show",
        f"{C_COMMIT}:V5_SOURCE_REGISTER.md",
    ) == _git_bytes(
        "show",
        f"{D1_COMMIT}:V5_SOURCE_REGISTER.md",
    )
    assert _git_bytes(
        "show",
        f"{D1_COMMIT}:V5_SOURCE_REGISTER.md",
    ) == _git_bytes(
        "show",
        f"{D2_COMMIT}:V5_SOURCE_REGISTER.md",
    )
    assert _git_bytes(
        "show",
        f"{D2_COMMIT}:V5_SOURCE_REGISTER.md",
    ) == _git_bytes(
        "show",
        f"{E_COMMIT}:V5_SOURCE_REGISTER.md",
    )


def test_b2_freshness_regression_retains_live_objects_and_uses_is_not() -> None:
    source = B2_TEST_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name
        == "test_repeated_checkpoint_restore_cycles_keep_order_and_fresh_state"
    )
    function_source = ast.get_source_segment(source, function) or ""
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    comparisons = [
        operator
        for node in ast.walk(function)
        if isinstance(node, ast.Compare)
        for operator in node.ops
    ]

    assert "id" not in {_call_name(call) for call in calls}
    generations_assignment = next(
        node
        for node in function.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "generations"
            for target in node.targets
        )
    )
    assert isinstance(generations_assignment.value, ast.List)
    assert len(generations_assignment.value.elts) == 1
    assert ast.unparse(generations_assignment.value.elts[0]) == (
        "(context, context.spacecraft_state, "
        "context.spacecraft_state.data_storage)"
    )
    append_calls = [call for call in calls if _call_name(call) == "append"]
    assert len(append_calls) == 1
    assert ast.unparse(append_calls[0].args[0]) == (
        "(context, context.spacecraft_state, "
        "context.spacecraft_state.data_storage)"
    )
    assert sum(isinstance(operator, ast.IsNot) for operator in comparisons) >= 4
    for phrase in (
        "context is not previous_context",
        "context.spacecraft_state is not previous_spacecraft",
        "context.spacecraft_state.data_storage is not previous_storage",
        "current[2] is not earlier[2]",
        "stored_records == records",
    ):
        assert phrase in function_source


def test_d296_and_model_status_freeze_release_candidate_semantics() -> None:
    decisions = _git_show(F_COMMIT, "V5_DECISION_LOG.md")
    heading = (
        "## D296 — V5.4 is release-candidate complete pending human review "
        "and tag"
    )
    status = _git_show(F_COMMIT, "MODEL_STATUS.md")
    historical_heading = "## Historical status at the 2026-08-31 handoff"
    active, separator, history = status.partition(historical_heading)
    e_status = _git_show(E_COMMIT, "MODEL_STATUS.md")
    _, e_separator, e_history = e_status.partition(historical_heading)

    assert decisions.count(heading) == 1
    assert decisions.index("## D295 ") < decisions.index(heading)
    assert "## D297 " not in decisions
    normalized_decision = _normalized(decisions.partition(heading)[2])
    for phrase in (
        "verification and freeze evidence only",
        "changes no production module",
        "configuration value",
        "checkpoint schema",
        "runtime behavior",
        "public api",
        "physical source",
        "literature source",
        "spacecraft value",
        "complete-sequence `math.fsum`",
        "exact-full admission",
        "schema-4",
        "pure c composition",
        "d1 precommit",
        "d2 atomic",
        "green focused and full release gates",
        "does not create or claim `v5.4-final`",
        "external calibration",
        "flight qualification",
        "operational validation",
        "real recorder fidelity",
        "kazEOSat-1 digital-twin status".lower(),
    ):
        assert phrase in normalized_decision

    assert separator == e_separator == historical_heading
    assert history == e_history
    historical_heading_bytes = historical_heading.encode("utf-8")
    live_bytes = _git_bytes("show", f"{F_COMMIT}:MODEL_STATUS.md")
    e_bytes = _git_bytes("show", f"{E_COMMIT}:MODEL_STATUS.md")
    assert live_bytes.partition(historical_heading_bytes)[1:] == (
        e_bytes.partition(historical_heading_bytes)[1:]
    )
    normalized_active = _normalized(active)
    for phrase in (
        "current v5.4 release-candidate status",
        "**release-candidate complete**",
        "no such tag is claimed or created",
        "continuous equivalent-bit bookkeeping",
        "complete-sequence `math.fsum`",
        "checkpoint schema 4",
        "144,000 derived equivalent bits",
        "exact-full 36,000-bit synthetic capacity boundary",
        "remain outside the frozen v5.4 scope",
        "uncalibrated and to research",
        "v5.5 owns communications",
        "v5.6 owns orbit-derived opportunities",
        "v5.7 owns `missionrequestid`-to-`imagingrequestid` binding",
        "v5.8 owns variable-duration execution",
    ):
        assert phrase in normalized_active
    assert "later v5.4 work owns" not in normalized_active
    assert "v5.4 is **in progress**" not in normalized_active


def test_release_audit_is_complete_truthful_and_has_no_placeholders() -> None:
    audit = AUDIT_PATH.read_text(encoding="utf-8")
    normalized = _normalized(audit)
    headings = tuple(
        _normalized(line.lstrip("# "))
        for line in audit.splitlines()
        if line.startswith("## ")
    )
    expected_headings = tuple(
        f"{index}. {title}"
        for index, title in enumerate(
            (
                "release identity and immutable anchors",
                "implemented scope and causal chain",
                "authoritative-owner table",
                "numerical semantics and limitations",
                "identity and lineage",
                "persistent storage and checkpoint schema",
                "pure imaging/storage authorization",
                "atomicity and rollback matrix",
                "public api and backward compatibility",
                "v5.4e integrated evidence",
                "source/provenance audit",
                "explicit non-scope and deferred owners",
                "historical-guard migrations and f diff scope",
                "focused/full validation evidence",
                "release verdict and tag-not-created statement",
            ),
            start=1,
        )
    )

    assert len(headings) == 15
    assert headings == expected_headings
    for immutable_hash in (
        V53_FINAL,
        A1_COMMIT,
        A2_COMMIT,
        B1_COMMIT,
        B2_COMMIT,
        C_COMMIT,
        D1_COMMIT,
        D2_COMMIT,
        E_COMMIT,
    ):
        assert immutable_hash in audit
    for marker in ("TODO", "TBD", "@@", "X passed"):
        assert marker not in audit
    assert "placeholder" not in normalized
    for phrase in (
        "`v5.4-final` has not been created by f",
        "release-candidate complete",
        "36,000",
        "144,000",
        "schema 4",
        "zero production",
        "zero example",
        "v5_source_register.md",
        "52 passed in 1.62s",
        "52 passed in 1.61s",
        "52 passed in 1.59s",
        "52 passed in 1.55s",
        "20 passed in 2.86s",
        "387 passed in 18.77s",
        "195 passed in 5.27s",
        "2721 passed in 181.85s",
        "2741 passed in 114.92s",
        "149 passed in 5.66s",
        "2741 passed in 113.59s",
        "uncommitted, committed-pretag, and exact-tagged",
        "must peel exactly to the audited f head",
        "no future migration is required",
        "all focused gates and independent b2 processes are green",
        "the full repository is green",
        "f is committed",
        "the committed tree is clean",
        "external calibration",
        "flight qualification",
        "operational validation",
        "real recorder fidelity",
        "v5.5 owns communications",
        "v5.6 owns orbit-derived opportunities",
        "v5.7 owns mission-to-imaging identity binding",
        "v5.8 owns variable-duration methods",
    ):
        assert phrase in normalized


def test_f_scope_is_exact_across_release_lifecycle_states() -> None:
    changes = set(
        _git("diff", "--name-only", E_COMMIT, F_COMMIT).splitlines()
    )
    production = {
        path for path in changes if path.startswith("ops_sim/v5/")
    }
    examples = {path for path in changes if path.startswith("examples/")}

    assert changes == APPROVED_F_CHANGES
    assert production == set()
    assert examples == set()
    assert "V5_SOURCE_REGISTER.md" not in changes
