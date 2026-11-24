"""Integrated accumulation, replay, and capacity evidence for V5.4E."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields
from inspect import signature
from json import dumps, loads
from math import fsum
from pathlib import Path
import subprocess
import sys

import pytest

import examples.v54_integrated_storage_demo as demo
from examples.v54_integrated_storage_demo import (
    CapacityBoundaryReport,
    StorageAccumulationRow,
    V54IntegratedStorageDemoReport,
    run_v54_integrated_storage_demo,
)
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.imaging_storage import ImagingStorageAuthorizationStatus


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples" / "v54_integrated_storage_demo.py"
D2_TEST_PATH = (
    ROOT / "tests" / "test_v54d2_imaging_storage_engine_integration.py"
)
D1_COMMIT = "ed7fd889f53339bf0fb220df76b69c53c36a448e"
D2_COMMIT = "537291dc787adb18137dba550be4e82501f2e3b1"
E_COMMIT = "20d2b4079e6f44460032865eacbd4cd25204c243"


@pytest.fixture(scope="module")
def report() -> V54IntegratedStorageDemoReport:
    return run_v54_integrated_storage_demo()


def _git_show(commit: str, relative_path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


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


def _run_successes(context, count: int, *, series: str):
    attempts = []
    engine = SimulationEngine()
    for index in range(count):
        attempts.append(
            demo._execute_storage_step(engine, context, index, series)
        )
    return tuple(attempts)


def _method_source(path: Path, method_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    segment = ast.get_source_segment(source, function)
    assert segment is not None
    return segment


def test_demo_import_has_no_output_and_public_exports_are_exact() -> None:
    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            "import examples.v54_integrated_storage_demo",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert imported.stdout == ""
    assert imported.stderr == ""
    assert demo.__all__ == [
        "CapacityBoundaryReport",
        "StorageAccumulationRow",
        "V54IntegratedStorageDemoReport",
        "run_v54_integrated_storage_demo",
    ]
    assert tuple(signature(run_v54_integrated_storage_demo).parameters) == ()


def test_report_dataclass_contracts_are_exact_frozen_slotted_and_required(
    report,
) -> None:
    expected_fields = {
        StorageAccumulationRow: (
            "step_index",
            "start_time_seconds",
            "end_time_seconds",
            "record_id",
            "stored_record_count",
            "stored_occupancy_equivalent_bits",
            "battery_energy_wh",
            "authorization_status",
            "physical_evidence_reused",
        ),
        CapacityBoundaryReport: (
            "successful_rows",
            "represented_capacity_equivalent_bits",
            "full_occupancy_equivalent_bits",
            "rejected_record_id",
            "rejected_status",
            "rejected_step_result_present",
            "rejection_context_unchanged",
            "rejection_authoritative_identities_unchanged",
        ),
        V54IntegratedStorageDemoReport: (
            "direct_rows",
            "restarted_rows",
            "direct_restart_rows_equal",
            "direct_restart_context_equal",
            "restart_mutable_state_fresh",
            "final_record_count",
            "final_occupancy_equivalent_bits",
            "checkpoint_split_step",
            "checkpoint_schema_version",
            "capacity_boundary",
        ),
    }
    for contract, names in expected_fields.items():
        assert tuple(field.name for field in fields(contract)) == names
        assert contract.__dataclass_params__.frozen
        assert all(
            field.default is MISSING and field.default_factory is MISSING
            for field in fields(contract)
        )
    assert not hasattr(report, "__dict__")
    assert not hasattr(report.direct_rows[0], "__dict__")
    assert not hasattr(report.capacity_boundary, "__dict__")
    with pytest.raises(FrozenInstanceError):
        report.final_record_count = 0


def test_accumulation_has_twelve_authorized_ordered_growth_rows(report) -> None:
    rows = report.direct_rows

    assert len(rows) == demo.ACCUMULATION_STEPS == 12
    assert all(
        row.authorization_status is ImagingStorageAuthorizationStatus.AUTHORIZED
        for row in rows
    )
    assert all(row.physical_evidence_reused for row in rows)
    assert tuple(row.stored_record_count for row in rows) == tuple(
        range(1, 13)
    )
    assert tuple(row.record_id.value for row in rows) == tuple(
        f"v54e-accumulation-{index:03d}" for index in range(12)
    )
    assert len({row.record_id for row in rows}) == 12


def test_accumulation_time_diagnostics_and_occupancy_evolve_exactly(
    report,
) -> None:
    rows = report.direct_rows

    assert tuple(row.start_time_seconds for row in rows) == tuple(
        demo.DEMO_START_SECONDS + index * demo.DEMO_TIMESTEP_SECONDS
        for index in range(12)
    )
    assert tuple(row.end_time_seconds for row in rows) == tuple(
        demo.DEMO_START_SECONDS + (index + 1) * demo.DEMO_TIMESTEP_SECONDS
        for index in range(12)
    )
    expected_occupancies = tuple(
        fsum(demo.EXPECTED_RECORD_EQUIVALENT_BITS for _ in range(count))
        for count in range(1, 13)
    )
    assert tuple(
        row.stored_occupancy_equivalent_bits for row in rows
    ) == expected_occupancies
    assert all(
        later > earlier
        for earlier, later in zip(
            expected_occupancies,
            expected_occupancies[1:],
        )
    )

    context = demo._build_demo_context()
    live_rows = demo._run_accumulation(
        context,
        range(12),
        series="diagnostics",
    )
    assert context.simulation_time_seconds == 376
    assert context.diagnostics.completed_steps == 12
    assert len(context.spacecraft_state.data_storage.stored_records) == 12
    assert live_rows[-1].stored_occupancy_equivalent_bits == 144_000.0


def test_each_demo_success_reuses_physics_and_appends_exactly_one_record(
    monkeypatch,
) -> None:
    original = SimulationEngine.step_imaging_to_storage
    observed = []

    def observe(self, *args, **kwargs):
        context = kwargs["context"]
        records_before = context.spacecraft_state.data_storage.stored_records
        attempt = original(self, *args, **kwargs)
        observed.append(attempt)
        authorization = attempt.authorization_result
        if authorization.status is ImagingStorageAuthorizationStatus.AUTHORIZED:
            step = attempt.step_result
            f2 = authorization.imaging_authorization_result
            assert step is not None
            assert step.eps_result is f2.electrical_result.eps_result
            assert step.eps_capability_result is (
                f2.electrical_result.eps_capability_result
            )
            assert step.thermal_coupling_result is (
                f2.thermal_proposal.eps_thermal_coupling_result
            )
            assert len(context.spacecraft_state.data_storage.stored_records) == (
                len(records_before) + 1
            )
            assert context.spacecraft_state.data_storage.stored_records[-1] is (
                authorization.storage_admission_result.proposed_record
            )
        return attempt

    monkeypatch.setattr(
        SimulationEngine,
        "step_imaging_to_storage",
        observe,
    )
    run_v54_integrated_storage_demo()

    assert len(observed) == 28
    assert sum(
        attempt.authorization_result.status
        is ImagingStorageAuthorizationStatus.AUTHORIZED
        for attempt in observed
    ) == 27
    assert sum(
        attempt.authorization_result.status
        is ImagingStorageAuthorizationStatus.INSUFFICIENT_STORAGE_CAPACITY
        for attempt in observed
    ) == 1


def test_records_persist_in_attempt_order_without_replacement_or_removal() -> None:
    context = demo._build_demo_context()
    first, second = _run_successes(context, 2, series="identity")
    first_record = first.authorization_result.storage_admission_result.proposed_record
    second_record = second.authorization_result.storage_admission_result.proposed_record
    records = context.spacecraft_state.data_storage.stored_records

    assert records == (first_record, second_record)
    assert records[0] is first_record
    assert records[1] is second_record
    assert len(records) == 2


def test_direct_and_schema_five_restarted_runs_are_exactly_equal(report) -> None:
    assert report.checkpoint_split_step == demo.CHECKPOINT_SPLIT_STEP == 6
    assert report.checkpoint_schema_version == (
        CURRENT_CHECKPOINT_SCHEMA_VERSION
    ) == 5
    assert report.direct_rows == report.restarted_rows
    assert report.direct_restart_rows_equal is True
    assert report.direct_restart_context_equal is True
    assert report.restart_mutable_state_fresh is True
    assert report.final_record_count == 12
    assert report.final_occupancy_equivalent_bits == 144_000.0


def test_explicit_json_checkpoint_pipeline_preserves_values_and_freshens_state(
) -> None:
    source = demo._build_demo_context()
    demo._run_accumulation(source, range(6), series="json")
    checkpoint = CheckpointState.from_context(source)
    encoded = dumps(checkpoint.to_dict(), allow_nan=False, sort_keys=True)
    parsed = CheckpointState.from_dict(loads(encoded))
    restored = parsed.restore(source.inputs)

    assert checkpoint.schema_version == 5
    assert parsed.to_dict() == checkpoint.to_dict()
    assert restored == source
    assert all(
        restored_value is not source_value
        for restored_value, source_value in zip(
            demo._mutable_references(restored),
            demo._mutable_references(source),
        )
    )
    source_records = source.spacecraft_state.data_storage.stored_records
    restored_records = restored.spacecraft_state.data_storage.stored_records
    assert restored_records == source_records
    assert tuple(record.record_id for record in restored_records) == tuple(
        record.record_id for record in source_records
    )
    assert tuple(record.stored_equivalent_bits for record in restored_records) == (
        tuple(record.stored_equivalent_bits for record in source_records)
    )


def test_capacity_boundary_admits_exact_full_then_rejects_next(report) -> None:
    boundary = report.capacity_boundary

    assert len(boundary.successful_rows) == 3
    assert tuple(
        row.stored_record_count for row in boundary.successful_rows
    ) == (1, 2, 3)
    assert all(
        row.authorization_status is ImagingStorageAuthorizationStatus.AUTHORIZED
        for row in boundary.successful_rows
    )
    assert boundary.represented_capacity_equivalent_bits == 36_000.0
    assert boundary.full_occupancy_equivalent_bits == 36_000.0
    assert boundary.rejected_status is (
        ImagingStorageAuthorizationStatus.INSUFFICIENT_STORAGE_CAPACITY
    )
    assert boundary.rejected_step_result_present is False
    assert boundary.rejection_context_unchanged is True
    assert boundary.rejection_authoritative_identities_unchanged is True


def test_capacity_rejection_preserves_all_authoritative_values_and_identities(
    report,
) -> None:
    capacity = report.capacity_boundary.represented_capacity_equivalent_bits
    context = demo._build_demo_context(capacity_equivalent_bits=capacity)
    attempts = _run_successes(context, 3, series="atomicity")
    assert all(
        attempt.authorization_result.status
        is ImagingStorageAuthorizationStatus.AUTHORIZED
        for attempt in attempts
    )
    assert fsum(
        record.stored_equivalent_bits
        for record in context.spacecraft_state.data_storage.stored_records
    ) == capacity
    before = deepcopy(context)
    references = _authoritative_references(context)
    time_before = context.simulation_time_seconds
    completed_before = context.diagnostics.completed_steps
    records_before = context.spacecraft_state.data_storage.stored_records

    rejected = demo._execute_storage_step(
        SimulationEngine(),
        context,
        3,
        "atomicity",
    )

    assert rejected.authorization_result.status is (
        ImagingStorageAuthorizationStatus.INSUFFICIENT_STORAGE_CAPACITY
    )
    assert rejected.step_result is None
    assert context == before
    assert context.simulation_time_seconds == time_before
    assert context.diagnostics.completed_steps == completed_before
    assert context.spacecraft_state.data_storage.stored_records is records_before
    assert all(
        current is original
        for current, original in zip(
            _authoritative_references(context),
            references,
        )
    )


def test_old_imaging_and_storage_paths_have_equal_physical_endpoint() -> None:
    imaging_context = demo._build_demo_context()
    storage_context = demo._build_demo_context()
    imaging_arguments = demo._step_arguments(
        imaging_context,
        0,
        "physical-compare",
    )
    storage_arguments = demo._step_arguments(
        storage_context,
        0,
        "physical-compare",
    )
    del imaging_arguments["record_id"]

    imaging_attempt = SimulationEngine().step_imaging(**imaging_arguments)
    storage_attempt = SimulationEngine().step_imaging_to_storage(
        **storage_arguments
    )

    assert imaging_attempt.step_result == storage_attempt.step_result
    assert imaging_context.simulation_time_seconds == (
        storage_context.simulation_time_seconds
    )
    assert imaging_context.diagnostics == storage_context.diagnostics
    assert imaging_context.spacecraft_state.battery == (
        storage_context.spacecraft_state.battery
    )
    assert imaging_context.spacecraft_state.propulsion == (
        storage_context.spacecraft_state.propulsion
    )
    assert imaging_context.spacecraft_state.thermal == (
        storage_context.spacecraft_state.thermal
    )
    assert imaging_context.spacecraft_state.degradation == (
        storage_context.spacecraft_state.degradation
    )
    assert imaging_context.spacecraft_state.data_storage.stored_records == ()
    assert len(storage_context.spacecraft_state.data_storage.stored_records) == 1


def test_accumulation_preserves_mission_controller_onboard_and_knowledge() -> None:
    context = demo._build_demo_context()
    mission = deepcopy(context.mission_state)
    controller = deepcopy(context.controller_state)
    onboard = deepcopy(context.spacecraft_state.onboard)
    knowledge = deepcopy(context.ground_knowledge_state)

    demo._run_accumulation(context, range(12), series="boundaries")

    assert context.mission_state == mission
    assert context.controller_state == controller
    assert context.spacecraft_state.onboard == onboard
    assert context.ground_knowledge_state == knowledge


def test_example_uses_only_public_d2_execution_and_derived_fsum_reporting() -> None:
    source = EXAMPLE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    call_names = {
        node.func.id
        for node in calls
        if isinstance(node.func, ast.Name)
    } | {
        node.func.attr
        for node in calls
        if isinstance(node.func, ast.Attribute)
    }
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    storage_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and node.func.attr == "step_imaging_to_storage"
    ]

    assert len(storage_calls) == 1
    assert not any(module.startswith("tests") for module in imports)
    assert "_run_transaction" not in call_names
    assert "evaluate_storage_admission" not in call_names
    assert "authorize_imaging_storage_execution" not in call_names
    assert "fsum" in call_names
    assert call_names.isdisjoint(
        {
            "pop",
            "remove",
            "clear",
            "evict",
            "compute_optical_acquisition",
            "evaluate_imaging_engine_step_authorization",
        }
    )
    assert not any(
        isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        and any(
            isinstance(target, ast.Attribute)
            and target.attr == "stored_records"
            for target in (
                node.targets
                if isinstance(node, ast.Assign)
                else (node.target,)
            )
        )
        for node in ast.walk(tree)
    )


def test_example_has_no_random_deletion_or_deferred_storage_semantics() -> None:
    source = EXAMPLE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
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

    assert imported_roots.isdisjoint({"random", "uuid", "communications"})
    assert identifiers.isdisjoint(
        {
            "compression_ratio",
            "compression_factor",
            "codec",
            "throughput",
            "storage_power",
            "obc_power",
            "downlink",
            "transmission",
            "delivery",
            "dataproductid",
            "missionrequestid",
            "evict",
            "remove",
            "clear",
        }
    )


def test_main_output_is_concise_deterministic_and_truthful(capsys) -> None:
    demo.main()
    first = capsys.readouterr()
    demo.main()
    second = capsys.readouterr()

    assert first == second
    assert first.err == ""
    output = first.out
    assert output.startswith("V5.4 integrated storage demo\n")
    assert sum(
        line.startswith("step=") for line in output.splitlines()
    ) == 12
    for phrase in (
        "Synthetic integration evidence only",
        "checkpoint replay:",
            "schema=5",
        "direct_equals_restart=True",
        "capacity boundary:",
        "successful_records=3",
        "next_status=insufficient-storage-capacity",
        "context_unchanged=True",
        "not recorder calibration",
    ):
        assert phrase in output


def test_e_historical_production_tree_is_byte_unchanged_from_d2() -> None:
    production_changes = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            D2_COMMIT,
            E_COMMIT,
            "--",
            "ops_sim/v5",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert production_changes == []


def test_d295_records_e_scope_once_without_d296() -> None:
    decisions = _git_show(E_COMMIT, "V5_DECISION_LOG.md")
    heading = (
        "## D295 — V5.4E demonstrates deterministic storage accumulation, "
        "capacity rejection, and schema-4 replay without new model physics"
    )

    assert decisions.count(heading) == 1
    assert decisions.index("## D294 ") < decisions.index(heading)
    assert "## D296 " not in decisions
    normalized = " ".join(decisions.partition(heading)[2].lower().split())
    for phrase in (
        "not a new production model",
        "public v5.4d2 engine api",
        "exactly one ordered acquisition-data record",
        "complete record sequence with `math.fsum`",
        "schema-4 json checkpoint pipeline",
        "exact-full third record commits",
        "insufficient capacity with no physical or storage commit",
        "no eviction, removal, downlink, communications",
        "recorder-capacity calibration",
        "mission/product completion",
    ):
        assert phrase in normalized


def test_e_model_status_active_section_and_history_are_exact() -> None:
    e_status = _git_show(E_COMMIT, "MODEL_STATUS.md")
    d2 = _git_show(D2_COMMIT, "MODEL_STATUS.md")
    history_heading = "## Historical status at the 2026-08-31 handoff"
    active, separator, history = e_status.partition(history_heading)
    _, d2_separator, d2_history = d2.partition(history_heading)

    assert separator == d2_separator == history_heading
    assert history == d2_history
    normalized = " ".join(active.lower().split())
    for phrase in (
        "v5.3 is complete at the preserved `v5.3-final` tag",
        "v5.4 is **in progress** through e",
        "a1/a2, b1/b2, c, d1, and d2 have landed",
        "physical endpoint and exactly one ordered acquisition-data record",
        "nonauthorization commits neither",
        "checkpoint schema 4",
        "twelve-step deterministic accumulation",
        "exact-full synthetic capacity boundary",
        "compression",
        "recorder throughput",
        "storage/obc power",
        "communications/link/contact-capacity",
        "record removal or eviction",
        "mission/product completion",
        "uncalibrated and to research",
    ):
        assert phrase in normalized
    assert "final v5.4 release" not in normalized


def test_e_source_register_is_byte_identical_to_d2() -> None:
    assert _git_show(E_COMMIT, "V5_SOURCE_REGISTER.md") == _git_show(
        D2_COMMIT, "V5_SOURCE_REGISTER.md"
    )


def test_d2_guards_use_committed_history_not_current_dirty_state() -> None:
    source = D2_TEST_PATH.read_text(encoding="utf-8")
    assert f'D2_COMMIT = "{D2_COMMIT}"' in source
    scope_source = _method_source(
        D2_TEST_PATH,
        "test_d2_historical_scope_is_exactly_nine_files_and_one_production_module",
    )
    decision_source = _method_source(
        D2_TEST_PATH,
        "test_d294_d1_history_and_source_register_are_exact",
    )

    assert "D1_COMMIT, D2_COMMIT" in scope_source
    assert "ls-files" not in scope_source
    assert "--others" not in scope_source
    assert 'f"{D2_COMMIT}:V5_DECISION_LOG.md"' in decision_source
    assert 'f"{D1_COMMIT}:V5_SOURCE_REGISTER.md"' in decision_source
    assert 'f"{D2_COMMIT}:V5_SOURCE_REGISTER.md"' in decision_source
    assert "SOURCE_REGISTER_PATH.read_text" not in decision_source
    historical_changes = set(
        subprocess.run(
            ["git", "diff", "--name-only", D1_COMMIT, D2_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    assert historical_changes == {
        "V5_DECISION_LOG.md",
        "ops_sim/v5/engine.py",
        "tests/test_v50d1_time_engine.py",
        "tests/test_v51f_eps_release_hardening.py",
        "tests/test_v53f3a_engine_transaction_refactor.py",
        "tests/test_v53f3b_imaging_engine_integration.py",
        "tests/test_v53f4b_final_release_audit.py",
        "tests/test_v54d1_engine_precommit_result.py",
        "tests/test_v54d2_imaging_storage_engine_integration.py",
    }


def test_e_historical_scope_is_exactly_five_files_with_zero_production_changes() -> None:
    changes = set(
        subprocess.run(
            ["git", "diff", "--name-only", D2_COMMIT, E_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    production_changes = set(
        subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                D2_COMMIT,
                E_COMMIT,
                "--",
                "ops_sim/v5",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )

    assert changes == {
        "MODEL_STATUS.md",
        "V5_DECISION_LOG.md",
        "examples/v54_integrated_storage_demo.py",
        "tests/test_v54d2_imaging_storage_engine_integration.py",
        "tests/test_v54e_integrated_storage_demo.py",
    }
    assert production_changes == set()
