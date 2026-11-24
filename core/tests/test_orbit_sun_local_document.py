"""Input-only local authority: strict reconstruction, seed rejection and offline I/O."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import os
import subprocess
import sys

import pytest

from examples.m2_interval_illumination_demo import KINDS as INTERVAL_KINDS, example_request as interval_example
from ops_sim.v5 import orbit_j2 as f2
from ops_sim.v5 import orbit_j2_enclosure as f3
from ops_sim.v5 import orbit_j2_segments as b2
from ops_sim.v5 import orbit_sun_intervals as b3
from ops_sim.v5 import orbit_sun_windows as b4
from ops_sim.v5 import orbit_sun_local as b6
from ops_sim.v5._experiment_types import RECORD_FIELDS
from ops_sim.v5.experiment_codec import CANONICAL_VERSION, canonical_content, content_digest, json_text
from ops_sim.v5.orbit_sun_local_document import (
    DOMAIN, FORMAT, INPUT_FIELDS, POLICY_FIELDS, VERSION,
    local_request_digest, local_request_to_json, local_request_from_json,
    save_local_request, load_local_request,
)


def request(kind="illuminated"):
    q = interval_example(kind)
    policy = b6.LocalIlluminationPolicy(4, 128, 1536, 128, 8192, 65536)
    return b6.LocalIlluminationRequest(q.coast, q.table, q.start, q.end, 1/128, policy)


def mapping(wire):
    return dict(wire["items"])


def redigest(payload):
    # Sender-controlled hashing is not authority to weaken typed validation.
    payload["digest"] = hashlib.sha256(json_text({
        "domain": DOMAIN, "canonical_version": CANONICAL_VERSION,
        "content": payload["inputs"],
    }).encode("utf-8")).hexdigest()
    return json.dumps(payload)


def put(wire, value):
    wire.clear()
    wire.update(canonical_content(value))


def test_document_contract_has_its_own_explicit_domain_without_codec_registration():
    assert FORMAT == "M2_LOCAL_ILLUMINATION_REQUEST"
    assert DOMAIN == "m2-local-illumination-request-v1"
    assert VERSION == 1
    assert POLICY_FIELDS == (
        "max_passes", "max_integration_steps", "max_picard_attempts",
        "max_geometry_cells", "max_retained_evidence_units", "max_arithmetic_operations",
    )
    assert INPUT_FIELDS == ("coast", "table", "start", "end", "requested_resolution_seconds", "policy")
    assert b6.LocalIlluminationRequest not in RECORD_FIELDS
    assert b6.LocalIlluminationPolicy not in RECORD_FIELDS


@pytest.mark.parametrize("kind", INTERVAL_KINDS)
def test_exact_input_roundtrip_and_exclusive_save(kind, tmp_path):
    q = request(kind)
    text, digest = local_request_to_json(q), local_request_digest(q)
    path = tmp_path/"inputs.json"
    save_local_request(path, q)
    assert path.read_bytes() == (text+"\n").encode("utf-8")
    assert load_local_request(path, expected_digest=digest) == q
    assert local_request_from_json(text) == q
    assert local_request_to_json(local_request_from_json(text)) == text
    with pytest.raises(FileExistsError):
        save_local_request(path, q)
    assert path.read_bytes() == (text+"\n").encode("utf-8")


@pytest.mark.parametrize("key,value", [
    ("version", True), ("version", 1.), ("version", 2), ("version", "1"),
    ("canonical_version", True), ("canonical_version", 2),
    ("format", "M2_ILLUMINATION_WINDOW_REQUEST"), ("format", None),
    ("digest", "0"*64), ("digest", "F"*64), ("digest", None), ("digest", "a"*63),
    ("windows", []), ("seeds", []), ("cached_proofs", {}), ("ledger", {}),
    ("combined_qualification", "QUALIFIED"),
])
def test_envelope_rejects_wrong_types_versions_and_derived_fields(key, value):
    p = json.loads(local_request_to_json(request()))
    p[key] = value
    with pytest.raises((TypeError, ValueError)):
        local_request_from_json(json.dumps(p))


@pytest.mark.parametrize("key", ["format", "version", "canonical_version", "inputs", "digest"])
def test_missing_envelope_fields(key):
    p = json.loads(local_request_to_json(request()))
    del p[key]
    with pytest.raises(ValueError):
        local_request_from_json(json.dumps(p))


@pytest.mark.parametrize("key", INPUT_FIELDS)
def test_missing_authorities_with_recomputed_hash(key):
    p = json.loads(local_request_to_json(request()))
    p["inputs"]["items"] = [item for item in p["inputs"]["items"] if item[0] != key]
    with pytest.raises(ValueError):
        local_request_from_json(redigest(p))


@pytest.mark.parametrize("name,ceiling", [
    ("max_passes", 16), ("max_integration_steps", 65536),
    ("max_picard_attempts", 1048576), ("max_geometry_cells", 65536),
    ("max_retained_evidence_units", 393216), ("max_arithmetic_operations", 33562624),
])
@pytest.mark.parametrize("bad", ["bool", "float", "zero", "over-limit"])
def test_every_redigested_global_budget_remains_strict(name, ceiling, bad):
    p = json.loads(local_request_to_json(request()))
    policy = mapping(mapping(p["inputs"])["policy"])
    values = {"bool": True, "float": 1., "zero": 0, "over-limit": ceiling+1}
    put(policy[name], values[bad])
    with pytest.raises((TypeError, ValueError)):
        local_request_from_json(redigest(p))


@pytest.mark.parametrize("value", [True, False, 0., -1., float(2**41+1), Fraction(1, 128), "0.1"])
def test_redigested_resolution_type_and_domain(value):
    p = json.loads(local_request_to_json(request()))
    put(mapping(p["inputs"])["requested_resolution_seconds"], value)
    with pytest.raises((TypeError, ValueError)):
        local_request_from_json(redigest(p))


def test_noncanonical_resolution_normalization_rejected_even_with_recomputed_hash():
    # Direct integer construction may normalize; wire authority must already
    # contain the canonical normalized binary64 value.
    p = json.loads(local_request_to_json(request()))
    put(mapping(p["inputs"])["requested_resolution_seconds"], 1)
    with pytest.raises(ValueError, match="noncanonical"):
        local_request_from_json(redigest(p))


@pytest.mark.parametrize("which", [
    "coast-version", "bool-time", "epoch", "reversed", "outside-domain",
    "policy-extra", "policy-missing", "duplicate-map", "noncanonical-order",
    "table-normalization", "table-zero", "table-policy", "table-frame",
    "table-epoch", "table-provenance", "table-extra", "derived-windows",
])
def test_malformed_redigested_content_remains_invalid(which):
    p = json.loads(local_request_to_json(request()))
    data = mapping(p["inputs"])
    table = mapping(data["table"])
    start, end = data["start"]["fields"], data["end"]["fields"]
    if which == "coast-version":
        data["coast"]["fields"]["policy_version"] = canonical_content(True)
    elif which == "bool-time":
        start["elapsed_seconds"] = canonical_content(True)
    elif which == "epoch":
        end["epoch"]["fields"]["julian_day"] = canonical_content(2451546)
    elif which == "reversed":
        start["elapsed_seconds"], end["elapsed_seconds"] = end["elapsed_seconds"], start["elapsed_seconds"]
    elif which == "outside-domain":
        end["elapsed_seconds"] = canonical_content(129.)
    elif which == "policy-extra":
        data["policy"]["items"].append(["root_tolerance", canonical_content(.1)])
    elif which == "policy-missing":
        data["policy"]["items"] = data["policy"]["items"][1:]
    elif which == "duplicate-map":
        p["inputs"]["items"].append(deepcopy(p["inputs"]["items"][0]))
    elif which == "noncanonical-order":
        p["inputs"]["items"].reverse()
    elif which in ("table-normalization", "table-zero"):
        sample = mapping(table["samples"]["items"][0])
        put(sample["elapsed_seconds"] if which == "table-normalization" else sample["position_m"],
            128 if which == "table-normalization" else (0., 0., 0.))
    elif which == "table-policy":
        put(table["interpolation"], "CUBIC")
    elif which == "table-frame":
        table["frame"]["fields"]["rotation"]["fields"]["initial_phase_rad"]["fields"]["value"] = canonical_content(.5)
    elif which == "table-epoch":
        table["epoch"]["fields"]["julian_day"] = canonical_content(2451546)
    elif which == "table-provenance":
        put(mapping(table["provenance"])["accuracy_policy"], "ZERO_ERROR")
    elif which == "table-extra":
        data["table"]["items"].append(["cached_samples", canonical_content(())])
    else:
        p["inputs"]["items"].append(["derived_windows", canonical_content(())])
    with pytest.raises((TypeError, ValueError)):
        local_request_from_json(redigest(p))


@pytest.mark.parametrize("where", ["input", "coast", "table", "policy"])
@pytest.mark.parametrize("name", ["seed", "boundary_boxes", "certificates", "proof_ancestry"])
def test_injected_derived_products_rejected_even_when_redigested(where, name):
    p = json.loads(local_request_to_json(request()))
    data = mapping(p["inputs"])
    derived = canonical_content({"input_digest": p["digest"], "position_bounds_m": ((0., 0.),)*3})
    if where == "input":
        p["inputs"]["items"].append([name, derived])
    elif where == "coast":
        data["coast"]["fields"][name] = derived
    else:
        data[where]["items"].append([name, derived])
    with pytest.raises((TypeError, ValueError)):
        local_request_from_json(redigest(p))


def test_duplicate_json_keys_and_nonfinite_constants_rejected():
    text = local_request_to_json(request())
    with pytest.raises(ValueError, match="duplicate"):
        local_request_from_json('{"format":"x",'+text[1:])
    with pytest.raises(ValueError, match="non-finite"):
        local_request_from_json('{"inputs":NaN}')


@pytest.mark.parametrize("expected", ["0"*64, "F"*64, True, 1., "bad"])
def test_expected_digest_is_strict(expected):
    with pytest.raises((TypeError, ValueError)):
        local_request_from_json(local_request_to_json(request()), expected_digest=expected)


@pytest.mark.parametrize("which", [
    "start", "end", "nominal", "enclosure-step", "enclosure-precision", "sun-node", "provenance",
    "requested-resolution", *POLICY_FIELDS,
])
def test_digest_binds_physical_inputs_and_every_local_authority(which):
    q = request()
    if which == "start":
        changed = replace(q, start=replace(q.start, elapsed_seconds=q.start.elapsed_seconds+1/256))
    elif which == "end":
        changed = replace(q, end=replace(q.end, elapsed_seconds=q.end.elapsed_seconds-1/256))
    elif which == "nominal":
        changed = replace(q, coast=replace(q.coast, solver_config=replace(q.coast.solver_config, max_steps=31)))
    elif which == "enclosure-step":
        changed = replace(q, coast=replace(q.coast, enclosure_policy=replace(q.coast.enclosure_policy, step_seconds=1/64)))
    elif which == "enclosure-precision":
        changed = replace(q, coast=replace(q.coast, enclosure_policy=replace(q.coast.enclosure_policy, precision_digits=60)))
    elif which == "sun-node":
        changed = replace(q, table=replace(q.table, samples=(replace(q.table.samples[0], position_m=(101., -1., 0.)), q.table.samples[1])))
    elif which == "provenance":
        changed = replace(q, table=replace(q.table, provenance=replace(q.table.provenance,
            accuracy_statement="Unquantified; changed explicit rationale")))
    elif which == "requested-resolution":
        changed = replace(q, requested_resolution_seconds=1/256)
    else:
        changed = replace(q, policy=replace(q.policy, **{which: getattr(q.policy, which)-1}))
    assert local_request_digest(changed) != local_request_digest(q)
    with pytest.raises(ValueError, match="expected"):
        local_request_from_json(local_request_to_json(changed), expected_digest=local_request_digest(q))


def test_loading_does_not_propagate_or_register_derived_record_types(monkeypatch, tmp_path):
    q = request()
    path = tmp_path/"inputs.json"
    save_local_request(path, q)
    before = tuple(RECORD_FIELDS.items())
    def forbidden(*args, **kwargs):
        raise AssertionError("loading evaluated derived evidence")
    monkeypatch.setattr(f2, "evaluate_j2_cartesian_state", forbidden)
    monkeypatch.setattr(f3, "evaluate_j2_enclosure", forbidden)
    monkeypatch.setattr(f3, "_step_with_tube", forbidden)
    monkeypatch.setattr(b2, "evaluate_j2_segments", forbidden)
    monkeypatch.setattr(b2, "_validated_step", forbidden)
    monkeypatch.setattr(b3, "evaluate_interval_illumination", forbidden)
    monkeypatch.setattr(b4, "evaluate_illumination_windows", forbidden)
    monkeypatch.setattr(b6, "evaluate_local_illumination", forbidden)
    assert load_local_request(path) == q
    assert local_request_from_json(local_request_to_json(q)) == q
    assert tuple(RECORD_FIELDS.items()) == before
    with pytest.raises(TypeError):
        canonical_content(q)
    data = {"coast": q.coast, "start": q.start, "end": q.end}
    assert content_digest(DOMAIN, data) != content_digest("m2-illumination-window-request-v1", data)


@pytest.mark.parametrize("name", POLICY_FIELDS)
def test_forged_request_is_rebuilt_before_serialization(name):
    q = request()
    object.__setattr__(q.policy, name, True)
    with pytest.raises(TypeError):
        local_request_digest(q)
    with pytest.raises(TypeError):
        local_request_to_json(q)


def test_fresh_process_input_only_reconstruction_without_network_or_propagation(tmp_path):
    q = request("ambiguous")
    path = tmp_path/"inputs.json"
    save_local_request(path, q)
    script = """
import sys
from examples.m2_j2_segments_demo import block_network
from ops_sim.v5 import orbit_j2_enclosure as f3
from ops_sim.v5 import orbit_j2_segments as b2
from ops_sim.v5 import orbit_sun_intervals as b3
from ops_sim.v5 import orbit_sun_local as b6
from ops_sim.v5.orbit_sun_local_document import load_local_request, local_request_to_json
def forbidden(*args, **kwargs):
    raise AssertionError('input reconstruction evaluated derived evidence')
block_network()
f3._step_with_tube = forbidden
b2._validated_step = forbidden
b3.evaluate_interval_illumination = forbidden
b6.evaluate_local_illumination = forbidden
print(local_request_to_json(load_local_request(sys.argv[1], expected_digest=sys.argv[2])))
"""
    process = subprocess.run([sys.executable, "-B", "-c", script, str(path), local_request_digest(q)],
        capture_output=True, text=True, check=True, timeout=30,
        env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"))
    assert process.stdout.rstrip("\r\n") == local_request_to_json(q)
    assert process.stderr == ""
