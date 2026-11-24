"""B47 immutable-root adaptive coordinator with causal command publication."""
from dataclasses import dataclass, replace, asdict
from fractions import Fraction as Q
from .rolling_contract import RollingRoot, typed
from .rolling_knowledge import ReceivedKnowledge, IssuedCommand, observe_boundary, receive_boundary
from .rolling_cache import CumulativeWork, PublicCacheBank, paid_publication
from .rolling_physics import start_physical, advance_physical, digest
from .rolling_forecast import PlanningView
from .rolling_controller import select_rolling, RollingDecision
from .assembly_attitude_3d import BodyAttitude3D
from .checkpoint import CheckpointState
from .long_mission import LongMissionAction
from .long_mission_continuation import _scientific
from .long_mission_document import canonical_json


@dataclass(frozen=True, slots=True)
class CommittedCommand:
    root_identity: str
    previous_identity: str
    decision_identity: str
    knowledge_identity: str
    action: LongMissionAction
    lineage_identity: str
    decision_payload_identity: str


@dataclass(slots=True)
class RollingState:
    root: RollingRoot
    root_identity: str
    physical: object
    actual_cache: PublicCacheBank
    forecast_cache: PublicCacheBank
    work: CumulativeWork
    knowledge: ReceivedKnowledge
    queued: tuple
    decisions: tuple = ()
    command_lineage: tuple = ()
    status: str = 'ACTIVE'
    boundary_identity: str = ''
    retained_bytes_upper: int = 16*2**20
    intents: tuple = ()
    reconciliations: tuple = ()
    diagnosis: object = None


def boundary_identity(state):
    return digest((state.root_identity,CheckpointState.from_context(state.physical.context).to_dict(),
        state.physical.attitude,state.physical.commands,state.physical.outcomes,state.physical.acquisitions,
        state.physical.consumed_contacts,state.knowledge,state.queued,state.decisions,state.command_lineage,state.status,
        state.intents,state.reconciliations,state.diagnosis))


def start_rolling(root, *, work=None):
    from .command_estimation import CommandRollingRoot,CommandWork
    command=type(root) is CommandRollingRoot
    typed(root,CommandRollingRoot if command else RollingRoot)
    ledger=CommandWork if command else CumulativeWork
    paid=ledger() if work is None else work
    if type(paid) is not ledger: raise TypeError('exact method-owned aggregate ledger required')
    paid.validate(root.quotas)
    paid.admit_output_capacity(32*2**20,root.quotas)
    # Conservative complete old invocation admission before provider/physical start.
    if paid.actual_physical_reserved+root.model.limits.max_physical_substeps>root.quotas.max_actual_physical_reserved:
        raise ValueError('B47_ACTUAL_INVOCATION_ADMISSION')
    paid.charge('harness_compiles',1,root.quotas)
    context=root.initial_checkpoint.restore(root.model.simulation_inputs)
    t=context.simulation_time_seconds
    pose=BodyAttitude3D(root.model.assembly.body_frame_id,root.model.environment.trajectory.initial_state.position.frame,Q(t),root.initial_quaternion,Q(t))
    actual=PublicCacheBank(root.model,paid,root.quotas,'ACTUAL_PUBLIC_MODEL')
    forecast=PublicCacheBank(root.model,paid,root.quotas,'FORECAST_PUBLIC_MODEL')
    root_id=digest(root)
    physical=start_physical(root.model,context,pose,tuple(r.product for r in root.requests),actual,'ACTUAL_ROOT:'+root_id)
    initial=observe_boundary(physical,root.knowledge_mode,0)
    knowledge,queued=receive_boundary(ReceivedKnowledge(root.initial_estimate),(initial,),t)
    result=RollingState(root,root_id,physical,actual,forecast,paid,knowledge,queued)
    if command:
        from .mission_diagnosis import collect_diagnosis
        result.diagnosis=collect_diagnosis(result)
    result.boundary_identity=boundary_identity(result)
    return result


