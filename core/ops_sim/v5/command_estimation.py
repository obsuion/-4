"""B48 opt-in command-following estimates. Predictions never acknowledge truth.

Only a public model, received sample, issued intents and known clock enter this
owner. A fresh paid physical invocation redoes the full-tensor slew and resource
evolution. Unsupported or contradicted histories return an explicit refusal.
"""
from dataclasses import dataclass, replace, asdict
from fractions import Fraction as Q
from .rolling_contract import RollingRoot, typed, integer
from .rolling_knowledge import ReceivedKnowledge
from .rolling_forecast import PlanningView, ForecastResult, estimated_context
from .rolling_cache import CumulativeWork, paid_publication
from .rolling_physics import digest, start_physical, advance_physical
from .long_mission import LongMissionAction
from .assembly_attitude_3d import BodyAttitude3D
from .contact_execution import ConsumedContacts

METHOD='B48_PAID_COMMAND_FOLLOWING_ESTIMATE_V1'
CONTROLLER='B48_COMMAND_INFORMED_GREEDY_FIRST_ACTION_V1'
API='M5_COMMAND_INFORMED_ROLLING_V1'


@dataclass(frozen=True, slots=True)
class EstimationPolicy:
    maximum_unreceived_intents: int = 8
    maximum_age_seconds: int = 600
    maximum_invocations: int = 512
    maximum_command_propagations: int = 4096
    assumption: str = 'UNCONFIRMED_COMMAND_FOLLOWING_NO_CERTIFIED_ERROR_BOUND'
    method: str = METHOD

    def __post_init__(self):
        for n,lo,hi in (('maximum_unreceived_intents',1,8),('maximum_age_seconds',1,600),
                        ('maximum_invocations',1,512),('maximum_command_propagations',1,4096)):
            integer(getattr(self,n),n,lo,hi)
        if type(self.method) is not str or self.method!=METHOD or type(self.assumption) is not str or self.assumption!='UNCONFIRMED_COMMAND_FOLLOWING_NO_CERTIFIED_ERROR_BOUND':
            raise ValueError('exact declared estimator method/assumption')


@dataclass(frozen=True, slots=True)
class CommandRollingRoot:
    reference: RollingRoot
    estimation: EstimationPolicy = EstimationPolicy()
    controller_method: str = CONTROLLER
    api: str = API

    def __post_init__(self):
        typed(self.reference,RollingRoot);typed(self.estimation,EstimationPolicy)
        if type(self.api) is not str or self.api!=API or type(self.controller_method) is not str or self.controller_method!=CONTROLLER:
            raise ValueError('exact opt-in command root identities')

    def __getattr__(self,name):
        if name in RollingRoot.__dataclass_fields__ and name!='api':return getattr(self.reference,name)
        raise AttributeError(name)


@dataclass(frozen=True, slots=True)
class CommandIntent:
    command_id: str
    model_identity: str
    action: LongMissionAction
    issued_at_seconds: int
    expected_end_seconds: int
    expected_attitude: BodyAttitude3D
    profile_identity: str
    prediction_status: str = 'ASSUMED_COMPLETED_NOT_ACKNOWLEDGED'

    def __post_init__(self):
        typed(self.action,LongMissionAction);typed(self.expected_attitude,BodyAttitude3D)
        integer(self.issued_at_seconds,'intent start');integer(self.expected_end_seconds,'intent end')
        if self.expected_end_seconds<self.issued_at_seconds or self.expected_attitude.at_seconds!=self.expected_end_seconds:
            raise ValueError('intent profile time binding')
        if type(self.command_id) is not str or self.action.action_id!=self.command_id or type(self.prediction_status) is not str or self.prediction_status!='ASSUMED_COMPLETED_NOT_ACKNOWLEDGED':
            raise ValueError('explicit unconfirmed intent')
        for s in (self.model_identity,self.profile_identity):
            if type(s) is not str or len(s)!=64 or any(c not in '0123456789abcdef' for c in s):raise ValueError('intent exact model/profile digest')


