"""Independent short references; no propagation campaigns or scenario dependency."""
from dataclasses import replace
from decimal import Decimal, localcontext
from math import hypot, nextafter, inf, pi
import copy

import pytest

from examples.m2_orbit_sun_demo import demo_query
from examples.v5_experiment_bundle_demo import build_demo_state
from examples.v5_j2_enclosure_pilot import inputs as pilot_trajectory
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.context import with_coast_orbit, with_j2_coast_orbit
from ops_sim.v5.experiment_codec import canonical_content
from ops_sim.v5.frames import CartesianPosition, CartesianDirection, transform_direction
from ops_sim.v5.orbit import evaluate_two_body_state
from ops_sim.v5.orbit_config import GeometryInstant, FrameKind
from ops_sim.v5.orbit_j2_enclosure import evaluate_j2_enclosure
from ops_sim.v5.orbit_sun import (
    SuppliedSunDirection, OrbitSunQuery, evaluate_orbit_sun, evaluate_context_orbit_sun,
    nominal_parallel_ray, _qualified,
)
from test_v56a_time_frame_contracts import _model, _sphere


def ray(r, d, flattening=0., radius=1.):
    _, frame = _model(ellipsoid=_sphere(radius, flattening))
    t = GeometryInstant(frame.rotation.epoch, 0.)
    return CartesianPosition(frame, t, r), SuppliedSunDirection(
        CartesianDirection(frame, t, d), "SYNTHETIC", (), "Hand-solvable synthetic ray")


@pytest.mark.parametrize("r,d,expected", [
    ((2.,0.,0.), (1.,0.,0.), "ILLUMINATED"),
    ((2.,0.,0.), (-1.,0.,0.), "OCCULTED"),
    ((2.,1.,0.), (-1.,0.,0.), "TANGENT"),
    ((2.,nextafter(1.,inf),0.), (-1.,0.,0.), "ILLUMINATED"),
    ((2.,nextafter(1.,0.),0.), (-1.,0.,0.), "OCCULTED"),
    ((2.,0.,0.), (0.,1.,0.), "ILLUMINATED"),
    ((-2.,0.,0.), (1.,0.,0.), "OCCULTED"),
    ((0.,0.,0.), (1.,0.,0.), "INVALID_POSITION"),
    ((1.,0.,0.), (1.,0.,0.), "INVALID_POSITION"),
    ((.5,0.,0.), (1.,0.,0.), "INVALID_POSITION"),
])
def test_analytic_sphere(r, d, expected):
    assert nominal_parallel_ray(*ray(r,d)) == expected


@pytest.mark.parametrize("z,expected", [(.5,"TANGENT"),(.75,"ILLUMINATED"),(.25,"OCCULTED")])
def test_oblate_shape_not_equatorial_sphere(z, expected):
    assert nominal_parallel_ray(*ray((2.,0.,z),(-1.,0.,0.),.5)) == expected
    assert nominal_parallel_ray(*ray((2.,0.,z),(-1.,0.,0.),0.)) == "OCCULTED"


@pytest.mark.parametrize("scale", [2.**-1000,1.,2.**1000])
def test_positive_scaling_and_extreme_magnitudes(scale):
    assert nominal_parallel_ray(*ray((2.,1.,0.),(-scale,0.,0.))) == "TANGENT"
    assert nominal_parallel_ray(*ray((2.*scale,scale,0.),(-1.,0.,0.),radius=scale)) == "TANGENT"


@pytest.mark.parametrize("r,d", [
    ((2.,.25,.125),(-3.,.5,.25)), ((2.,2.,2.),(-1.,2.,-1.)),
    ((-3.,1.,.75),(2.,-.5,.125)), ((1.5,-2.,.2),(-.5,1.,-.125)),
    ((4.,.5,.75),(-2.,.1,.3)), ((.25,.25,2.),(1.,0.,-3.)),
])
def test_independent_decimal_quadratic_roots(r,d):
    # Solve the ray/surface equation with explicit roots in 90-digit Decimal.
    # Inputs selected far from tangent; reference uses sqrt, not interval sign.
    with localcontext() as ctx:
        ctx.prec=90
        xyz=list(map(Decimal.from_float,r)); v=list(map(Decimal.from_float,d))
        axes=[Decimal(1),Decimal(1),Decimal('.5')]
        a=sum((x/b)**2 for x,b in zip(v,axes))
        b=2*sum(x*y/z**2 for x,y,z in zip(xyz,v,axes))
        c=sum((x/z)**2 for x,z in zip(xyz,axes))-1
        disc=b*b-4*a*c
        roots=[] if disc<0 else [(-b-disc.sqrt())/(2*a),(-b+disc.sqrt())/(2*a)]
        expected="OCCULTED" if any(x>=0 for x in roots) else "ILLUMINATED"
    assert nominal_parallel_ray(*ray(r,d,.5)) == expected


