"""Strict input-only bounded-window documents; canonical registration unchanged."""
from pathlib import Path

from .experiment_codec import (
    CANONICAL_VERSION, canonical_content, content_digest, decode_content,
    json_text, object_fields, parse_json,
)
from .orbit_config import _exact
from .orbit_sun_windows import IlluminationSearchPolicy, IlluminationWindowRequest, _request
from .sun_table_document import _read_table, _table_map


FORMAT = "M2_ILLUMINATION_WINDOW_REQUEST"
DOMAIN = "m2-illumination-window-request-v1"
VERSION = 1
POLICY_FIELDS = (
    "max_trials", "max_integration_steps", "max_geometry_cells",
    "max_retained_evidence_units", "max_arithmetic_operations",
)
INPUT_FIELDS = ("coast", "table", "start", "end", "requested_resolution_seconds", "policy")


def _input_map(request):
    q = _request(request)
    return {
        "coast": q.coast, "table": _table_map(q.table), "start": q.start,
        "end": q.end, "requested_resolution_seconds": q.requested_resolution_seconds,
        "policy": {name: getattr(q.policy, name) for name in POLICY_FIELDS},
    }


def _digest(value):
    _exact(value, str, "digest")
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("digest requires lowercase SHA-256")
    return value


def window_request_digest(request):
    return content_digest(DOMAIN, _input_map(request))


def window_request_to_json(request):
    data = _input_map(request)
    return json_text({
        "format": FORMAT, "version": VERSION, "canonical_version": CANONICAL_VERSION,
        "inputs": canonical_content(data), "digest": content_digest(DOMAIN, data),
    })


def window_request_from_json(text, *, expected_digest=None):
    p = object_fields(parse_json(text), ("format", "version", "canonical_version", "inputs", "digest"))
    if type(p["format"]) is not str or p["format"] != FORMAT:
        raise ValueError("unsupported illumination window format")
    if (type(p["version"]) is not int or p["version"] != VERSION or
            type(p["canonical_version"]) is not int or p["canonical_version"] != CANONICAL_VERSION):
        raise ValueError("unsupported illumination window version")
    data = object_fields(decode_content(p["inputs"]), INPUT_FIELDS)
    policy = IlluminationSearchPolicy(**object_fields(data["policy"], POLICY_FIELDS))
    request = IlluminationWindowRequest(
        data["coast"], _read_table(data["table"]), data["start"], data["end"],
        data["requested_resolution_seconds"], policy,
    )
    checked = _input_map(request)
    if canonical_content(checked) != p["inputs"]:
        raise ValueError("noncanonical window input normalization")
    digest = content_digest(DOMAIN, checked)
    if _digest(p["digest"]) != digest:
        raise ValueError("window document digest mismatch")
    if expected_digest is not None and _digest(expected_digest) != digest:
        raise ValueError("expected window digest mismatch")
    return request


def save_window_request(path, request):
    text = window_request_to_json(request)
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text+"\n")


def load_window_request(path, *, expected_digest=None):
    return window_request_from_json(Path(path).read_text(encoding="utf-8"), expected_digest=expected_digest)


__all__ = [
    "window_request_digest", "window_request_to_json", "window_request_from_json",
    "save_window_request", "load_window_request",
]
