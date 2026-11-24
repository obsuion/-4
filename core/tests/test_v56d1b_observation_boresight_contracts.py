"""Concrete frame authority, hardened external labels and D1a ownership."""

from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import ast
import inspect
import math

import pytest

from ops_sim.v5.ids import ADCSBoresightFrameId, GroundTargetId, ImagingRequestId, ObservationOpportunityId, SourceRecordId
from ops_sim.v5.orbit_config import FrameDefinition, FrameKind
from ops_sim.v5.provenance import SensitivityRange
import ops_sim.v5.orbit_observation_boresight as adapter
from ops_sim.v5.orbit_observation_boresight import (
    ModelInertialBoresightFrameBinding as Binding,
    OrbitBoundObservationManeuverCandidate as Result,
    derive_observation_maneuver_candidate_for_engine_step as derive,
)
from test_v56b1_two_body_contracts import _forge
from test_v56d1a_observation_opportunity_contracts import _arguments as d1a_arguments
from test_v56d1a_observation_opportunity_geometry import _projection_seam, _block


def _arguments(**changes):
    args = d1a_arguments(**{k: v for k, v in changes.items() if k != "boresight_frame"})
    frame = args["inputs"].coast_orbit.trajectory.initial_state.position.frame
    args["boresight_frame"] = changes.get("boresight_frame", Binding(ADCSBoresightFrameId("caller-axes"), frame))
    return args


def _quick(monkeypatch):
    # Only bypass C2c search cost in contract tests; real D1a/B1/C1 still run.
    # This seam is not visibility evidence. A real hidden-pass test is separate.
    _projection_seam(monkeypatch, (_block(9, 3, 1),))


class PlainText(str): pass
class EqualText(str):
    def __eq__(self, other): return True
    def __ne__(self, other): return False
    def __hash__(self): raise AssertionError("caller hash invoked")
class UnequalText(str):
    def __eq__(self, other): return False
    def __ne__(self, other): return str.__ne__(self, other)
    def __hash__(self): raise AssertionError("caller hash invoked")
class IdSubclass(ADCSBoresightFrameId): pass
class BindingSubclass(Binding): pass
class FrameSubclass(FrameDefinition): pass


def test_public_required_frozen_slotted_default_free_contracts(monkeypatch):
    _quick(monkeypatch)
    names = tuple(_arguments())
    derived = ("orbit_observation", "common_frame_boresight", "maneuver_candidate")
    assert tuple(inspect.signature(Binding).parameters) == ("frame_id", "frame")
    assert tuple(inspect.signature(Result).parameters) == tuple(inspect.signature(derive).parameters) == names
    assert tuple(f.name for f in fields(Result) if not f.init) == derived
    for cls in (Binding, Result):
        assert cls.__dataclass_params__.frozen
        assert cls.__slots__ == tuple(f.name for f in fields(cls))
        assert all(p.default is inspect.Parameter.empty for p in inspect.signature(cls).parameters.values())
        assert cls.__hash__ is None
        with pytest.raises(TypeError): cls()
    result = derive(**_arguments())
    for value, field in ((result, "step_start_seconds"), (result.boresight_frame, "frame")):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError): setattr(value, field, None)
        with pytest.raises(TypeError): hash(value)
        assert value.__eq__(object()) is NotImplemented
    assert set(adapter.__all__) == {Binding.__name__, Result.__name__, derive.__name__}


def test_binding_rebuilds_nested_graph_retaining_caller_id():
    binding = _arguments()["boresight_frame"]
    frame = binding.frame
    forged = _forge(frame, "rotation.initial_phase_rad.value", Fraction(1, 4))
    normalized = Binding(binding.frame_id, forged)
    assert normalized.frame_id is binding.frame_id
    assert normalized.frame is not forged
    assert type(normalized.frame.rotation.initial_phase_rad.value) is float
    assert normalized.frame.rotation is not forged.rotation
    assert normalized.frame.ellipsoid is not forged.ellipsoid
    assert normalized.frame.rotation.initial_phase_rad.provenance is not forged.rotation.initial_phase_rad.provenance


@pytest.mark.parametrize("value", [None, "axes", FrameKind.MODEL_INERTIAL, GroundTargetId("axes"), IdSubclass("axes")])
def test_binding_requires_exact_frame_id(value):
    with pytest.raises(TypeError): Binding(value, _arguments()["boresight_frame"].frame)


