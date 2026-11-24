"""B55 linked causal consumer contracts; actual leaves remain unmodified."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
from types import SimpleNamespace
import pytest

from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot,LifecyclePolicy,METHOD55
from ops_sim.v5.lifecycle_execution import (start_lifecycle,step_lifecycle,
    progress_projection,scientific_projection,_select,_packet,_queue_power_feedback,
    _receive,_prune_power_requests)
from ops_sim.v5.lifecycle_service import (PowerServicePolicy,PowerServiceWork,
    initial_service_state,select_service_mode,commit_service_step)
from ops_sim.v5.lifecycle_state import (LifecycleDeferredFeedback,LifecycleIntent,
    LifecycleActiveRequest,guard_lifecycle)
from ops_sim.v5.lifecycle_report import unpack,validate_report_summary,validate_partial_report_row,LifecycleReport
from ops_sim.v5.long_mission import LongMissionAction


@pytest.fixture(scope='module')
def base():return make_inputs(wire='nominal')


def short_root(base,duration=120):
    return LifecycleRoot(base,duration,service_policy=PowerServicePolicy())


def test_actual_hold_feeds_selected_mode_report_and_progress(base):
    root=short_root(base);state=start_lifecycle(root)
    while state.status=='ACTIVE':state,event,row=step_lifecycle(state)
    assert state.status=='COMPLETE' and state.clock==root.end_seconds
    guard_lifecycle(state)
    summary=state.report.summary();service=summary['totals']['power_service']
    assert unpack(service['mode_durations_seconds']['NORMAL'])==120
    assert all(unpack(v)==0 for k,v in service['mode_durations_seconds'].items() if k!='NORMAL')
    assert service['selected_steps']==summary['totals']['physical_substeps']>0
    assert unpack(service['receiving_energy_wh']['essential_unserved_wh'])==0
    assert progress_projection(state)['power_service']['low_rate_telemetry_serviceable']
    assert not progress_projection(state)['power_service']['tx_fully_served']
    assert scientific_projection(state)['clock']==248


def test_low_rate_housekeeping_does_not_grant_high_rate_tx():
    policy=PowerServicePolicy();state=initial_service_state(Q(128))
    decision=select_service_mode(policy,state,clock_seconds=Q(128),energy_wh=80.,usable_capacity_wh=100.,stationary=True)
    state,work=commit_service_step(policy,decision,PowerServiceWork(),duration_seconds=Q(1),
        desired_normal_load_w=8.,commanded_load_w=8.,served_receiving_load_w=3.,
        essential_unserved_w=0.,essential_fully_served=True,tx_fully_served=False)
    assert state.low_rate_telemetry_serviceable and not state.tx_fully_served
    assert work.served_receiving_load_wh==Q(3,3600)


def test_stale_ground_knowledge_waits_without_reading_actual_state():
    state=SimpleNamespace(clock=1000,root=SimpleNamespace(method=METHOD55,
        policy=SimpleNamespace(maximum_observation_age_seconds=180)),
        knowledge=SimpleNamespace(observed_at_seconds=128),intents=())
    # Deliberately no physical attribute: selection must use received age only.
    assert _select(state)==(None,'',None)


def test_deferred_terminal_feedback_is_not_an_ack_until_received(base):
    state=start_lifecycle(short_root(base));action=LongMissionAction('issued','CAPTURE',state.root.base.requests[0].product.request.target_id.value,duration_seconds=1,product_id='request-0')
    state.intents=(LifecycleIntent(action,'request-0',128,128,state.physical.attitude),)
    state.physical.service_state=replace(state.physical.service_state,mode='POWER_OFF',communications_serviceable=False,
        essential_serviceable=False,last_reason='ESSENTIAL_SERVICE_UNAVAILABLE')
    outcome=SimpleNamespace(action_id='issued',kind='CAPTURE',status='refused',reason='B55_POWER_SERVICE_INTERRUPTED',end_seconds=128)
    waiting=_queue_power_feedback(state,state.physical,outcome,'request-0',telemetry=True,meaningful=True)
    assert waiting.queued==() and len(waiting.deferred_feedback)==1
    assert len(waiting.intents)==1 and waiting.work.acknowledged_commands==0
    waiting.physical.service_state=replace(waiting.physical.service_state,mode='NORMAL',communications_serviceable=True,
        essential_serviceable=True,last_reason='BOOT_COMPLETED')
    hold=SimpleNamespace(action_id='hold',kind='HOLD_UNTIL',status='completed',reason=None,end_seconds=128)
    transmitted=_queue_power_feedback(waiting,waiting.physical,hold,'',telemetry=False,meaningful=False)
    assert len(transmitted.queued)==1 and transmitted.deferred_feedback==()
    assert len(transmitted.intents)==1 and transmitted.work.acknowledged_commands==0
    packet=transmitted.queued[0]
    assert packet.command_id=='issued' and packet.command_completed_at_seconds==128
    assert packet.received_at_seconds==128+state.root.policy.latency_seconds
    assert transmitted.knowledge.ordinal==0


def test_feedback_original_completion_and_resource_observation_are_distinct(base):
    state=start_lifecycle(short_root(base));physical=state.physical
    feedback=LifecycleDeferredFeedback('issued','CONTACT','refused','B55_POWER_SERVICE_INTERRUPTED','request-0',120)
    packet=_packet(physical,state.root,1,feedback=feedback)
    assert packet.observed_at_seconds==128 and packet.command_completed_at_seconds==120
    assert packet.received_at_seconds==168
    assert packet.checkpoint.simulation_time_seconds==128


def test_partial_terminal_row_has_actual_scope_and_no_phantom_empty_tail(base):
    state=start_lifecycle(short_root(base));state,_,_=step_lifecycle(state)
    original=deepcopy(state.report.state)
    view=LifecycleReport(state.root,state.physical.context,state=state.report.state)
    copied=view.seal_partial_terminal(state.physical.context)
    assert validate_partial_report_row(state.root,copied,state.clock) is copied
    assert state.report.state==original
    row=state.report.seal_partial_terminal(state.physical.context)
    assert row['seal']=='PARTIAL_TERMINAL' and row['end_seconds']==state.clock
    assert row['start_seconds']<row['end_seconds']<state.root.end_seconds
    assert state.report.state['status']=='PARTIAL_TERMINAL'
    assert state.report.seal_partial_terminal(state.physical.context) is None
    assert state.report.summary()['coverage_status']=='ACTUAL_COVERED_PREFIX_OR_WINDOW'

def test_exact_component_power_sum_has_no_float_reassociation_refusal():
    policy=PowerServicePolicy();state=initial_service_state(Q(128))
    decision=select_service_mode(policy,state,clock_seconds=Q(128),energy_wh=80.,usable_capacity_wh=100.,stationary=True)
    commanded=Q(.1)+Q(.2)+Q(.3)
    served=Q(.1)+Q(.2)
    advanced,work=commit_service_step(policy,decision,PowerServiceWork(),duration_seconds=Q(1),
        desired_normal_load_w=commanded,commanded_load_w=commanded,
        served_receiving_load_w=served,essential_unserved_w=Q(.3),essential_fully_served=False)
    assert work.commanded_load_wh==commanded/3600
    assert work.served_receiving_load_wh==served/3600
    assert work.essential_unserved_wh==(commanded-served)/3600
    assert not advanced.essential_serviceable


@pytest.mark.parametrize('power',[True,Q(-1)])
def test_exact_receiving_power_rejects_invalid_inputs_atomically(power):
    policy=PowerServicePolicy();state=initial_service_state(Q(128));work=PowerServiceWork()
    decision=select_service_mode(policy,state,clock_seconds=Q(128),energy_wh=80.,usable_capacity_wh=100.,stationary=True)
    with pytest.raises(ValueError):
        commit_service_step(policy,decision,work,duration_seconds=Q(1),desired_normal_load_w=power,
            commanded_load_w=power,served_receiving_load_w=0.,essential_unserved_w=0.,essential_fully_served=True)
    assert state.clock_seconds==128 and work.covered_seconds==0


def test_empty_commanded_essential_request_cannot_create_survival_pass():
    policy=PowerServicePolicy();state=initial_service_state(Q(128));work=PowerServiceWork()
    decision=select_service_mode(policy,state,clock_seconds=Q(128),energy_wh=80.,usable_capacity_wh=100.,stationary=True)
    with pytest.raises(ValueError,match='positive authored essential'):
        commit_service_step(policy,decision,work,duration_seconds=Q(1),desired_normal_load_w=6.,
            commanded_load_w=0.,served_receiving_load_w=0.,essential_unserved_w=0.,essential_fully_served=True)


def test_report_cannot_reassign_actual_normal_support_to_safe(base):
    state=start_lifecycle(short_root(base));state,_,_=step_lifecycle(state)
    service=state.report.state['current']['power_service']
    normal=unpack(service['mode_durations_seconds']['NORMAL'])
    service['mode_durations_seconds']['NORMAL']=[str(normal.numerator-normal.denominator),str(normal.denominator)]
    service['mode_durations_seconds']['SAFE']=['1','1']
    with pytest.raises(ValueError,match='selected|actual'):
        guard_lifecycle(state)


def test_recovery_contact_partition_is_explicit_immutable_input():
    assert PowerServicePolicy().contact_service_chunk_seconds==1
    with pytest.raises(ValueError):PowerServicePolicy(contact_service_chunk_seconds=2)

@pytest.fixture(scope='module')
def saved_service_prefix(base):
    state=start_lifecycle(short_root(base));state,_,_=step_lifecycle(state)
    return state.root,state.clock,state.report.summary()


def test_strict_saved_service_summary_admits_actual_prefix(saved_service_prefix):
    root,clock,summary=saved_service_prefix
    assert validate_report_summary(root,summary,clock) is summary


@pytest.mark.parametrize('mutation',['unknown','unknown_mode','duration','selected_steps',
    'action_count','score','endpoint','initial_energy','reason_bool'])
def test_saved_service_summary_rejects_corruption_without_physics(saved_service_prefix,mutation):
    root,clock,summary=saved_service_prefix;value=deepcopy(summary)
    service=value['totals']['power_service']
    if mutation=='unknown':value['invented']=0
    elif mutation=='unknown_mode':service['mode_durations_seconds']['FREE_SLEEP']=['0','1']
    elif mutation=='duration':service['mode_durations_seconds']['NORMAL']=['59','1']
    elif mutation=='selected_steps':service['selected_steps']+=1
    elif mutation=='action_count':service['interrupted_actions']+=1
    elif mutation=='score':value['totals']['priority_score']=0.
    elif mutation=='endpoint':value['end_seconds']+=1
    elif mutation=='initial_energy':value['totals']['start_energy_wh']+=1
    elif mutation=='reason_bool':service['transition_reasons']['NORMAL_LOW_ENERGY']=False
    with pytest.raises((ValueError,TypeError)):
        validate_report_summary(root,value,clock)

def test_retained_moving_point_cannot_publish_command_terminal_ack(base):
    state=start_lifecycle(short_root(base))
    # SYNTHETIC bookkeeping boundary: no slew/physics result is fabricated.
    action=LongMissionAction('still-moving','POINT',state.root.base.requests[0].product.request.target_id.value)
    state.intents=(LifecycleIntent(action,'request-0',128,200,state.physical.attitude),)
    state.physical.pending=SimpleNamespace(kind='POINT',action=action)
    outcome=SimpleNamespace(action_id='still-moving',kind='POINT',status='refused',
        reason='UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY',end_seconds=128)
    result=_queue_power_feedback(state,state.physical,outcome,'request-0',telemetry=False,meaningful=True)
    assert result.queued==() and result.deferred_feedback==()
    assert result.intents==state.intents and result.physical.pending is state.physical.pending
    assert result.work.acknowledged_commands==0


def test_fractional_contact_service_support_keeps_exact_duration_and_legacy_eps_dt():
    from ops_sim.v5.lifecycle_report import _service_part,_service_row
    exact_dt=Q(1,3);physical_dt=Q(float(exact_dt));start=Q(532);end=start+exact_dt
    assert physical_dt!=exact_dt
    loads=dict(base_bus_w=2.,obc_w=0.,adcs_w=0.,payload_w=0.,
        communications_w=0.,heater_w=0.,other_w=0.)
    row=dict(power_service=_service_row(row=True));row['power_service']['audit_epoch_seconds']=128
    battery=dict(duration=dict(numerator=1,denominator=3),generation_w=3.,load_w=2.,
        unmet_load_w=0.,charge_input_w=1.,discharge_output_w=0.,curtailed_generation_w=0.,
        conversion_loss_wh=0.,start_energy_wh=10.)
    rec=dict(authoritative_end_energy_wh=10.0001,unavailable_energy_wh=0.)
    part=dict(service=dict(service_mode='NORMAL',desired_loads=loads,commanded_loads=loads,
        served_loads=loads,essential_fully_served=True,
        start_seconds=dict(numerator=start.numerator,denominator=start.denominator),
        end_seconds=dict(numerator=end.numerator,denominator=end.denominator)),
        electrical=dict(pv_wire_loss_w=0.,receiving_wire_loss_w=0.))
    nodes=[dict(node_id=dict(value='BUS'),start_temperature_k=280.,end_temperature_k=280.001)]
    _service_part(row,part,battery,rec,physical_dt,nodes)
    value=row['power_service'];audit=value['energy_audit'][0]
    assert unpack(value['mode_durations_seconds']['NORMAL'])==exact_dt
    assert unpack(value['receiving_energy_wh']['commanded_load_wh'])==Q(2)*exact_dt/3600
    assert unpack(audit['covered_seconds'])==exact_dt
    assert unpack(audit['sums']['generation_wh'])==Q(3)*physical_dt/3600
    assert unpack(audit['sums']['generation_wh'])!=Q(3)*exact_dt/3600
    damaged=deepcopy(part);damaged['service']['end_seconds']=dict(numerator=1065,denominator=2)
    before=deepcopy(row)
    with pytest.raises(ValueError,match='duration differs'):
        _service_part(row,damaged,battery,rec,physical_dt,nodes)
    assert row==before


@pytest.mark.parametrize('failure_stage',('report','final_guard'))
@pytest.mark.parametrize('adaptive',(False,True))
def test_late_coordinator_failure_keeps_prior_selected_prefix_and_paid_work(base,monkeypatch,failure_stage,adaptive):
    import ops_sim.v5.lifecycle_execution as owner
    from ops_sim.v5.checkpoint import CheckpointState
    from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes,make_bindings
    from ops_sim.v5.lifecycle_quiet import QuietIntegrationPolicy
    root=short_root(base)
    if adaptive:root=replace(root,policy=replace(root.policy,quiet_solver=QuietIntegrationPolicy()))
    state=start_lifecycle(root)
    context=CheckpointState.from_context(state.physical.context).to_dict()
    report=deepcopy(state.report.state);service=state.physical.service_state;service_work=state.physical.service_work
    lighting=deepcopy(state.actual_world.lighting_accounting())
    quiet=state.physical.quiet_work
    committed=None if quiet is None else (quiet.committed_parts,quiet.committed_seconds)
    paid=state.physical.runtime_work.physical_reserved_calls
    if failure_stage=='report':
        def fail_report(*args,**kwargs):raise RuntimeError('INJECTED_LATE_REPORT_FAILURE')
        monkeypatch.setattr(LifecycleReport,'consume',fail_report)
    else:
        original=owner.guard_lifecycle;calls=[]
        def fail_final(value):
            calls.append(value)
            if len(calls)==2:raise RuntimeError('INJECTED_LATE_FINAL_GUARD_FAILURE')
            return original(value)
        monkeypatch.setattr(owner,'guard_lifecycle',fail_final)
    with pytest.raises(RuntimeError,match='INJECTED_LATE_'):
        step_lifecycle(state)
    assert state.clock==root.start_seconds
    assert CheckpointState.from_context(state.physical.context).to_dict()==context
    assert state.report.state==report and state.physical.service_state==service and state.physical.service_work==service_work
    assert state.actual_world.lighting_accounting()==lighting
    assert state.work.transitions_reserved==1 and state.work.failed_transitions==1 and state.work.transitions_completed==0
    assert state.physical.runtime_work.physical_reserved_calls>paid
    if quiet is not None:
        assert (quiet.committed_parts,quiet.committed_seconds)==committed
        assert quiet.reserved_leaf_calls>0 and quiet.selected_parts>0
    guard_lifecycle(state)
    # A new paid-prefix checkpoint must remain serializable after the failure;
    # no numerical retry or scientific progress is performed by this assertion.
    assert checkpoint_bytes(state,make_bindings(root,state.clock))


def test_pre_release_receipt_handler_failure_restores_selected_ack_counts(base,monkeypatch):
    import ops_sim.v5.lifecycle_execution as owner
    state=start_lifecycle(short_root(base));before=state.work.acknowledged_commands
    original=owner._receive
    def injected_receipt_handler(value):
        value=original(value)
        # SYNTHETIC failure injection after a handler's selected bookkeeping.
        # No genuine packet or numerical command completion is asserted here.
        value.work.acknowledged_commands+=1
        value.work.contradicted_commands+=1
        return value
    def fail_release(value):raise RuntimeError('INJECTED_PRE_RELEASE_FAILURE')
    monkeypatch.setattr(owner,'_receive',injected_receipt_handler)
    monkeypatch.setattr(owner,'_release',fail_release)
    with pytest.raises(RuntimeError,match='INJECTED_PRE_RELEASE_FAILURE'):
        step_lifecycle(state)
    assert state.work.acknowledged_commands==before and state.work.contradicted_commands==0
    assert state.work.failed_transitions==1 and state.work.transitions_completed==0
    assert state.clock==state.root.start_seconds
    guard_lifecycle(state)


def test_late_guard_failure_cannot_evict_old_prefix_actual_or_forecast_cache(base,monkeypatch):
    import ops_sim.v5.lifecycle_execution as owner
    from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes,make_bindings
    root=short_root(base,240)
    root=replace(root,policy=replace(root.policy,latency_seconds=0,telemetry_step_seconds=60,maximum_observation_age_seconds=1))
    state=start_lifecycle(root);state,_,_=step_lifecycle(state)
    assert state.clock>root.start_seconds
    assert state.knowledge.observed_at_seconds==state.clock
    worlds=(state.actual_world,state.forecast_world)
    before=[(world.retention_floor,world.provider.retention_floor,
        set(world._lighting),set(world.provider._grid_states),set(world.provider._tails)) for world in worlds]
    original=owner.guard_lifecycle;calls=[]
    def fail_final(value):
        calls.append(value)
        if len(calls)==2:raise RuntimeError('INJECTED_FINAL_GUARD_BEFORE_RETENTION')
        return original(value)
    monkeypatch.setattr(owner,'guard_lifecycle',fail_final)
    with pytest.raises(RuntimeError,match='INJECTED_FINAL_GUARD_BEFORE_RETENTION'):
        step_lifecycle(state)
    for world,(floor,provider_floor,lighting,grid,tails) in zip(worlds,before):
        assert world.retention_floor==floor and world.provider.retention_floor==provider_floor
        assert lighting<=set(world._lighting) and grid<=set(world.provider._grid_states) and tails<=set(world.provider._tails)
    guard_lifecycle(state)
    assert checkpoint_bytes(state,make_bindings(root,state.clock))


def test_retention_admits_forecast_quota_before_actual_scope_can_evict(base):
    from ops_sim.v5.lifecycle_execution import _commit_power_retention
    state=start_lifecycle(short_root(base))
    actual=state.actual_world;forecast=state.forecast_world
    prior=(actual.controls,actual.retention_floor,actual.provider.retention_floor,
        dict(actual._lighting),dict(actual.provider._grid_states),dict(actual.provider._tails))
    # SYNTHETIC bounded quota boundary, no calculation or cache removal.
    forecast.controls=forecast.environment.max_index_control_units-63
    with pytest.raises(ValueError,match='QUOTA_BEFORE_ANY_EVICTION'):
        _commit_power_retention(state,Q(state.clock))
    assert (actual.controls,actual.retention_floor,actual.provider.retention_floor,
        actual._lighting,actual.provider._grid_states,actual.provider._tails)==prior
