"""Versioned chronological ACK-gated NOMINAL compact mission owners.

This deliberately distinct controller waits for received command feedback. It
uses a paid public-model catch-up from the last received state, not private
future pose or a reset initial estimate. B52 retains detailed quiet fallback;
B53 admits a separately versioned paid step-doubling owner. No B48 owner
or completed forecast tree is retained or invoked.
"""
from copy import deepcopy
from dataclasses import replace,asdict
from fractions import Fraction as Q
from hashlib import sha256
import json
from .lifecycle_contract import (LifecycleRoot,METHOD,METHOD53,METHOD55,canonical,occurrence,horizon_inputs,initial_context)
from .lifecycle_state import (LifecycleState,LifecycleWork,LifecycleObservation,LifecycleIntent,LifecycleActiveRequest,LifecycleDeferredFeedback,guard_lifecycle)
from .lifecycle_orbit import LifecycleOrbitPolicy,LifecycleOrbitProvider
from .lifecycle_world import LifecycleWorld,AcquiredLifecycleWorld,ReducedSunPolicy
from .lifecycle_physics import (LifecyclePhysicalModel,LifecyclePhysicsLimits,start_lifecycle_physical,
    execute_lifecycle_action,resume_pending_lifecycle_action,assess_lifecycle_product,retire_lifecycle_products)
from .lifecycle_report import LifecycleReport,pack
from .lifecycle_service import fresh_service_work,service_projection
from .checkpoint import CheckpointState
from .assembly_attitude_3d import BodyAttitude3D
from .long_mission import LongMissionAction,RuntimeWork
from .rolling_physics import digest
from .long_mission_continuation import _scientific
from .solar_attitude import SolarAction
from .solar_lifecycle import select_solar_action,solar_projection

