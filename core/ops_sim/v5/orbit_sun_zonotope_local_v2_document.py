"""Strict decomposed input document; unsafe records refused before any decode.

Only safe registered input types appear. No registry or scientific owner changes.
"""
from pathlib import Path

from . import experiment_codec as _codec
from . import orbit_j2 as _coast
from . import orbit_j2_zonotope as _z
from . import orbit_j2_zonotope_segments_document as _sd
from .orbit_config import _exact
from .orbit_j2_zonotope_segments import J2ZonotopeSegmentRequest
from .orbit_sun_zonotope_local_v2 import (API_ID, LIMITS,
    ZonotopeLocalIlluminationPolicyV2, ZonotopeLocalIlluminationRequestV2, _request)
from .orbit_sun_zonotope_intervals import MAX_INPUT_NODES, _bounded_input
from .sun_table_document import _read_table, _table_map, TABLE_FIELDS, PROVENANCE_FIELDS

FORMAT = "M2_ZONOTOPE_LOCAL_ILLUMINATION_V2_REQUEST"
DOMAIN = "m2-zonotope-local-illumination-request-v2"
VERSION = 2
_IDENTITIES = dict(api_id=API_ID, api_version=2, resource_policy_version=2,
                   geometry_resource_policy_version=2)
_NAMES = (*_IDENTITIES, "segment", "table", "requested_resolution_seconds", "policy")
_POLICY_NAMES = (*LIMITS, "resource_policy_version")


def _input_map(request):
    q = _request(request)
    return dict(_IDENTITIES, segment=_sd._input_data(q.segment), table=_table_map(q.table),
                requested_resolution_seconds=q.requested_resolution_seconds,
                policy={n:getattr(q.policy,n) for n in _POLICY_NAMES})


def _safe_tree(node):
    """Validate EVERY nested schema/enum/primitive before constructor dispatch."""
    _bounded_input(node)
    remaining = MAX_INPUT_NODES
    def visit(v, depth):
        nonlocal remaining
        if depth > 64 or remaining <= 0:
            raise ValueError("bounded document tree exceeded")
        remaining -= 1
        _exact(v, dict, "typed input node")
        _exact(v.get("kind"), str, "typed kind")
        kind = v["kind"]
        if kind == "record":
            _codec.object_fields(v, ("kind", "type", "fields"))
            _exact(v["type"], str, "record type")
            if v["type"] not in _sd._SAFE_RECORDS:
                raise ValueError("unsafe or derived input record")
            owner = _codec._RECORDS[v["type"]]
            _codec.object_fields(v["fields"], _codec.RECORD_FIELDS[owner])
            for x in v["fields"].values():
                visit(x, depth+1)
        elif kind == "enum":
            _codec.object_fields(v, ("kind", "type", "member"))
            _exact(v["type"], str, "enum type")
            if v["type"] not in _sd._SAFE_ENUMS:
                raise ValueError("unsafe enum")
            _exact(v["member"], str, "enum member")
            if v["member"] not in _codec._ENUMS[v["type"]].__members__:
                raise ValueError("unknown enum member")
        elif kind in ("tuple", "list", "map"):
            _codec.object_fields(v, ("kind", "items"))
            _exact(v["items"], list, "typed items")
            if len(v["items"]) > 4096:
                raise ValueError("bounded document container exceeded")
            keys = []
            for x in v["items"]:
                if kind == "map":
                    _exact(x, list, "map pair")
                    if len(x) != 2:
                        raise ValueError("map pair required")
                    _exact(x[0], str, "map key")
                    keys.append(x[0]); x = x[1]
                visit(x, depth+1)
            if kind == "map" and (keys != sorted(keys) or len(set(keys)) != len(keys)):
                raise ValueError("noncanonical/duplicate map keys")
        elif kind in ("none", "bool", "str", "int", "float", "fraction"):
            # Primitive-only decoder cannot construct a physical owner.
            _codec._decode(v)
        else:
            raise ValueError("unsupported typed input")
    visit(node, 0)


def _wire_map(node, names):
    if node["kind"] != "map":
        raise ValueError("input mapping required")
    return _codec.object_fields(dict(node["items"]), names)


def _wire_id(data, expected):
    for n, value in expected.items():
        if data[n] != _codec.canonical_content(value):
            raise ValueError("unsupported input identity: " + n)


