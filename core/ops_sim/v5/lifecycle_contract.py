"""B52 finite NOMINAL chronological inputs, distinct from B48 short replay.

The base root supplies fixed hardware and an initial state, never an advanced
state or a growing action history. Fifteen years is an admission capability,
not computed coverage. All numerical and memory policies are explicit inputs.

B55 alone may declare an existing immutable ReducedSunPolicy as original
scenario authority. None preserves all older input wires and identities. An
explicit declaration has a separate input version/digest; it is not a runtime
override, a new Sun model, a checkpoint migration or a calibration claim.
"""
from dataclasses import dataclass, replace, asdict, field
from fractions import Fraction as Q
from hashlib import sha256
import json, math

METHOD='B52_CHRONOLOGICAL_NOMINAL_ACK_GATED_V1'
METHOD53='B53_ADAPTIVE_QUIET_CHRONOLOGICAL_NOMINAL_V1'
METHOD55='B55_CONSTRUCTION_RECOVERY_CHRONOLOGICAL_NOMINAL_V1'
POLICY='B52_EVENT_CUT_RETURNED_STATE_V1'
CALENDAR='FIXED_30_DAY_BUCKET_V1'
YEAR=31557600
MAX_DURATION=15*YEAR
MONTH=2592000

def integer(value,name,lo=0,hi=2**48):
    if type(value) is not int or not lo<=value<=hi:raise ValueError('lifecycle exact integer: '+name)
    return value

def identity(value):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('lifecycle digest')
    return value

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

