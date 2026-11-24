"""V5.6A domain, provenance, split-TT and standalone compatibility contracts."""

from dataclasses import FrozenInstanceError, fields, replace
from enum import Enum
from fractions import Fraction
import inspect
import math
from pathlib import Path

import numpy as np
import pytest

from ops_sim.v5.ids import ParameterId, SourceRecordId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance, ProvenanceClass, ProvenanceStatus, SensitivityRange,
)
import ops_sim.v5.orbit_config as config
import ops_sim.v5.frames as frames
from ops_sim.v5.orbit_config import (
    TTEpoch, GeometryInstant, ReferenceEllipsoid, GeodeticLocation,
    FrameKind, FrameDefinition, UniformRotationDefinition, tt_date_at,
    elapsed_seconds_between, wgs84_reference_ellipsoid, nominal_earth_angular_velocity,
)
from ops_sim.v5.frames import (
    CartesianPosition, CartesianVelocity, CartesianDirection, CartesianState,
    transform_position, transform_direction, transform_state, rotation_angle,
    geodetic_position, geodetic_normal,
)


def _parameter(identifier, units, value):
    return ScalarParameter(value, ParameterProvenance(
        ParameterId(identifier), ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
        units, (), ProvenanceStatus.VERIFIED, rationale="Synthetic analytical verification input",
    ))


def _model(*, phase=0.0, rate=0.0, ellipsoid=None, epoch=None):
    ellipsoid = wgs84_reference_ellipsoid() if ellipsoid is None else ellipsoid
    epoch = TTEpoch(2451545, 0.0) if epoch is None else epoch  # Explicit synthetic fixture.
    rotation = UniformRotationDefinition(
        epoch, _parameter("orbit.rotation.initial-phase", "rad", phase),
        _parameter("orbit.rotation.angular-rate", "rad/s", rate),
    )
    return (FrameDefinition(FrameKind.EARTH_FIXED, ellipsoid, rotation),
            FrameDefinition(FrameKind.MODEL_INERTIAL, ellipsoid, rotation))


def _sphere(radius=10.0, flattening=0.0):
    return ReferenceEllipsoid(
        "Synthetic", _parameter("orbit.earth.equatorial-radius", "m", radius),
        _parameter("orbit.earth.flattening", "1", flattening),
    )


def _forge(value, field, damaged):
    result = object.__new__(type(value))
    for item in fields(value):
        object.__setattr__(result, item.name, getattr(value, item.name))
    object.__setattr__(result, field, damaged)
    return result


def _state(frame, instant):
    return CartesianState(CartesianPosition(frame, instant, (1.0, 2.0, 3.0)),
                          CartesianVelocity(frame, instant, (4.0, 5.0, 6.0)))


def test_all_public_value_fields_are_required_frozen_and_slotted():
    expected = {
        TTEpoch: ("julian_day", "fractional_day"),
        GeometryInstant: ("epoch", "elapsed_seconds"),
        ReferenceEllipsoid: ("name", "equatorial_radius_m", "flattening"),
        GeodeticLocation: ("ellipsoid", "latitude_rad", "longitude_rad", "ellipsoidal_height_m"),
        UniformRotationDefinition: ("epoch", "initial_phase_rad", "angular_velocity_rad_per_s"),
        FrameDefinition: ("kind", "ellipsoid", "rotation"),
        CartesianPosition: ("frame", "instant", "components_m"),
        CartesianVelocity: ("frame", "instant", "components_m_per_s"),
        CartesianDirection: ("frame", "instant", "components"),
        CartesianState: ("position", "velocity"),
    }
    for cls, names in expected.items():
        assert tuple(f.name for f in fields(cls)) == names
        assert cls.__dataclass_params__.frozen
        assert cls.__slots__ == names
        assert all(p.default is inspect.Parameter.empty for p in inspect.signature(cls).parameters.values())
    epoch = TTEpoch(2451545, 0)
    with pytest.raises(FrozenInstanceError):
        epoch.julian_day = 1
    assert type(epoch.fractional_day) is float
    assert epoch == TTEpoch(2451545, -0.0)
    assert math.copysign(1.0, TTEpoch(0, -0.0).fractional_day) == 1.0


