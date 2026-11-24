"""Strict document v1 authority, canonical identity and fresh-process round trips."""

from dataclasses import replace
import hashlib
import json
from math import inf, nan
import os
from pathlib import Path
import subprocess
import sys

import pytest

from examples.m1_assembly_choices_demo import summary, synthetic_design
from ops_sim.v5.assembly import MassCoverage, calculate_mass_properties
from ops_sim.v5.assembly_choices import InstallationRegion, assess_design
from ops_sim.v5.assembly_document import (
    assembly_document_digest, dumps_assembly_document, load_assembly_document,
    loads_assembly_document, save_assembly_document,
)


def payload():
    return json.loads(dumps_assembly_document(synthetic_design()))


def load(payload):
    return loads_assembly_document(json.dumps(payload))


def nested(data, path):
    for part in path:
        data = data[part]
    return data


def test_literal_version_one_reference_and_digest():
    text = (Path(__file__).parent / "fixtures/assembly_document_v1.json").read_text(encoding="utf-8")
    # Independently authored reference, no production encoder built its fields.
    canonical = json.dumps(json.loads(text), sort_keys=True, ensure_ascii=False,
                           allow_nan=False, separators=(",", ":"))
    golden = "089b0ff4101ed190caa19a5acc4be0d1aab9ad086c8ed45702f5f89427832666"
    assert hashlib.sha256(b"M1-ASSEMBLY-DOCUMENT" + bytes([0]) + b"v1" + bytes([0])
                          + canonical.encode()).hexdigest() == golden
    design = loads_assembly_document(text, expected_digest=golden)
    assert dumps_assembly_document(design) == canonical
    assert assembly_document_digest(design) == golden
    result = assess_design(design)
    assert not result.qualified and result.installation_status == "UNSPECIFIED"
    properties = calculate_mass_properties(result.assembly)
    assert properties.total_mass_kg == 1 and properties.center_body_m == (0, 0, 0)
    assert properties.inertia_com_body_kg_m2[1][1] == pytest.approx(1/6, abs=2e-14, rel=2e-14)


@pytest.mark.parametrize("case", ["compact", "spread", "envelope-conflict", "reserved-conflict"])
def test_round_trip_preserves_authority_outcomes_and_static_properties(case):
    original = synthetic_design(case)
    encoded = dumps_assembly_document(original)
    decoded = loads_assembly_document(encoded, expected_digest=assembly_document_digest(original))
    assert decoded == original
    assert dumps_assembly_document(decoded) == encoded
    assert assess_design(decoded) == assess_design(original)
    assert summary(decoded) == summary(original)
    assert not encoded.endswith("\n")
    assert "inertia_com_body_kg_m2" not in encoded and '"qualified"' not in encoded


def test_unordered_records_sets_and_paths_have_order_independent_identity():
    design = synthetic_design()
    extra_definition = replace(design.definitions[0], definition_id="unused-definition", mass_kg=3)
    design = replace(design, definitions=(*design.definitions, extra_definition),
        instances=tuple(replace(i, mass_coverage=MassCoverage(((i.instance_id, "b"), (i.instance_id, "a")))) for i in design.instances),
        choices=tuple(replace(c, allowed_instance_ids=("left", "right"), pose=replace(c.pose,
            occupied_slots=(c.choice_id+"-a", c.choice_id+"-b"))) for c in design.choices),
        allowed_regions=(*design.allowed_regions, InstallationRegion("unused-region", design.allowed_regions[0].box)),
        reserved_regions=(*design.reserved_regions, InstallationRegion("unused-reserved", design.reserved_regions[0].box)))
    expected = assembly_document_digest(design)
    data = json.loads(dumps_assembly_document(design))
    for field in ("definitions", "instances", "choices", "selections", "allowed_regions", "reserved_regions"):
        data[field].reverse()
    for choice in data["choices"]:
        choice["allowed_instance_ids"].reverse()
        choice["pose"]["occupied_slots"].reverse()
    for instance in data["instances"]:
        instance["mass_coverage"].reverse()
    changed = loads_assembly_document(json.dumps(data, indent=4, sort_keys=False))
    assert assembly_document_digest(changed) == expected
    assert dumps_assembly_document(changed) == dumps_assembly_document(design)
    assert assess_design(changed) == assess_design(design)


