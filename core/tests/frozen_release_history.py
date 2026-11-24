"""Test-only Git integrity checks independent of successor worktree contents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class FrozenRelease:
    tag_name: str
    tag_object_id: str
    commit: str
    tree: str
    parent: str
    subject: str
    changed_paths: frozenset[str]


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "--no-optional-locks", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def read_blob(repository: Path, commit: str, path: str) -> str:
    """Read evidence from an explicit immutable commit, never a working file."""
    return git(repository, "show", f"{commit}:{path}")


def assert_frozen_release(repository: Path, expected: FrozenRelease) -> None:
    """Validate pinned release objects and ancestry, allowing dirty successors."""
    tag_ref = f"refs/tags/{expected.tag_name}"
    tag_object = git(repository, "rev-parse", "--verify", tag_ref).strip()
    assert tag_object == expected.tag_object_id, "release tag object changed"
    assert git(repository, "cat-file", "-t", tag_object).strip() == "tag", (
        "release ref must point to an annotated tag"
    )
    header = git(repository, "cat-file", "-p", tag_object).partition("\n\n")[0]
    for key, value in (
        ("tag", expected.tag_name),
        ("type", "commit"),
        ("object", expected.commit),
    ):
        entries = [line for line in header.splitlines() if line.startswith(key + " ")]
        assert entries == [f"{key} {value}"], f"release tag {key} header mismatch"
    assert git(repository, "cat-file", "-t", expected.commit).strip() == "commit", (
        "release target must be a commit object"
    )
    assert git(repository, "rev-parse", f"{tag_ref}^{{}}").strip() == expected.commit, (
        "release tag peeled target mismatch"
    )
    assert git(repository, "rev-parse", f"{expected.commit}^{{tree}}").strip() == (
        expected.tree
    ), "release tree mismatch"
    assert git(
        repository, "rev-list", "--parents", "-n", "1", expected.commit
    ).split() == [expected.commit, expected.parent], "release sole parent mismatch"
    assert git(repository, "show", "-s", "--format=%s", expected.commit).strip() == (
        expected.subject
    ), "release subject mismatch"
    changes = frozenset(git(
        repository, "diff", "--name-only", "--no-renames",
        expected.parent, expected.commit,
    ).splitlines())
    assert changes == expected.changed_paths, "release changed-file scope mismatch"
    assert not any(path.startswith(("ops_sim/", "examples/")) for path in changes), (
        "release must have zero production/example changes"
    )
    ancestry = subprocess.run(
        ["git", "--no-optional-locks", "merge-base", "--is-ancestor",
         expected.commit, "HEAD"],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if ancestry.returncode != 1:
        ancestry.check_returncode()
    assert ancestry.returncode == 0, "HEAD must equal or descend from the release"
