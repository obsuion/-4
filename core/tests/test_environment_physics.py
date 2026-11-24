"""Independent constant-rate references and exact primitive compatibility."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
from math import ulp
import pytest

from test_environment_forcing import fixture, T
from examples.m2_environment_forcing_demo import physical_case, profile_entry
from ops_sim.v5 import environment_physics as p
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.eps_system import compute_eps_interval_transition, compute_eps_substep_transition
from ops_sim.v5.thermal_coupling import (compute_eps_thermal_interval_transition,
                                       compute_eps_thermal_substep_transition)
from ops_sim.v5.state import BatteryState, ThermalState, ThermalNodeState
from ops_sim.v5.eps_capability import compute_eps_capability


@pytest.mark.parametrize("assessment", ["ILLUMINATED", "OCCULTED"])
@pytest.mark.parametrize("duration", [Q(1,3), Q(7,3), Q(6)])
def test_constant_rate_energy_and_isolated_node_heat_reference(assessment, duration):
    r, q = fixture((assessment,))
    q = replace(q,end_seconds=T(duration))
    states = physical_case()
    before = deepcopy(states)
    result = p.compute_environment_transition(r, q, *states)
    assert result.status == "complete" and states == before
    # Supplied100 W array at incidence0,20 W load; unit battery efficiency.
    rate = 80 if assessment == "ILLUMINATED" else -20
    seconds = duration.numerator if duration.denominator == 1 else float(duration)
    exact_energy = Q(100)+Q(rate)*Q(seconds)/3600
    expected = float(exact_energy)
    # Existing binary64 duration/energy composition: <=2 final-state ULPs.
    assert abs(result.final_proposal.battery_energy_wh-expected) <= 2*ulp(expected)
    heat = 16 if assessment == "ILLUMINATED" else 6
    target = float(Q(300)+Q(heat)*Q(seconds)/1000)
    assert all(abs(t-target) <= 2*ulp(target) for _, t in result.final_proposal.temperatures_k)
    assert result.trajectory[0].eps_result.solar.generation_w == (100. if rate > 0 else 0.)


def test_conversion_heat_is_added_once_and_existing_capability_is_forwarded():
    r, q = fixture()
    states = physical_case(efficiency=.8)
    out = p.compute_environment_transition(r,q,*states)
    step = out.trajectory[0]
    loss = step.eps_result.battery.conversion_loss_wh*3600/6
    assert loss == pytest.approx(16., rel=0, abs=2*ulp(16.))
    heat = {n.node_id.value:n for n in step.thermal_coupling_result.node_heat_ledgers}
    assert heat["battery"].battery_conversion_heat_w == loss
    assert heat["battery"].total_applied_heat_w == 16.+loss
    assert heat["bus"].battery_conversion_heat_w == heat["payload"].battery_conversion_heat_w == 0
    # Forward a separately derived existing nominal capability, no new ageing.
    from ops_sim.v5.state import DegradationState, BatteryDegradationState, SolarDegradationState
    capability = compute_eps_capability(states[1],DegradationState(
        BatteryDegradationState(1.,0.),SolarDegradationState(1.)))
    with_cap = p.compute_environment_transition(r,q,*states,capability=capability)
    assert with_cap.final_proposal == out.final_proposal


def test_exact_wrapper_primitive_equality_on_identical_rational_segments():
    r,q=fixture(("ILLUMINATED","OCCULTED"))
    q=replace(q,profile=(profile_entry(T(0),T(Q(4,3))),profile_entry(T(Q(4,3)),T(6),incidence=60.)))
    states=physical_case(efficiency=.8)
    out=p.compute_environment_transition(r,q,*states)
    b, ec, t, tc=states
    b=BatteryState(b.energy_wh)
    t=deepcopy(t)
    for step in out.trajectory:
        c=step.forcing;case=c.alternatives[0];dt=c.end_seconds-c.start_seconds
        if dt.denominator == 1:
            e=compute_eps_interval_transition(b,ec,case.eps_inputs,dt_seconds=dt.numerator)
            h=compute_eps_thermal_interval_transition(t,tc,case.thermal_inputs,case.heat_source_inputs,e,dt_seconds=dt.numerator)
        else:
            duration=RationalSeconds.from_fraction(dt)
            e=compute_eps_substep_transition(b,ec,case.eps_inputs,duration=duration)
            h=compute_eps_thermal_substep_transition(t,tc,case.thermal_inputs,case.heat_source_inputs,e,duration=duration)
        assert e==step.eps_result and h==step.thermal_coupling_result
        b=BatteryState(e.battery.end_energy_wh)
        t=ThermalState(tuple(ThermalNodeState(n.node_id,n.end_temperature_k) for n in h.thermal_result.node_transitions))
    assert out.final_proposal.to_states()==(b,t)
    b.energy_wh=0.
    assert out.final_proposal.battery_energy_wh > 0


def test_unresolved_preflight_refuses_every_physical_call_but_certified_subinterval_works(monkeypatch):
    r,q=fixture(("ILLUMINATED","UNRESOLVED"))
    states=physical_case()
    def forbidden(*a,**k):raise AssertionError("no physical execution on uncertain schedule")
    with monkeypatch.context() as patch:
        patch.setattr(p,"compute_eps_interval_transition",forbidden)
        patch.setattr(p,"compute_eps_substep_transition",forbidden)
        out=p.compute_environment_transition(r,q,*states)
    assert out.status=="unresolved" and out.final_proposal is out.trajectory is None
    assert not out.diagnostic_prefix and len(out.unresolved_regions)==1
    assert len(out.unresolved_regions[0].alternatives)==2
    ok=p.compute_environment_transition(r,replace(q,end_seconds=T(3)),*states)
    assert ok.status=="complete"


@pytest.mark.parametrize("assessment", ["ILLUMINATED","UNRESOLVED"])
def test_zero_duration_calls_no_physical_kernel_and_preserves_state(assessment,monkeypatch):
    r,q=fixture((assessment,));q=replace(q,start_seconds=T(6),end_seconds=T(6))
    states=physical_case();before=deepcopy(states)
    def forbidden(*a,**k):raise AssertionError("zero energy has no invented duration")
    monkeypatch.setattr(p,"compute_eps_interval_transition",forbidden)
    monkeypatch.setattr(p,"compute_eps_substep_transition",forbidden)
    out=p.compute_environment_transition(r,q,*states)
    assert out.status=="zero_duration" and out.trajectory==() and not out.unresolved_regions
    assert out.final_proposal.to_states()==(states[0],states[2]) and states==before


def test_real_late_primitive_overflow_publishes_diagnostic_prefix_only():
    r,q=fixture();states=physical_case();before=deepcopy(states)
    q=replace(q,profile=(profile_entry(T(0),T(2)),profile_entry(T(2),T(6),heat=1.7e308,solar=1.7e308)))
    out=p.compute_environment_transition(r,q,*states)
    assert out.status=="physical_failure" and out.failed_cell_index==1
    assert len(out.diagnostic_prefix)==1 and out.final_proposal is out.trajectory is None
    assert states==before and "finite" in out.reason


def test_wrong_physical_node_set_rejected_before_execution():
    r,q=fixture();b,e,t,c=physical_case()
    t=ThermalState(t.node_states[:-1])
    with pytest.raises(ValueError,match="node sets"):
        p.compute_environment_transition(r,q,b,e,t,c)