@pytest.mark.parametrize("text", [None, True, "", "BAD", " bad", "bad ", "a/b", "a..b", "a\x00b", "\ud800", "é", "e\u0301", "x" * 129])
def test_invalid_label_text_revalidated_through_legacy_owner(text):
    binding = _arguments()["boresight_frame"]
    with pytest.raises((TypeError, ValueError)):
        Binding(_forge(binding.frame_id, "value", text), binding.frame)


@pytest.mark.parametrize("kind", [FrameKind.EARTH_FIXED, "MODEL_INERTIAL", None])
def test_wrong_or_string_frame_kind_rejects(kind):
    binding = _arguments()["boresight_frame"]
    with pytest.raises((TypeError, ValueError)):
        Binding(binding.frame_id, _forge(binding.frame, "kind", kind))


@pytest.mark.parametrize("path,value", [
    ("ellipsoid", None), ("ellipsoid.name", ""),
    ("ellipsoid.equatorial_radius_m.value", 0.), ("ellipsoid.flattening.value", 1.),
    ("ellipsoid.equatorial_radius_m.provenance", None),
    ("ellipsoid.equatorial_radius_m.provenance.parameter_id.value", "wrong"),
    ("ellipsoid.equatorial_radius_m.provenance.units", "km"),
    ("ellipsoid.equatorial_radius_m.provenance.classification", "EXPLICIT_MODEL_ASSUMPTION"),
    ("ellipsoid.equatorial_radius_m.provenance.status", "VERIFIED"),
    ("ellipsoid.equatorial_radius_m.provenance.source_ids", ["source"]),
    ("ellipsoid.equatorial_radius_m.provenance.source_ids", (GroundTargetId("source"),)),
    ("ellipsoid.equatorial_radius_m.provenance.rationale", None),
    ("ellipsoid.equatorial_radius_m.provenance.sensitivity_range", SensitivityRange(2., 3.)),
    ("rotation", None), ("rotation.epoch", None), ("rotation.epoch.julian_day", True),
    ("rotation.epoch.fractional_day", 1.),
    ("rotation.initial_phase_rad.value", math.pi),
    ("rotation.initial_phase_rad.provenance.units", "deg"),
    ("rotation.angular_velocity_rad_per_s.value", math.nan),
    ("rotation.angular_velocity_rad_per_s.value", math.inf),
    ("rotation.angular_velocity_rad_per_s.value", True),
])
def test_complete_forged_frame_graph_is_revalidated_before_d1a(monkeypatch, path, value):
    args = _arguments()
    args["boresight_frame"] = _forge(args["boresight_frame"], "frame." + path, value)
    def forbidden(*values): pytest.fail("invalid binding reached D1a")
    monkeypatch.setattr(adapter, "derive_observation_opportunity_for_engine_step", forbidden)
    with pytest.raises((TypeError, ValueError)): derive(**args)


def test_exact_binding_and_frame_owners_before_d1a(monkeypatch):
    args = _arguments(); binding = args["boresight_frame"]
    def forbidden(*values): pytest.fail("invalid binding reached D1a")
    monkeypatch.setattr(adapter, "derive_observation_opportunity_for_engine_step", forbidden)
    for value in (None, binding.frame, BindingSubclass(binding.frame_id, binding.frame)):
        with pytest.raises(TypeError): derive(**dict(args, boresight_frame=value))
    for frame in (None, "MODEL_INERTIAL", FrameKind.MODEL_INERTIAL,
                  FrameSubclass(binding.frame.kind, binding.frame.ellipsoid, binding.frame.rotation)):
        with pytest.raises(TypeError):
            derive(**dict(args, boresight_frame=_forge(binding, "frame", frame)))
    # A forged enum instance is not one of the declared actual members.
    fake = str.__new__(FrameKind, "MODEL_INERTIAL")
    object.__setattr__(fake, "_name_", "MODEL_INERTIAL")
    object.__setattr__(fake, "_value_", "MODEL_INERTIAL")
    with pytest.raises(ValueError, match="actual frame enum"):
        derive(**dict(args, boresight_frame=_forge(binding, "frame.kind", fake)))


