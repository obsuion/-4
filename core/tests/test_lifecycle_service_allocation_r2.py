"""Cheap real seven-positive-branch wire/EPS checks, not campaign evidence."""
from dataclasses import replace,fields
from fractions import Fraction
from math import fsum,isclose
import pytest
from examples.m4_construction_mission_demo import make_inputs
from ops_sim.v5.construction_mission import start_construction_mission
from ops_sim.v5.assembly_attitude_3d import compile_assembly_hardware_3d
from ops_sim.v5.long_mission import _forcing
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.power_loads import PowerLoadBreakdown
from ops_sim.v5.construction_service import ConstructionServicePolicy,ConstructionServiceWork,service_physical_substep

@pytest.mark.parametrize('limited',[False,True])
def test_all_seven_positive_receiving_demands_and_independent_wire_balances(limited):
    state=start_construction_mission(make_inputs())
    hw=compile_assembly_hardware_3d(state.inputs.assembly,state.inputs.capabilities,state.inputs.actuator)
    forcing,eps,*_=_forcing(state,hw,Fraction(130),Fraction(131),state.attitude.quaternion)
    loads=PowerLoadBreakdown(**{f.name:float(n+1) for n,f in enumerate(fields(PowerLoadBreakdown))})
    eps=replace(eps,load_breakdown=loads,sunlit=False,incidence_angle_deg=0.)
    compilation=state.construction.compilation
    if limited:
        # Explicit declared regulated-bus limit. All physical wire, load and
        # battery owners remain real. The full demand must be refused first.
        compilation=replace(compilation,configuration=replace(compilation.configuration,bus_current_limit_a=.08))
    paid=ConstructionServiceWork();before=state.context.spacecraft_state.battery.energy_wh
    part,_=service_physical_substep(state.context,RationalSeconds(1,1),forcing,eps,state.inputs.protection,None,
        compilation=compilation,service_policy=ConstructionServicePolicy(),service_mode='NORMAL',service_work=paid,
        work=state.construction.work,limits=state.construction.inputs.limits,start_seconds=Fraction(130),end_seconds=Fraction(131))
    d=part.service;e=d.selected_electrical
    assert all(getattr(d.desired_loads,f.name)>0 for f in fields(PowerLoadBreakdown))
    assert all(0<=getattr(d.served_loads,f.name)<=getattr(loads,f.name) for f in fields(PowerLoadBreakdown))
    non_pv=[b for b in e.branches if b.component!='PV']
    # Independent I^2 R, P=VI and receiving/source balance, in W/A/ohm.
    for b in e.branches:
        op=b.electrical
        assert isclose(op.loss_w,op.current_a**2*op.resistance_ohm,rel_tol=2e-14,abs_tol=1e-14)
        assert isclose(op.source_power_w-op.delivered_power_w,op.loss_w,rel_tol=2e-12,abs_tol=1e-12)
    assert isclose(e.source_load_w,fsum(b.electrical.source_power_w for b in non_pv),rel_tol=1e-14)
    assert isclose(e.source_load_w,e.receiving_load_w+e.receiving_wire_loss_w,rel_tol=1e-14,abs_tol=1e-12)
    assert fsum(b.electrical.current_a for b in non_pv)<=compilation.configuration.bus_current_limit_a
    assert e.battery.unmet_load_w==0 and e.fully_served
    assert state.context.spacecraft_state.battery.energy_wh<=before
    assert paid.eps_calls_reserved==paid.eps_calls_returned+paid.eps_calls_refused
    assert paid.eps_work_unknown==0 and paid.selected_coupled_calls==1
    if limited:
        assert d.initial_wire_refusal and not d.full_commanded_service and paid.bisection_trials>0
        assert d.essential_unserved_w>0
    else:
        assert d.full_commanded_service and d.essential_fully_served and paid.bisection_trials==0
