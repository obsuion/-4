"""Independent rational, analytic and Decimal references for C2a geometry."""

from collections import Counter
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import math

import pytest

from ops_sim.v5.orbit_config import wgs84_reference_ellipsoid
from ops_sim.v5.orbit_visibility import (
    GroundVisibilityStatus as V, LineOfSightStatus as L, LineOfSightReason as R,
    ElevationStatus as E, BodyLocation as B, SegmentMinimumLocation as M,
    evaluate_ground_visibility, _segment_minimum, _occultation,
)
from test_v56a_time_frame_contracts import _sphere
from test_v56c1_ground_point_contracts import _point, _state
from test_v56c2a_visibility_contracts import _policy
from test_v56b1_two_body_propagation import _atan2, _pi, _sincos


def _query(*, h=0., r=(2., 0., 0.), mask=0., earth=None):
    p = _point(height=h, ellipsoid=earth)
    return evaluate_ground_visibility(p, _state(p, r=r, v=(0., 0., 1.)), _policy(mask))


@pytest.mark.parametrize("h,r,mask,los,elevation,status,reason", [
    (0., (2., 0., 0.), 0., L.CLEAR, E.ABOVE, V.VISIBLE, R.SURFACE_OUTWARD),
    (0., (-2., 0., 0.), -1., L.BLOCKED, E.BELOW, V.NOT_VISIBLE, R.SURFACE_ENTRY),
    (0., (1., 1., 0.), 0., L.BOUNDARY, E.BOUNDARY, V.BOUNDARY, R.SURFACE_TANGENT),
    (0., (1., 1., 0.), -.1, L.BOUNDARY, E.ABOVE, V.BOUNDARY, R.SURFACE_TANGENT),
    (0., (1., 1., 0.), .1, L.BOUNDARY, E.BELOW, V.NOT_VISIBLE, R.SURFACE_TANGENT),
    (-.1, (2., 0., 0.), 0., L.BLOCKED, E.ABOVE, V.NOT_VISIBLE, R.GROUND_INSIDE_REFERENCE_BODY),
    (-1e-20, (2., 0., 0.), 0., L.BLOCKED, E.ABOVE, V.NOT_VISIBLE, R.GROUND_INSIDE_REFERENCE_BODY),
    (1., (1.5, 2., 0.), 0., L.CLEAR, E.BELOW, V.NOT_VISIBLE, R.SEGMENT_CLEAR),
    (1., (1.5, 2., 0.), -.5, L.CLEAR, E.ABOVE, V.VISIBLE, R.SEGMENT_CLEAR),
    (1., (1.5, 0., 0.), -1., L.CLEAR, E.BELOW, V.NOT_VISIBLE, R.SEGMENT_CLEAR),
    (1., (.5, 0., 0.), 0., L.BLOCKED, E.BELOW, V.NOT_VISIBLE, R.SPACECRAFT_INSIDE_REFERENCE_BODY),
    (1., (1., 0., 0.), 0., L.BOUNDARY, E.BELOW, V.NOT_VISIBLE, R.SPACECRAFT_SURFACE),
    (1., (-1., 0., 0.), 0., L.BLOCKED, E.BELOW, V.NOT_VISIBLE, R.INTERIOR_PENETRATION),
])
def test_hand_solved_surface_elevated_and_endpoint_rules(h, r, mask, los, elevation, status, reason):
    result = _query(h=h, r=r, mask=mask)
    assert (result.line_of_sight_status, result.elevation_status, result.status,
            result.line_of_sight_reason) == (los, elevation, status, reason)
    if h < 0: assert result.ground_location is B.INSIDE


def test_overhead_none_azimuths_do_not_prevent_visibility():
    result = _query()
    assert result.geometry.ground_azimuth_rad is result.geometry.orbital_azimuth_rad is None
    assert result.status is V.VISIBLE and result.minimum_parameter == 0 and result.minimum_level == 0


