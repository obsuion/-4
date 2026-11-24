"""Strict input authority, portable exact evidence, and offline reconstruction."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
import subprocess
import sys

import pytest

from examples.v5_j2_enclosure_pilot import inputs as synthetic_trajectory
from ops_sim.v5.experiment_codec import (
    CANONICAL_VERSION, canonical_content, content_digest, json_text,
)
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.orbit_j2 import J2RK4SolverConfig
from ops_sim.v5.orbit_j2_binding import J2CoastOrbitInputs
from ops_sim.v5.orbit_j2_enclosure import J2EnclosurePolicy
from ops_sim.v5.orbit_j2_segments import J2SegmentRequest, evaluate_j2_segments
from ops_sim.v5.orbit_j2_segments_document import (
    SEGMENT_DIGEST_DOMAIN, segment_request_digest, segment_request_to_json,
    segment_request_from_json, save_segment_request, load_segment_request,
)


def request(kind="forward"):
    trajectory = synthetic_trajectory(True)
    coast = J2CoastOrbitInputs(trajectory, J2RK4SolverConfig(1 / 32, 32),
                              J2EnclosurePolicy(1 / 32, 32, .5, 50, 12))
    intervals = {"forward": (128 + 1 / 64, 128 + 1 / 16),
                 "backward": (128 - 1 / 16, 128 - 1 / 64),
                 "crossing": (128 - 1 / 32, 128 + 1 / 32),
                 "unresolved": (128., 128 + 1 / 16)}
    start, end = intervals[kind]
    if kind == "unresolved":
        coast = replace(coast, enclosure_policy=replace(coast.enclosure_policy, max_steps=1))
    epoch = trajectory.initial_state.position.instant.epoch
    return J2SegmentRequest(coast, GeometryInstant(epoch, start), GeometryInstant(epoch, end))


def wire_map(document):
    return dict(document["inputs"]["items"])


def redigest_wire(document):
    # Deliberately does not invoke canonical_content: a malicious sender can
    # calculate SHA-256 for malformed payloads, which the reader must reject.
    document["digest"] = hashlib.sha256(json_text({
        "domain": SEGMENT_DIGEST_DOMAIN, "canonical_version": CANONICAL_VERSION,
        "content": document["inputs"],
    }).encode("utf-8")).hexdigest()
    return json.dumps(document)


def evidence(result):
    # Decimal strings preserve every bound digit (and exponent); Fraction
    # numerator/denominator preserve the exact clipped and source boundaries.
    def time(t):
        return [t.numerator, t.denominator]

    cells = None if result.cells is None else [{
        "start": time(c.start_seconds), "end": time(c.end_seconds),
        "source_initial": time(c.source_initial_seconds),
        "source_final": time(c.source_final_seconds),
        "position": [[str(lo), str(hi)] for lo, hi in c.position_bounds_m],
        "velocity": [[str(lo), str(hi)] for lo, hi in c.velocity_bounds_m_per_s],
    } for c in result.cells]
    return {"request": segment_request_to_json(result.request),
            "status": result.status, "reason": result.reason, "cells": cells,
            "planned_steps": result.planned_steps,
            "enclosure_steps": result.enclosure_steps,
            "picard_attempts": result.picard_attempts, "nominal_steps": result.nominal_steps}


@pytest.mark.parametrize("kind", ["forward", "backward", "crossing", "unresolved"])
def test_input_roundtrip_and_exclusive_file_creation(kind, tmp_path):
    q = request(kind)
    text = segment_request_to_json(q)
    digest = segment_request_digest(q)
    assert segment_request_from_json(text, expected_digest=digest) == q
    p = tmp_path / "request.json"
    save_segment_request(p, q)
    original = p.read_bytes()
    assert original == (text + "\n").encode("utf-8")
    assert load_segment_request(p, expected_digest=digest) == q
    with pytest.raises(FileExistsError):
        save_segment_request(p, request())
    assert p.read_bytes() == original
    result = evaluate_j2_segments(q)
    assert result.status == ("unresolved" if kind == "unresolved" else "enclosed")
    assert result.nominal_steps == 0
    assert evidence(evaluate_j2_segments(load_segment_request(p))) == evidence(result)


@pytest.mark.parametrize("field,value", [
    ("version", True), ("version", 1.), ("version", 2), ("version", "1"),
    ("canonical_version", True), ("canonical_version", 2),
    ("format", "M2_SUN_POSITION_TABLE"), ("format", None),
    ("digest", "0" * 64), ("digest", "F" * 64), ("digest", None),
    ("digest", "a" * 63), ("digest", "a" * 65), ("digest", ["a"] * 64),
    ("derived_cells", []), ("nominal_state", {}),
])
def test_strict_envelope(field, value):
    document = json.loads(segment_request_to_json(request()))
    document[field] = value
    with pytest.raises((TypeError, ValueError)):
        segment_request_from_json(json.dumps(document))


@pytest.mark.parametrize("field", ["format", "version", "canonical_version", "inputs", "digest"])
def test_missing_envelope_field(field):
    document = json.loads(segment_request_to_json(request()))
    del document[field]
    with pytest.raises(ValueError, match="fields"):
        segment_request_from_json(json.dumps(document))


@pytest.mark.parametrize("field", ["coast", "start", "end"])
def test_missing_request_field_even_with_matching_digest(field):
    document = json.loads(segment_request_to_json(request()))
    document["inputs"]["items"] = [p for p in document["inputs"]["items"] if p[0] != field]
    with pytest.raises(ValueError, match="fields"):
        segment_request_from_json(redigest_wire(document))


@pytest.mark.parametrize("field", ["cells", "cached_state", "derived_endpoint", "nominal_state"])
def test_derived_outputs_cannot_be_added_as_authority(field):
    document = json.loads(segment_request_to_json(request()))
    document["inputs"]["items"].append([field, canonical_content(())])
    document["inputs"]["items"].sort(key=lambda item: item[0])
    with pytest.raises(ValueError, match="fields"):
        segment_request_from_json(redigest_wire(document))


@pytest.mark.parametrize("mutation", [
    "reversed", "equal", "epoch", "bool-time", "int-normalization",
    "negative-zero-normalization", "wrong-coast", "coast-version", "unknown-policy",
    "noncanonical-order", "duplicate-map-key", "extra-instant-field",
])
def test_redigested_malformed_inputs_fail(mutation):
    document = json.loads(segment_request_to_json(request()))
    data = wire_map(document)
    start, end, coast = data["start"]["fields"], data["end"]["fields"], data["coast"]["fields"]
    if mutation == "reversed":
        start["elapsed_seconds"], end["elapsed_seconds"] = end["elapsed_seconds"], start["elapsed_seconds"]
    elif mutation == "equal":
        end["elapsed_seconds"] = deepcopy(start["elapsed_seconds"])
    elif mutation == "epoch":
        end["epoch"]["fields"]["julian_day"] = canonical_content(2451546)
    elif mutation == "bool-time":
        start["elapsed_seconds"] = canonical_content(True)
    elif mutation == "int-normalization":
        start["elapsed_seconds"] = canonical_content(128)
    elif mutation == "negative-zero-normalization":
        start["elapsed_seconds"] = canonical_content(-0.)
    elif mutation == "wrong-coast":
        data["coast"].clear()
        data["coast"].update(canonical_content({}))
    elif mutation == "coast-version":
        coast["policy_version"] = canonical_content(2)
    elif mutation == "unknown-policy":
        coast["enclosure_policy"]["fields"]["cached_error_bound"] = canonical_content(0.)
    elif mutation == "noncanonical-order":
        document["inputs"]["items"].reverse()
    elif mutation == "duplicate-map-key":
        document["inputs"]["items"].insert(0, deepcopy(document["inputs"]["items"][0]))
    else:
        start["units"] = canonical_content("seconds")
    with pytest.raises((TypeError, ValueError)):
        segment_request_from_json(redigest_wire(document))


def test_duplicate_json_fields_and_nonfinite_constants_rejected():
    valid = segment_request_to_json(request())
    with pytest.raises(ValueError, match="duplicate"):
        segment_request_from_json('{"format":"wrong",' + valid[1:])
    with pytest.raises(ValueError, match="non-finite"):
        segment_request_from_json('{"inputs":NaN}')


@pytest.mark.parametrize("expected", ["0" * 64, "F" * 64, "bad", True])
def test_expected_digest_is_strict(expected):
    with pytest.raises((TypeError, ValueError)):
        segment_request_from_json(segment_request_to_json(request()), expected_digest=expected)


@pytest.mark.parametrize("field", ["start", "end", "anchor", "nominal", "enclosure", "gravity"])
def test_content_identity_binds_complete_original_authority(field):
    q = request()
    if field in ("start", "end"):
        old = getattr(q, field)
        changed = replace(q, **{field: replace(old, elapsed_seconds=old.elapsed_seconds + 1 / 256)})
    elif field == "nominal":
        changed = replace(q, coast=replace(q.coast, solver_config=replace(q.coast.solver_config, max_steps=31)))
    elif field == "enclosure":
        changed = replace(q, coast=replace(q.coast, enclosure_policy=replace(q.coast.enclosure_policy, max_steps=31)))
    elif field == "anchor":
        state = q.coast.trajectory.initial_state
        instant = replace(state.position.instant, elapsed_seconds=127.)
        state = replace(state, position=replace(state.position, instant=instant),
                        velocity=replace(state.velocity, instant=instant))
        changed = replace(q, coast=replace(q.coast, trajectory=replace(q.coast.trajectory, initial_state=state)))
    else:
        model = q.coast.trajectory.gravity_model
        model = replace(model, j2=replace(model.j2, value=model.j2.value / 2))
        changed = replace(q, coast=replace(q.coast, trajectory=replace(q.coast.trajectory, gravity_model=model)))
    assert segment_request_digest(q) != segment_request_digest(changed)
    with pytest.raises(ValueError, match="expected"):
        segment_request_from_json(segment_request_to_json(changed), expected_digest=segment_request_digest(q))


def test_domain_separation_and_no_new_codec_registration():
    q = request()
    data = {"coast": q.coast, "start": q.start, "end": q.end}
    assert segment_request_digest(q) != content_digest("m2-table-orbit-query-v1", data)
    with pytest.raises(TypeError, match="unsupported canonical type"):
        canonical_content(q)
    assert "ops_sim.v5.scenario_inputs" not in sys.modules


@pytest.mark.parametrize("target", ["request", "instant", "coast", "policy"])
def test_serializing_forged_objects_rebuilds_authorities(target):
    q = deepcopy(request())
    if target == "request":
        object.__setattr__(q, "end", q.start)
    elif target == "instant":
        object.__setattr__(q.start, "elapsed_seconds", True)
    elif target == "coast":
        object.__setattr__(q.coast, "policy_version", True)
    else:
        object.__setattr__(q.coast.enclosure_policy, "max_steps", True)
    for writer in (segment_request_digest, segment_request_to_json):
        with pytest.raises((TypeError, ValueError)):
            writer(q)


@pytest.mark.parametrize("kind", ["forward", "backward", "crossing", "unresolved"])
def test_fresh_process_offline_full_cell_reconstruction(kind, tmp_path):
    import inspect

    q = request(kind)
    path = tmp_path / "request.json"
    save_segment_request(path, q)
    code = '''
import json, socket, sys
def deny(*args, **kwargs):
    raise RuntimeError("Python network disabled for segment replay")
socket.socket = deny
socket.create_connection = deny
socket.getaddrinfo = deny
socket.gethostbyname = deny
try:
    socket.getaddrinfo("example.invalid", 443)
except RuntimeError:
    blocked = True
else:
    raise AssertionError("network denial was not installed")
from ops_sim.v5.orbit_j2_segments import evaluate_j2_segments
from ops_sim.v5.orbit_j2_segments_document import load_segment_request, segment_request_to_json
'''
    code += inspect.getsource(evidence)
    code += '\nq = load_segment_request(sys.argv[1], expected_digest=sys.argv[2])\n'
    code += 'print(json.dumps({"blocked":blocked,"evidence":evidence(evaluate_j2_segments(q))}))\n'
    completed = subprocess.run([sys.executable, "-B", "-c", code, str(path), segment_request_digest(q)],
        capture_output=True, text=True, check=True, timeout=60,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"))
    actual = json.loads(completed.stdout)
    assert actual["blocked"] is True
    assert actual["evidence"] == evidence(evaluate_j2_segments(q))
