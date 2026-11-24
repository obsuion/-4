"""B56 onboard autonomous intent selection; forecast receives only observations.

Pending paid science is finished rather than erased/preempted. New solar intents
have no ground request/ACK/credit. A hold keeps the inertial quaternion fixed.
Only cadence-bound paid model-Sun queries may request another paid turn.
"""
from dataclasses import replace
from fractions import Fraction as Q
from math import degrees
from .solar_attitude import (EnergyAttitudePolicy,SolarAction,SolarAttitudeState,
    SolarTarget,SolarSpatialSlew,paid_sun_target,panel_axis,METHOD)
from .assembly_attitude import angle_between
from .eps_capability import compute_eps_capability

COUNTERS=('point_attempts','point_completions','point_refusals')
QUANTITIES=('paid_point_seconds','actuator_requested_wh','charge_hold_seconds','positive_charge_hold_seconds')

def initial_solar_state(policy,clock):return SolarAttitudeState(policy.identity,Q(clock))

def guard_solar_physical(state):
    p=state.inputs.energy_attitude_policy;s=state.solar_state
    if p is None:
        if s is not None:raise ValueError('solar state requires explicit energy-attitude policy')
        return
    if type(p) is not EnergyAttitudePolicy or type(s) is not SolarAttitudeState:raise TypeError('exact solar policy/state')
    p.__post_init__();s.__post_init__()
    if s.policy_identity!=p.identity or s.clock_seconds!=state.context.simulation_time_seconds:raise ValueError('solar policy/state clock binding')
    from .rolling_physics import digest
    from .lifecycle_orbit import _identity
    from .lifecycle_world import API
    def target_guard(t):
        if t is None:return
        if type(t) is not SolarTarget:raise TypeError('exact solar target')
        t.__post_init__()
        if t.frame!=state.attitude.inertial_frame or t.epoch_identity!=digest(state.inputs.environment.trajectory.initial_state.position.instant.epoch):raise ValueError('foreign solar frame/epoch')
        if t.world_identity!=_identity((API,state.inputs.environment,t.role)):raise ValueError('foreign solar world')
        if state.nominal_provider.role=='ACTUAL' and t.role!='ACTUAL':raise ValueError('forecast target cannot become actual authority')
    target_guard(s.held_target)
    pending=state.pending
    if pending is not None and type(pending.action) is SolarAction:
        pending.action.__post_init__()
        if pending.action.policy_identity!=p.identity:raise ValueError('pending solar policy changed')
        if pending.kind=='SOLAR_POINT':
            target_guard(pending.solar_target)
            if pending.solar_target is None or pending.solar_target.clock_seconds!=pending.origin_seconds:raise ValueError('pending Sun target origin')
            if type(pending.slew) is not SolarSpatialSlew or pending.slew.hardware!=state.harness.hardware:raise ValueError('exact solar plan/hardware authority')
            if pending.slew.commanded_body_axis!=panel_axis(state.harness.hardware):raise ValueError('solar slew did not command actual panel axis')

def select_solar_action(physical,cut,action_id):
    """Reads actual onboard resources OR an isolated forecast physical state.

    Caller must never use the returned actual mode as a ground observation.
    No existing pending action is removed; the caller continues it as before.
    """
    p=physical.inputs.energy_attitude_policy
    if p is None or physical.pending is not None:return physical,None
    guard_solar_physical(physical)
    s=physical.solar_state;t=physical.context.simulation_time_seconds
    capacity=compute_eps_capability(physical.context.inputs.spacecraft_configuration.eps,physical.context.spacecraft_state.degradation).battery_usable_capacity_wh
    energy=physical.context.spacecraft_state.battery.energy_wh
    normal=physical.service_state.mode=='NORMAL' and physical.service_state.essential_serviceable
    if s.phase=='MISSION':
        if not normal or energy>p.entry_usable_fraction*capacity:return physical,None
        s=replace(s,phase='CHARGE',ordinal=s.ordinal+1,entered_at_seconds=Q(t),minimum_until_seconds=Q(t+p.minimum_dwell_seconds),next_point_check_seconds=Q(t),reason='PREVENTIVE_ENTRY_CURRENT_USABLE_CAPACITY')
    elif energy>=p.exit_usable_fraction*capacity and t>=s.minimum_until_seconds and normal:
        return replace(physical,solar_state=replace(s,phase='MISSION',reason='HIGH_RESERVE_AND_MINIMUM_DWELL_REACHED')),None
    physical=replace(physical,solar_state=s)
    if normal and energy>0 and t>=s.next_point_check_seconds:
        needs_point=s.held_target is None
        if not needs_point:
            target=paid_sun_target(physical.source_authority,t)
            angle=degrees(angle_between(physical.attitude.direction(panel_axis(physical.harness.hardware)),target.direction_inertial))
            needs_point=angle>=p.repoint_angle_deg
        if needs_point:
            return physical,SolarAction(action_id,'SOLAR_POINT',p.identity)
        s=replace(s,next_point_check_seconds=Q(t+p.repoint_interval_seconds),reason='HELD_PANEL_WITHIN_DECLARED_REPOINT_ANGLE')
    if not normal:s=replace(s,reason='PASSIVE_EXISTING_SAFE_OFF_NO_FREE_SUN_POINT')
    return replace(physical,solar_state=s),SolarAction(action_id,'SOLAR_HOLD',p.identity,until_seconds=cut)

