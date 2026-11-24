"""Independent C1 analytic/Decimal references, conditioning and B2 composition.

Decimal oracle uses exact binary inputs, ellipsoid support geometry, complex
rotation, and direct transverse projection (production uses a double cross).
90/110-digit agreement is checked independently of binary64 production.
Budgets separate A geodesy/phase, relative-vector arithmetic, basis conditioning
and projection conditioning. They are conservative working bounds, not an
operational or universal libm guarantee. All comparisons are absolute SI/rad
or dimensionless norm errors; there is no implicit pytest relative tolerance.
"""

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
import json
import math

import pytest

import ops_sim.v5.context as context_module
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.context import evaluate_context_coast, with_coast_orbit
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.frames import CartesianPosition, CartesianState, CartesianVelocity
from ops_sim.v5.orbit_binding import CoastOrbitInputs
from ops_sim.v5.orbit_config import GeometryInstant, wgs84_reference_ellipsoid
from ops_sim.v5.orbit_geometry import evaluate_ground_point_geometry
from test_v56c1_ground_point_contracts import _point, _state
from test_v56b2_checkpoint_binding import _bound, generic_context
from test_v56b1_two_body_propagation import _atan2, _pi, _sincos


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _close(actual, expected, error=2e-15):
    assert actual == pytest.approx(expected, rel=0, abs=error)


def test_exact_hand_case_has_distinct_incidence_and_off_nadir():
    g = evaluate_ground_point_geometry(_point(), _state())
    assert g.slant_range_m == 1. and g.slant_range_rate_m_per_s == 1.
    assert g.elevation_rad == 0. and g.ground_azimuth_rad == math.pi/2
    assert g.incidence_rad == math.pi/2
    _close(g.off_nadir_rad, math.pi/4)
    assert g.orbital_azimuth_rad == math.pi
    assert g.ground_to_spacecraft.components == (0., 1., 0.)
    assert g.spacecraft_to_ground.components == (0., -1., 0.)
    _close(g.orbital_x.components, (-1/math.sqrt(2), 1/math.sqrt(2), 0.))
    assert g.orbital_y.components == (0., 0., -1.)


@pytest.mark.parametrize("height", [-.5, 0., 2.])
@pytest.mark.parametrize("rate", [-.125, 0., .125])
@pytest.mark.parametrize("radial", [-3., 0., 3.])
def test_equatorial_overhead_stationary_rotating_earth_and_signed_range_rate(height, rate, radial):
    p = _point(height=height)
    g = evaluate_ground_point_geometry(p, _state(p, r=(4., 0., 0.), v=(radial, 2., 0.), rate=rate))
    assert g.ground_state.position.components_m == (1+height, 0., 0.)
    assert g.ground_state.velocity.components_m_per_s == (0., rate*(1+height), 0.)
    assert g.slant_range_m == 3-height and g.slant_range_rate_m_per_s == radial
    assert g.elevation_rad == math.pi/2 and g.incidence_rad == 0. and g.off_nadir_rad == 0.
    assert g.ground_azimuth_rad is g.orbital_azimuth_rad is None
    assert g.ground_azimuth_status == g.orbital_azimuth_status == "zero_projection"


@pytest.mark.parametrize("offset,azimuth", [
    ((0., 0., 1.), 0.), ((0., 1., 0.), math.pi/2),
    ((0., 0., -1.), math.pi), ((0., -1., 0.), 3*math.pi/2),
    ((0., 1., 1.), math.pi/4), ((0., -1., 1.), 7*math.pi/4)])
def test_ground_azimuth_north_east_south_west_and_quadrants(offset, azimuth):
    r = (1., offset[1], offset[2])
    g = evaluate_ground_point_geometry(_point(), _state(r=r, v=(0., 2., 3.)))
    assert g.elevation_rad == 0.
    _close(g.ground_azimuth_rad, azimuth)
    _close(g.incidence_rad, math.pi/2)


