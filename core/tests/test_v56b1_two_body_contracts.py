"""B1 domain, nested evidence, explicit ownership and standalone contract guards."""

from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import inspect
import math

import numpy as np
import pytest

from ops_sim.v5.frames import CartesianPosition, CartesianState, CartesianVelocity
from ops_sim.v5.ids import ParameterId, SourceRecordId
from ops_sim.v5.orbit_config import (
    FrameDefinition, FrameKind, GeometryInstant, ReferenceEllipsoid, TTEpoch,
    UniformRotationDefinition,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import ParameterProvenance, ProvenanceClass, ProvenanceStatus, SensitivityRange
import ops_sim.v5.orbit as orbit
from ops_sim.v5.orbit import (
    TwoBodyTrajectory, TwoBodySolverConfig, evaluate_two_body_state,
    nominal_earth_gravitational_parameter,
)


def _parameter(identifier, units, value):
    return ScalarParameter(value, ParameterProvenance(
        ParameterId(identifier), ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
        units, (), ProvenanceStatus.VERIFIED, rationale="Synthetic B1 verification input",
    ))


def _trajectory(r=(2.0, 0.0, 0.0), v=(0.0, 1.0, 0.0), mu=2.0, earth=1.0, t0=0.0):
    epoch = TTEpoch(2451545, 0.125)
    frame = FrameDefinition(FrameKind.MODEL_INERTIAL, ReferenceEllipsoid(
        "Synthetic B1 sphere", _parameter("orbit.earth.equatorial-radius", "m", earth),
        _parameter("orbit.earth.flattening", "1", 0.0),
    ), UniformRotationDefinition(epoch,
        _parameter("orbit.rotation.initial-phase", "rad", 0.25),
        _parameter("orbit.rotation.angular-rate", "rad/s", -0.125)))
    instant = GeometryInstant(epoch, t0)
    return TwoBodyTrajectory(CartesianState(CartesianPosition(frame, instant, r),
        CartesianVelocity(frame, instant, v)),
        _parameter("orbit.gravity.gravitational-parameter", "m^3/s^2", mu))


def _forge(value, path, damaged):
    result = object.__new__(type(value))
    for field in fields(value):
        object.__setattr__(result, field.name, getattr(value, field.name))
    first, *rest = path.split(".")
    object.__setattr__(result, first, _forge(getattr(value, first), ".".join(rest), damaged)
                       if rest else damaged)
    return result


def _query(trajectory, seconds=1.0, config=None):
    return evaluate_two_body_state(trajectory,
        GeometryInstant(trajectory.initial_state.position.instant.epoch, seconds),
        TwoBodySolverConfig(1e-10, 100) if config is None else config)


def test_required_immutable_fields_signatures_and_exports():
    expected = {TwoBodyTrajectory: ("initial_state", "gravitational_parameter_m3_s2"),
                TwoBodySolverConfig: ("time_tolerance_seconds", "max_iterations")}
    for cls, names in expected.items():
        assert tuple(f.name for f in fields(cls)) == names
        assert cls.__slots__ == names and cls.__dataclass_params__.frozen
        assert all(p.default is inspect.Parameter.empty for p in inspect.signature(cls).parameters.values())
        with pytest.raises(TypeError):
            cls()
    trajectory = _trajectory()
    assert not hasattr(trajectory, "__dict__")
    with pytest.raises(FrozenInstanceError):
        trajectory.initial_state = trajectory.initial_state
    assert tuple(inspect.signature(evaluate_two_body_state).parameters) == ("trajectory", "instant", "solver_config")
    assert all(p.default is inspect.Parameter.empty for p in inspect.signature(evaluate_two_body_state).parameters.values())
    assert not inspect.signature(nominal_earth_gravitational_parameter).parameters
    assert set(orbit.__all__) == {"TwoBodyTrajectory", "TwoBodySolverConfig", "evaluate_two_body_state",
                                 "nominal_earth_gravitational_parameter"}


def test_named_mu_value_identity_units_and_precise_provenance():
    mu = nominal_earth_gravitational_parameter()
    assert mu.value == 398_600_441_800_000.0
    assert mu.parameter_id == ParameterId("orbit.gravity.gravitational-parameter")
    assert mu.units == "m^3/s^2"
    assert mu.provenance.classification is ProvenanceClass.PUBLIC_SPECIFICATION
    assert mu.provenance.status is ProvenanceStatus.VERIFIED
    assert mu.provenance.source_ids == (SourceRecordId("nga-wgs84-defining-parameters"),)
    assert mu.value != 398_600_500_000_000.0  # NGA's separate GPS-user footnote.


@pytest.mark.parametrize("value", [True, False, "1", None, complex(1), math.inf, -math.inf,
                                   math.nan, 0, -1, 2**53+1, Fraction(1, 10**1000)])
def test_invalid_tolerance(value):
    with pytest.raises((TypeError, ValueError)):
        TwoBodySolverConfig(value, 50)


@pytest.mark.parametrize("value", [True, False, 1.0, np.int64(2), None, "5", 0, -1])
def test_iteration_limit_requires_exact_positive_builtin_integer(value):
    with pytest.raises((TypeError, ValueError)):
        TwoBodySolverConfig(1e-8, value)


def test_existing_numeric_interoperability_and_normalization():
    t = _trajectory(mu=np.float64(2), r=(np.int64(2), 0, 0), v=(0, np.float64(1), 0))
    assert type(t.gravitational_parameter_m3_s2.value) is float
    assert type(TwoBodySolverConfig(np.float64(1e-8), 2).time_tolerance_seconds) is float
    assert _query(t) == _query(_trajectory())


@pytest.mark.parametrize("field,value", [
    ("value", True), ("value", math.nan), ("value", math.inf), ("value", 0),
    ("value", -1), ("value", 2**53+1), ("value", Fraction(1, 10**1000)),
    ("provenance.units", "km^3/s^2"),
    ("provenance.parameter_id", ParameterId("wrong.gravity")),
    ("provenance.parameter_id.value", " invalid "),
    ("provenance.classification", "EXPLICIT_MODEL_ASSUMPTION"),
    ("provenance.status", "VERIFIED"),
    ("provenance.status", ProvenanceStatus.REJECTED),
    ("provenance.status", ProvenanceStatus.SUPERSEDED),
    ("provenance.rationale", None),
    ("provenance.source_ids", [SourceRecordId("synthetic")]),
    ("provenance.source_ids", ("synthetic",)),
    ("provenance.source_ids", (SourceRecordId("synthetic"), SourceRecordId("synthetic"))),
    ("provenance.sensitivity_range", SensitivityRange(3, 4)),
])
def test_forged_mu_metadata_revalidated_even_at_initial_time(field, value):
    t = _forge(_trajectory(), "gravitational_parameter_m3_s2."+field, value)
    with pytest.raises((TypeError, ValueError)):
        _query(t, seconds=0.0)


@pytest.mark.parametrize("field,value", [
    ("position.components_m", (True, 0, 0)),
    ("position.components_m", (math.inf, 0, 0)),
    ("position.components_m", (2**53+1, 0, 0)),
    ("position.components_m", [2, 0, 0]),
    ("velocity.components_m_per_s", (0, math.nan, 0)),
    ("position.frame.kind", "MODEL_INERTIAL"),
    ("position.frame.rotation.epoch.julian_day", True),
    ("position.frame.rotation.initial_phase_rad.provenance.rationale", None),
    ("position.frame.rotation.angular_velocity_rad_per_s.provenance.status", "VERIFIED"),
    ("position.frame.ellipsoid.equatorial_radius_m.provenance.units", "km"),
    ("position.frame.ellipsoid.flattening.provenance.classification", "EXPLICIT_MODEL_ASSUMPTION"),
    ("position.instant.elapsed_seconds", True),
    ("position.instant.epoch.fractional_day", 1.0),
    ("velocity.instant.elapsed_seconds", 0.5),
    ("velocity.frame.rotation.angular_velocity_rad_per_s.value", 0.5),
])
def test_forged_state_graph_revalidated_at_initial_time(field, value):
    t = _forge(_trajectory(), "initial_state."+field, value)
    # Use a separate valid request so a damaged state instant cannot mask the guard.
    with pytest.raises((TypeError, ValueError)):
        evaluate_two_body_state(t, _trajectory().initial_state.position.instant, TwoBodySolverConfig(1e-8, 50))


@pytest.mark.parametrize("field,value", [("time_tolerance_seconds", 0), ("time_tolerance_seconds", True),
                                          ("time_tolerance_seconds", math.nan), ("max_iterations", False)])
def test_forged_config_revalidated_before_zero_time(field, value):
    with pytest.raises((TypeError, ValueError)):
        _query(_trajectory(), 0, _forge(TwoBodySolverConfig(1e-8, 50), field, value))


@pytest.mark.parametrize("field,value", [("elapsed_seconds", math.nan), ("elapsed_seconds", True),
    ("elapsed_seconds", 2**40+1), ("epoch.julian_day", True), ("epoch.fractional_day", -0.5)])
def test_forged_requested_instant(field, value):
    t = _trajectory()
    with pytest.raises((TypeError, ValueError)):
        evaluate_two_body_state(t, _forge(t.initial_state.position.instant, field, value), TwoBodySolverConfig(1e-8, 50))


def test_exact_domain_types_and_incompatible_epoch():
    t, cfg = _trajectory(), TwoBodySolverConfig(1e-8, 50)
    instant = t.initial_state.position.instant
    class TrajectorySubclass(TwoBodyTrajectory):
        pass
    class ConfigSubclass(TwoBodySolverConfig):
        pass
    class InstantSubclass(GeometryInstant):
        pass
    class StateSubclass(CartesianState):
        pass
    with pytest.raises(TypeError, match="exact CartesianState"):
        TwoBodyTrajectory(StateSubclass(t.initial_state.position, t.initial_state.velocity), t.gravitational_parameter_m3_s2)
    for args in [(object(), instant, cfg), (t, object(), cfg), (t, instant, object()),
                 (TrajectorySubclass(t.initial_state, t.gravitational_parameter_m3_s2), instant, cfg),
                 (t, instant, ConfigSubclass(1e-8, 50)),
                 (t, InstantSubclass(instant.epoch, 0), cfg)]:
        with pytest.raises(TypeError):
            evaluate_two_body_state(*args)
    with pytest.raises(ValueError, match="reference TT epoch"):
        evaluate_two_body_state(t, GeometryInstant(TTEpoch(2451546, .125), 0), cfg)


def test_earth_fixed_rejects_and_complete_frame_evidence_is_preserved():
    t = _trajectory()
    frame = replace(t.initial_state.position.frame, kind=FrameKind.EARTH_FIXED)
    instant = t.initial_state.position.instant
    fixed = CartesianState(CartesianPosition(frame, instant, (2, 0, 0)),
                           CartesianVelocity(frame, instant, (0, 1, 0)))
    with pytest.raises(ValueError, match="MODEL_INERTIAL"):
        TwoBodyTrajectory(fixed, t.gravitational_parameter_m3_s2)
    # Enormous rotation metadata is legal here: B1 neither rotates nor calls A's phase guard.
    frame = replace(frame, kind=FrameKind.MODEL_INERTIAL,
                    rotation=replace(frame.rotation, angular_velocity_rad_per_s=
                    _parameter("orbit.rotation.angular-rate", "rad/s", 1e100)))
    state = CartesianState(CartesianPosition(frame, instant, (2, 0, 0)),
                           CartesianVelocity(frame, instant, (0, 1, 0)))
    result = _query(TwoBodyTrajectory(state, t.gravitational_parameter_m3_s2))
    assert result.position.frame == frame == result.velocity.frame
    assert result.position.components_m == _query(t).position.components_m


@pytest.mark.parametrize("r,v,mu,match", [
    ((0, 0, 0), (0, 1, 0), 2, "radius"),
    ((2, 0, 0), (1, 0, 0), 2, "radial"),
    ((2, 0, 0), (0, 0, 0), 2, "radial"),
    ((2, 0, 0), (1, 1, 0), 2, "nonelliptic"),  # Exact scaled parabolic v²=2mu/R.
    ((2, 0, 0), (0, 1, 0), 1, "near-parabolic"),  # sqrt scaling rounds beta above zero; still rejected.
    ((2, 0, 0), (0, 2, 0), 2, "nonelliptic"),
    ((2, 0, 0), (0, 0.5, 0), 2, "pericentre"),  # Exterior now, unsafe pericentre.
    ((1, 0, 0), (0, 1, 0), 1, "pericentre"),
    ((0.5, 0, 0), (0, 1, 0), 0.5, "pericentre"),
])
def test_invalid_physical_family_reaches_intended_guard(r, v, mu, match):
    with pytest.raises(ValueError, match=match):
        _trajectory(r, v, mu)


@pytest.mark.parametrize("e,accepted", [(0, True), (0.95, True),
    (1-2**-8-1e-12, True), (1-2**-8+1e-12, False), (1-2**-20, False)])
def test_eccentricity_conditioning_boundary(e, accepted):
    # Start at periapsis R=2 m, mu=2; known e=v²-1 (subject to binary input rounding).
    if accepted:
        assert _trajectory(v=(0, math.sqrt(1+e), 0))
    else:
        with pytest.raises(ValueError, match="near-parabolic"):
            _trajectory(v=(0, math.sqrt(1+e), 0))


@pytest.mark.parametrize("radius", [2.0**-128, 2.0**128])
def test_radius_scale_endpoints(radius):
    assert _trajectory(r=(radius, 0, 0), v=(0, 1, 0), mu=radius, earth=radius/4)


@pytest.mark.parametrize("radius", [math.nextafter(2.0**-128, 0), math.nextafter(2.0**128, math.inf)])
def test_radius_scale_outside_endpoints(radius):
    with pytest.raises(ValueError, match="radius"):
        _trajectory(r=(radius, 0, 0), v=(0, 1, 0), mu=radius, earth=radius/4)


@pytest.mark.parametrize("speed", [2.0**-128, 2.0**128])
def test_speed_and_time_scale_endpoints(speed):
    assert _trajectory(r=(1, 0, 0), v=(0, speed, 0), mu=speed*speed, earth=.25)


@pytest.mark.parametrize("speed", [2.0**-129, 2.0**129])
def test_speed_scale_outside_endpoints(speed):
    with pytest.raises(ValueError, match="speed scale"):
        _trajectory(r=(1, 0, 0), v=(0, speed, 0), mu=speed*speed, earth=.25)


@pytest.mark.parametrize("radius,speed", [(2.0**128, .5), (2.0**-128, 2)])
def test_time_scale_outside_endpoints(radius, speed):
    with pytest.raises(ValueError, match="time scale"):
        _trajectory(r=(radius, 0, 0), v=(0, speed, 0), mu=radius*speed*speed, earth=radius/4)


def test_numerically_ambiguous_surface_clearance_is_not_admitted():
    with pytest.raises(ValueError, match="resolvably strictly outside"):
        _trajectory(r=(math.nextafter(1.0, math.inf), 0, 0), mu=math.nextafter(1.0, math.inf))
    assert _trajectory(r=(1+1e-12, 0, 0), mu=1+1e-12)


def test_span_and_period_count_boundaries_are_separate_from_a_timestamps():
    t = _trajectory(t0=-(2**40))
    with pytest.raises(ValueError, match=r"span exceeds 2\*\*40"):
        _query(t, 2**40)
    t = _trajectory(r=(1e6, 0, 0), v=(0, 1, 0), mu=1e6, earth=1, t0=0)
    assert _query(t, 2**40, TwoBodySolverConfig(1e-5, 100))
    with pytest.raises(ValueError, match=r"span exceeds 2\*\*40"):
        _query(replace(t, initial_state=replace(t.initial_state,
            position=replace(t.initial_state.position, instant=GeometryInstant(t.initial_state.position.instant.epoch, -1)),
            velocity=replace(t.initial_state.velocity, instant=GeometryInstant(t.initial_state.position.instant.epoch, -1)))), 2**40)
    t = _trajectory()
    scales = orbit._scales(t.initial_state, 2.0)
    limit = scales.period_seconds*2**20
    assert _query(t, limit)
    with pytest.raises(ValueError, match=r"2\*\*20 orbital periods"):
        _query(t, math.nextafter(limit, math.inf))


def test_unsupported_scaled_tiny_duration_is_explicit_and_valid_small_duration_works():
    with pytest.raises(ValueError, match="scaled propagation duration"):
        _query(_trajectory(), math.ulp(0.0))
    tiny = _query(_trajectory(), 1e-20, TwoBodySolverConfig(1e-30, 50))
    assert tiny.position.components_m[1] != 0


def test_original_input_revalidated_after_external_forgery():
    t = _forge(_trajectory(), "initial_state.position.components_m", (0, 0, 0))
    with pytest.raises(ValueError, match="radius"):
        _query(t, 0)


def test_source_remains_standalone_without_runtime_owners():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(orbit.__file__).read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert modules == {"__future__", "dataclasses", "fractions", "math", "frames", "orbit_config", "parameters"}
    assert not any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(tree))
