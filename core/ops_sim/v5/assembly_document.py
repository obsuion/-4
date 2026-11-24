"""Self-contained assembly document v1, independent of simulator persistence.

Finite binary64 hex, strict JSON fields, sorted unordered records. See contract.
Only pure JSON helpers are reused from the accepted experiment codec; no M1
record enters its type allowlist and no experiment schema/version is changed.
"""

import hashlib
import hmac
from pathlib import Path

from .assembly import MassCoverage, MountPose, UniformCuboid, _real
from .assembly_choices import (
    AssemblyDesign, InstallationBox, InstallationRegion, PhysicalInstance,
    PlacementChoice, Selection, _copy,
)
from .experiment_codec import json_text, object_fields, parse_json


DOCUMENT_VERSION = 1
DOCUMENT_FORMAT = "M1_ASSEMBLY_DOCUMENT"
_DOMAIN = b"M1-ASSEMBLY-DOCUMENT\0v1\0"
_UNITS = {"mass": "kg", "length": "m", "inertia": "kg*m^2", "rotation": "dimensionless"}
_ROOT_FIELDS = ("format", "version", "units", "body_frame_id", "definitions", "instances",
                "choices", "selections", "allowed_regions", "reserved_regions", "clearance_m")


def _vector_json(value):
    return [x.hex() for x in value]


def _box_json(box):
    return None if box is None else {"lower_m": _vector_json(box.lower_m), "upper_m": _vector_json(box.upper_m)}


def _pose_json(pose):
    return {"mount_id": pose.mount_id, "choice_id": pose.choice_id,
            "body_frame_id": pose.body_frame_id, "local_frame_id": pose.local_frame_id,
            "origin_body_m": _vector_json(pose.origin_body_m),
            "rotation_body_from_local": [_vector_json(row) for row in pose.rotation_body_from_local],
            "occupied_slots": list(pose.occupied_slots)}


def _payload(design):
    design = _copy(design, AssemblyDesign)
    return {
        "format": DOCUMENT_FORMAT, "version": DOCUMENT_VERSION, "units": dict(_UNITS),
        "body_frame_id": design.body_frame_id, "clearance_m": design.clearance_m.hex(),
        "definitions": [{"definition_id": d.definition_id, "local_frame_id": d.local_frame_id,
            "mass_kg": d.mass_kg.hex(), "size_m": _vector_json(d.size_m),
            "center_local_m": _vector_json(d.center_local_m), "mass_distribution": d.mass_distribution}
            for d in design.definitions],
        "instances": [{"instance_id": i.instance_id, "definition_id": i.definition_id,
            "mass_coverage": None if i.mass_coverage is None else [list(p) for p in i.mass_coverage.paths]}
            for i in design.instances],
        "choices": [{"choice_id": c.choice_id, "definition_id": c.definition_id,
            "allowed_instance_ids": list(c.allowed_instance_ids), "pose": _pose_json(c.pose),
            "envelope": _box_json(c.envelope), "allowed_region_id": c.allowed_region_id,
            "exclusive": c.exclusive} for c in design.choices],
        "selections": [{"instance_id": s.instance_id, "choice_id": s.choice_id} for s in design.selections],
        "allowed_regions": [{"region_id": r.region_id, "box": _box_json(r.box)} for r in design.allowed_regions],
        "reserved_regions": [{"region_id": r.region_id, "box": _box_json(r.box)} for r in design.reserved_regions],
    }


def dumps_assembly_document(design: AssemblyDesign) -> str:
    """Canonical JSON text with no trailing newline or embedded derived values."""
    return json_text(_payload(design))


def assembly_document_digest(design: AssemblyDesign) -> str:
    return hashlib.sha256(_DOMAIN + dumps_assembly_document(design).encode("utf-8")).hexdigest()


def _array(value):
    if type(value) is not list:
        raise TypeError("document array must be a JSON list")
    return value


def _number(value):
    if type(value) is not str:
        raise TypeError("SI values require canonical binary64 hex strings")
    try:
        number = _real(float.fromhex(value), "document number")
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid finite binary64 hex string") from exc
    if number.hex() != value:
        raise ValueError("noncanonical binary64 hex string")
    return number


