"""Independent temporal model equations: missed events, Decimal orbit/geodesy.

The Decimal oracle uses B1's independently derived elliptic (not universal)
reference and independently constructs support-surface geodesy/rotation and
restricted segment distance. Positions remain Decimal through classification.
90/120 digits agree to 1e-60 in tested SI positions/dimensionless/radian values;
this is oracle convergence, not a production event-time accuracy claim.
"""

from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
from types import SimpleNamespace
import json
import math

import pytest

from ops_sim.v5.orbit import TwoBodyTrajectory, evaluate_two_body_state
from ops_sim.v5.orbit_config import GeometryInstant, wgs84_reference_ellipsoid
from ops_sim.v5.orbit_visibility import evaluate_ground_visibility, GroundVisibilityStatus as V
import ops_sim.v5.orbit_visibility_windows as windows
from ops_sim.v5.orbit_visibility_windows import (
    GroundVisibilitySearchConfig as Config, TemporalVisibilityStatus as S,
    TemporalUnresolvedReason as R, find_ground_visibility_windows as find,
)
from test_v56a_time_frame_contracts import _parameter
from test_v56b1_two_body_propagation import _reference as orbit_reference, _pi, _sincos, _atan2
from test_v56c1_ground_point_contracts import _point, _state
from test_v56c2a_visibility_contracts import _policy
from test_v56c2b_window_contracts import _run_inputs, _search, _coverage


def _statistics(result, true_visible=None):
    measures = {s.value: sum(c.end_seconds-c.start_seconds for c in result.cells if c.status is s) for s in S}
    out = {"measure_seconds": measures,
        "maximum_unresolved_width_seconds": max((c.end_seconds-c.start_seconds for c in result.cells if c.status is S.UNRESOLVED), default=0.),
        "evaluation_count": result.evaluation_count}
    if true_visible is not None:
        out.update(analytic_true_visible_seconds=true_visible,
                   conservative_visible_difference_seconds=true_visible-measures["VISIBLE"])
        assert 0 <= true_visible-measures["VISIBLE"] <= measures["UNRESOLVED"]+1e-12
    print("C2B_REFERENCE", json.dumps(out, sort_keys=True))
    return out


def _independent_times(cell):
    # Additional fractions are deliberately unrelated to midpoint subdivision.
    lo, hi = Fraction(cell.start_seconds), Fraction(cell.end_seconds)
    return tuple(float(lo+(hi-lo)*q) for q in (Fraction(0), Fraction(1,7), Fraction(1,2), Fraction(11,13), Fraction(1)))


def _check_analytic_cells(result, pass_at, boundaries):
    _coverage(result)
    for cell in result.cells:
        if cell.status is not S.UNRESOLVED:
            for t in _independent_times(cell):
                assert pass_at(t) == (cell.status is S.VISIBLE), (cell, t)
    for t in boundaries:
        assert any(c.status is S.UNRESOLVED and c.start_seconds <= t <= c.end_seconds for c in result.cells)


@pytest.mark.parametrize("sample", [10, 20, 60])
def test_short_visible_pass_hidden_between_equal_not_visible_seed_samples(sample):
    inputs = _run_inputs(sample=sample)
    coast = inputs.coast_orbit; point = _point(); policy = _policy(0.)
    for t in (2., 6., 14., 18.):
        state = evaluate_two_body_state(coast.trajectory, GeometryInstant(coast.trajectory.initial_state.position.instant.epoch, t), coast.solver_config)
        assert evaluate_ground_visibility(point, state, policy).status is V.NOT_VISIBLE
    result = find(inputs, point, policy, 2., 18., Config(.015625, 10000))
    half = math.acos(.5)/.5
    assert sample > 2*half
    if sample >= 20:
        assert list(windows._seeds(2.,18.,sample)) == [(2.,18.)]
        assert 2 < 10-half < 10+half < 18
    assert result.visible_windows and result.complete_to_tolerance
    _check_analytic_cells(result, lambda t: abs(t-10) < half, (10-half, 10+half))
    stats = _statistics(result, 2*half)
    assert stats["maximum_unresolved_width_seconds"] <= .015625


