"""Strict input-only document for the separate v3 continuous segment owner.

No registry changes. Only safe, existing immutable authority records are decoded;
full trajectories/coast bundles/results are rejected BEFORE any constructor.
"""
from pathlib import Path

from .experiment_codec import (CANONICAL_VERSION, canonical_content, content_digest,
                               decode_content, json_text, object_fields, parse_json)
from .orbit_config import _exact
from . import orbit_j2 as _coast
from . import orbit_j2_zonotope as _z
from .orbit_j2_zonotope_segments import (J2ZonotopeSegmentRequest, _request,
                                       SEGMENT_API_ID, SEGMENT_API_VERSION,
                                       PUBLICATION_VERSION)

SEGMENT_DOCUMENT_VERSION = 1
SEGMENT_DOCUMENT_FORMAT = "M2_J2_ZONOTOPE_SEGMENT_REQUEST"
SEGMENT_DIGEST_DOMAIN = "m2-j2-zonotope-segment-request-v1"
_SAFE_RECORDS = frozenset("ops_sim.v5." + n for n in (
    "ids.ParameterId", "ids.SourceRecordId", "parameters.ScalarParameter",
    "provenance.ParameterProvenance", "provenance.SensitivityRange",
    "orbit_config.TTEpoch", "orbit_config.GeometryInstant",
    "orbit_config.FrameDefinition", "orbit_config.ReferenceEllipsoid",
    "orbit_config.UniformRotationDefinition", "frames.CartesianPosition",
    "frames.CartesianVelocity", "frames.CartesianState",
    "orbit_j2_gravity.J2GravityModel", "orbit_j2_enclosure.J2EnclosurePolicy"))
_SAFE_ENUMS = frozenset("ops_sim.v5." + n for n in (
    "orbit_config.FrameKind", "provenance.ProvenanceClass", "provenance.ProvenanceStatus"))
_IDENTITIES = dict(api_id=SEGMENT_API_ID, api_version=SEGMENT_API_VERSION,
                   publication_version=PUBLICATION_VERSION,
                   transport_resource_policy_version=3, method_id=_z.METHOD_ID,
                   method_version=1, kernel_id="incremental-j2-jet-v1")
_POLICY_IDENTITIES = dict(method_id=_z.METHOD_ID, method_version=1,
                          resource_policy_version=3, kernel_id="incremental-j2-jet-v1",
                          pb_order=6, max_generators=12, retained_generators=6, rank_bit_cap=4096)
_INPUT_NAMES = (*_IDENTITIES, "initial_state", "gravity_model", "end", "policy")
_POLICY_NAMES = ("base_policy", "scale_exponents", "max_scalar_operations", *_POLICY_IDENTITIES)


def _identities(data, expected):
    for name, value in expected.items():
        _exact(data[name], type(value), name)
        if data[name] != value:
            raise ValueError("unsupported segment input identity: " + name)


def _safe_tree(node):
    _exact(node, dict, "typed input node")
    _exact(node.get("kind"), str, "typed kind")
    kind = node["kind"]
    if kind == "record":
        object_fields(node, ("kind", "type", "fields"))
        _exact(node["type"], str, "record type")
        if node["type"] not in _SAFE_RECORDS:
            raise ValueError("non-input or unsafe authority record")
        _exact(node["fields"], dict, "record fields")
        for value in node["fields"].values():
            _safe_tree(value)
    elif kind == "enum":
        object_fields(node, ("kind", "type", "member"))
        _exact(node["type"], str, "enum type")
        if node["type"] not in _SAFE_ENUMS:
            raise ValueError("unsupported input enum")
    elif kind in ("tuple", "list", "map"):
        object_fields(node, ("kind", "items"))
        _exact(node["items"], list, "typed items")
        for value in node["items"]:
            if kind == "map":
                _exact(value, list, "map pair")
                if len(value) != 2:
                    raise ValueError("map pair required")
                _exact(value[0], str, "map key")
                value = value[1]
            _safe_tree(value)
    elif kind not in ("none", "bool", "str", "int", "float", "fraction"):
        raise ValueError("unsupported primitive input")


def _input_data(request):
    req = _request(request)
    data = dict(_IDENTITIES, initial_state=req.trajectory.initial_state,
                gravity_model=req.trajectory.gravity_model, end=req.end,
                policy=dict(_POLICY_IDENTITIES, base_policy=req.policy.base_policy,
                            scale_exponents=req.policy.scale_exponents,
                            max_scalar_operations=req.policy.max_scalar_operations))
    # Revalidate canonical originals BEFORE normalization could hide corruption.
    canonical_content(data)
    _coast._authorities(data["initial_state"], data["gravity_model"])
    return data


def _digest(value):
    _exact(value, str, "digest")
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("64 lowercase hexadecimal digest required")
    return value


def zonotope_segment_request_digest(request):
    return content_digest(SEGMENT_DIGEST_DOMAIN, _input_data(request))


def zonotope_segment_request_to_json(request):
    data = _input_data(request)
    return json_text(dict(format=SEGMENT_DOCUMENT_FORMAT, version=SEGMENT_DOCUMENT_VERSION,
                          canonical_version=CANONICAL_VERSION, inputs=canonical_content(data),
                          digest=content_digest(SEGMENT_DIGEST_DOMAIN, data)))


def zonotope_segment_request_from_json(text, *, expected_digest=None):
    payload = object_fields(parse_json(text), ("format", "version", "canonical_version", "inputs", "digest"))
    _identities(payload, dict(format=SEGMENT_DOCUMENT_FORMAT, version=SEGMENT_DOCUMENT_VERSION,
                              canonical_version=CANONICAL_VERSION))
    _safe_tree(payload["inputs"])
    data = object_fields(decode_content(payload["inputs"]), _INPUT_NAMES)
    _identities(data, _IDENTITIES)
    p = object_fields(data["policy"], _POLICY_NAMES)
    _identities(p, _POLICY_IDENTITIES)
    state, model = _coast._authorities(data["initial_state"], data["gravity_model"])
    trajectory = object.__new__(_coast.J2CartesianTrajectory)
    object.__setattr__(trajectory, "initial_state", state)
    object.__setattr__(trajectory, "gravity_model", model)
    policy = _z.J2ZonotopePolicyV3(p["base_policy"], p["scale_exponents"], p["max_scalar_operations"])
    req = J2ZonotopeSegmentRequest(trajectory, data["end"], policy)
    checked = _input_data(req)
    if canonical_content(checked) != payload["inputs"]:
        raise ValueError("noncanonical segment normalization")
    digest = content_digest(SEGMENT_DIGEST_DOMAIN, checked)
    if _digest(payload["digest"]) != digest:
        raise ValueError("segment input digest mismatch")
    if expected_digest is not None and _digest(expected_digest) != digest:
        raise ValueError("expected segment digest mismatch")
    return req


def save_zonotope_segment_request(path, request):
    text = zonotope_segment_request_to_json(request)
    with Path(path).open("x", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")


def load_zonotope_segment_request(path, *, expected_digest=None):
    return zonotope_segment_request_from_json(Path(path).read_text(encoding="utf-8"),
                                             expected_digest=expected_digest)


__all__ = ["zonotope_segment_request_digest", "zonotope_segment_request_to_json",
           "zonotope_segment_request_from_json", "save_zonotope_segment_request",
           "load_zonotope_segment_request"]
