"""Independent scalar fixtures, field-graph coverage and strict codec rejection."""

from dataclasses import fields, is_dataclass, replace
from enum import Enum
from fractions import Fraction
import hashlib
import json
from typing import get_args, get_type_hints

import pytest

from examples.v5_experiment_bundle_demo import build_demo_state
from ops_sim.v5._experiment_types import ENUM_TYPES, RECORD_FIELDS
from ops_sim.v5.context import SimulationInputs
from ops_sim.v5.experiment_codec import (
    canonical_content, canonical_copy, check_schema_coverage, content_digest,
    decode_content, parse_json,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import ProvenanceStatus


def test_scalar_literal_and_sha256_are_independently_specified():
    fixture = {"canonical_version": 1, "domain": "literal", "content": {
        "kind": "tuple", "items": [
            {"kind": "bool", "value": True}, {"kind": "int", "value": "1"},
            {"kind": "float", "value": "0x1.0000000000000p+0"},
            {"kind": "float", "value": "-0x0.0p+0"},
            {"kind": "fraction", "numerator": "1", "denominator": "3"},
        ],
    }}
    expected = hashlib.sha256(json.dumps(fixture, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert content_digest("literal", (True, 1, 1.0, -0.0, Fraction(1, 3))) == expected
    assert canonical_content(2**100) == {"kind": "int", "value": "1267650600228229401496703205376"}


def test_independent_inputs_json_roundtrip_and_mapping_order():
    left, right = build_demo_state(), build_demo_state()
    assert left.context.inputs is not right.context.inputs
    assert canonical_content(left.context.inputs) == canonical_content(right.context.inputs)
    wire = json.loads(json.dumps(canonical_content(left.context.inputs)))
    assert decode_content(wire) == right.context.inputs
    assert canonical_content({"b": 2, "a": 1}) == canonical_content({"a": 1, "b": 2})
    assert content_digest("a", 1) != content_digest("b", 1)


@pytest.mark.parametrize("left,right", [
    (True, 1), (1, 1.0), (Fraction(1), 1), (0.0, -0.0),
    ((1, 2), (2, 1)), ((1, 2), [1, 2]),
    (ProvenanceStatus.VERIFIED, "VERIFIED"), ("é", "e\u0301"),
])
def test_meaningful_type_order_enum_and_unicode_distinctions(left, right):
    assert content_digest("distinctions", left) != content_digest("distinctions", right)


def test_units_and_fraction_parameter_are_preserved_exactly():
    parameter = build_demo_state().context.inputs.spacecraft_configuration.eps.battery.discharge_efficiency
    rational = replace(parameter, value=Fraction(9, 10))
    assert canonical_copy(rational).value == Fraction(9, 10)
    assert type(canonical_copy(rational).value) is Fraction
    alternate_unit = replace(parameter, provenance=replace(parameter.provenance, units="W"))
    assert content_digest("parameter", parameter) != content_digest("parameter", alternate_unit)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), {1, 2}, 1j, b"text", object(), "\ud800", {1: "key"}])
def test_nonfinite_unsupported_types_and_text_rejected(value):
    with pytest.raises((TypeError, ValueError)):
        canonical_content(value)


def test_subclasses_do_not_downgrade_into_trusted_canonical_types():
    class Text(str):
        pass
    class Number(float):
        pass
    for value in (Text("name"), Number(1.0)):
        with pytest.raises(TypeError, match="unsupported canonical type"):
            canonical_content(value)


@pytest.mark.parametrize("payload", [
    {"kind": "int", "value": "01"}, {"kind": "float", "value": "nan"},
    {"kind": "float", "value": "1.0"}, {"kind": "bool", "value": 1},
    {"kind": "fraction", "numerator": "2", "denominator": "4"},
    {"kind": "map", "items": [["a", {"kind": "none"}], ["a", {"kind": "none"}]]},
    {"kind": "record", "type": "os.system", "fields": {}},
    {"kind": "none", "unknown": None},
])
def test_bad_canonical_encodings_are_not_repaired(payload):
    with pytest.raises((TypeError, ValueError)):
        decode_content(payload)


def test_missing_and_unknown_record_fields_fail_closed():
    encoded = canonical_content(build_demo_state().context.inputs)
    encoded["fields"]["unknown"] = {"kind": "none"}
    with pytest.raises(ValueError, match="fields"):
        decode_content(encoded)
    del encoded["fields"]["unknown"]
    del encoded["fields"]["coast_orbit"]
    with pytest.raises(ValueError, match="fields"):
        decode_content(encoded)


def test_constructor_validation_cannot_be_bypassed_by_a_valid_encoding():
    wire = canonical_content(build_demo_state().context.inputs)
    battery = wire["fields"]["spacecraft_configuration"]["fields"]["eps"]["fields"]["battery"]
    battery["fields"]["discharge_efficiency"]["fields"]["value"] = {"kind": "float", "value": 2.0.hex()}
    with pytest.raises(ValueError, match="discharge_efficiency"):
        decode_content(wire)


def test_every_current_input_annotation_and_field_has_an_explicit_owner():
    visited = set()

    def visit(annotation):
        if annotation in visited:
            return
        visited.add(annotation)
        if is_dataclass(annotation):
            assert annotation in RECORD_FIELDS
            assert tuple(f.name for f in fields(annotation)) == RECORD_FIELDS[annotation]
            hints = get_type_hints(annotation)
            for f in fields(annotation):
                visit(hints[f.name])
        elif isinstance(annotation, type) and issubclass(annotation, Enum):
            assert annotation in ENUM_TYPES
        else:
            for child in get_args(annotation):
                visit(child)

    visit(SimulationInputs)
    assert ScalarParameter in visited
    check_schema_coverage()


def test_future_field_omission_is_detected_before_encoding(monkeypatch):
    monkeypatch.setitem(RECORD_FIELDS, SimulationInputs, RECORD_FIELDS[SimulationInputs][:-1])
    with pytest.raises(ValueError, match="unreviewed canonical field schema"):
        canonical_content(None)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_json_does_not_accept_duplicate_keys_or_nonfinite_constants(text):
    with pytest.raises(ValueError):
        parse_json(text)
