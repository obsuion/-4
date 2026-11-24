"""Integrated multi-contact/restart/storage-release evidence for V5.5E."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from inspect import signature
from pathlib import Path
import subprocess

import pytest

import examples.v55_integrated_downlink_demo as demo_module
from examples.v55_integrated_downlink_demo import (
    DownlinkServiceRow,
    V55IntegratedDownlinkDemoReport,
    run_v55_integrated_downlink_demo,
)
from ops_sim.v5.checkpoint import CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.data_delivery import DownlinkTransferProgress
from ops_sim.v5.downlink import DownlinkTransmissionStatus
from ops_sim.v5.engine import DownlinkEngineStepResult, SimulationEngine
from ops_sim.v5.ids import AcquisitionDataRecordId


ROOT = Path(__file__).resolve().parents[1]
DEMO_PATH = ROOT / "examples" / "v55_integrated_downlink_demo.py"
V55D_COMMIT = "2a6674b3b48b34f68d9c2e34be97d63d0c2b2066"
V55E_COMMIT = "96ffc1f2db7759e5b373afd3b2e5d14195a5f556"


@pytest.fixture(scope="module")
def report() -> V55IntegratedDownlinkDemoReport:
    return run_v55_integrated_downlink_demo()


def _values(values) -> tuple[object, ...]:
    return tuple(value.value for value in values)


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _assignment_targets(node: ast.AST) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Assign):
        return tuple(node.targets)
    if isinstance(node, ast.AnnAssign):
        return (node.target,)
    if isinstance(node, ast.AugAssign):
        return (node.target,)
    return ()


def test_demo_import_exports_and_signatures_are_narrow(capsys) -> None:
    assert capsys.readouterr().out == ""
    assert demo_module.__all__ == [
        "DownlinkServiceRow",
        "V55IntegratedDownlinkDemoReport",
        "run_v55_integrated_downlink_demo",
    ]
    assert tuple(signature(run_v55_integrated_downlink_demo).parameters) == ()
    assert tuple(signature(demo_module.main).parameters) == ()


def test_report_and_row_are_immutable_slotted_and_self_validating(report) -> None:
    assert DownlinkServiceRow.__dataclass_params__.frozen
    assert V55IntegratedDownlinkDemoReport.__dataclass_params__.frozen
    assert not hasattr(report, "__dict__")
    assert not hasattr(report.direct_rows[0], "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for contract in (DownlinkServiceRow, V55IntegratedDownlinkDemoReport)
        for field in fields(contract)
    )
    assert tuple(field.name for field in fields(DownlinkServiceRow)) == (
        "attempt_index",
        "contact_id",
        "contact_start_seconds",
        "contact_end_seconds",
        "selected_record_id",
        "status",
        "nominal_contact_capacity_bits",
        "transmitted_equivalent_bits_this_service",
        "progress_before_equivalent_bits",
        "progress_after_equivalent_bits",
        "remaining_before_equivalent_bits",
        "remaining_after_equivalent_bits",
        "unused_contact_capacity_bits",
        "utilization_ratio",
        "storage_freed_equivalent_bits",
        "onboard_occupancy_after_equivalent_bits",
        "onboard_record_ids_after",
        "partial_progress_after",
        "completed_record_ids_after",
        "simulation_time_after_seconds",
        "physical_evidence_fields_all_none",
    )
    with pytest.raises(FrozenInstanceError):
        report.final_simulation_time_seconds = 0
    with pytest.raises(ValueError, match="row-equality flag"):
        replace(report, direct_restart_rows_equal=False)
    with pytest.raises(ValueError, match="must be demonstrated"):
        replace(report, restart_mutable_state_fresh=False)


def test_exact_four_contact_scenario_and_transmission_evidence(report) -> None:
    rows = report.direct_rows

    assert len(rows) == 4
    assert tuple(row.attempt_index for row in rows) == (1, 2, 3, 4)
    assert tuple(row.contact_id.value for row in rows) == (
        "v55e-contact-1",
        "v55e-contact-2",
        "v55e-contact-3",
        "v55e-contact-4",
    )
    assert tuple(
        (row.contact_start_seconds, row.contact_end_seconds) for row in rows
    ) == ((100, 123), (123, 146), (146, 169), (169, 192))
    assert tuple(row.selected_record_id.value for row in rows) == (
        "v55e-record-a",
        "v55e-record-a",
        "v55e-record-a",
        "v55e-record-b",
    )
    assert tuple(row.status for row in rows) == (
        DownlinkTransmissionStatus.PARTIAL,
        DownlinkTransmissionStatus.PARTIAL,
        DownlinkTransmissionStatus.COMPLETE,
        DownlinkTransmissionStatus.COMPLETE,
    )
    assert tuple(row.nominal_contact_capacity_bits for row in rows) == (
        5_000.0,
    ) * 4
    assert tuple(
        row.transmitted_equivalent_bits_this_service for row in rows
    ) == (5_000.0, 5_000.0, 2_000.0, 4_000.0)
    assert tuple(row.unused_contact_capacity_bits for row in rows) == (
        0.0,
        0.0,
        3_000.0,
        1_000.0,
    )
    assert tuple(row.utilization_ratio for row in rows) == (1.0, 1.0, 0.4, 0.8)
    assert tuple(row.simulation_time_after_seconds for row in rows) == (
        123,
        146,
        169,
        192,
    )


def test_progress_transitions_are_exact(report) -> None:
    rows = report.direct_rows

    assert tuple(row.progress_before_equivalent_bits for row in rows) == (
        0.0,
        5_000.0,
        10_000.0,
        0.0,
    )
    assert tuple(row.progress_after_equivalent_bits for row in rows) == (
        5_000.0,
        10_000.0,
        12_000.0,
        4_000.0,
    )
    assert tuple(row.remaining_before_equivalent_bits for row in rows) == (
        12_000.0,
        7_000.0,
        2_000.0,
        4_000.0,
    )
    assert tuple(row.remaining_after_equivalent_bits for row in rows) == (
        7_000.0,
        2_000.0,
        0.0,
        0.0,
    )


def test_storage_is_released_only_as_complete_whole_records(report) -> None:
    rows = report.direct_rows

    assert report.initial_onboard_occupancy_equivalent_bits == 16_000.0
    assert tuple(
        row.onboard_occupancy_after_equivalent_bits for row in rows
    ) == (16_000.0, 16_000.0, 4_000.0, 0.0)
    assert tuple(row.storage_freed_equivalent_bits for row in rows) == (
        0.0,
        0.0,
        12_000.0,
        4_000.0,
    )
    assert tuple(_values(row.onboard_record_ids_after) for row in rows) == (
        ("v55e-record-a", "v55e-record-b"),
        ("v55e-record-a", "v55e-record-b"),
        ("v55e-record-b",),
        (),
    )
    assert report.occupancy_after_a_partial_service_equivalent_bits == 16_000.0
    assert report.occupancy_after_a_completion_equivalent_bits == 4_000.0
    assert report.final_onboard_occupancy_equivalent_bits == 0.0


def test_excess_capacity_is_not_reassigned_and_delivery_order_is_exact(
    report,
) -> None:
    rows = report.direct_rows

    assert rows[2].unused_contact_capacity_bits == 3_000.0
    assert rows[2].onboard_record_ids_after == (
        AcquisitionDataRecordId("v55e-record-b"),
    )
    assert rows[3].progress_before_equivalent_bits == 0.0
    assert rows[0].partial_progress_after == (
        DownlinkTransferProgress(
            AcquisitionDataRecordId("v55e-record-a"),
            5_000.0,
        ),
    )
    assert rows[1].partial_progress_after == (
        DownlinkTransferProgress(
            AcquisitionDataRecordId("v55e-record-a"),
            10_000.0,
        ),
    )
    assert rows[2].partial_progress_after == ()
    assert rows[3].partial_progress_after == ()
    assert tuple(_values(row.completed_record_ids_after) for row in rows) == (
        (),
        (),
        ("v55e-record-a",),
        ("v55e-record-a", "v55e-record-b"),
    )
    assert _values(report.final_completed_record_ids) == (
        "v55e-record-a",
        "v55e-record-b",
    )
    assert report.final_partial_transfer_count == 0


def test_schema_five_restart_direct_equality_and_fresh_graph(report) -> None:
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    assert report.checkpoint_schema_version == 5
    assert report.checkpoint_split_index == 1
    assert report.restart_mutable_state_fresh is True
    assert report.direct_restart_rows_equal is True
    assert report.direct_rows == report.restarted_rows
    assert report.direct_restart_final_context_equal is True
    assert report.final_simulation_time_seconds == 192
    assert report.final_completed_steps == report.initial_completed_steps + 4

    tree = ast.parse(DEMO_PATH.read_text(encoding="utf-8"))
    calls = {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    for required in (
        "from_context",
        "to_dict",
        "dumps",
        "loads",
        "from_dict",
        "restore",
    ):
        assert required in calls


def test_fresh_direct_repeat_and_complete_report_are_deterministic(report) -> None:
    assert report.repeat_rows_equal is True
    assert report.direct_rows == report.repeat_rows
    assert report.direct_repeat_final_context_equal is True
    assert run_v55_integrated_downlink_demo() == report


def test_every_service_has_no_physical_evidence_or_domain_evolution(
    monkeypatch,
) -> None:
    observed: list[DownlinkEngineStepResult] = []
    original = SimulationEngine.step_downlink

    def observe(self, context, contact, *, record_id):
        before = deepcopy(demo_module._unchanging_domain_values(context))
        result = original(self, context, contact, record_id=record_id)
        assert demo_module._unchanging_domain_values(context) == before
        observed.append(result)
        return result

    monkeypatch.setattr(SimulationEngine, "step_downlink", observe)
    report = run_v55_integrated_downlink_demo()

    assert report.physical_domains_unchanged is True
    assert len(observed) == 12
    for result in observed:
        step = result.step_result
        assert (
            step.eps_result,
            step.thermal_coupling_result,
            step.battery_degradation_result,
            step.solar_degradation_result,
            step.eps_capability_result,
            step.battery_capacity_reconciliation_result,
        ) == (None,) * 6


def test_demo_composes_public_api_without_state_mutation_or_duplicate_math() -> None:
    source = DEMO_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    assert calls.count("step_downlink") == 1
    assert "evaluate_downlink_transmission" not in calls
    assert "compute_downlink_capacity" not in calls
    assert all(
        not (isinstance(node, ast.Attribute) and node.attr.startswith("_prepare"))
        for node in ast.walk(tree)
    )
    protected_attributes = {
        "stored_records",
        "partial_transfers",
        "completed_deliveries",
    }
    assert not any(
        isinstance(target, ast.Attribute)
        and target.attr in protected_attributes
        for node in ast.walk(tree)
        for target in _assignment_targets(node)
    )
    occupancy = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_occupancy_equivalent_bits"
    )
    assert sum(
        _call_name(node) == "fsum"
        for node in ast.walk(occupancy)
        if isinstance(node, ast.Call)
    ) == 1


def test_main_output_is_concise_deterministic_and_bounded(capsys) -> None:
    demo_module.main()
    first = capsys.readouterr().out
    demo_module.main()
    second = capsys.readouterr().out

    assert first == second
    assert len(first.splitlines()) == 8
    normalized = " ".join(first.casefold().split())
    for phrase in (
        "synthetic integration evidence only",
        "intervals=4",
        "partial/partial/complete/complete",
        "schema=5",
        "direct_restart_equal=true",
        "whole-record storage",
        "unused capacity was not automatically reassigned",
        "communications power and concurrent physical evolution are not modeled during v5.5 downlink bookkeeping.",
    ):
        assert phrase in normalized
    for prohibited in (
        "energy-feasible",
        "zero-power",
        "mission completion",
        "product completion",
        "customer completion",
        "kazeosat calibration",
    ):
        assert prohibited not in normalized


def test_d301_status_and_readme_record_only_demonstration_scope() -> None:
    decisions = subprocess.run(
        ["git", "show", f"{V55E_COMMIT}:V5_DECISION_LOG.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    status = " ".join(
        subprocess.run(
            ["git", "show", f"{V55E_COMMIT}:MODEL_STATUS.md"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.casefold().split()
    )
    readme = " ".join(
        subprocess.run(
            ["git", "show", f"{V55E_COMMIT}:README.md"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.casefold().split()
    )
    heading = (
        "## D301 — V5.5E demonstrates multi-contact delivery, restart, "
        "and whole-record storage release"
    )

    assert decisions.count(heading) == 1
    assert decisions.index("## D300 ") < decisions.index(heading)
    assert "## D302 " not in decisions
    normalized_decision = " ".join(
        decisions.partition(heading)[2].casefold().split()
    )
    for phrase in (
        "adds no production behavior",
        "synthetic four-contact scenario",
        "schema-5",
        "whole-record storage release",
        "deterministic repeat",
        "unused capacity",
    ):
        assert phrase in normalized_decision
    for phrase in (
        "v5.5 is **in progress** through e",
        "2a6674b3b48b34f68d9c2e34be97d63d0c2b2066",
        "integrated demonstration evidence",
        "production behavior remains v5.5d",
        "checkpoint remains schema 5",
        "one caller-selected record per interval",
        "partial records retain their full onboard storage",
        "completed records release their entire stored volume",
        "unused capacity is not automatically reassigned",
        "no mission, product, or customer completion",
        "no orbit-derived contact generation",
    ):
        assert phrase in status
    for phrase in (
        "v5.5 integrated downlink demonstration",
        "python examples/v55_integrated_downlink_demo.py",
        "partial/partial/complete/complete",
        "schema-5",
        "whole-record storage release",
        "unused capacity",
        "communications power and concurrent physical evolution are not modeled during v5.5 downlink bookkeeping.",
    ):
        assert phrase in readme


def test_e_scope_has_zero_production_changes_and_protected_files_are_unchanged() -> None:
    changed = set(
        subprocess.run(
            ["git", "diff", "--name-only", V55D_COMMIT, V55E_COMMIT],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
    )
    production = {
        path for path in changed if path.startswith("ops_sim/v5/")
    }

    assert production == set()
    assert changed == {
        "MODEL_STATUS.md",
        "README.md",
        "V5_DECISION_LOG.md",
        "examples/v55_integrated_downlink_demo.py",
        "tests/test_v55d_downlink_engine_integration.py",
        "tests/test_v55e_integrated_downlink_demo.py",
    }
    protected = (
        "V5_SOURCE_REGISTER.md",
        "KAZEOSAT_PUBLIC_SPEC.md",
        "V5_4_RELEASE_AUDIT.md",
    )
    assert subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            V55D_COMMIT,
            V55E_COMMIT,
            "--",
            *protected,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines() == []
