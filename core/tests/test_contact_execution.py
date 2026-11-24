"""Independent ordered-service, exact-time, protected-physics and rollback checks."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from math import ceil, ulp

import pytest

from examples import v5_contact_execution_demo as demo
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.contact_execution import ConsumedContacts, execute_contact_plan
import ops_sim.v5.contact_execution as execution
from ops_sim.v5.engine import SimulationEngine
from ops_sim.v5.experiment_codec import canonical_content, check_schema_coverage
from ops_sim.v5.ids import AcquisitionDataRecordId, GroundContactId, ThermalLinkId
from ops_sim.v5.integration_time import RationalSeconds, IntegrationPolicy, checked_duration
from ops_sim.v5.state import FDIRState
from ops_sim.v5.thermal_config import ThermalLinkConfig


def run(c, plan, policy, level=2, consumed=None):
    return execute_contact_plan(c, plan, policy=policy, integration=IntegrationPolicy(level),
                                consumed_contacts=ConsumedContacts(()) if consumed is None else consumed)


@pytest.mark.parametrize("bits,partials,rate,duration,order,expected", [
    ((20,20),(),3,10,(0,1),(20,10)),
    ((20,20),((0,5),),3,10,(0,1),(15,15)),
    ((3,5,7),(),3,10,(0,1,2),(3,5,7)),
    ((10,20),(),3,10,(0,1),(10,20)),
    ((1,),(),3,10,(0,),(1,)),
    ((10,8,4),((0,4),(1,2)),3,10,(1,0,2),(6,6,4)),
    ((10,20),(),3,10,(),()),
    ((10,20),(),3,10,(1,),(20,)),
])
@pytest.mark.parametrize("level", [0,1,2])
def test_independent_bit_time_storage_and_order(bits,partials,rate,duration,order,expected,level):
    c,p,policy=demo.contact_case(bits=bits,partials=partials,rate=rate,duration=duration)
    original=deepcopy(c);records=c.spacecraft_state.data_storage.stored_records
    p=replace(p,record_ids=tuple(records[i].record_id for i in order))
    result=run(c,p,policy,level);o=result.outcome
    assert tuple(s.transmitted_bits for s in o.services)==expected
    assert tuple(s.record.record_id for s in o.services)==p.record_ids[:len(expected)]
    before=dict(partials);completed=[];cursor=Fraction(0)
    for i,served,s in zip(order,expected,o.services):
        assert s.progress_before_bits==before.get(i,0)
        assert s.progress_after_bits==before.get(i,0)+served<=bits[i]
        assert s.start_offset.fraction==cursor
        cursor+=Fraction(served,rate)
        assert s.end_offset.fraction==cursor
        if s.progress_after_bits==bits[i]:
            completed.append(records[i].record_id)
            assert s.completed and s.completion_time_seconds==100+ceil(cursor)
            assert Fraction(s.completion_time_seconds)>=100+cursor
        else:
            assert not s.completed and s.completion_time_seconds is None
    assert o.transmitted_bits==sum(expected)
    assert o.tx_on_seconds.fraction==Fraction(sum(expected),rate)
    assert o.tx_on_seconds.fraction+o.idle_seconds.fraction==duration
    assert tuple(d.record.record_id for d in c.ground_data_delivery_state.completed_deliveries)==tuple(completed)
    assert all(d.completing_contact==p.contact for d in c.ground_data_delivery_state.completed_deliveries)
    assert tuple(r.record_id for r in c.spacecraft_state.data_storage.stored_records)==tuple(r.record_id for r in records if r.record_id not in completed)
    initial_storage=sum(bits);final_storage=sum(r.stored_equivalent_bits for r in c.spacecraft_state.data_storage.stored_records)
    assert initial_storage-final_storage==sum(bits[i] for i in order if records[i].record_id in completed)
    assert c.simulation_time_seconds==100+duration and c.diagnostics.completed_steps==original.diagnostics.completed_steps+1
    assert c.ground_knowledge_state==original.ground_knowledge_state
    assert o.accounting.numerical_substeps==len(o.segments)*2**level
    assert result.consumed_contacts==ConsumedContacts((p.contact,))
    assert o.segments[-1].transmitter_on==(o.idle_seconds.fraction==0)
    assert all(s.transmitter_on for s in o.segments[:-1])
    assert c.spacecraft_state.degradation.battery.cumulative_energy_throughput_wh>original.spacecraft_state.degradation.battery.cumulative_energy_throughput_wh


def test_non_dyadic_completion_and_full_idle_energy_reference():
    evidence=demo.numerical_reference()
    assert evidence['transmitted_bits']==18 and evidence['tx_on_s']=='6' and evidence['idle_s']=='4'
    c,p,policy=demo.contact_case();result=run(c,p,policy)
    assert result.outcome.services[1].end_offset.fraction==Fraction(14,3)
    assert result.outcome.services[1].completion_time_seconds==105
    assert result.outcome.services[0].completion_time_seconds==102
    assert result.outcome.services[2].completion_time_seconds==106
    idle=result.outcome.segments[-1]
    assert idle.accounting.requested_load_wh==12*4/3600
    assert idle.trace.samples[-1].battery_energy_wh<idle.trace.samples[0].battery_energy_wh
    assert idle.trace.samples[-1].battery_retention<idle.trace.samples[0].battery_retention
    assert idle.trace.samples[-1].temperatures_k!=idle.trace.samples[0].temperatures_k
    assert abs(result.outcome.accounting.requested_load_wh-float(Fraction(7,75)))<=64*ulp(float(Fraction(7,75)))
    assert result.outcome.accounting.requested_load_wh<evidence['whole_contact_tx_energy_wh']


def test_same_outer_interval_retains_task03a_whole_contact_tx_semantics():
    c,p,policy=demo.contact_case();legacy=deepcopy(c)
    legacy.inputs=replace(legacy.inputs,numerical_config=replace(legacy.inputs.numerical_config,
        timestep_seconds=10,checkpoint_interval_seconds=10))
    old=SimulationEngine().step_coupled_downlink(legacy,p.contact,record_id=p.record_ids[0],physical_inputs=p.tx_inputs)
    new=run(c,p,policy)
    assert old.eps_result.battery.load_w==48.
    assert old.transmission_result.transmitted_equivalent_bits_this_service==6.
    assert len(legacy.ground_data_delivery_state.completed_deliveries)==1
    assert new.outcome.transmitted_bits==18 and len(c.ground_data_delivery_state.completed_deliveries)==3
    assert legacy.spacecraft_state.battery.energy_wh<c.spacecraft_state.battery.energy_wh
    assert legacy.simulation_time_seconds==c.simulation_time_seconds==110


def test_thermal_denial_uses_state_after_earlier_success_and_idles_entire_remainder():
    c,p,policy=demo.contact_case(bits=(3,9),partials=(),rate=3,duration=5)
    cfg=c.inputs.spacecraft_configuration;n=cfg.thermal.network
    nodes=tuple(replace(node,heat_capacity_j_per_k=demo.old.physical.parameter_value(node.heat_capacity_j_per_k,4.))
        if node.node_id==n.bus_node_id else node for node in n.nodes)
    c.inputs=replace(c.inputs,spacecraft_configuration=replace(cfg,thermal=replace(cfg.thermal,network=replace(n,nodes=nodes))))
    alone=deepcopy(c)
    alone_result=run(alone,replace(p,record_ids=(p.record_ids[1],)),policy)
    assert alone_result.outcome.denied_record_id is None  # B is feasible from original 300 K.
    result=run(c,p,policy);o=result.outcome
    assert o.transmitted_bits==3 and o.denied_record_id==p.record_ids[1]
    assert len(o.services)==1 and len(o.attempts)==2
    assert o.attempts[0].availability.available and not o.attempts[1].availability.available
    assert o.tx_on_seconds.fraction==1 and o.idle_seconds.fraction==4
    assert o.segments[1].trace.start_offset.fraction==1
    assert {p.record_id for p in c.ground_data_delivery_state.partial_transfers}==set()
    assert c.spacecraft_state.data_storage.stored_records[0].record_id==p.record_ids[1]
    assert c.simulation_time_seconds==105 and c.diagnostics.completed_steps==1
    assert c.spacecraft_state.onboard.fdir_state is FDIRState.BACKUP
    assert abs(dict(o.segments[-1].trace.samples[-1].temperatures_k)[n.bus_node_id]-314.5)<32*ulp(314.5)


def test_later_power_denial_keeps_first_record_and_does_not_charge_tx_during_idle():
    c,p,policy=demo.contact_case(bits=(3,9),partials=(),rate=3,duration=5)
    # Exactly enough for first 1 s TX, then insufficient for 3 s TX. Idle still consumes energy.
    c.spacecraft_state.battery.energy_wh=.025
    result=run(c,p,policy);o=result.outcome
    assert o.transmitted_bits==3 and o.denied_record_id==p.record_ids[1]
    assert o.tx_on_seconds.fraction==1 and o.idle_seconds.fraction==4
    assert o.segments[-1].accounting.requested_load_wh==12*4/3600
    assert o.attempts[-1].availability.action_unmet_w>0
    assert o.segments[-1].accounting.unmet_load_wh>0
    assert c.spacecraft_state.onboard.critical_energy_since_seconds==100


def test_refinement_can_change_sampled_admission_without_changing_physical_plan():
    from examples.v5_substepped_execution_demo import analytic_two_node
    c,p,policy=demo.contact_case(bits=(12,),partials=(),rate=1,duration=12)
    cfg=c.inputs.spacecraft_configuration;n=cfg.thermal.network
    nodes=tuple(replace(node,heat_capacity_j_per_k=demo.old.physical.parameter_value(node.heat_capacity_j_per_k,10.))
        if node.node_id in (n.bus_node_id,n.payload_node_id) else node for node in n.nodes)
    link=ThermalLinkConfig(ThermalLinkId('task04b-refinement'),n.bus_node_id,n.payload_node_id,
        demo.old.physical.storage._parameter('thermal.link.task04b-refinement.conductance','W/K',1.))
    c.inputs=replace(c.inputs,spacecraft_configuration=replace(cfg,thermal=replace(cfg.thermal,network=replace(n,nodes=nodes,links=(link,)))))
    for node in c.spacecraft_state.thermal.node_states:
        node.temperature_k={'bus':310.,'payload':290.,'battery':300.}[node.node_id.value]
    fine=deepcopy(c);coarse=run(c,p,policy,0);refined=run(fine,p,policy,10)
    assert coarse.outcome.transmitted_bits==12 and refined.outcome.transmitted_bits==0
    assert refined.outcome.denied_record_id==p.record_ids[0]
    assert c.simulation_time_seconds==fine.simulation_time_seconds==112
    expected=analytic_two_node(10,10,310,290,26,3,12)
    predicted=dict(refined.outcome.attempts[0].predicted_trace.samples[-1].temperatures_k)
    assert abs(predicted[n.bus_node_id]-expected[0])<.002
    assert predicted[n.bus_node_id]>320


@pytest.mark.parametrize('failure', ['late-segment','final-result','final-checkpoint','commit-assignment'])
def test_whole_contact_rollback_preserves_external_values_and_identities(monkeypatch,failure):
    c,p,policy=demo.contact_case(bits=(3,3,3),partials=(),duration=5)
    before=deepcopy(c);consumed=ConsumedContacts(())
    names=('spacecraft_state','ground_knowledge_state','ground_data_delivery_state','mission_state','controller_state','diagnostics')
    refs=tuple(getattr(c,n) for n in names)
    if failure=='late-segment':
        original=execution._physical_substep;calls=[]
        def fail(*a,**kw):
            calls.append(1)
            if len(calls)==6:raise RuntimeError('late third-record physical failure')
            return original(*a,**kw)
        monkeypatch.setattr(execution,'_physical_substep',fail)
    elif failure=='final-result':
        monkeypatch.setattr(execution.ContactExecutionResult,'__post_init__',lambda self:(_ for _ in ()).throw(RuntimeError('final result')))
    elif failure=='final-checkpoint':
        original=execution.checked_checkpoint
        def fail(ctx):
            if ctx.simulation_time_seconds==105:raise RuntimeError('final checkpoint')
            return original(ctx)
        monkeypatch.setattr(execution,'checked_checkpoint',fail)
    else:
        def fail(original,candidate):
            original.simulation_time_seconds=candidate.simulation_time_seconds
            original.spacecraft_state=candidate.spacecraft_state
            raise RuntimeError('late commit assignment')
        monkeypatch.setattr(SimulationEngine,'_commit',staticmethod(fail))
    with pytest.raises(RuntimeError):run(c,p,policy,0,consumed)
    assert c==before and all(getattr(c,n) is r for n,r in zip(names,refs))
    assert consumed.contacts==()


@pytest.mark.parametrize('malformed',['duplicate','missing-last','fractional-record','fractional-progress','fractional-rate',
    'zero-rate','wrong-start','outside-horizon','chronology','already-completed','consumed-id','wrong-off-load','wrong-environment','work-bound','capacity-bound'])
def test_malformed_plan_rejected_before_physical_substeps(monkeypatch,malformed):
    c,p,policy=demo.contact_case();consumed=ConsumedContacts(())
    def forbidden(*a,**kw):raise AssertionError('malformed plan reached physical integration')
    monkeypatch.setattr(execution,'_physical_substep',forbidden)
    with pytest.raises((ValueError,TypeError)):
        if malformed=='duplicate':p=replace(p,record_ids=(p.record_ids[0],p.record_ids[0]))
        elif malformed=='missing-last':p=replace(p,record_ids=(*p.record_ids,AcquisitionDataRecordId('missing')))
        elif malformed=='fractional-record':
            rs=c.spacecraft_state.data_storage.stored_records
            c.spacecraft_state.data_storage.stored_records=(replace(rs[0],stored_equivalent_bits=9.5),*rs[1:])
        elif malformed=='fractional-progress':
            ps=c.ground_data_delivery_state.partial_transfers
            c.ground_data_delivery_state.partial_transfers=(replace(ps[0],transmitted_equivalent_bits=4.5),*ps[1:])
        elif malformed in ('fractional-rate','zero-rate','capacity-bound'):
            cfg=c.inputs.spacecraft_configuration
            value={'fractional-rate':3.5,'zero-rate':0.,'capacity-bound':float(2**40)}[malformed]
            c.inputs=replace(c.inputs,spacecraft_configuration=replace(cfg,communications=replace(cfg.communications,
                nominal_downlink_data_rate_bps=demo.old.physical.parameter_value(cfg.communications.nominal_downlink_data_rate_bps,value))))
        elif malformed=='wrong-start':p=replace(p,contact=replace(p.contact,start_time_seconds=101))
        elif malformed=='outside-horizon':p=replace(p,contact=replace(p.contact,end_time_seconds=c.inputs.common_world.horizon_seconds+1))
        elif malformed=='chronology':
            rs=c.spacecraft_state.data_storage.stored_records
            c.spacecraft_state.data_storage.stored_records=(replace(rs[0],scheduled_start_seconds=99),*rs[1:])
        elif malformed=='already-completed':
            from ops_sim.v5.data_delivery import CompletedAcquisitionDelivery
            rs=c.spacecraft_state.data_storage.stored_records
            c.spacecraft_state.data_storage.stored_records=rs[1:]
            c.ground_data_delivery_state.partial_transfers=c.ground_data_delivery_state.partial_transfers[1:]
            c.ground_data_delivery_state.completed_deliveries=(CompletedAcquisitionDelivery(rs[0],replace(p.contact,start_time_seconds=20,end_time_seconds=30)),)
        elif malformed=='consumed-id':consumed=ConsumedContacts((replace(p.contact,start_time_seconds=90,end_time_seconds=100),))
        elif malformed=='wrong-off-load':p=replace(p,idle_inputs=replace(p.idle_inputs,loads=replace(p.idle_inputs.loads,base_bus_w=11.)))
        elif malformed=='wrong-environment':p=replace(p,idle_inputs=replace(p.idle_inputs,sunlit=True))
        run(c,p,policy,12 if malformed=='work-bound' else 2,consumed)


@pytest.mark.parametrize('n,d',[(0,1),(1,3),(23,2),(1,2**52),(2**40,1)])
def test_exact_rational_offsets_and_single_binary64_conversion(n,d):
    t=RationalSeconds(n,d)
    assert t.fraction==Fraction(n,d)
    if n:
        assert checked_duration(t)==float(Fraction(n,d))
        error=abs(Fraction.from_float(t.seconds)-t.fraction)
        assert error<=Fraction.from_float(ulp(t.seconds))/2
    else:
        with pytest.raises(ValueError):checked_duration(t)


@pytest.mark.parametrize('n,d',[(True,1),(1.,3),(1,0),(-1,3),(2,6),(0,2),(1,2**65),(2**97,1)])
def test_invalid_rational_representation_rejected(n,d):
    with pytest.raises((ValueError,TypeError)):RationalSeconds(n,d)


def test_closed_codec_covers_version_five_records():
    check_schema_coverage()
    s=demo.build_demo_state()
    assert s.program.version==5 and s.program.initial_checkpoint.schema_version==5
    assert canonical_content(s.program)['kind']=='record'


def test_public_clock_stays_exact_beyond_binary64_integer_resolution():
    c,p,policy=demo.contact_case(bits=(1,),partials=(),rate=3,duration=10)
    start=2**60+1
    c.inputs=replace(c.inputs,common_world=replace(c.inputs.common_world,horizon_seconds=start+100))
    c.simulation_time_seconds=start
    p=replace(p,contact=replace(p.contact,start_time_seconds=start,end_time_seconds=start+10))
    result=run(c,p,policy)
    assert c.simulation_time_seconds==start+10 and type(c.simulation_time_seconds) is int
    assert result.outcome.services[0].end_offset.fraction==Fraction(1,3)
    assert result.outcome.services[0].completion_time_seconds==start+1


@pytest.mark.parametrize('level',[0,2,4])
def test_whole_contact_solar_forcing_distributed_by_actual_service_and_idle_time(level):
    from ops_sim.v5.degradation import SolarDegradationForcingInput
    c,p,policy=demo.contact_case()
    loss=SolarDegradationForcingInput(.006)
    p=replace(p,tx_inputs=replace(p.tx_inputs,solar_degradation_forcing=loss),
              idle_inputs=replace(p.idle_inputs,solar_degradation_forcing=loss))
    result=run(c,p,policy,level);o=result.outcome
    assert abs(o.accounting.solar_retention_loss-.006)<=4*ulp(.006)
    assert abs(c.spacecraft_state.degradation.solar.generation_retention-.794)<=o.accounting.numerical_substeps*ulp(.8)
    for segment in o.segments:
        expected=float(Fraction(.006)*(segment.trace.end_offset.fraction-segment.trace.start_offset.fraction)/10)
        assert abs(segment.accounting.solar_retention_loss-expected)<=4*ulp(expected)


def test_schema_valid_late_data_corruption_is_rejected_before_outer_commit(monkeypatch):
    c,p,policy=demo.contact_case(bits=(20,20),partials=(),rate=3,duration=10)
    before=deepcopy(c);delivery=c.ground_data_delivery_state;spacecraft=c.spacecraft_state
    original=execution._apply_services
    def corrupt(candidate,contact,services):
        original(candidate,contact,services)
        progress=candidate.ground_data_delivery_state.partial_transfers[0]
        candidate.ground_data_delivery_state.partial_transfers=(replace(progress,transmitted_equivalent_bits=11.),)
    monkeypatch.setattr(execution,'_apply_services',corrupt)
    with pytest.raises(ValueError,match='partial service disagrees'):
        run(c,p,policy)
    assert c==before and c.ground_data_delivery_state is delivery and c.spacecraft_state is spacecraft


class _RateInt(int):
    pass


class _RateFloat(float):
    pass


def _raw_rate_case(raw_rate, duration=2):
    c,p,policy=demo.contact_case(bits=(3,),partials=(),rate=3,duration=duration)
    cfg=c.inputs.spacecraft_configuration
    parameter=replace(cfg.communications.nominal_downlink_data_rate_bps,value=raw_rate)
    c.inputs=replace(c.inputs,spacecraft_configuration=replace(cfg,
        communications=replace(cfg.communications,nominal_downlink_data_rate_bps=parameter)))
    prior=replace(p.contact,contact_id=GroundContactId('raw-rate-prior'),start_time_seconds=90,end_time_seconds=100)
    return c,p,policy,ConsumedContacts((prior,))


def _assert_rate_rejection_unchanged(c,p,policy,consumed,expected=(ValueError,TypeError)):
    before=deepcopy(c);history=consumed.contacts
    names=('inputs','spacecraft_state','ground_knowledge_state','ground_data_delivery_state',
           'mission_state','controller_state','diagnostics')
    refs=tuple(getattr(c,name) for name in names)
    storage=c.spacecraft_state.data_storage;records=storage.stored_records
    delivery=c.ground_data_delivery_state
    partials=delivery.partial_transfers;completed=delivery.completed_deliveries
    with pytest.raises(expected):
        run(c,p,policy,0,consumed)
    assert c==before and all(getattr(c,name) is ref for name,ref in zip(names,refs))
    assert c.spacecraft_state.data_storage is storage and storage.stored_records is records
    assert delivery.partial_transfers is partials and delivery.completed_deliveries is completed
    assert consumed.contacts is history and consumed==ConsumedContacts(history)
    assert c.simulation_time_seconds==100 and c.diagnostics.completed_steps==before.diagnostics.completed_steps
    assert not partials and not completed  # No bits, delivery or storage release credited.


@pytest.mark.parametrize('raw_rate',[
    Fraction(3)-Fraction(1,2**60), Fraction(3)+Fraction(1,2**60),
    Fraction(3), Fraction(7,2), 3.5, .5, 2**40+1, float(2**40+1),
    _RateInt(3), _RateFloat(3),
],ids=['fraction-below','fraction-above','integral-fraction','fractional-fraction',
       'noninteger-float','below-one','int-over-bound','float-over-bound','int-subclass','float-subclass'])
def test_raw_rate_rejects_before_lossy_capacity_or_physics(monkeypatch,raw_rate):
    c,p,policy,consumed=_raw_rate_case(raw_rate)
    def forbidden(*a,**kw):
        raise AssertionError('unsupported raw rate reached capacity conversion or physics')
    monkeypatch.setattr(execution,'compute_downlink_capacity',forbidden)
    monkeypatch.setattr(execution,'_physical_substep',forbidden)
    _assert_rate_rejection_unchanged(c,p,policy,consumed)


@pytest.mark.parametrize('raw_rate',[1,1.,3,3.])
def test_raw_rate_preserves_builtin_integer_and_integer_float_service(raw_rate):
    c,p,policy,consumed=_raw_rate_case(raw_rate)
    result=run(c,p,policy,0,consumed);out=result.outcome
    expected_rate=int(raw_rate);expected_bits=min(3,expected_rate*2)
    assert type(out.bitrate_bps) is int and out.bitrate_bps==expected_rate
    assert out.transmitted_bits==expected_bits
    assert out.tx_on_seconds.fraction==Fraction(expected_bits,expected_rate)
    assert out.idle_seconds.fraction==2-Fraction(expected_bits,expected_rate)
    assert out.services[0].completed==(expected_bits==3)
    assert out.services[0].completion_time_seconds==(101 if expected_bits==3 else None)
    assert c.simulation_time_seconds==102 and c.diagnostics.completed_steps==1
    assert result.consumed_contacts.contacts==(*consumed.contacts,p.contact)


@pytest.mark.parametrize('raw_rate',[2**40,float(2**40)])
def test_raw_rate_and_exact_capacity_upper_bound_remain_admitted(raw_rate):
    c,p,policy,consumed=_raw_rate_case(raw_rate,duration=1)
    before=deepcopy(c)
    *_,rate=execution.validate_contact_plan(c,p,consumed,policy,IntegrationPolicy(0))
    assert rate==2**40 and type(rate) is int and c==before


@pytest.mark.parametrize('raw_rate',[2**39,float(2**39)])
def test_raw_rate_valid_but_exact_contact_capacity_over_bound_rejects(monkeypatch,raw_rate):
    c,p,policy,consumed=_raw_rate_case(raw_rate,duration=3)
    def forbidden(*a,**kw):raise AssertionError('oversized exact capacity reached physics')
    monkeypatch.setattr(execution,'_physical_substep',forbidden)
    _assert_rate_rejection_unchanged(c,p,policy,consumed,ValueError)


def test_raw_rate_must_agree_with_historical_capacity_proposal(monkeypatch):
    from ops_sim.v5.communications import DownlinkCapacityProposal
    c,p,policy,consumed=_raw_rate_case(3)
    # A valid historical proposal for another rate cannot override the raw owner.
    monkeypatch.setattr(execution,'compute_downlink_capacity',lambda *a:DownlinkCapacityProposal(p.contact,4.,2,8.))
    def forbidden(*a,**kw):raise AssertionError('inconsistent nominal proposal reached physics')
    monkeypatch.setattr(execution,'_physical_substep',forbidden)
    _assert_rate_rejection_unchanged(c,p,policy,consumed,ValueError)
