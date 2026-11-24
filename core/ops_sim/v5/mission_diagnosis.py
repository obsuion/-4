"""Output-only typed M6 attribution. No diagnostic object grants execution.

The scope and exact returned owner reason remain explicit. Unsupported subcauses
stay UNKNOWN; forecast refusals are not observed spacecraft failures.
"""
from dataclasses import dataclass
from .rolling_physics import digest
from .rolling_contract import integer
from .long_mission import EnvironmentActionOutcome

METHOD='M6_TYPED_RETURNED_EVIDENCE_DIAGNOSIS_V1'


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    owner_type: str
    record_id: str
    field_path: str
    value: object
    units: str


@dataclass(frozen=True, slots=True)
class DiagnosisFinding:
    finding_id: str
    scope: str
    category: str
    decision_id: str
    action_id: str
    request_id: str
    at_seconds: int
    owner_reason: str | None
    conclusion: str
    evidence: tuple[EvidenceReference,...]


@dataclass(frozen=True, slots=True)
class MissionDiagnosis:
    method: str
    root_identity: str
    model_identity: str
    assembly_identity: str
    construction_identity: str
    controller_method: str
    estimation_method: str
    boundary_commands: int
    findings: tuple[DiagnosisFinding,...]

    def __post_init__(self):
        if type(self.method) is not str or self.method!=METHOD:raise ValueError('diagnosis version')
        integer(self.boundary_commands,'diagnosed prefix',0,64)
        if type(self.findings) is not tuple or len(self.findings)>4096 or any(type(f) is not DiagnosisFinding for f in self.findings):raise ValueError('bounded typed diagnosis')


def classify_returned_reason(reason):
    """Exact documented owners only, retaining UNKNOWN for ambiguous admissions."""
    if reason is None:return 'COMPLETED_RETURNED_ACTION'
    exact={'ACQUISITION_WINDOW_MISSED':'ACQUISITION_WINDOW',
        'CAMERA_TARGET_SEPARATION_EXCEEDS_FOV':'SAMPLED_FOV',
        'TARGET_NOMINAL_SAMPLED_NOT_VISIBLE':'SAMPLED_VISIBILITY',
        'TARGET_POINTING_GEOMETRY_REFUSED':'SAMPLED_VISIBILITY',
        'STATION_GEOMETRY_OR_DECLARED_SERVICE_UNAVAILABLE':'GEOMETRY_OR_DECLARED_SERVICE_UNKNOWN_SUBCAUSE',
        'OPERATING_TEMPERATURE_AT_ENDPOINT':'PRIVATE_TRIAL_THERMAL_PROTECTION',
        'FULL_ELECTRICAL_SERVICE_UNAVAILABLE':'FULL_ELECTRICAL_SERVICE',
        'EXISTING_ACQUISITION_SEQUENCE_OR_STORAGE_REFUSED':'ACQUISITION_OR_STORAGE_UNKNOWN_SUBCAUSE',
        'HOLD_END_ALREADY_PASSED':'LINKED_PLAN_TIMING',
        'SLEW_EXCEEDS_ENVIRONMENT_DOMAIN':'PAID_SLEW_DOMAIN',
        'ACTION_EXCEEDS_BOUND_ENVIRONMENT':'ACTION_DOMAIN'}
    if reason in exact:return exact[reason]
    if type(reason) is str and reason.startswith(('CONSTRUCTION_ELECTRICAL_REFUSED:','CONSTRUCTION_CONTACT_ELECTRICAL_REFUSED:')):return 'RETURNED_ELECTRICAL_LIMIT'
    return 'UNKNOWN_OWNER_SUBCAUSE'


