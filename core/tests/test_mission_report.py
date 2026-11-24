from fractions import Fraction
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.mission_report import MissionReport,pack,unpack
from ops_sim.v5.mission_report_document import validate_state,dumps_report,loads_report
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace
import ops_sim.v5.mission_report as report_owner
from ops_sim.v5.mission_report_document import validate_summary

def test_fixed_month_boundaries_are_exact_not_gregorian():
    r=MissionReport(make_inputs(wire='weakness'))
    assert r.bucket(Fraction(199999,1000))==0 and r.bucket(200)==1
    assert r.bucket(2592200)==2
    validate_state(r.state);assert loads_report(dumps_report(r.state))==r.state
    restored=MissionReport(r.root,state=r.state);assert restored.state==r.state

def test_rational_report_sums_preserve_binary64_sum_inputs():
    q=sum((Fraction(x) for x in (.1,.2,.3)),Fraction())
    assert unpack(pack(q))==q

def test_report_duplicate_cursor_and_foreign_root_reject():
    r=MissionReport(make_inputs(wire='weakness'))
    bad=dict(r.state,cursor=True)
    with pytest.raises(ValueError):validate_state(bad)


def original_report():
    return json.loads(ORIGINAL_B51_REPORT_RAW)


def original_state():
    summary=original_report()
    return dict(method=summary['method'],root_identity=summary['root_identity'],offset_seconds=summary['epoch_offset_seconds'],
        period_seconds=summary['period_seconds'],start_seconds=summary['start_seconds'],end_seconds=summary['end_seconds'],
        cursor=15,base_cursor=0,seen_actions=['b47-command-'+str(i) for i in range(15)],
        seen_receipts=['b47-medium','b47-low'],seen_offered=['b47-urgent','b47-medium','b47-low'],seen_expired=['b47-urgent'],
        sealed=summary['rows'],current=None,control_units=28992,control_reserved_units=15728640,detail_bytes=3687,status='COMPLETE')


def test_original_b51_primary_report_and_state_still_load_byte_exactly():
    assert sha256(ORIGINAL_B51_REPORT_RAW).hexdigest()=='4c0d38ee9680432b29f76d79a56160f3367633cf956484f1bb66656260c6848f'
    assert dumps_report(loads_report(ORIGINAL_B51_REPORT_RAW))==ORIGINAL_B51_REPORT_RAW
    state_raw=dumps_report(original_state())
    assert sha256(state_raw).hexdigest()=='43e097a16f0fc177169bcad51fd4dd42f429e0a19dbb3193b3a2a48989ddb3d1'
    assert loads_report(state_raw)==original_state()


@pytest.mark.parametrize(('path','value'),[
    (('totals','priority_score'),999),
    (('totals','useful_bits'),-1),
    (('totals','executed_point_seconds'),99999),
    (('end_seconds',),1),
    (('totals','maximum_temperature_k','battery'),-100),
])
def test_f1_five_reported_single_mutations_reject_after_canonical_reencoding(path,value):
    report=original_report();cursor=report
    for key in path[:-1]:cursor=cursor[key]
    cursor[path[-1]]=value
    with pytest.raises(ValueError):loads_report(dumps_report(report))


@pytest.mark.parametrize('name',[
    'offered','credits','useful_bits','priority_numerator','priority_denominator','priority_score','refused_actions',
    'expired_requests','executed_point_seconds','minimum_energy_wh','end_energy_wh','maximum_temperature_k','sums'])
def test_every_summary_total_is_derived_from_rows(name):
    report=original_report();totals=report['totals']
    if name=='maximum_temperature_k':totals[name]['bus']+=1
    elif name=='sums':totals[name]['wire_loss_wh']=['1','1']
    else:totals[name]+=1
    with pytest.raises(ValueError):loads_report(dumps_report(report))


@pytest.mark.parametrize('mutation',[
    'gap','overlap','reorder','bucket','seal','terminal_seal','cross_bucket','receipt_outside','receipt_at_wrong_boundary',
    'duplicate_offer','duplicate_receipt','reused_custody','credited_expired','weight_disagreement','mixed_thermal',
    'negative_sum','energy_extrema','expired_type','unknown_row_field','missing_row_field','soc_extrema','wear_direction'])