def _admit(node):
    _safe_tree(node)
    root = _wire_map(node, _NAMES)
    _wire_id(root, _IDENTITIES)
    segment = _wire_map(root["segment"], _sd._INPUT_NAMES)
    _wire_id(segment, _sd._IDENTITIES)
    policy = _wire_map(segment["policy"], _sd._POLICY_NAMES)
    _wire_id(policy, _sd._POLICY_IDENTITIES)
    geometry = _wire_map(root["policy"], _POLICY_NAMES)
    _wire_id(geometry, dict(resource_policy_version=2))
    # New budgets and resolution are complete schemas, not merely safe values.
    # Primitive-only decoding cannot construct physical owners. Reject their
    # wrong kinds/ranges BEFORE the general record decoder is allowed to run.
    budget_values = {}
    for name in LIMITS:
        if geometry[name]["kind"] != "int":
            raise ValueError("integer budget input required: "+name)
        budget_values[name] = _codec._decode(geometry[name])
    ZonotopeLocalIlluminationPolicyV2(**budget_values)
    if root["requested_resolution_seconds"]["kind"] != "float":
        raise ValueError("float resolution input required")
    resolution = _codec._decode(root["requested_resolution_seconds"])
    if not 0 < resolution <= 86400:
        raise ValueError("positive resolution <=86400 seconds required")
    table = _wire_map(root["table"], TABLE_FIELDS)
    _wire_map(table["provenance"], PROVENANCE_FIELDS)
    if table["samples"]["kind"] != "tuple" or not 2 <= len(table["samples"]["items"]) <= 1024:
        raise ValueError("2..1024 typed Sun nodes required")
    for sample in table["samples"]["items"]:
        _wire_map(sample, ("elapsed_seconds", "position_m"))


def zonotope_local_request_digest_v2(request):
    return _codec.content_digest(DOMAIN, _input_map(request))


def zonotope_local_request_to_json_v2(request):
    data = _input_map(request)
    return _codec.json_text(dict(format=FORMAT, version=VERSION,
        canonical_version=1, inputs=_codec.canonical_content(data),
        digest=_codec.content_digest(DOMAIN, data)))


def zonotope_local_request_from_json_v2(text, *, expected_digest=None):
    _exact(text, str, "document text")
    if len(text) > 4 * 2**20:
        raise ValueError("bounded document text exceeded")
    payload = _codec.object_fields(_codec.parse_json(text),
        ("format", "version", "canonical_version", "inputs", "digest"))
    _sd._identities(payload, dict(format=FORMAT, version=2, canonical_version=1))
    _admit(payload["inputs"])
    data = _codec.object_fields(_codec.decode_content(payload["inputs"]), _NAMES)
    d = _codec.object_fields(data["segment"], _sd._INPUT_NAMES)
    p = _codec.object_fields(d["policy"], _sd._POLICY_NAMES)
    state, model = _coast._authorities(d["initial_state"], d["gravity_model"])
    trajectory = object.__new__(_coast.J2CartesianTrajectory)
    object.__setattr__(trajectory, "initial_state", state)
    object.__setattr__(trajectory, "gravity_model", model)
    segment = J2ZonotopeSegmentRequest(trajectory, d["end"],
        _z.J2ZonotopePolicyV3(p["base_policy"], p["scale_exponents"], p["max_scalar_operations"]))
    g = _codec.object_fields(data["policy"], _POLICY_NAMES)
    request = ZonotopeLocalIlluminationRequestV2(segment, _read_table(data["table"]),
        data["requested_resolution_seconds"], ZonotopeLocalIlluminationPolicyV2(**{n:g[n] for n in LIMITS}))
    checked = _input_map(request)
    if _codec.canonical_content(checked) != payload["inputs"]:
        raise ValueError("noncanonical input normalization")
    digest = _codec.content_digest(DOMAIN, checked)
    if _sd._digest(payload["digest"]) != digest:
        raise ValueError("document digest mismatch")
    if expected_digest is not None and _sd._digest(expected_digest) != digest:
        raise ValueError("expected input digest mismatch")
    return request


def save_zonotope_local_request_v2(path, request):
    text = zonotope_local_request_to_json_v2(request)
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text+"\n")


def load_zonotope_local_request_v2(path, *, expected_digest=None):
    return zonotope_local_request_from_json_v2(Path(path).read_text(encoding="utf-8"),
                                               expected_digest=expected_digest)


__all__ = ["zonotope_local_request_digest_v2", "zonotope_local_request_to_json_v2",
           "zonotope_local_request_from_json_v2", "save_zonotope_local_request_v2",
           "load_zonotope_local_request_v2"]