def test_elevated_sphere_clear_below_horizontal_case_has_interior_minimum():
    result = _query(h=1., r=(1.5, 2., 0.), mask=-.5)
    # d=(-1/2,2,0); min at4/17; distance²=64/17, so Fmin=47/17>0.
    assert result.minimum_parameter == Fraction(4, 17)
    assert result.minimum_level == Fraction(47, 17)
    assert result.minimum_location is M.INTERIOR
    assert result.geometry.elevation_rad < 0 and result.status is V.VISIBLE


def test_finite_segment_clear_even_when_forward_ray_and_infinite_line_hit():
    result = _query(h=1., r=(1.5, 0., 0.))
    assert result.line_of_sight_status is L.CLEAR
    assert result.minimum_parameter == 1 and result.minimum_location is M.SPACECRAFT_ENDPOINT
    # Infinite quadratic roots s=2 and6 are BOTH beyond the endpoint s=1.
    a, b, c = result.quadratic_a, result.quadratic_b, result.ground_level
    assert a*2**2+2*b*2+c == a*6**2+2*b*6+c == 0


@pytest.mark.parametrize("offset,expected", [(0., L.BOUNDARY), (1e-8, L.CLEAR), (-1e-8, L.BLOCKED),
    (math.nextafter(1., math.inf)-1, L.CLEAR), (math.nextafter(1., 0.)-1, L.BLOCKED)])
def test_exact_rational_interior_tangent_and_both_sides(offset, expected):
    result = _query(h=.25, r=(.5, 1.+offset, 0.), mask=-1.)
    assert result.line_of_sight_status is expected
    assert result.minimum_location is M.INTERIOR
    assert result.occultation_allowance == 0 and result.exact_axis_definition
    if offset == 0:
        assert (result.quadratic_a, result.quadratic_b, result.ground_level) == (
            Fraction(25, 16), Fraction(-15, 16), Fraction(9, 16))
        assert result.minimum_parameter == Fraction(3, 5) and result.minimum_level == 0
        assert result.status is V.BOUNDARY
    # Exact geographic axis + exact a/f make even these last-bit signs exact
    # model-equation evidence. Nonaxis near-tangency is tested separately.


def test_exact_oblate_tangent_and_equatorial_sphere_disagree():
    earth = _sphere(2., .25)
    tangent = _query(h=.5, r=(1., 0., 1.5), earth=earth, mask=-1.)
    assert tangent.line_of_sight_status is L.BOUNDARY and tangent.minimum_level == 0
    clear = _query(h=.5, r=(1., 0., 1.6), earth=earth, mask=-1.)
    sphere = _query(h=.5, r=(1., 0., 1.6), earth=_sphere(2.), mask=-1.)
    assert clear.line_of_sight_status is L.CLEAR and sphere.line_of_sight_status is L.BLOCKED


def test_rounded_derived_polar_radius_cannot_redefine_authoritative_shape():
    f = 2.**-54
    assert 1.-f == 1.  # Binary redundant b would make p1 on the surface.
    p = _point(height=1., ellipsoid=_sphere(1., f))
    result = evaluate_ground_visibility(p, _state(p, r=(0., 0., 1.), v=(0., 1., 0.)), _policy(-1.))
    assert result.spacecraft_location is B.OUTSIDE
    assert result.spacecraft_level == 1/(1-Fraction(f))**2-1


def test_exact_ground_identity_does_not_move_c1_coordinate_or_invent_mask_equality():
    result = _query(h=2.**-53, r=(1., 1., 0.), mask=0.)
    assert result.geometry.ground_state.position.components_m[0] == 1.
    assert result.ground_level == (1+Fraction(1, 2**53))**2-1 > 0
    assert result.geometry.elevation_rad == result.elevation_margin_rad == 0.
    assert result.elevation_status is E.UNRESOLVED  # True height was not rounded away.
    assert result.line_of_sight_status is L.CLEAR


@pytest.mark.parametrize("mask", [math.pi/4, math.pi/2])
def test_copying_rounded_angle_to_policy_is_not_exact_boundary(mask):
    result = _query(r=(2., 1., 0.) if mask == math.pi/4 else (2., 0., 0.), mask=mask)
    assert result.elevation_margin_rad == 0.
    assert result.elevation_status is E.UNRESOLVED and result.status is V.UNRESOLVED