@pytest.mark.parametrize("change", ["mass", "local-com", "selected-choice", "coverage", "clearance",
                                    "envelope", "exclusive", "compatibility", "unused-pose"])
def test_meaningful_authoritative_edits_change_identity(change):
    original = synthetic_design()
    data = json.loads(dumps_assembly_document(original))
    if change == "mass": data["definitions"][0]["mass_kg"] = (2.0).hex()
    elif change == "local-com": data["definitions"][0]["center_local_m"][0] = (.125).hex()
    elif change == "selected-choice": data["selections"][0]["choice_id"] = "left-far"
    elif change == "coverage": data["instances"][0]["mass_coverage"][0][0] = "new-physical-partition"
    elif change == "clearance": data["clearance_m"] = (.125).hex()
    elif change == "envelope": data["choices"][0]["envelope"]["lower_m"][0] = (-.75).hex()
    elif change == "exclusive": data["choices"][0]["exclusive"] = False
    elif change == "compatibility": data["choices"][0]["allowed_instance_ids"] = ["left", "right"]
    elif change == "unused-pose":
        assert data["choices"][0]["choice_id"] == "left-blocked"
        data["choices"][0]["pose"]["origin_body_m"][0] = (.125).hex()
    changed = load(data)
    assert assembly_document_digest(changed) != assembly_document_digest(original)
    with pytest.raises(ValueError, match="digest mismatch"):
        loads_assembly_document(json.dumps(data), expected_digest=assembly_document_digest(original))


def test_signed_zero_and_unicode_content_scope_are_explicit():
    base = synthetic_design()
    minus_zero = replace(base, definitions=(replace(base.definitions[0], center_local_m=(-0.0, 0.0, 0.0)),))
    assert assembly_document_digest(minus_zero) != assembly_document_digest(base)
    assert loads_assembly_document(dumps_assembly_document(minus_zero)).definitions[0].center_local_m[0].hex() == '-0x0.0p+0'
    composed = replace(base, instances=(replace(base.instances[0], mass_coverage=MassCoverage((("caf\u00e9",),))), base.instances[1]))
    decomposed = replace(base, instances=(replace(base.instances[0], mass_coverage=MassCoverage((("cafe\u0301",),))), base.instances[1]))
    assert assembly_document_digest(composed) != assembly_document_digest(decomposed)
    assert "caf\u00e9" in dumps_assembly_document(composed)
    assert loads_assembly_document(dumps_assembly_document(composed)) == composed


@pytest.mark.parametrize("path", [(), ("units",), ("definitions", 0), ("instances", 0),
    ("choices", 0), ("choices", 0, "pose"), ("choices", 0, "envelope"),
    ("selections", 0), ("allowed_regions", 0), ("allowed_regions", 0, "box"),
    ("reserved_regions", 0), ("reserved_regions", 0, "box")])
def test_unknown_fields_and_cached_derived_data_rejected_at_every_object_level(path):
    data = payload()
    nested(data, path)["inertia_com_body_kg_m2"] = [[0, 0, 0]] * 3
    with pytest.raises(ValueError, match="unknown fields"):
        load(data)


@pytest.mark.parametrize("path,key", [((), "version"), (("definitions", 0), "mass_distribution"),
    (("instances", 0), "mass_coverage"), (("choices", 0), "exclusive"),
    (("choices", 0, "pose"), "occupied_slots"), (("choices", 0, "envelope"), "upper_m")])
def test_missing_fields_never_receive_implicit_defaults(path, key):
    data = payload(); del nested(data, path)[key]
    with pytest.raises(ValueError, match="missing"):
        load(data)


@pytest.mark.parametrize("value", [True, 1.0, "1", None, 0, 2])
def test_invalid_or_unsupported_document_version(value):
    data = payload(); data["version"] = value
    with pytest.raises((TypeError, ValueError)):
        load(data)