def collect_diagnosis(state):
    """Consume actual typed coordinator history outside planning/selection.

    Counter reservations, timeouts and hidden truth never enter PlanningView.
    Each finding binds its own precise record/field and complete root/model.
    """
    from .rolling_execution import RollingState
    if type(state) is not RollingState:raise TypeError('typed actual history required')
    findings=[]
    def add(scope,category,decision,action,request,t,reason,conclusion,refs):
        if len(findings)>=4096:raise ValueError('M6_DIAGNOSIS_OUTPUT_BOUND')
        payload=(scope,category,decision,action,request,t,reason,conclusion,refs)
        findings.append(DiagnosisFinding(digest(payload),*payload))
    def ref(record,path,value,units='1'):
        return EvidenceReference(type(record).__module__+'.'+type(record).__qualname__,
            getattr(record,'action_id',getattr(record,'decision_id',getattr(record,'packet_id','boundary'))),path,value,units)
    def outcome(o,scope,did,request=''):
        if type(o) is not EnvironmentActionOutcome:raise TypeError('exact returned action evidence')
        refs=[ref(o,'status',o.status),ref(o,'reason',o.reason),ref(o,'start_seconds',o.start_seconds,'s'),ref(o,'end_seconds',o.end_seconds,'s')]
        if o.slew is not None:
            refs.extend((ref(o,'slew.duration_seconds',o.slew.duration_seconds,'s'),
                ref(o,'slew.effective_inertia_kg_m2',o.slew.effective_inertia_kg_m2,'kg m^2')))
        if o.geometry:
            refs.append(ref(o,'geometry[].visible',tuple(g.visible for g in o.geometry)))
            refs.extend((ref(o,'geometry[].station_available',tuple(g.station_available for g in o.geometry)),
                ref(o,'geometry[].rf_admitted',tuple(g.rf_admitted for g in o.geometry)),
                ref(o,'geometry[].service_assumption',tuple(g.service_assumption for g in o.geometry))))
            if o.reason=='CAMERA_TARGET_SEPARATION_EXCEEDS_FOV':
                from .long_mission import angle_between
                camera=o.attitude.direction(state.physical.harness.hardware.camera_body_axis)
                separation=tuple((g.requested_seconds,angle_between(camera,g.direction.components)) for g in o.geometry)
                refs.extend((ref(o,'geometry[].camera_separation_derived_from_returned_pose_direction',separation,'rad'),
                    EvidenceReference('PublicPhysicalModel',state.root_identity,'camera_half_fov_rad',state.root.model.camera_half_fov_rad,'rad')))
        if o.failure_diagnostic:refs.append(ref(o,'failure_diagnostic',o.failure_diagnostic,'owner-native'))
        if o.acquired_record is not None:refs.append(ref(o,'acquired_record',o.acquired_record,'bit/record'))
        if o.contact_outcomes:
            refs.append(ref(o,'contact_outcomes',o.contact_outcomes,'bit/Wh/s'))
        if o.cuts:
            # Native returned branch solutions, not reevaluated electrical physics.
            refs.append(ref(o,'cuts[].part.electrical.branches.endpoints',
                (o.cuts[0].part.electrical.branches,o.cuts[-1].part.electrical.branches),'A/V/W'))
        category=classify_returned_reason(o.reason)
        conclusion=('Returned predicted trial; does not establish actual failure or receipt.' if scope=='FORECAST' else
            'Committed actual boundary; returned trial diagnostic is separate from published physical state.')
        if category.endswith('UNKNOWN_SUBCAUSE') or category=='UNKNOWN_OWNER_SUBCAUSE':conclusion+=' More specific root cause UNKNOWN.'
        add(scope,category,did,o.action_id,request,o.start_seconds,o.reason,conclusion,tuple(refs))
    for d,a,o in zip(state.decisions,state.physical.commands,state.physical.outcomes):
        outcome(o,'ACTUAL',d.decision_id,a.product_id)
        add('POLICY','RECEIVED_KNOWLEDGE_AGE',d.decision_id,a.action_id,a.product_id,o.start_seconds,None,
            'Age is received-sample age, not an attitude error bound.',(ref(d,'knowledge_age_seconds',d.knowledge_age_seconds,'s'),ref(d,'explanation',d.explanation)))
        for key,reason in d.rejected:
            add('POLICY','CANDIDATE_SELECTION_OR_SCREEN',d.decision_id,'',key,o.start_seconds,reason,
                'Policy screen or tried forecast refusal. It is not an actual execution refusal.',(ref(d,'rejected',(key,reason)),))
        tried={a.product_id for _,f in d.forecasts for a in f.suffix if a.product_id}
        for r in state.root.requests:
            if r.release_seconds<=o.start_seconds<r.product.acquisition_end_seconds and r.product.request.request_id.value not in tried:
                add('POLICY','UNTRIED_BY_BOUNDED_POLICY',d.decision_id,'',r.product.request.request_id.value,o.start_seconds,None,
                    'No paid suffix for this request at this boundary; greedy stopping/screening/pending rules may explain selection, not physical infeasibility.',
                    (ref(d,'tried_forecast_request_ids',tuple(sorted(tried))),ref(d,'explanation',d.explanation),ref(d,'rejected',d.rejected)))
        for tag,f in d.forecasts:
            for trial in f.predicted_outcomes:
                # Catch-up belongs to the estimate; identify it separately.
                trial_scope='FORECAST'
                outcome(trial,trial_scope,d.decision_id,next((x.product_id for x in f.suffix if x.action_id==trial.action_id),''))
            if hasattr(f,'estimate'):
                e=f.estimate
                add('ESTIMATE','UNCONFIRMED_COMMAND_FOLLOWING',d.decision_id,'','',o.start_seconds,e.reason,
                    'Model-derived expected pose/resources/custody. No observed command success, receipt or credit.',
                    (ref(d,'forecasts.'+tag+'.estimate.source_packet_id',e.source_packet_id),
                     ref(d,'forecasts.'+tag+'.estimate.command_ids',e.command_ids),
                     ref(d,'forecasts.'+tag+'.estimate.status',e.status),
                     ref(d,'forecasts.'+tag+'.estimate.attitude',e.attitude,'quaternion/s'),
                     ref(d,'forecasts.'+tag+'.estimate.energy_wh',e.energy_wh,'Wh'),
                     ref(d,'forecasts.'+tag+'.estimate.observation_age_seconds',e.observation_age_seconds,'s'),
                     ref(d,'forecasts.'+tag+'.estimate.assumption',e.assumption)))
    for r in state.reconciliations:
        add('RECEIVED_ACK','ACK_RECONCILIATION','',r.command_id,'',r.received_at_seconds,r.observed_reason,
            r.conclusion,(EvidenceReference(type(r).__module__+'.'+type(r).__qualname__,r.packet_id,'reconciliation',r,'s/pose/status'),))
    now=state.physical.context.simulation_time_seconds
    from .ms_product import assess_ms_product
    for r in state.root.requests:
        p=r.product;rid=p.request.request_id.value
        assessment=assess_ms_product(p,state.physical.acquisitions,state.physical.context.ground_data_delivery_state,
            tuple(c for o in state.physical.outcomes for c in o.contact_outcomes),now)
        selected=tuple(a.action_id for a in state.physical.commands if a.product_id==rid)
        category='UNRELEASED' if r.release_seconds>now else ('ACTUAL_RECEIPT_CREDIT' if selected else 'NOT_SELECTED_BY_GREEDY_POLICY')
        add('EVALUATION_ONLY',category,'','',rid,now,None,
            'Causal assessment uses actual custody and returned receipt/deadline evidence; this ledger is excluded from planner.',
            (EvidenceReference('MSProductAssessment',rid,'assessment',assessment,'request/bit/s'),
             EvidenceReference('ReleasedRequest',rid,'release_seconds',r.release_seconds,'s'),
             EvidenceReference('MSProductSpec',rid,'acquisition_window',(p.acquisition_start_seconds,p.acquisition_end_seconds),'s'),
             EvidenceReference('RollingState',rid,'selected_actual_command_ids',selected,'1')))
    if state.status.startswith('INCOMPLETE'):
        add('COORDINATOR','INCOMPLETE_OR_BUDGET','', '', '',now,state.status,
            'Returned bounded coordinator status. Physical infeasibility and unobserved continuation UNKNOWN.',
            (EvidenceReference('RollingState',state.root_identity,'status',state.status,'1'),))
    return MissionDiagnosis(METHOD,state.root_identity,digest(state.root.model),state.root.model.configuration.assembly_digest,
        state.physical.construction.compilation.configuration_digest,
        getattr(state.root,'controller_method',state.root.policy.method),getattr(getattr(state.root,'estimation',None),'method','B47_RECEIVED_ONLY_V1'),
        len(state.command_lineage),tuple(findings))


