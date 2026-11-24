"""Real visibility composition and independent D1a direction/step references."""

from copy import deepcopy
from dataclasses import fields, replace
from fractions import Fraction
from types import SimpleNamespace
import json
import math
import sys

import pytest

from ops_sim.v5.checkpoint import CheckpointState, CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.context import with_coast_orbit
from ops_sim.v5.frames import CartesianPosition, CartesianState, CartesianVelocity
from ops_sim.v5.ids import GroundTargetId, ObservationOpportunityId
from ops_sim.v5.orbit import TwoBodyTrajectory
from ops_sim.v5.orbit_binding import CoastOrbitInputs, COAST_BINDING_VERSION
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.orbit_visibility_grid import EngineGridVisibilityBlock as Block
from ops_sim.v5.orbit_visibility_windows import GroundVisibilityWindow as Window, GroundVisibilitySearchConfig as Config
import ops_sim.v5.orbit_observation_opportunity as adapter
from test_v50d1_time_engine import _context as generic_context
from test_v56a_time_frame_contracts import _parameter
from test_v56c1_ground_point_contracts import _state
from test_v56c2a_visibility_contracts import _policy
from test_v56c2c_grid_projection_contracts import _inputs
from test_v56d1a_observation_opportunity_contracts import Result, derive, _arguments, _result, _request, _target


def _assert_evidence(result, args):
    p = result.visibility_projection
    for name in ("inputs", "policy", "search_start_seconds", "search_end_seconds", "search_config", "first_step_start_seconds"):
        assert getattr(result, name) is getattr(p, name)
    assert result.target is p.point
    assert result.supporting_visibility_block is next(b for b in p.blocks
        if b.first_start_time_seconds <= result.step_start_seconds < b.last_end_time_seconds)
    assert result.geometry.point == result.target and result.geometry.spacecraft_state == result.spacecraft_state
    assert result.spacecraft_state.position.instant.elapsed_seconds == args["step_start_seconds"]
    assert result.spacecraft_state.position.instant.epoch == args["inputs"].coast_orbit.trajectory.initial_state.position.instant.epoch
    assert result.request.request_id is args["request"].request_id
    assert result.request.target_id is args["request"].target_id
    assert result.opportunity_id is args["opportunity_id"]
    o = result.opportunity
    assert o.opportunity_id is args["opportunity_id"] and o.request_id is args["request"].request_id
    assert (o.window_start_seconds, o.window_end_seconds, o.imaging_duration_seconds) == (
        args["step_start_seconds"], args["step_start_seconds"]+p.timestep_seconds, p.timestep_seconds)


def test_real_hidden_pass_one_projection_then_one_explicit_start_snapshot(monkeypatch):
    calls, returned = [], {}
    for name in ("project_ground_visibility_to_engine_grid", "evaluate_two_body_state", "evaluate_ground_point_geometry"):
        owner = getattr(adapter, name)
        def spy(*args, _name=name, _owner=owner):
            calls.append((_name, args))
            value = _owner(*args)
            returned[_name] = value
            return value
        monkeypatch.setattr(adapter, name, spy)
    args = _arguments()
    result = derive(**args)
    assert [name for name, _ in calls] == [
        "project_ground_visibility_to_engine_grid", "evaluate_two_body_state", "evaluate_ground_point_geometry"]
    assert all(actual is original for actual, original in zip(calls[0][1], list(args.values())[:7]))
    p = result.visibility_projection
    assert p is returned[calls[0][0]] and not p.all_search_cells_resolved
    trajectory, instant, solver = calls[1][1]
    assert trajectory is p.inputs.coast_orbit.trajectory and solver is p.inputs.coast_orbit.solver_config
    # Initial state is at10; the selected snapshot must be9, not10+9.
    assert trajectory.initial_state.position.instant.elapsed_seconds == 10.
    assert instant == GeometryInstant(trajectory.initial_state.position.instant.epoch, 9)
    assert calls[2][1][0] is p.point and calls[2][1][1] is result.spacecraft_state
    assert result.spacecraft_state is returned[calls[1][0]] and result.geometry is returned[calls[2][0]]
    _assert_evidence(result, args)
    assert (result.opportunity.window_start_seconds, result.opportunity.window_end_seconds) == (9, 12)
    assert result.opportunity.window_end_seconds-result.opportunity.imaging_duration_seconds == 9
    # Independent circular orbit: radius2m, speed1m/s, n=0.5rad/s, theta=-0.5.
    # For this circular case B1's residual-adjusted endpoint is
    # r(q)=(2cos(q),2sin(q)-e,0), q=-0.5+e/2, with residual e in seconds.
    # Its first-order position error is 2|sin(0.25)| |e| <0.5|e| metres.
    # LOS>=1m and radius2m give off-angle sensitivity <0.75|e| rad.
    # With |e|<=1e-10s, 1e-8deg includes this fixed-case bound, negligible
    # O(e^2) terms and binary64 operations; no general along-track law is assumed.
    expected = math.atan2(-math.sin(-.5), 2-math.cos(-.5))*180/math.pi
    assert result.opportunity.pointing.view_angle_from_nadir_deg == pytest.approx(expected, rel=0, abs=1e-8)
    assert result.opportunity.pointing.view_azimuth_deg == 0.


