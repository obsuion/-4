"""Independent short interpolation and point-integration checks."""
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import copy
import math
import pytest

from examples.m2_sun_table_demo import synthetic_table, example_query
from examples.v5_experiment_bundle_demo import build_demo_state
from examples.v5_j2_enclosure_pilot import inputs as pilot_trajectory
from ops_sim.v5.context import with_coast_orbit, with_j2_coast_orbit
from ops_sim.v5.orbit_config import GeometryInstant, FrameKind, TTEpoch
from ops_sim.v5.sun_table import (
    SunPositionSample, SunPositionTable, TableOrbitSunQuery,
    evaluate_sun_position, evaluate_table_orbit_sun, evaluate_context_table_sun,
)
import ops_sim.v5.sun_table as module


def affine():
    table=example_query("two-body").table
    return replace(table,domain_seconds=(0.,10.),samples=(
        SunPositionSample(0.,(10.,20.,30.)),SunPositionSample(4.,(18.,8.,34.)),
        SunPositionSample(10.,(30.,-10.,40.))))


@pytest.mark.parametrize("t,expected",[
    (0.,(10.,20.,30.)),(1.,(12.,17.,31.)),(4.,(18.,8.,34.)),
    (7.,(24.,-1.,37.)),(10.,(30.,-10.,40.)),
])
def test_hand_solved_nodes_segments_closed_end(t,expected):
    table=affine()
    assert evaluate_sun_position(table,GeometryInstant(table.epoch,t)).components_m==expected


@pytest.mark.parametrize("t",[-1.,math.nextafter(0.,-math.inf),math.nextafter(10.,math.inf),11.])
def test_no_extrapolation(t):
    table=affine()
    with pytest.raises(ValueError,match="domain"):evaluate_sun_position(table,GeometryInstant(table.epoch,t))


@pytest.mark.parametrize("t",[.1,.3,1.234567,3.99,4.001,7.125,9.999])
def test_independent_decimal_affine(t):
    table=affine();actual=evaluate_sun_position(table,GeometryInstant(table.epoch,t)).components_m
    i=0 if t<4 else 1;a,b=table.samples[i:i+2]
    with localcontext() as c:
        c.prec=90
        w=(Decimal.from_float(t)-Decimal.from_float(a.elapsed_seconds))/(Decimal.from_float(b.elapsed_seconds)-Decimal.from_float(a.elapsed_seconds))
        expected=[(1-w)*Decimal.from_float(x)+w*Decimal.from_float(y) for x,y in zip(a.position_m,b.position_m)]
    for x,y in zip(actual,expected):assert abs(x-float(y))<=math.ulp(x)


def test_large_time_origin_preserves_small_offsets():
    table=affine();origin=2.**39
    table=replace(table,domain_seconds=(origin,origin+10),samples=tuple(
        replace(s,elapsed_seconds=origin+s.elapsed_seconds) for s in table.samples))
    assert evaluate_sun_position(table,GeometryInstant(table.epoch,origin+.125)).components_m==(10.25,19.625,30.125)


@pytest.mark.parametrize("value",[True,float("nan"),float("inf"),"1",2**60+1])
def test_bad_numbers(value):
    with pytest.raises((TypeError,ValueError)):SunPositionSample(value,(1.,2.,3.))
    with pytest.raises((TypeError,ValueError)):SunPositionSample(0.,(value,2.,3.))


def test_numeric_subclasses_reject():
    class F(float):pass
    with pytest.raises(TypeError):SunPositionSample(F(1),(1.,2.,3.))


@pytest.mark.parametrize("which",["duplicate","reverse","one","list","domain","frame","epoch","policy","too-many"])
def test_malformed_table(which):
    t=affine()
    bad={
        "duplicate":{"samples":(t.samples[0],t.samples[0],t.samples[-1])},
        "reverse":{"samples":tuple(reversed(t.samples))},
        "one":{"samples":t.samples[:1]},
        "list":{"samples":list(t.samples)},
        "domain":{"domain_seconds":(0.,11.)},
        "frame":{"frame":replace(t.frame,kind=FrameKind.EARTH_FIXED)},
        "epoch":{"epoch":replace(t.epoch,julian_day=t.epoch.julian_day+1)},
        "policy":{"interpolation":"cubic"},
        "too-many":{"samples":t.samples*342},
    }[which]
    with pytest.raises((TypeError,ValueError)):replace(t,**bad)


@pytest.mark.parametrize("name,value",[
    ("target","399"),("center","500@10"),("axes","ICRF"),("reference_plane","ECLIPTIC"),
    ("correction","LT"),("source_timescale","TDB"),("source_timescale","UTC"),
    ("source_units","AU"),("conversion","guess"),("alignment","automatic"),
    ("accuracy_policy","ZERO_ERROR"),("accuracy_statement",""),
    ("request_sha256","a"*64),("ephemeris_id","DE441"),("source_ids",[]),
])
def test_metadata_rejection(name,value):
    with pytest.raises((TypeError,ValueError)):replace(affine().provenance,**{name:value})