@dataclass(frozen=True, slots=True)
class TerminationEvidence:
    root_identity: str
    model_identity: str
    kind: str
    owner: str
    reason: str
    last_validated_seconds: int | None
    integrity_verified: bool
    source_record_identity: str

    def __post_init__(self):
        for s in (self.root_identity,self.model_identity,self.source_record_identity):
            if type(s) is not str or len(s)!=64 or any(c not in '0123456789abcdef' for c in s):raise ValueError('termination binding')
        if type(self.kind) is not str or self.kind not in ('MODEL_EXCEPTION','ADMISSION_REFUSAL','OWNED_PROCESS_TIMEOUT','INCOMPLETE_COORDINATOR'):raise ValueError('termination scope')
        if type(self.owner) is not str or not self.owner or type(self.reason) is not str or type(self.integrity_verified) is not bool:raise ValueError('termination exact evidence')
        if self.last_validated_seconds is not None:integer(self.last_validated_seconds,'last validated boundary')


def diagnose_termination(evidence):
    """A typed termination describes only recorded work, never future coverage."""
    if type(evidence) is not TerminationEvidence:raise TypeError('exact termination evidence')
    evidence.__post_init__()
    category={'MODEL_EXCEPTION':'COMPUTATIONAL_ERROR_CAUSE_UNKNOWN','ADMISSION_REFUSAL':'WORK_OR_OUTPUT_ADMISSION',
        'OWNED_PROCESS_TIMEOUT':'PROCESS_TIMEOUT_NOT_MATHEMATICAL_FAILURE','INCOMPLETE_COORDINATOR':'INCOMPLETE_BOUNDED_PREFIX'}[evidence.kind]
    if not evidence.integrity_verified:category='DIAGNOSTIC_INTEGRITY_UNESTABLISHED'
    refs=(EvidenceReference('TerminationEvidence',evidence.source_record_identity,'kind',evidence.kind,'1'),
        EvidenceReference('TerminationEvidence',evidence.source_record_identity,'last_validated_seconds',evidence.last_validated_seconds,'s'),
        EvidenceReference('TerminationEvidence',evidence.source_record_identity,'integrity_verified',evidence.integrity_verified,'1'))
    return DiagnosisFinding(digest(evidence),'TERMINATION',category,'','','',evidence.last_validated_seconds or 0,
        evidence.reason,'No endpoint, complete coverage, checkpoint, final counters or physical infeasibility follows from this termination. Unrecorded work and deeper cause UNKNOWN.',refs)