@dataclass(frozen=True,slots=True)
class LifecyclePolicy:
    quiet_step_seconds: int = 60
    detailed_step_seconds: int = 2
    lighting_step_seconds: int = 60
    contact_piece_seconds: int = 4
    contact_integration_level: int = 2
    latency_seconds: int = 40
    telemetry_step_seconds: int = 120
    maximum_observation_age_seconds: int = 180
    month_period_seconds: int = MONTH
    month_epoch_offset_seconds: int = -128
    recent_records: int = 8
    active_requests: int = 16
    max_pending_packets: int = 128
    max_journal_bytes: int = 8*2**20
    max_checkpoint_bytes: int = 64*2**20
    max_working_bytes: int = 64*2**20
    max_task_output_bytes: int = 512*2**20
    max_transitions: int = 2**28
    max_controller_decisions: int = 2**24
    max_control_units: int = 2**48
    max_forecast_transitions: int = 2**26
    method: str = POLICY
    quiet_solver: object | None = None
    def __post_init__(self):
        if type(self.method) is not str or self.method not in(POLICY,'B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'):raise ValueError('lifecycle numerical policy')
        for n,lo,hi in (('quiet_step_seconds',1,120),('detailed_step_seconds',1,10),('lighting_step_seconds',1,120),
            ('contact_piece_seconds',1,30),('contact_integration_level',0,4),('latency_seconds',0,120),('telemetry_step_seconds',1,600),('maximum_observation_age_seconds',1,600),
            ('month_period_seconds',1,MONTH),('recent_records',1,32),('active_requests',1,16),('max_pending_packets',1,128),
            ('max_journal_bytes',1024,16*2**20),('max_checkpoint_bytes',65536,64*2**20),('max_working_bytes',65536,64*2**20),
            ('max_task_output_bytes',2**20,2**30),('max_transitions',1,2**32),('max_controller_decisions',1,2**32),
            ('max_control_units',1,2**52),('max_forecast_transitions',1,2**48 if self.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'else 2**32)):
            integer(getattr(self,n),n,lo,hi)
        integer(self.month_epoch_offset_seconds,'calendar offset',-2**40,2**40)
        if self.maximum_observation_age_seconds<self.latency_seconds:raise ValueError('latency exceeds retained observation contract')
        if self.max_checkpoint_bytes>self.max_task_output_bytes:raise ValueError('checkpoint prospective output admission')
        if self.quiet_solver is not None:
            from .lifecycle_quiet import QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy
            if type(self.quiet_solver) not in (QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy):raise TypeError('exact versioned quiet solver policy')
            self.quiet_solver.__post_init__()
            if self.quiet_solver.detailed_seconds!=self.detailed_step_seconds:
                raise ValueError('quiet fallback and detailed action policy differ')

@dataclass(frozen=True,slots=True)
class LifecycleScenario:
    namespace: str = 'b52-recurring'
    cadence_seconds: int = 900
    acquisition_window_seconds: int = 180
    capture_duration_seconds: int = 4
    contact_offset_seconds: int = 240
    contact_duration_seconds: int = 120
    deadline_offset_seconds: int = 600
    request_index: int = 0
    method: str = 'B52_FINITE_RECURRING_RELEASED_MS_SCENARIO_V1'
    def __post_init__(self):
        if type(self.namespace) is not str or not 1<=len(self.namespace)<=64 or any(not(c.isalnum() or c in '-_') for c in self.namespace):raise ValueError('scenario namespace')
        from .ids import ImagingRequestId
        ImagingRequestId(self.namespace+'-0');ImagingRequestId(self.namespace+'-'+str(2**32))
        for n,lo,hi in (('cadence_seconds',120,86400),('acquisition_window_seconds',2,600),('capture_duration_seconds',1,120),
            ('contact_offset_seconds',1,1800),('contact_duration_seconds',1,120),('deadline_offset_seconds',2,3600),('request_index',0,15)):
            integer(getattr(self,n),n,lo,hi)
        if self.capture_duration_seconds>self.acquisition_window_seconds or self.acquisition_window_seconds>self.deadline_offset_seconds or self.contact_offset_seconds+self.contact_duration_seconds>self.deadline_offset_seconds or self.deadline_offset_seconds>self.cadence_seconds:raise ValueError('ordered disjoint occurrence domain')
        if type(self.method) is not str or self.method!='B52_FINITE_RECURRING_RELEASED_MS_SCENARIO_V1':raise ValueError('scenario method')
    def occurrence_id(self,index):
        integer(index,'occurrence',0,2**32)
        return self.namespace+'-'+str(index)

@dataclass(frozen=True,slots=True)
class LifecycleRoot:
    base: object
    duration_seconds: int
    policy: LifecyclePolicy = LifecyclePolicy()
    scenario: LifecycleScenario = LifecycleScenario()
    sun_mode: str = 'REDUCED_ASSUMED_ANNUAL_V1'
    method: str = METHOD
    study: object | None = None
    output_policy: object | None = None
    service_policy: object | None = None
    reduced_sun_policy: object | None = None
    energy_attitude_policy: object | None = None
    battery_port_policy: object | None = None
    environment_ageing_policy: object | None = None
    _identity: str = field(init=False,repr=False,compare=False)
    def __post_init__(self):
        from .command_estimation import CommandRollingRoot
        if type(self.base) is not CommandRollingRoot or type(self.policy) is not LifecyclePolicy or type(self.scenario) is not LifecycleScenario:raise TypeError('exact lifecycle root authorities')
        integer(self.duration_seconds,'horizon',1,MAX_DURATION)
        self.policy.__post_init__();self.scenario.__post_init__()
        if self.environment_ageing_policy is not None:
            from .environment_ageing import EnvironmentAgeingPolicy,admit_network
            from .lifecycle_quiet import EnvironmentQuietIntegrationPolicy
            if type(self.environment_ageing_policy)is not EnvironmentAgeingPolicy:raise TypeError('B61 exact ageing policy')
            admit_network(self.base.model.simulation_inputs.spacecraft_configuration.thermal.network,self.environment_ageing_policy)
            if self.policy.quiet_solver is not None and type(self.policy.quiet_solver)is not EnvironmentQuietIntegrationPolicy:raise ValueError('B61 unit-aware ageing quiet policy required')
        service=self.service_policy is not None
        if service:
            from .lifecycle_service import PowerServicePolicy
            if type(self.service_policy) is not PowerServicePolicy:raise TypeError('exact named construction power service policy')
            self.service_policy.__post_init__()
        if self.battery_port_policy is not None:
            from .battery_port import BatteryPortPolicy
            from .lifecycle_quiet import BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy
            if type(self.battery_port_policy)is not BatteryPortPolicy or not service:raise TypeError('B58 port requires explicit service')
            self.battery_port_policy.__post_init__()
            if self.policy.quiet_solver is not None and type(self.policy.quiet_solver) not in (BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy):raise ValueError('port requires unit-aware numerical policy')
        if self.energy_attitude_policy is not None:
            from .solar_attitude import EnergyAttitudePolicy
            if type(self.energy_attitude_policy) is not EnergyAttitudePolicy:raise TypeError('exact immutable energy-attitude policy')
            self.energy_attitude_policy.__post_init__()
            if not service or self.energy_attitude_policy.entry_usable_fraction<=self.service_policy.low_usable_capacity_fraction:raise ValueError('preventive Sun policy requires explicit B55 service and entry above hard SAFE')
        if self.reduced_sun_policy is not None:
            from .lifecycle_world import ReducedSunPolicy
            if type(self.reduced_sun_policy) is not ReducedSunPolicy:
                raise TypeError('exact explicit immutable reduced Sun policy')
            self.reduced_sun_policy.__post_init__()
            if not service or self.sun_mode!='REDUCED_ASSUMED_ANNUAL_V1':
                raise ValueError('explicit reduced Sun override requires B55 reduced-Sun input')
        extended=self.study is not None or self.output_policy is not None or self.policy.quiet_solver is not None or service or self.environment_ageing_policy is not None
        expected_method=METHOD55 if service else METHOD53 if extended else METHOD
        if (service and self.method in (METHOD,METHOD53)) or (extended and self.method==METHOD):object.__setattr__(self,'method',expected_method)
        if type(self.method) is not str or self.method!=expected_method or type(self.sun_mode) is not str or self.sun_mode not in ('REDUCED_ASSUMED_ANNUAL_V1','BOUND_SHORT_TABLE_V1'):raise ValueError('new lifecycle/world method')
        if self.study is not None:
            from .lifecycle_study import LifecycleStudyInput,validate_study_base
            if type(self.study) is not LifecycleStudyInput:raise TypeError('exact long study declaration')
            self.study.__post_init__()
            if self.duration_seconds>self.study.maximum_duration_seconds or self.policy.latency_seconds!=self.study.latency_seconds:
                raise ValueError('study horizon/latency authority')
            validate_study_base(self.base,self.study)
        if self.output_policy is not None:
            from .lifecycle_stream import LifecycleStreamPolicy
            if type(self.output_policy) is not LifecycleStreamPolicy:raise TypeError('exact versioned output policy')
            self.output_policy.__post_init__()
            if self.output_policy.declared_stream_bytes>self.policy.max_task_output_bytes:
                raise ValueError('prospective complete stream allocation exceeds root output allowance')
        if self.scenario.request_index>=len(self.base.requests):raise ValueError('scenario template index')
        if not self.base.contacts:raise ValueError('declared service station template required')
        if self.sun_mode=='BOUND_SHORT_TABLE_V1' and self.end_seconds>self.base.model.environment.end_seconds:raise ValueError('short Sun table cannot cover long horizon')
        if self.month_rows>184:raise ValueError('finite calendar population')
        from .rolling_physics import digest
        if not extended:
            # Preserve the original B52 input identity, not its source binding.
            # The new optional None policy field did not exist in that schema.
            from .long_mission_continuation import _scientific
            from .long_mission_document import canonical_json
            data=_scientific((METHOD,self.base,self.duration_seconds,self.policy,self.scenario,self.sun_mode))
            data['tuple'][3]['fields'].pop('quiet_solver')
            h=sha256(canonical_json(data).encode()).hexdigest()
        elif self.environment_ageing_policy is not None:
            h=digest(('B61_EXPLICIT_ENVIRONMENT_AGEING_ROOT_V1',self.method,self.base,self.duration_seconds,self.policy,self.scenario,self.sun_mode,self.study,self.output_policy,self.service_policy,self.reduced_sun_policy,self.energy_attitude_policy,self.battery_port_policy,self.environment_ageing_policy))
        elif self.battery_port_policy is not None:
            h=digest(('B58_EXPLICIT_BATTERY_PORT_ROOT_V1',self.method,self.base,self.duration_seconds,self.policy,self.scenario,self.sun_mode,self.study,self.output_policy,self.service_policy,self.reduced_sun_policy,self.energy_attitude_policy,self.battery_port_policy))
        elif self.energy_attitude_policy is not None:
            h=digest(('B56_EXPLICIT_ENERGY_ATTITUDE_ROOT_V1',self.method,self.base,self.duration_seconds,self.policy,self.scenario,self.sun_mode,self.study,self.output_policy,self.service_policy,self.reduced_sun_policy,self.energy_attitude_policy))
        elif self.reduced_sun_policy is not None:
            h=digest(('B55_EXPLICIT_REDUCED_SUN_AUTHORITY_V1',self.method,self.base,self.duration_seconds,self.policy,
                self.scenario,self.sun_mode,self.study,self.output_policy,self.service_policy,self.reduced_sun_policy))
        elif service:h=digest((self.method,self.base,self.duration_seconds,self.policy,self.scenario,self.sun_mode,self.study,self.output_policy,self.service_policy))
        else:h=digest((self.method,self.base,self.duration_seconds,self.policy,self.scenario,self.sun_mode,self.study,self.output_policy))
        object.__setattr__(self,'_identity',h)
    @property
    def start_seconds(self):return self.base.initial_checkpoint.simulation_time_seconds
    @property
    def end_seconds(self):return self.start_seconds+self.duration_seconds
    @property
    def month_rows(self):
        p=self.policy
        return (self.end_seconds-1+p.month_epoch_offset_seconds)//p.month_period_seconds-(self.start_seconds+p.month_epoch_offset_seconds)//p.month_period_seconds+1
    @property
    def offered_population(self):
        # Offers occur only for declared complete occurrence windows; no
        # fictitious incomplete request is silently completed at horizon end.
        n=self.duration_seconds-self.scenario.deadline_offset_seconds
        return 0 if n<0 else n//self.scenario.cadence_seconds+1
    @property
    def identity(self):
        return self._identity

def occurrence(root,index):
    """One immutable released product and service declaration, no future truth."""
    from .rolling_contract import ReleasedRequest,DeclaredContact
    from .ids import ImagingRequestId
    integer(index,'occurrence index',0,root.offered_population-1)
    s=root.scenario;t=root.start_seconds+index*s.cadence_seconds
    template=root.base.requests[s.request_index]
    rid=s.occurrence_id(index)
    p=replace(template.product,request=replace(template.product.request,request_id=ImagingRequestId(rid)),
        capture_group=rid+'-capture',acquisition_start_seconds=t,acquisition_end_seconds=t+s.acquisition_window_seconds,
        delivery_deadline_seconds=t+s.deadline_offset_seconds)
    # Station availability/rate remain authored service assumptions. Geometry
    # is evaluated by the actual contact owner and may refuse it.
    station=root.base.contacts[0].station_id
    return ReleasedRequest(t,p,s.capture_duration_seconds),DeclaredContact(rid+'-service',station,t+s.contact_offset_seconds,t+s.contact_offset_seconds+s.contact_duration_seconds)

def horizon_inputs(root):
    """New initial immutable identity. Never retags an advanced checkpoint."""
    from .ids import WorldId,ModelManifestId,ControllerId
    old=root.base.model.simulation_inputs
    h=root.identity
    prefix='b58' if root.battery_port_policy is not None else 'b56' if root.energy_attitude_policy is not None else 'b55' if root.method==METHOD55 else 'b53' if root.method==METHOD53 else 'b52'
    world=replace(old.common_world,world_id=WorldId(prefix+'-world-'+h),horizon_seconds=root.end_seconds)
    manifest=replace(old.model_manifest,world_id=world.world_id,manifest_id=ModelManifestId(prefix+'-model-'+h),controller_id=ControllerId(prefix+'-ack-gated-v1'))
    return replace(old,common_world=world,model_manifest=manifest)

def initial_context(root,inputs):
    """Carry exactly initial physical values into a separately named world."""
    from .checkpoint import CheckpointState
    # The only rebinding is at original initial time, before any paid mission
    # transition. Resume always requires the already-long manifest unchanged.
    old=root.base.initial_checkpoint
    if old.simulation_time_seconds!=root.start_seconds:raise ValueError('initial authority clock')
    manifest=inputs.model_manifest
    cp=replace(old,model_manifest_id=manifest.manifest_id,world_id=manifest.world_id,controller_id=manifest.controller_id,
        controller=replace(old.controller,controller_id=manifest.controller_id))
    return cp.restore(inputs)

def static_admission(root):
    root.__post_init__()
    result=dict(method=root.method,status='ADMITTED_INPUT_ONLY_NOT_COMPUTED',duration_seconds=root.duration_seconds,
        end_seconds=root.end_seconds,calendar=CALENDAR if root.policy.month_period_seconds==MONTH else 'SYNTHETIC_UNIT_BUCKET_NOT_MONTH_PHYSICS',month_rows=root.month_rows,offered_population=root.offered_population,
        orbit_grid_steps_upper=(root.duration_seconds+9)//10,
        retained_grid_cap=256,working_bytes_cap=root.policy.max_working_bytes,checkpoint_bytes_cap=root.policy.max_checkpoint_bytes,
        year_seconds=YEAR,max_duration_seconds=MAX_DURATION,
        quiet_method=None if root.policy.quiet_solver is None else root.policy.quiet_solver.method,
        study_digest=None if root.study is None else root.study.content_digest,
        output_method=None if root.output_policy is None else root.output_policy.method,
        qualification='NOMINAL_NO_CONTINUOUS_OR_PHYSICAL_CERTIFICATE')
    if root.service_policy is not None:
        result.update(service_method=root.service_policy.method,service_policy_identity=root.service_policy.identity)
    if root.reduced_sun_policy is not None:
        result['reduced_sun_policy']=asdict(root.reduced_sun_policy)
    if root.energy_attitude_policy is not None:
        result['energy_attitude_policy']=asdict(root.energy_attitude_policy)
        result['energy_attitude_policy_identity']=root.energy_attitude_policy.identity
    if root.battery_port_policy is not None:
        # Stored admission is JSON data, not the immutable tuple input graph.
        result['battery_port_policy']=json.loads(canonical(asdict(root.battery_port_policy)))
        result['battery_port_policy_identity']=root.battery_port_policy.identity
    return result