@pytest.mark.parametrize("left_type", [str, PlainText, EqualText, UnequalText])
@pytest.mark.parametrize("right_type", [str, PlainText, EqualText, UnequalText])
def test_binding_uses_actual_text_without_caller_equality_or_hash(left_type, right_type):
    frame = _arguments()["boresight_frame"].frame
    left_id, right_id = ADCSBoresightFrameId(left_type("axes")), ADCSBoresightFrameId(right_type("axes"))
    left, right = Binding(left_id, frame), Binding(right_id, frame)
    assert left == right and right == left and not left != right
    different = Binding(ADCSBoresightFrameId(right_type("other-axes")), frame)
    assert left != different and different != left
    assert left.frame_id is left_id and right.frame_id is right_id
    assert type(right.frame_id.value) is right_type


@pytest.mark.parametrize("parameter", ["ellipsoid.equatorial_radius_m", "ellipsoid.flattening",
    "rotation.initial_phase_rad", "rotation.angular_velocity_rad_per_s"])
@pytest.mark.parametrize("field", ["parameter_id.value", "units", "rationale", "derivation", "source_ids"])
@pytest.mark.parametrize("text_type", [PlainText, EqualText, UnequalText])
def test_concrete_frame_metadata_text_cannot_overload_complete_identity(monkeypatch, parameter, field, text_type):
    args = _arguments(); binding = args["boresight_frame"]
    owner = binding.frame
    for name in parameter.split("."): owner = getattr(owner, name)
    if field == "parameter_id.value": value = text_type(owner.provenance.parameter_id.value)
    elif field == "units": value = text_type(owner.provenance.units)
    elif field == "source_ids":
        # The frozen provenance owner hashes source IDs during reconstruction.
        # Allow that existing validation to reach the later exact-text guard;
        # retain hostile equality/inequality. ADCS-label hash traps are tested
        # separately above and are never invoked by D1b semantic equality.
        hashable_text = type("SourceText", (text_type,), {"__hash__": str.__hash__})
        value = (SourceRecordId(hashable_text("external-source")),)
    else: value = text_type("different external evidence")
    bad_frame = _forge(binding.frame, parameter + ".provenance." + field, value)
    def forbidden(*values): pytest.fail("invalid concrete metadata reached D1a")
    monkeypatch.setattr(adapter, "derive_observation_opportunity_for_engine_step", forbidden)
    # Concrete frame metadata follows the existing C1/B2 exact-text boundary;
    # the separately supplied legacy ADCS label still admits text subclasses.
    with pytest.raises(TypeError, match="portable text"):
        Binding(binding.frame_id, bad_frame)
    with pytest.raises(TypeError, match="portable text"):
        derive(**dict(args, boresight_frame=_forge(binding, "frame", bad_frame)))


@pytest.mark.parametrize("path,value", [
    ("rotation.initial_phase_rad.provenance.rationale", EqualText("different evidence")),
    ("rotation.initial_phase_rad.provenance.units", EqualText("deg")),
    ("rotation.initial_phase_rad.provenance.parameter_id.value", EqualText("wrong")),
])
def test_hostile_text_cannot_hide_different_frame_content_or_wrong_parameter_contract(path, value):
    original = _arguments()["boresight_frame"]
    # A's historical reconstruction alone admits these hostile strings. D1b
    # must also apply the concrete frame text guard used by C1/B2 before equality.
    damaged = _forge(original.frame, path, value)
    rebuilt = FrameDefinition(damaged.kind, damaged.ellipsoid, damaged.rotation)
    if path.endswith("rationale"):
        assert rebuilt == original.frame  # Exhibits the legacy comparison trap.
    with pytest.raises(TypeError, match="portable text"):
        Binding(original.frame_id, rebuilt)


@pytest.mark.parametrize("path", ["ellipsoid.name", "rotation.initial_phase_rad.provenance.rationale",
    "rotation.initial_phase_rad.provenance.derivation"])
def test_concrete_frame_rejects_surrogates_without_unicode_normalization(path):
    binding = _arguments()["boresight_frame"]
    with pytest.raises(ValueError, match="surrogates"):
        Binding(binding.frame_id, _forge(binding.frame, path, "bad\ud800text"))
    composed = Binding(binding.frame_id, _forge(binding.frame, path, "caf\u00e9"))
    decomposed = Binding(binding.frame_id, _forge(binding.frame, path, "cafe\u0301"))
    assert composed != decomposed


