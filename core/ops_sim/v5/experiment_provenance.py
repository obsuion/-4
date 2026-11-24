"""Local source-content and environment evidence, separate from physical inputs."""

import hashlib
from importlib import metadata
from pathlib import Path
import platform
import re
import subprocess
import sys

from .experiment_codec import content_digest, object_fields


PROVENANCE_VERSION = 1


def _git_pathnames(output: bytes) -> set[str]:
    """Decode Git -z output without quoting or newline/whitespace conversion."""
    if not output:
        return set()
    if not output.endswith(b"\0"):
        raise ValueError("Git pathname output must end with NUL")
    paths = output[:-1].split(b"\0")
    if any(not path for path in paths):
        raise ValueError("Git pathname output contains an empty pathname")
    return {path.decode("utf-8") for path in paths}


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid SHA-256 text")


def compatibility_digest(provenance):
    return content_digest("v5-code-environment-v1", {
        "sources": provenance["source_sha256"], "environment": provenance["environment"],
    })


def validate_provenance(value):
    object_fields(value, ("version", "git_head", "git_dirty", "source_status",
                          "source_sha256", "environment", "compatibility_digest"))
    if type(value["version"]) is not int or value["version"] != PROVENANCE_VERSION:
        raise ValueError("unsupported provenance version")
    if type(value["git_head"]) is not str or re.fullmatch(r"[0-9a-f]{40}", value["git_head"]) is None:
        raise ValueError("invalid Git commit identity")
    if type(value["git_dirty"]) is not bool:
        raise TypeError("git_dirty must be explicit bool")
    sources, statuses = value["source_sha256"], value["source_status"]
    if type(sources) is not dict or type(statuses) is not dict or not sources or sources.keys() != statuses.keys():
        raise ValueError("incomplete source provenance")
    for path, digest in sources.items():
        if type(path) is not str or not path or "\\" in path or path.startswith("/") or ":" in path or ".." in path.split("/"):
            raise ValueError("source paths must be repository-relative")
        _sha(digest)
        if type(statuses[path]) is not str or statuses[path] not in ("clean", "modified", "untracked"):
            raise ValueError("invalid source status")
    if not value["git_dirty"] and any(s != "clean" for s in statuses.values()):
        raise ValueError("dirty/new sources cannot be represented as clean HEAD")
    env = object_fields(value["environment"], ("python", "implementation", "platform", "machine", "byteorder", "dependencies"))
    for key in ("python", "implementation", "platform", "machine", "byteorder"):
        if type(env[key]) is not str or not env[key]:
            raise ValueError("missing environment provenance")
    dependencies = env["dependencies"]
    if type(dependencies) is not dict:
        raise TypeError("dependencies must be an explicit mapping")
    if any(type(k) is not str or not k or type(v) is not str or not v for k, v in dependencies.items()):
        raise ValueError("invalid dependency versions")
    _sha(value["compatibility_digest"])
    if compatibility_digest(value) != value["compatibility_digest"]:
        raise ValueError("code/environment digest mismatch")


def capture_provenance(repository_root: Path):
    """Hash actual V5/example Python sources, including dirty and untracked files.

    Git status/HEAD are recorded, not substituted for content. Compatibility
    requires exact source bytes and reported runtime/dependency versions. It is
    deliberately conservative, not an equivalence claim across platforms.
    """
    root = Path(repository_root).resolve()
    if root != Path(__file__).resolve().parents[2]:
        raise ValueError("provenance root must own the executing V5 implementation")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args])

    candidates = list((root / "ops_sim/v5").rglob("*.py")) + list((root / "examples").rglob("*.py"))
    candidates += [p for p in (root / "ops_sim/__init__.py", root / "requirements.txt") if p.is_file()]
    sources = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(candidates)}
    tracked = _git_pathnames(git("ls-files", "-z"))
    modified = _git_pathnames(git("diff", "HEAD", "--name-only", "-z"))
    dependencies = {}
    for distribution in metadata.distributions():
        name = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
        if name in dependencies:
            raise ValueError("ambiguous duplicate installed dependency metadata")
        dependencies[name] = distribution.version
    result = {
        "version": PROVENANCE_VERSION,
        "git_head": git("rev-parse", "HEAD").decode("ascii").strip(),
        "git_dirty": bool(git("status", "--porcelain=v1", "--untracked-files=all")),
        "source_status": {p: "untracked" if p not in tracked else "modified" if p in modified else "clean" for p in sources},
        "source_sha256": sources,
        "environment": {"python": sys.version, "implementation": platform.python_implementation(),
                        "platform": platform.system(), "machine": platform.machine(),
                        "byteorder": sys.byteorder, "dependencies": dict(sorted(dependencies.items()))},
    }
    result["compatibility_digest"] = compatibility_digest(result)
    validate_provenance(result)
    return result


__all__ = ["capture_provenance"]
