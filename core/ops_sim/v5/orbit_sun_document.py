"""Strict portable input adapter; no derived result or new codec registration."""
from pathlib import Path

from .experiment_codec import (
    CANONICAL_VERSION, canonical_content, content_digest, decode_content,
    json_text, object_fields, parse_json,
)
from .frames import CartesianDirection
from .orbit_config import _exact
from .orbit_sun import OrbitSunQuery, SuppliedSunDirection

FORMAT = "M2_ORBIT_SUN_QUERY"
VERSION = 1
DOMAIN = "m2-orbit-sun-query-v1"


def _inputs(query):
    _exact(query, OrbitSunQuery, "query")
    q = OrbitSunQuery(query.coast, query.instant, query.sun)
    sun = q.sun
    return {"coast": q.coast, "instant": q.instant, "sun": {
        "direction": {"frame": sun.direction.frame, "instant": sun.direction.instant,
                      "components": sun.direction.components},
        "origin": sun.origin, "source_ids": sun.source_ids, "rationale": sun.rationale}}


def query_digest(query):
    return content_digest(DOMAIN, _inputs(query))


def query_to_json(query):
    payload = _inputs(query)
    return json_text({"format": FORMAT, "version": VERSION,
                      "canonical_version": CANONICAL_VERSION,
                      "inputs": canonical_content(payload),
                      "digest": content_digest(DOMAIN, payload)})


def _digest(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("expected lowercase SHA-256 digest")
    return value


def query_from_json(text, *, expected_digest=None):
    p = object_fields(parse_json(text), ("format", "version", "canonical_version", "inputs", "digest"))
    if type(p["format"]) is not str or p["format"] != FORMAT:
        raise ValueError("unsupported query format")
    for key, version in (("version", VERSION), ("canonical_version", CANONICAL_VERSION)):
        if type(p[key]) is not int or p[key] != version:
            raise ValueError("unsupported "+key)
    payload = decode_content(p["inputs"])
    p0 = object_fields(payload, ("coast", "instant", "sun"))
    sun = object_fields(p0["sun"], ("direction", "origin", "source_ids", "rationale"))
    d = object_fields(sun["direction"], ("frame", "instant", "components"))
    q = OrbitSunQuery(p0["coast"], p0["instant"], SuppliedSunDirection(
        CartesianDirection(d["frame"], d["instant"], d["components"]),
        sun["origin"], sun["source_ids"], sun["rationale"]))
    # Reject wire data normalized by a constructor, rather than accepting drift.
    if canonical_content(_inputs(q)) != p["inputs"]:
        raise ValueError("noncanonical query input")
    digest = query_digest(q)
    if _digest(p["digest"]) != digest:
        raise ValueError("query digest mismatch")
    if expected_digest is not None and _digest(expected_digest) != digest:
        raise ValueError("expected query digest mismatch")
    return q


def save_query(path, query):
    text = query_to_json(query)
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text+"\n")


def load_query(path, *, expected_digest=None):
    return query_from_json(Path(path).read_text(encoding="utf-8"), expected_digest=expected_digest)
