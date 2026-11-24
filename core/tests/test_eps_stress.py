"""Task05D input invariants, independent budgets and reporting failure gates."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from math import ulp

import pytest

from examples.v5_eps_stress import HARDWARE,SCENARIOS,POLICY,build_inputs_program,independent_budgets
from examples.v5_eps_stress_report import matrix,case_id,validate_result,qualify
from examples.v5_ms_comparison import boundary,physical_samples
from ops_sim.v5.campaign_contract import PlannedAction
from ops_sim.v5.campaign_continuation import start_campaign,planning_boundary
from ops_sim.v5.campaign_controller import execute_selected
from ops_sim.v5.comparison_campaign import build_inputs_program as accepted_inputs
from ops_sim.v5.contact_execution import ConsumedContacts
from ops_sim.v5.solar import compute_solar_generation


@pytest.mark.parametrize('hardware',HARDWARE)
@pytest.mark.parametrize('scenario',SCENARIOS)
@pytest.mark.parametrize('level',[1,2])
@pytest.mark.parametrize('factor',[1.,.5])
def test_all_32_definitions_keep_hardware_and_admit_known_common_requests(hardware,scenario,level,factor):
    inputs,p=build_inputs_program(hardware,scenario,level=level,mode_factor=factor)
    original,old=accepted_inputs(hardware,level=level,mode_factor=factor)
    assert inputs.spacecraft_configuration==original.spacecraft_configuration
    assert p.protection==old.protection and p.knowledge==old.knowledge and p.initial_attitude==old.initial_attitude
    assert p.policy==POLICY and p.version==7 and p.initial_checkpoint.schema_version==5
    assert p.policy.max_decisions*p.policy.max_forecast_eps==131072
    assert (len(p.requests)+1)*p.integration.substeps<=4096
    assert p.policy.max_decisions*(2*len(p.requests)+1)*p.integration.substeps<=16384
    s=SCENARIOS[scenario];c=start_campaign(inputs,p)
    view,_=planning_boundary(inputs,p,c.memory)
    assert len(view.requests)==len(view.opportunities)==6 and all(r.release_seconds==0 for r in view.requests)
    assert len({r.product.footprint.region_id for r in p.requests})==6
    assert sum(r.product.request.priority_weight for r in p.requests)==12
    assert [r.product.request.priority_weight for r in p.requests]==[3,2,1,3,2,1]
    assert inputs.common_world.horizon_seconds==s['horizon']
    assert c.context.spacecraft_state.battery.energy_wh==inputs.spacecraft_configuration.eps.battery.nominal_energy_wh.value*s['initial_fraction']
    assert c.context.spacecraft_state.degradation==p.initial_checkpoint.restore(inputs).spacecraft_state.degradation
    assert [(o.opportunity.window_start_seconds,o.opportunity.window_end_seconds) for o in p.opportunities]==[(t,t+s['window']) for t in s['starts']]
    assert all(o.opportunity.imaging_duration_seconds==60 and o.acquisition.sizing.stored_bits==426241440 for o in p.opportunities)
    assert all(len(o.acquisition.sizing.captured_channels)==5 for o in p.opportunities)
    assert all(r.product.required_channels==('B','G','R','NIR') and r.product.delivery_deadline_seconds==s['deadline'] for r in p.requests)
    assert (p.contacts[0].start_time_seconds,p.contacts[0].end_time_seconds)==s['contact']
    assert p.forcing[0].start_seconds==0 and p.forcing[0].end_seconds==s['horizon']
    assert p.forcing[0].standby.sunlit==s['sunlit'] and p.forcing[0].standby.incidence_angle_deg==s['incidence_deg']
    assert p.forcing[0].standby.loads.total_load_w==12
    assert all('3600 s experiment' not in a and 'Admission ends at 2700' not in a for a in p.assumptions)


def test_matrix_and_independent_dimensional_arithmetic():
    jobs=matrix()
    assert len(jobs)==len({case_id(*j) for j in jobs})==40
    assert sum(j[-1]=='rolling' for j in jobs)==32
    assert sum(j[-1]=='fixed' for j in jobs)==8
    b=independent_budgets()
    assert b['A_baseline_before_workload_wh']=='40'
    assert list(map(Fraction,b['A_initial_wh']))==[172,129,86,43]
    assert list(map(Fraction,b['B_initial_wh']))==[Fraction(86,25),Fraction(129,50),Fraction(43,25),Fraction(43,50)]
    assert b['B_six_nominal_image_discharge_wh']==['20/3','25/6','5/3','0']
    assert b['all_product_bits']==2557448640 < b['contact_capacity_bits']==4800000000
    assert b['product_bits']==1539*4616*5*12==426241440


@pytest.mark.parametrize('hardware,expected',list(zip(HARDWARE,[45.,67.5,90.,112.5])))
def test_actual_binary64_cosine_and_common_wiring(hardware,expected):
    inputs,p=build_inputs_program(hardware,'B')
    f=p.forcing[0].standby
    solar=compute_solar_generation(inputs.spacecraft_configuration.eps.solar_array,sunlit=f.sunlit,incidence_angle_deg=f.incidence_angle_deg)
    assert solar.incidence_factor.hex()=='0x1.0000000000001p-1'
    assert abs(solar.generation_w-expected)<=2*ulp(expected)
    assert inputs.spacecraft_configuration.payload.optical_acquisition.acquisition_power_w.value==93
    half,hp=build_inputs_program(hardware,'B',mode_factor=.5)
    assert half.spacecraft_configuration.payload.optical_acquisition.acquisition_power_w.value==46.5
    assert hp.forcing[0].transmitter.electrical_power_w.value==46.5


def test_long_dark_standby_hand_energy_and_two_resolutions():
    results=[]
    for level in (1,2):
        inputs,p=build_inputs_program('J-E4','A',level=level,mode_factor=.5)
        state=start_campaign(inputs,p);view,_=planning_boundary(inputs,p,state.memory)
        previous,consumed=p.initial_attitude,ConsumedContacts(())
        for start in range(0,10800,1800):
            action=PlannedAction('standby',f'test-wait-{start}',start,start+1800,(),'fixed thermal/energy prefix check')
            o,_,previous,consumed=execute_selected(state.context,view,action,previous,consumed)
            assert not o.availability.reasons
        e=state.context.spacecraft_state.battery.energy_wh
        # 24 maximum substeps; allow one capacity-scale ULP per subtraction.
        assert abs(e-3)<=24*ulp(43.)
        results.append(boundary(state.context))
    assert max(abs(results[0]['temperatures_k'][n]-results[1]['temperatures_k'][n]) for n in ('bus','battery','payload'))<=.1


@pytest.mark.parametrize('level',[1,2])
def test_empty_contact_consumes_baseline_without_transmitter(level):
    inputs,p=build_inputs_program('J-E1','A',level=level)
    state=start_campaign(inputs,p);view,_=planning_boundary(inputs,p,state.memory)
    contact=replace(p.contacts[0],start_time_seconds=0,end_time_seconds=30)
    view=replace(view,contacts=(contact,))
    action=PlannedAction('contact',contact.contact_id.value,0,30,(),'isolated idle-contact accounting check')
    outcome,*_=execute_selected(state.context,view,action,p.initial_attitude,ConsumedContacts(()))
    assert outcome.transmitted_bits==0 and not outcome.services
    assert all(not s.transmitter_on for s in outcome.segments)
    assert abs(outcome.accounting.served_load_wh-.1)<=2*ulp(.1)
    assert state.context.simulation_time_seconds==30


def report_fixture():
    samples=[dict(seconds=str(t),energy_wh=10.,temperatures_k=dict(bus=293.,battery=293.,payload=293.)) for t in (0,300,600)]
    return dict(status='completed-horizon',scenario='B',requests=[dict(request_id=f'task05d-r{i}',credited_products=0) for i in range(6)],
        total_priority='12',boundaries=[dict(seconds=0),dict(seconds=600)],physical_samples=samples,acquired_bits=0,
        final_custody=dict(queued_bits=0,delivered_bits=0,partial_bits=0),selected_actions=['same'],
        mechanism=dict(received_bits=0,actual_intervals=[dict(start_seconds=0,end_seconds=600,requested_kind='standby',actual_kind='standby',reasons=[])]))


@pytest.mark.parametrize('bad',['incomplete','horizon','duplicate','nan','node','custody','receipt','gap'])
def test_invalid_evidence_is_never_a_valid_zero(bad):
    r=report_fixture()
    if bad=='incomplete': r['status']='incomplete'
    elif bad=='horizon': r['boundaries'][-1]['seconds']=599
    elif bad=='duplicate': r['physical_samples'].append(deepcopy(r['physical_samples'][-1]))
    elif bad=='nan': r['physical_samples'][1]['energy_wh']=float('nan')
    elif bad=='node': del r['physical_samples'][0]['temperatures_k']['bus']
    elif bad=='custody': r['acquired_bits']=1
    elif bad=='receipt': r['mechanism']['received_bits']=1
    else: r['mechanism']['actual_intervals'][0]['end_seconds']=599
    with pytest.raises(ValueError): validate_result(r)


@pytest.mark.parametrize('bad',['energy','temperature','credit','missing-coarse-time'])
def test_qualification_rejects_declared_screen_failures(bad):
    a,b=report_fixture(),report_fixture()
    if bad=='energy': b['physical_samples'][1]['energy_wh']+=.345
    elif bad=='temperature': b['physical_samples'][1]['temperatures_k']['bus']+=.101
    elif bad=='credit': b['requests'][0]['credited_products']=1
    else: b['physical_samples'][1]['seconds']='301'
    assert not qualify(a,b,344.)['qualified']


def test_time_alignment_uses_exact_rationals_not_array_indexes():
    a,b=report_fixture(),report_fixture()
    b['physical_samples'].insert(1,dict(seconds='150',energy_wh=11.,temperatures_k=dict(bus=293.,battery=293.,payload=293.)))
    q=qualify(a,b,344.)
    assert q['qualified'] and q['common_times_seconds']==['0','300','600']
    assert q['fine_unmatched_times']==['150']