def test_qualification_boundary_box_and_tangent_convention():
    position,sun=ray((2.,1.,0.),(-1.,0.,0.))
    point=((Decimal(2),Decimal(2)),(Decimal(1),Decimal(1)),(Decimal(0),Decimal(0)))
    assert _qualified(position.frame.ellipsoid,sun.direction,point)[0]=="OCCULTED"
    box=(point[0],(Decimal(".999"),Decimal("1.001")),point[2])
    assert _qualified(position.frame.ellipsoid,sun.direction,box)[0]=="UNRESOLVED"
    assert _qualified(position.frame.ellipsoid,sun.direction,
                      ((Decimal(0),Decimal(2)),point[2],point[2]))[0]=="UNRESOLVED"


@pytest.mark.parametrize("kind",["j2","two-body","unresolved","rotated"])
def test_original_owners_and_nonmutation(kind):
    q=demo_query(kind); before=copy.deepcopy(q)
    result=evaluate_orbit_sun(q)
    assert q==before
    assert result.query==q
    assert abs(hypot(*result.unit_sun_direction.components)-1)<2e-15
    assert result.sun_direction.instant==q.instant
    if kind=="two-body":
        expected=evaluate_two_body_state(q.coast.trajectory,q.instant,q.coast.solver_config)
        assert result.orbit_state==expected
        assert result.shadow.qualified=="UNRESOLVED"
        assert result.j2_evidence is None
    else:
        expected=evaluate_j2_enclosure(q.coast.trajectory,q.instant,q.coast.solver_config,q.coast.enclosure_policy)
        assert result.j2_evidence==expected
        assert result.orbit_state==expected.nominal_state
        if kind=="unresolved":
            assert expected.status=="unresolved"
            assert result.orbit_state is None and result.shadow.nominal is None
            assert result.shadow.qualified=="UNRESOLVED"
            assert expected.reason in result.shadow.reason
        elif kind=="j2":
            assert result.shadow.qualified=="OCCULTED"
            assert expected.position_error_bound_m>0
        else:
            assert result.shadow.qualified=="UNRESOLVED"
            assert result.shadow.reason=="SUN_FRAME_TRANSFORM_ERROR_NOT_ENCLOSED"


@pytest.mark.parametrize("direction,expected",[((1.,0.,0.),"ILLUMINATED"),((-1.,0.,0.),"OCCULTED")])
def test_j2_certified_sides(direction,expected):
    q=demo_query()
    q=replace(q,sun=replace(q.sun,direction=replace(q.sun.direction,components=direction)))
    r=evaluate_orbit_sun(q)
    assert r.shadow.nominal==r.shadow.qualified==expected


def test_equivalent_compatible_frames_nominal_only():
    q=demo_query()
    fixed=replace(q.sun.direction.frame,kind=FrameKind.EARTH_FIXED)
    d=transform_direction(q.sun.direction,fixed)
    transformed=replace(q,sun=replace(q.sun,direction=d))
    a,b=evaluate_orbit_sun(q),evaluate_orbit_sun(transformed)
    assert a.shadow.nominal==b.shadow.nominal
    assert b.shadow.qualified=="UNRESOLVED"
    for x,y in zip(a.unit_sun_direction.components,b.unit_sun_direction.components):
        assert abs(x-y)<2e-15


@pytest.mark.parametrize("kind",["two-body","j2"])
def test_context_actual_clock_original_epoch_and_complete_nonmutation(kind):
    q=demo_query(kind)
    # Original sample 128 s; actual clock 127 means backward 1 s, not 255 s.
    if kind=="j2":
        q=replace(q,coast=replace(q.coast,
            trajectory=pilot_trajectory(False),
            enclosure_policy=replace(q.coast.enclosure_policy,step_seconds=.25),
            solver_config=replace(q.coast.solver_config,step_seconds=.25)))
    context=build_demo_state().context
    bind=with_coast_orbit if kind=="two-body" else with_j2_coast_orbit
    context=replace(context,inputs=bind(context.inputs,q.coast),simulation_time_seconds=127)
    at=GeometryInstant(q.instant.epoch,127.)
    q=replace(q,instant=at,sun=replace(q.sun,direction=replace(q.sun.direction,instant=at)))
    before=copy.deepcopy(context)
    a=evaluate_context_orbit_sun(context,q.sun)
    assert context==before
    assert a==evaluate_orbit_sun(q)
    assert a.query.instant.elapsed_seconds==127
    assert a.query.coast.trajectory.initial_state.position.instant.elapsed_seconds==128
    assert a.orbit_state.position.instant==at