def test_public_function_signatures_are_explicit_without_defaults():
    expected = {
        tt_date_at: ("epoch", "elapsed_seconds"),
        elapsed_seconds_between: ("epoch", "date"),
        rotation_angle: ("rotation", "instant"),
        transform_position: ("position", "target_frame"),
        transform_direction: ("direction", "target_frame"),
        transform_state: ("state", "target_frame"),
        geodetic_position: ("location", "frame", "instant"),
        geodetic_normal: ("location", "frame", "instant"),
        wgs84_reference_ellipsoid: (), nominal_earth_angular_velocity: (),
    }
    for function, names in expected.items():
        signature = inspect.signature(function)
        assert tuple(signature.parameters) == names
        assert all(p.default is inspect.Parameter.empty for p in signature.parameters.values())


@pytest.mark.parametrize(("day", "fraction", "error"), [
    (True, 0, TypeError), (1.0, 0, TypeError), (np.int64(1), 0, TypeError),
    (2**31, 0, ValueError), (-(2**31), 0, ValueError),
    (1, True, TypeError), (1, "0", TypeError), (1, -0.1, ValueError),
    (1, 1.0, ValueError), (1, math.nan, ValueError), (1, math.inf, ValueError),
])
def test_invalid_tt_epoch(day, fraction, error):
    with pytest.raises(error):
        TTEpoch(day, fraction)


@pytest.mark.parametrize(("fraction", "elapsed", "day", "result"), [
    (0.0, 43200.0, 11, 0.5), (0.75, 43200.0, 12, 0.25),
    (0.25, -43200.0, 10, 0.75), (0.0, -86400.0, 10, 0.0),
    (0.5, 0.125, 11, 0.5 + 0.125 / 86400),
])
def test_split_tt_fraction_and_day_carry(fraction, elapsed, day, result):
    epoch = TTEpoch(11, fraction)
    date = tt_date_at(epoch, elapsed)
    assert date == TTEpoch(day, result)
    # Two rounded fractional days contribute at most ~9.6 ps to a difference.
    assert elapsed_seconds_between(epoch, date) == pytest.approx(elapsed, rel=0, abs=1e-11)


def test_small_offset_survives_large_jd_and_subresolution_rounding_is_explicit():
    epoch = TTEpoch(2451545, 0.5)
    seconds = 1e-6
    assert (2451545.5 + seconds / 86400) == 2451545.5
    date = tt_date_at(epoch, seconds)
    assert date != epoch
    assert elapsed_seconds_between(epoch, date) == pytest.approx(seconds, rel=0, abs=1e-11)
    assert tt_date_at(epoch, 1e-15) == epoch
    assert tt_date_at(TTEpoch(11, 0), -1e-15) == TTEpoch(11, 0)


def test_time_representation_limits_are_separate_from_a_mission_horizon():
    bound = 2**40
    for elapsed in (-bound, bound):
        epoch = TTEpoch(0, 0.5)
        assert elapsed_seconds_between(epoch, tt_date_at(epoch, elapsed)) == elapsed
    assert math.ulp(float(bound)) == 2**-12  # seconds, 244.140625 microseconds.
    with pytest.raises(ValueError, match="envelope"):
        GeometryInstant(TTEpoch(0, 0), math.nextafter(float(bound), math.inf))
    with pytest.raises(ValueError, match="integer-day"):
        tt_date_at(TTEpoch(2**31 - 1, 0.5), 86400)
    with pytest.raises(ValueError, match="integer-day"):
        tt_date_at(TTEpoch(-(2**31 - 1), 0), -1)
    with pytest.raises(ValueError, match="envelope"):
        elapsed_seconds_between(TTEpoch(-2**31 + 1, 0), TTEpoch(2**31 - 1, 0))
    epoch = TTEpoch(0, 0.5)
    edge = tt_date_at(epoch, bound)
    beyond = replace(edge, fractional_day=edge.fractional_day + math.ulp(float(bound))/86400)
    with pytest.raises(ValueError, match="envelope"):
        elapsed_seconds_between(epoch, beyond)


