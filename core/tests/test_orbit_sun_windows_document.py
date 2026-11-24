"""Strict input authority, hostile reconstruction and offline window replay."""
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
from ops_sim.v5._experiment_types import RECORD_FIELDS
from ops_sim.v5.experiment_codec import CANONICAL_VERSION, canonical_content, content_digest, json_text
from ops_sim.v5.orbit_sun_windows_document import (
    DOMAIN, POLICY_FIELDS, window_request_digest, window_request_to_json,
    window_request_from_json, save_window_request, load_window_request,
)


def request(kind="illuminated"):
    q = interval_example(kind)
    policy = b4.IlluminationSearchPolicy(4, 128, 128, 2048, 65536)
    return b4.IlluminationWindowRequest(q.coast, q.table, q.start, q.end, 1/128, policy)


def mapping(wire):
    return dict(wire["items"])


def redigest(payload):
    # A sender may hash malformed canonical data; the reader must still reject it.
    payload["digest"] = hashlib.sha256(json_text({
        "domain": DOMAIN, "canonical_version": CANONICAL_VERSION,
        "content": payload["inputs"],
    }).encode("utf-8")).hexdigest()
    return json.dumps(payload)


def put(wire, value):
    wire.clear()
    wire.update(canonical_content(value))


@pytest.mark.parametrize("kind", INTERVAL_KINDS)
def test_exact_input_roundtrip_and_exclusive_save(kind, tmp_path):
    q = request(kind)
    text, digest = window_request_to_json(q), window_request_digest(q)
    path = tmp_path/"inputs.json"
    save_window_request(path, q)
    assert path.read_bytes() == (text+"\n").encode("utf-8")
    assert load_window_request(path, expected_digest=digest) == q
    assert window_request_from_json(text) == q
    assert window_request_to_json(window_request_from_json(text)) == text
    with pytest.raises(FileExistsError):
        save_window_request(path, q)
    assert path.read_bytes() == (text+"\n").encode("utf-8")


@pytest.mark.parametrize("key,value", [
    ("version", True), ("version", 1.), ("version", 2), ("version", "1"),
    ("canonical_version", True), ("canonical_version", 2),
    ("format", "M2_INTERVAL_ILLUMINATION_REQUEST"), ("format", None),
    ("digest", "0"*64), ("digest", "F"*64), ("digest", None), ("digest", "a"*63),
    ("windows", []), ("event_guesses", []), ("cached_proofs", {}),
    ("combined_qualification", "QUALIFIED"),
])
def test_envelope_rejects_wrong_types_versions_and_derived_fields(key, value):
    p = json.loads(window_request_to_json(request()))
    p[key] = value
    with pytest.raises((TypeError, ValueError)):
        window_request_from_json(json.dumps(p))


@pytest.mark.parametrize("key", ["format", "version", "canonical_version", "inputs", "digest"])
def test_missing_envelope_fields(key):
    p = json.loads(window_request_to_json(request()))
    del p[key]
    with pytest.raises(ValueError):
        window_request_from_json(json.dumps(p))


@pytest.mark.parametrize("key", ["coast", "table", "start", "end", "requested_resolution_seconds", "policy"])
def test_missing_authorities_with_recomputed_hash(key):
    p = json.loads(window_request_to_json(request()))
    p["inputs"]["items"] = [item for item in p["inputs"]["items"] if item[0] != key]
    with pytest.raises(ValueError):
        window_request_from_json(redigest(p))


@pytest.mark.parametrize("name,ceiling", [
    ("max_trials", 16), ("max_integration_steps", 65536),
    ("max_geometry_cells", 65536), ("max_retained_evidence_units", 393216),
    ("max_arithmetic_operations", 33562624),
])
@pytest.mark.parametrize("bad", ["bool", "float", "zero", "over-limit"])
def test_every_redigested_global_budget_remains_strict(name, ceiling, bad):
    p = json.loads(window_request_to_json(request()))
    policy = mapping(mapping(p["inputs"])["policy"])
    values = {"bool": True, "float": 1., "zero": 0, "over-limit": ceiling+1}
    put(policy[name], values[bad])
    with pytest.raises((TypeError, ValueError)):
        window_request_from_json(redigest(p))