def test_antipodal_obstructed_ray_still_produces_full_range_angles():
    g = evaluate_ground_point_geometry(_point(), _state(r=(-2., 0., 0.), v=(0., -1., 0.)))
    assert g.slant_range_m == 3.
    assert g.elevation_rad == -math.pi/2 and g.incidence_rad == math.pi
    assert g.off_nadir_rad == 0. and g.ground_azimuth_rad is None
    assert not hasattr(g, "visible")


@pytest.mark.parametrize("v", [(5., 2., 0.), (5., -2., 0.), (5., 0., 2.), (-5., 1., 2.)])
def test_local_basis_transverse_inertial_motion_inclined_retrograde_and_radial(v):
    g = evaluate_ground_point_geometry(_point(), _state(r=(2., 0., 0.), v=v, rate=7.))
    transverse = math.hypot(v[1], v[2])
    _close(g.orbital_x.components, (0., v[1]/transverse, v[2]/transverse))
    _close(g.orbital_y.components, (0., v[2]/transverse, -v[1]/transverse))
    _close(_cross(g.orbital_x.components, g.orbital_y.components), g.orbital_z.components)
    assert g.orbital_z.components == (-1., 0., 0.)


def test_rotational_ground_velocity_changes_range_rate_not_fixed_site_velocity():
    p = _point()
    g = evaluate_ground_point_geometry(p, _state(rate=.25))
    assert g.ground_state.velocity.components_m_per_s == (0., .25, 0.)
    assert g.slant_range_rate_m_per_s == .75


@pytest.mark.parametrize("latitude", [-math.pi/2, math.pi/2])
def test_pole_longitude_selects_meridian_convention(latitude):
    # Longitude selects east, even where an independently unique north is absent.
    values = []
    for longitude in (0., math.pi/2):
        p = _point(latitude=latitude, longitude=longitude)
        g = evaluate_ground_point_geometry(p, _state(p, r=(2., 2., 3.), v=(-1., 2., 0.)))
        values.append(g.ground_azimuth_rad)
        _close(g.incidence_rad+g.elevation_rad, math.pi/2, 5e-15)
    assert abs(math.remainder(values[0]-values[1], math.tau)) > 1.


@pytest.mark.parametrize("offset,defined", [(0., False), (1e-16, False), (1e-10, True)])
def test_azimuth_projection_resolution_preserves_ray_and_distinguishes_zero(offset, defined):
    g = evaluate_ground_point_geometry(_point(), _state(r=(2., offset, 0.), v=(0., 1., 0.)))
    assert (g.ground_azimuth_rad is not None) == defined
    assert g.ground_to_spacecraft.components[1] == offset/math.hypot(1., offset)
    assert g.ground_azimuth_status == ("zero_projection" if offset == 0 else
                                      "resolved" if defined else "unresolved_projection")
    assert g.off_nadir_rad >= 0  # No snapping of the direction or polar angle.


def test_half_open_azimuth_upper_endpoint_rounding_is_explicit_inward_neighbour():
    g = evaluate_ground_point_geometry(_point(), _state(r=(1., -1e-20, 1.), v=(0., 1., 0.)))
    assert g.ground_azimuth_rad == math.nextafter(math.tau, 0.)
    assert 0 <= g.ground_azimuth_rad < math.tau
    assert g.ground_to_spacecraft.components[1] == -1e-20


def test_near_zenith_angle_check_is_conditioned_on_projection_magnitude():
    east, north = 1e-10+8*2.**-53, 1e-10
    g = evaluate_ground_point_geometry(_point(), _state(r=(2., east, north), v=(0., 1., 0.)))
    with localcontext() as ctx:
        ctx.prec = 90
        eps = Decimal("1e-82")
        expected = _atan2(Decimal.from_float(east), Decimal.from_float(north), _pi(eps), eps)
    P = g.ground_azimuth_projection_norm
    delta_projection = math.sqrt(2)*64*2.**-53
    assert P > 2*delta_projection
    # atan2 gradient norm=1/P; this tolerance grows as the ray approaches zenith.
    assert abs(Decimal.from_float(g.ground_azimuth_rad)-expected) < Decimal.from_float(delta_projection/(P-delta_projection))
    _close(g.ground_to_spacecraft.components[1:], (east, north), 1e-25)


