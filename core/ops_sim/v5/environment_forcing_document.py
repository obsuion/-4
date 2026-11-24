"""Strict bounded input-only forcing documents; loading never evaluates B38."""
from dataclasses import fields
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

from . import orbit_sun_zonotope_local_v2_document as source_doc
from .environment_forcing import (EnvironmentForcingRequest, ForcingPolicy,
    ForcingProfileEntry, NodeForcing, LOAD_FIELDS, _type, _text)
from .ids import ThermalNodeId
from .power_loads import PowerLoadBreakdown

FORMAT = "M2_ENVIRONMENT_FORCING_REQUEST"
VERSION = 1
MAX_TEXT_BYTES = 8 * 2**20


def _object(v, names):
    if type(v) is not dict or set(v) != set(names):
        raise ValueError("exact input object fields required: " + ",".join(names))
    return v


def _pair(v):
    if type(v) is not list or len(v) != 2 or any(type(x) is not str or not x.isascii() for x in v):
        raise ValueError("fraction requires two canonical bounded integer strings")
    if any(len(x) > 32 or not x.isdecimal() or (len(x) > 1 and x[0] == "0") for x in v):
        raise ValueError("invalid rational encoding")
    a, b = (int(x) for x in v)
    if b == 0:
        raise ValueError("zero denominator")
    q = Fraction(a, b)
    if [str(q.numerator), str(q.denominator)] != v:
        raise ValueError("noncanonical rational encoding")
    from .integration_time import RationalSeconds
    RationalSeconds.from_fraction(q)
    return q


def _q(v):
    return [str(v.numerator), str(v.denominator)]


def _inputs(request):
    _type(request, EnvironmentForcingRequest, "request")
    # Construct a fresh input-only validation copy, not a result.
    r = EnvironmentForcingRequest(request.source_request, request.start_seconds,
        request.end_seconds, request.node_ids, request.profile, request.policy)
    return dict(source_request=json.loads(source_doc.zonotope_local_request_to_json_v2(r.source_request)),
        source_request_digest=source_doc.zonotope_local_request_digest_v2(r.source_request),
        start_seconds=_q(r.start_seconds), end_seconds=_q(r.end_seconds),
        node_ids=[n.value for n in r.node_ids],
        policy={f.name: getattr(r.policy, f.name) for f in fields(ForcingPolicy)},
        profile=[dict(start_seconds=_q(e.start_seconds), end_seconds=_q(e.end_seconds),
            incidence_angle_deg=e.incidence_angle_deg,
            loads={n: getattr(e.loads, n) for n in LOAD_FIELDS},
            nodes=[{f.name: (n.node_id.value if f.name == "node_id" else list(n.sink_includes)
                    if f.name == "sink_includes" else getattr(n, f.name)) for f in fields(NodeForcing)} for n in e.nodes],
            non_overlap_assumption=e.non_overlap_assumption,
            internal_includes_eps_losses=e.internal_includes_eps_losses) for e in r.profile])