@pytest.mark.parametrize("sample", [10, 20])
def test_short_not_visible_gap_hidden_between_equal_visible_seed_samples(sample):
    point = _point(height=3.)
    trajectory = TwoBodyTrajectory(_state(point, r=(-4.,0.,0.), v=(0.,-1.,0.), t=10.),
        _parameter("orbit.gravity.gravitational-parameter", "m^3/s^2", 4.))
    inputs = _run_inputs(trajectory, sample=sample)
    coast = inputs.coast_orbit; policy = _policy(-math.pi/2)
    for t in (2., 6., 14., 18.):
        state = evaluate_two_body_state(trajectory, GeometryInstant(trajectory.initial_state.position.instant.epoch, t), coast.solver_config)
        assert evaluate_ground_visibility(point, state, policy).status is V.VISIBLE
    result = find(inputs, point, policy, 2., 18., Config(.03125, 15000))
    # Equal radii4: restricted chord distance is4*abs(sin(.25*(t-10)/2)).
    half_gap = 8*math.asin(.25)
    assert sample > 2*half_gap
    if sample >= 20:
        assert list(windows._seeds(2.,18.,sample)) == [(2.,18.)]
        assert 2 < 10-half_gap < 10+half_gap < 18
    assert len(result.visible_windows) == 2 and result.complete_to_tolerance
    _check_analytic_cells(result, lambda t: abs(t-10) > half_gap, (10-half_gap, 10+half_gap))
    assert any(c.status is S.NOT_VISIBLE and c.start_seconds <= 10 <= c.end_seconds for c in result.cells)
    _statistics(result, 16-2*half_gap)


def test_tangent_singleton_is_never_a_positive_duration_pass():
    point = _point()
    trajectory = TwoBodyTrajectory(_state(point, r=(1.,2.,2.), v=(0.,2.,-2.), t=10.),
        _parameter("orbit.gravity.gravitational-parameter", "m^3/s^2", 24.))
    inputs = _run_inputs(trajectory, sample=20)
    result = find(inputs, point, _policy(0.), 9., 11., Config(.015625, 20000))
    # |r|=3, r.v=0, v²=mu/3=8. x(t)=cos(sqrt(8/9)*(t-10))<=1.
    assert not result.visible_windows and result.complete_to_tolerance
    assert any(c.status is S.NOT_VISIBLE for c in result.cells)
    assert any(c.status is S.UNRESOLVED and c.start_seconds <= 10 <= c.end_seconds for c in result.cells)
    _check_analytic_cells(result, lambda t: False, (10.,))
    _statistics(result, 0.)


@pytest.mark.parametrize("tolerance", [32., 2., .125, .015625])
def test_tolerance_is_cell_width_target_not_sample_or_function_accuracy(tolerance):
    result = _search(inputs=_run_inputs(sample=60), config=Config(tolerance, 10000))
    _coverage(result)
    assert result.complete_to_tolerance
    assert all(c.end_seconds-c.start_seconds <= tolerance for c in result.cells if c.status is S.UNRESOLVED)
    if tolerance > 16:
        assert not result.visible_windows and len(result.cells) == 1
    elif tolerance < 2:
        assert result.visible_windows


def test_refinement_reduces_uncertainty_without_outward_windows():
    coarse, fine = (_search(config=Config(tol, 10000)) for tol in (.25, .015625))
    a, b = _statistics(coarse, 4*math.pi/3), _statistics(fine, 4*math.pi/3)
    assert b["measure_seconds"]["UNRESOLVED"] < a["measure_seconds"]["UNRESOLVED"]
    assert b["measure_seconds"]["VISIBLE"] >= a["measure_seconds"]["VISIBLE"]
    for old in coarse.visible_windows:
        assert any(new.start_seconds <= old.start_seconds and new.end_seconds >= old.end_seconds for new in fine.visible_windows)


@pytest.mark.parametrize("budget", [1, 2, 3, 9])
def test_evaluation_budget_retains_all_uncertainty_without_false_window(budget):
    result = _search(config=Config(.00001, budget))
    assert result.evaluation_count == budget and not result.complete_to_tolerance
    assert any(c.unresolved_reason is R.EVALUATION_LIMIT for c in result.cells)
    _check_analytic_cells(result, lambda t: abs(t-10) < 2*math.pi/3, (10-2*math.pi/3, 10+2*math.pi/3))


def test_negative_height_is_whole_cell_failure_without_transition_search():
    result = _search(point=_point(height=-.1), inputs=_run_inputs(sample=60))
    assert result.evaluation_count == 1 and result.complete_to_tolerance
    assert len(result.cells) == 1 and result.cells[0].status is S.NOT_VISIBLE
    assert result.cells[0].line_of_sight_temporal_allowance == 0.


def test_asymmetric_rounded_midpoint_uses_larger_edge_reach(monkeypatch):
    start = .1; end = math.nextafter(math.nextafter(math.nextafter(start, math.inf), math.inf), math.inf)
    observed = []
    original = windows._classify
    def classify(evidence, envelope, reach):
        observed.append(reach)
        return original(evidence, envelope, reach)
    monkeypatch.setattr(windows, "_classify", classify)
    result = _search(start=start, end=end, config=Config(1., 1))
    midpoint = result.cells[0].representative_seconds
    assert observed == [max(Fraction(midpoint)-Fraction(start), Fraction(end)-Fraction(midpoint))]
    assert observed[0] > (Fraction(end)-Fraction(start))/2