@pytest.mark.parametrize("path,value", [
    ("rotation.initial_phase_rad.value", .125),
    ("rotation.angular_velocity_rad_per_s.value", .01),
    ("rotation.epoch.fractional_day", .25),
    ("ellipsoid.flattening.value", .01),
    ("ellipsoid.equatorial_radius_m.value", 1.01),
    ("ellipsoid.name", "Different evidence name"),
    ("rotation.initial_phase_rad.provenance.rationale", "Different external evidence"),
])
def test_colliding_label_different_complete_frame_rejects_after_one_d1a(monkeypatch, path, value):
    _quick(monkeypatch)
    args = _arguments(); original = args["boresight_frame"]
    changed = Binding(original.frame_id, _forge(original.frame, path, value))
    assert changed != original and changed.frame != original.frame
    calls = []
    owner = adapter.derive_observation_opportunity_for_engine_step
    def spy(*values):
        calls.append("D1a")
        return owner(*values)
    def forbidden(*values): pytest.fail("mismatched frame reached V5.3 construction")
    monkeypatch.setattr(adapter, "derive_observation_opportunity_for_engine_step", spy)
    monkeypatch.setattr(adapter, "CommonFrameBoresightDirection", forbidden)
    monkeypatch.setattr(adapter, "ObservationManeuverCandidate", forbidden)
    with pytest.raises(ValueError, match="concrete/common-frame mismatch"):
        derive(**dict(args, boresight_frame=changed))
    assert calls == ["D1a"]


def test_d1a_failure_propagates_same_exception_and_stops_construction(monkeypatch):
    failure = ValueError("D1a owner failure")
    calls = []
    def fail(*values):
        calls.append(values)
        raise failure
    def forbidden(*values): pytest.fail("failed D1a reached boresight/candidate")
    monkeypatch.setattr(adapter, "derive_observation_opportunity_for_engine_step", fail)
    monkeypatch.setattr(adapter, "CommonFrameBoresightDirection", forbidden)
    monkeypatch.setattr(adapter, "ObservationManeuverCandidate", forbidden)
    args = _arguments()
    with pytest.raises(ValueError) as caught: derive(**args)
    assert caught.value is failure and len(calls) == 1
    assert all(a is b for a, b in zip(calls[0], list(args.values())[:10]))


@pytest.mark.parametrize("source", ["spacecraft_state.position", "spacecraft_state.velocity", "geometry.spacecraft_to_ground"])
@pytest.mark.parametrize("damage", ["frame", "instant", "nested_frame"])
def test_all_three_frame_and_instant_evidence_references_are_checked(monkeypatch, source, damage):
    _quick(monkeypatch)
    args = _arguments()
    observation = adapter.derive_observation_opportunity_for_engine_step(*list(args.values())[:10])
    frame = args["boresight_frame"].frame
    if damage == "frame":
        broken = _forge(observation, source + ".frame", replace(frame, rotation=replace(frame.rotation,
            initial_phase_rad=replace(frame.rotation.initial_phase_rad, value=.2))))
    elif damage == "instant":
        broken = _forge(observation, source + ".instant.elapsed_seconds", 10.)
    else:
        broken = _forge(observation, source + ".frame.rotation.epoch.fractional_day", 1.)
    calls = []
    def seam(*values):
        calls.append(values)
        return broken
    def forbidden(*values): pytest.fail("inconsistent evidence reached V5.3 candidate")
    monkeypatch.setattr(adapter, "derive_observation_opportunity_for_engine_step", seam)
    monkeypatch.setattr(adapter, "ObservationManeuverCandidate", forbidden)
    with pytest.raises(ValueError): derive(**args)
    assert len(calls) == 1


def test_equal_but_shifted_state_and_direction_instants_reject(monkeypatch):
    _quick(monkeypatch)
    args = _arguments()
    observation = adapter.derive_observation_opportunity_for_engine_step(*list(args.values())[:10])
    for path in ("spacecraft_state.position", "spacecraft_state.velocity", "geometry.spacecraft_to_ground"):
        observation = _forge(observation, path + ".instant.elapsed_seconds", 10.)
    monkeypatch.setattr(adapter, "derive_observation_opportunity_for_engine_step", lambda *values: observation)
    with pytest.raises(ValueError, match="selected step start"): derive(**args)


