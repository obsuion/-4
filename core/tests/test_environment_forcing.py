"""Trusted synthetic partitions exercise adapters; zero fresh B38 evaluations."""
from copy import copy
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction as Q
import pytest

from test_orbit_sun_zonotope_local_v2 import request as upstream_request
from examples.m2_environment_forcing_demo import (trusted_synthetic_result,
    forcing_request, profile_entry)
from ops_sim.v5 import environment_forcing as m
from ops_sim.v5 import orbit_sun_zonotope_local_v2 as light
from ops_sim.v5.ids import ThermalNodeId


def T(offset):
    return Q(128)+Q(offset)


def fixture(assessments=("ILLUMINATED",), *, duration=6.0):
    q = upstream_request("illuminated", passes=0, span=duration)
    return trusted_synthetic_result(q, assessments), forcing_request(q)


def alter(value, **changes):
    out = copy(value)
    for n, v in changes.items():
        object.__setattr__(out, n, v)
    return out


def test_union_breakpoint_inside_whole_support_and_original_ancestry():
    r, q = fixture(("ILLUMINATED", "OCCULTED"))
    q = replace(q, profile=(profile_entry(T(0), T(2)), profile_entry(T(2), T(6), load=30.)))
    s = m.adapt_environment_forcing(r, q)
    assert [(c.start_seconds, c.end_seconds) for c in s.cells] == [(T(0), T(2)), (T(2), T(3)), (T(3), T(6))]
    assert [c.support_index for c in s.cells] == [0, 0, 1]
    assert s.supports[0].geometry.cell.start_seconds == T(0) and s.supports[0].geometry.cell.end_seconds == T(3)
    assert s.ancestry[0].parent_boundary_id == 0
    assert s.original_anchor_seconds == T(0) and s.source_end_seconds == T(6)
    assert s.supports[0].geometry_support_convention == "CLOSED"
    assert s.request is not q and s.request.source_request == q.source_request
    with pytest.raises(FrozenInstanceError):
        s.coverage_id = "bad"
    assert s == m.adapt_environment_forcing(r, q)


def test_eclipse_removes_direct_solar_only_and_records_supplied_assumption():
    r, q = fixture(("OCCULTED",))
    s = m.adapt_environment_forcing(r, q)
    case = s.cells[0].alternatives[0]
    assert case.sunlit is False
    for n in case.heat_source_inputs.node_sources:
        assert (n.internal_dissipation_w, n.absorbed_solar_w, n.absorbed_albedo_w,
                n.absorbed_earth_ir_w) == (2., 0, 1., 3.)
    assert s.request.profile[0].non_overlap_assumption


def test_unresolved_exposes_input_alternatives_without_trajectory_bounds():
    r, q = fixture(("UNRESOLVED",))
    c = m.adapt_environment_forcing(r, q).cells[0]
    assert c.assessment == "UNRESOLVED" and tuple(x.sunlit for x in c.alternatives) == (True, False)
    assert c.alternatives[0].heat_source_inputs.node_sources[0].absorbed_solar_w == 10.


@pytest.mark.parametrize("t,index", [(Q(0),0), (Q(3),1), (Q(6),1)])
def test_zero_duration_uses_right_hand_partition_and_included_final_end(t, index):
    r, q = fixture(("ILLUMINATED", "OCCULTED"))
    s = m.adapt_environment_forcing(r, replace(q, start_seconds=T(t), end_seconds=T(t)))
    assert len(s.cells) == 1 and s.cells[0].support_index == index
    assert s.cells[0].start_seconds == s.cells[0].end_seconds == T(t)


@pytest.mark.parametrize("changes", [dict(coverage_complete=False), dict(coverage_complete=1),
    dict(status="computational_failure"), dict(authority_digest="0"*64), dict(api_version=True),
    dict(local_control_ledger_failed=True), dict(geometry_leaf_budget_rejected=True), dict(pieces=()),
    dict(windows=()), dict(boundaries=()), dict(steps=[])])
def test_failed_or_foreign_or_empty_source_rejected_before_schedule(changes):
    r, q = fixture()
    with pytest.raises((TypeError,ValueError)):
        m.adapt_environment_forcing(alter(r, **changes), q)