@pytest.mark.parametrize("scale", [1e-200, 1e200])
def test_scaled_geometry_avoids_squared_distance_overflow_and_underflow(scale):
    from test_v56a_time_frame_contracts import _sphere
    p = _point(ellipsoid=_sphere(scale))
    assert scale*scale == (0. if scale < 1 else math.inf)
    g = evaluate_ground_point_geometry(p, _state(p, r=(scale, scale, 0.), v=(-1., 1., 0.)))
    assert g.slant_range_m == scale
    _close(g.off_nadir_rad, math.pi/4)


@pytest.mark.parametrize("delta", [1e-4, 1e-8, 1e-12])
def test_near_radial_non_axis_basis_against_independent_transverse_reference(delta):
    p = _point()
    r = (2., 3., 4.)
    v = (2.+3*delta, 3.-2*delta, 4.)
    state = _state(p, r=r, v=v)
    g, ref = evaluate_ground_point_geometry(p, state), _reference(p, state, 110)
    sine = math.hypot(*_cross(r, v))/(math.hypot(*r)*math.hypot(*v))
    axis_bound = 64*2.**-53*(1+1/sine)
    for name in ("orbital_x", "orbital_y", "orbital_z"):
        error = math.hypot(*(float(Decimal.from_float(a)-b) for a,b in zip(getattr(g, name).components, ref[name])))
        assert error <= axis_bound
    P = float(ref["orbital_projection"])
    epsP = math.sqrt(2)*(axis_bound+64*2.**-53)
    assert abs(float(Decimal.from_float(g.off_nadir_rad)-ref["off_nadir_rad"])) <= 4*epsP
    if g.orbital_azimuth_rad is not None:
        assert P > epsP
        assert abs(float(Decimal.from_float(g.orbital_azimuth_rad)-ref["orbital_azimuth_rad"])) <= epsP/(P-epsP)


@pytest.mark.parametrize("offset,status", [(0., "zero_projection"), (1e-16, "unresolved_projection"), (1e-10, "resolved")])
def test_orbital_azimuth_projection_status_and_no_polar_angle_snapping(offset, status):
    g = evaluate_ground_point_geometry(_point(), _state(r=(2., offset, 0.), v=(0., 1., 0.)))
    assert g.orbital_azimuth_status == status
    assert (g.orbital_azimuth_rad is None) == (status != "resolved")
    assert (g.orbital_azimuth_projection_norm == 0) == (offset == 0)
    assert (g.off_nadir_rad == 0) == (offset == 0)
    if status == "resolved":
        assert g.orbital_azimuth_projection_norm > g.orbital_azimuth_resolution


def test_rounded_product_cancellation_is_not_called_exact_alignment():
    from ops_sim.v5.orbit_geometry import _dot as production_dot
    from fractions import Fraction
    a, b = (1+2.**-27, 1.), (1-2.**-27, -1.)
    assert sum(x*y for x,y in zip(a,b)) == 0.
    assert sum(Fraction(x)*Fraction(y) for x,y in zip(a,b)) == -Fraction(1, 2**54)
    with pytest.raises(ValueError, match="cancellation is numerically unresolved"):
        production_dot(a, b)