@pytest.mark.parametrize("value", [True, "1", math.nan, math.inf, -math.inf, 2**53 + 1, 10**400])
def test_elapsed_invalid_and_lossy_integers_reject(value):
    with pytest.raises((TypeError, ValueError)):
        GeometryInstant(TTEpoch(0, 0), value)


def test_numeric_real_normalization_preserves_existing_engine_separation():
    instant = GeometryInstant(TTEpoch(10, np.float64(0.5)), np.float64(0.125))
    assert type(instant.elapsed_seconds) is float
    fixed, _ = _model(epoch=instant.epoch)
    position = CartesianPosition(fixed, instant, (np.int64(4), np.float64(5), 6))
    assert all(type(x) is float for x in position.components_m)
    with pytest.raises(ValueError, match="integer precision"):
        CartesianPosition(fixed, instant, (2**53 + 1, 0, 0))
    # Existing engine owns exact integer time; new geometry never changes it.
    from examples.v52_integrated_eps_thermal_demo import build_demo_context
    context = build_demo_context()
    before = context.simulation_time_seconds
    assert type(before) is int
    with pytest.raises(TypeError):
        replace(context, simulation_time_seconds=0.125)
    assert context.simulation_time_seconds == before


def test_wgs84_parameters_have_precise_source_and_derivation():
    earth = wgs84_reference_ellipsoid()
    assert earth.equatorial_radius_m.value == 6378137.0
    assert earth.flattening.value == 1 / 298.257223563
    assert earth.polar_radius_m == 6378137.0 * (1 - 1 / 298.257223563)
    assert earth.eccentricity_squared == earth.flattening.value * (2 - earth.flattening.value)
    rate = nominal_earth_angular_velocity()
    assert rate.value == 7.292115e-5
    for parameter in (earth.equatorial_radius_m, earth.flattening, rate):
        assert parameter.provenance.source_ids == (SourceRecordId("nga-wgs84-defining-parameters"),)
        assert parameter.provenance.status is ProvenanceStatus.VERIFIED
    assert earth.equatorial_radius_m.provenance.classification is ProvenanceClass.PUBLIC_SPECIFICATION
    assert rate.provenance.classification is ProvenanceClass.PUBLIC_SPECIFICATION
    assert earth.flattening.provenance.classification is ProvenanceClass.DERIVED_VALUE
    assert "298.257223563" in earth.flattening.provenance.derivation


@pytest.mark.parametrize(("a", "f"), [
    (0, 0), (-1, 0), (1, -0.1), (1, 1),
    (1, math.nextafter(1.0, 0.0)), (1e308, 0.5), (5e-324, 0.5),
])
def test_ellipsoid_domain_rejects_degeneracy_and_derived_overflow(a, f):
    with pytest.raises(ValueError):
        _sphere(a, f)


def test_ellipsoid_conditioning_boundary_and_negative_height_domain():
    f = 1 - 2**-20
    earth = _sphere(10.0, f)
    assert earth.polar_radius_m == 10 * 2**-20
    with pytest.raises(ValueError, match="conditioning"):
        _sphere(10.0, math.nextafter(f, 1.0))
    earth = wgs84_reference_ellipsoid()
    boundary = -earth.equatorial_radius_m.value * (1 - earth.flattening.value)**2
    GeodeticLocation(earth, 0.4, -0.3, -350.25)
    GeodeticLocation(earth, 0.4, -0.3, math.nextafter(boundary, math.inf))
    with pytest.raises(ValueError, match="inward"):
        GeodeticLocation(earth, 0.4, -0.3, boundary)