def _canonical(v):
    return json.dumps(v, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _digest(data):
    return sha256(_canonical(dict(domain="m2-environment-forcing-input-v1", version=1, inputs=data)).encode()).hexdigest()


def environment_forcing_digest(request):
    return _digest(_inputs(request))


def environment_forcing_to_json(request):
    data = _inputs(request)
    return _canonical(dict(format=FORMAT, version=VERSION, inputs=data, digest=_digest(data)))


def _bounded_tree(root):
    count = 0
    todo = [(root, 0)]
    while todo:
        v, depth = todo.pop()
        count += 1
        if count > 262144 or depth > 64:
            raise ValueError("bounded document tree exceeded")
        if type(v) is dict:
            if len(v) > 4096 or any(type(k) is not str or len(k) > 1024 for k in v):
                raise ValueError("bounded object exceeded")
            todo.extend((x, depth+1) for x in v.values())
        elif type(v) is list:
            if len(v) > 4096:
                raise ValueError("bounded list exceeded")
            todo.extend((x, depth+1) for x in v)
        elif type(v) is str:
            if len(v) > 16384:
                raise ValueError("bounded string exceeded")
        elif type(v) not in (int, float, bool, type(None)):
            raise ValueError("unsafe input scalar")


def _pairs(items):
    result = {}
    for k, v in items:
        if k in result:
            raise ValueError("duplicate JSON key")
        result[k] = v
    return result


def _hex_digest(v):
    if type(v) is not str or len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
        raise ValueError("canonical SHA256 required")
    return v


def environment_forcing_from_json(text, *, expected_digest=None):
    _type(text, str, "document text")
    if len(text) > MAX_TEXT_BYTES or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("document text budget exceeded")
    try:
        payload = json.loads(text, object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (RecursionError, UnicodeError, OverflowError) as e:
        raise ValueError("unsafe document representation") from e
    _bounded_tree(payload)
    p = _object(payload, ("format", "version", "inputs", "digest"))
    if type(p["format"]) is not str or p["format"] != FORMAT or type(p["version"]) is not int or p["version"] != VERSION:
        raise ValueError("unsupported document identity")
    d = _object(p["inputs"], ("source_request", "source_request_digest", "start_seconds",
                            "end_seconds", "node_ids", "profile", "policy"))
    policy_data = _object(d["policy"], tuple(f.name for f in fields(ForcingPolicy)))
    policy = ForcingPolicy(**policy_data)
    if type(d["node_ids"]) is not list or not 1 <= len(d["node_ids"]) <= 64:
        raise ValueError("node ID admission exceeded")
    for n in d["node_ids"]:
        _text(n, "node ID", 256)
    ids = tuple(ThermalNodeId(n) for n in d["node_ids"])
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate configured nodes")
    if type(d["profile"]) is not list or not 1 <= len(d["profile"]) <= policy.max_profile_entries:
        raise ValueError("profile count admission exceeded")
    a, b = _pair(d["start_seconds"]), _pair(d["end_seconds"])
    entries = []
    for raw in d["profile"]:
        e = _object(raw, ("start_seconds", "end_seconds", "incidence_angle_deg", "loads", "nodes",
                          "non_overlap_assumption", "internal_includes_eps_losses"))
        ld = _object(e["loads"], LOAD_FIELDS)
        if type(e["nodes"]) is not list or not 1 <= len(e["nodes"]) <= 64:
            raise ValueError("thermal node count admission exceeded")
        nodes = []
        for raw_node in e["nodes"]:
            n = _object(raw_node, tuple(f.name for f in fields(NodeForcing)))
            _text(n["node_id"], "node ID", 256)
            if type(n["sink_includes"]) is not list:
                raise ValueError("sink convention list required")
            nodes.append(NodeForcing(ThermalNodeId(n["node_id"]), n["sink_temperature_k"],
                n["internal_dissipation_w"], n["illuminated_solar_w"], n["absorbed_albedo_w"],
                n["absorbed_earth_ir_w"], tuple(n["sink_includes"])))
        entry = ForcingProfileEntry(_pair(e["start_seconds"]), _pair(e["end_seconds"]),
            e["incidence_angle_deg"], PowerLoadBreakdown(**ld), tuple(nodes), e["non_overlap_assumption"],
            e["internal_includes_eps_losses"])
        if {n.node_id for n in entry.nodes} != set(ids):
            raise ValueError("missing/foreign profile nodes")
        entries.append(entry)
    if a > b or any(x.end_seconds != y.start_seconds for x, y in zip(entries, entries[1:])) or not entries[0].start_seconds <= a <= b <= entries[-1].end_seconds:
        raise ValueError("invalid complete input coverage")
    # Admit nested wire fields before allowing its input-only physical decoder.
    nested = _object(d["source_request"], ("format", "version", "canonical_version", "inputs", "digest"))
    if type(nested["format"]) is not str or nested["format"] != source_doc.FORMAT or type(nested["version"]) is not int or nested["version"] != 2 or type(nested["canonical_version"]) is not int or nested["canonical_version"] != 1:
        raise ValueError("unsupported nested source document")
    source_doc._admit(nested["inputs"])
    if _hex_digest(d["source_request_digest"]) != _hex_digest(nested["digest"]):
        raise ValueError("nested request binding mismatch")
    digest = _digest(d)
    if _hex_digest(p["digest"]) != digest or (expected_digest is not None and _hex_digest(expected_digest) != digest):
        raise ValueError("forcing input digest mismatch")
    source = source_doc.zonotope_local_request_from_json_v2(_canonical(nested),
        expected_digest=d["source_request_digest"])
    result = EnvironmentForcingRequest(source, a, b, ids, tuple(entries), policy)
    if _inputs(result) != d:
        raise ValueError("noncanonical forcing inputs")
    return result


def save_environment_forcing(path, request):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(environment_forcing_to_json(request)+"\n")


def load_environment_forcing(path, *, expected_digest=None):
    p = Path(path)
    if p.stat().st_size > MAX_TEXT_BYTES:
        raise ValueError("document file budget exceeded")
    return environment_forcing_from_json(p.read_text(encoding="utf-8"), expected_digest=expected_digest)