@dataclass(frozen=True, slots=True)
class Reconciliation:
    command_id: str
    packet_id: str
    observed_at_seconds: int
    received_at_seconds: int
    observed_status: str
    observed_reason: str | None
    conclusion: str
    expected_end_seconds: int
    observed_end_seconds: int
    pose_exactly_matches_prediction: bool

    def __post_init__(self):
        for v in (self.command_id,self.packet_id,self.observed_status,self.conclusion):
            if type(v) is not str or not v:raise ValueError('exact reconciliation text')
        if self.observed_status not in ('completed','refused') or self.conclusion not in ('CONFIRMED_BOUNDARY','CONTRADICTED_REBASE_FROM_RECEIVED'):raise ValueError('reconciliation status')
        for n in ('observed_at_seconds','received_at_seconds','expected_end_seconds','observed_end_seconds'):integer(getattr(self,n),n)
        if not self.observed_at_seconds<=self.received_at_seconds<=self.observed_at_seconds+120 or self.observed_end_seconds!=self.observed_at_seconds:raise ValueError('received reconciliation time')
        if type(self.observed_reason) not in (str,type(None)) or type(self.pose_exactly_matches_prediction) is not bool:raise ValueError('reconciliation exact reason/pose status')


def reconcile_intents(knowledge,intents):
    """Only already received command feedback; never private future packets."""
    typed(knowledge,ReceivedKnowledge)
    index={i.command_id:i for i in intents};rows=[]
    for p in knowledge.received:
        if p.command_id in index:
            i=index[p.command_id]
            equal=p.attitude.quaternion==i.expected_attitude.quaternion
            matches=p.command_status=='completed' and p.observed_at_seconds==i.expected_end_seconds and equal
            rows.append(Reconciliation(i.command_id,p.packet_id,p.observed_at_seconds,p.received_at_seconds,
                p.command_status,p.command_reason,'CONFIRMED_BOUNDARY' if matches else 'CONTRADICTED_REBASE_FROM_RECEIVED',
                i.expected_end_seconds,p.observed_at_seconds,equal))
    return tuple(rows)


@dataclass(slots=True)
class CommandWork(CumulativeWork):
    estimator_invocations: int = 0
    estimator_command_propagations_reserved: int = 0
    estimator_command_propagations_completed: int = 0
    estimator_method: str = METHOD

    def validate(self,quotas):
        CumulativeWork.validate(self,quotas)
        integer(self.estimator_invocations,'estimator invocations',0,512)
        integer(self.estimator_command_propagations_reserved,'estimator reserved intents',0,4096)
        integer(self.estimator_command_propagations_completed,'estimator completed intents',0,self.estimator_command_propagations_reserved)
        if type(self.estimator_method) is not str or self.estimator_method!=METHOD:raise ValueError('foreign estimator ledger')

    def reserve_estimation(self,model,quotas,policy,count):
        self.validate(quotas);typed(policy,EstimationPolicy);integer(count,'pending propagation count',0,policy.maximum_unreceived_intents)
        if self.estimator_invocations+1>policy.maximum_invocations or self.estimator_command_propagations_reserved+count>policy.maximum_command_propagations:
            raise ValueError('B48_ESTIMATOR_RECONSTRUCTION_OR_BRANCH_ADMISSION')
        if self.harness_compiles+2*count>quotas.max_harness_compiles:
            raise ValueError('B48_ESTIMATOR_HARNESS_ADMISSION')
        self.charge('harness_compiles',2*count,quotas)
        self.charge('control_reserved',(count+1)*2**20,quotas)
        self.estimator_invocations+=1;self.estimator_command_propagations_reserved+=count