def test_structural_calendar_events_and_returned_resource_admission(mutation):
    report=original_report();a,b=report['rows']
    if mutation=='gap':b['start_seconds']=201
    elif mutation=='overlap':b['start_seconds']=199
    elif mutation=='reorder':report['rows'].reverse()
    elif mutation=='bucket':a['bucket']=1
    elif mutation=='seal':a['seal']='PARTIAL_TERMINAL'
    elif mutation=='terminal_seal':b['seal']=None
    elif mutation=='cross_bucket':a['end_seconds']=201
    elif mutation=='receipt_outside':a['credits'][0]['completion_time']=['201','1']
    elif mutation=='receipt_at_wrong_boundary':a['credits'][0]['completion_time']=['200','1']
    elif mutation=='duplicate_offer':a['offered'].append(deepcopy(a['offered'][0]))
    elif mutation=='duplicate_receipt':b['credits'][0]['request_id']=a['credits'][0]['request_id']
    elif mutation=='reused_custody':b['credits'][0]['record_ids']=a['credits'][0]['record_ids'][:]
    elif mutation=='credited_expired':b['expired']=[a['credits'][0]['request_id']]
    elif mutation=='weight_disagreement':
        a['credits'][0]['priority']=3.0;a['priority_numerator']=3.0
        report['totals']['priority_numerator']=4.0;report['totals']['priority_score']=4/6
    elif mutation=='mixed_thermal':b['maximum_temperature_k']['other']=300.0
    elif mutation=='negative_sum':a['sums']['wire_loss_wh']=['-1','1']
    elif mutation=='energy_extrema':a['minimum_energy_wh']=a['end_energy_wh']+1
    elif mutation=='expired_type':b['expired']=[True]
    elif mutation=='unknown_row_field':a['unreviewed']=0
    elif mutation=='missing_row_field':del a['wear_end']
    elif mutation=='soc_extrema':a['soc']['minimum_returned']=1.0
    elif mutation=='wear_direction':a['wear_end']['battery']['usable_capacity_retention']=1.0
    with pytest.raises((ValueError,TypeError)):loads_report(dumps_report(report))


@pytest.mark.parametrize('mutation',[
    'cursor','physical_cursor','offered_ledger','expired_ledger','receipt_ledger','duplicate_action','active_shape',
    'unsealed_history','outer_coverage','boolean_counter','reservation','negative_detail','unknown_field'])
def test_report_state_cursor_dedup_active_rows_and_paid_counters(mutation):
    state=original_state()
    if mutation=='cursor':state['cursor']=14;state['seen_actions'].pop()
    elif mutation=='physical_cursor':state['base_cursor']=50
    elif mutation=='offered_ledger':state['seen_offered'].pop()
    elif mutation=='expired_ledger':state['seen_expired'].clear()
    elif mutation=='receipt_ledger':state['seen_receipts'][0]='other-request'
    elif mutation=='duplicate_action':state['seen_actions'][1]=state['seen_actions'][0]
    elif mutation=='active_shape':state['status']='ACTIVE'
    elif mutation=='unsealed_history':state['sealed'][0]['seal']=None
    elif mutation=='outer_coverage':state['end_seconds']=729
    elif mutation=='boolean_counter':state['control_units']=True
    elif mutation=='reservation':state['control_reserved_units']+=1
    elif mutation=='negative_detail':state['detail_bytes']=-1
    elif mutation=='unknown_field':state['unreviewed']=0
    with pytest.raises((ValueError,TypeError)):loads_report(dumps_report(state))


@pytest.mark.parametrize(('path','value'),[
    (('status',),'UNKNOWN'),(('root_identity',),'G'*64),(('coverage',),'MONTH_QUALIFIED'),
    (('period_seconds',),True),(('epoch_offset_seconds',),1.5),(('control_units',),True),
    (('totals','priority_score'),float('inf')),(('totals','maximum_temperature_k','battery'),float('nan'))])
def test_summary_exact_metadata_types_and_finite_values(path,value):
    report=original_report();cursor=report
    for key in path[:-1]:cursor=cursor[key]
    cursor[path[-1]]=value
    with pytest.raises((ValueError,TypeError)):validate_summary(report)


def test_carried_in_window_credit_keeps_common_mission_denominator():
    report=original_report();row=report['rows'][1]
    report.update(start_seconds=200,rows=[row],control_units=16160,control_reserved_units=8388608)
    report['totals'].update(offered=0,credits=1,useful_bits=12288.0,priority_numerator=1.0,priority_score=1/6,
        executed_point_seconds=0,minimum_energy_wh=row['minimum_energy_wh'],sums=deepcopy(row['sums']))
    assert loads_report(dumps_report(report))==report