@pytest.mark.parametrize("path,key,value", [
    (("definitions", 0), "mass_kg", 1), (("definitions", 0), "mass_kg", True),
    (("definitions", 0), "mass_kg", "nan"), (("definitions", 0), "mass_kg", "inf"),
    (("definitions", 0), "mass_kg", "0x1p+0"), (("definitions", 0), "mass_kg", " 0x1.0000000000000p+0"),
    (("definitions", 0), "mass_kg", "0x1p+9999999"),
    (("definitions", 0), "size_m", ["0x0.0p+0"]),
    (("choices", 0), "exclusive", 1), (("choices", 0), "allowed_instance_ids", "left"),
    (("choices", 0, "pose"), "occupied_slots", {}), ((), "definitions", {}),
    (("units",), "mass", "g"), (("instances", 0), "instance_id", "\ud800"),
    (("instances", 0), "mass_coverage", []),
])
def test_invalid_field_types_values_and_noncanonical_numbers(path, key, value):
    data = payload(); nested(data, path)[key] = value
    with pytest.raises((TypeError, ValueError)):
        load(data)


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_nonfinite_json_constants_reject(value):
    data = payload(); data["clearance_m"] = value
    with pytest.raises(ValueError, match="non-finite JSON"):
        load(data)


def test_duplicate_json_keys_reject_at_root_and_nested_level():
    text = dumps_assembly_document(synthetic_design())
    for altered in (text.replace('"version":1', '"version":1,"version":1'),
                    text.replace('"mass_kg":', '"mass_kg":"0x1.0000000000000p+0","mass_kg":')):
        with pytest.raises(ValueError, match="duplicate JSON key"):
            loads_assembly_document(altered)


@pytest.mark.parametrize("field", ["definitions", "instances", "choices", "selections", "allowed_regions", "reserved_regions"])
def test_duplicate_authority_records_reject_even_if_identical(field):
    data = payload(); data[field].append(data[field][0])
    with pytest.raises(ValueError, match="duplicate"):
        load(data)


@pytest.mark.parametrize("path,key,value", [
    (("instances", 0), "definition_id", "missing"),
    (("choices", 0), "definition_id", "missing"),
    (("choices", 0), "allowed_region_id", "missing"),
    (("choices", 0), "allowed_instance_ids", ["missing"]),
    (("choices", 0, "pose"), "choice_id", "allowed-looking-alias"),
    (("choices", 0, "pose"), "body_frame_id", "OTHER"),
    (("choices", 0, "pose"), "local_frame_id", "OTHER"),
    (("selections", 0), "choice_id", "missing"),
    (("selections", 0), "choice_id", "right-near"),
    (("selections", 0), "instance_id", "missing"),
])
def test_dangling_incompatible_or_conflicting_references_reject(path, key, value):
    data = payload(); nested(data, path)[key] = value
    with pytest.raises(ValueError):
        load(data)


def test_caller_pose_cannot_be_smuggled_into_a_selection_or_declared_as_trusted_output():
    for key, value in (("center_body_m", [0, 0, 0]), ("rotation_body_from_local", [[1, 0, 0]]*3),
                       ("qualified", True)):
        data = payload(); data["selections"][0][key] = value
        with pytest.raises(ValueError, match="unknown fields"):
            load(data)


def test_tampered_python_graph_cannot_be_serialized_without_revalidation():
    design = synthetic_design()
    object.__setattr__(design.choices[0].envelope, "lower_m", (nan, 0, 0))
    with pytest.raises(ValueError, match="finite"):
        dumps_assembly_document(design)


def test_save_is_exclusive_and_never_persists_derived_results(tmp_path):
    design = synthetic_design()
    path = tmp_path / "document.json"
    save_assembly_document(design, path)
    before = path.read_bytes()
    assert before == dumps_assembly_document(design).encode("utf-8")
    with pytest.raises(FileExistsError):
        save_assembly_document(synthetic_design("spread"), path)
    assert path.read_bytes() == before
    assert load_assembly_document(path) == design
    with pytest.raises(ValueError, match="digest mismatch"):
        load_assembly_document(path, expected_digest="0"*64)
    with pytest.raises(ValueError, match="expected_digest"):
        load_assembly_document(path, expected_digest="NOT-A-DIGEST")


@pytest.mark.parametrize("case", ["compact", "spread", "envelope-conflict", "reserved-conflict"])
def test_fresh_process_reconstructs_document_identity_outcomes_and_properties(tmp_path, case):
    design = synthetic_design(case)
    path = tmp_path / (case + ".json")
    save_assembly_document(design, path)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    result = subprocess.run([sys.executable, "-B", "-m", "examples.m1_assembly_choices_demo",
        "--load", str(path), "--expected-digest", assembly_document_digest(design)],
        cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == json.loads(json.dumps(summary(design)))
