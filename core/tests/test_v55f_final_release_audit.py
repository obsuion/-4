"""Final release/freeze audit for the bounded V5.5 implementation."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
import re
import subprocess

import pytest

from frozen_release_history import FrozenRelease, assert_frozen_release, read_blob

import examples.v55_integrated_downlink_demo as demo_module
from examples.v52_integrated_eps_thermal_demo import build_demo_context
from ops_sim.v5.checkpoint import (
    CURRENT_CHECKPOINT_SCHEMA_VERSION,
    CheckpointState,
)
from ops_sim.v5.communications import (
    DownlinkCapacityProposal,
    ServiceableGroundContact,
    compute_downlink_capacity,
)
from ops_sim.v5.configuration import CommunicationsConfig
from ops_sim.v5.data_delivery import (
    CompletedAcquisitionDelivery,
    DownlinkTransferProgress,
    GroundDataDeliveryState,
)
from ops_sim.v5.downlink import (
    DownlinkTransmissionResult,
    DownlinkTransmissionStatus,
    evaluate_downlink_transmission,
)
from ops_sim.v5.engine import (
    DownlinkEngineStepResult,
    SimulationEngine,
)
from ops_sim.v5.ids import (
    AcquisitionDataRecordId,
    GroundContactId,
    GroundStationId,
    ParameterId,
    SourceRecordId,
    SubsystemConfigurationId,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.state import DataStorageState


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "V5_5_RELEASE_AUDIT.md"
MODEL_STATUS_PATH = ROOT / "MODEL_STATUS.md"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
PUBLIC_SPEC_PATH = ROOT / "KAZEOSAT_PUBLIC_SPEC.md"
V54_AUDIT_PATH = ROOT / "V5_4_RELEASE_AUDIT.md"
README_PATH = ROOT / "README.md"
CHECKPOINT_PATH = ROOT / "ops_sim" / "v5" / "checkpoint.py"
DOWNLINK_PATH = ROOT / "ops_sim" / "v5" / "downlink.py"

V54_FINAL = "526d131a8ca2df7fdce25d90619f5545806eac1d"
V55A_COMMIT = "b6c42a79c7ed28c6abb6685692e0a117cbdd26dc"
V55B_COMMIT = "aeba9d10493fcf7d5dd36d31556ad42f5f825d7a"
V55C_COMMIT = "f1b655c85965168aac4f694f28bdc73e78762b82"
V55D_COMMIT = "2a6674b3b48b34f68d9c2e34be97d63d0c2b2066"
V55E_COMMIT = "96ffc1f2db7759e5b373afd3b2e5d14195a5f556"
V55F_COMMIT = "430e87cfc9f1e7781151f97e3dccd1d1d267fe8c"
V55F_TREE = "1197b591233859e611cd0f10b575b16b3225e189"
V55_FINAL_TAG_OBJECT = "20cec2eb34266a20c96a9411e60d45c63c96abdf"

ANCHORS = (
    V54_FINAL,
    V55A_COMMIT,
    V55B_COMMIT,
    V55C_COMMIT,
    V55D_COMMIT,
    V55E_COMMIT,
)
SUBJECTS = (
    "Add V5.5A nominal contact capacity",
    "Add V5.5B delivery state and schema 5",
    "Add V5.5C pure downlink transmission",
    "Add V5.5D atomic downlink execution",
    "Add V5.5E integrated downlink demonstration",
)
APPROVED_F_CHANGES = {
    "MODEL_STATUS.md",
    "V5_5_RELEASE_AUDIT.md",
    "V5_DECISION_LOG.md",
    "tests/test_v55e_integrated_downlink_demo.py",
    "tests/test_v55f_final_release_audit.py",
}
V55_RELEASE = FrozenRelease(
    tag_name="v5.5-final",
    tag_object_id=V55_FINAL_TAG_OBJECT,
    commit=V55F_COMMIT,
    tree=V55F_TREE,
    parent=V55E_COMMIT,
    subject="Add V5.5F final release audit",
    changed_paths=frozenset(APPROVED_F_CHANGES),
)
EXPECTED_V55_PRODUCTION = {
    "ops_sim/v5/checkpoint.py",
    "ops_sim/v5/communications.py",
    "ops_sim/v5/configuration.py",
    "ops_sim/v5/context.py",
    "ops_sim/v5/data_delivery.py",
    "ops_sim/v5/downlink.py",
    "ops_sim/v5/engine.py",
    "ops_sim/v5/ids.py",
}


@pytest.fixture(scope="module")
def report():
    return demo_module.run_v55_integrated_downlink_demo()


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _f_changes() -> set[str]:
    return set(_git(
        "diff", "--name-only", "--no-renames", V55E_COMMIT, V55F_COMMIT
    ).splitlines())


def _f_text(path: str) -> str:
    return read_blob(ROOT, V55F_COMMIT, path)


def test_immutable_anchors_subjects_branch_and_parent_chain_are_exact() -> None:
    assert _git("branch", "--show-current").strip() == "v5-redesign"
    assert _git("rev-parse", "v5.4-final^{}").strip() == V54_FINAL
    assert _git("cat-file", "-t", "v5.4-final").strip() == "tag"

    for index, commit in enumerate(ANCHORS[1:]):
        parents = _git("rev-list", "--parents", "-n", "1", commit).split()
        assert parents == [commit, ANCHORS[index]]
        assert _git("show", "-s", "--format=%s", commit).strip() == (
            SUBJECTS[index]
        )


def test_f_scope_is_exact_across_honest_release_lifecycle_states() -> None:
    # Release preparation is historical; current development may descend from F
    # and may be unstaged, staged, or contain untracked successor work.
    assert_frozen_release(ROOT, V55_RELEASE)


def test_f_has_zero_production_or_example_changes_and_exact_paths() -> None:
    changes = _f_changes()

    assert changes == APPROVED_F_CHANGES
    assert not any(path.startswith("ops_sim/v5/") for path in changes)
    assert not any(path.startswith("examples/") for path in changes)
    assert "README.md" not in changes
    assert "V5_SOURCE_REGISTER.md" not in changes
    assert "KAZEOSAT_PUBLIC_SPEC.md" not in changes
    assert "V5_4_RELEASE_AUDIT.md" not in changes


@pytest.mark.parametrize(
    "path",
    (
        "README.md",
        "V5_SOURCE_REGISTER.md",
        "KAZEOSAT_PUBLIC_SPEC.md",
        "V5_4_RELEASE_AUDIT.md",
    ),
)
def test_protected_document_is_value_equal_to_e(path) -> None:
    assert _f_text(path) == _git(
        "show", f"{V55E_COMMIT}:{path}"
    )


def test_tracked_side_paper_and_result_artifacts_are_unchanged_from_e() -> None:
    tracked = tuple(
        path
        for path in _git("ls-tree", "-r", "--name-only", V55E_COMMIT).splitlines()
        if re.search(r"(?i)(side|paper|results)", path)
    )

    assert tracked
    assert _git(
        "diff", "--name-only", V55E_COMMIT, V55F_COMMIT, "--", *tracked
    ) == ""


def test_audit_has_exact_sections_anchors_and_no_future_f_hash() -> None:
    audit = _f_text("V5_5_RELEASE_AUDIT.md")
    headings = tuple(
        line[3:] for line in audit.splitlines() if line.startswith("## ")
    )

    assert audit.startswith("# V5.5 final release audit\n")
    assert headings == (
        "1. Release identity and immutable anchors",
        "2. Frozen V5.5 scope",
        "3. Implemented causal/state chain",
        "4. Checkpoint and restart semantics",
        "5. Numerical and accounting boundaries",
        "6. Integrated demonstration evidence",
        "7. Backward compatibility / preserved releases",
        "8. Explicit exclusions and TO-RESEARCH boundaries",
        "9. Validation matrix",
        "10. Release lifecycle and tag policy",
        "11. Release-candidate conclusion",
    )
    for anchor in ANCHORS:
        assert anchor in audit
    assert set(re.findall(r"\b[0-9a-f]{40}\b", audit)) == set(ANCHORS)
    assert (
        "Uncommitted verification/freeze work; no future F commit hash is "
        "asserted."
    ) in audit


def test_audit_freezes_implemented_chain_and_release_claims() -> None:
    normalized = _normalized(_f_text("V5_5_RELEASE_AUDIT.md"))

    for phrase in (
        "externally supplied serviceable contacts",
        "nominal rate-times-duration capacity",
        "partial-transfer progress",
        "completed acquisition deliveries",
        "schema 5",
        "partial or complete transmission",
        "simulationengine.step_downlink",
        "checkpoint-isolated working context",
        "precommit result construction",
        "one authoritative commit",
        "complete rollback",
        "whole-record storage release",
        "unused capacity",
        "checkpointstate.from_context",
        "json round trips are deterministic",
        "no `isclose`, epsilon, tolerance, `nextafter`",
        "release-candidate complete",
        "pending final human review",
        "explicit `v5.5-final` tag creation",
    ):
        assert phrase in normalized


def test_audit_freezes_ownership_and_physical_mission_boundaries() -> None:
    normalized = _normalized(_f_text("V5_5_RELEASE_AUDIT.md"))

    for phrase in (
        "communications configuration owns",
        "servicablegroundcontact".replace("servicable", "serviceable"),
        "datastoragestate` owns",
        "grounddatadeliverystate` owns",
        "partial service retains the full onboard record",
        "occupancy remains derived",
        "record identity is the custody key",
        "repeated request or opportunity lineage is allowed",
        "groundknowledgestate` remains epistemic",
        "missionstate` does not",
        "modeled link-service completion of one acquisition record only",
        "communications power and concurrent physical evolution are not modeled during v5.5 downlink bookkeeping.",
    ):
        assert phrase in normalized
    assert "zero-power downlink" not in normalized


def test_audit_records_public_spec_arithmetic_without_overclaim() -> None:
    normalized = _normalized(_f_text("V5_5_RELEASE_AUDIT.md"))

    for phrase in (
        "270_000_000 bit/s",
        "16_200_000_000 bits = 2.025 decimal gb",
        "not measured delivered throughput",
        "recorder write rate",
        "rf link-budget output",
        "command/housekeeping rate",
        "5,000-bit-per-23-second",
        "explicit_model_assumption",
        "not kazeosat hardware performance",
    ):
        assert phrase in normalized


def test_audit_records_all_deferred_boundaries_and_future_owners() -> None:
    normalized = _normalized(_f_text("V5_5_RELEASE_AUDIT.md"))

    for phrase in (
        "communications electrical power",
        "transmitter heat",
        "antenna gain or pattern",
        "receiver g/t",
        "weather/rain loss",
        "modulation/coding/fec efficiency",
        "packet/file overhead",
        "acknowledgement/retry/error behavior",
        "automatic multiple-record capacity allocation",
        "orbit-derived contacts",
        "aos/los/elevation geometry",
        "partial-step contacts",
        "variable-duration engine stepping",
        "scheduling/controller policy",
        "automatic record selection",
        "ground processing",
        "dataproduct` creation",
        "mission-request completion",
        "customer delivery/completion",
        "v5.6 remains the owner",
        "v5.7 remains the owner",
        "v5.8 remains the owner",
    ):
        assert phrase in normalized


def test_d302_and_model_status_are_release_candidate_complete_without_tag_claim() -> None:
    decisions = _f_text("V5_DECISION_LOG.md")
    status = _normalized(_f_text("MODEL_STATUS.md"))
    heading = (
        "## D302 — V5.5 is release-candidate complete pending human review "
        "and tag"
    )

    assert decisions.count(heading) == 1
    assert decisions.index("## D301 ") < decisions.index(heading)
    assert "## D303 " not in decisions
    normalized_decision = _normalized(decisions.partition(heading)[2])
    for phrase in (
        "verification and freeze evidence only",
        "changes no production module, equation, configuration value, state, checkpoint schema, runtime behavior, or public api",
        "no new physical source, literature value, or spacecraft numerical value",
        "verify v5.5a-e as one immutable causal and state chain",
        "release-candidate complete",
        "internal release evidence for the implemented scope only",
        "external calibration",
        "flight qualification",
        "operational validation",
        "real delivered-throughput validation",
        "does not create or claim `v5.5-final`",
        "separate human-reviewed action",
    ):
        assert phrase in normalized_decision

    for phrase in (
        "current v5.5 release-candidate status",
        "v5.5 is **release-candidate complete**",
        "pending final human review",
        "explicit `v5.5-final` tag creation",
        "no such tag is claimed or created by the v5.5f audit",
        V55A_COMMIT,
        V55B_COMMIT,
        V55C_COMMIT,
        V55D_COMMIT,
        V55E_COMMIT,
        "production behavior is frozen through v5.5d",
        "integrated release demonstration evidence only",
        "v5.5f is final audit and freeze evidence only",
        "adds no production or example behavior",
        "live checkpoint remains schema 5",
        "external calibration",
        "real delivered-throughput validation",
        "flight qualification",
        "operational validation",
        "digital-twin status",
    ):
        assert phrase in status


def test_f_model_status_distinguishes_b_history_from_current_cd_behavior() -> None:
    status = _f_text("MODEL_STATUS.md")
    current_status, marker, _ = status.partition(
        "## Historical status at the 2026-08-31 handoff"
    )

    assert marker == "## Historical status at the 2026-08-31 handoff"
    normalized = _normalized(current_status)
    for obsolete_claim in (
        "V5.5B adds state and persistence only. Communications power and "
        "concurrent physical evolution remain unmodeled, and no executable "
        "transmission, record-removal, engine-downlink, controller-policy, "
        "or scheduling behavior is implemented.",
        "later V5.5 work owns transmission arithmetic, record removal, "
        "engine integration, and communications power or thermal coupling",
    ):
        assert _normalized(obsolete_claim) not in normalized

    for current_claim in (
        "V5.5B introduced delivery state and persistence",
        "V5.5C and V5.5D subsequently added pure transmission arithmetic "
        "and atomic downlink execution",
        "whole-record removal on completed delivery",
        "Communications power and concurrent physical evolution",
    ):
        assert _normalized(current_claim) in normalized


def test_source_register_stays_frozen_and_reference_rate_is_exact() -> None:
    assert _f_text("V5_SOURCE_REGISTER.md") == _git(
        "show", f"{V55E_COMMIT}:V5_SOURCE_REGISTER.md"
    )
    assert _f_text("KAZEOSAT_PUBLIC_SPEC.md") == _git(
        "show", f"{V55E_COMMIT}:KAZEOSAT_PUBLIC_SPEC.md"
    )
    communications = CommunicationsConfig(
        SubsystemConfigurationId("v55f-public-reference-communications"),
        ScalarParameter(
            270_000_000.0,
            ParameterProvenance(
                ParameterId("communications.nominal-downlink-data-rate"),
                ProvenanceClass.PUBLIC_SPECIFICATION,
                "bit/s",
                (
                    SourceRecordId(
                        "s001-airbus-kazeosat-1-technical-sheet-2019"
                    ),
                ),
                ProvenanceStatus.VERIFIED,
                rationale="Frozen public nominal X-band reference.",
            ),
        ),
    )
    contact = ServiceableGroundContact(
        GroundContactId("v55f-sixty-second-contact"),
        GroundStationId("v55f-station"),
        100,
        160,
    )
    proposal = compute_downlink_capacity(communications, contact)
    assert proposal.nominal_contact_capacity_bits == 16_200_000_000.0
    assert proposal.nominal_contact_capacity_bits / 8_000_000_000.0 == 2.025


def test_accumulated_production_tree_and_slice_ownership_are_exact() -> None:
    total = set(
        _git(
            "diff",
            "--name-only",
            V54_FINAL,
            V55E_COMMIT,
            "--",
            "ops_sim/v5",
        ).splitlines()
    )
    assert total == EXPECTED_V55_PRODUCTION

    expected_by_slice = (
        (
            V54_FINAL,
            V55A_COMMIT,
            {
                "ops_sim/v5/communications.py",
                "ops_sim/v5/configuration.py",
                "ops_sim/v5/ids.py",
            },
        ),
        (
            V55A_COMMIT,
            V55B_COMMIT,
            {
                "ops_sim/v5/checkpoint.py",
                "ops_sim/v5/context.py",
                "ops_sim/v5/data_delivery.py",
                "ops_sim/v5/engine.py",
            },
        ),
        (V55B_COMMIT, V55C_COMMIT, {"ops_sim/v5/downlink.py"}),
        (V55C_COMMIT, V55D_COMMIT, {"ops_sim/v5/engine.py"}),
        (V55D_COMMIT, V55E_COMMIT, set()),
    )
    for earlier, later, expected in expected_by_slice:
        assert set(
            _git(
                "diff",
                "--name-only",
                earlier,
                later,
                "--",
                "ops_sim/v5",
            ).splitlines()
        ) == expected


def test_live_public_api_surfaces_and_earlier_engine_paths_are_preserved() -> None:
    assert ServiceableGroundContact is not None
    assert DownlinkCapacityProposal is not None
    assert callable(compute_downlink_capacity)
    assert DownlinkTransferProgress is not None
    assert CompletedAcquisitionDelivery is not None
    assert GroundDataDeliveryState is not None
    assert DownlinkTransmissionStatus is not None
    assert DownlinkTransmissionResult is not None
    assert callable(evaluate_downlink_transmission)
    assert DownlinkEngineStepResult is not None
    for method_name in (
        "step",
        "step_imaging",
        "step_imaging_to_storage",
        "step_downlink",
    ):
        assert callable(getattr(SimulationEngine, method_name))


def test_live_schema_five_preserves_historical_schema_four_boundary() -> None:
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    historical = _git("show", f"{V54_FINAL}:ops_sim/v5/checkpoint.py")
    assert "CURRENT_CHECKPOINT_SCHEMA_VERSION = 4" in historical
    assert "CURRENT_CHECKPOINT_SCHEMA_VERSION = 5" not in historical

    context = build_demo_context()
    payload = CheckpointState.from_context(context).to_dict()
    payload["schema_version"] = 4
    with pytest.raises(ValueError, match="schema_version 4; expected 5"):
        CheckpointState.from_dict(payload)


def test_numerical_path_retains_exact_fsum_min_and_no_repair_calls() -> None:
    source = DOWNLINK_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    evaluator = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "evaluate_downlink_transmission"
    )
    calls = [
        _call_name(node)
        for node in ast.walk(evaluator)
        if isinstance(node, ast.Call)
    ]

    assert calls.count("compute_downlink_capacity") == 1
    assert calls.count("min") == 1
    assert calls.count("fsum") == 1
    assert set(calls).isdisjoint({"isclose", "nextafter", "round", "ceil", "floor"})


def test_state_ownership_has_no_redundant_accounting_fields() -> None:
    assert tuple(field.name for field in fields(DataStorageState)) == (
        "stored_records",
    )
    assert tuple(field.name for field in fields(GroundDataDeliveryState)) == (
        "partial_transfers",
        "completed_deliveries",
    )
    forbidden = {
        "occupancy_bits",
        "freed_bits",
        "remaining_bits",
        "backlog_bits",
        "delivered_bits",
    }
    assert forbidden.isdisjoint(
        {field.name for field in fields(DataStorageState)}
        | {field.name for field in fields(GroundDataDeliveryState)}
    )


def test_integrated_e_evidence_is_exact_and_physical_domains_do_not_evolve(
    report,
) -> None:
    rows = report.direct_rows

    assert len(rows) == 4
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
    assert tuple(
        row.transmitted_equivalent_bits_this_service for row in rows
    ) == (5_000.0, 5_000.0, 2_000.0, 4_000.0)
    assert tuple(row.unused_contact_capacity_bits for row in rows) == (
        0.0,
        0.0,
        3_000.0,
        1_000.0,
    )
    assert tuple(
        row.onboard_occupancy_after_equivalent_bits for row in rows
    ) == (16_000.0, 16_000.0, 4_000.0, 0.0)
    assert report.checkpoint_schema_version == 5
    assert report.checkpoint_split_index == 1
    assert report.direct_restart_rows_equal is True
    assert report.direct_restart_final_context_equal is True
    assert report.repeat_rows_equal is True
    assert report.direct_repeat_final_context_equal is True
    assert tuple(
        record_id.value for record_id in report.final_completed_record_ids
    ) == ("v55e-record-a", "v55e-record-b")
    assert report.final_partial_transfer_count == 0
    assert report.physical_domains_unchanged is True
    assert all(row.physical_evidence_fields_all_none for row in rows)


def test_public_downlink_failure_retains_complete_context_value() -> None:
    context = demo_module._build_demo_context()
    before = deepcopy(context)

    with pytest.raises(ValueError, match="not onboard"):
        SimulationEngine().step_downlink(
            context,
            demo_module._contacts()[0],
            record_id=AcquisitionDataRecordId("v55f-missing-record"),
        )
    assert context == before


def test_no_deferred_public_engine_surface_or_state_field_appeared() -> None:
    for method_name in (
        "step_downlink_many",
        "step_downlink_schedule",
        "step_partial_contact",
        "derive_orbit_contacts",
        "select_downlink_record",
        "complete_mission_request",
        "complete_customer_delivery",
    ):
        assert not hasattr(SimulationEngine, method_name)
    all_state_fields = {
        field.name for field in fields(GroundDataDeliveryState)
    } | {field.name for field in fields(DataStorageState)}
    assert all_state_fields.isdisjoint(
        {
            "communications_power_w",
            "transmitter_heat_w",
            "automatic_schedule",
            "mission_completion",
            "customer_completion",
        }
    )