def _D(value):
    return Decimal.from_float(value)


def _oracle(trajectory, point, policy, t, precision):
    """Independent exact-binary-input orbit + support geometry, no production query."""
    with localcontext() as ctx:
        ctx.prec = precision
        eps = Decimal(10)**(-precision+8); pi = _pi(eps/100)
        ref = orbit_reference(trajectory, SimpleNamespace(elapsed_seconds=t), precision)
        position = ref["r"]  # Do NOT round oracle positions through CartesianState.
        a, f, height = map(_D, (point.ellipsoid.equatorial_radius_m.value,
            point.ellipsoid.flattening.value, point.ellipsoidal_height_m.value))
        sp, cp = _sincos(_D(point.latitude_rad.value), pi, eps)
        sl, cl = _sincos(_D(point.longitude_rad.value), pi, eps)
        normal = (cp*cl, cp*sl, sp); axes = (a, a, a*(1-f))
        dot = lambda a,b: sum(x*y for x,y in zip(a,b))
        support = sum((axis*n)**2 for axis,n in zip(axes,normal)).sqrt()
        fixed = tuple(axis*axis*n/support+height*n for axis,n in zip(axes,normal))
        rotation = trajectory.initial_state.position.frame.rotation
        phase = _D(rotation.initial_phase_rad.value)+_D(rotation.angular_velocity_rad_per_s.value)*_D(t)
        s, c = _sincos(phase, pi, eps)
        rot = lambda v: (c*v[0]-s*v[1], s*v[0]+c*v[1], v[2])
        ground, up = rot(fixed), rot(normal)
        ray = tuple(x-y for x,y in zip(position,ground))
        east, north = rot((-sl,cl,Decimal(0))), rot((-sp*cl,-sp*sl,cp))
        elevation = _atan2(dot(ray,up), (dot(ray,east)**2+dot(ray,north)**2).sqrt(), pi, eps)
        p0,p1 = (tuple(x/axis for x,axis in zip(v,axes)) for v in (ground,position))
        direction = tuple(y-x for x,y in zip(p0,p1))
        along = -dot(p0,direction)/dot(direction,direction)
        if along <= 0:
            level = dot(p0,p0)-1
        elif along >= 1:
            level = dot(p1,p1)-1
        else:
            cross = (p0[1]*p1[2]-p0[2]*p1[1],p0[2]*p1[0]-p0[0]*p1[2],p0[0]*p1[1]-p0[1]*p1[0])
            level = dot(cross,cross)/dot(direction,direction)-1
        departure = dot(p0,p1)-1
        los_margin = Decimal(-1) if height < 0 else departure if height == 0 else level
        elevation_margin = elevation-_D(policy.minimum_elevation_rad.value)
        return {"r":position, "los_margin":los_margin, "elevation_margin":elevation_margin,
                "visible":los_margin > 0 and elevation_margin > 0}


def _agreed_oracle(trajectory, point, policy, t):
    first, second = (_oracle(trajectory, point, policy, t, p) for p in (90,120))
    with localcontext() as ctx:
        ctx.prec = 130
        for key in ("r", "los_margin", "elevation_margin"):
            a,b = first[key],second[key]
            if not isinstance(a,tuple): a,b=(a,),(b,)
            assert all(abs(x-y)<Decimal("1e-60") for x,y in zip(a,b)), (t,key)
        assert first["visible"] == second["visible"]
    return second


def _offaxis_case(height=0.):
    point = _point(ellipsoid=wgs84_reference_ellipsoid(), latitude=.4, longitude=.3, height=height)
    phase, rate, t0, radius = .1, 7.292115e-5, 900., 7200000.
    latitude, longitude = .4, .3+phase+rate*t0
    cp,sp,cl,sl = math.cos(latitude),math.sin(latitude),math.cos(longitude),math.sin(longitude)
    normal = (cp*cl,cp*sl,sp); east=(-sl,cl,0.); north=(-sp*cl,-sp*sl,cp)
    mu = 398600441800000.; speed=.98*math.sqrt(mu/radius)
    state = _state(point,r=tuple(radius*x for x in normal),
        v=tuple(speed*(.8*x+.6*y) for x,y in zip(east,north)),phase=phase,rate=rate,t=t0)
    return TwoBodyTrajectory(state,_parameter("orbit.gravity.gravitational-parameter","m^3/s^2",mu)), point, _policy(.1)