@pytest.mark.parametrize(("lat", "lon", "height"), [
    (math.nextafter(math.pi/2, math.inf), 0, 0), (-2, 0, 0),
    (0, math.pi, 0), (0, -4, 0), (math.nan, 0, 0),
    (0, 0, math.inf), (True, 0, 0), (0, False, 0), (0, 0, True),
])
def test_geodetic_strict_ranges_and_required_height(lat, lon, height):
    with pytest.raises((TypeError, ValueError)):
        GeodeticLocation(wgs84_reference_ellipsoid(), lat, lon, height)


def test_geographic_and_rotation_constructors_have_no_implicit_height_epoch_or_phase():
    with pytest.raises(TypeError):
        GeodeticLocation(wgs84_reference_ellipsoid(), 0, 0)
    with pytest.raises(TypeError):
        UniformRotationDefinition()
    for phase in (math.pi, -4.0):
        with pytest.raises(ValueError, match="phase"):
            _model(phase=phase)
    fixed, _ = _model(rate=-1)
    assert fixed.rotation.angular_velocity_rad_per_s.value == -1
    with pytest.raises(TypeError):
        replace(fixed, kind="EARTH_FIXED")


@pytest.mark.parametrize("damage", ["units", "id", "status", "source", "duplicates", "derivation", "rationale", "bounds", "bool"])
def test_forged_nested_provenance_rejects_at_public_transform(damage):
    fixed, inertial = _model()
    parameter = fixed.ellipsoid.equatorial_radius_m
    p = parameter.provenance
    if damage == "units": p = _forge(p, "units", "km")
    if damage == "id": p = _forge(p, "parameter_id", _forge(p.parameter_id, "value", "BAD ID"))
    if damage == "status": p = _forge(p, "status", ProvenanceStatus.REJECTED)
    if damage == "source": p = _forge(p, "source_ids", (_forge(p.source_ids[0], "value", "BAD"),))
    if damage == "duplicates": p = _forge(p, "source_ids", p.source_ids * 2)
    if damage == "derivation": p = _forge(p, "classification", ProvenanceClass.DERIVED_VALUE)
    if damage == "rationale": p = _forge(p, "classification", ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION)
    if damage == "bounds": p = _forge(p, "sensitivity_range", _forge(SensitivityRange(0, 1), "upper", -1))
    parameter = _forge(parameter, "provenance", p)
    if damage == "bool": parameter = _forge(parameter, "value", True)
    earth = _forge(fixed.ellipsoid, "equatorial_radius_m", parameter)
    damaged = _forge(fixed, "ellipsoid", earth)
    instant = GeometryInstant(fixed.rotation.epoch, 0)
    position = _forge(CartesianPosition(fixed, instant, (1, 2, 3)), "frame", damaged)
    with pytest.raises((TypeError, ValueError)):
        transform_position(position, inertial)


@pytest.mark.parametrize("kind", ["position", "direction", "state"])
@pytest.mark.parametrize("damage", ["rate", "phase", "epoch", "shape", "metadata"])
def test_same_kind_label_different_complete_definition_is_incompatible(kind, damage):
    fixed, inertial = _model()
    instant = GeometryInstant(fixed.rotation.epoch, 0)
    if damage == "rate": _, other = _model(rate=1)
    if damage == "phase": _, other = _model(phase=1)
    if damage == "epoch": _, other = _model(epoch=TTEpoch(2451546, 0))
    if damage == "shape": _, other = _model(ellipsoid=_sphere())
    if damage == "metadata": other = replace(inertial, ellipsoid=replace(inertial.ellipsoid, name="Same shape different definition"))
    assert other.kind is inertial.kind
    with pytest.raises(ValueError, match="incompatible"):
        if kind == "position": transform_position(CartesianPosition(fixed, instant, (1, 2, 3)), other)
        if kind == "direction": transform_direction(CartesianDirection(fixed, instant, (1, 2, 3)), other)
        if kind == "state": transform_state(_state(fixed, instant), other)


