from dataclasses import replace
from fractions import Fraction as Q
import json,math
import pytest
from examples.m8_battery_port import make_inputs
from ops_sim.v5.environment_ageing import *
from ops_sim.v5.environment_ageing_document import to_data,from_data
from ops_sim.v5.environment_thermal import effective_network,thermal_network
from ops_sim.v5.lifecycle_quiet import EnvironmentQuietIntegrationPolicy,_scale

@pytest.fixture(scope='module')
def baseline():return make_inputs().base.model.simulation_inputs.spacecraft_configuration.thermal.network

def policy_for(network,**kw):
    return EnvironmentAgeingPolicy(emissivity=tuple(sorted((EmissivityAgeing(n.node_id.value,.2,0.,.001)for n in network.nodes),key=lambda x:x.node_id)),
        conductance=tuple(sorted((ConductanceAgeing(l.link_id.value,l.conductance_w_per_k.value*.5,0.,.001)for l in network.links),key=lambda x:x.link_id)),**kw)

def test_analytic_calendar_vs_incidence_exposure_and_no_duplicate_loss(baseline):
    p=policy_for(baseline,pv_floor_fraction=.5,pv_calendar_rate_per_second=.001,pv_exposure_rate_per_second=.002)
    s=initial_state(p,128,baseline,1.);w=EnvironmentAgeingWork()
    dark=propose(p,s,baseline,Q(128),Q(228),False,0.,w)
    lit=propose(p,s,baseline,Q(128),Q(228),True,0.,w)
    back=propose(p,s,baseline,Q(128),Q(228),True,180.,w)
    assert dark.calendar_seconds==lit.calendar_seconds==Q(100)
    assert lit.pv_exposure_seconds==100 and dark.pv_exposure_seconds==back.pv_exposure_seconds==0
    assert retention(p,dark)==1.-.5*(.1/1.1)
    assert retention(p,lit)==1.-.5*(.3/1.3)
    assert retention(p,back)==retention(p,dark) and s.selected_cuts==0
    assert w.proposed==w.returned==3 and w.failed==0

def test_rotated_incidence_and_partition_exposure(baseline):
    p=policy_for(baseline);s=initial_state(p,0,baseline,.9);w=EnvironmentAgeingWork()
    for i in range(2):s=propose(p,s,baseline,Q(50*i),Q(50*(i+1)),True,60.,w)
    assert abs(s.pv_exposure_seconds-50)<2.e-14 and s.thermal_exposure_seconds==100 and s.calendar_seconds==100
    assert s.selected_cuts==2

def test_epsilon_G_only_and_provenance(baseline):
    p=policy_for(baseline);s=initial_state(p,0,baseline,1.);s=propose(p,s,baseline,Q(0),Q(100),True,0.,EnvironmentAgeingWork())
    e=effective_network(p,s,baseline);n=e.validate(baseline,p,s)
    assert n!=baseline and thermal_network((e,p,s),baseline)==n
    for a,b in zip(baseline.nodes,n.nodes):assert replace(b,emissivity=a.emissivity)==a
    for a,b in zip(baseline.links,n.links):assert replace(b,conductance_w_per_k=a.conductance_w_per_k)==a
    with pytest.raises(ValueError):replace(e,state_identity='0'*64).validate(baseline,p,s)

@pytest.mark.parametrize('field,value',[('pv_floor_fraction',True),('pv_floor_fraction',0.),('pv_floor_fraction',1.1),('pv_exposure_rate_per_second',float('nan')),('pv_calendar_rate_per_second',-1.),('initial_calendar_seconds',1.),('maximum_proposals',False),('method','other'),('assumption','NASA_CALIBRATED')])
def test_strict_domains(field,value):
    with pytest.raises((ValueError,TypeError)):EnvironmentAgeingPolicy(**{field:value})

def test_foreign_ids_and_declared_graph_limits(baseline):
    with pytest.raises(ValueError):admit_network(baseline,EnvironmentAgeingPolicy(emissivity=(EmissivityAgeing('absent',.2),)))
    with pytest.raises(ValueError):EnvironmentAgeingPolicy(emissivity=tuple(EmissivityAgeing('same',.2)for _ in range(17)))

def test_strict_codec_and_no_unknown_fields(baseline):
    p=policy_for(baseline);d=json.loads(json.dumps(to_data(p)));assert from_data(d)==p
    d['unknown']=0
    with pytest.raises(ValueError):from_data(d)

def test_work_failure_is_paid_state_atomic(baseline):
    p=EnvironmentAgeingPolicy(maximum_proposals=1);s=initial_state(p,0,baseline,1.);w=EnvironmentAgeingWork()
    with pytest.raises(ValueError):propose(p,s,baseline,Q(1),Q(2),True,0.,w)
    assert w.proposed==w.failed==1 and s.clock_seconds==0
    with pytest.raises(ValueError,match='WORK_LIMIT'):propose(p,s,baseline,Q(0),Q(1),True,0.,w)
    assert w.proposed==1

