"""Strict input-only interval illumination documents; codec registration unchanged."""
from pathlib import Path

from .experiment_codec import (CANONICAL_VERSION, canonical_content, content_digest,
                               decode_content, json_text, object_fields, parse_json)
from .orbit_config import _exact
from .orbit_sun_intervals import IntervalIlluminationPolicy, IntervalIlluminationRequest, _request
from .sun_table_document import _read_table, _table_map


FORMAT = "M2_INTERVAL_ILLUMINATION_REQUEST"
DOMAIN = "m2-interval-illumination-request-v1"
VERSION = 1


def _input_map(request):
    q = _request(request)
    return {"coast": q.coast, "table": _table_map(q.table), "start": q.start,
            "end": q.end, "policy": {"max_cells": q.policy.max_cells}}


def _digest(value):
    _exact(value, str, "digest")
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("digest requires lowercase SHA-256")
    return value


def interval_request_digest(request):
    return content_digest(DOMAIN, _input_map(request))


def interval_request_to_json(request):
    data = _input_map(request)
    return json_text({"format": FORMAT, "version": VERSION, "canonical_version": CANONICAL_VERSION,
                      "inputs": canonical_content(data), "digest": content_digest(DOMAIN, data)})


def interval_request_from_json(text, *, expected_digest=None):
    p = object_fields(parse_json(text), ("format", "version", "canonical_version", "inputs", "digest"))
    if type(p["format"]) is not str or p["format"] != FORMAT:
        raise ValueError("unsupported interval illumination format")
    if (type(p["version"]) is not int or p["version"] != VERSION or
            type(p["canonical_version"]) is not int or p["canonical_version"] != CANONICAL_VERSION):
        raise ValueError("unsupported interval illumination version")
    data = object_fields(decode_content(p["inputs"]), ("coast", "table", "start", "end", "policy"))
    policy = IntervalIlluminationPolicy(**object_fields(data["policy"], ("max_cells",)))
    request = IntervalIlluminationRequest(data["coast"], _read_table(data["table"]),
                                          data["start"], data["end"], policy)
    checked = _input_map(request)
    if canonical_content(checked) != p["inputs"]:
        raise ValueError("noncanonical interval input normalization")
    digest = content_digest(DOMAIN, checked)
    if _digest(p["digest"]) != digest:
        raise ValueError("interval document digest mismatch")
    if expected_digest is not None and _digest(expected_digest) != digest:
        raise ValueError("expected interval digest mismatch")
    return request


def save_interval_request(path, request):
    text = interval_request_to_json(request)
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text+"\n")


def load_interval_request(path, *, expected_digest=None):
    return interval_request_from_json(Path(path).read_text(encoding="utf-8"), expected_digest=expected_digest)


__all__ = ["interval_request_digest", "interval_request_to_json", "interval_request_from_json",
           "save_interval_request", "load_interval_request"]