@pytest.mark.parametrize("scale", [2.**-900, 1e-200, 1., 1e200, 2.**900])
@pytest.mark.parametrize("flattening", [0., .5])
def test_supported_scale_and_shape_endpoints(scale, flattening):
    result = _query(r=(2*scale, 0., 0.), earth=_sphere(scale, flattening))
    assert result.status is V.VISIBLE and result.occultation_signed_value == 1


@pytest.mark.parametrize("radius,flattening,r", [
    (math.nextafter(2.**-900, 0.), 0., None),
    (math.nextafter(2.**900, math.inf), 0., None),
    (1., math.nextafter(.5, 1.), None),
    (1., 0., (math.nextafter(float(2**40), math.inf), 1., 0.)),
])
def test_explicit_additional_c2a_domain_rejects_without_calling_hidden(radius, flattening, r):
    with pytest.raises(ValueError, match="C2a"):
        _query(r=(2*radius, 0., 0.) if r is None else r, earth=_sphere(radius, flattening))


def test_normalized_coordinate_and_height_envelope_boundary():
    assert _query(r=(float(2**40), 1., 0.)).line_of_sight_status is L.CLEAR
    p = _point(height=float(2**40))
    assert evaluate_ground_visibility(p, _state(p, r=(0., float(2**40), 0.)), _policy(-1.)).line_of_sight_status is L.CLEAR
    with pytest.raises(ValueError, match="C2a"):
        p = _point(height=math.nextafter(float(2**40), math.inf))
        evaluate_ground_visibility(p, _state(p, r=(0., float(2**40), 0.)), _policy(-1.))


def _D(value):
    if isinstance(value, Fraction): return Decimal(value.numerator)/Decimal(value.denominator)
    return Decimal.from_float(value)


def _reference(point, state, precision=90):
    """Support-surface geodesy; complex rotation; cross-product line distance.

    No production geometry/predicate helper is called. Root overlap supplies
    an independent penetration test; roots are used only in this oracle.
    """
    with localcontext() as ctx:
        ctx.prec = precision
        eps = Decimal(10)**(-precision+8)
        pi = _pi(eps)
        a, f, h = map(_D, (point.ellipsoid.equatorial_radius_m.value,
                            point.ellipsoid.flattening.value, point.ellipsoidal_height_m.value))
        sp, cp = _sincos(_D(point.latitude_rad.value), pi, eps)
        sl, cl = _sincos(_D(point.longitude_rad.value), pi, eps)
        normal = (cp*cl, cp*sl, sp)
        axes = (a, a, a*(1-f))
        norm = lambda v: sum(x*x for x in v).sqrt()
        support = norm(tuple(axis*n for axis, n in zip(axes, normal)))
        fixed = tuple(axis*axis*n/support+h*n for axis, n in zip(axes, normal))
        rotation = state.position.frame.rotation
        phase = _D(rotation.initial_phase_rad.value)+_D(rotation.angular_velocity_rad_per_s.value)*_D(state.position.instant.elapsed_seconds)
        sine, cosine = _sincos(phase, pi, eps)
        rot = lambda v: (cosine*v[0]-sine*v[1], sine*v[0]+cosine*v[1], v[2])
        ground, up = rot(fixed), rot(normal)
        r = tuple(map(_D, state.position.components_m))
        ray = tuple(x-y for x,y in zip(r, ground))
        east, north = rot((-sl, cl, Decimal(0))), rot((-sp*cl, -sp*sl, cp))
        dot = lambda x,y: sum(a*b for a,b in zip(x,y))
        vertical = dot(ray, up)
        elevation = _atan2(vertical, (dot(ray,east)**2+dot(ray,north)**2).sqrt(), pi, eps)
        p0, p1 = (tuple(x/axis for x,axis in zip(v,axes)) for v in (ground,r))
        d = tuple(y-x for x,y in zip(p0,p1)); aa=dot(d,d); bb=dot(p0,d)
        cc = dot(p0,p0)-1 if h else Decimal(0)  # Authoritative h=0 surface.
        s = -bb/aa
        if s <= 0: minimum, location = dot(p0,p0)-1, M.GROUND_ENDPOINT
        elif s >= 1: minimum, location = dot(p1,p1)-1, M.SPACECRAFT_ENDPOINT
        else:
            cross = (p0[1]*p1[2]-p0[2]*p1[1], p0[2]*p1[0]-p0[0]*p1[2], p0[0]*p1[1]-p0[1]*p1[0])
            minimum, location = dot(cross,cross)/aa-1, M.INTERIOR
        disc = bb*bb-aa*cc
        roots = None if disc < 0 else ((-bb-disc.sqrt())/aa, (-bb+disc.sqrt())/aa)
        penetration = roots is not None and max(Decimal(0),roots[0]) < min(Decimal(1),roots[1])
        return {"ground_scaled":tuple(x/a for x in ground), "up":up, "east":east,
                "elevation":elevation, "minimum":minimum, "location":location,
                "surface_departure":dot(p0,p1)-1, "end_level":dot(p1,p1)-1,
                "end_derivative":dot(p1,d), "penetration":penetration}