@pytest.mark.parametrize("change",["instant","epoch","shape","phase","kind-type"])
def test_incompatible_inputs_rejected_before_query(change):
    q=demo_query();d=q.sun.direction
    if change=="instant":
        d=replace(d,instant=replace(d.instant,elapsed_seconds=129.))
    elif change=="epoch":
        epoch=replace(d.instant.epoch,julian_day=d.instant.epoch.julian_day+1)
        d=replace(d,instant=replace(d.instant,epoch=epoch),frame=replace(
            d.frame,rotation=replace(d.frame.rotation,epoch=epoch)))
    elif change=="shape":
        d=replace(d,frame=replace(d.frame,ellipsoid=_sphere(1.,.5)))
    elif change=="phase":
        r=d.frame.rotation
        d=replace(d,frame=replace(d.frame,rotation=replace(r,initial_phase_rad=replace(r.initial_phase_rad,value=.125))))
    else:
        with pytest.raises(TypeError): replace(d.frame,kind="MODEL_INERTIAL")
        return
    with pytest.raises(ValueError): replace(q,sun=replace(q.sun,direction=d))


@pytest.mark.parametrize("v",[True,float("nan"),float("inf"),0.])
def test_invalid_direction_inputs(v):
    q=demo_query()
    with pytest.raises((TypeError,ValueError)):
        replace(q.sun,direction=replace(q.sun.direction,components=(v,0.,0.)))


@pytest.mark.parametrize("kwargs",[{"origin":"unknown"},{"origin":"EXTERNALLY_SUPPLIED"},
                                  {"rationale":""},{"source_ids":[]},{"rationale":"\ud800"}])
def test_provenance_required_and_strict(kwargs):
    with pytest.raises((TypeError,ValueError,UnicodeError)): replace(demo_query().sun,**kwargs)


def test_no_global_codec_or_deferred_scenario_dependency():
    import sys
    with pytest.raises(TypeError,match="unsupported canonical type"):
        canonical_content(demo_query().sun.direction)
    assert "ops_sim.v5.scenario_inputs" not in sys.modules


def test_context_unresolved_retains_missing_state_and_bound():
    q=demo_query("unresolved")
    context=build_demo_state().context
    context=replace(context,inputs=with_j2_coast_orbit(context.inputs,q.coast),simulation_time_seconds=129)
    at=replace(q.instant,elapsed_seconds=129.)
    sun=replace(q.sun,direction=replace(q.sun.direction,instant=at))
    before=copy.deepcopy(context)
    result=evaluate_context_orbit_sun(context,sun)
    assert context==before
    assert result.query.instant==at
    assert result.j2_evidence.status=="unresolved"
    assert result.orbit_state is None
    assert result.j2_evidence.position_error_bound_m is None
    assert result.shadow.nominal is None
    assert result.shadow.qualified=="UNRESOLVED"


@pytest.mark.parametrize("center,width,expected",[
    ((2.,0.,0.),.01,"OCCULTED"),((2.,2.,0.),.01,"ILLUMINATED"),
    ((-2.,0.,0.),.01,"ILLUMINATED"),((2.,1.,0.),.01,"UNRESOLVED"),
])
def test_box_classifications_against_independent_sampled_roots(center,width,expected):
    from itertools import product
    pos,sun=ray(center,(-1.,0.,0.))
    box=tuple((Decimal.from_float(x)-Decimal.from_float(width),
               Decimal.from_float(x)+Decimal.from_float(width)) for x in center)
    classification,_=_qualified(pos.frame.ellipsoid,sun.direction,box)
    assert classification==expected
    # For d=(-1,0,0), ray reaches the unit sphere iff transverse y²+z²<=1
    # and starts to its right. This is independent of production interval D.
    labels=set()
    for x,y,z in product(*[(a,(a+b)/2,b) for a,b in box]):
        labels.add("OCCULTED" if x>0 and y*y+z*z<=1 else "ILLUMINATED")
    if classification!="UNRESOLVED": assert labels=={classification}
    else: assert len(labels)==2


def test_j2_zero_span_retains_owners_genuine_zero_error():
    q=demo_query()
    at=q.coast.trajectory.initial_state.position.instant
    q=replace(q,instant=at,sun=replace(q.sun,direction=replace(q.sun.direction,instant=at)))
    r=evaluate_orbit_sun(q)
    assert r.j2_evidence.enclosure_steps==0
    assert r.j2_evidence.position_error_bound_m==0.
    assert r.orbit_state==q.coast.trajectory.initial_state
    assert r.shadow.qualified=="OCCULTED"