def test_asymptote_large_domain_finite_no_clamp():
    assert .5<saturate(1.,.5,Q(10**12),1.e12,1.,1.)<1.

@pytest.mark.parametrize('name,field',[('environment_pv_exposure_seconds','absolute_exposure_seconds'),('environment_calendar_seconds','absolute_exposure_seconds'),('environment_epsilon:bus','absolute_emissivity'),('environment_conductance:link','absolute_conductance_w_per_k'),('environment_pv_retention','absolute_retention')])
def test_explicit_metric_units(name,field):
    p=EnvironmentQuietIntegrationPolicy();assert _scale(name,p)==getattr(p,field)


def test_effective_epsilon_and_G_are_consumed_by_real_thermal_api(baseline):
    from copy import deepcopy
    from test_construction_service import leaf
    from ops_sim.v5.thermal import compute_thermal_substep_transition
    from ops_sim.v5.integration_time import RationalSeconds
    state,forcing,*_=leaf(mode='NORMAL')
    thermal=deepcopy(state.context.spacecraft_state.thermal)
    for i,n in enumerate(thermal.node_states):n.temperature_k=300.+10*i
    p=policy_for(baseline);s=initial_state(p,128,baseline,1.)
    s=propose(p,s,baseline,Q(128),Q(228),True,0.,EnvironmentAgeingWork());effective=effective_network(p,s,baseline).network
    a=compute_thermal_substep_transition(thermal,baseline,forcing.thermal_inputs,duration=RationalSeconds.from_fraction(Q(1)))
    b=compute_thermal_substep_transition(thermal,effective,forcing.thermal_inputs,duration=RationalSeconds.from_fraction(Q(1)))
    assert any(x.end_temperature_k!=y.end_temperature_k for x,y in zip(a.node_transitions,b.node_transitions))
    for x,y,n,m in zip(a.node_transitions,b.node_transitions,baseline.nodes,effective.nodes):
        # Same T,A,sink: independently expected radiation ratio epsilon1/epsilon0.
        if n.emissivity.value:
            expected=x.radiative_heat_into_w*(m.emissivity.value/n.emissivity.value)
            assert abs(y.radiative_heat_into_w-expected)<=8*math.ulp(expected)
    for x,y,l,m in zip(a.link_heat_flows,b.link_heat_flows,baseline.links,effective.links):
        expected=x.heat_flow_a_to_b_w*(m.conductance_w_per_k.value/l.conductance_w_per_k.value)
        assert abs(y.heat_flow_a_to_b_w-expected)<=8*math.ulp(expected)
    assert any(x.heat_flow_a_to_b_w!=y.heat_flow_a_to_b_w for x,y in zip(a.link_heat_flows,b.link_heat_flows))

def test_rejected_full_trials_do_not_accumulate_actual_exposure(baseline):
    from types import SimpleNamespace
    from copy import deepcopy
    from ops_sim.v5.environment_lifecycle import EnvironmentPrivate
    from ops_sim.v5.lifecycle_quiet import QuietControllerState,QuietWork,QuietSample,QuietTrial,integrate_quiet_hold
    p=EnvironmentAgeingPolicy(pv_exposure_rate_per_second=.001);initial=initial_state(p,0,baseline,1.);paid=EnvironmentAgeingWork()
    policy=EnvironmentQuietIntegrationPolicy(absolute_temperature_k=1.e-8,relative_tolerance=1.e-10,detailed_seconds=1)
    v=EnvironmentPrivate(SimpleNamespace(t=400.),initial);qw=QuietWork()
    def values(v):return (('temperature:bus',v.context.t),('environment_pv_exposure_seconds',v.history.pv_exposure_seconds))
    def step(v,a,b):
        v.context.t-=.01*(v.context.t-280.)*float(b-a)
        v.history=propose(p,v.history,baseline,a,b,True,0.,paid)
        return QuietTrial(v,(a,b),QuietSample(values(v),(('served_load_wh',0.),),('steady',)))
    result=integrate_quiet_hold(v,Q(0),Q(60),policy=policy,controller=QuietControllerState(Q(0),60,method=policy.method),work=qw,clone_context=deepcopy,state_values=values,step=step)
    assert qw.rejected_macros>0 and paid.proposed>result.context.history.selected_cuts
    assert result.context.history.pv_exposure_seconds==60. and initial.calendar_seconds==0 and initial.pv_exposure_seconds==0.


@pytest.mark.parametrize('name',['pv_calendar_rate_per_second','pv_exposure_rate_per_second','initial_pv_exposure_seconds'])
def test_huge_integer_is_typed_before_float_conversion(name):
    with pytest.raises(ValueError):EnvironmentAgeingPolicy(**{name:2**2000})

@pytest.mark.parametrize('name',['absolute_exposure_seconds','absolute_energy_wh','absolute_temperature_k'])
def test_huge_quiet_scale_is_typed_finite_refusal(name):
    with pytest.raises(ValueError):EnvironmentQuietIntegrationPolicy(**{name:2**2000})