def _reference_event_brackets(trajectory, point, policy, precision):
    # Independent 37-point exploration then 40 dyadic bisections per crossing.
    # These are oracle brackets only, never production window endpoints.
    times = [float(t) for t in range(0,1801,50)]
    statuses = [_oracle(trajectory,point,policy,t,precision)["visible"] for t in times]
    brackets=[]
    for i in range(len(times)-1):
        if statuses[i] == statuses[i+1]: continue
        lo,hi,initial=times[i],times[i+1],statuses[i]
        for _ in range(40):
            mid=(lo+hi)/2
            if _oracle(trajectory,point,policy,mid,precision)["visible"] == initial: lo=mid
            else: hi=mid
        brackets.append((lo,hi))
    return brackets


@pytest.mark.parametrize("height", [0., 100000.])
def test_offaxis_wgs84_against_independent_decimal_orbit_geodesy_and_event_regions(height):
    trajectory,point,policy = _offaxis_case(height)
    inputs = _run_inputs(trajectory,sample=600,horizon=1800,tolerance=1e-8)
    result = find(inputs,point,policy,0.,1800.,Config(.5,20000))
    assert result.complete_to_tolerance and result.visible_windows
    _coverage(result)
    references={}
    def reference(t):
        if t not in references: references[t]=_agreed_oracle(trajectory,point,policy,t)
        return references[t]
    for cell in result.cells:
        for t in _independent_times(cell):
            ref=reference(t)
            if cell.status is S.VISIBLE: assert ref["visible"], (cell,t,ref)
            if cell.status is S.NOT_VISIBLE: assert not ref["visible"], (cell,t,ref)
    brackets90 = _reference_event_brackets(trajectory,point,policy,90)
    brackets120 = _reference_event_brackets(trajectory,point,policy,120)
    assert brackets90 == brackets120 and len(brackets120) == 2
    for lo,hi in brackets120:
        assert hi-lo < 1e-9  # 50s/2**40 plus binary64 timestamp rounding.
        # Both independent brackets are wholly retained in unresolved coverage.
        covered = [c for c in result.cells if c.start_seconds < hi and c.end_seconds > lo]
        assert covered and all(c.status is S.UNRESOLVED for c in covered)
        reference(lo); reference(hi)
    stats=_statistics(result)
    assert stats["maximum_unresolved_width_seconds"] <= .5
    print("C2B_WGS84_EVENT_BRACKETS",json.dumps(brackets120))
    print("C2B_WGS84_REFERENCE_POINTS",len(references))


def test_low_elevated_point_can_need_finer_width_than_surface_point():
    trajectory,point,policy=_offaxis_case(1000.)
    inputs=_run_inputs(trajectory,sample=600,horizon=1800,tolerance=1e-8)
    coarse=find(inputs,point,policy,899.,901.,Config(.5,1000))
    fine=find(inputs,point,policy,899.,901.,Config(.03125,1000))
    # The exact segment minimum is the low elevated ground endpoint. Its
    # small positive level requires finer cells under the global rate bound.
    assert coarse.complete_to_tolerance and not coarse.visible_windows
    assert fine.complete_to_tolerance and fine.visible_windows
    for result in (coarse,fine):
        _coverage(result)
        for cell in result.cells:
            for t in _independent_times(cell):
                assert _agreed_oracle(trajectory,point,policy,t)["visible"]


@pytest.mark.parametrize("scale", [2.**-100, 1., 2.**100])
def test_scale_safe_model_envelope_against_exact_circular_invariants(scale):
    from test_v56a_time_frame_contracts import _sphere
    point=_point(ellipsoid=_sphere(scale))
    trajectory=TwoBodyTrajectory(_state(point,r=(2*scale,0.,0.),v=(0.,scale,0.),t=10.),
        _parameter("orbit.gravity.gravitational-parameter","m^3/s^2",2*scale**3))
    inputs=_run_inputs(trajectory)
    epoch=trajectory.initial_state.position.instant.epoch
    envelope=windows._envelope(inputs,point,GeometryInstant(epoch,2.),GeometryInstant(epoch,18.))
    assert envelope.radius_s >= 2 and envelope.rate_s >= 1
    assert envelope.relative_speed >= Fraction(scale)
    result=find(inputs,point,_policy(0.),2.,18.,Config(.0625,10000))
    _check_analytic_cells(result,lambda t: abs(t-10)<2*math.pi/3,(10-2*math.pi/3,10+2*math.pi/3))


def test_loose_b1_numerical_anchor_reserve_does_not_fabricate_visibility():
    # Still inside V0*eta/rp<=2^-10; reserve deliberately exceeds tiny cell widths.
    inputs=_run_inputs(tolerance=.001)
    result=_search(inputs, start=10-2*math.pi/3-.001,end=10-2*math.pi/3+.001,
                   config=Config(.00001,10000))
    _check_analytic_cells(result,lambda t: abs(t-10)<2*math.pi/3,(10-2*math.pi/3,))
    assert any(c.status is S.UNRESOLVED for c in result.cells)
