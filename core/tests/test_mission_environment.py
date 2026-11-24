from dataclasses import replace
from fractions import Fraction as Q
from math import pi
import pytest
from examples.m3_constructor_mission_demo import make_inputs, scalar
from ops_sim.v5.mission_environment import query_point_state,sample_catalog,SamplingPolicy
from ops_sim.v5.orbit_config import GeometryInstant
from ops_sim.v5.orbit_visibility import GroundVisibilityStatus


def test_hand_solvable_overhead_and_opposite_ground_points():
    d=make_inputs();q=d.environment.source_request;s=q.segment.trajectory.initial_state
    target,blocked,station=d.catalog
    for p in (target,station):
        o=query_point_state(q,p,s)
        assert o.range_m==600000.;assert o.off_nadir_rad==0.
        assert o.elevation_rad==pi/2;assert o.direction.components==(-1.,0.,0.)
        assert o.visible
    assert not query_point_state(q,target,s).serviceable_nominal
    assert query_point_state(q,station,s).serviceable_nominal
    assert not query_point_state(q,blocked,s).visible
    assert query_point_state(q,blocked,s).visibility.status is GroundVisibilityStatus.NOT_VISIBLE


def test_boundary_is_not_silently_serviceable():
    d=make_inputs();q=d.environment.source_request;s=q.segment.trajectory.initial_state
    p=replace(d.catalog[-1],visibility_policy=replace(d.catalog[-1].visibility_policy,
        minimum_elevation_rad=scalar('orbit.visibility.minimum-elevation','rad',pi/2)))
    o=query_point_state(q,p,s)
    assert not o.serviceable_nominal
    assert o.visibility.status is not GroundVisibilityStatus.VISIBLE


def test_declared_serviceability_is_separate_from_visibility():
    d=make_inputs();q=d.environment.source_request;s=q.segment.trajectory.initial_state
    for field in ('station_available','rf_admitted'):
        o=query_point_state(q,replace(d.catalog[-1],**{field:False}),s)
        assert o.visible and not o.serviceable_nominal


def test_deterministic_sorted_samples_and_explicit_time_rounding():
    d=make_inputs();q=d.environment.source_request;t=(Q(128),Q(128)+Q(1,3))
    a=sample_catalog(q,d.catalog,t,d.sampling)
    b=sample_catalog(q,tuple(reversed(d.catalog)),t,d.sampling)
    assert a==b and len(a)==6
    assert a[0].requested_seconds==Q(128) and a[-1].requested_seconds==t[-1]
    assert a[-1].rounding_seconds!=0
    assert all(o.mode=='NOMINAL_SAMPLED_J2_POINT_GRID_V1' for o in a)


@pytest.mark.parametrize('times',[(Q(127),),(Q(193),),(Q(128),Q(128)),(Q(130),Q(128)),(128,)])
def test_invalid_sample_authority(times):
    d=make_inputs()
    with pytest.raises((ValueError,TypeError)):sample_catalog(d.environment.source_request,d.catalog,times,d.sampling)


def test_foreign_frame_and_requested_time_refused():
    d=make_inputs();q=d.environment.source_request;s=q.segment.trajectory.initial_state
    with pytest.raises(ValueError,match='rounding'):query_point_state(q,d.catalog[0],s,requested_seconds=Q(129))
    f=replace(s.position.frame,rotation=replace(s.position.frame.rotation,
        initial_phase_rad=scalar('orbit.rotation.initial-phase','rad',.1)))
    other=replace(s,position=replace(s.position,frame=f),velocity=replace(s.velocity,frame=f))
    with pytest.raises(ValueError,match='foreign frame'):query_point_state(q,d.catalog[0],other)
