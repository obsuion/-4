"""Strict adapters around canonical codec v1; no new registered record types."""
from pathlib import Path

from .experiment_codec import (
    CANONICAL_VERSION, canonical_content, content_digest, decode_content,
    json_text, object_fields, parse_json,
)
from .orbit_config import _exact
from .sun_table import SunPositionSample, SunPositionTable, SunTableProvenance, TableOrbitSunQuery, _table, _hash

PROVENANCE_FIELDS = (
    "source_kind", "target", "center", "axes", "reference_plane", "correction",
    "source_timescale", "source_units", "conversion", "alignment", "source_ids",
    "source_uri", "retrieved_utc", "request_sha256", "response_sha256", "ephemeris_id",
    "accuracy_policy", "accuracy_statement", "alignment_rationale",
)
TABLE_FIELDS = ("epoch", "frame", "domain_seconds", "interpolation", "samples", "provenance")


def _table_map(table):
    table = _table(table)
    return {"epoch": table.epoch, "frame": table.frame, "domain_seconds": table.domain_seconds,
            "interpolation": table.interpolation,
            "samples": tuple({"elapsed_seconds": x.elapsed_seconds, "position_m": x.position_m} for x in table.samples),
            "provenance": {k: getattr(table.provenance, k) for k in PROVENANCE_FIELDS}}


def _read_table(data):
    p = object_fields(data, TABLE_FIELDS)
    _exact(p["samples"], tuple, "samples")
    samples = []
    for s in p["samples"]:
        object_fields(s, ("elapsed_seconds", "position_m"))
        samples.append(SunPositionSample(**s))
    provenance = SunTableProvenance(**object_fields(p["provenance"], PROVENANCE_FIELDS))
    return SunPositionTable(p["epoch"], p["frame"], p["domain_seconds"],
                            p["interpolation"], tuple(samples), provenance)


def _query_map(query):
    _exact(query, TableOrbitSunQuery, "query")
    q = TableOrbitSunQuery(query.coast, query.table, query.instant)
    return {"coast": q.coast, "table": _table_map(q.table), "instant": q.instant}


def table_digest(table):
    return content_digest("m2-sun-table-v1", _table_map(table))


def table_query_digest(query):
    return content_digest("m2-table-orbit-query-v1", _query_map(query))


def _save_payload(fmt, domain, data):
    return json_text({"format": fmt, "version": 1, "canonical_version": CANONICAL_VERSION,
                      "inputs": canonical_content(data), "digest": content_digest(domain, data)})


def table_to_json(table):
    return _save_payload("M2_SUN_POSITION_TABLE", "m2-sun-table-v1", _table_map(table))


def table_query_to_json(query):
    return _save_payload("M2_TABLE_ORBIT_QUERY", "m2-table-orbit-query-v1", _query_map(query))


def _read_payload(text, fmt, domain, reader, writer, expected_digest):
    p = object_fields(parse_json(text), ("format", "version", "canonical_version", "inputs", "digest"))
    if type(p["format"]) is not str or p["format"] != fmt:
        raise ValueError("unsupported document format")
    if (type(p["version"]) is not int or p["version"] != 1 or
            type(p["canonical_version"]) is not int or p["canonical_version"] != CANONICAL_VERSION):
        raise ValueError("unsupported document version")
    value = reader(decode_content(p["inputs"]))
    data = writer(value)
    if canonical_content(data) != p["inputs"]:
        raise ValueError("noncanonical input normalization")
    digest = content_digest(domain, data)
    if _hash(p["digest"]) != digest:
        raise ValueError("document digest mismatch")
    if expected_digest is not None and _hash(expected_digest) != digest:
        raise ValueError("expected digest mismatch")
    return value


def table_from_json(text, *, expected_digest=None):
    return _read_payload(text, "M2_SUN_POSITION_TABLE", "m2-sun-table-v1",
                         _read_table, _table_map, expected_digest)


def _read_query(data):
    p = object_fields(data, ("coast", "table", "instant"))
    return TableOrbitSunQuery(p["coast"], _read_table(p["table"]), p["instant"])


def table_query_from_json(text, *, expected_digest=None):
    return _read_payload(text, "M2_TABLE_ORBIT_QUERY", "m2-table-orbit-query-v1",
                         _read_query, _query_map, expected_digest)


def save_table(path, table):
    _save(path, table_to_json(table))


def save_table_query(path, query):
    _save(path, table_query_to_json(query))


def _save(path, text):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text+"\n")


def load_table(path, *, expected_digest=None):
    return table_from_json(Path(path).read_text(encoding="utf-8"), expected_digest=expected_digest)


def load_table_query(path, *, expected_digest=None):
    return table_query_from_json(Path(path).read_text(encoding="utf-8"), expected_digest=expected_digest)