def planning_view(state):
    """Trusted filtering adapter. No unreleased schedule/queue contents enter view."""
    now=state.physical.context.simulation_time_seconds
    from .command_estimation import CommandRollingRoot,CommandPlanningView
    if type(state.root) is CommandRollingRoot:
        return CommandPlanningView(state.root.model,now,tuple(r for r in state.root.requests if r.release_seconds<=now),
            state.root.contacts,state.knowledge,state.root.knowledge_mode,state.root.policy,state.intents,state.reconciliations,
            state.root.estimation,state.root.controller_method)
    return PlanningView(state.root.model,now,tuple(r for r in state.root.requests if r.release_seconds<=now),
        state.root.contacts,state.knowledge,state.root.knowledge_mode,state.root.policy)


def guard_rolling(state):
    if type(state) is not RollingState: raise TypeError('adaptive state required')
    if digest(state.root)!=state.root_identity or boundary_identity(state)!=state.boundary_identity:
        raise ValueError('FOREIGN_OR_MUTATED_ADAPTIVE_ROOT_BOUNDARY')
    if len(state.decisions)!=len(state.command_lineage) or len(state.command_lineage)!=state.physical.cursor:
        raise ValueError('command/decision/physical lineage mismatch')
    parent=state.root_identity
    for item,decision,action,outcome in zip(state.command_lineage,state.decisions,state.physical.commands,state.physical.outcomes):
        payload=digest(decision)
        expected=digest((state.root_identity,parent,decision.decision_id,decision.view_identity,payload,action))
        if (item.root_identity,item.previous_identity,item.decision_identity,item.knowledge_identity,item.action,item.lineage_identity,item.decision_payload_identity)!=(state.root_identity,parent,decision.decision_id,decision.view_identity,action,expected,payload):
            raise ValueError('broken complete adaptive prefix')
        if not decision.selected_suffix or replace(decision.selected_suffix[0],action_id=action.action_id)!=action:
            raise ValueError('SELECTED_FIRST_COMMAND_SEMANTICS_MISMATCH')
        if decision.explanation=='TERMINAL_PAID_STANDBY_NO_LOOKAHEAD' and (
                len(decision.selected_suffix)!=1 or decision.forecasts or action.kind!='HOLD_UNTIL' or
                action.until_seconds!=state.root.model.environment.end_seconds or outcome.start_seconds!=action.until_seconds-1):
            raise ValueError('TERMINAL_PAID_TAIL_SEMANTICS_MISMATCH')
        parent=item.lineage_identity
    state.work.validate(state.root.quotas)
    from .command_estimation import CommandRollingRoot,CommandWork,reconcile_intents,published_intent
    if type(state.root) is CommandRollingRoot:
        if type(state.work) is not CommandWork or len(state.intents)!=len(state.command_lineage):raise ValueError('B48 intent/work ownership mismatch')
        if state.reconciliations!=reconcile_intents(state.knowledge,state.intents):raise ValueError('B48 unreceived reconciliation')
        if state.diagnosis.root_identity!=state.root_identity or state.diagnosis.boundary_commands!=len(state.command_lineage):raise ValueError('B48 diagnosis lineage mismatch')
        for i,a,d in zip(state.intents,state.physical.commands,state.decisions):
            if i.action!=a or i.model_identity!=digest(state.root.model):raise ValueError('B48 issued intent binding mismatch')
    elif state.intents or state.reconciliations or state.diagnosis is not None:
        raise ValueError('B47 reference cannot import command estimates')