def capture_model_exception(state,error):
    """Capture the original exception's exact final frame without suppressing it."""
    from .rolling_execution import guard_rolling
    guard_rolling(state)
    if not isinstance(error,Exception):raise TypeError('ordinary original model exception required')
    tb=error.__traceback__
    while tb is not None and tb.tb_next is not None:tb=tb.tb_next
    owner='UNAVAILABLE_NO_TRACEBACK' if tb is None else tb.tb_frame.f_code.co_filename+':'+str(tb.tb_lineno)+':'+tb.tb_frame.f_code.co_name
    reason=type(error).__module__+'.'+type(error).__qualname__+': '+str(error)
    admitted_names=('rolling_cache.py','command_estimation.py','command_document.py','engineering_experiment.py')
    scope='ADMISSION_REFUSAL' if type(error) is ValueError and tb is not None and any(tb.tb_frame.f_code.co_filename.endswith(n) for n in admitted_names) and ('QUOTA' in str(error) or 'ADMISSION' in str(error) or 'BOUND' in str(error)) else 'MODEL_EXCEPTION'
    evidence=TerminationEvidence(state.root_identity,digest(state.root.model),scope,owner,reason,
        state.physical.context.simulation_time_seconds,True,digest((owner,reason,state.boundary_identity)))
    return evidence,diagnose_termination(evidence)