def _reference(point, state, precision=90):
    """Support-function geodesy + complex rotation + direct transverse projection."""
    with localcontext() as ctx:
        ctx.prec = precision
        eps = Decimal(10)**(-precision+8)
        pi = _pi(eps)
        D = Decimal.from_float
        norm = lambda v: _dot(v, v).sqrt()
        unit = lambda v: tuple(x/norm(v) for x in v)
        a, f = D(point.ellipsoid.equatorial_radius_m.value), D(point.ellipsoid.flattening.value)
        phi, lon, height = map(D, (point.latitude_rad.value, point.longitude_rad.value, point.ellipsoidal_height_m.value))
        sp, cp = _sincos(phi, pi, eps)
        sl, cl = _sincos(lon, pi, eps)
        normal = (cp*cl, cp*sl, sp)
        Q = (a*a, a*a, (a*(1-f))**2)
        support = sum(q*n*n for q, n in zip(Q, normal)).sqrt()
        fixed = tuple(q*n/support+height*n for q, n in zip(Q, normal))
        rotation = state.position.frame.rotation
        omega = D(rotation.angular_velocity_rad_per_s.value)
        phase = D(rotation.initial_phase_rad.value)+omega*D(state.position.instant.elapsed_seconds)
        s, c = _sincos(phase, pi, eps)
        # Complex multiplication exp(i*phase)*(x+i*y).
        rot = lambda v: (c*v[0]-s*v[1], s*v[0]+c*v[1], v[2])
        rg = rot(fixed)
        vg = (-omega*rg[1], omega*rg[0], Decimal(0))
        r = tuple(map(D, state.position.components_m))
        v = tuple(map(D, state.velocity.components_m_per_s))
        d = tuple(x-y for x, y in zip(r, rg)); rho = norm(d); u = unit(d)
        q = tuple(-x for x in u)
        rh = unit(r)
        transverse = tuple(vi-_dot(v, rh)*ri for vi, ri in zip(v, rh))
        x = unit(transverse); z = tuple(-x for x in rh); y = _cross(z, x)
        east, north, up = rot((-sl, cl, Decimal(0))), rot((-sp*cl, -sp*sl, cp)), rot(normal)
        e, n, U = _dot(u, east), _dot(u, north), _dot(u, up)
        qx, qy, qz = _dot(q, x), _dot(q, y), _dot(q, z)
        az = lambda Y,X: _atan2(Y, X, pi, eps) % (2*pi) if Y >= 0 else _atan2(Y, X, pi, eps)+2*pi
        return {
            "ground_position": rg, "ground_velocity": vg, "ground_to_spacecraft": u,
            "orbital_x": x, "orbital_y": y, "orbital_z": z,
            "slant_range_m": rho, "slant_range_rate_m_per_s": _dot(u, tuple(a-b for a,b in zip(v, vg))),
            "elevation_rad": _atan2(U, (e*e+n*n).sqrt(), pi, eps),
            "ground_azimuth_rad": az(e, n),
            "incidence_rad": _atan2(norm(_cross(up, u)), _dot(up, u), pi, eps),
            "off_nadir_rad": _atan2((qx*qx+qy*qy).sqrt(), qz, pi, eps),
            "orbital_azimuth_rad": az(qy, qx),
            "ground_projection": (e*e+n*n).sqrt(), "orbital_projection": (qx*qx+qy*qy).sqrt(),
        }