def test_root_bound_restore_rejects_internally_consistent_weight_or_population_substitution():
    report=MissionReport(make_inputs(wire='weakness'))
    bad=deepcopy(report.state);bad['current']['priority_denominator']*=2
    validate_state(bad)
    with pytest.raises(ValueError,match='denominator'):MissionReport(report.root,state=bad)
    if report.state['seen_offered']:
        bad=deepcopy(report.state);bad['current']['offered'].pop();bad['seen_offered'].pop()
        validate_state(bad)
        with pytest.raises(ValueError,match='offered'):MissionReport(report.root,state=bad)


def test_finish_retains_zero_action_initial_boundary_and_declared_offers():
    report=MissionReport(make_inputs(wire='weakness'));offered=deepcopy(report.state['current']['offered'])
    result=report.finish()
    assert result['status']=='COMPLETE' and len(result['rows'])==1
    assert result['rows'][0]['offered']==offered and result['totals']['credits']==0
    assert loads_report(dumps_report(result))==result
    assert loads_report(dumps_report(report.state))==report.state


def test_failed_consume_keeps_published_state_and_external_references_unchanged(monkeypatch):
    # SYNTHETIC_ADMISSION: no physical executor or scientific transition is run.
    report=MissionReport(make_inputs(wire='weakness'));published=report.state;raw=dumps_report(published)
    clock=published['end_seconds'];context=report.root.initial_checkpoint.restore(report.root.model.simulation_inputs)
    outcome=SimpleNamespace(action_id='synthetic-atomic',start_seconds=clock,end_seconds=clock+1,kind='HOLD',
        status='completed',cuts=(),contact_outcomes=(),reason=None)
    state=SimpleNamespace(root=report.root,physical=SimpleNamespace(cursor=1,outcomes=(outcome,),context=context,acquisitions=()))
    monkeypatch.setattr(report_owner,'_scientific',lambda value:value)
    monkeypatch.setattr(report_owner,'_plain_output',lambda value:dict(cuts=[dict(part={})],contact_forcing=[]))
    def injected_late_error(row,part):
        row['end_energy_wh']=123.0
        raise RuntimeError('EXPECTED_INJECTED_REPORT_PART_FAILURE')
    monkeypatch.setattr(report,'_part',injected_late_error)
    with pytest.raises(RuntimeError,match='EXPECTED_INJECTED'):report.consume(state)
    assert report.state is published and dumps_report(published)==raw


def test_failed_finish_keeps_published_state_and_external_references_unchanged(monkeypatch):
    report=MissionReport(make_inputs(wire='weakness'));published=report.state;raw=dumps_report(published)
    def injected_summary_failure(candidate):raise RuntimeError('EXPECTED_INJECTED_REPORT_SUMMARY_FAILURE')
    monkeypatch.setattr(report,'_summary',injected_summary_failure)
    with pytest.raises(RuntimeError,match='EXPECTED_INJECTED'):report.finish()
    assert report.state is published and dumps_report(published)==raw