def test_zero_positions_and_zero_interpolated_point():
    with pytest.raises(ValueError):SunPositionSample(0.,(0.,0.,0.))
    t=affine()
    t=replace(t,domain_seconds=(0.,2.),samples=(SunPositionSample(0.,(1.,0.,0.)),SunPositionSample(2.,(-1.,0.,0.))))
    with pytest.raises(ValueError):evaluate_sun_position(t,GeometryInstant(t.epoch,1.))


@pytest.mark.parametrize("direction,expected",[((100.,0.,0.),"ILLUMINATED"),((-100.,0.,0.),"OCCULTED")])
def test_nominal_sides_fixed_ray_vs_combined(direction,expected):
    q=example_query("j2");at=q.coast.trajectory.initial_state.position.instant
    table=replace(q.table,samples=tuple(replace(s,position_m=direction) for s in q.table.samples))
    q=replace(q,table=table,instant=at)
    r=evaluate_table_orbit_sun(q)
    assert r.fixed_ray_assessment.shadow.nominal==expected
    assert r.fixed_ray_assessment.shadow.qualified==expected
    assert r.combined_qualification=="UNRESOLVED"
    assert "SPACECRAFT_DEPENDENT_RAY_NOT_JOINTLY_ENCLOSED" in r.combined_reasons


def test_finite_distance_direction_and_undefined_difference():
    q=example_query("two-body");at=q.coast.trajectory.initial_state.position.instant
    table=replace(q.table,samples=tuple(replace(s,position_m=(2.,10.,0.)) for s in q.table.samples))
    r=evaluate_table_orbit_sun(replace(q,table=table,instant=at))
    assert r.orbit_state.position.components_m==(2.,0.,0.)
    assert r.spacecraft_to_sun_m==(0.,10.,0.)
    assert r.fixed_ray_assessment.unit_sun_direction.components==(0.,1.,0.)
    table=replace(table,samples=tuple(replace(s,position_m=(2.,0.,0.)) for s in table.samples))
    with pytest.raises(ValueError):evaluate_table_orbit_sun(replace(q,table=table,instant=at))


@pytest.mark.parametrize("kind",["two-body","j2","unresolved"])
def test_single_orbit_call_preserved_evidence_nonmutation(kind,monkeypatch):
    q=example_query(kind);before=copy.deepcopy(q)
    owner=module._evaluate_coast_at;calls=[]
    def spy(coast,instant):
        calls.append((coast,instant))
        return owner(coast,instant)
    monkeypatch.setattr(module,"_evaluate_coast_at",spy)
    r=evaluate_table_orbit_sun(q)
    assert q==before and calls==[(q.coast,q.instant)]
    expected_state,expected_evidence=owner(q.coast,q.instant)
    assert r.orbit_state==expected_state and r.j2_evidence==expected_evidence
    if kind=="unresolved":
        assert r.orbit_state is None and r.fixed_ray_assessment is None and r.spacecraft_to_sun_m is None
        assert r.j2_evidence.position_error_bound_m is None
        assert r.j2_evidence.reason in r.combined_reasons[0]
    assert r.combined_qualification=="UNRESOLVED"


@pytest.mark.parametrize("kind",["two-body","j2"])
def test_actual_context_clock_127_not_anchor_plus_clock(kind):
    q=example_query(kind)
    if kind=="j2":
        coast=replace(q.coast,trajectory=pilot_trajectory(False),
                      solver_config=replace(q.coast.solver_config,step_seconds=.25),
                      enclosure_policy=replace(q.coast.enclosure_policy,step_seconds=.25))
        q=replace(q,coast=coast)
    c=build_demo_state().context
    binder=with_coast_orbit if kind=="two-body" else with_j2_coast_orbit
    c=replace(c,inputs=binder(c.inputs,q.coast),simulation_time_seconds=127)
    before=copy.deepcopy(c)
    result=evaluate_context_table_sun(c,q.table)
    assert c==before
    assert result.query.instant.elapsed_seconds==127.
    assert result.query.coast.trajectory.initial_state.position.instant.elapsed_seconds==128.
    assert result==evaluate_table_orbit_sun(replace(q,instant=GeometryInstant(q.table.epoch,127.)))


def test_mismatches_reject_before_orbit_work(monkeypatch):
    q=example_query("two-body")
    def forbidden(*args):raise AssertionError("orbit evaluated on rejected inputs")
    monkeypatch.setattr(module,"_evaluate_coast_at",forbidden)
    with pytest.raises(ValueError):replace(q,instant=replace(q.instant,elapsed_seconds=1000.))
    with pytest.raises(ValueError):replace(q,instant=replace(q.instant,epoch=TTEpoch(2451546,.125)))
    shape=replace(q.table.frame.ellipsoid,name="different-declaration")
    table=replace(q.table,frame=replace(q.table.frame,ellipsoid=shape))
    with pytest.raises(ValueError):replace(q,table=table)