def step_rolling(state):
    guard_rolling(state)
    if state.status!='ACTIVE': raise ValueError('completed/incomplete rolling owner cannot step')
    now=state.physical.context.simulation_time_seconds; end=int(state.root.model.environment.end_seconds)
    if now==end:
        state.status='COMPLETE';state.boundary_identity=boundary_identity(state);return state
    if len(state.decisions)>=state.root.policy.max_decisions:
        state.status='INCOMPLETE_DECISION_BUDGET';state.boundary_identity=boundary_identity(state);return state
    knowledge,queue=receive_boundary(state.knowledge,state.queued,now)
    state=replace(state,knowledge=knowledge,queued=queue)
    from .command_estimation import CommandRollingRoot,reconcile_intents,published_intent
    command=type(state.root) is CommandRollingRoot
    if command:state.reconciliations=reconcile_intents(knowledge,state.intents)
    view=planning_view(state)
    byte_start=state.work.publication_reencoded_bytes
    state.work.admit_output_capacity(32*2**20,state.root.quotas)
    if end-now==1:
        # End-domain completion is a positive paid safe-standby tail, not a fake
        # two-action forecast with zero-time suffix. Ordinary plans remain >=2.
        action=LongMissionAction('terminal-standby','HOLD_UNTIL',until_seconds=end)
        decision=RollingDecision(digest((view.identity,'TERMINAL_PAID_STANDBY')),view.identity,
            now-knowledge.observation.observed_at_seconds,(action,),'TERMINAL_PAID_STANDBY_NO_LOOKAHEAD',(),())
    else:
        decision=select_rolling(view,state.forecast_cache,state.work,state.root.quotas)
    if not decision.selected_suffix:
        state.status='INCOMPLETE_NO_ADMISSIBLE_SUFFIX';state.boundary_identity=boundary_identity(state);return state
    ordinal=len(state.decisions)
    selected=decision.selected_suffix[0]
    action=replace(selected,action_id='b47-command-'+str(ordinal))
    intent=published_intent(view,decision,action) if command else None
    old_rt=asdict(state.physical.runtime_work);old_cw=asdict(state.physical.construction.work);old_hw=asdict(state.physical.harness.work)
    # Admit the entire remaining old invocation ceiling before a new transaction;
    # aggregates retain all replay and forecast ownership separately.
    remaining=state.root.model.limits.max_physical_substeps-old_rt['physical_reserved_calls']
    if state.work.actual_physical_reserved+remaining>state.root.quotas.max_actual_physical_reserved:
        raise ValueError('B47_ACTUAL_ACTION_ADMISSION')
    if state.work.harness_compiles+2>state.root.quotas.max_harness_compiles:
        raise ValueError('B47_ACTUAL_HARNESS_ADMISSION')
    if state.work.construction_line_reserved+8*remaining>state.root.quotas.max_construction_line_reserved:
        raise ValueError('B47_ACTUAL_CONSTRUCTION_ADMISSION')
    try:
        private=replace(state.physical,context=CheckpointState.from_context(state.physical.context).restore(state.root.model.simulation_inputs))
        physical=advance_physical(private,action)
    finally:
        rt=asdict(state.physical.runtime_work);cw=asdict(state.physical.construction.work);hw=asdict(state.physical.harness.work)
        state.work.charge('actual_physical_reserved',rt['physical_reserved_calls']-old_rt['physical_reserved_calls'],state.root.quotas)
        state.work.charge('construction_line_reserved',cw['line_calls_reserved']-old_cw['line_calls_reserved'],state.root.quotas)
        state.work.charge('harness_compiles',hw['compilation_calls']-old_hw['compilation_calls'],state.root.quotas)
        state.work.charge('control_reserved',rt['output_control_units']-old_rt['output_control_units']+cw['control_units']-old_cw['control_units']+hw['control_reserved_units']-old_hw['control_reserved_units'],state.root.quotas)
    outcome=physical.outcomes[-1]
    parent=state.root_identity if not state.command_lineage else state.command_lineage[-1].lineage_identity
    payload=digest(decision)
    lineage_id=digest((state.root_identity,parent,decision.decision_id,decision.view_identity,payload,action))
    committed=CommittedCommand(state.root_identity,parent,decision.decision_id,decision.view_identity,action,lineage_id,payload)
    packet=observe_boundary(physical,state.root.knowledge_mode,ordinal+1,action)
    queue=(*state.queued,packet)
    if len(queue)>state.root.knowledge_mode.max_queue: raise ValueError('B47_PRIVATE_FEEDBACK_QUEUE_QUOTA')
    # Completion time is the public command boundary clock; status/resources
    # remain private until the latency boundary. Due time is declared latency.
    issued=IssuedCommand(action.action_id,action.kind,action.point_id,action.product_id,now,
        physical.context.simulation_time_seconds+state.root.knowledge_mode.latency_seconds)
    knowledge=replace(state.knowledge,issued=(*state.knowledge.issued,issued))
    knowledge,queue=receive_boundary(knowledge,queue,physical.context.simulation_time_seconds)
    result=replace(state,physical=physical,knowledge=knowledge,queued=queue,
        decisions=(*state.decisions,decision),command_lineage=(*state.command_lineage,committed))
    if command:
        from .mission_diagnosis import collect_diagnosis
        result.intents=(*state.intents,intent)
        result.reconciliations=reconcile_intents(knowledge,result.intents)
        result.work.charge('control_reserved',4096*(1+len(result.decisions)+sum(len(d.forecasts) for d in result.decisions)),result.root.quotas)
        result.diagnosis=collect_diagnosis(result)
    result.work.decisions+=1
    if physical.context.simulation_time_seconds==end: result.status='COMPLETE'
    elif physical.context.simulation_time_seconds==now and action.kind=='HOLD_UNTIL': result.status='INCOMPLETE_NO_TIME_PROGRESS'
    result.boundary_identity=boundary_identity(result)
    # All prospective quota checks occurred before physical work. Exact causal
    # publication is checked before returning the new coordinator boundary.
    # Forecast bodies were charged once by their independent owners. Charge the
    # new actual publication and selection metadata, not repeated historical
    # serialization. The derived retained-tree bound is rebuilt on replay.
    delta=dict(outcome=outcome,command=committed,packet=packet,knowledge=result.knowledge,queued=result.queued,
        checkpoint=CheckpointState.from_context(physical.context).to_dict(),status=result.status,
        selection=dict(id=decision.decision_id,view=decision.view_identity,age=decision.knowledge_age_seconds,
            suffix=decision.selected_suffix,explanation=decision.explanation,rejected=decision.rejected))
    if command:delta.update(intent=intent,reconciliations=result.reconciliations,diagnosis=result.diagnosis)
    paid_publication(delta,result.work,result.root.quotas,32*2**20)
    result.retained_bytes_upper=state.retained_bytes_upper+result.work.publication_reencoded_bytes-byte_start
    if result.retained_bytes_upper>result.root.model.limits.max_document_bytes:
        raise ValueError('B47_RETAINED_CAUSAL_OUTPUT_QUOTA')
    return result