@pytest.mark.parametrize("value", [True, False, 0., -1., float(2**41+1), Fraction(1, 128), "0.1"])
def test_redigested_resolution_type_and_domain(value):
    p = json.loads(window_request_to_json(request()))
    put(mapping(p["inputs"])["requested_resolution_seconds"], value)
    with pytest.raises((TypeError, ValueError)):
        window_request_from_json(redigest(p))


def test_noncanonical_resolution_normalization_rejected_even_with_recomputed_hash():
    # A direct built-in integer may normalize at construction, but persisted
    # authority must already contain the canonical normalized binary64 value.
    p = json.loads(window_request_to_json(request()))
    put(mapping(p["inputs"])["requested_resolution_seconds"], 1)
    with pytest.raises(ValueError, match="noncanonical"):
        window_request_from_json(redigest(p))


@pytest.mark.parametrize("which", [
    "coast-version", "bool-time", "epoch", "reversed", "outside-domain",
    "policy-extra", "policy-missing", "duplicate-map", "noncanonical-order",
    "table-normalization", "table-zero", "table-policy", "table-frame",
    "table-epoch", "table-provenance", "table-extra", "derived-windows",
])
def test_malformed_redigested_content_remains_invalid(which):
    p = json.loads(window_request_to_json(request()))
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
        window_request_from_json(redigest(p))


def test_duplicate_json_keys_and_nonfinite_constants_rejected():
    text = window_request_to_json(request())
    with pytest.raises(ValueError, match="duplicate"):
        window_request_from_json('{"format":"x",'+text[1:])
    with pytest.raises(ValueError, match="non-finite"):
        window_request_from_json('{"inputs":NaN}')


@pytest.mark.parametrize("expected", ["0"*64, "F"*64, True, 1., "bad"])
def test_expected_digest_is_strict(expected):
    with pytest.raises((TypeError, ValueError)):
        window_request_from_json(window_request_to_json(request()), expected_digest=expected)


@pytest.mark.parametrize("which", [
    "start", "end", "nominal", "enclosure-step", "enclosure-precision", "sun-node", "provenance",
    "requested-resolution", *POLICY_FIELDS,
])
def test_digest_binds_physical_inputs_and_every_search_authority(which):
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
    assert window_request_digest(changed) != window_request_digest(q)
    with pytest.raises(ValueError, match="expected"):
        window_request_from_json(window_request_to_json(changed), expected_digest=window_request_digest(q))


def test_loading_does_not_propagate_or_register_derived_record_types(monkeypatch):
    q = request()
    text = window_request_to_json(q)
    before = tuple(RECORD_FIELDS.items())
    def forbidden(*args, **kwargs):
        raise AssertionError("loading evaluated derived evidence")
    monkeypatch.setattr(f2, "evaluate_j2_cartesian_state", forbidden)
    monkeypatch.setattr(f3, "evaluate_j2_enclosure", forbidden)
    monkeypatch.setattr(b2, "evaluate_j2_segments", forbidden)
    monkeypatch.setattr(b3, "evaluate_interval_illumination", forbidden)
    monkeypatch.setattr(b4, "evaluate_illumination_windows", forbidden)
    assert window_request_from_json(text) == q
    assert tuple(RECORD_FIELDS.items()) == before
    with pytest.raises(TypeError):
        canonical_content(q)
    data = {"coast": q.coast, "start": q.start, "end": q.end}
    assert content_digest(DOMAIN, data) != content_digest("m2-interval-illumination-request-v1", data)


def test_forged_request_is_rebuilt_before_serialization():
    q = request()
    object.__setattr__(q.policy, "max_trials", True)
    with pytest.raises(TypeError):
        window_request_digest(q)
    with pytest.raises(TypeError):
        window_request_to_json(q)


@pytest.mark.parametrize("kind", ["illuminated", "refinement"])
def test_fresh_process_offline_reconstructs_complete_evidence(kind, tmp_path):
    from examples.m2_illumination_windows_demo import example_request, summary
    q = example_request(kind)
    path = tmp_path/"inputs.json"
    save_window_request(path, q)
    command = [sys.executable, "-B", "-m", "examples.m2_illumination_windows_demo", "--offline",
               "--inputs", str(path), "--expected-digest", window_request_digest(q)]
    process = subprocess.run(command, capture_output=True, text=True, check=True, timeout=120,
        env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"))
    actual = json.loads(process.stdout)
    assert actual["python_network_disabled"] is True
    expected = json.loads(json.dumps(summary(b4.evaluate_illumination_windows(q))))
    assert actual["evidence"] == expected