def _agreed_reference(point, state):
    ref, extra = _reference(point, state, 90), _reference(point, state, 120)
    with localcontext() as ctx:
        ctx.prec = 130
        for key in ("ground_scaled", "up", "east", "elevation", "minimum", "surface_departure", "end_level", "end_derivative"):
            left, right = ref[key], extra[key]
            if not isinstance(left, tuple): left, right = (left,), (right,)
            assert all(abs(a-b) < Decimal("1e-60") for a,b in zip(left,right)), key
    return extra


@pytest.mark.parametrize("latitude,longitude,phase,time", [
    (.731,-1.117,.271,12345.6789), (-.731,1.117,-.271,1e9),
    (.2,2.4,-2.1,100.), (-1.2,-2.1,1.4,2e8),
    (math.pi/2,.7,.4,400.), (-math.pi/2,-.7,-.4,400.),
])
@pytest.mark.parametrize("height", [0., -1e-12, 1500.])
def test_offaxis_wgs84_outward_geometry_preserves_surface_and_negative_height(latitude, longitude, phase, time, height):
    p = _point(ellipsoid=wgs84_reference_ellipsoid(), latitude=latitude, longitude=longitude, height=height)
    provisional = _state(p, r=(7e6,2e6,1e6), v=(1.,2.,3.), phase=phase, rate=7.292115e-5, t=time)
    ref = _reference(p, provisional,120)
    a = p.ellipsoid.equatorial_radius_m.value
    r = tuple(float(g*_D(a)+Decimal(800000)*n+Decimal(10000)*e) for g,n,e in zip(ref["ground_scaled"],ref["up"],ref["east"]))
    state = _state(p, r=r, v=(1.,2.,3.), phase=phase,rate=7.292115e-5,t=time)
    result, ref = evaluate_ground_visibility(p,state,_policy(.1)), _agreed_reference(p,state)
    assert result.elevation_status is E.ABOVE
    if height < 0:
        assert result.line_of_sight_reason is R.GROUND_INSIDE_REFERENCE_BODY and result.status is V.NOT_VISIBLE
    else:
        assert result.line_of_sight_status is L.CLEAR and result.status is V.VISIBLE
        assert not ref["penetration"]
    with localcontext() as ctx:
        ctx.prec=130
        error=abs(_D(result.geometry.elevation_rad)-ref["elevation"])
        assert error <= _D(result.elevation_allowance_rad)
        actual=tuple(_D(x)/_D(a) for x in result.geometry.ground_state.position.components_m)
        ground_error=sum((x-y)**2 for x,y in zip(actual,ref["ground_scaled"])).sqrt()
        allowance=_D(result.ground_position_allowance_scaled)*(1-_D(p.ellipsoid.flattening.value))
        assert ground_error <= allowance