@pytest.mark.parametrize("time", [12345.6789, 1e9])
def test_off_axis_wgs84_against_independent_decimal_reference(time):
    p = _point(ellipsoid=wgs84_reference_ellipsoid(), latitude=.731, longitude=-1.117, height=1234.5)
    s = _state(p, r=(7200000., 1300000., 2500000.), v=(-1400., 6800., 1800.),
               phase=.271, rate=7.292115e-5, t=time)
    ref, extra = _reference(p, s), _reference(p, s, 110)
    for name in ref:
        left, right = ref[name], extra[name]
        if not isinstance(left, tuple): left, right = (left,), (right,)
        assert all(abs(a-b) < Decimal("1e-60") for a,b in zip(left, right))
    g = evaluate_ground_point_geometry(p, s)
    u = 2.**-53
    radius = math.hypot(*map(float, ref["ground_position"]))
    rho = float(ref["slant_range_m"])
    phase_error = 8*u*(.271+abs(7.292115e-5*time)+1)
    # A: support arithmetic scaled by a+h, then phase error times |rg|.
    ground_error = 64*u*(6378137.+1234.5)+radius*phase_error
    d_error = ground_error+8*u*rho
    los_error = 2*d_error/(rho-d_error)+32*u
    axis_error = phase_error+32*u
    r, v = s.position.components_m, s.velocity.components_m_per_s
    sine = math.hypot(*_cross(r, v))/(math.hypot(*r)*math.hypot(*v))
    basis_error = 64*u*(1+1/sine)
    vg_error = abs(7.292115e-5)*ground_error+16*u*math.hypot(*map(float, ref["ground_velocity"]))
    vrel = tuple(a-float(b) for a,b in zip(v, ref["ground_velocity"]))
    rate_error = math.hypot(*vrel)*los_error+vg_error+16*u*(math.hypot(*v)+math.hypot(*vrel))
    ground_plane_error = math.sqrt(2)*(los_error+axis_error+8*u)
    orbit_plane_error = math.sqrt(2)*(los_error+basis_error+8*u)
    # Three projections have norm perturbation <=sqrt(3)*epsilon; hypot is
    # 1-Lipschitz and atan2's gradient has norm 1/radius. For epsilon<1/8,
    # sqrt(3)*epsilon/(1-sqrt(3)*epsilon) <4*epsilon, including a libm reserve.
    # Cross/dot incidence has the same small-perturbation two-vector bound.
    assert max(los_error+axis_error+8*u, los_error+basis_error+8*u) < 1/8
    bounds = {
        "ground_position": ground_error, "ground_velocity": vg_error,
        "ground_to_spacecraft": los_error,
        "orbital_x": basis_error, "orbital_y": basis_error, "orbital_z": 16*u,
        "slant_range_m": d_error+8*u*rho, "slant_range_rate_m_per_s": rate_error,
        "elevation_rad": 4*(los_error+axis_error+8*u),
        "incidence_rad": 4*(los_error+axis_error+8*u),
        "off_nadir_rad": 4*(los_error+basis_error+8*u),
        "ground_azimuth_rad": ground_plane_error/(float(ref["ground_projection"])-ground_plane_error)+8*u,
        "orbital_azimuth_rad": orbit_plane_error/(float(ref["orbital_projection"])-orbit_plane_error)+8*u,
    }
    assert float(ref["ground_projection"]) > 2*ground_plane_error
    assert float(ref["orbital_projection"]) > 2*orbit_plane_error
    actual = {"ground_position": g.ground_state.position.components_m,
              "ground_velocity": g.ground_state.velocity.components_m_per_s}
    for name in bounds:
        if name not in actual:
            value = getattr(g, name); actual[name] = value.components if hasattr(value, "components") else value
    errors = {}
    for name, bound in bounds.items():
        a, b = actual[name], ref[name]
        if not isinstance(a, tuple): a, b = (a,), (b,)
        errors[name] = math.hypot(*(float(Decimal.from_float(x)-y) for x,y in zip(a,b)))
        assert errors[name] <= bound+1e-60, (name, errors[name], bound)
    _close(g.incidence_rad+g.elevation_rad, math.pi/2, 8e-15)
    assert abs(g.incidence_rad-g.off_nadir_rad) > .01
    print("C1_REFERENCE", time, json.dumps({name: [errors[name], bounds[name]] for name in bounds}, sort_keys=True))