def advance_solar_state(state,action,target,cuts,start,end,status,reason,world,policy):
    if state is None:return None
    changes=dict(clock_seconds=Q(end))
    solar=type(action) is SolarAction
    if solar and action.kind=='SOLAR_POINT':
        first=state.last_action_id!=action.action_id
        changes.update(last_action_id=action.action_id,point_attempts=state.point_attempts+int(first),paid_point_seconds=state.paid_point_seconds+Q(end-start),
            actuator_requested_wh=state.actuator_requested_wh+sum((Q(c.actuator_draw_w)*(c.end_seconds-c.start_seconds)/3600 for c in cuts),Q()))
        if status=='completed':
            if target is None:raise ValueError('completed paid Sun point lacks actual target')
            changes.update(held_target=target,point_completions=state.point_completions+1,next_point_check_seconds=Q(end+policy.repoint_interval_seconds),reason='PAID_SUN_POINT_COMPLETED')
        elif status=='refused':changes.update(point_refusals=state.point_refusals+1,next_point_check_seconds=Q(end+policy.repoint_interval_seconds),reason=str(reason))
    if solar and action.kind=='SOLAR_HOLD':
        positive=sum((c.end_seconds-c.start_seconds for c in cuts if c.part.eps_result.battery.charge_input_w>0),Q())
        changes.update(charge_hold_seconds=state.charge_hold_seconds+Q(end-start),positive_charge_hold_seconds=state.positive_charge_hold_seconds+positive)
    if cuts:
        c=cuts[-1];flags=[world._lighting.get(i,'UNAVAILABLE') for i in c.source_support_indices]
        changes.update(last_incidence_deg=float(c.incidence_angle_deg),last_illumination=flags[-1] if flags else 'UNAVAILABLE',last_support=(Q(c.start_seconds),Q(c.end_seconds)))
    result=replace(state,**changes);result.__post_init__();return result

def solar_projection(state):
    if state is None:return None
    from .lifecycle_report import pack
    from .rolling_physics import digest
    t=state.held_target
    return dict(method=METHOD,policy_identity=state.policy_identity,clock_seconds=pack(state.clock_seconds),phase=state.phase,ordinal=state.ordinal,reason=state.reason,
        entered_at_seconds=pack(state.entered_at_seconds),minimum_until_seconds=pack(state.minimum_until_seconds),next_point_check_seconds=pack(state.next_point_check_seconds),
        held_target=None if t is None else dict(role=t.role,world_identity=t.world_identity,clock_seconds=pack(t.clock_seconds),frame_identity=digest(t.frame),epoch_identity=t.epoch_identity,direction_inertial=list(t.direction_inertial),assumption=t.assumption),
        **{n:getattr(state,n) for n in COUNTERS},**{n:pack(getattr(state,n)) for n in QUANTITIES},
        last_incidence_deg=state.last_incidence_deg,last_illumination=state.last_illumination,last_support=[pack(x) for x in state.last_support],support_scope='LAST_RETURNED_SELECTED_SUPPORT_ONLY_NOT_WHOLE_HOLD_OR_CONTINUOUS')

def solar_report_blank(policy):
    return dict(method=METHOD,policy_identity=policy.identity,**{n:0 for n in COUNTERS},**{n:['0','1'] for n in QUANTITIES})

def solar_report_combine(rows):
    from .lifecycle_report import pack,unpack
    result=dict(rows[0])
    if any(r['method']!=METHOD or r['policy_identity']!=result['policy_identity'] for r in rows):raise ValueError('mixed solar report policy')
    for n in COUNTERS:result[n]=sum(r[n] for r in rows)
    for n in QUANTITIES:result[n]=pack(sum((unpack(r[n]) for r in rows),Q()))
    return result

def solar_report_delta(row,outcome):
    from .lifecycle_report import pack,unpack
    before,after=outcome.solar_state_before,outcome.solar_state_after
    if type(before) is not SolarAttitudeState or type(after) is not SolarAttitudeState:raise ValueError('solar report requires selected physical state delta')
    before.__post_init__();after.__post_init__()
    if before.policy_identity!=row['policy_identity'] or after.policy_identity!=row['policy_identity']:raise ValueError('solar report delta policy')
    for n in (*COUNTERS,*QUANTITIES):
        d=getattr(after,n)-getattr(before,n)
        if d<0:raise ValueError('solar cumulative work cannot be refunded')
        row[n]=row[n]+d if n in COUNTERS else pack(unpack(row[n])+d)

