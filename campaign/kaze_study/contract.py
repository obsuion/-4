"""Immutable, strict study specification. No shell commands in the wire format."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .catalogue import FIXTURE, load_catalogue
from .data import canonical, fields, identity, integer, parse, read_bytes, reference, relative, sha, slug, text
from .errors import Refusal
from .protocol import B65, family, typed_build
from .resources import admit_cost, admit_resources

SCHEMA = "KAZE_STUDY_V1"
BINDING = "KAZE_ENGINE_BINDING_V1"
BINDING_V2 = "KAZE_ENGINE_BINDING_V2"
PENDING = "ENGINE_COMPATIBILITY_PENDING_B64_FREEZE"
B63_SOURCE = "56056002787fedae0b05e448e9e99193427cefdb3e2297624399abaaaab3b246"
PROTOCOL = "SERVERCTL_B63_V2"


def acceptance_references(value):
    if value is None:
        return []
    if type(value) is dict and set(value) == {"path", "sha256", "bytes"}:
        return [value]
    fields(value, ("schema", "designs"), "per-design acceptance map")
    if value["schema"] != "KAZE_DESIGN_ACCEPTANCE_MAP_V1" or type(value["designs"]) is not dict or not 1 <= len(value["designs"]) <= 128:
        raise Refusal("DESIGN_ACCEPTANCE_MAP")
    for did in value["designs"]:
        slug(did)
    return list(value["designs"].values())


def design_acceptance(binding, design_id):
    value = binding["acceptance"]
    if value is None or set(value) == {"path", "sha256", "bytes"}:
        return value
    acceptance_references(value)
    if design_id not in value["designs"]:
        raise Refusal("MISSING_GENUINE_DESIGN_DOMAIN_ACCEPTANCE", design_id)
    return value["designs"][design_id]


def admit_binding(v, root, mode):
    names = {"schema", "revision", "freeze", "protocol", "source_manifest", "source_sha256",
               "runtime", "backend", "build", "capability_sha256", "acceptance", "repair_evidence"}
    fields(v, names | ({"core_handoff"} if type(v) is dict and v.get("schema") == BINDING_V2 else set()), "engine binding")
    if v["schema"] not in (BINDING, BINDING_V2):
        raise Refusal("ENGINE_PROTOCOL_VERSION")
    wire = family(v["protocol"])
    if (wire == B65) != (v["schema"] == BINDING_V2):
        raise Refusal("EXPLICIT_TYPED_BINDING_V2_REQUIRED")
    if mode == FIXTURE and wire == B65:
        raise Refusal("B65_IS_NOT_SYNTHETIC_FIXTURE")
    integer(v["revision"], "binding revision", 1, 2**31)
    sha(v["source_sha256"])
    _, raw = reference(root, v["source_manifest"])
    source = parse(raw)
    if type(source) is not dict or identity(source) != v["source_sha256"]:
        raise Refusal("ENGINE_MANIFEST_IDENTITY")
    if not 1 <= len(source) <= 2000:
        raise Refusal("ENGINE_MANIFEST_POPULATION")
    for name, entry in source.items():
        relative(name); fields(entry, ("bytes", "sha256"), "source entry")
        integer(entry["bytes"], "source bytes", 0, 16 * 2**20); sha(entry["sha256"])
    fields(v["runtime"], ("python", "platform", "executable", "interpreter_sha256", "requirements_sha256", "dependency_versions"), "runtime binding")
    text(v["runtime"]["python"], "python version"); text(v["runtime"]["platform"], "platform")
    text(v["runtime"]["executable"], "runtime executable"); sha(v["runtime"]["interpreter_sha256"])
    sha(v["runtime"]["requirements_sha256"])
    if type(v["runtime"]["dependency_versions"]) is not dict:
        raise Refusal("RUNTIME_DEPENDENCIES")
    for name, version in v["runtime"]["dependency_versions"].items():
        text(name); text(version)
    if v["backend"] not in ((B65.backend_method,) if wire == B65 else ("REFERENCE", "PREPARED_NATIVE", "PREPARED_PYTHON")):
        raise Refusal("BACKEND_SELECTION")
    if wire == B65:
        if v["build"] is None:
            raise Refusal("B65_NATIVE_BUILD_REQUIRED")
        receipt = parse(reference(root, v["build"], 65536)[1])
        typed_build(receipt, source, v["runtime"], sha(v["capability_sha256"]))
    elif v["backend"] == "PREPARED_NATIVE":
        if v["build"] is None:
            raise Refusal("NATIVE_BUILD_REQUIRED")
        _, build = reference(root, v["build"], 65536)
        receipt = fields(parse(build), ("format", "artifact", "runtime", "engine_source_sha256", "compiler", "capabilities", "capability_sha256"), "native build receipt")
        if receipt["format"] != "B63_NATIVE_BUILD_RECEIPT_V1":
            raise Refusal("BUILD_RECEIPT_FORMAT")
        # The actual owner uses this field for lifecycle_native.pyx, not for
        # the entire source-manifest identity. Bind both independently.
        if receipt["engine_source_sha256"] != source.get("ops_sim/v5/lifecycle_native.pyx", {}).get("sha256"):
            raise Refusal("BUILD_SOURCE_BINDING")
        artifact = fields(receipt["artifact"], ("path", "sha256", "bytes"), "native artifact")
        relative(artifact["path"]); sha(artifact["sha256"]); integer(artifact["bytes"], "artifact bytes", 1, 128 * 2**20)
        if source.get(artifact["path"]) != {k: artifact[k] for k in ("bytes", "sha256")}:
            raise Refusal("BUILD_ARTIFACT_MANIFEST_BINDING")
        build_runtime = fields(receipt["runtime"], ("implementation", "python", "cache_tag", "ext_suffix", "platform", "machine"), "build runtime")
        if build_runtime["python"] != v["runtime"]["python"] or build_runtime["platform"] != v["runtime"]["platform"]:
            raise Refusal("BUILD_RUNTIME_BINDING")
        if v["runtime"]["platform"].startswith("linux") and artifact["path"].endswith(".pyd"):
            raise Refusal("WINDOWS_PYD_IS_NOT_LINUX_NATIVE")
        if identity(receipt["capabilities"]) != sha(receipt["capability_sha256"]):
            raise Refusal("BUILD_CAPABILITY_CONTENT")
        if receipt.get("capability_sha256") != sha(v["capability_sha256"]):
            raise Refusal("BUILD_CAPABILITY_BINDING")
    elif v["build"] is not None or v["capability_sha256"] is not None:
        raise Refusal("NONNATIVE_BUILD_CLAIM")
    for ref in acceptance_references(v["acceptance"]):
        reference(root, ref)
    if v["repair_evidence"] is not None:
        reference(root, v["repair_evidence"])
    permitted = ("PROTOCOL_FIXTURE_NO_SCIENCE",) if mode == FIXTURE else (("PROVISIONAL_NO_DISPATCH", "FROZEN_B65") if wire == B65 else ("PENDING_B64_FREEZE", "FROZEN_B64"))
    if v["freeze"] not in permitted:
        raise Refusal("FREEZE_MODE")
    if v["freeze"] == "FROZEN_B64":
        if v["source_sha256"] == B63_SOURCE or v["repair_evidence"] is None:
            raise Refusal("B64_REPAIR_FREEZE_REQUIRED")
        handoff = fields(parse(reference(root, v["repair_evidence"])[1]),
            ("schema", "source_sha256", "runtime", "backend", "build_sha256", "protocol", "corrections", "evidence"), "CORE freeze handoff")
        expected_build = None if v["build"] is None else identity(parse(reference(root, v["build"])[1]))
        if (handoff["schema"] != "KAZE_B64_FREEZE_HANDOFF_V1" or handoff["source_sha256"] != v["source_sha256"] or
                handoff["runtime"] != v["runtime"] or handoff["backend"] != v["backend"] or
                handoff["build_sha256"] != expected_build or handoff["protocol"] != v["protocol"] or
                handoff["corrections"] != ["LIFETIME_V2_CALLER_ADMISSION", "TERMINAL_RESOURCE_RETIREMENT"]):
            raise Refusal("B64_FREEZE_HANDOFF_BINDING")
        if type(handoff["evidence"]) is not list or not 2 <= len(handoff["evidence"]) <= 16:
            raise Refusal("GENUINE_CORE_REPAIR_EVIDENCE_REFERENCES_REQUIRED")
        for item in handoff["evidence"]:
            reference(root, item)
    if v["freeze"] == "FROZEN_B65":
        if v["repair_evidence"] is None:
            raise Refusal("GENUINE_CORE_API_REQUIRED")
        api = parse(reference(root, v["repair_evidence"])[1])
        handoff = parse(reference(root, v["core_handoff"], 65536)[1])
        if (handoff.get("format") != "B65_CORE_HANDOFF_V2" or handoff.get("state") != "FROZEN_SOURCE_CONTRACT" or
                handoff.get("api", {}).get("sha256") != v["repair_evidence"]["sha256"]):
            raise Refusal("ACTUAL_CORE_HANDOFF_API_RAW_PIN")
        if (api.get("format") != "B65_CORE_API_CONTRACT_V1" or api.get("state") != "FROZEN" or
                api.get("source_identity") != v["source_sha256"] or api.get("source_files") != len(source) or
                api.get("backend") != B65.backend_method or api.get("runtime") != receipt["runtime"] or
                api.get("build", {}).get("sha256") != v["build"]["sha256"] or
                api["build"].get("artifact") != receipt["artifact"] or api["build"].get("profile") != receipt["profile"] or
                api.get("formats", {}).get("contract") != B65.contract or api["formats"].get("result") != B65.result or
                api["formats"].get("server_plan") != B65.plan):
            raise Refusal("B65_ACTUAL_CORE_HANDOFF_BINDING")
        integer(api["revision"], "CORE API revision", 3)
    elif wire == B65:
        reference(root, v["core_handoff"], 65536)
    return source


@dataclass(frozen=True)
class Study:
    raw: bytes
    spec_bytes: bytes
    manifest_sha256: str
    root: str
    catalogue: object
    source_bytes: bytes
    manifest_path: str = ""
    authority: object = None

    @property
    def spec(self):
        # Fresh DATA prevents callers mutating the admitted in-memory contract.
        return parse(self.spec_bytes)


def load_study(path, *, protocol_fixture=False,authority=None):
    from pathlib import Path
    p = Path(path).absolute()
    raw = read_bytes(p)
    return replace(admit_study(raw, p.parent, protocol_fixture=protocol_fixture,authority=authority), manifest_path=str(p))


def admit_study(raw, root, *, protocol_fixture=False,authority=None):
    if parse(raw).get('schema')=='KAZE_AUTHORED_PROJECT_YEAR_STUDY_V1':
        if protocol_fixture:raise Refusal('YEAR_AUTHORED_IS_NOT_PROTOCOL_FIXTURE')
        from .year_study import admit
        return admit(raw,root,authority)
    if parse(raw).get('schema')=='KAZE_NAMED_PROJECT_STUDY_V1':
        if protocol_fixture:raise Refusal('NAMED_PROJECT_IS_NOT_PROTOCOL_FIXTURE')
        from .named_execution import admit_study as named
        return named(raw,root,authority)
    v = fields(parse(raw), ("schema", "study_id", "mode", "binding", "catalogue", "policy",
        "horizon_seconds", "deadline", "concurrency", "resources", "cost", "objective",
        "failure_policy", "execution_mode"), "study")
    if v["schema"] != SCHEMA or v["mode"] not in ("PRODUCTION", FIXTURE):
        raise Refusal("STUDY_SCHEMA_OR_MODE")
    if (v["mode"] == FIXTURE) != protocol_fixture:
        raise Refusal("EXPLICIT_PROTOCOL_FIXTURE_OPT_IN_REQUIRED")
    slug(v["study_id"])
    integer(v["horizon_seconds"], "horizon", 1, 473364000)
    integer(v["concurrency"], "concurrency", 1, 2 if protocol_fixture else 128)
    try:
        deadline = datetime.fromisoformat(v["deadline"])
        if deadline.tzinfo is None:
            raise ValueError("offset required")
        deadline.astimezone(timezone.utc)
    except (TypeError, ValueError) as error:
        raise Refusal("DEADLINE_WITH_OFFSET", error) from error
    if v["failure_policy"] != "CONTINUE_INDEPENDENT":
        raise Refusal("FAILURE_POLICY")
    if v["execution_mode"] not in ("pilot", "long"):
        raise Refusal("EXECUTION_MODE")
    if v["execution_mode"] == "pilot" and v["horizon_seconds"] > 86400:
        raise Refusal("PILOT_HORIZON")
    admit_resources(v["resources"], v["concurrency"])
    admit_cost(v["cost"])
    if v["objective"] is not None:
        fields(v["objective"], ("metric", "direction"), "declared objective")
        if v["objective"]["metric"] not in ("credits", "useful_bits", "priority_score") or v["objective"]["direction"] not in ("max", "min"):
            raise Refusal("DECLARED_OBJECTIVE")
    source = admit_binding(v["binding"], root, v["mode"])
    _, catraw = reference(root, v["catalogue"])
    reference(root, v["policy"], 65536)
    catalogue = load_catalogue(catraw, root, mode=v["mode"],
        source_sha256=v["binding"]["source_sha256"], horizon_seconds=v["horizon_seconds"],
        build_sha256=None if v["binding"]["build"] is None else identity(parse(reference(root, v["binding"]["build"])[1])),authority=authority)
    if v["binding"]["protocol"] == B65.protocol and parse(catraw).get("schema") not in ("KAZE_COMPILED_PROJECT_MANIFEST_V2","KAZE_PROJECT_EXECUTION_CATALOGUE_V1"):
        raise Refusal("B65_REQUIRES_EXACT_COMPILED_PROJECT_MANIFEST")
    if v["execution_mode"] == "long" and v["binding"]["protocol"] == B65.protocol:
        # Source824 has the reviewed cross-domain/self-comparison admission bugs.
        # A future source must carry the corrected CORE acceptance API explicitly.
        api = {} if v["binding"]["repair_evidence"] is None else parse(reference(root, v["binding"]["repair_evidence"])[1])
        if api.get("source_identity") == "d90243c0725645237a60ab771b6c093de3af38fb08d815a10404adc7d72f8bb1" or api.get("per_domain_target_acceptance") != "CORRECTED_GENUINE_EVIDENCE_REQUIRED":
            raise Refusal("B66_CORRECTED_PER_DOMAIN_TARGET_ACCEPTANCE_PENDING")
    if v["execution_mode"] == "long" and v["binding"]["freeze"] in ("FROZEN_B64", "FROZEN_B65"):
        value = v["binding"]["acceptance"]
        if type(value) is not dict or value.get("schema") != "KAZE_DESIGN_ACCEPTANCE_MAP_V1" or set(value["designs"]) != {d.design_id for d in catalogue.designs}:
            raise Refusal("LONG_REQUIRES_EXACT_PER_DESIGN_DOMAIN_ACCEPTANCE_MAP")
    return Study(raw, canonical(v), identity(v), str(root), catalogue, canonical(source),authority=authority)