@dataclass(frozen=True, slots=True)
class CommandPlanningView(PlanningView):
    intents: tuple = ()
    reconciliations: tuple = ()
    estimation: EstimationPolicy = EstimationPolicy()
    controller_method: str = CONTROLLER

    def __post_init__(self):
        PlanningView.__post_init__(self);typed(self.estimation,EstimationPolicy)
        if self.controller_method!=CONTROLLER or type(self.controller_method) is not str:raise ValueError('command consumer identity')
        if type(self.intents) is not tuple or len(self.intents)>64 or type(self.reconciliations) is not tuple or len(self.reconciliations)>128:raise ValueError('bounded intent/reconciliation histories')
        issued={i.command_id:i for i in self.knowledge.issued}
        if len({i.command_id for i in self.intents})!=len(self.intents):raise ValueError('duplicate intent')
        for i in self.intents:
            typed(i,CommandIntent)
            if i.command_id not in issued or i.model_identity!=digest(self.model) or i.issued_at_seconds>self.now_seconds:raise ValueError('foreign/future intent')
            c=issued[i.command_id]
            if (i.action.kind,i.action.point_id,i.action.product_id,i.issued_at_seconds)!=(c.kind,c.point_id,c.product_id,c.issued_at_seconds):raise ValueError('issued-intent semantic mismatch')
            if i.expected_attitude.body_frame_id!=self.model.assembly.body_frame_id or i.expected_attitude.inertial_frame!=self.model.environment.trajectory.initial_state.position.frame or i.expected_end_seconds>self.model.environment.end_seconds:raise ValueError('intent foreign frame/profile domain')
        for r in self.reconciliations:typed(r,Reconciliation)
        if self.reconciliations!=reconcile_intents(self.knowledge,self.intents):raise ValueError('unreceived/forged reconciliation')
        if self.now_seconds-self.knowledge.observation.observed_at_seconds>self.estimation.maximum_age_seconds:raise ValueError('B48_STALE_ESTIMATE')

    def propagation_intents(self):
        p=self.knowledge.observation;ack=self.knowledge.acknowledged_ids()
        return tuple(i for i in self.intents if i.command_id not in ack and i.issued_at_seconds>=p.observed_at_seconds)

    def point_assumption_ready(self):
        pending=tuple(c for c in self.knowledge.pending() if c.kind=='POINT')
        intents={i.command_id:i for i in self.intents}
        return all(c.command_id in intents and intents[c.command_id].expected_end_seconds<=self.now_seconds for c in pending)


@dataclass(frozen=True, slots=True)
class EstimatedCommandState:
    method: str
    view_identity: str
    model_identity: str
    source_packet_id: str
    observed_at_seconds: int
    received_at_seconds: int
    estimated_at_seconds: int
    observation_age_seconds: int
    assumption: str
    command_ids: tuple
    status: str
    reason: str | None
    attitude: BodyAttitude3D
    energy_wh: float
    temperatures_k: tuple
    expected_records: tuple
    expected_partial_bits: tuple
    expected_receipts: tuple
    propagation_outcomes: tuple
    runtime_work: object
    construction_work: object
    harness_work: object


@dataclass(frozen=True, slots=True)
class CommandForecastResult(ForecastResult):
    estimate: EstimatedCommandState | None = None