# Exact immutable B51 primary report; copied as data, without a mission rerun.
ORIGINAL_B51_REPORT_RAW = br'''{"control_reserved_units":15728640,"control_units":28992,"coordinator_history":"FULL_SHORT_PREFIX_RETAINED_SEPARATELY","coverage":"SHORT_SYNTHETIC_DEMO_NOT_MONTH_PHYSICAL_SIMULATION","end_seconds":728,"epoch_offset_seconds":2591800,"extrema_scope":"RETURNED_STATES_NOT_CONTINUOUS_EXTREMA","method":"B51_INCREMENTAL_RETURNED_STATE_REPORT_V1","month_semantics":"FIXED_30_DAY_BUCKET_NOT_GREGORIAN","period_seconds":2592000,"root_identity":"d7d05260493389236fa920689083ae85daf6e0f6c421003658c16a8b23a41fb7","rows":[{"actions":7,"bucket":0,"credits":[{"completion_time":["24036","125"],"priority":2.0,"record_ids":["b44.b47-command-1"],"request_id":"b47-medium","useful_bits":12288.0}],"credits_count":1,"delivered_useful_bits":12288.0,"end_energy_wh":80.20334858932975,"end_seconds":200,"executed_point_seconds":8,"expired":[],"maximum_temperature_k":{"battery":300.08271550667695,"bus":300.1584161289089,"payload":300.1023082042878},"minimum_energy_wh":79.99527130026232,"offered":[{"id":"b47-urgent","priority":3.0},{"id":"b47-medium","priority":2.0},{"id":"b47-low","priority":1.0}],"priority_denominator":6.0,"priority_numerator":2.0,"refused_actions":0,"seal":"MONTH_BOUNDARY","soc":{"end_returned":0.8912242184954583,"minimum_returned":0.8888397781852462,"scope":"DERIVED_RETURNED_ENERGY_OVER_RETURNED_CAPACITY_NOT_CONTINUOUS"},"start_seconds":128,"sums":{"actuator_energy_wh":["39855150145746125264338426201","8913168282854737979273694412800"],"conversion_loss_wh":["246492458827326689","9223372036854775808"],"generation_wh":["107389145998125088462597313463119","285221385051351615336758221209600"],"requested_load_wh":["10692430066115070350038757985061937","73016674573146013526210104629657600"],"served_load_wh":["10692430066115070350038757985061937","73016674573146013526210104629657600"],"throughput_wh":["4240937152098714893","18446744073709551616"],"unmet_load_wh":["0","1"],"wire_loss_wh":["1277462808787922225432079958276825439","299076299051606071403356588563077529600"]},"wear_end":{"battery":{"cumulative_energy_throughput_wh":0.22990166368399573,"usable_capacity_retention":0.8999233517770305},"solar":{"generation_retention":0.7999928000000002}},"wear_start":{"battery":{"cumulative_energy_throughput_wh":0.0,"usable_capacity_retention":0.9},"solar":{"generation_retention":0.8}}},{"actions":8,"bucket":1,"credits":[{"completion_time":["38072","125"],"priority":1.0,"record_ids":["b44.b47-command-2"],"request_id":"b47-low","useful_bits":12288.0}],"credits_count":1,"delivered_useful_bits":12288.0,"end_energy_wh":82.53772301955252,"end_seconds":728,"executed_point_seconds":0,"expired":["b47-urgent"],"maximum_temperature_k":{"battery":300.7527571100349,"bus":300.8900034327669,"payload":300.5160888519118},"minimum_energy_wh":80.20334858932975,"offered":[],"priority_denominator":6.0,"priority_numerator":1.0,"refused_actions":0,"seal":"PARTIAL_TERMINAL","soc":{"end_returned":0.9177537673312968,"minimum_returned":0.8912242184954583,"scope":"DERIVED_RETURNED_ENERGY_OVER_RETURNED_CAPACITY_NOT_CONTINUOUS"},"start_seconds":200,"sums":{"actuator_energy_wh":["0","1"],"conversion_loss_wh":["4784623076281144521","18446744073709551616"],"generation_wh":["275715402841376369867597690063047","95073795017117205112252740403200"],"requested_load_wh":["1118123796695161879496573804346029","3650833728657300676310505231482880"],"served_load_wh":["1118123796695161879496573804346029","3650833728657300676310505231482880"],"throughput_wh":["1345675240204072193","576460752303423488"],"unmet_load_wh":["0","1"],"wire_loss_wh":["2627165317736649710323747076501273","146033349146292027052420209259315200"]},"wear_end":{"battery":{"cumulative_energy_throughput_wh":2.5642760939067286,"usable_capacity_retention":0.8993449654754455},"solar":{"generation_retention":0.7999400000000004}},"wear_start":{"battery":{"cumulative_energy_throughput_wh":0.22990166368399573,"usable_capacity_retention":0.8999233517770305},"solar":{"generation_retention":0.7999928000000002}}}],"start_seconds":128,"status":"COMPLETE","totals":{"credits":2,"end_energy_wh":82.53772301955252,"executed_point_seconds":8,"expired_requests":1,"maximum_temperature_k":{"battery":300.7527571100349,"bus":300.8900034327669,"payload":300.5160888519118},"minimum_energy_wh":79.99527130026232,"offered":3,"priority_denominator":6.0,"priority_numerator":3.0,"priority_score":0.5,"refused_actions":0,"sums":{"actuator_energy_wh":["39855150145746125264338426201","8913168282854737979273694412800"],"conversion_loss_wh":["5277607993935797899","18446744073709551616"],"generation_wh":["46726767726112709903269519182613","14261069252567580766837911060480"],"requested_load_wh":["3672767333335367548885581563553613","8112963841460668169578900514406400"],"served_load_wh":["3672767333335367548885581563553613","8112963841460668169578900514406400"],"throughput_wh":["47302544838629025069","18446744073709551616"],"unmet_load_wh":["0","1"],"wire_loss_wh":["739766375501397870241679330105714727","33230699894622896822595176507008614400"]},"useful_bits":24576.0}}'''