def test_state_frame_and_timestamp_mismatch_are_rejected_without_retiming():
    fixed, inertial = _model()
    t0, t1 = GeometryInstant(fixed.rotation.epoch, 0), GeometryInstant(fixed.rotation.epoch, 1)
    position = CartesianPosition(fixed, t0, (0, 0, 0))
    for velocity in (CartesianVelocity(fixed, t1, (1, 2, 3)), CartesianVelocity(inertial, t0, (1, 2, 3))):
        with pytest.raises(ValueError, match="must match"):
            CartesianState(position, velocity)
        forged = _forge(_state(fixed, t0), "velocity", velocity)
        with pytest.raises(ValueError, match="must match"):
            transform_state(forged, inertial)
    assert position.instant == t0


@pytest.mark.parametrize("components", [(0, 0, 0), (math.inf, 0, 0), (math.nan, 1, 0), (True, 1, 0), [1, 2, 3], (1, 2)])
def test_direction_rejects_zero_and_invalid_components(components):
    fixed, _ = _model()
    with pytest.raises((TypeError, ValueError)):
        CartesianDirection(fixed, GeometryInstant(fixed.rotation.epoch, 0), components)


def test_every_entry_point_revalidates_forged_time_and_location():
    fixed, inertial = _model()
    t = GeometryInstant(fixed.rotation.epoch, 0)
    bad_time = _forge(t, "elapsed_seconds", math.nan)
    bad_epoch_time = _forge(t, "epoch", TTEpoch(2451546, 0))
    location = GeodeticLocation(fixed.ellipsoid, 0, 0, 0)
    for damaged in (bad_time, bad_epoch_time):
        for call in (
            lambda: rotation_angle(fixed.rotation, damaged),
            lambda: geodetic_position(location, fixed, damaged),
            lambda: geodetic_normal(location, fixed, damaged),
            lambda: transform_position(_forge(CartesianPosition(fixed, t, (1, 2, 3)), "instant", damaged), inertial),
            lambda: transform_direction(_forge(CartesianDirection(fixed, t, (1, 2, 3)), "instant", damaged), inertial),
        ):
            with pytest.raises(ValueError): call()
    for function in (geodetic_position, geodetic_normal):
        with pytest.raises(ValueError):
            function(_forge(location, "latitude_rad", 4), fixed, t)
        with pytest.raises(ValueError, match="EARTH_FIXED"):
            function(location, inertial, t)
        with pytest.raises(ValueError, match="ellipsoids"):
            function(replace(location, ellipsoid=_sphere()), fixed, t)
    with pytest.raises(ValueError):
        tt_date_at(_forge(t.epoch, "fractional_day", 1.0), 0)
    with pytest.raises(ValueError):
        elapsed_seconds_between(t.epoch, _forge(t.epoch, "fractional_day", math.nan))


def test_different_time_inertial_directions_keep_same_fixed_axes_and_raw_magnitudes():
    fixed, inertial = _model()
    results = [transform_direction(CartesianDirection(fixed, GeometryInstant(fixed.rotation.epoch, t), (3, 4, 0)), inertial) for t in (0.0, 0.125)]
    assert results[0].frame == results[1].frame
    assert results[0].instant != results[1].instant
    assert results[0].components == results[1].components == (3, 4, 0)
    with pytest.raises(ValueError, match="opposite"):
        transform_direction(results[0], inertial)