def test_deterministic_grid_against_independent_root_reference_reports_all_outcomes():
    counts=Counter({x.value:0 for x in V}); los_counts=Counter({x.value:0 for x in L})
    max_angle_ratio=0.; max_sign_ratio=0.; max_angle_error=0.; max_sign_error=0.
    # No random selection and no exception filtering. Every case is asserted.
    for time in (12345.6789,1e9):
        for height in (0.,1000.):
            for latitude,longitude in ((.731,-1.117),(-.4,2.1)):
                p=_point(ellipsoid=wgs84_reference_ellipsoid(),latitude=latitude,longitude=longitude,height=height)
                provisional=_state(p,r=(7e6,2e6,1e6),v=(1.,2.,3.),phase=.271,rate=7.292115e-5,t=time)
                ref=_reference(p,provisional,120); a=p.ellipsoid.equatorial_radius_m.value
                for vertical in (-4e5,-10000.,0.,1e-6,4e5):
                    r=tuple(float(g*_D(a)+Decimal(400000)*e+_D(vertical)*n) for g,e,n in zip(ref["ground_scaled"],ref["east"],ref["up"]))
                    state=_state(p,r=r,v=(1.,2.,3.),phase=.271,rate=7.292115e-5,t=time)
                    ref=_agreed_reference(p,state)
                    for mask in (-.1,0.,.1):
                        result=evaluate_ground_visibility(p,state,_policy(mask))
                        counts[result.status.value]+=1;los_counts[result.line_of_sight_status.value]+=1
                        with localcontext() as ctx:
                            ctx.prec=130
                            angle_error=abs(_D(result.geometry.elevation_rad)-ref["elevation"])
                            assert angle_error<=_D(result.elevation_allowance_rad)
                            max_angle_error=max(max_angle_error,float(angle_error))
                            max_angle_ratio=max(max_angle_ratio,float(angle_error/_D(result.elevation_allowance_rad)))
                            if result.line_of_sight_status is L.CLEAR: assert not ref["penetration"]
                            if result.line_of_sight_status is L.BLOCKED: assert ref["penetration"]
                            true_margin=ref["elevation"]-_D(mask)
                            if result.elevation_status is E.ABOVE: assert true_margin>0
                            if result.elevation_status is E.BELOW: assert true_margin<0
                            key={"surface_departure":"surface_departure","minimum_level":"minimum",
                                 "spacecraft_level":"end_level","spacecraft_half_derivative":"end_derivative"}[result.occultation_predicate]
                            err=abs(_D(result.occultation_signed_value)-ref[key])
                            bound=_D(result.occultation_allowance)
                            assert err<=bound+Decimal("1e-60")
                            max_sign_error=max(max_sign_error,float(err))
                            if bound: max_sign_ratio=max(max_sign_ratio,float(err/bound))
    assert sum(counts.values())==120
    assert counts["VISIBLE"]>0 and counts["NOT_VISIBLE"]>0 and counts["UNRESOLVED"]>0
    print("C2A_REFERENCE_GRID",json.dumps({"final":dict(counts),"line_of_sight":dict(los_counts),
        "max_elevation_error_over_allowance":max_angle_ratio,"max_predicate_error_over_allowance":max_sign_ratio,
        "max_elevation_error_rad":max_angle_error,"max_predicate_error_dimensionless":max_sign_error},sort_keys=True))


def test_nonaxis_near_grazing_is_unresolved_without_a_fictitious_boundary():
    p=_point(ellipsoid=wgs84_reference_ellipsoid(),latitude=.731,longitude=-1.117)
    initial=_state(p,r=(7e6,2e6,1e6),v=(1.,2.,3.),phase=.271,rate=7.292115e-5,t=1e9)
    ref=_reference(p,initial,120);a=p.ellipsoid.equatorial_radius_m.value
    r=tuple(float(g*_D(a)+Decimal(400000)*e) for g,e in zip(ref["ground_scaled"],ref["east"]))
    result=evaluate_ground_visibility(p,_state(p,r=r,v=(1.,2.,3.),phase=.271,rate=7.292115e-5,t=1e9),_policy(-.1))
    assert result.line_of_sight_status is L.UNRESOLVED and result.elevation_status is E.ABOVE
    assert result.status is V.UNRESOLVED and result.occultation_allowance>0
    assert abs(result.occultation_signed_value)<=result.occultation_allowance


