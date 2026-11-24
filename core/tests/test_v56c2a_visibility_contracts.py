"""C2a public evidence, adversarial validation and real B2 restart contracts."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import ast
import inspect
import json
import math

import pytest

from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.context import evaluate_context_coast, with_coast_orbit
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.ids import ParameterId, SourceRecordId
from ops_sim.v5.orbit_binding import CoastOrbitInputs
from ops_sim.v5.orbit_config import FrameKind
from ops_sim.v5.orbit_geometry import GroundPointDefinition, evaluate_ground_point_geometry
from ops_sim.v5.orbit_visibility import (
    GroundVisibilityPolicy, GroundVisibilityResult, GroundVisibilityStatus as V,
    LineOfSightStatus as L, ElevationStatus as E, evaluate_ground_visibility,
)
from ops_sim.v5.provenance import ProvenanceStatus, SensitivityRange
import ops_sim.v5.orbit_visibility as visibility_module
import ops_sim.v5.orbit as orbit_module
import ops_sim.v5.context as context_module
from test_v56a_time_frame_contracts import _parameter
from test_v56b1_two_body_contracts import _forge
from test_v56b2_orbit_binding import PlainText, ComparisonText
from test_v56b2_checkpoint_binding import _bound, generic_context
from test_v56c1_ground_point_contracts import _point, _state, _TEXT_PATHS


def _policy(value):
    return GroundVisibilityPolicy(_parameter("orbit.visibility.minimum-elevation", "rad", value))


def test_public_required_frozen_slotted_and_recomputed_evidence():
    p, s, policy = _point(), _state(), _policy(0.)
    assert tuple(f.name for f in fields(GroundVisibilityPolicy)) == ("minimum_elevation_rad",)
    for cls in (GroundVisibilityPolicy, GroundVisibilityResult):
        assert cls.__dataclass_params__.frozen
        assert all(x.default is inspect.Parameter.empty for x in inspect.signature(cls).parameters.values())
    assert tuple(inspect.signature(evaluate_ground_visibility).parameters) == ("point", "spacecraft_state", "policy")
    assert tuple(inspect.signature(GroundVisibilityResult).parameters) == ("point", "spacecraft_state", "policy")
    result = evaluate_ground_visibility(p, s, policy)
    assert not hasattr(policy, "__dict__") and not hasattr(result, "__dict__")
    assert result.point == p and result.spacecraft_state == s and result.policy == policy
    assert result.geometry == evaluate_ground_point_geometry(p, s)
    assert result.geometry.ground_state.position.instant == s.position.instant
    assert result.geometry.ground_state.position.frame == s.position.frame
    with pytest.raises(FrozenInstanceError): result.status = V.VISIBLE
    for name in ("geometry", "status", "elevation_margin_rad", "minimum_level"):
        with pytest.raises(TypeError): GroundVisibilityResult(p, s, policy, **{name: None})
        assert replace(_forge(result, name, None)) == result
    assert replace(result, policy=_policy(-.1)) == evaluate_ground_visibility(p, s, _policy(-.1))
    assert all(not hasattr(result, name) for name in ("visible", "serviceable", "contact", "window", "opportunity"))


@pytest.mark.parametrize("value", [-math.pi/2, math.pi/2, 0., -.4, Fraction(1, 4)])
def test_policy_explicit_supported_thresholds(value):
    policy = _policy(value)
    assert policy.minimum_elevation_rad.value == float(value)
    assert policy.minimum_elevation_rad.provenance.units == "rad"


@pytest.mark.parametrize("value", [True, False, math.nan, math.inf, -math.inf, 2**53+1,
    Fraction(1, 10**400), Fraction(math.pi/2)+Fraction(1, 10**100),
    -Fraction(math.pi/2)-Fraction(1, 10**100), math.nextafter(math.pi/2, math.inf), "0", None])
def test_original_real_numeric_domain_rejected_without_repair(value):
    forged = _forge(_policy(0.), "minimum_elevation_rad.value", value)
    with pytest.raises((TypeError, ValueError)):
        evaluate_ground_visibility(_point(), _state(), forged)


@pytest.mark.parametrize("path,value", [
    ("provenance.parameter_id", ParameterId("wrong")), ("provenance.units", "deg"),
    ("provenance.classification", "EXPLICIT_MODEL_ASSUMPTION"), ("provenance.status", "VERIFIED"),
    ("provenance.rationale", None), ("provenance.source_ids", []),
    ("provenance.source_ids", (SourceRecordId("same"), SourceRecordId("same"))),
    ("provenance.status", ProvenanceStatus.REJECTED), ("provenance.status", ProvenanceStatus.SUPERSEDED),
    ("provenance.sensitivity_range", SensitivityRange(1., 2.)),
    ("provenance.sensitivity_range", _forge(SensitivityRange(-1., 1.), "lower", True)),
    ("provenance", None),
])
def test_complete_policy_provenance_graph_is_revalidated(path, value):
    bad = _forge(_policy(0.), "minimum_elevation_rad."+path, value)
    with pytest.raises((TypeError, ValueError)):
        evaluate_ground_visibility(_point(), _state(), bad)


@pytest.mark.parametrize("path", ["parameter_id.value", "units", "rationale", "derivation", "source_ids"])
@pytest.mark.parametrize("kind", ["plain", "comparison", "high", "low", "pair"])
def test_policy_exact_scalar_unicode_text(path, kind):
    policy = _policy(0.)
    valid = {"parameter_id.value": "orbit.visibility.minimum-elevation", "units": "rad"}.get(path, "Evidence")
    bad = {"plain": PlainText(valid), "comparison": ComparisonText(valid),
           "high": "Bad \ud800", "low": "Bad \udfff", "pair": "Bad \ud83d\ude80"}[kind]
    if path == "source_ids": bad = (_forge(SourceRecordId("evidence"), "value", bad),)
    policy = _forge(policy, "minimum_elevation_rad.provenance."+path, bad)
    with pytest.raises((TypeError, ValueError)):
        evaluate_ground_visibility(_point(), _state(), policy)


@pytest.mark.parametrize("path", _TEXT_PATHS)
@pytest.mark.parametrize("value", [ComparisonText("Evidence"), "Bad \ud800", "Bad \udfff"])
def test_c1_complete_point_evidence_is_not_bypassed(path, value):
    with pytest.raises((TypeError, ValueError)):
        evaluate_ground_visibility(_forge(_point(), path, value), _state(), _policy(0.))


@pytest.mark.parametrize("side", ["position", "velocity"])
@pytest.mark.parametrize("parameter", ["ellipsoid.equatorial_radius_m", "ellipsoid.flattening",
                                      "rotation.initial_phase_rad", "rotation.angular_velocity_rad_per_s"])
@pytest.mark.parametrize("path,value", [
    ("rationale", ComparisonText("Hidden metadata")), ("derivation", PlainText("Hidden metadata")),
    ("source_ids", (SourceRecordId(PlainText("evidence")),)),
    ("rationale", "Bad \ud800"), ("derivation", "Bad \udfff"), ("derivation", "Bad \ud83d\ude80")])
def test_both_state_frames_validate_text_before_equality(side, parameter, path, value):
    bad = _forge(_state(), side+".frame."+parameter+".provenance."+path, value)
    with pytest.raises((TypeError, ValueError)):
        evaluate_ground_visibility(_point(), bad, _policy(0.))


@pytest.mark.parametrize("text", ["ASCII", "\u041a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0430", "Test \U0001f680", "Caf\u00e9", "Cafe\u0301"])
def test_valid_policy_and_point_text_is_retained_without_normalization(text):
    p, policy = _point(), _policy(0.)
    p = _forge(p, "latitude_rad.provenance.rationale", text)
    policy = _forge(policy, "minimum_elevation_rad.provenance.rationale", text)
    result = evaluate_ground_visibility(p, _state(), policy)
    assert result.point.latitude_rad.provenance.rationale == text
    assert result.policy.minimum_elevation_rad.provenance.rationale == text


def test_subclasses_and_other_input_types_rejected():
    class Policy(GroundVisibilityPolicy): pass
    class Point(GroundPointDefinition): pass
    p, s, policy = _point(), _state(), _policy(0.)
    for args in ((p, s, None), (p, s, Policy(policy.minimum_elevation_rad)),
                 (None, s, policy), (Point(*(getattr(p, f.name) for f in fields(p))), s, policy),
                 (p, s.position, policy)):
        with pytest.raises((TypeError, ValueError)): evaluate_ground_visibility(*args)


@pytest.mark.parametrize("path,value", [
    ("position.frame.kind", FrameKind.EARTH_FIXED), ("velocity.instant.elapsed_seconds", 1.),
    ("velocity.frame.ellipsoid.name", "Different"), ("position.frame.ellipsoid.name", "Different"),
    ("position.instant.epoch.julian_day", 2451546), ("velocity.frame.rotation.epoch.julian_day", 2451546),
    ("velocity.frame.rotation.initial_phase_rad.value", .1),
    ("position.components_m", (True, 1., 0.)), ("velocity.components_m_per_s", (math.inf, 1., 0.)),
])
def test_full_shape_frame_epoch_numeric_state_compatibility(path, value):
    with pytest.raises((TypeError, ValueError)):
        evaluate_ground_visibility(_point(), _forge(_state(), path, value), _policy(0.))


@pytest.mark.parametrize("r,v,message", [
    ((1., 0., 0.), (0., 1., 0.), "separation is zero"),
    ((math.nextafter(1., 2.), 0., 0.), (0., 1., 0.), "separation is numerically"),
    ((0., 0., 0.), (0., 1., 0.), "radius is zero"),
    ((2., 0., 0.), (0., 0., 0.), "velocity is zero"),
    ((2., 0., 0.), (1., 0., 0.), "radial motion"),
    ((2., 0., 0.), (1., 1e-16, 0.), "basis is numerically"),
    ((1.5e308, 1.5e308, 1.5e308), (-1., 1., 0.), "finite binary64"),
    ((2., 1., 0.), (1e300, 1e-300, 0.), "underflows"),
])
def test_c1_numeric_errors_propagate_unchanged(r, v, message):
    with pytest.raises(ValueError, match=message):
        evaluate_ground_visibility(_point(), _state(r=r, v=v), _policy(0.))


def test_phase_envelope_failure_is_not_invisibility():
    with pytest.raises(ValueError, match="accumulated-phase"):
        evaluate_ground_visibility(_point(), _state(rate=1., t=2**20+1.), _policy(0.))


def test_component_vocabulary_and_all_sixteen_conjunctions():
    assert {x.value for x in V} == {"VISIBLE", "NOT_VISIBLE", "BOUNDARY", "UNRESOLVED"}
    assert {x.value for x in L} == {"CLEAR", "BLOCKED", "BOUNDARY", "UNRESOLVED"}
    assert {x.value for x in E} == {"ABOVE", "BELOW", "BOUNDARY", "UNRESOLVED"}
    expected = [
        [V.VISIBLE, V.NOT_VISIBLE, V.BOUNDARY, V.UNRESOLVED],
        [V.NOT_VISIBLE]*4,
        [V.BOUNDARY, V.NOT_VISIBLE, V.BOUNDARY, V.UNRESOLVED],
        [V.UNRESOLVED, V.NOT_VISIBLE, V.UNRESOLVED, V.UNRESOLVED],
    ]
    for los, row in zip(L, expected):
        for elevation, status in zip(E, row):
            assert visibility_module._combine(los, elevation) is status


def test_no_propagator_import_and_no_exception_to_hidden_conversion():
    tree = ast.parse(inspect.getsource(visibility_module))
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert "orbit" not in imports and "context" not in imports and "engine" not in imports
    assert not any(isinstance(n, ast.ExceptHandler) for n in ast.walk(tree))


def test_explicit_b2_query_schema5_json_restart_external_point_and_policy(monkeypatch):
    context = _bound()
    inputs, before = context.inputs, deepcopy(context)
    state = evaluate_context_coast(context)
    point = _point(ellipsoid=state.position.frame.ellipsoid, latitude=.25, longitude=.5, height=20.)
    policy = _policy(-.2)
    original_arguments = deepcopy((point, state, policy))
    checkpoint = CheckpointState.from_context(context).to_dict()
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(inputs.coast_orbit.to_dict(), allow_nan=False)))
    restored = CheckpointState.from_dict(json.loads(json.dumps(checkpoint, allow_nan=False))).restore(
        with_coast_orbit(generic_context().inputs, coast))
    replay_state = evaluate_context_coast(restored)
    replay_point = _point(ellipsoid=coast.trajectory.initial_state.position.frame.ellipsoid,
                          latitude=.25, longitude=.5, height=20.)
    replay_policy = _policy(-.2)
    assert replay_point is not point and replay_policy is not policy and coast is not inputs.coast_orbit
    def fail(*args, **kwargs): pytest.fail("Unexpected implicit geometry or propagation")
    with monkeypatch.context() as guard:
        guard.setattr(context_module, "evaluate_two_body_state", fail)
        guard.setattr(orbit_module, "evaluate_two_body_state", fail)
        result = evaluate_ground_visibility(point, state, policy)
        assert evaluate_ground_visibility(replay_point, replay_state, replay_policy) == result
        assert evaluate_ground_visibility(point, state, policy) == result
        for changed_point, changed_policy in (
            (replace(point, longitude_rad=replace(point.longitude_rad, value=.6)), policy),
            (_forge(point, "latitude_rad.provenance.rationale", "Different point evidence"), policy),
            (point, _policy(.1)),
            (point, _forge(policy, "minimum_elevation_rad.provenance.rationale", "Different mask evidence")),
        ):
            changed = evaluate_ground_visibility(changed_point, state, changed_policy)
            assert changed != result and changed.point.point_id == result.point.point_id
            assert context.inputs.model_manifest == inputs.model_manifest
            assert CheckpointState.from_context(context).to_dict() == checkpoint
    assert (point, state, policy) == original_arguments
    assert context == before and context.inputs is inputs and checkpoint["schema_version"] == 5
    with monkeypatch.context() as guard:
        guard.setattr(visibility_module, "evaluate_ground_visibility", fail)
        SimulationEngine().step(context)
    assert context.inputs is inputs
