"""Exercise migrated history checks without mutating the real repository."""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from pathlib import Path
import subprocess

import pytest

from frozen_release_history import FrozenRelease, assert_frozen_release, git, read_blob
import test_v55f_final_release_audit as final_audit


ROOT = Path(__file__).resolve().parents[1]
TAG_REF = "refs/tags/v5.5-final"


def _fixture_git(repository: Path, *arguments: str) -> str:
    """Permit fixture mutations only outside the actual repository."""
    assert not repository.resolve().is_relative_to(ROOT.resolve())
    return subprocess.run(
        ["git", "--no-optional-locks", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _configure_fixture(repository: Path) -> None:
    for key, value in (
        ("user.name", "Frozen release test"),
        ("user.email", "frozen-release-test@example.invalid"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
        ("core.autocrlf", "false"),
        ("core.hooksPath", ".git/no-fixture-hooks"),
    ):
        _fixture_git(repository, "config", "--local", key, value)


def _write(repository: Path, path: str, text: str) -> None:
    assert not repository.resolve().is_relative_to(ROOT.resolve())
    target = repository / path
    assert target.resolve().is_relative_to(repository.resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def _commit(repository: Path, subject: str) -> str:
    _fixture_git(repository, "add", "--all")
    _fixture_git(repository, "commit", "--quiet", "-m", subject)
    return git(repository, "rev-parse", "HEAD").strip()


@pytest.fixture
def synthetic_release(tmp_path):
    assert not tmp_path.resolve().is_relative_to(ROOT.resolve())
    repository = tmp_path / "synthetic-release"
    repository.mkdir()
    _fixture_git(repository, "init", "--quiet", "-b", "v5-redesign")
    _configure_fixture(repository)
    for path in ("README.md", "V5_SOURCE_REGISTER.md", "MODEL_STATUS.md"):
        _write(repository, path, f"Parent evidence: {path}\n")
    _write(repository, "V5_DECISION_LOG.md", "## D301 — Fixture parent\n")
    parent = _commit(repository, "Fixture E")
    for path in sorted(final_audit.APPROVED_F_CHANGES):
        _write(repository, path, f"Frozen F evidence: {path}\n")
    commit = _commit(repository, "Add V5.5F final release audit")
    _fixture_git(repository, "tag", "-a", "v5.5-final", "-m", "Fixture annotation")
    expected = FrozenRelease(
        tag_name="v5.5-final",
        tag_object_id=git(repository, "rev-parse", TAG_REF).strip(),
        commit=commit,
        tree=git(repository, "rev-parse", f"{commit}^{{tree}}").strip(),
        parent=parent,
        subject="Add V5.5F final release audit",
        changed_paths=frozenset(final_audit.APPROVED_F_CHANGES),
    )
    return repository, expected


@pytest.fixture
def historical_repository(tmp_path, monkeypatch):
    # A local shared clone reads existing objects, but owns its refs, index,
    # working files and newly written objects. No source-repository refs change.
    repository = tmp_path / "historical-release"
    _fixture_git(
        tmp_path, "clone", "--quiet", "--shared", "--branch", "v5.5-final",
        "-c", "core.autocrlf=false",
        str(ROOT), str(repository),
    )
    _configure_fixture(repository)
    _fixture_git(repository, "switch", "--quiet", "--create", "v5-redesign")
    assert git(repository, "rev-parse", "HEAD").strip() == final_audit.V55F_COMMIT
    modules = tuple(import_module(name) for name in (
        "test_v55a_contact_capacity",
        "test_v55b_delivery_state_checkpoint",
        "test_v55c_downlink_transmission",
        "test_v55d_downlink_engine_integration",
        "test_v55f_final_release_audit",
        "test_v54a2_acquisition_data_record",
        "test_v54b1_storage_admission",
        "test_v54c_imaging_storage_authorization",
    ))
    for module in modules:
        for name, value in tuple(vars(module).items()):
            if isinstance(value, Path) and value.is_relative_to(ROOT):
                monkeypatch.setattr(module, name, repository / value.relative_to(ROOT))
    return repository, modules


def _successor_documents(repository: Path) -> None:
    _write(repository, "MODEL_STATUS.md", "# Successor status\nA new document layout.\n")
    _write(repository, "README.md", "# Successor README\n")
    for path, addition in (
        ("V5_DECISION_LOG.md", "\n## D303 — Synthetic successor decision\n"),
        ("V5_SOURCE_REGISTER.md", "\n### S011 — Synthetic successor sources\n"),
    ):
        original = (repository / path).read_text(encoding="utf-8")
        _write(repository, path, original + addition)
    _write(repository, "successor_paper_notes.md", "Synthetic successor file.\n")


@pytest.mark.parametrize("state", ("tagged-f", "descendant", "unstaged", "staged"))
def test_frozen_release_accepts_successor_lifecycle_states(synthetic_release, state):
    repository, expected = synthetic_release
    assert_frozen_release(repository, expected)
    before = {path: read_blob(repository, expected.commit, path)
              for path in expected.changed_paths}
    if state != "tagged-f":
        _successor_documents(repository)
    if state == "descendant":
        _commit(repository, "Synthetic successor")
    if state == "staged":
        _fixture_git(repository, "add", "--all")
        assert git(repository, "diff", "--name-only") == ""
        assert git(repository, "diff", "--cached", "--name-only")
    if state == "unstaged":
        assert git(repository, "diff", "--cached", "--name-only") == ""
        assert "successor_paper_notes.md" in git(
            repository, "ls-files", "--others", "--exclude-standard"
        )
    assert_frozen_release(repository, expected)
    assert {path: read_blob(repository, expected.commit, path)
            for path in expected.changed_paths} == before


def _run_migrated_history_tests(modules) -> None:
    calls = (
        (0, "test_d297_and_source_families_record_exact_a_semantics"),
        (0, "test_live_reference_parameter_sources_remain_registered"),
        (1, "test_d298_frozen_docs_source_stability_and_production_scope_are_exact"),
        (2, "test_d299_frozen_status_source_stability_and_c_scope_are_exact"),
        (3, "test_d300_docs_history_boundaries_and_scope_are_exact"),
        (5, "test_d289_and_s010_a2_semantics_preserve_s009_and_a1"),
        (6, "test_d290_and_s010_b1_semantics_preserve_s009"),
        (7, "test_d292_and_s010_record_c_semantics_without_s011"),
    )
    for index, name in calls:
        getattr(modules[index], name)()
    for name in (
        "test_immutable_anchors_subjects_branch_and_parent_chain_are_exact",
        "test_f_scope_is_exact_across_honest_release_lifecycle_states",
        "test_f_has_zero_production_or_example_changes_and_exact_paths",
        "test_tracked_side_paper_and_result_artifacts_are_unchanged_from_e",
        "test_audit_has_exact_sections_anchors_and_no_future_f_hash",
        "test_audit_freezes_implemented_chain_and_release_claims",
        "test_audit_freezes_ownership_and_physical_mission_boundaries",
        "test_audit_records_public_spec_arithmetic_without_overclaim",
        "test_audit_records_all_deferred_boundaries_and_future_owners",
        "test_d302_and_model_status_are_release_candidate_complete_without_tag_claim",
        "test_f_model_status_distinguishes_b_history_from_current_cd_behavior",
        "test_source_register_stays_frozen_and_reference_rate_is_exact",
        "test_accumulated_production_tree_and_slice_ownership_are_exact",
    ):
        getattr(final_audit, name)()
    for path in ("README.md", "V5_SOURCE_REGISTER.md", "KAZEOSAT_PUBLIC_SPEC.md",
                 "V5_4_RELEASE_AUDIT.md"):
        final_audit.test_protected_document_is_value_equal_to_e(path)


@pytest.mark.parametrize("state", ("tagged-f", "descendant", "unstaged", "staged"))
def test_actual_migrated_checks_accept_changed_successor_documents(
    historical_repository, state,
):
    repository, modules = historical_repository
    _run_migrated_history_tests(modules)
    if state != "tagged-f":
        _successor_documents(repository)
    if state == "descendant":
        _commit(repository, "Synthetic successor documentation")
    if state == "staged":
        _fixture_git(repository, "add", "--all")
        assert git(repository, "diff", "--name-only") == ""
        assert git(repository, "diff", "--cached", "--name-only")
    _run_migrated_history_tests(modules)


@pytest.mark.parametrize("damage", (
    "missing", "lightweight", "annotation", "nested", "other-commit",
))
def test_replaced_or_missing_tag_is_rejected(synthetic_release, damage):
    repository, expected = synthetic_release
    assert_frozen_release(repository, expected)
    if damage == "missing":
        _fixture_git(repository, "tag", "-d", expected.tag_name)
        with pytest.raises(subprocess.CalledProcessError):
            assert_frozen_release(repository, expected)
    else:
        if damage == "lightweight":
            _fixture_git(repository, "update-ref", TAG_REF, expected.commit)
        else:
            target = {
                "annotation": expected.commit,
                "nested": expected.tag_object_id,
                "other-commit": expected.parent,
            }[damage]
            _fixture_git(repository, "tag", "-f", "-a", expected.tag_name,
                         target, "-m", "Changed fixture annotation")
        if damage in ("annotation", "nested"):
            assert git(repository, "rev-parse", f"{TAG_REF}^{{}}").strip() == (
                expected.commit
            )
        with pytest.raises(AssertionError, match="release tag object changed"):
            assert_frozen_release(repository, expected)


@pytest.mark.parametrize(("damage", "message"), (
    ("lightweight", "must point to an annotated tag"),
    ("internal-name", "tag header mismatch"),
    ("nested", "type header mismatch"),
    ("other-commit", "object header mismatch"),
))
def test_tag_semantics_are_checked_beyond_object_identity(
    synthetic_release, damage, message,
):
    repository, expected = synthetic_release
    assert_frozen_release(repository, expected)
    if damage == "lightweight":
        tag_object = expected.commit
    elif damage == "internal-name":
        _fixture_git(
            repository, "tag", "-a", "wrong-internal-name", expected.commit,
            "-m", "Fixture annotation",
        )
        tag_object = git(
            repository, "rev-parse", "refs/tags/wrong-internal-name",
        ).strip()
    else:
        target = expected.tag_object_id if damage == "nested" else expected.parent
        _fixture_git(repository, "tag", "-f", "-a", expected.tag_name,
                     target, "-m", "Semantic fixture")
        tag_object = git(repository, "rev-parse", TAG_REF).strip()
    _fixture_git(repository, "update-ref", TAG_REF, tag_object)
    # Synthetic expectations acknowledge the new object only to reach the
    # independent header/type guard. Real-repository expectations stay fixed.
    with pytest.raises(AssertionError, match=message):
        assert_frozen_release(repository, replace(expected, tag_object_id=tag_object))


@pytest.mark.parametrize(("field", "message"), (
    ("commit", "object header mismatch"),
    ("tree", "release tree mismatch"),
    ("parent", "release sole parent mismatch"),
    ("subject", "release subject mismatch"),
    ("changed_paths", "release changed-file scope mismatch"),
))
def test_wrong_expected_release_metadata_is_rejected(synthetic_release, field, message):
    repository, expected = synthetic_release
    assert_frozen_release(repository, expected)
    wrong = {
        "commit": expected.parent,
        "tree": git(repository, "rev-parse", f"{expected.parent}^{{tree}}").strip(),
        "parent": expected.commit,
        "subject": "Incorrect release subject",
        "changed_paths": expected.changed_paths - {"MODEL_STATUS.md"},
    }[field]
    with pytest.raises(AssertionError, match=message):
        assert_frozen_release(repository, replace(expected, **{field: wrong}))


def test_unrelated_head_is_rejected(synthetic_release):
    repository, expected = synthetic_release
    assert_frozen_release(repository, expected)
    unrelated = _fixture_git(repository, "commit-tree", expected.tree,
                             "-m", "Unrelated root").strip()
    _fixture_git(repository, "update-ref", "refs/heads/v5-redesign", unrelated)
    with pytest.raises(AssertionError, match="HEAD must equal or descend"):
        assert_frozen_release(repository, expected)


@pytest.mark.parametrize(("path", "test_name", "missing"), (
    ("V5_5_RELEASE_AUDIT.md", "test_audit_has_exact_sections_anchors_and_no_future_f_hash", True),
    ("V5_5_RELEASE_AUDIT.md", "test_audit_has_exact_sections_anchors_and_no_future_f_hash", False),
    ("V5_DECISION_LOG.md", "test_d302_and_model_status_are_release_candidate_complete_without_tag_claim", False),
    ("MODEL_STATUS.md", "test_f_model_status_distinguishes_b_history_from_current_cd_behavior", False),
    ("V5_SOURCE_REGISTER.md", "test_source_register_stays_frozen_and_reference_rate_is_exact", False),
    ("paper_suite.py", "test_tracked_side_paper_and_result_artifacts_are_unchanged_from_e", False),
))
def test_actual_historical_evidence_checks_reject_bad_fixture_release(
    historical_repository, monkeypatch, path, test_name, missing,
):
    repository, _ = historical_repository
    guard = getattr(final_audit, test_name)
    final_audit.test_f_scope_is_exact_across_honest_release_lifecycle_states()
    guard()
    if missing:
        _fixture_git(repository, "rm", "--", path)
    else:
        _write(repository, path, "Incorrect historical fixture evidence.\n")
    damaged_commit = _commit(repository, "Damaged fixture evidence")
    # Parameterize the actual blob-reading guard with an alternative fixture
    # release. The original F object and every real-repository ref are intact.
    monkeypatch.setattr(final_audit, "V55F_COMMIT", damaged_commit)
    failure = subprocess.CalledProcessError if missing else AssertionError
    with pytest.raises(failure):
        guard()


def test_live_reference_source_lookup_still_rejects_removed_source(
    historical_repository,
):
    repository, modules = historical_repository
    guard = modules[0].test_live_reference_parameter_sources_remain_registered
    guard()
    _write(repository, "V5_SOURCE_REGISTER.md", "### S011 — Fixture only\n")
    # Historical A evidence survives; the independent LIVE source lookup fails.
    modules[0].test_d297_and_source_families_record_exact_a_semantics()
    with pytest.raises(AssertionError):
        guard()
