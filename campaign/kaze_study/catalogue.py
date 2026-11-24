"""Data-only admission of explicitly supplied canonical initial roots.

This reader does not construct scientific inputs. The engine remains the owner
of physical admission. Every unapproved input field is compared, not only a
hand-picked scenario summary.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .data import canonical, digest, fields, identity, integer, parse, reference, sha, slug, text
from .errors import Refusal

FORMAT = "KAZE_DESIGN_CATALOGUE_V1"
PROJECT_FORMAT = "KAZE_COMPILED_PROJECT_MANIFEST_V2"
FIXTURE = "PROTOCOL_FIXTURE_NO_SCIENCE"
ROOT_FORMAT = "B61_EXPLICIT_ENVIRONMENT_AGEING_INPUT_V7"
ROLLING = "/inputs/base/inputs/reference/inputs/fields"
MODEL = ROLLING + "/model/fields"
SIMULATION = MODEL + "/simulation_inputs/immutable_input/typed/fields"
# Protect actual V7 common owners, not every component field called "policy"
# or "limits". Physical component DTOs and derived initial energies can vary.
COMMON_OWNERS = ("/inputs/policy", "/inputs/scenario", "/inputs/output_policy", "/inputs/environment_ageing_policy",
    "/inputs/energy_attitude_policy", "/inputs/service_policy", "/inputs/reduced_sun_policy",
    "/inputs/base/inputs/controller_method", "/inputs/base/inputs/estimation",
    *(ROLLING + "/" + name for name in ("policy", "contacts", "requests", "quotas", "knowledge_mode", "initial_quaternion")),
    *(MODEL + "/" + name for name in ("environment", "geometry_policy", "construction_limits", "limits", "nominal_policy", "protection", "routing", "sampling")),
    *(SIMULATION + "/" + name for name in ("common_world", "environment_config", "flight_rules_config", "numerical_config", "scenario_config", "coast_orbit")))


def pointer(path):
    text(path, "JSON pointer", 2048)
    if not path.startswith("/inputs/") or "~" in path or "//" in path:
        raise Refusal("INPUT_POINTER", path)
    parts = path[1:].split("/")
    if any(x in ("", ".", "..") for x in parts):
        raise Refusal("INPUT_POINTER", path)
    return parts


def get_pointer(value, path):
    for part in pointer(path):
        try:
            value = value[int(part)] if type(value) is list and part.isdecimal() else value[part]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise Refusal("MISSING_INPUT_POINTER", path) from error
    return value


def project(document, paths):
    result = deepcopy({k: document[k] for k in ("format", "version", "inputs")})
    for path in paths:
        parts = pointer(path)
        parent = result
        for part in parts[:-1]:
            parent = parent[int(part)] if type(parent) is list else parent[part]
        key = int(parts[-1]) if type(parent) is list else parts[-1]
        parent[key] = {"KAZE_APPROVED_DESIGN_SLOT": path}
    return result


def normalize_documents(value):
    """Validate nested canonical envelopes before removing derived digests."""
    if type(value) is list:
        return [normalize_documents(x) for x in value]
    if type(value) is not dict:
        return value
    out = dict(value)
    if set(out) == {"format", "version", "inputs", "digest"}:
        if out["digest"] != identity({k: out[k] for k in ("format", "version", "inputs")}):
            raise Refusal("NESTED_CANONICAL_DOCUMENT_DIGEST")
        del out["digest"]
    return {k: normalize_documents(x) for k, x in out.items()}


@dataclass(frozen=True)
class Design:
    design_id: str
    root_identity: str
    original_sha256: str
    input_path: str
    input_bytes: bytes
    assumptions_bytes: bytes
    mass_bytes: bytes
    provenance_bytes: bytes = b"{}"

    @property
    def pins(self):
        value = parse(self.provenance_bytes)
        return value or dict(initial_root_identity=self.root_identity, input_sha256=self.original_sha256)

    @property
    def assumptions(self):
        return parse(self.assumptions_bytes)

    @property
    def mass(self):
        return parse(self.mass_bytes)


@dataclass(frozen=True)
class Catalogue:
    designs: tuple[Design, ...]
    common_sha256: str
    source_sha256: str
    original_bytes: bytes
    anchor_seconds: int
    bucket_seconds: int


def load_catalogue(raw, root, *, mode, source_sha256, horizon_seconds, build_sha256=None,authority=None):
    v = parse(raw)
    from .projects import EXECUTION,load_execution_catalogue
    if v.get('schema')==EXECUTION:
        return load_execution_catalogue(raw,root,mode=mode,source_sha256=source_sha256,
            horizon_seconds=horizon_seconds,build_sha256=build_sha256,authority=authority)
    modern = v.get("schema") == PROJECT_FORMAT
    names = {"schema", "label", "engine_source_sha256", "baseline_design",
        "allowed_design_paths", "common_paths", "common_projection_sha256",
        "original_anchor_seconds", "bucket_seconds", "designs"}
    fields(v, names | ({"finite_policy"} if modern else set()), "catalogue")
    if v["schema"] not in (FORMAT, PROJECT_FORMAT) or v["label"] != mode:
        raise Refusal("CATALOGUE_MODE_OR_SCHEMA")
    if sha(v["engine_source_sha256"]) != source_sha256:
        raise Refusal("CATALOGUE_SOURCE_BINDING")
    integer(v["original_anchor_seconds"], "original anchor")
    integer(v["bucket_seconds"], "fixed bucket", 1, 31557600)
    allowed = v["allowed_design_paths"]
    if type(allowed) is not list or not 1 <= len(allowed) <= 256 or len(set(allowed)) != len(allowed):
        raise Refusal("ALLOWED_DESIGN_PATHS")
    fields(v["common_paths"], ("world", "scenario", "controller", "numerical") if modern else ("world", "scenario", "controller"), "common paths")
    common = []
    for group in v["common_paths"].values():
        if type(group) is not list or not 1 <= len(group) <= 128:
            raise Refusal("COMMON_PATHS")
        common.extend(group)
    for path in allowed + common:
        pointer(path)
    for a in allowed:
        # Policy/controller/world masks cannot hide a changed common scenario.
        if any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for b in common):
            raise Refusal("DESIGN_COMMON_PATH_OVERLAP", a)
        if any(a != b and (a.startswith(b + "/") or b.startswith(a + "/")) for b in allowed):
            raise Refusal("OVERLAPPING_DESIGN_MASKS")
        if mode != FIXTURE and a.split("/")[2] in ("scenario", "policy", "output_policy", "service_policy",
                "energy_attitude_policy", "environment_ageing_policy", "duration_seconds", "method", "sun_mode"):
            raise Refusal("COMMON_CONTROLLER_MASK_FORBIDDEN", a)
    records = v["designs"]
    maximum = 128
    total_cap = 64 * 2**20
    if modern:
        policy = fields(v["finite_policy"], ("maximum_cases", "maximum_total_input_bytes"), "finite project population")
        maximum = integer(policy["maximum_cases"], "maximum cases", 1, 128)
        total_cap = integer(policy["maximum_total_input_bytes"], "total input bytes", 1, 64 * 2**20)
    if type(records) is not list or not 1 <= len(records) <= maximum:
        raise Refusal("SUPPLIED_CANONICAL_ROOT_COUNT")
    designs = []
    seen_ids, seen_roots, seen_paths, seen_hashes = set(), set(), set(), set()
    expected_projection = None
    total_bytes = 0; seen_projects = set()
    for record in records:
        fields(record, {"design_id", "root_identity", "input", "assumptions", "mass"} | ({"project"} if modern else set()), "design")
        did = slug(record["design_id"])
        rid = sha(record["root_identity"])
        path, data = reference(root, record["input"], 8 * 2**20)
        total_bytes += len(data)
        if total_bytes > total_cap:
            raise Refusal("BOUNDED_MANIFEST_TOTAL_INPUT_BYTES")
        path_key = str(path.resolve()).casefold()
        if did in seen_ids or rid in seen_roots or path_key in seen_paths or digest(data) in seen_hashes:
            raise Refusal("DUPLICATE_DESIGN_INPUT_OR_ROOT", did)
        seen_ids.add(did); seen_roots.add(rid); seen_paths.add(path_key); seen_hashes.add(digest(data))
        document = fields(parse(data), ("format", "version", "inputs", "digest"), "canonical initial root")
        if data != canonical(document):
            raise Refusal("NONCANONICAL_INITIAL_INPUT", did)
        if document["format"] != ("KAZE_SYNTHETIC_INITIAL_V1" if mode == FIXTURE else ROOT_FORMAT):
            raise Refusal("INITIAL_INPUT_FORMAT")
        integer(document["version"], "input version", 1, 7)
        if document["version"] != (1 if mode == FIXTURE else 7):
            raise Refusal("INITIAL_INPUT_VERSION")
        if sha(document["digest"]) != identity({k: document[k] for k in ("format", "version", "inputs")}):
            raise Refusal("INPUT_DOCUMENT_DIGEST")
        integer(document["inputs"].get("duration_seconds"), "root duration", 1, 473364000)
        if document["inputs"]["duration_seconds"] != horizon_seconds:
            raise Refusal("CATALOGUE_HORIZON_MISMATCH")
        for path_name in common + allowed:
            get_pointer(document, path_name)
        if not modern and any(type(get_pointer(document, path_name)) in (dict, list) for path_name in allowed):
            raise Refusal("DESIGN_MASK_MUST_BE_SCALAR_LEAF")
        normalized = normalize_documents(document) if modern else document
        if modern:
            protected = {"world", "common_world", "scenario", "controller", "controller_method", "numerical_config",
                "controller_id", "world_id", "environment_id", "scenario_id", "flight_rules_id", "numerical_config_id",
                "environment_config", "flight_rules_config", "scenario_config", "ground_knowledge", "mission", "inertial_frame"}
            def hidden(value):
                if type(value) is dict:
                    return bool(set(value) & protected) or any(hidden(x) for x in value.values())
                return type(value) is list and any(hidden(x) for x in value)
            for name in allowed:
                if (any(name == owner or name.startswith(owner + "/") or owner.startswith(name + "/") for owner in COMMON_OWNERS) or
                        set(pointer(name)) & protected or hidden(get_pointer(document, name))):
                    raise Refusal("DESIGN_MASK_HIDES_COMMON_OR_NUMERICAL_OWNER", name)
        projected = canonical(project(normalized, allowed))
        if expected_projection is None:
            expected_projection = projected
        if projected != expected_projection:
            raise Refusal("HIDDEN_COMMON_WORLD_SCENARIO_CONTROLLER_DIFFERENCE", did)
        assumptions = record["assumptions"]
        if type(assumptions) is not list or not assumptions or len(assumptions) > 256:
            raise Refusal("ASSUMPTION_PROVENANCE_REQUIRED")
        for assumption in assumptions:
            fields(assumption, ("name", "value", "units", "source", "consumer", "status"), "assumption")
            for key in ("name", "units", "source", "consumer", "status"):
                text(assumption[key], key)
            if assumption["status"] not in ("ASSUMED", "SYNTHETIC_ACCELERATED_ASSUMED", "MEASURED", "SUPPLIED"):
                raise Refusal("ASSUMPTION_STATUS")
        fields(record["mass"], ("value_kg", "status", "source"), "mass assumption")
        text(record["mass"]["status"], "mass status"); text(record["mass"]["source"], "mass source")
        from .resources import decimal
        decimal(record["mass"]["value_kg"], "mass kg", zero=True)
        pins = {}
        if modern:
            provenance = fields(record["project"], ("project_identity", "spec", "compiler", "common_scenario_sha256", "engine_source_sha256", "build_sha256"), "compiled project provenance")
            _, specraw = reference(root, provenance["spec"], 2 * 2**20)
            _, compilerraw = reference(root, provenance["compiler"], 2 * 2**20)
            specdata = parse(specraw); compiler = parse(compilerraw)
            if sha(provenance["project_identity"]) != identity(specdata):
                raise Refusal("EXACT_PROJECT_SPEC_IDENTITY")
            fields(compiler, ("schema", "name", "version", "source_manifest", "source_sha256"), "compiler identity")
            if compiler["schema"] != "KAZE_COMPILER_IDENTITY_V1" or identity(compiler["source_manifest"]) != sha(compiler["source_sha256"]):
                raise Refusal("EXACT_COMPILER_SOURCE_IDENTITY")
            text(compiler["name"]); text(compiler["version"])
            if not 1 <= len(compiler["source_manifest"]) <= 2000:
                raise Refusal("COMPILER_SOURCE_POPULATION")
            from .data import relative
            for name, item in compiler["source_manifest"].items():
                relative(name); fields(item, ("bytes", "sha256"), "compiler source member")
                integer(item["bytes"], "compiler source bytes", 0, 16 * 2**20); sha(item["sha256"])
            if (provenance["common_scenario_sha256"] != v["common_projection_sha256"] or
                    provenance["engine_source_sha256"] != source_sha256 or provenance["build_sha256"] != build_sha256):
                raise Refusal("EXACT_CASE_COMMON_SOURCE_BUILD_IDENTITY")
            pins = dict(project_identity=provenance["project_identity"], spec_sha256=digest(specraw),
                compiler_sha256=digest(compilerraw), compiler_source_sha256=compiler["source_sha256"],
                initial_root_identity=rid, input_sha256=digest(data), common_scenario_sha256=v["common_projection_sha256"],
                engine_source_sha256=source_sha256, build_sha256=build_sha256)
            if pins["project_identity"] in seen_projects:
                raise Refusal("SAME_PROJECT_UNDER_NEW_CASE_LABEL")
            seen_projects.add(pins["project_identity"])
        designs.append(Design(did, rid, digest(data), str(path), data,
                              canonical(assumptions), canonical(record["mass"]), canonical(pins)))
    if slug(v["baseline_design"]) not in seen_ids:
        raise Refusal("BASELINE_DESIGN_MISSING")
    if digest(expected_projection) != sha(v["common_projection_sha256"]):
        raise Refusal("COMMON_PROJECTION_DIGEST")
    return Catalogue(tuple(designs), v["common_projection_sha256"], source_sha256,
                     raw, v["original_anchor_seconds"], v["bucket_seconds"])