@pytest.mark.parametrize("bad", ["gap", "overlap", "reverse", "missing_geometry", "foreign_classification", "bad_convention"])
def test_partition_corruption_rejected(bad):
    r, q = fixture(("ILLUMINATED", "OCCULTED"))
    pieces = list(r.pieces)
    if bad == "gap": pieces[1] = replace(pieces[1], start_seconds=T(4))
    if bad == "overlap": pieces[1] = replace(pieces[1], start_seconds=T(2))
    if bad == "reverse": pieces.reverse()
    if bad == "missing_geometry": pieces[0] = replace(pieces[0], geometry_record_id=100)
    if bad == "foreign_classification": pieces[0] = replace(pieces[0], assessment="OCCULTED")
    if bad == "bad_convention": pieces[0] = alter(pieces[0], endpoint_convention="OPEN")
    with pytest.raises((TypeError,ValueError)):
        m.adapt_environment_forcing(alter(r, pieces=tuple(pieces)), q)


@pytest.mark.parametrize("kind", ["root_time", "boundary_authority", "missing_parent", "duplicate_geometry", "geometry_trial"])
def test_ancestry_and_support_binding_reject_corruption(kind):
    r, q = fixture()
    if kind == "root_time": r = alter(r, boundaries=(replace(r.boundaries[0], set=replace(r.boundaries[0].set,time=Q(1))),)+r.boundaries[1:])
    if kind == "boundary_authority": r = alter(r, boundaries=(replace(r.boundaries[0],authority_digest="0"*64),)+r.boundaries[1:])
    if kind == "missing_parent": r = alter(r, steps=(replace(r.steps[0],parent_boundary_id=100),))
    if kind == "duplicate_geometry": r = alter(r, geometry_records=r.geometry_records*2)
    if kind == "geometry_trial": r = alter(r, geometry_records=(replace(r.geometry_records[0],trial_index=True),))
    with pytest.raises((TypeError,ValueError)):
        m.adapt_environment_forcing(r, q)


@pytest.mark.parametrize("value", [True, -1., float("inf"), float("nan"), "1"])
def test_supplied_heat_and_power_are_finite_builtin_nonnegative(value):
    with pytest.raises((TypeError,ValueError)):
        m.NodeForcing(ThermalNodeId("bus"), 300., value, 0., 0., 0.)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "foreign", "gap", "overlap", "eps_loss", "radiative_double_count"])
def test_profile_and_conventions_reject_bad_input(kind):
    r, q = fixture()
    e = q.profile[0]
    with pytest.raises((TypeError,ValueError)):
        if kind == "missing": replace(q,profile=(replace(e,nodes=e.nodes[:-1]),))
        elif kind == "duplicate": replace(e,nodes=e.nodes+(e.nodes[0],))
        elif kind == "foreign": replace(q,profile=(replace(e,nodes=(replace(e.nodes[0],node_id=ThermalNodeId("other")),)+e.nodes[1:]),))
        elif kind == "gap": replace(q,profile=(profile_entry(T(0),T(2)),profile_entry(T(3),T(6))))
        elif kind == "overlap": replace(q,profile=(profile_entry(T(0),T(4)),profile_entry(T(3),T(6))))
        elif kind == "eps_loss": replace(e,internal_includes_eps_losses=True)
        else: replace(e.nodes[0],sink_includes=("solar",))


def test_own_admission_and_foreign_request_without_numerical_calls(monkeypatch):
    r, q = fixture(("ILLUMINATED", "OCCULTED"))
    def forbidden(*a, **k): raise AssertionError("no numerical owner calls")
    monkeypatch.setattr(light,"evaluate_zonotope_local_illumination_v2",forbidden)
    m.adapt_environment_forcing(r, q)
    with pytest.raises(ValueError):
        m.adapt_environment_forcing(r,replace(q,policy=m.ForcingPolicy(max_cells=1)))
    with pytest.raises(ValueError):
        m.adapt_environment_forcing(r,replace(q,policy=m.ForcingPolicy(max_source_records=1)))
    other = upstream_request("occulted",passes=0,span=6.0)
    with pytest.raises(ValueError):
        m.adapt_environment_forcing(r,replace(q,source_request=replace(other,requested_resolution_seconds=.5)))