def run_rolling(state, *, stop_after=None):
    while state.status=='ACTIVE' and (stop_after is None or len(state.decisions)<stop_after):
        state=step_rolling(state)
    return state


def scientific_projection(state):
    p=state.physical
    from .ms_product import assess_ms_product
    assessments=tuple(assess_ms_product(r.product,p.acquisitions,p.context.ground_data_delivery_state,
        tuple(c for o in p.outcomes for c in o.contact_outcomes),p.context.simulation_time_seconds) for r in state.root.requests)
    result=dict(api=state.root.api,root_identity=state.root_identity,status=state.status,
        checkpoint=CheckpointState.from_context(p.context).to_dict(),attitude=p.attitude,
        outcomes=p.outcomes,acquisitions=p.acquisitions,consumed_contacts=p.consumed_contacts,
        effective_hardware=p.harness.hardware,construction=p.construction.compilation,
        knowledge=state.knowledge,queued=state.queued,decisions=state.decisions,
        command_lineage=state.command_lineage,assessments=assessments,
        nominal_model_identity=state.actual_cache.provider.identity,
        illumination_rule='ORIGINAL_GRID_NOMINAL_HELD_SAMPLES_NO_CERTIFICATE')
    if state.intents or state.diagnosis is not None:
        result.update(command_intents=state.intents,reconciliations=state.reconciliations,diagnosis=state.diagnosis,
            estimation_method=state.root.estimation.method,controller_method=state.root.controller_method)
    return result


def scientific_bytes(state):
    return canonical_json(_scientific(scientific_projection(state))).encode('utf-8')


def work_projection(state):
    return dict(aggregate=asdict(state.work),actual_runtime=asdict(state.physical.runtime_work),
        actual_construction=asdict(state.physical.construction.work),actual_harness=asdict(state.physical.harness.work),
        actual_public_cache=state.actual_cache.accounting(),forecast_public_cache=state.forecast_cache.accounting())


def paid_scientific_bytes(state):
    guard_rolling(state)
    return paid_publication(scientific_projection(state),state.work,state.root.quotas,state.root.model.limits.max_document_bytes)