def validate_solar_report(row,policy):
    from .experiment_codec import object_fields
    from .lifecycle_report import unpack
    object_fields(row,('method','policy_identity',*COUNTERS,*QUANTITIES))
    if row['method']!=METHOD or row['policy_identity']!=policy.identity:raise ValueError('solar report binding')
    for n in COUNTERS:
        if type(row[n]) is not int or not 0<=row[n]<=2**48:raise ValueError('solar report count')
    for n in QUANTITIES:
        if unpack(row[n])<0:raise ValueError('solar report nonnegative quantity')
    if unpack(row['positive_charge_hold_seconds'])>unpack(row['charge_hold_seconds']):raise ValueError('solar charge/hold support balance')

def validate_solar_progress(value,root,clock):
    """Data-only strict progress reader; progress never grants resume authority."""
    from .experiment_codec import object_fields
    from .lifecycle_report import unpack
    from .lifecycle_contract import integer,identity
    from .rolling_physics import digest
    from .solar_attitude import SENSOR
    p=root.energy_attitude_policy
    if type(p) is not EnergyAttitudePolicy:raise ValueError('progress requires trusted caller solar root')
    object_fields(value,('policy_identity','actual','received','estimated','received_at_seconds','observed_at_seconds','knowledge_scope'))
    if value['policy_identity']!=p.identity or value['knowledge_scope']!='RECEIVED_POWERED_PACKETS_ONLY_NOT_CURRENT_ACTUAL_GROUND_ACCESS':raise ValueError('solar progress policy/knowledge scope')
    a=integer(value['observed_at_seconds'],'solar observation',root.start_seconds,clock)
    integer(value['received_at_seconds'],'solar receive',a,clock)
    names=('method','policy_identity','clock_seconds','phase','ordinal','reason','entered_at_seconds','minimum_until_seconds','next_point_check_seconds','held_target',*COUNTERS,*QUANTITIES,'last_incidence_deg','last_illumination','last_support','support_scope')
    for label in ('actual','received','estimated'):
        d=value[label]
        if d is None:
            if label!='estimated':raise ValueError('required solar observation missing')
            continue
        object_fields(d,names)
        if d['method']!=METHOD or d['policy_identity']!=p.identity or d['phase'] not in ('MISSION','CHARGE') or d['support_scope']!='LAST_RETURNED_SELECTED_SUPPORT_ONLY_NOT_WHOLE_HOLD_OR_CONTINUOUS':raise ValueError('solar progress state schema')
        t=unpack(d['clock_seconds'])
        if not root.start_seconds<=t<=clock or label=='actual' and t!=clock or label=='received' and t!=a:raise ValueError('solar displayed clock')
        integer(d['ordinal'],'solar ordinal')
        if type(d['reason']) is not str or len(d['reason'])>256:raise ValueError('solar displayed reason')
        for n in (*QUANTITIES,'entered_at_seconds','minimum_until_seconds','next_point_check_seconds'):
            if unpack(d[n])<0:raise ValueError('solar displayed nonnegative quantity')
        for n in COUNTERS:integer(d[n],n)
        if d['point_completions']+d['point_refusals']>d['point_attempts'] or unpack(d['positive_charge_hold_seconds'])>unpack(d['charge_hold_seconds']):raise ValueError('solar displayed work balance')
        angle=d['last_incidence_deg']
        from math import isfinite,hypot
        if angle is not None and (type(angle) is not float or not isfinite(angle) or not 0<=angle<=180):raise ValueError('solar displayed incidence')
        if d['last_illumination'] not in (None,'ILLUMINATED','OCCULTED','UNRESOLVED','UNAVAILABLE'):raise ValueError('solar displayed illumination')
        support=d['last_support']
        if type(support) is not list or len(support) not in (0,2) or support and not 0<=unpack(support[0])<unpack(support[1])<=t:raise ValueError('solar displayed selected support')
        target=d['held_target']
        if target is not None:
            object_fields(target,('role','world_identity','clock_seconds','frame_identity','epoch_identity','direction_inertial','assumption'))
            trajectory=root.base.model.environment.trajectory
            if target['frame_identity']!=digest(trajectory.initial_state.position.frame) or target['epoch_identity']!=digest(trajectory.initial_state.position.instant.epoch):raise ValueError('solar displayed wrong frame/epoch')
            if target['role'] not in (('ACTUAL','FORECAST') if label=='estimated' else ('ACTUAL',)) or target['assumption']!=SENSOR or not root.start_seconds<=unpack(target['clock_seconds'])<=t:raise ValueError('solar displayed target role/clock')
            identity(target['world_identity']);v=target['direction_inertial']
            if type(v) is not list or len(v)!=3 or any(type(x) not in (int,float) or not isfinite(x) for x in v) or abs(hypot(*v)-1)>2**-40:raise ValueError('solar displayed unit target')
    return value