@pytest.mark.parametrize("changes", [
    {"inputs": _inputs(60)}, {"first_step_start_seconds": 1},
    {"step_start_seconds": 10}, {"step_start_seconds": 8}, {"step_start_seconds": 12},
    {"target": _target(height=-.1)},
])
def test_real_missing_or_nongrid_step_rejects_before_pointing_snapshot(monkeypatch, changes):
    def forbidden(*args): pytest.fail("unsupported selected step reached explicit pointing snapshot")
    monkeypatch.setattr(adapter, "evaluate_two_body_state", forbidden)
    monkeypatch.setattr(adapter, "evaluate_ground_point_geometry", forbidden)
    with pytest.raises(ValueError, match="engine step.*visibility support"): _result(**changes)


def _block(first=60, dt=60, count=2):
    return Block(first, dt, count, Window(float(first), float(first+dt*count)))


def _projection_seam(monkeypatch, blocks):
    # Trusted C2c adapter seam. It tests lookup/pointing composition, not physical
    # certification. No public D1a input accepts this precomputed projection.
    calls, projections = [], []
    def project(inputs, point, policy, start, end, config, origin):
        calls.append((inputs, point, policy, start, end, config, origin))
        projection = SimpleNamespace(inputs=inputs, point=point, policy=policy,
            search_start_seconds=start, search_end_seconds=end, search_config=config,
            first_step_start_seconds=origin, timestep_seconds=inputs.numerical_config.timestep_seconds,
            blocks=blocks, total_step_count=sum(b.step_count for b in blocks), all_search_cells_resolved=False)
        projections.append(projection)
        return projection
    monkeypatch.setattr(adapter, "project_ground_visibility_to_engine_grid", project)
    return calls, projections


def _stationary_snapshot_seam(monkeypatch):
    # Explicitly artificial B1 seam for integer lookup/compactness, not a claim
    # that a stationary satellite is a propagated coast or visible at all times.
    calls = []
    def state(trajectory, instant, solver):
        calls.append(instant)
        frame = trajectory.initial_state.position.frame
        return CartesianState(CartesianPosition(frame, instant, (2., 0., 0.)),
                              CartesianVelocity(frame, instant, (0., 1., 0.)))
    monkeypatch.setattr(adapter, "evaluate_two_body_state", state)
    return calls


@pytest.mark.parametrize("start,valid", [(60,True),(120,True),(61,False),(119,False),(59,False),(180,False)])
def test_hand_solved_exact_step_membership(monkeypatch, start, valid):
    calls, _ = _projection_seam(monkeypatch, (_block(),))
    snapshots = _stationary_snapshot_seam(monkeypatch)
    args = _arguments(inputs=_inputs(60), search_start_seconds=0., search_end_seconds=240., step_start_seconds=start)
    if valid:
        result = derive(**args)
        _assert_evidence(result, args)
        assert len(snapshots) == 1
    else:
        with pytest.raises(ValueError, match="engine step.*visibility support"): derive(**args)
        assert not snapshots
    assert len(calls) == 1