def test_replace_recomputes_and_no_precomputed_authority_can_be_injected(monkeypatch):
    _quick(monkeypatch)
    args = _arguments(); result = derive(**args)
    calls = []
    for name in ("derive_observation_opportunity_for_engine_step", "CommonFrameBoresightDirection", "ObservationManeuverCandidate"):
        owner = getattr(adapter, name)
        def spy(*values, _name=name, _owner=owner):
            calls.append(_name)
            return _owner(*values)
        monkeypatch.setattr(adapter, name, spy)
    for item in fields(result):
        if item.init: continue
        with pytest.raises(TypeError): Result(**args, **{item.name: None})
        with pytest.raises((TypeError, ValueError), match="init=False"): replace(result, **{item.name: None})
        calls.clear()
        rebuilt = replace(_forge(result, item.name, None))
        assert rebuilt == result and rebuilt.orbit_observation is not result.orbit_observation
        assert calls == ["derive_observation_opportunity_for_engine_step", "CommonFrameBoresightDirection", "ObservationManeuverCandidate"]
    for key in ("state", "geometry", "direction", "candidate"):
        with pytest.raises(TypeError): derive(**args, **{key: None})


@pytest.mark.parametrize("text_type", [PlainText, EqualText, UnequalText])
def test_result_equality_preserves_d1a_and_binding_actual_text_semantics(monkeypatch, text_type):
    _quick(monkeypatch)
    args = _arguments(); original = derive(**args)
    binding = args["boresight_frame"]
    represented = replace(binding, frame_id=ADCSBoresightFrameId(text_type("caller-axes")))
    same = derive(**dict(args, boresight_frame=represented))
    assert same == original and original == same
    different = derive(**dict(args, boresight_frame=replace(binding, frame_id=ADCSBoresightFrameId(text_type("other-axes")))))
    assert different != original and different.orbit_observation == original.orbit_observation
    assert different.inputs.model_manifest == original.inputs.model_manifest
    request = replace(args["request"], request_id=ImagingRequestId(text_type("external-request")),
                      target_id=GroundTargetId(text_type("synthetic")))
    same = derive(**dict(args, request=request, opportunity_id=ObservationOpportunityId(text_type("external-opportunity"))))
    assert same == original and original == same
    changed = derive(**dict(args, opportunity_id=ObservationOpportunityId(text_type("other-opportunity"))))
    assert changed != original
    changed_ray = _forge(original, "common_frame_boresight.x", original.common_frame_boresight.x + .01)
    assert changed_ray != original


def test_production_ast_has_bounded_owner_imports_calls_and_no_generated_ids():
    tree = ast.parse(inspect.getsource(adapter))
    imports = {(node.module, name.name) for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) for name in node.names}
    permitted = {
        "__future__": {"annotations"}, "dataclasses": {"dataclass", "field", "fields"},
        "adcs": {"CommonFrameBoresightDirection"}, "context": {"SimulationInputs"},
        "ids": {"ADCSBoresightFrameId", "ObservationOpportunityId"},
        "observation": {"ImagingRequest"}, "observation_feasibility": {"ObservationManeuverCandidate"},
        "orbit_config": {"FrameDefinition", "FrameKind", "_exact", "_frame", "_instant"},
        "orbit_geometry": {"GroundPointDefinition", "_frame_text"},
        "orbit_observation_opportunity": {"OrbitDerivedObservationOpportunity", "derive_observation_opportunity_for_engine_step"},
        "orbit_visibility": {"GroundVisibilityPolicy"}, "orbit_visibility_windows": {"GroundVisibilitySearchConfig"},
    }
    assert all(module in permitted and name in permitted[module] for module, name in imports)
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    names = [node.func.id for node in calls if isinstance(node.func, ast.Name)]
    assert names.count("derive_observation_opportunity_for_engine_step") == 1
    forbidden = {"project_ground_visibility_to_engine_grid", "find_ground_visibility_windows",
        "evaluate_ground_visibility", "evaluate_two_body_state", "evaluate_ground_point_geometry",
        "compute_boresight_angular_separation", "compute_boresight_transition",
        "evaluate_observation_sequence_feasibility", "ObservationOpportunityCatalog", "ObservationCampaign"}
    assert not forbidden.intersection(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
    id_calls = [node for node in calls if isinstance(node.func, ast.Name) and node.func.id.endswith("Id")]
    assert len(id_calls) == 1 and id_calls[0].func.id == "ADCSBoresightFrameId"
    assert ast.unparse(id_calls[0].args[0]) == "self.frame_id.value"
    assert not any(isinstance(node, ast.Try) for node in ast.walk(tree))