def build_model(root):
    """Static immutable materialization; no orbit/physics evaluation."""
    if type(root) is not LifecycleRoot:raise TypeError('exact lifecycle root')
    old=root.base.model.environment;p=root.policy
    profile=(replace(old.profile[0],start_seconds=Q(root.start_seconds),end_seconds=Q(root.end_seconds)),)
    world=LifecycleWorld(old.trajectory,Q(root.start_seconds),Q(root.end_seconds),old.node_ids,profile,
        sun=ReducedSunPolicy() if root.reduced_sun_policy is None else root.reduced_sun_policy,
        sun_table=old.table if root.sun_mode=='BOUND_SHORT_TABLE_V1' else None,lighting_step_seconds=p.lighting_step_seconds,**({'max_index_control_units':2**48}if p.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'else {}))
    limits=LifecyclePhysicsLimits(max_interval_seconds=p.quiet_step_seconds,detailed_interval_seconds=p.detailed_step_seconds,
        contact_integration_level=p.contact_integration_level,max_active_products=p.active_requests,**(__import__(__package__+'.lifetime_admission',fromlist=['physical_overrides']).physical_overrides(root)))
    return LifecyclePhysicalModel(root.base.model,world,limits,horizon_inputs(root),quiet_policy=p.quiet_solver,service_policy=root.service_policy,energy_attitude_policy=root.energy_attitude_policy,battery_port_policy=root.battery_port_policy,environment_ageing_policy=root.environment_ageing_policy)

def orbit_policy_for(root):
    new=root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'
    return LifecycleOrbitPolicy(max_duration_seconds=root.duration_seconds,**(dict(max_queries=2**40,max_force_reservations=2**40,max_control_units=2**48)if new else {}))
def grid_identity(root):return digest((root.base.model.environment.trajectory,orbit_policy_for(root),root.policy.lighting_step_seconds,'ORIGINAL_ANCHOR_FIXED_10S'))

def _packet(physical,root,ordinal,*,outcome=None,request_id='',feedback=None):
    t=physical.context.simulation_time_seconds
    if feedback is not None:
        action_id,kind,status,reason,rid=(feedback.action_id,feedback.kind,feedback.status,feedback.reason,feedback.request_id)
    elif outcome is not None:
        action_id,kind,status,reason,rid=(outcome.action_id,outcome.kind,outcome.status,outcome.reason,request_id)
    else:action_id,kind,status,reason,rid=('','','initial',None,'')
    return LifecycleObservation(ordinal,t,t+root.policy.latency_seconds,CheckpointState.from_context(physical.context),physical.attitude,
        physical.consumed_through_seconds,action_id,kind,status,reason,rid,physical.acquisitions,physical.receipts,
        quiet_controller=physical.quiet_controller,
        service_state=physical.service_state if root.method==METHOD55 else None,
        command_completed_at_seconds=(None if feedback is None else feedback.completed_at_seconds),
        solar_state=physical.solar_state,battery_port_state=physical.battery_port_state,environment_ageing_state=physical.environment_ageing_state,
        solar_pending=physical.pending if physical.pending is not None and type(physical.pending.action) is SolarAction else None)
def start_lifecycle(root, *, execution_mode='BASELINE', backend=None, source_binding=None, backend_build=None, job_admission=None):
    from .lifecycle_backend import TYPED_SELECTIONS,current_source_binding
    if backend in TYPED_SELECTIONS:
        from .lifecycle_job_prepared import prepare_job_runtime
        from .lifecycle_typed_context import TypedBackendContext
        if type(source_binding)is not str or source_binding!=current_source_binding():raise ValueError('B64 public source binding mismatch')
        from .lifecycle_job_prepared import JobInputAdmission
        from .lifecycle_backend import canonical
        if type(job_admission)is not JobInputAdmission:raise TypeError('B64 typed start requires fresh exact input admission')
        if job_admission.build_sha256!=sha256(canonical(backend_build)).hexdigest():raise ValueError('B64 start build/admission binding')
        job=prepare_job_runtime(job_admission,root)
        try:
            context=TypedBackendContext(job,backend,source_binding,backend_build)
            with context.transaction():
                return _start_lifecycle(root,execution_mode=execution_mode,backend=backend,source_binding=source_binding,backend_build=backend_build,prepared_context=context)
        except BaseException as primary:
            try:job.close()
            except BaseException as secondary:
                try:
                    job._secondary(primary,secondary)
                except BaseException:
                    try:BaseException.add_note(primary,"B69 secondary annotator failed; original exception preserved")
                    except BaseException:pass
            raise
    if job_admission is not None:raise ValueError('foreign typed admission on legacy backend')
    return _start_lifecycle(root,execution_mode=execution_mode,backend=backend,source_binding=source_binding,backend_build=backend_build)

def _start_lifecycle(root, *, execution_mode='BASELINE', backend=None, source_binding=None, backend_build=None, prepared_context=None):
    root.__post_init__();model=build_model(root) if prepared_context is None else prepared_context.model;p=root.policy;rt=RuntimeWork();ft=RuntimeWork()
    backend_context=prepared_context
    if backend is not None and backend_context is None:
        from .lifecycle_backend import BackendContext,current_source_binding
        if type(source_binding)is not str or source_binding!=current_source_binding():raise ValueError('B63 public source binding mismatch')
        backend_context=BackendContext(root,model,backend,source_binding,backend_build)
    from .lifecycle_admission import BASELINE,COMPILED,MODES,CompiledLifecycleContext
    if type(execution_mode) is not str or execution_mode not in MODES:
        raise ValueError('explicit lifecycle wrapper execution mode')
    compiled=None
    if execution_mode==COMPILED:
        if root.method not in (METHOD53,METHOD55):raise ValueError('compiled wrapper requires an explicitly versioned quiet/recovery root')
        compiled=CompiledLifecycleContext(root,model)
    actual=LifecycleOrbitProvider(model.environment.trajectory,orbit_policy_for(root),role='ACTUAL',charge=lambda n,c:rt.charge(n,c,model.limits))
    forecast=LifecycleOrbitProvider(model.environment.trajectory,orbit_policy_for(root),role='FORECAST',charge=lambda n,c:ft.charge(n,c,model.limits))
    aw=AcquiredLifecycleWorld(model.environment,actual,charge=lambda n,c:rt.charge(n,c,model.limits))
    fw=AcquiredLifecycleWorld(model.environment,forecast,charge=lambda n,c:ft.charge(n,c,model.limits))
    ctx=initial_context(root,model.simulation_inputs)
    pose=BodyAttitude3D(model.assembly.body_frame_id,model.environment.trajectory.initial_state.position.frame,Q(root.start_seconds),root.base.initial_quaternion,Q(root.start_seconds))
    physical=start_lifecycle_physical(model,ctx,pose,(),actual,aw,runtime_work=rt,
        static_admission=None if compiled is None else compiled.actual)
    # The authored initial state is explicitly declared known; subsequent
    # observations are delayed. This is not hidden access to future truth.
    initial=replace(_packet(physical,root,0),received_at_seconds=root.start_seconds)
    state=LifecycleState(root,root.identity,model,physical,actual,forecast,aw,fw,ft,LifecycleReport(root,ctx,environment_ageing_state=physical.environment_ageing_state,prepared_runtime=None if backend_context is None else backend_context.actual),LifecycleWork(),initial,
        compiled_context=compiled)
    if p.quiet_solver is not None:
        from .lifecycle_quiet import quiet_work_for
        state.forecast_quiet_work=quiet_work_for(p.quiet_solver)
    if root.battery_port_policy is not None:
        from .battery_port import BatteryPortWork
        state.forecast_port_work=BatteryPortWork()
    if root.environment_ageing_policy is not None:
        from .environment_ageing import EnvironmentAgeingWork
        state.forecast_environment_work=EnvironmentAgeingWork()
    if backend is not None:
        from .lifecycle_backend import attach_backend
        attach_backend(state,backend,source_binding,backend_build,prepared=backend_context)
    _sync_orbit_work(state);guard_lifecycle(state)
    return state

def _sync_orbit_work(s):
    s.physical.runtime_work.nominal_force_completed=s.actual_provider.work.force_completed
    s.forecast_runtime.nominal_force_completed=s.forecast_provider.work.force_completed

def _receive(s):
    now=s.clock;ready=tuple(sorted((p for p in s.queued if p.received_at_seconds<=now),key=lambda p:(p.received_at_seconds,p.ordinal)))
    remaining=tuple(p for p in s.queued if p.received_at_seconds>now);knowledge=s.knowledge;active=list(s.active);pins=list(s.pinned_requests);intents=list(s.intents)
    for packet in ready:
        if packet.observed_at_seconds>knowledge.observed_at_seconds or (packet.observed_at_seconds==knowledge.observed_at_seconds and packet.ordinal>knowledge.ordinal):knowledge=packet
        if packet.command_status not in ('completed','refused'):continue
        matching=[i for i in intents if i.action.action_id==packet.command_id]
        if not matching:continue
        intent=matching[0]
        s.work.acknowledged_commands+=1
        if (packet.command_status!='completed' or (packet.observed_at_seconds if packet.command_completed_at_seconds is None else packet.command_completed_at_seconds)!=intent.expected_end_seconds or packet.attitude.quaternion!=intent.expected_attitude.quaternion):s.work.contradicted_commands+=1
        for j,a in enumerate(active):
            if a.released.product.request.request_id.value!=intent.request_id:continue
            phase='REFUSED' if packet.command_status=='refused' else {'POINT':'POINTED','CAPTURE':'CAPTURED','CONTACT':'CONTACTED'}.get(packet.command_kind,a.phase)
            active[j]=replace(a,phase=phase)
        for j,a in enumerate(pins):
            if a.released.product.request.request_id.value==intent.request_id:
                pins[j]=replace(a,phase='REFUSED' if packet.command_status=='refused' else 'DONE')
        intents=[i for i in intents if i.action.action_id!=packet.command_id]
    return replace(s,knowledge=knowledge,queued=remaining,active=tuple(active),pinned_requests=tuple(pins),intents=tuple(intents))

def _release(s):
    offered=[];active=list(s.active);n=s.next_occurrence
    # At most one generated item per due occurrence; there is no 15-year array.
    while n<s.root.offered_population:
        t=s.root.start_seconds+n*s.root.scenario.cadence_seconds
        if t>s.clock:break
        if len(active)+len(s.pinned_requests)>=s.root.policy.active_requests:raise ValueError('LIFECYCLE_ACTIVE_BACKLOG_ADMISSION')
        r,c=occurrence(s.root,n);s.report.offer(n,r.product.request.priority_weight,prepared_runtime=s.physical.prepared_runtime)
        active.append(LifecycleActiveRequest(n,r,c));offered.append(dict(ordinal=n,request_id=r.product.request.request_id.value,priority=r.product.request.priority_weight,release_seconds=t))
        n+=1
    physical=replace(s.physical,inputs=replace(s.physical.inputs,products=tuple(a.released.product for a in (*s.pinned_requests,*active))))
    return replace(s,active=tuple(active),next_occurrence=n,physical=physical),offered

def _estimate(s):
    """Paid catch-up of RECEIVED state only. No forecast body survives return."""
    p=s.root.policy;k=s.knowledge
    if s.clock-k.observed_at_seconds>p.maximum_observation_age_seconds:raise ValueError('LIFECYCLE_OBSERVATION_TOO_OLD')
    if s.work.forecast_transitions+1>p.max_forecast_transitions:raise ValueError('LIFECYCLE_FORECAST_QUOTA')
    s.work.forecast_invocations+=1
    ctx=k.checkpoint.restore(s.model.simulation_inputs)
    # Completed retired receipts are safe to remove only after the coordinator
    # disposition/ACK frontier. No pending record or partial transfer is dropped.
    products=tuple(a.released.product for a in (*s.pinned_requests,*s.active))
    active_ids={p.request.request_id for p in products}
    acq=tuple(e for e in k.acquisitions if e.plan.request.request_id in active_ids)
    receipts=tuple(r for r in k.receipts if r.request_id in active_ids)
    _filter_context(ctx,active_ids)
    rt=s.forecast_runtime;before=rt.physical_reserved_calls;done=rt.physical_completed_calls
    private=start_lifecycle_physical(s.model,ctx,k.attitude,products,s.forecast_provider,s.forecast_world,
        runtime_work=rt,consumed_through_seconds=k.consumed_through_seconds,acquisitions=acq,receipts=receipts,
        quiet_controller=k.quiet_controller,quiet_work=s.forecast_quiet_work,
        service_state=k.service_state,solar_state=k.solar_state,pending=k.solar_pending,
        battery_port_state=k.battery_port_state,battery_port_work=s.forecast_port_work,
        environment_ageing_state=k.environment_ageing_state,environment_ageing_work=s.forecast_environment_work,
        service_work=(None if k.service_state is None else fresh_service_work(k.service_state)),
        static_admission=None if s.compiled_context is None else s.compiled_context.forecast)
    if s.backend_context is not None:
        private.backend_context=s.backend_context;private.prepared_runtime=s.backend_context.forecast
    old_lines=private.construction.work.line_calls_reserved
    try:
        while ctx.simulation_time_seconds<s.clock:
            if s.work.forecast_transitions>=p.max_forecast_transitions:raise ValueError('LIFECYCLE_FORECAST_QUOTA')
            cut=s.clock
            action=None
            if s.root.energy_attitude_policy is not None:
                cut=min(cut,ctx.simulation_time_seconds+p.quiet_step_seconds,int(s.forecast_world.next_boundary_after(Q(ctx.simulation_time_seconds))))
                if private.pending is None:private,action=select_solar_action(private,cut,'b56-estimate-'+str(s.work.forecast_transitions))
            if private.pending is not None:private,o=resume_pending_lifecycle_action(private,stop_at_seconds=cut)
            else:
                if action is None:action=LongMissionAction('b52-estimate-'+str(s.work.forecast_invocations),'HOLD_UNTIL',until_seconds=cut)
                private,o=execute_lifecycle_action(private,action,stop_at_seconds=cut)
            s.work.forecast_transitions+=1
            solar_boundary=(type(action) is SolarAction and action.kind=='SOLAR_POINT' and private.pending is None and private.solar_state.next_point_check_seconds>ctx.simulation_time_seconds)
            if (o.status not in ('completed','partial') or o.end_seconds<=o.start_seconds) and not solar_boundary:raise ValueError('LIFECYCLE_MODEL_CATCHUP_REFUSED:'+str(o.reason))
        if s.root.energy_attitude_policy is not None:s.solar_forecast=replace(private.solar_state)
        if s.root.battery_port_policy is not None:s.battery_port_forecast=replace(private.battery_port_state)
        if s.root.environment_ageing_policy is not None:
            s.environment_forecast=replace(private.environment_ageing_state)
            s.environment_forecast_origin=(k.environment_ageing_state,Q(k.received_at_seconds))
        return private
    finally:
        s.work.forecast_physical_reserved+=rt.physical_reserved_calls-before
        s.work.forecast_physical_completed+=rt.physical_completed_calls-done
        s.work.forecast_construction_lines+=private.construction.work.line_calls_reserved-old_lines
        s.work.forecast_harness_compiles+=private.harness.work.compilation_calls
        _sync_orbit_work(s)

def _filter_context(ctx,active_ids):
    storage=ctx.spacecraft_state.data_storage
    storage.stored_records=tuple(r for r in storage.stored_records if r.imaging_request_id in active_ids)
    delivery=ctx.ground_data_delivery_state
    delivery.partial_transfers=tuple(r for r in delivery.partial_transfers if r.record_id in {a.record_id for a in storage.stored_records})
    delivery.completed_deliveries=tuple(d for d in delivery.completed_deliveries if d.record.imaging_request_id in active_ids)

def _select(s):
    now=s.clock;p=s.root.policy
    if s.intents:return None,'',None
    if s.root.method==METHOD55 and now-s.knowledge.observed_at_seconds>p.maximum_observation_age_seconds:
        # Silence is not a current actual-mode observation. Wait for a genuine
        # delayed resource packet rather than peeking at actual resources.
        return None,'',None
    eligible=[a for a in s.active if not(a.credit_reported or a.expired_reported) and a.phase in ('RELEASED','POINTED','CAPTURED')]
    if not eligible:return None,'',None
    a=eligible[0];r=a.released;rid=r.product.request.request_id.value
    if a.phase=='CAPTURED' and now<a.contact.start_seconds:return None,'',None
    if a.phase!='CAPTURED' and now+r.acquisition_duration_seconds>r.product.acquisition_end_seconds:return None,'',None
    if a.phase=='CAPTURED' and now>=a.contact.end_seconds:return None,'',None
    s.work.controller_decisions+=1
    if s.work.controller_decisions>p.max_controller_decisions:raise ValueError('LIFECYCLE_CONTROLLER_QUOTA')
    estimated=_estimate(s);pose=estimated.attitude
    if s.root.method==METHOD55 and estimated.service_state.mode!='NORMAL':return None,'',None
    # This new common controller has one explicit received-state margin gate,
    # then relies on the actual owner's electrical/operational protection.
    energy=estimated.context.spacecraft_state.battery.energy_wh
    if energy<=0:return None,'',None
    aid='b52-action-'+str(s.next_action)
    if a.phase=='RELEASED':
        from .harness_slew import plan_effective_slew
        entry=next(e for e in s.model.catalog if e.point.point_id==r.product.request.target_id)
        geometry=s.forecast_world.observations(entry,Q(now),Q(now),s.model.sampling)
        action=LongMissionAction(aid,'POINT',r.product.request.target_id.value)
        expected=pose;end=now
        if geometry[0].visible:
            before=estimated.harness.work.compilation_calls
            try:
                slew=plan_effective_slew(estimated.harness.hardware,pose,geometry[0].direction.components,
                    work=estimated.harness.work,policy=s.model.augmentation.policy)
                end=now+slew.duration_seconds
                expected=BodyAttitude3D(pose.body_frame_id,pose.inertial_frame,Q(end),slew.quaternion_at(Q(slew.duration_seconds)),Q(now+slew.rest_start_offset_seconds))
            finally:s.work.forecast_harness_compiles+=estimated.harness.work.compilation_calls-before
    elif a.phase=='POINTED':
        action=LongMissionAction(aid,'CAPTURE',r.product.request.target_id.value,duration_seconds=r.acquisition_duration_seconds,product_id=rid)
        end=now+r.acquisition_duration_seconds;expected=replace(pose,at_seconds=Q(end))
    else:
        action=LongMissionAction(aid,'CONTACT',a.contact.station_id,duration_seconds=a.contact.end_seconds-now)
        end=a.contact.end_seconds;expected=replace(pose,at_seconds=Q(end))
    _sync_orbit_work(s)
    return action,rid,LifecycleIntent(action,rid,now,end,expected)

def _next_cut(s):
    now=s.clock;p=s.root.policy;cuts=[s.root.end_seconds,now+p.quiet_step_seconds,s.report.boundary]
    cuts.append(s.root.start_seconds+((now-s.root.start_seconds)//p.telemetry_step_seconds+1)*p.telemetry_step_seconds)
    if s.next_occurrence<s.root.offered_population:cuts.append(s.root.start_seconds+s.next_occurrence*s.root.scenario.cadence_seconds)
    cuts.extend(packet.received_at_seconds for packet in s.queued)
    for a in s.active:
        cuts.extend((a.released.product.acquisition_end_seconds,a.released.product.delivery_deadline_seconds,a.contact.start_seconds,a.contact.end_seconds))
    cuts.append(int(s.actual_world.next_boundary_after(Q(now))))
    if s.root.energy_attitude_policy is not None:
        solar=s.physical.solar_state
        if solar.phase=='CHARGE':cuts.extend(int(x) for x in (solar.minimum_until_seconds,solar.next_point_check_seconds) if x>now)
    return min(t for t in cuts if t>now)

def _dispositions(s,end):
    credits=[];expired=0;active=[]
    for a in s.active:
        product=a.released.product;assessment=assess_lifecycle_product(s.physical,product)
        if assessment.status=='credited' and not a.credit_reported:
            bits=sum(e.record.stored_equivalent_bits for e in s.physical.acquisitions if e.record.record_id in assessment.credited_record_ids)
            if int(bits)!=bits:raise ValueError('integer MS useful bits expected')
            credits.append(dict(request_id=product.request.request_id.value,record_ids=[r.value for r in assessment.credited_record_ids],
                completion_time=pack(assessment.completion_time_seconds),priority=product.request.priority_weight,useful_bits=int(bits),released_at_seconds=a.released.release_seconds))
            a=replace(a,credit_reported=True)
        elif assessment.status=='expired' and not a.expired_reported and not a.credit_reported:
            expired+=1;a=replace(a,expired_reported=True,phase='EXPIRED')
        active.append(a)
    return replace(s,active=tuple(active)),credits,expired

def _queue_power_feedback(s, physical, outcome, rid, *, telemetry, meaningful):
    """Transmit only powered genuine feedback; public expiry is never an ACK.

    Unsent command metadata has no resource snapshot. On actual recovery a new
    current-resource packet carries that original command completion clock and
    its declared transmission latency. Already transmitted packets are retained.
    """
    queued=list(s.queued); deferred=list(s.deferred_feedback)
    terminal=bool(physical.pending is None and rid and outcome.kind in ('POINT','CAPTURE','CONTACT') and outcome.status in ('completed','refused'))
    if terminal and not any(f.action_id==outcome.action_id for f in deferred) and not any(
            p.command_id==outcome.action_id and p.command_status in ('completed','refused') for p in queued):
        deferred.append(LifecycleDeferredFeedback(outcome.action_id,outcome.kind,outcome.status,outcome.reason,rid,outcome.end_seconds))
    if len(deferred)>s.root.policy.active_requests:raise ValueError('B55_DEFERRED_FEEDBACK_CAPACITY')
    service=physical.service_state
    if service is None or not service.low_rate_telemetry_serviceable:
        return replace(s,deferred_feedback=tuple(deferred))
    ordinal=(s.transition_count+1)*(s.root.policy.active_requests+2)
    sent=[]
    for item in sorted(deferred,key=lambda f:(f.completed_at_seconds,f.action_id)):
        ordinal+=1;sent.append(_packet(physical,s.root,ordinal,feedback=item))
    if not sent and meaningful and outcome.status=='partial':
        ordinal+=1;sent.append(_packet(physical,s.root,ordinal,outcome=outcome,request_id=rid))
    if not sent and telemetry:
        ordinal+=1;sent.append(_packet(physical,s.root,ordinal))
    if len(queued)+len(sent)>s.root.policy.max_pending_packets:raise ValueError('LIFECYCLE_FEEDBACK_CAPACITY')
    return replace(s,queued=(*queued,*sent),deferred_feedback=())


def _prune_power_requests(s,*,defer_retention=False):
    """Sparse public retirement plus bounded unresolved causal/custody pins.

    One global issued intent permits at most one command pin. Public deadline
    disposition releases the active backlog even if that intent has no ACK.
    Physical products/custody and feedback are retained until genuine received
    reconciliation makes their retirement safe. Nothing here fabricates ACKs.
    """
    physical=s.physical;active=[];pins=[];retired_ids=[];discarded_count=0;new_retired=0
    old_pins={a.ordinal for a in s.pinned_requests}
    for a in sorted((*s.pinned_requests,*s.active),key=lambda a:a.ordinal):
        rid=a.released.product.request.request_id.value
        disposed=a.credit_reported or a.expired_reported
        command_pin=any(i.request_id==rid for i in s.intents)
        feedback_pin=any(p.request_id==rid and p.command_status in ('partial','completed','refused') for p in s.queued)
        deferred_pin=any(f.request_id==rid for f in s.deferred_feedback)
        if not disposed:
            active.append(a);continue
        if a.ordinal not in old_pins:new_retired+=1
        from .lifecycle_physics import pending_pins_product
        if command_pin or feedback_pin or deferred_pin or pending_pins_product(physical.pending,rid):
            pins.append(a);continue
        physical,discarded=retire_lifecycle_products(physical,(rid,),reported_through_seconds=s.clock,
            allow_discard_expired=a.expired_reported)
        discarded_count+=len(discarded);retired_ids.append(rid)
    if len(active)+len(pins)>s.root.policy.active_requests:raise ValueError('B55_SPARSE_PINNED_REQUEST_QUOTA')
    ids={a.released.product.request.request_id for a in (*pins,*active)}
    def clean(packet):
        ctx=packet.checkpoint.restore(s.model.simulation_inputs);_filter_context(ctx,ids)
        return replace(packet,checkpoint=CheckpointState.from_context(ctx),
            acquisitions=tuple(e for e in packet.acquisitions if e.plan.request.request_id in ids),
            receipts=tuple(r for r in packet.receipts if r.request_id in ids))
    s.work.retired_requests+=new_retired;s.work.known_expired_discards+=discarded_count
    if retired_ids:
        s=replace(s,knowledge=clean(s.knowledge),queued=tuple(clean(p) for p in s.queued))
    physical=replace(physical,inputs=replace(physical.inputs,products=tuple(a.released.product for a in (*pins,*active))))
    s=replace(s,physical=physical,active=tuple(active),pinned_requests=tuple(pins),
        retired_frontier=min((a.ordinal for a in active),default=s.next_occurrence))
    cutoff=s.clock-s.root.policy.maximum_observation_age_seconds
    # Stale knowledge cannot authorize _estimate and cannot pin numerical
    # history throughout an arbitrarily prolonged communication blackout.
    relevant=[p.observed_at_seconds for p in (s.knowledge,*s.queued) if p.observed_at_seconds>=cutoff]
    earliest=min([*relevant,s.clock])
    keep=max(s.root.start_seconds,min(earliest,cutoff))
    if defer_retention:return s,keep
    s.actual_world.retain_from(Q(keep));s.forecast_world.retain_from(Q(keep))
    return s


def _commit_power_retention(s,keep):
    """Admit BOTH paid retention calls before either scope can evict a seed.

    This is called only after complete candidate guards. It does not copy a
    cache or refund prior work. All ordinary domain/quota/authority refusals
    precede the first eviction; existing owners perform and charge the calls.
    """
    for world,runtime in ((s.actual_world,s.physical.runtime_work),(s.forecast_world,s.forecast_runtime)):
        seconds=Q(keep);environment=world.environment;provider=world.provider
        if not world.retention_floor<=seconds<=environment.end_seconds:
            raise ValueError('B55_RETENTION_CUTOFF_OUTSIDE_WORLD')
        cell=environment.start_seconds+int((seconds-environment.start_seconds)//environment.lighting_step_seconds)*environment.lighting_step_seconds
        floor=max(environment.start_seconds,min(cell,seconds));target=max(provider.retention_floor,floor)
        provider.validate();runtime.validate(s.model.limits)
        if not provider.retention_floor<=target<=Q(provider.anchor.instant.elapsed_seconds)+provider.policy.max_duration_seconds:
            raise ValueError('B55_RETENTION_CUTOFF_OUTSIDE_ORBIT')
        if (world.controls+64>environment.max_index_control_units or
                provider.work.control_reserved+64>provider.policy.max_control_units or
                runtime.index_control_units+64>s.model.limits.max_index_control_units or
                runtime.nominal_control_units+64>s.model.limits.max_nominal_control_units):
            raise ValueError('B55_RETENTION_QUOTA_BEFORE_ANY_EVICTION')
    s.actual_world.retain_from(Q(keep));s.forecast_world.retain_from(Q(keep))
def _prune(s):
    """Retire only a reported disposition with all issued feedback received."""
    if s.root.method==METHOD55:return _prune_power_requests(s)
    active=list(s.active);retired=s.retired_frontier;physical=s.physical
    while active:
        a=active[0];rid=a.released.product.request.request_id.value
        if not(a.credit_reported or a.expired_reported) or any(i.request_id==rid for i in s.intents) or physical.pending is not None:break
        # Any in-flight command observation is causally pinned. Quiet resource
        # packets may have old custody, but acknowledged retired IDs can be
        # canonically stripped from them without changing resource history.
        if any(p.request_id==rid and p.command_status in ('partial','completed','refused') for p in s.queued):break
        physical,discarded=retire_lifecycle_products(physical,(rid,),reported_through_seconds=s.clock,allow_discard_expired=a.expired_reported)
        if a.expired_reported:s.work.known_expired_discards+=len(discarded)
        active.pop(0);retired+=1;s.work.retired_requests+=1
    ids={a.released.product.request.request_id for a in active}
    def clean(packet):
        ctx=packet.checkpoint.restore(s.model.simulation_inputs);_filter_context(ctx,ids)
        return replace(packet,checkpoint=CheckpointState.from_context(ctx),
            acquisitions=tuple(e for e in packet.acquisitions if e.plan.request.request_id in ids),receipts=tuple(r for r in packet.receipts if r.request_id in ids))
    if retired!=s.retired_frontier:
        s=replace(s,physical=physical,active=tuple(active),retired_frontier=retired,knowledge=clean(s.knowledge),queued=tuple(clean(p) for p in s.queued))
    earliest=min([s.knowledge.observed_at_seconds,*[p.observed_at_seconds for p in s.queued],s.clock])
    keep=max(s.root.start_seconds,min(earliest,s.clock-s.root.policy.maximum_observation_age_seconds))
    s.actual_world.retain_from(Q(keep));s.forecast_world.retain_from(Q(keep))
    return s

_SELECTED_LIFECYCLE_COUNTERS=('transitions_completed','acknowledged_commands',
    'contradicted_commands','retired_requests','known_expired_discards')


def _selected_transaction_snapshot(state):
    """Small selected-frontier snapshot; no paid-work/cache copy or refund.

    Physical context/report/pose/custody already evolve in private candidates.
    The shared lighting owner and two committed quiet tallies additionally
    require transaction isolation until all causal/report guards have passed.
    Numerical/cache/allocation/control attempts remain shared and paid.
    """
    world=state.actual_world;quiet=state.physical.quiet_work
    return (tuple(getattr(state.work,name) for name in _SELECTED_LIFECYCLE_COUNTERS),
        (world._consumed_through,dict(world._light_durations),world._light_commits),
        None if quiet is None else (quiet.committed_parts,quiet.committed_seconds))


def _rollback_selected_transaction(state,snapshot):
    counters,lighting,quiet=snapshot
    for name,value in zip(_SELECTED_LIFECYCLE_COUNTERS,counters):setattr(state.work,name,value)
    state.actual_world._consumed_through=lighting[0]
    state.actual_world._light_durations=lighting[1]
    state.actual_world._light_commits=lighting[2]
    if quiet is not None:
        state.physical.quiet_work.committed_parts=quiet[0]
        state.physical.quiet_work.committed_seconds=quiet[1]


def step_lifecycle(state):
    from .lifecycle_typed_context import TypedBackendContext
    if type(state)is not LifecycleState:raise TypeError('exact lifecycle state')
    if type(state.backend_context)is TypedBackendContext:
        snapshot=_selected_transaction_snapshot(state) if state.root.method==METHOD55 else None
        try:
            with state.backend_context.transaction():return _step_lifecycle(state)
        except BaseException:
            if snapshot is not None:_rollback_selected_transaction(state,snapshot)
            raise
    return _step_lifecycle(state)

def _step_lifecycle(state):
    guard_lifecycle(state)
    if state.status!='ACTIVE' or state.clock>=state.root.end_seconds:raise ValueError('lifecycle cannot dispatch after terminal state')
    state.work.reserve_transition(state.root.policy)
    selected_snapshot=_selected_transaction_snapshot(state) if state.root.method==METHOD55 else None
    # Isolate mutable context/report/controller from published state; shared
    # numerical/cache/failed-work ledgers retain every attempted operation.
    s=replace(state,report=LifecycleReport(state.root,state.physical.context,state=state.report.state,
        prepared_runtime=state.physical.prepared_runtime))
    if state.root.method!=METHOD55:
        s=_receive(s);s,offers=_release(s);cut=_next_cut(s);rid=''
    try:
        if state.root.method==METHOD55:
            s=_receive(s);s,offers=_release(s);cut=_next_cut(s);rid=''
        if s.physical.pending is not None:
            action=s.physical.pending.action
            rid=next((i.request_id for i in s.intents if i.action.action_id==action.action_id),'')
            cut=min(cut,s.clock+s.root.policy.contact_piece_seconds) if action.kind=='CONTACT' else cut
        else:
            action=None;prediction=None
            if s.root.energy_attitude_policy is not None:
                physical,action=select_solar_action(s.physical,cut,'b56-onboard-'+str(s.next_action))
                s=replace(s,physical=physical)
            if action is None:action,rid,prediction=_select(s)
            if action is None:action=LongMissionAction('b52-action-'+str(s.next_action),'HOLD_UNTIL',until_seconds=cut)
            s=replace(s,next_action=s.next_action+1)
            if rid:
                # Prediction is explicitly unconfirmed; completed/refused actual
                # status reaches planning only through the delayed packet.
                intent=prediction
                s=replace(s,intents=(*s.intents,intent),active=tuple(replace(a,phase={'POINT':'POINT_WAIT','CAPTURE':'CAPTURE_WAIT','CONTACT':'CONTACT_WAIT'}[action.kind]) if a.released.product.request.request_id.value==rid else a for a in s.active))
            if action.kind=='CONTACT':cut=min(cut,s.clock+s.root.policy.contact_piece_seconds)
        private=replace(s.physical,context=CheckpointState.from_context(s.physical.context).restore(s.model.simulation_inputs))
        if private.pending is not None:physical,outcome=resume_pending_lifecycle_action(private,stop_at_seconds=cut)
        else:physical,outcome=execute_lifecycle_action(private,action,stop_at_seconds=cut)
        s=replace(s,physical=physical,last_outcome=outcome)
        lighting_delta=None
        if s.root.method==METHOD55:
            # Preparation pays validation work but publishes no selected time.
            # A late report/feedback/guard failure must leave the prior native
            # prefix coherent while retaining all attempted physical work.
            lighting_delta=s.actual_world.prepare_support_delta(Q(outcome.start_seconds),Q(outcome.end_seconds))
        elif s.root.method==METHOD53:
            # Fold selected ACTUAL support exactly once. Trial/forecast queries
            # never enter this duration ledger, and eviction happens only later.
            s.actual_world.consume_support(Q(outcome.start_seconds),Q(outcome.end_seconds))
        s,credits,expired=_dispositions(s,s.clock)
        carry=s.report.consume(outcome,s.physical.context,s.transition_count,credits=credits,expired=expired,
            prepared_runtime=s.physical.prepared_runtime,
            **({'lifetime_work':lifetime_work_snapshot(s)}if s.root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'else {}))
        row=None
        if s.clock==s.report.boundary:
            # Seal the covered terminal bucket exactly once. Only an actual
            # half-open endpoint credit/expiry handoff may create a tail row.
            row=s.report.seal(s.physical.context,terminal=s.clock==s.root.end_seconds,carry=carry,prepared_runtime=s.physical.prepared_runtime)
        if outcome.status=='refused' and physical.pending is not None:
            s=replace(s,status='INCOMPLETE_PENDING_PHYSICAL_REFUSAL')
        elif outcome.kind in ('HOLD_UNTIL','SOLAR_HOLD') and outcome.status=='refused' and outcome.end_seconds==outcome.start_seconds:
            # No admissible quiet evolution was committed. Repeating this same
            # boundary cannot cool the spacecraft or advance knowledge/time.
            # Retain the paid failed attempt and stop at its actual prefix.
            s=replace(s,status='INCOMPLETE_NO_PROGRESS_HOLD_REFUSAL')
        if s.root.battery_port_policy is not None and outcome.status=='refused' and type(outcome.reason)is str and outcome.reason.startswith(('BATTERY_PORT_DOMAIN_REFUSED:','UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY')):
            s=replace(s,status='INCOMPLETE_TYPED_MODEL_BOUNDARY')
        if s.root.environment_ageing_policy is not None and outcome.status=='refused' and str(outcome.reason).startswith('B61'):
            s=replace(s,status='INCOMPLETE_TYPED_MODEL_BOUNDARY')
        if s.root.battery_port_policy is not None and s.status!='ACTIVE':
            from .battery_terminal import physical_terminal
            s=replace(s,terminal=physical_terminal(outcome,s.clock))
        # Resource observations have a fixed original-anchor cadence. A quiet
        # HOLD must not create another delayed packet that then creates another
        # artificial HOLD/ACK boundary forever. Command completion and the first
        # partial-action boundary are explicit additional observation events.
        telemetry=(s.clock-s.root.start_seconds)%s.root.policy.telemetry_step_seconds==0
        meaningful=outcome.kind not in ('HOLD_UNTIL','SOLAR_HOLD') and (outcome.status!='partial' or private.pending is None)
        if s.root.method==METHOD55:
            s=_queue_power_feedback(s,physical,outcome,rid,telemetry=telemetry,meaningful=meaningful)
        else:
            queued=s.queued
            if telemetry or meaningful:
                packet=_packet(physical,s.root,s.transition_count+1,outcome=outcome,request_id=rid)
                if len(queued)+1>s.root.policy.max_pending_packets:raise ValueError('LIFECYCLE_FEEDBACK_CAPACITY')
                queued=(*queued,packet)
            s=replace(s,queued=queued)
        s=replace(s,transition_count=s.transition_count+1)
        s.work.transitions_completed+=1;s=_receive(s)
        event=dict(index=s.transition_count-1,action_id=outcome.action_id,kind=outcome.kind,status=outcome.status,reason=outcome.reason,
            start_seconds=outcome.start_seconds,end_seconds=outcome.end_seconds,request_id=rid,credits=credits,expired_count=expired,new_offers=offers,
            action_input=asdict(action),acknowledged_commands=s.work.acknowledged_commands,contradicted_commands=s.work.contradicted_commands,
            pending=None if physical.pending is None else physical.pending.kind,actual_partial_bits=[p.transmitted_equivalent_bits for p in physical.context.ground_data_delivery_state.partial_transfers])
        if getattr(outcome,'refusal_detail',None) is not None:
            event['refusal_detail']=asdict(outcome.refusal_detail)
        if s.clock==s.root.end_seconds:
            if physical.pending is not None:s.status='INCOMPLETE_ACTION_AT_HORIZON'
            else:s.status='COMPLETE'
            if s.report.state['status']=='ACTIVE':
                terminal=s.report.seal(s.physical.context,terminal=True,prepared_runtime=s.physical.prepared_runtime)
                if row is None:row=terminal
                else:event['additional_terminal_row']=terminal
        if s.root.method==METHOD55 and s.status!='ACTIVE' and s.report.state['status']=='ACTIVE':
            terminal=s.report.seal_partial_terminal(s.physical.context,prepared_runtime=s.physical.prepared_runtime)
            if terminal is not None:
                if row is None:row=terminal
                else:event['additional_terminal_row']=terminal
        if s.root.method==METHOD55:
            event['power_service']=service_projection(s.root.service_policy,physical.service_state,physical.service_work,original_start_seconds=Q(s.root.start_seconds))
            event['untransmitted_feedback']=len(s.deferred_feedback)
        if s.root.energy_attitude_policy is not None:
            event['solar_attitude']=solar_projection(physical.solar_state)
            event['intent_authority']='ONBOARD_AUTONOMOUS_PREVENTIVE_CHARGE' if type(action) is SolarAction else 'GROUND_RECEIVED_ESTIMATE' if rid else 'SCHEDULED_IDLE'
        if s.root.battery_port_policy is not None:
            from .battery_port_reporting import port_projection
            event['battery_port']=port_projection(s.root.battery_port_policy,physical.battery_port_state)
        if s.root.environment_ageing_policy is not None:
            from .environment_lifecycle import projection
            event['environment_ageing']=projection(s.root.environment_ageing_policy,physical.environment_ageing_state,s.model.simulation_inputs.spacecraft_configuration.thermal.network,prepared_runtime=physical.prepared_runtime)
        # A real endpoint tail is part of this committed event's hash. Hashing
        # before terminal handoff would leave that scientific field unbound.
        s.event_chain=sha256((s.event_chain+canonical(event)).encode()).hexdigest();s.work.event_hashes+=1
        event['chain']=s.event_chain;s.recent=(*s.recent,event)[-s.root.policy.recent_records:]
        if lighting_delta is not None:s.actual_world.commit_support_delta(lighting_delta)
        if s.root.method==METHOD55:
            s,retention_keep=_prune_power_requests(s,defer_retention=True)
        else:s=_prune(s)
        _sync_orbit_work(s);guard_lifecycle(s)
        if s.root.method==METHOD55:
            _commit_power_retention(s,retention_keep)
            _sync_orbit_work(s)
        return s,event,row
    except BaseException:
        if selected_snapshot is not None:_rollback_selected_transaction(state,selected_snapshot)
        state.work.failed_transitions+=1;_sync_orbit_work(state)
        raise

def scientific_projection(s):
    from .lifecycle_typed_context import TypedBackendContext
    if type(s.backend_context)is TypedBackendContext:
        with s.backend_context.transaction():return _scientific_projection(s)
    return _scientific_projection(s)

def _scientific_projection(s):
    """Full causally relevant bounded state; no timing/logging/store metadata."""
    p=s.physical
    work=asdict(s.work)
    for n in ('checkpoint_encoding_units','checkpoint_storage_bytes','restore_validation_units','report_control_units'):work.pop(n)
    value=dict(method=s.root.method,root_identity=s.root_identity,clock=s.clock,status=s.status,checkpoint=CheckpointState.from_context(p.context).to_dict(),
        attitude=p.attitude,pending=p.pending,acquisitions=p.acquisitions,receipts=p.receipts,consumed_through_seconds=p.consumed_through_seconds,
        physical_transitions=p.transition_count,physical_actions=p.completed_actions,reported_through_seconds=p.reported_through_seconds,
        knowledge=s.knowledge,queued=s.queued,active=s.active,intents=s.intents,next_occurrence=s.next_occurrence,retired_frontier=s.retired_frontier,
        next_action=s.next_action,event_chain=s.event_chain,work=work,actual_work=p.runtime_work,forecast_work=s.forecast_runtime,
        construction_work=p.construction.work,harness_work=p.harness.work,report=s.report.state,
        actual_orbit=s.actual_provider.to_data(),forecast_orbit=s.forecast_provider.to_data(),actual_world=s.actual_world.to_data(),forecast_world=s.forecast_world.to_data())
    if s.terminal is not None:value['terminal']=s.terminal
    if s.root.method in (METHOD53,METHOD55):
        value.update(quiet_controller=p.quiet_controller,quiet_work=p.quiet_work,forecast_quiet_work=s.forecast_quiet_work)
    if s.root.method==METHOD55:
        value.update(service_state=p.service_state,service_work=p.service_work,service_allocation_work=p.service_allocation_work,
            last_service_diagnostic=p.last_service_diagnostic,pinned_requests=s.pinned_requests,deferred_feedback=s.deferred_feedback)
    if s.root.energy_attitude_policy is not None:value.update(solar_state=p.solar_state,solar_forecast=s.solar_forecast)
    if s.root.battery_port_policy is not None:value.update(battery_port_state=p.battery_port_state,battery_port_work=p.battery_port_work,
        forecast_port_work=s.forecast_port_work,battery_port_forecast=s.battery_port_forecast)
    if s.root.environment_ageing_policy is not None:value.update(environment_ageing_state=p.environment_ageing_state,environment_ageing_work=p.environment_ageing_work,forecast_environment_work=s.forecast_environment_work,environment_forecast=s.environment_forecast,environment_forecast_origin=s.environment_forecast_origin)
    result=_scientific(value)
    if s.root.environment_ageing_policy is None:
        omitted={'ops_sim.v5.lifecycle_physics.LifecycleActionOutcome':('environment_ageing_state_before','environment_ageing_state_after'),'ops_sim.v5.lifecycle_state.LifecycleObservation':('environment_ageing_state',),
            'ops_sim.v5.lifecycle_physics.LifecyclePhysicalModel':('environment_ageing_policy',),
            'ops_sim.v5.lifecycle_service_contact.ServiceContactResult':('environment_ageing_state',)}
        todo=[result]
        while todo:
            item=todo.pop()
            if type(item)is dict:
                for name in omitted.get(item.get('record_type'),()):
                    if item['fields'].get(name,'MISSING')is not None:raise ValueError('B61 imported legacy state')
                    item['fields'].pop(name)
                todo.extend(item.values())
            elif type(item)is list:todo.extend(item)
    if s.root.battery_port_policy is None:
        omitted={'ops_sim.v5.lifecycle_state.LifecycleObservation':('battery_port_state',),
            'ops_sim.v5.lifecycle_physics.LifecyclePhysicalModel':('battery_port_policy',),
            'ops_sim.v5.lifecycle_physics.LifecycleActionOutcome':('battery_port_state_before','battery_port_state_after'),
            'ops_sim.v5.lifecycle_service_contact.ServiceContactResult':('battery_port_state',)}
        todo=[result]
        while todo:
            item=todo.pop()
            if type(item)is dict:
                for name in omitted.get(item.get('record_type'),()):
                    if item['fields'].get(name,'MISSING')is not None:raise ValueError('legacy imported port state')
                    item['fields'].pop(name)
                todo.extend(item.values())
            elif type(item)is list:todo.extend(item)

    if s.root.energy_attitude_policy is None:
        omitted={'ops_sim.v5.lifecycle_state.LifecycleObservation':('solar_state','solar_pending'),
            'ops_sim.v5.lifecycle_physics.PendingLifecycleAction':('solar_target',),
            'ops_sim.v5.lifecycle_physics.LifecyclePhysicalModel':('energy_attitude_policy',),
            'ops_sim.v5.lifecycle_physics.LifecycleActionOutcome':('solar_target','solar_state_before','solar_state_after')}
        todo=[result]
        while todo:
            item=todo.pop()
            if type(item) is dict:
                for name in omitted.get(item.get('record_type'),()):
                    if item['fields'].get(name,'MISSING') is not None:raise ValueError('legacy output imported solar state')
                    item['fields'].pop(name)
                todo.extend(item.values())
            elif type(item) is list:todo.extend(item)
    if s.root.method!=METHOD55:
        # These two optional fields did not belong to the historical B52/B53
        # observation output schema. Strip only these exact SOURCE-owned None
        # additions; never drop an arbitrary similarly named payload field.
        todo=[result];visits=0
        while todo:
            item=todo.pop();visits+=1
            if visits>2**20:raise ValueError('bounded legacy projection graph')
            if type(item) is dict:
                if item.get('record_type')=='ops_sim.v5.lifecycle_state.LifecycleObservation':
                    fields=item['fields']
                    for name in ('service_state','command_completed_at_seconds'):
                        if name not in fields or fields[name] is not None:raise ValueError('legacy observation imported recovery state')
                        fields.pop(name)
                todo.extend(item.values())
            elif type(item) is list:todo.extend(item)
    return result

def progress_projection(s):
    """Public DATA read; the native owner folds only this one frontier."""
    return progress_frontier_projection(s)


def progress_frontier_projection(s,*,resources=False):
    """One required worker read, never a capability spanning a step/publication.

    The summary and optional totals are local DATA, not a reusable memo or grant.
    A second original validate preserves BOTH logical consumers/fees and checks
    mutable report DATA again; only duplicate summary/combine/deepcopy is removed.
    Unprepared/reference consumers retain the full original fallback.
    """
    if type(resources)is not bool:raise TypeError('B71 exact resources flag')
    from .lifecycle_typed_context import TypedBackendContext
    context=s.backend_context
    if type(context)is TypedBackendContext:
        with context.transaction():
            result=_progress_projection(s,_fold=True,_resources=resources)
        return result # only after successful native finally-exit
    return _progress_projection(s,_resources=resources)


def _progress_projection(s,*,_fold=False,_resources=False):
    if type(_fold)is not bool or type(_resources)is not bool:raise TypeError('B71 exact private frontier flags')
    p=s.physical;summary=None
    if _fold:
        from .lifecycle_typed_context import TypedBackendContext
        from .lifecycle_job_prepared import _data
        context=s.backend_context
        if type(context)is not TypedBackendContext:raise ValueError('B71 admitted frontier owner required')
        context.guard(s.root,s.model)
        if (context._role(p)is not context.actual or type(s.report)is not LifecycleReport or
                s.report.root is not s.root or s.report.state['end_seconds']!=s.clock or
                s.report.state['next_transition']!=s.transition_count):
            raise ValueError('B71 foreign role/root/report/frontier')
        tx=context.job.require_transaction();report=s.report;data=report.state
        frontier=(s.clock,s.transition_count,s.root,s.model,context.source_binding)
        # Admit the complete finite local work domain BEFORE traversal,
        # encoding, copying or comparison. Same existing64MiB metadata ceiling;
        # no reduction in old logical consumer fees and no refunds.
        capacity=64*2**20
        context.job._charge(4096+32*capacity,'progress_frontiers')
        def capture(value):
            # A JSON node/key/character contributes at least one output byte.
            # Refuse oversized containers BEFORE iteration; recursion is bounded.
            # This is a local work admission, not a total heap/RSS claim.
            remaining=[capacity,capacity]
            def check(v,depth=0):
                remaining[0]-=1
                if depth>64 or remaining[0]<0:raise ValueError('B72 bounded frontier DATA nodes/depth')
                owner=type(v)
                if owner is str:
                    remaining[1]-=len(v)
                    if remaining[1]<0:raise ValueError('B72 bounded frontier DATA text')
                elif owner is int:
                    if v.bit_length()>8*capacity:raise ValueError('B72 bounded frontier integer')
                elif v is None or owner in (bool,float):pass
                elif owner is list:
                    if len(v)>remaining[0]:raise ValueError('B72 bounded frontier sequence')
                    for item in v:check(item,depth+1)
                elif owner is dict:
                    if len(v)>remaining[0]//2:raise ValueError('B72 bounded frontier mapping')
                    for key,item in v.items():
                        if type(key)is not str:raise TypeError('B72 exact frontier DATA key')
                        check(key,depth+1);check(item,depth+1)
                else:raise TypeError('B72 exact frontier DATA')
            check(value)
            return _data(value)
        snapshot=capture(data) # complete typed finite bytes, NOT a hash/cache/grant
        summary=report.summary(prepared_runtime=p.prepared_runtime)
        context._work['progress_summary_calls']+=1

    result=dict(method=s.root.method,status=s.status,clock=s.clock,start_seconds=s.root.start_seconds,end_seconds=s.root.end_seconds,
        simulated_seconds=s.clock-s.root.start_seconds,transitions=s.transition_count,actions=p.completed_actions,decisions=s.work.controller_decisions,
        offered=s.report.state['offered_frontier'],active_requests=len(s.active),queued_packets=len(s.queued),pending_intents=len(s.intents),
        pending_action=None if p.pending is None else p.pending.kind,partial_bits=[x.transmitted_equivalent_bits for x in p.context.ground_data_delivery_state.partial_transfers],
        credits=(summary if _fold else s.report.summary(prepared_runtime=s.physical.prepared_runtime))['totals']['credits'],sealed_month_rows=s.report.state['sealed_count'],
        actual_cache=s.actual_provider.accounting(),forecast_cache=s.forecast_provider.accounting(),
        actual_world=s.actual_world.accounting(),forecast_world=s.forecast_world.accounting())
    if s.root.method in (METHOD53,METHOD55):
        result['illumination']=s.actual_world.lighting_accounting()
        o=s.last_outcome
        result['last_action']=None if o is None else dict(action_id=o.action_id,kind=o.kind,status=o.status,
            reason=o.reason,refusal_detail=None if o.refusal_detail is None else asdict(o.refusal_detail))
        def work_data(work):return {n:pack(v) if type(v) is Q else v for n,v in asdict(work).items()}
        if p.quiet_work is None:result['quiet']=None
        else:
            c=p.quiet_controller
            result['quiet']=dict(method=s.root.policy.quiet_solver.method,
                controller=dict(clock_seconds=pack(c.clock_seconds),next_step_seconds=c.next_step_seconds,
                    last_step_seconds=pack(c.last_step_seconds),last_error_norm=c.last_error_norm,phase=c.phase),
                actual=work_data(p.quiet_work),forecast=work_data(s.forecast_quiet_work))
    if s.root.method==METHOD55:
        result['power_service']=service_projection(s.root.service_policy,p.service_state,p.service_work,original_start_seconds=Q(s.root.start_seconds))
        result['power_service']['pinned_requests']=len(s.pinned_requests)
        result['power_service']['deferred_feedback']=len(s.deferred_feedback)
    if s.root.energy_attitude_policy is not None:
        result['solar_attitude']=dict(policy_identity=s.root.energy_attitude_policy.identity,actual=solar_projection(p.solar_state),
            received=solar_projection(s.knowledge.solar_state),estimated=solar_projection(s.solar_forecast),received_at_seconds=s.knowledge.received_at_seconds,observed_at_seconds=s.knowledge.observed_at_seconds,
            knowledge_scope='RECEIVED_POWERED_PACKETS_ONLY_NOT_CURRENT_ACTUAL_GROUND_ACCESS')
    if s.root.battery_port_policy is not None:
        if _fold:
            report.validate(prepared_runtime=p.prepared_runtime) # original second logical consumer and exact fees
            context._work['progress_secondary_validations']+=1
        from .battery_port_reporting import port_projection
        result['battery_port']=dict(actual=port_projection(s.root.battery_port_policy,p.battery_port_state),
            received=port_projection(s.root.battery_port_policy,s.knowledge.battery_port_state),
            estimated=port_projection(s.root.battery_port_policy,s.battery_port_forecast),
            observed_at_seconds=s.knowledge.observed_at_seconds,received_at_seconds=s.knowledge.received_at_seconds,
            sampled_report=(summary if _fold else s.report.summary(prepared_runtime=s.physical.prepared_runtime))['totals']['battery_port'],knowledge_scope='RECEIVED_PACKETS_AND_PAID_CATCHUP_ONLY')
    if s.root.environment_ageing_policy is not None:
        from .environment_lifecycle import projection
        base=s.model.simulation_inputs.spacecraft_configuration.thermal.network
        forecast_prepared=None if s.backend_context is None else s.backend_context.forecast
        result['environment_ageing']=dict(actual=projection(s.root.environment_ageing_policy,p.environment_ageing_state,base,prepared_runtime=p.prepared_runtime),
            received=projection(s.root.environment_ageing_policy,s.knowledge.environment_ageing_state,base,prepared_runtime=forecast_prepared),
            estimated=projection(s.root.environment_ageing_policy,s.environment_forecast,base,prepared_runtime=forecast_prepared),observed_at_seconds=s.knowledge.observed_at_seconds,
            estimated_source=None if s.environment_forecast_origin is None else dict(state=projection(s.root.environment_ageing_policy,s.environment_forecast_origin[0],base,prepared_runtime=forecast_prepared),received_at_seconds=str(s.environment_forecast_origin[1])),
            actual_work=asdict(p.environment_ageing_work),forecast_work=asdict(s.forecast_environment_work))
    if _fold:
        tx.require_active()
        if (s.backend_context is not context or s.report is not report or report.state is not data or
                s.clock!=frontier[0] or s.transition_count!=frontier[1] or s.root is not frontier[2] or
                s.model is not frontier[3] or context.source_binding!=frontier[4] or
                capture(data)!=snapshot):raise ValueError('B71 mutable report/frontier drift')
        context._work['progress_frontiers_completed']+=1
    if _resources:
        if _fold:
            # Exact raw combine schema; summary-only fields are not raw totals.
            # Detach recursively, including nested battery/service dicts.
            totals={name:deepcopy(value)for name,value in summary['totals'].items()
                if name not in ('priority_score','priority_score_status')}
        else:
            from .lifecycle_report import combine
            data=s.report.state;totals=combine([v for v in (data['sealed_totals'],data['current'])if v is not None])
        return result,totals
    return result


def lifetime_work_snapshot(state):
    """Cumulative paid attempts, distinct actual/forecast, at returned boundary."""
    return dict(actual_environment=asdict(state.physical.environment_ageing_work),forecast_environment=asdict(state.forecast_environment_work))