def test_standalone_purity_and_no_runtime_time_or_ephemeris_dependencies():
    import ast
    allowed = {"__future__", "dataclasses", "enum", "fractions", "math", "numbers",
               "ids", "parameters", "provenance", "orbit_config"}
    for module in (config, frames):
        tree = ast.parse(inspect.getsource(module))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert set(imports) <= allowed
        assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
        for name, value in vars(module).items():
            if not name.startswith("_") and not inspect.isclass(value) and not inspect.isfunction(value):
                assert not isinstance(value, (dict, list, set))
    fixed, inertial = _model(rate=0.1)
    state = _state(fixed, GeometryInstant(fixed.rotation.epoch, 0.125))
    snapshot = repr(state)
    first, second = transform_state(state, inertial), transform_state(state, inertial)
    assert first == second and first is not second
    assert first.position.instant == state.position.instant
    assert repr(state) == snapshot


def test_bounded_d303_and_s008_evidence_preserves_source_classifications():
    root = Path(__file__).resolve().parents[1]
    decisions = (root / "V5_DECISION_LOG.md").read_text(encoding="utf-8")
    section = decisions.split("## D303 — ", 1)[1].split("\n## ", 1)[0]
    for phrase in ("TT", "uniform rotation", "schema 5", "2**40", "2**20"):
        assert phrase.lower() in section.lower()
    sources = (root / "V5_SOURCE_REGISTER.md").read_text(encoding="utf-8")
    section = sources.split("### S008 — ", 1)[1].split("\n### ", 1)[0]
    for phrase in ("nga-wgs84-defining-parameters", "298.257223563", "georec_c",
                   "Terrestrial Time", "UT1", "TO RESEARCH"):
        assert phrase in section


def test_nonzero_real_underflow_and_preconversion_range_violations_reject():
    tiny = Fraction(1, 10**400)
    for value in (tiny, -tiny):
        with pytest.raises(ValueError, match="underflows"):
            TTEpoch(0, value)
        with pytest.raises(ValueError, match="underflows"):
            _sphere(10, value)
    with pytest.raises(ValueError, match="canonical"):
        GeodeticLocation(_sphere(), Fraction(math.pi/2) + tiny, 0, 0)
    with pytest.raises(ValueError, match="phase"):
        _model(phase=Fraction(-math.pi) - tiny)
    with pytest.raises(ValueError, match="envelope"):
        GeometryInstant(TTEpoch(0, 0), Fraction(2**40) + tiny)


def test_original_rational_sensitivity_constraints_revalidate_before_rounding():
    fixed, _ = _model()
    parameter = fixed.ellipsoid.equatorial_radius_m
    a = Fraction(6378137)
    bounds = _forge(SensitivityRange(0, 1), "lower", a + Fraction(1, 10**100))
    bounds = _forge(bounds, "upper", a)
    provenance = _forge(parameter.provenance, "sensitivity_range", bounds)
    parameter = _forge(parameter, "provenance", provenance)
    with pytest.raises(ValueError, match="lower"):
        replace(fixed.ellipsoid, equatorial_radius_m=parameter)


@pytest.mark.parametrize("enum_type", [FrameKind, ProvenanceClass, ProvenanceStatus])
def test_forged_string_enum_instances_are_not_actual_members(enum_type):
    forged = str.__new__(enum_type, "FORGED")
    fixed, inertial = _model()
    if enum_type is FrameKind:
        damaged = _forge(fixed, "kind", forged)
    else:
        parameter = fixed.ellipsoid.equatorial_radius_m
        field = "classification" if enum_type is ProvenanceClass else "status"
        parameter = _forge(parameter, "provenance", _forge(parameter.provenance, field, forged))
        damaged = _forge(fixed, "ellipsoid", _forge(fixed.ellipsoid, "equatorial_radius_m", parameter))
    t = GeometryInstant(fixed.rotation.epoch, 0)
    position = _forge(CartesianPosition(fixed, t, (1, 2, 3)), "frame", damaged)
    with pytest.raises(ValueError, match="actual.*member"):
        transform_position(position, inertial)