@pytest.mark.parametrize("start,valid", [(0,True),(2,True),(4,False),(6,False),(8,True),(10,True),(12,False),(1,False)])
def test_gap_and_exact_grid_reference(monkeypatch, start, valid):
    _projection_seam(monkeypatch, (_block(0,2,2), _block(8,2,2)))
    snapshots = _stationary_snapshot_seam(monkeypatch)
    # Fixed independent oracle: these four starts were listed by hand.
    assert valid is (start in {0,2,8,10})
    args = _arguments(inputs=_inputs(2),search_start_seconds=0.,search_end_seconds=12.,step_start_seconds=start)
    if valid:
        result = derive(**args)
        assert not result.visibility_projection.all_search_cells_resolved
        _assert_evidence(result,args)
    else:
        with pytest.raises(ValueError,match="visibility support"): derive(**args)
        assert not snapshots


def test_adjacent_blocks_do_not_support_straddling_or_non_grid_step(monkeypatch):
    _projection_seam(monkeypatch, (_block(0,3,1),_block(3,3,1)))
    snapshots = _stationary_snapshot_seam(monkeypatch)
    with pytest.raises(ValueError,match="visibility support"): _result(step_start_seconds=2)
    assert not snapshots


@pytest.mark.parametrize("blocks", [(_block(),_block()),(_block(),_block(120,60,2))])
def test_ambiguous_support_rejects_before_snapshot(monkeypatch, blocks):
    _projection_seam(monkeypatch,blocks)
    snapshots = _stationary_snapshot_seam(monkeypatch)
    with pytest.raises(ValueError,match="inconsistent visibility support"):
        _result(inputs=_inputs(60),step_start_seconds=120)
    assert not snapshots