def _vector(value):
    return tuple(_number(x) for x in _array(value))


def _box(value):
    data = object_fields(value, ("lower_m", "upper_m"))
    return InstallationBox(_vector(data["lower_m"]), _vector(data["upper_m"]))


def _pose(value):
    data = object_fields(value, ("mount_id", "choice_id", "body_frame_id", "local_frame_id",
        "origin_body_m", "rotation_body_from_local", "occupied_slots"))
    return MountPose(data["mount_id"], data["choice_id"], data["body_frame_id"], data["local_frame_id"],
        _vector(data["origin_body_m"]), tuple(_vector(row) for row in _array(data["rotation_body_from_local"])),
        tuple(_array(data["occupied_slots"])))


def _definition(value):
    data = object_fields(value, ("definition_id", "local_frame_id", "mass_kg", "size_m",
                                 "center_local_m", "mass_distribution"))
    return UniformCuboid(data["definition_id"], data["local_frame_id"], _number(data["mass_kg"]),
                         _vector(data["size_m"]), _vector(data["center_local_m"]), data["mass_distribution"])


def _instance(value):
    data = object_fields(value, ("instance_id", "definition_id", "mass_coverage"))
    coverage = data["mass_coverage"]
    if coverage is not None:
        coverage = MassCoverage(tuple(tuple(_array(path)) for path in _array(coverage)))
    return PhysicalInstance(data["instance_id"], data["definition_id"], coverage)


def _choice(value):
    data = object_fields(value, ("choice_id", "definition_id", "allowed_instance_ids", "pose",
                                 "envelope", "allowed_region_id", "exclusive"))
    return PlacementChoice(data["choice_id"], data["definition_id"], tuple(_array(data["allowed_instance_ids"])),
        _pose(data["pose"]), None if data["envelope"] is None else _box(data["envelope"]),
        data["allowed_region_id"], data["exclusive"])


def _selection(value):
    data = object_fields(value, ("instance_id", "choice_id"))
    return Selection(data["instance_id"], data["choice_id"])


def _region(value):
    data = object_fields(value, ("region_id", "box"))
    return InstallationRegion(data["region_id"], _box(data["box"]))


def loads_assembly_document(text: str, *, expected_digest: str | None = None) -> AssemblyDesign:
    """Rebuild every authority from strict JSON, optionally bind to a trusted digest."""
    data = object_fields(parse_json(text), _ROOT_FIELDS)
    if type(data["version"]) is not int:
        raise TypeError("assembly document version must be a built-in integer")
    if data["version"] != DOCUMENT_VERSION or data["format"] != DOCUMENT_FORMAT:
        raise ValueError("unsupported assembly document format/version")
    units = object_fields(data["units"], _UNITS)
    if units != _UNITS:
        raise ValueError("unsupported assembly document units")
    design = AssemblyDesign(data["body_frame_id"],
        tuple(_definition(v) for v in _array(data["definitions"])),
        tuple(_instance(v) for v in _array(data["instances"])),
        tuple(_choice(v) for v in _array(data["choices"])),
        tuple(_selection(v) for v in _array(data["selections"])),
        tuple(_region(v) for v in _array(data["allowed_regions"])),
        tuple(_region(v) for v in _array(data["reserved_regions"])), _number(data["clearance_m"]))
    if expected_digest is not None:
        if (type(expected_digest) is not str or len(expected_digest) != 64
                or any(c not in "0123456789abcdef" for c in expected_digest)):
            raise ValueError("expected_digest must be a lowercase SHA-256 hex string")
        if not hmac.compare_digest(assembly_document_digest(design), expected_digest):
            raise ValueError("assembly document digest mismatch")
    return design


def save_assembly_document(design: AssemblyDesign, path: str | Path) -> None:
    """Exclusive creation; never silently replace an existing document."""
    encoded = dumps_assembly_document(design).encode("utf-8")
    with Path(path).open("xb") as handle:
        handle.write(encoded)


def load_assembly_document(path: str | Path, *, expected_digest: str | None = None) -> AssemblyDesign:
    return loads_assembly_document(Path(path).read_bytes().decode("utf-8", errors="strict"),
                                   expected_digest=expected_digest)