def forecast_command_suffix(view,suffix,cache,work,quotas):
    if type(view) is not CommandPlanningView or type(work) is not CommandWork or type(suffix) is not tuple or not 2<=len(suffix)<=view.policy.suffix_actions:raise TypeError('exact command forecast ownership')
    view.__post_init__()
    if cache.ownership!='FORECAST_PUBLIC_MODEL' or cache.model!=view.model:raise ValueError('independent command forecast bank required')
    intents=view.propagation_intents()
    if len(intents)>view.estimation.maximum_unreceived_intents:raise ValueError('B48_PENDING_INTENT_BOUND')
    if work.forecast_invocations>=min(quotas.max_forecast_invocations,view.policy.max_forecasts):raise ValueError('B48_FORECAST_COUNT_EXHAUSTED')
    work.reserve_forecast(view.model,quotas)
    work.reserve_estimation(view.model,quotas,view.estimation,len(intents))
    context=estimated_context(view);p=view.knowledge.observation
    state=start_physical(view.model,context,p.attitude,tuple(r.product for r in view.requests),cache,
        'COMMAND_ESTIMATE:'+view.identity,consumed=ConsumedContacts(p.consumed_contacts),forecast=True)
    reason=None
    try:
        for i in intents:
            if i.expected_end_seconds>view.now_seconds:
                reason='UNCONFIRMED_PROFILE_NOT_YET_EXPECTED_SETTLED';break
            if state.context.simulation_time_seconds<i.issued_at_seconds:
                state=advance_physical(state,LongMissionAction('estimate-gap-'+i.command_id,'HOLD_UNTIL',until_seconds=i.issued_at_seconds))
                if state.outcomes[-1].status!='completed':reason='ESTIMATE_GAP_REFUSED:'+str(state.outcomes[-1].reason);break
            if state.context.simulation_time_seconds!=i.issued_at_seconds:
                reason='UNSUPPORTED_INTENT_TIME_REBASE';break
            state=advance_physical(state,i.action);o=state.outcomes[-1]
            work.estimator_command_propagations_completed+=1
            if o.status!='completed':reason='ASSUMED_COMMAND_MODEL_REFUSED:'+str(o.reason);break
            if o.end_seconds!=i.expected_end_seconds or o.attitude.quaternion!=i.expected_attitude.quaternion:
                reason='COMMAND_PROFILE_CONTRADICTION_REPLAN';break
        if reason is None and state.context.simulation_time_seconds<view.now_seconds:
            state=advance_physical(state,LongMissionAction('command-estimate-age-'+view.identity[:20],'HOLD_UNTIL',until_seconds=view.now_seconds))
            if state.outcomes[-1].status!='completed':reason='ESTIMATE_CATCHUP:'+str(state.outcomes[-1].reason)
        estimate=EstimatedCommandState(METHOD,view.identity,digest(view.model),p.packet_id,p.observed_at_seconds,p.received_at_seconds,
            state.context.simulation_time_seconds,view.now_seconds-p.observed_at_seconds,view.estimation.assumption,
            tuple(i.command_id for i in intents),'MODEL_ESTIMATE_UNCONFIRMED' if reason is None else 'UNSUPPORTED',reason,
            state.attitude,state.context.spacecraft_state.battery.energy_wh,
            tuple((n.node_id.value,n.temperature_k) for n in state.context.spacecraft_state.thermal.node_states),
            state.context.spacecraft_state.data_storage.stored_records,
            tuple((r.record_id.value,r.transmitted_equivalent_bits) for r in state.context.ground_data_delivery_state.partial_transfers),
            state.context.ground_data_delivery_state.completed_deliveries,state.outcomes,
            asdict(state.runtime_work),asdict(state.construction.work),asdict(state.harness.work))
        if reason is None:
            for a in suffix:
                if a.kind=='HOLD_UNTIL' and a.until_seconds>min(view.now_seconds+view.policy.lookahead_seconds,view.model.environment.end_seconds):raise ValueError('command forecast lookahead admission')
                state=advance_physical(state,a)
                if state.outcomes[-1].status!='completed':reason=state.outcomes[-1].reason;break
                if state.context.simulation_time_seconds>min(view.now_seconds+view.policy.lookahead_seconds,view.model.environment.end_seconds):reason='FORECAST_LOOKAHEAD_EXCEEDED';break
        f=CommandForecastResult(view.identity,suffix,'admissible' if reason is None else 'refused',reason,
            state.context.simulation_time_seconds,state.context.spacecraft_state.battery.energy_wh,
            tuple((n.node_id.value,n.temperature_k) for n in state.context.spacecraft_state.thermal.node_states),
            state.context.spacecraft_state.data_storage.stored_records,
            tuple((r.record_id.value,r.transmitted_equivalent_bits) for r in state.context.ground_data_delivery_state.partial_transfers),
            state.context.ground_data_delivery_state.completed_deliveries,state.outcomes,
            asdict(state.runtime_work),asdict(state.construction.work),asdict(state.harness.work),None,estimate)
        paid_publication(f,work,quotas,min(32*2**20,view.model.limits.max_document_bytes))
        return f
    finally:work.record('B48_COMMAND_ESTIMATE_AND_SUFFIX',state)


def published_intent(view,decision,action):
    """Extract only publicly forecast first-action profile, before actual execution."""
    if decision.explanation in ('TERMINAL_PAID_STANDBY_NO_LOOKAHEAD','B48_UNSUPPORTED_ESTIMATE_PAID_WAIT_NO_FORECAST_CERTIFICATE'):
        if action.kind!='HOLD_UNTIL':raise ValueError('uncertified wait only permits paid standby')
        pose=replace(view.knowledge.observation.attitude,at_seconds=Q(action.until_seconds))
        return CommandIntent(action.action_id,digest(view.model),action,view.now_seconds,action.until_seconds,pose,digest(('TERMINAL_HOLD',action)))
    selected=next((f for _,f in decision.forecasts if f.status=='admissible' and f.suffix==decision.selected_suffix),None)
    if type(selected) is not CommandForecastResult:raise ValueError('no paid command prediction selected')
    o=next((o for o in selected.predicted_outcomes if o.action_id==decision.selected_suffix[0].action_id),None)
    if o is None or o.status!='completed' or o.start_seconds!=view.now_seconds:raise ValueError('selected profile boundary mismatch')
    return CommandIntent(action.action_id,digest(view.model),action,view.now_seconds,o.end_seconds,o.attitude,
        digest((o.slew,o.start_seconds,o.end_seconds,o.attitude)))