@pytest.mark.parametrize("offset,expected", [(-1e-6,L.BLOCKED),(0.,L.UNRESOLVED),(1e-6,L.CLEAR)])
def test_nonaxis_interior_grazing_and_both_resolved_sides(offset,expected):
    p=_point(latitude=0.,longitude=.731,height=.25)
    initial=_state(p,r=(2.,1.,0.),v=(0.,0.,1.),phase=.271,rate=7.292115e-5,t=1e9)
    ref=_reference(p,initial,120)
    # Rotate the exact (p0=5/4, p1=(1/2,1)) tangent construction using the
    # independent normal/east reference, then admit rounded p1 as authority.
    r=tuple(float(Decimal('.5')*n+(Decimal(1)+_D(offset))*e) for n,e in zip(ref["up"],ref["east"]))
    state=_state(p,r=r,v=(0.,0.,1.),phase=.271,rate=7.292115e-5,t=1e9)
    result=evaluate_ground_visibility(p,state,_policy(-1.))
    ref=_agreed_reference(p,state)
    assert result.minimum_location is M.INTERIOR and result.line_of_sight_status is expected
    assert result.elevation_status is E.ABOVE
    if expected is L.BLOCKED: assert ref["penetration"]
    if expected is L.CLEAR: assert not ref["penetration"]
    with localcontext() as ctx:
        ctx.prec=130
        error=abs(_D(result.minimum_level)-ref["minimum"])
        assert error<=_D(result.occultation_allowance)
        print("C2A_GRAZING",offset,expected.value,"level",float(result.minimum_level),
              "error",float(error),"allowance",float(result.occultation_allowance))


@pytest.mark.parametrize("scale", [2.**-900,2.**900])
@pytest.mark.parametrize("height_ratio", [.5, float(2**30)])
def test_nonaxis_extreme_scale_and_flattening_against_decimal(scale,height_ratio):
    p=_point(ellipsoid=_sphere(scale,.5),latitude=.7,longitude=-1.1,height=scale*height_ratio)
    distance=scale*max(1.,height_ratio)
    s=_state(p,r=(2*distance,distance,2*distance),v=(1.,2.,3.),phase=.4,rate=0.,t=0.)
    result=evaluate_ground_visibility(p,s,_policy(-1.))
    ref=_agreed_reference(p,s)
    with localcontext() as ctx:
        ctx.prec=130
        assert abs(_D(result.geometry.elevation_rad)-ref["elevation"])<=_D(result.elevation_allowance_rad)
        assert abs(_D(result.minimum_level)-ref["minimum"])<=_D(result.occultation_allowance)


@pytest.mark.parametrize("p0,p1,s,level,where", [
    ((2,0,0),(3,0,0),0,3,M.GROUND_ENDPOINT),
    ((2,0,0),(Fraction(3,2),0,0),1,Fraction(5,4),M.SPACECRAFT_ENDPOINT),
    ((Fraction(5,4),0,0),(Fraction(1,2),1,0),Fraction(3,5),0,M.INTERIOR),
    ((2,0,0),(-2,0,0),Fraction(1,2),-1,M.INTERIOR),
    ((2,1,0),(1,1,0),1,1,M.SPACECRAFT_ENDPOINT),
])
def test_private_exact_segment_reference_cases(p0,p1,s,level,where):
    result=_segment_minimum(tuple(map(Fraction,p0)),tuple(map(Fraction,p1)))
    assert (result.parameter,result.level,result.location)==(s,level,where)


def test_near_endpoint_penetration_is_not_discarded():
    # Exact helper case: a tiny penetrating region before an on-body endpoint.
    # D1=2^-70>0 proves entry before arrival independently of quadratic roots.
    p0=(Fraction(1)-Fraction(1,2**70),Fraction(1,2**20),Fraction(0))
    p1=(Fraction(1),Fraction(0),Fraction(0))
    endpoint=_segment_minimum(p0,p1)
    assert endpoint.c>0 and endpoint.end_level==0
    assert endpoint.location is M.INTERIOR and endpoint.level<0
    assert 0<1-endpoint.parameter<Fraction(1,10**6)
    assert _occultation(Fraction(1),p0,p1,Fraction(0),endpoint)[:2] == (L.BLOCKED,R.INTERIOR_PENETRATION)