def test_range_derivative_refinement_supplements_analytic_rotating_reference():
    p = _point()
    r, v, omega = (1., 2., 3.), (-.1, .2, .3), .25
    g = evaluate_ground_point_geometry(p, _state(p, r=r, v=v, rate=omega))
    # Independent exact fixed-point motion and LINEAR spacecraft trajectory.
    def range_at(t):
        ground = (math.cos(omega*t), math.sin(omega*t), 0.)
        return math.hypot(*(ri+vi*t-gi for ri,vi,gi in zip(r,v,ground)))
    errors = []
    V = math.hypot(*v)+abs(omega)
    A, J = omega**2, abs(omega)**3
    rho_min = range_at(0)-V*.04
    # Differentiate rho=sqrt(d.d) three times and apply Cauchy-Schwarz:
    # |rho'''| <= J+6*V*A/rho_min+6*V**3/rho_min**2.
    third_derivative_bound = J+6*V*A/rho_min+6*V**3/rho_min**2
    for h in (.04, .02, .01, .005):
        numerical = (range_at(h)-range_at(-h))/(2*h)
        errors.append(abs(numerical-g.slant_range_rate_m_per_s))
        allowance = h*h*third_derivative_bound/6 + 32*2.**-53*(range_at(0)+V*h)/h
        assert errors[-1] <= allowance  # m/s: Taylor remainder plus subtraction/roundoff.
    assert all(3.9 < a/b < 4.1 for a,b in zip(errors, errors[1:]))  # central O(h^2) truncation


def test_b2_explicit_query_portable_restart_and_later_step_without_hidden_propagation(monkeypatch):
    context = _bound()
    point = _point(ellipsoid=context.inputs.coast_orbit.trajectory.initial_state.position.frame.ellipsoid,
                   latitude=.25, longitude=.5, height=20.)
    queried = evaluate_context_coast(context)
    before = deepcopy(context); inputs = context.inputs
    checkpoint = CheckpointState.from_context(context).to_dict()
    def geometry(state):
        with monkeypatch.context() as guard:
            guard.setattr(context_module, "evaluate_two_body_state", lambda *a: pytest.fail("hidden propagation"))
            return evaluate_ground_point_geometry(point, state)
    g = geometry(queried)
    assert g.spacecraft_state == queried and context == before and context.inputs is inputs
    assert CheckpointState.from_context(context).to_dict() == checkpoint
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(inputs.coast_orbit.to_dict())))
    restored = CheckpointState.from_dict(json.loads(json.dumps(checkpoint))).restore(
        with_coast_orbit(generic_context().inputs, coast))
    assert geometry(evaluate_context_coast(restored)) == g
    for name in ("ground_to_spacecraft", "spacecraft_to_ground", "orbital_x", "orbital_y", "orbital_z"):
        vector = getattr(g, name)
        assert vector.instant == queried.position.instant and vector.frame == queried.position.frame
    assert g.ground_state.position.instant == queried.position.instant
    changed = replace(point, longitude_rad=replace(point.longitude_rad, value=.6))
    assert changed.point_id == point.point_id
    assert evaluate_ground_point_geometry(changed, queried).point != g.point
    assert context.inputs.model_manifest == inputs.model_manifest  # Point is unbound.
    metadata = replace(point, latitude_rad=replace(point.latitude_rad,
        provenance=replace(point.latitude_rad.provenance, rationale="Different explicit coordinate provenance")))
    assert metadata.point_id == point.point_id and metadata.geodetic_location == point.geodetic_location
    changed_evidence = evaluate_ground_point_geometry(metadata, queried)
    assert changed_evidence != g
    assert changed_evidence.slant_range_m == g.slant_range_m
    assert changed_evidence.ground_to_spacecraft == g.ground_to_spacecraft
    assert CheckpointState.from_context(context).to_dict() == checkpoint
    SimulationEngine().step(context)
    later = geometry(evaluate_context_coast(context))
    assert later.spacecraft_state.position.instant.elapsed_seconds == context.simulation_time_seconds
    assert later.spacecraft_state.position.instant != g.spacecraft_state.position.instant
    assert context.inputs is inputs and inputs.coast_orbit.trajectory == before.inputs.coast_orbit.trajectory