def test_huge_block_direct_first_middle_final_lookup_and_exact_edge_errors(monkeypatch):
    count = 2**40
    source = _block(0,1,count)
    calls, _ = _projection_seam(monkeypatch,(source,))
    snapshots = _stationary_snapshot_seam(monkeypatch)
    args = _arguments(inputs=_inputs(1,horizon=count+2),search_start_seconds=0.,search_end_seconds=float(count))
    results = []
    for start in (0,count//2,count-1):
        result = derive(**dict(args,step_start_seconds=start))
        _assert_evidence(result,dict(args,step_start_seconds=start))
        assert result.supporting_visibility_block is source
        assert result.supporting_visibility_block.step_count == count
        results.append(result)
    for start in (-1,count,count+1):
        with pytest.raises(ValueError): derive(**dict(args,step_start_seconds=start))
    assert len(calls) == 6 and len(snapshots) == 3
    _projection_seam(monkeypatch,(_block(0,1,1),))
    small = _result(inputs=_inputs(1),step_start_seconds=0)
    assert all(sys.getsizeof(r)==sys.getsizeof(small) for r in results)
    assert len(fields(results[0])) == 15
    assert all(len(r.visibility_projection.blocks)==1 for r in results)
    # B1 is a labeled seam here; GeometryInstant and C1 are real and remain
    # inside |elapsed|<=2**40. Compact support does not expand that A/B1 domain.


def test_supported_step_does_not_bypass_instant_arithmetic_envelope(monkeypatch):
    start = 2**40+1
    _projection_seam(monkeypatch,(_block(start,1,1),))
    snapshots = _stationary_snapshot_seam(monkeypatch)
    with pytest.raises(ValueError,match="2\\*\\*40"):
        _result(inputs=_inputs(1,horizon=start+2),step_start_seconds=start)
    assert not snapshots


def _independent_angles(r, v, latitude, longitude):
    # Unit sphere, static Earth, phase0. No production C1/frame helpers used.
    def unit(a):
        norm = math.sqrt(sum(x*x for x in a))
        return tuple(x/norm for x in a)
    def dot(a,b): return sum(x*y for x,y in zip(a,b))
    def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    rhat = unit(r)
    z = tuple(-x for x in rhat)
    radial = dot(v,rhat)
    x = unit(tuple(vi-radial*ri for vi,ri in zip(v,rhat)))
    y = cross(z,x)
    ground = (math.cos(latitude)*math.cos(longitude),math.cos(latitude)*math.sin(longitude),math.sin(latitude))
    q = unit(tuple(g-ri for g,ri in zip(ground,r)))
    qx,qy,qz = dot(q,x),dot(q,y),dot(q,z)
    off = math.atan2(math.hypot(qx,qy),qz)
    az = math.atan2(qy,qx)
    if az < 0: az += 2*math.pi
    return off*180/math.pi, az*180/math.pi


@pytest.mark.parametrize("latitude,longitude,r,v", [
    (.1,.2,(2.,0.,0.),(0.,1.,0.)), (-.1,.2,(2.,0.,0.),(0.,1.,0.)),
    (.1,-.2,(2.,0.,0.),(0.,1.,0.)), (-.1,-.2,(2.,0.,0.),(0.,1.,0.)),
    (1e-10,.2,(2.,0.,0.),(0.,1.,0.)), (-1e-10,.2,(2.,0.,0.),(0.,1.,0.)),
    (0.,0.,(1.,1.,0.),(-1.,1.,0.)),
])
def test_independent_local_basis_and_degree_reference(monkeypatch, latitude, longitude, r, v):
    point = _target(latitude=latitude,longitude=longitude)
    state = _state(point,r=r,v=v,t=0.)
    trajectory = TwoBodyTrajectory(state,_parameter("orbit.gravity.gravitational-parameter","m^3/s^2",2.))
    inputs = _inputs(1,trajectory=trajectory)
    _projection_seam(monkeypatch,(_block(0,1,1),))
    result = _result(inputs=inputs,target=point,step_start_seconds=0)
    assert result.geometry.orbital_azimuth_status == "resolved"
    expected = _independent_angles(r,v,latitude,longitude)
    actual = (result.opportunity.pointing.view_angle_from_nadir_deg,result.opportunity.pointing.view_azimuth_deg)
    # These O(1)-scale cases have LOS>=1m and transverse projection>=~0.17.
    # Budget 128*u*(1+1/0.17) rad covers the short normalization/dot/atan2
    # chains, then 2 ulps at360deg for conversion. Absolute only, not a claim
    # of operational pointing accuracy or a universal C1 error certificate.
    bound_deg = 128*2.**-53*(1+1/.17)*180/math.pi + 2*math.ulp(360.)
    assert actual == pytest.approx(expected,rel=0,abs=bound_deg)
    if r == (1.,1.,0.):
        assert actual == pytest.approx((45.,180.),rel=0,abs=bound_deg)
        assert result.geometry.incidence_rad == pytest.approx(math.pi/2,rel=0,abs=2*math.ulp(math.pi/2))
        assert result.geometry.ground_azimuth_rad == pytest.approx(math.pi/2,rel=0,abs=2*math.ulp(math.pi/2))


@pytest.mark.parametrize("r,status", [((2.,0.,0.),"zero_projection"),((2.,1e-16,0.),"unresolved_projection")])
def test_real_c1_exact_nadir_and_unresolved_nonzero_projection(monkeypatch, r, status):
    point = _target()
    state = _state(point,r=r,v=(0.,1.,0.),t=0.)
    inputs = _inputs(1,trajectory=TwoBodyTrajectory(state,_parameter("orbit.gravity.gravitational-parameter","m^3/s^2",2.)))
    _projection_seam(monkeypatch,(_block(0,1,1),))
    owner, observed = adapter.evaluate_ground_point_geometry, []
    def snapshot(*args):
        geometry = owner(*args)
        observed.append(geometry)
        return geometry
    monkeypatch.setattr(adapter,"evaluate_ground_point_geometry",snapshot)
    if status == "zero_projection":
        result = _result(inputs=inputs,target=point,step_start_seconds=0)
        assert result.geometry.off_nadir_rad == 0.
        assert result.geometry.orbital_azimuth_rad is None
        assert result.opportunity.pointing.view_azimuth_deg == 0.
    else:
        with pytest.raises(ValueError,match="orbital azimuth is unresolved"):
            _result(inputs=inputs,target=point,step_start_seconds=0)
        assert observed[0].off_nadir_rad > 0 and observed[0].orbital_azimuth_rad is None
    assert observed[0].orbital_azimuth_status == status


def _geometry_seam(monkeypatch, off=.1, az=.2, status="resolved"):
    _projection_seam(monkeypatch,(_block(9,3,1),))
    def geometry(point,state):
        return SimpleNamespace(point=point,spacecraft_state=state,off_nadir_rad=off,
                               orbital_azimuth_rad=az,orbital_azimuth_status=status)
    monkeypatch.setattr(adapter,"evaluate_ground_point_geometry",geometry)


@pytest.mark.parametrize("off,az,status", [
    (.1,None,"resolved"), (.1,None,"unresolved_projection"), (0.,None,"unresolved_projection"),
    (1e-20,None,"zero_projection"), (math.pi,None,"zero_projection"), (.1,None,"unknown"),
])
def test_missing_or_unresolved_azimuth_never_invents_direction(monkeypatch,off,az,status):
    _geometry_seam(monkeypatch,off,az,status)
    with pytest.raises(ValueError): _result()


@pytest.mark.parametrize("field,upper_rad,upper_deg", [("off",math.pi/2,90.),("az",math.tau,360.)])
def test_exact_adjacent_angular_domain_boundaries(monkeypatch,field,upper_rad,upper_deg):
    for angle in (0.,math.nextafter(0.,1.),math.nextafter(upper_rad,0.)):
        _geometry_seam(monkeypatch,**{field:angle})
        pointing = _result().opportunity.pointing
        actual = pointing.view_angle_from_nadir_deg if field=="off" else pointing.view_azimuth_deg
        expected = math.degrees(angle)
        if expected == upper_deg: expected = math.nextafter(upper_deg,0.)
        assert actual == expected and 0 <= actual < upper_deg
    for angle in (math.nextafter(0.,-1.),upper_rad,math.nextafter(upper_rad,math.inf)):
        _geometry_seam(monkeypatch,**{field:angle})
        with pytest.raises(ValueError,match="pointing domain"): _result()


@pytest.mark.parametrize("field,upper_rad,upper_deg", [("off",math.pi/2,90.),("az",math.tau,360.)])
def test_one_ulp_rounding_guard_requires_strictly_interior_source(monkeypatch,field,upper_rad,upper_deg):
    # Exercise the defensive conversion-rounding branch independently of the
    # host libm's current last-bit outcome. This is a conversion seam only.
    inside = math.nextafter(upper_rad,0.)
    owner = adapter.degrees
    monkeypatch.setattr(adapter,"degrees",lambda value: upper_deg if value==inside else owner(value))
    _geometry_seam(monkeypatch,**{field:inside})
    p = _result().opportunity.pointing
    actual = p.view_angle_from_nadir_deg if field=="off" else p.view_azimuth_deg
    assert actual == math.nextafter(upper_deg,0.)
    assert Fraction(upper_deg)-Fraction(actual) == Fraction(math.ulp(upper_deg))
    _geometry_seam(monkeypatch,**{field:upper_rad})
    with pytest.raises(ValueError,match="pointing domain"): _result()


def _changed_target(point,field):
    if field=="identity": return replace(point,point_id=GroundTargetId("another-target"))
    if field=="provenance":
        p=point.longitude_rad
        return replace(point,longitude_rad=replace(p,provenance=replace(p.provenance,rationale="Different external coordinate evidence.")))
    p=getattr(point,field)
    return replace(point,**{field:replace(p,value=p.value+.01)})


def test_schema5_restart_independent_b2_decode_and_one_at_a_time_external_evidence(monkeypatch):
    inputs = _inputs(1)
    context = replace(generic_context(),inputs=inputs)
    before = deepcopy(context)
    coast_payload = inputs.coast_orbit.to_dict()
    payload = CheckpointState.from_context(context).to_dict()
    recovered = CheckpointState.from_dict(json.loads(json.dumps(payload,allow_nan=False)))
    coast = CoastOrbitInputs.from_dict(json.loads(json.dumps(coast_payload,allow_nan=False)))
    restored = recovered.restore(with_coast_orbit(inputs,coast))
    assert restored == context and coast == inputs.coast_orbit and coast is not inputs.coast_orbit
    assert payload["schema_version"] == CURRENT_CHECKPOINT_SCHEMA_VERSION == 5 and COAST_BINDING_VERSION == 1
    assert tuple(payload)==("schema_version","simulation_time_seconds","input_ids","spacecraft",
        "ground_knowledge","ground_data_delivery","mission","controller","diagnostics")
    args = _arguments(inputs=inputs)
    original = derive(**args)
    assert derive(**dict(args,inputs=restored.inputs)) == original
    changes = [{"target":_changed_target(args["target"],f)} for f in (
        "longitude_rad","latitude_rad","provenance")]
    changes += [{"policy":_policy(.2)},{"search_config":Config(.03125,10000)},
        {"search_start_seconds":3.},{"search_end_seconds":17.},{"first_step_start_seconds":1},
        {"step_start_seconds":10},{"request":_request(name="another-request")},
        {"request":_request(priority=2.)},{"opportunity_id":ObservationOpportunityId("another-opportunity")}]
    for change in changes:
        result = derive(**dict(args,**change))
        assert result != original and result.inputs.model_manifest == original.inputs.model_manifest
        assert derive(**dict(args,inputs=restored.inputs,**change)) == result
    # This 0.01m height change removes selected-step certification in the real
    # bounded search. External changes need not stay supported; repeat the
    # rejection and inspect the actual C2c evidence on both restart paths.
    raised_target = _changed_target(args["target"],"ellipsoidal_height_m")
    projections = []
    with monkeypatch.context() as patch:
        owner = adapter.project_ground_visibility_to_engine_grid
        def project(*values):
            projection = owner(*values)
            projections.append(projection)
            return projection
        def forbidden(*values): pytest.fail("unsupported restart variant reached pointing")
        patch.setattr(adapter,"project_ground_visibility_to_engine_grid",project)
        patch.setattr(adapter,"evaluate_two_body_state",forbidden)
        patch.setattr(adapter,"evaluate_ground_point_geometry",forbidden)
        for active in (inputs,restored.inputs):
            with pytest.raises(ValueError,match="engine step.*visibility support"):
                derive(**dict(args,inputs=active,target=raised_target))
    assert len(projections)==2 and projections[0]==projections[1]
    assert projections[0].point==raised_target and projections[0].point!=original.target
    assert projections[0].inputs.model_manifest==original.inputs.model_manifest
    assert not any(b.first_start_time_seconds<=9 and 10<=b.last_end_time_seconds
                   and (9-b.first_start_time_seconds)%b.timestep_seconds==0 for b in projections[0].blocks)
    target = _changed_target(args["target"],"identity")
    for active in (inputs,restored.inputs):
        with pytest.raises(ValueError,match="request target does not match"):
            derive(**dict(args,inputs=active,target=target))
        with pytest.raises(ValueError,match="request target does not match"):
            derive(**dict(args,inputs=active,request=_request(target=target.point_id)))
    matching = dict(args,target=target,request=_request(target=target.point_id))
    changed = derive(**matching)
    assert changed != original and changed.inputs.model_manifest == original.inputs.model_manifest
    assert derive(**dict(matching,inputs=restored.inputs)) == changed
    assert context == before and inputs.coast_orbit.to_dict() == coast_payload
    assert CheckpointState.from_context(context).to_dict() == payload
    assert CheckpointState.from_context(restored).to_dict() == payload
