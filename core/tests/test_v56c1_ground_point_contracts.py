"""C1 ownership/provenance tests; no alteration of legacy V5 interfaces."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import inspect
import math

import pytest

from ops_sim.v5.frames import CartesianPosition, CartesianState, CartesianVelocity
from ops_sim.v5.ids import GroundStationId, GroundTargetId, ParameterId, SourceRecordId, WorldId
from ops_sim.v5.orbit_config import FrameKind, GeometryInstant, GeodeticLocation
from ops_sim.v5.orbit_geometry import GroundPointDefinition, GroundPointGeometry, evaluate_ground_point_geometry
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import SensitivityRange
from test_v56a_time_frame_contracts import _model, _sphere, _parameter
from test_v56b1_two_body_contracts import _forge
from test_v56b2_orbit_binding import PlainText, ComparisonText


def _point(*, ellipsoid=None, latitude=0., longitude=0., height=0., identity=None):
    return GroundPointDefinition(
        GroundStationId("synthetic") if identity is None else identity,
        _sphere(1.) if ellipsoid is None else ellipsoid,
        _parameter("orbit.ground-point.geodetic-latitude", "rad", latitude),
        _parameter("orbit.ground-point.east-longitude", "rad", longitude),
        _parameter("orbit.ground-point.ellipsoidal-height", "m", height))


def _state(point=None, *, r=(1., 1., 0.), v=(-1., 1., 0.), phase=0., rate=0., t=0.):
    point = _point() if point is None else point
    _, frame = _model(ellipsoid=point.ellipsoid, phase=phase, rate=rate)
    when = GeometryInstant(frame.rotation.epoch, t)
    return CartesianState(CartesianPosition(frame, when, r), CartesianVelocity(frame, when, v))


def test_required_frozen_slotted_public_contract_and_recomputed_outputs():
    point, state = _point(), _state()
    assert tuple(f.name for f in fields(GroundPointDefinition)) == (
        "point_id", "ellipsoid", "latitude_rad", "longitude_rad", "ellipsoidal_height_m")
    for cls in (GroundPointDefinition, GroundPointGeometry):
        assert cls.__dataclass_params__.frozen
        assert all(p.default is inspect.Parameter.empty for p in inspect.signature(cls).parameters.values())
    assert tuple(inspect.signature(evaluate_ground_point_geometry).parameters) == ("point", "spacecraft_state")
    assert tuple(inspect.signature(GroundPointGeometry).parameters) == ("point", "spacecraft_state")
    result = evaluate_ground_point_geometry(point, state)
    assert not hasattr(result, "__dict__") and not hasattr(point, "__dict__")
    assert isinstance(point.geodetic_location, GeodeticLocation)
    with pytest.raises(FrozenInstanceError):
        result.slant_range_m = 9
    with pytest.raises(TypeError):
        GroundPointGeometry(point, state, slant_range_m=9)
    damaged = _forge(result, "slant_range_m", 999.)
    assert replace(damaged) == result
    moved = replace(point, ellipsoidal_height_m=replace(point.ellipsoidal_height_m, value=.2))
    assert replace(result, point=moved) == evaluate_ground_point_geometry(moved, state)
    assert result.point == point and result.spacecraft_state == state
    assert all(not hasattr(result, name) for name in ("visible", "feasible", "serviceable"))


@pytest.mark.parametrize("cls", [GroundStationId, GroundTargetId])
def test_exact_supported_ids_and_same_id_different_content(cls):
    point = _point(identity=cls("synthetic"))
    changed = replace(point, latitude_rad=replace(point.latitude_rad, value=.1))
    assert changed.point_id == point.point_id and changed != point
    assert evaluate_ground_point_geometry(changed, _state()) != evaluate_ground_point_geometry(point, _state())


@pytest.mark.parametrize("identity", ["synthetic", WorldId("synthetic"), None])
def test_other_id_types_rejected(identity):
    with pytest.raises(TypeError):
        replace(_point(), point_id=identity)


@pytest.mark.parametrize("field", ["latitude_rad", "longitude_rad", "ellipsoidal_height_m"])
@pytest.mark.parametrize("damage", ["units", "identity", "bool", "nan", "lossy", "bounds"])
def test_coordinate_parameter_validation_reaches_authoritative_guard(field, damage):
    point = _point()
    parameter = getattr(point, field)
    paths = {"units": ("provenance.units", "wrong"), "identity": ("provenance.parameter_id", ParameterId("wrong")),
             "bool": ("value", True), "nan": ("value", math.nan), "lossy": ("value", 2**53+1),
             "bounds": ("provenance.sensitivity_range", SensitivityRange(2., 3.))}
    path, value = paths[damage]
    damaged = _forge(point, field, _forge(parameter, path, value))
    with pytest.raises((TypeError, ValueError)):
        evaluate_ground_point_geometry(damaged, _state())


@pytest.mark.parametrize("latitude,longitude,height", [
    (math.pi/2, -math.pi, -.5), (-math.pi/2, 0., .2), (0., math.nextafter(math.pi, 0.), 1.)])
def test_a_coordinate_endpoints_and_supported_negative_height(latitude, longitude, height):
    p = _point(latitude=latitude, longitude=longitude, height=height)
    assert (p.geodetic_location.latitude_rad, p.geodetic_location.longitude_rad,
            p.geodetic_location.ellipsoidal_height_m) == (latitude, longitude, height)


@pytest.mark.parametrize("field,value", [
    ("latitude_rad", Fraction(math.pi/2)+Fraction(1, 10**100)),
    ("longitude_rad", math.pi), ("ellipsoidal_height_m", -1.),
    ("latitude_rad", Fraction(1, 10**400)), ("ellipsoidal_height_m", math.inf)])
def test_original_numeric_domain_is_not_repaired_by_rounding(field, value):
    p = _point()
    damaged = _forge(p, field+".value", value)
    with pytest.raises((TypeError, ValueError)):
        damaged.geodetic_location


_TEXT_PATHS = ["ellipsoid.name", "point_id.value"] + [
    p+".provenance."+f for p in ("latitude_rad", "longitude_rad", "ellipsoidal_height_m",
                                 "ellipsoid.equatorial_radius_m", "ellipsoid.flattening")
    for f in ("rationale", "derivation", "units", "parameter_id.value")]


@pytest.mark.parametrize("path", _TEXT_PATHS)
@pytest.mark.parametrize("kind", ["plain", "comparison", "high", "low", "pair"])
def test_complete_point_text_rejects_noncanonical_values(path, kind):
    p = _point()
    original = p
    for part in path.split("."):
        original = getattr(original, part)
    value = original if original is not None else "Otherwise valid text"
    bad = {"plain": PlainText(value), "comparison": ComparisonText(value),
           "high": "Test \ud800", "low": "Test \udfff", "pair": "Test \ud83d\ude80"}[kind]
    with pytest.raises((TypeError, ValueError)):
        evaluate_ground_point_geometry(_forge(p, path, bad), _state())


@pytest.mark.parametrize("side", ["position", "velocity"])
@pytest.mark.parametrize("parameter", ["ellipsoid.equatorial_radius_m", "ellipsoid.flattening",
                                      "rotation.initial_phase_rad", "rotation.angular_velocity_rad_per_s"])
@pytest.mark.parametrize("field", ["rationale", "derivation", "source_ids"])
def test_both_state_frames_reject_hidden_metadata(side, parameter, field):
    value = ((SourceRecordId(PlainText("synthetic")),) if field == "source_ids"
             else ComparisonText("Hidden metadata"))
    bad = _forge(_state(), side+".frame."+parameter+".provenance."+field, value)
    with pytest.raises(TypeError, match="exact str"):
        evaluate_ground_point_geometry(_point(), bad)


@pytest.mark.parametrize("text", ["ASCII", "Кириллица", "Test \U0001f680", "Caf\u00e9", "Cafe\u0301"])
def test_supported_unicode_metadata_is_retained_exactly(text):
    p = _point()
    parameter = replace(p.latitude_rad, provenance=replace(p.latitude_rad.provenance, rationale=text))
    p = replace(p, latitude_rad=parameter)
    assert evaluate_ground_point_geometry(p, _state()).point.latitude_rad.provenance.rationale == text


def test_complete_ellipsoid_frame_and_instant_matching_and_forged_numeric_state():
    p, s = _point(), _state()
    for bad in (
        _forge(s, "position.frame.kind", FrameKind.EARTH_FIXED),
        _forge(s, "velocity.instant.elapsed_seconds", 1.),
        _forge(s, "velocity.frame.ellipsoid.name", "Different valid name"),
        _forge(s, "position.components_m", (True, 1., 0.)),
        _forge(s, "velocity.components_m_per_s", (math.inf, 1., 0.)),
    ):
        with pytest.raises((TypeError, ValueError)):
            evaluate_ground_point_geometry(p, bad)
    with pytest.raises(ValueError, match="ellipsoid"):
        evaluate_ground_point_geometry(replace(p, ellipsoid=replace(p.ellipsoid, name="Different")), s)
    with pytest.raises(TypeError):
        evaluate_ground_point_geometry(p, s.position)


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
def test_documented_numerical_domain_failures(r, v, message):
    with pytest.raises(ValueError, match=message):
        evaluate_ground_point_geometry(_point(), _state(r=r, v=v))


def test_repeatability_purity_and_no_legacy_records():
    p, s = _point(), _state()
    before = deepcopy((p, s))
    first = evaluate_ground_point_geometry(p, s)
    assert first == evaluate_ground_point_geometry(p, s) and (p, s) == before
    assert not hasattr(first, "observation_pointing") and not hasattr(first, "contact")


@pytest.mark.parametrize("text", ["Test \U0001f680", "Caf\u00e9", "Cafe\u0301"])
def test_both_supplied_state_frames_retain_full_valid_metadata(text):
    state = _state()
    for side in ("position", "velocity"):
        state = _forge(state, side+".frame.rotation.initial_phase_rad.provenance.rationale", text)
    g = evaluate_ground_point_geometry(_point(), state)
    for side in ("position", "velocity"):
        assert getattr(g.spacecraft_state, side).frame.rotation.initial_phase_rad.provenance.rationale == text
    assert g.spacecraft_state == state


@pytest.mark.parametrize("side", ["position", "velocity"])
@pytest.mark.parametrize("text", ["Test \ud800", "Test \udfff", "Test \ud83d\ude80"])
def test_state_frame_surrogates_cannot_reach_equality(side, text):
    state = _forge(_state(), side+".frame.rotation.initial_phase_rad.provenance.derivation", text)
    with pytest.raises(ValueError, match="Unicode scalar values"):
        evaluate_ground_point_geometry(_point(), state)


def test_subclass_id_type_and_subclass_point_are_not_accepted():
    class Station(GroundStationId):
        pass
    class Point(GroundPointDefinition):
        pass
    with pytest.raises(TypeError):
        _point(identity=Station("synthetic"))
    p = _point()
    with pytest.raises(TypeError):
        evaluate_ground_point_geometry(Point(p.point_id, p.ellipsoid, p.latitude_rad,
                                             p.longitude_rad, p.ellipsoidal_height_m), _state())
