"""Pure DATA derivation of the actual M8 project-owner source identity.

The engine's store source_identity is NOT source_manifest_sha256. This is the
declared design_repair.source_identity + spacecraft_project asset-hash protocol;
no engine modules or scientific constructors are imported.
"""
from pathlib import PurePosixPath

from .data import digest, identity
from .errors import Refusal


def project_owner_source(manifest, *, fixture=False):
    if fixture:
        return identity(dict(label="PROTOCOL_FIXTURE_NO_SCIENCE", owner_source=manifest))
    names = sorted(name for name in manifest if name.startswith(("ops_sim/", "examples/"))
                   and name.endswith(".py") and "__pycache__" not in PurePosixPath(name).parts
                   and PurePosixPath(name).name != "scenario_inputs.py")
    if not 1 <= len(names) <= 1024:
        raise Refusal("M8_OWNER_SOURCE_POPULATION")
    base = digest("\n".join(name + ":" + manifest[name]["sha256"] for name in names).encode("utf-8"))
    prefix = "ops_sim/v5/workbench_assets/"
    assets = sorted(name for name in manifest if name.startswith(prefix) and "/" not in name[len(prefix):])
    body = base + "\n" + "\n".join(PurePosixPath(name).name + ":" + manifest[name]["sha256"] for name in assets)
    return digest(body.encode("utf-8"))

