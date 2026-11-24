"""Finite B52 future state. No completed forecast/action tree is retained."""
from dataclasses import dataclass
from fractions import Fraction as Q
from .lifecycle_contract import METHOD,integer,identity

@dataclass(frozen=True,slots=True)
class LifecycleObservation:
    ordinal: int
    observed_at_seconds: int
    received_at_seconds: int
    checkpoint: object
    attitude: object
    consumed_through_seconds: int
    command_id: str = ''
    command_kind: str = ''
    command_status: str = 'initial'
    command_reason: str | None = None
    request_id: str = ''
    acquisitions: tuple = ()
    receipts: tuple = ()
    quiet_controller: object | None = None
    service_state: object | None = None
    command_completed_at_seconds: int | None = None
    solar_state: object | None = None
    solar_pending: object | None = None
    battery_port_state: object | None = None
    environment_ageing_state: object | None = None
    def __post_init__(self):
        for n in ('ordinal','observed_at_seconds','received_at_seconds','consumed_through_seconds'):integer(getattr(self,n),n)
        if not self.observed_at_seconds<=self.received_at_seconds<=self.observed_at_seconds+120:raise ValueError('observation latency')
        if self.checkpoint.simulation_time_seconds!=self.observed_at_seconds or self.attitude.at_seconds!=self.observed_at_seconds:raise ValueError('observation state/pose/clock')
        if self.command_status not in ('initial','partial','completed','refused'):raise ValueError('observation status')
        if self.battery_port_state is not None:
            from .battery_port import BatteryPortState
            if type(self.battery_port_state)is not BatteryPortState or self.battery_port_state.clock_seconds!=self.observed_at_seconds:raise ValueError('received port clock')
            self.battery_port_state.__post_init__()
        if self.environment_ageing_state is not None:
            from .environment_ageing import EnvironmentAgeingState
            if type(self.environment_ageing_state)is not EnvironmentAgeingState or self.environment_ageing_state.clock_seconds!=self.observed_at_seconds:raise ValueError('B61 received ageing clock')
            self.environment_ageing_state.__post_init__()
        if self.service_state is not None:
            from .lifecycle_service import PowerServiceState
            if type(self.service_state) is not PowerServiceState or self.service_state.clock_seconds != self.observed_at_seconds:
                raise ValueError('received service state/observation clock')
            self.service_state.__post_init__()
        if self.command_completed_at_seconds is not None:
            integer(self.command_completed_at_seconds,'genuine command completion',0,self.observed_at_seconds)
            if self.command_status not in ('completed','refused'):raise ValueError('completion time requires genuine terminal feedback')
        if self.solar_state is not None:
            from .solar_attitude import SolarAttitudeState,SolarAction
            from .lifecycle_physics import PendingLifecycleAction
            if type(self.solar_state) is not SolarAttitudeState or self.solar_state.clock_seconds!=self.observed_at_seconds:raise ValueError('received solar state/clock')
            self.solar_state.__post_init__()
            if self.solar_pending is not None and (type(self.solar_pending) is not PendingLifecycleAction or type(self.solar_pending.action) is not SolarAction or not self.solar_pending.origin_seconds<=self.observed_at_seconds<self.solar_pending.end_seconds):raise ValueError('received solar pending phase')
        elif self.solar_pending is not None:raise ValueError('solar pending requires received solar state')

@dataclass(frozen=True,slots=True)
class LifecycleDeferredFeedback:
    action_id: str
    kind: str
    status: str
    reason: str | None
    request_id: str
    completed_at_seconds: int
    method: str = 'B55_UNTRANSMITTED_GENUINE_COMMAND_FEEDBACK_V1'
    def __post_init__(self):
        if self.method != 'B55_UNTRANSMITTED_GENUINE_COMMAND_FEEDBACK_V1' or type(self.method) is not str:
            raise ValueError('exact deferred feedback method')
        for name in ('action_id','request_id'):
            value=getattr(self,name)
            if type(value) is not str or not value or len(value)>256:raise ValueError('bounded deferred command identity')
        if type(self.kind) is not str or self.kind not in ('POINT','CAPTURE','CONTACT'):raise ValueError('deferred command kind')
        if type(self.status) is not str or self.status not in ('completed','refused'):raise ValueError('genuine terminal feedback only')
        if self.reason is not None and (type(self.reason) is not str or not self.reason or len(self.reason)>512):raise ValueError('bounded deferred reason')
        integer(self.completed_at_seconds,'deferred command completion')

@dataclass(frozen=True,slots=True)
class LifecycleIntent:
    action: object
    request_id: str
    issued_at_seconds: int
    expected_end_seconds: int
    expected_attitude: object
    prediction_status: str = 'ASSUMED_COMMANDED_NOT_ACKNOWLEDGED'

@dataclass(frozen=True,slots=True)
class LifecycleActiveRequest:
    ordinal: int
    released: object
    contact: object
    phase: str = 'RELEASED'
    credit_reported: bool = False
    expired_reported: bool = False
    def __post_init__(self):
        integer(self.ordinal,'active occurrence')
        if self.phase not in ('RELEASED','POINT_WAIT','POINTED','CAPTURE_WAIT','CAPTURED','CONTACT_WAIT','CONTACTED','REFUSED','EXPIRED','DONE'):raise ValueError('active request phase')
        if type(self.credit_reported) is not bool or type(self.expired_reported) is not bool:raise ValueError('active disposition')

@dataclass(slots=True)
class LifecycleWork:
    transitions_reserved: int = 0
    transitions_completed: int = 0
    failed_transitions: int = 0
    controller_decisions: int = 0
    forecast_invocations: int = 0
    forecast_transitions: int = 0
    forecast_physical_reserved: int = 0
    forecast_physical_completed: int = 0
    forecast_construction_lines: int = 0
    forecast_harness_compiles: int = 0
    acknowledged_commands: int = 0
    contradicted_commands: int = 0
    control_units: int = 0
    event_hashes: int = 0
    retired_requests: int = 0
    known_expired_discards: int = 0
    checkpoint_encoding_units: int = 0
    checkpoint_storage_bytes: int = 0
    restore_validation_units: int = 0
    report_control_units: int = 0
    def validate(self,p):
        for n in self.__dataclass_fields__:integer(getattr(self,n),n,0,2**56)
        if self.transitions_reserved>p.max_transitions or self.transitions_completed+self.failed_transitions>self.transitions_reserved:raise ValueError('LIFECYCLE_TRANSITION_QUOTA')
        if self.controller_decisions>p.max_controller_decisions or self.forecast_transitions>p.max_forecast_transitions or self.control_units>p.max_control_units:raise ValueError('LIFECYCLE_CUMULATIVE_WORK_QUOTA')
        if self.forecast_physical_completed>self.forecast_physical_reserved:raise ValueError('forecast work balance')
    def reserve_transition(self,p):
        self.validate(p)
        if self.transitions_reserved+1>p.max_transitions or self.control_units+65536>p.max_control_units:raise ValueError('LIFECYCLE_WORK_ADMISSION_BEFORE_TRANSITION')
        self.transitions_reserved+=1;self.control_units+=65536

@dataclass(slots=True)
class LifecycleState:
    root: object
    root_identity: str
    model: object
    physical: object
    actual_provider: object
    forecast_provider: object
    actual_world: object
    forecast_world: object
    forecast_runtime: object
    report: object
    work: LifecycleWork
    knowledge: LifecycleObservation
    queued: tuple = ()
    active: tuple = ()
    intents: tuple = ()
    next_occurrence: int = 0
    retired_frontier: int = 0
    next_action: int = 0
    transition_count: int = 0
    event_chain: str = '0'*64
    recent: tuple = ()
    status: str = 'ACTIVE'
    last_outcome: object = None
    forecast_quiet_work: object | None = None
    compiled_context: object | None = None
    backend_context: object | None = None
    pinned_requests: tuple = ()
    deferred_feedback: tuple = ()
    solar_forecast: object | None = None
    forecast_port_work: object | None = None
    battery_port_forecast: object | None = None
    terminal: dict | None = None
    forecast_environment_work: object | None = None
    environment_forecast: object | None = None
    environment_forecast_origin: object | None = None
    @property
    def clock(self):return self.physical.context.simulation_time_seconds

def guard_lifecycle(state):
    from .lifecycle_physics import guard_lifecycle_physical
    if type(state)is not LifecycleState:raise TypeError('exact lifecycle state')
    from .lifecycle_typed_context import TypedBackendContext
    typed=type(state.backend_context)is TypedBackendContext
    if state.root_identity!=(state.backend_context.job.static.root_identity if typed else state.root.identity):raise ValueError('lifecycle root identity')
    if state.backend_context is not None:
        from .lifecycle_backend import BackendContext
        if type(state.backend_context) not in (BackendContext,TypedBackendContext):raise TypeError('exact backend context')
        state.backend_context.guard(state.root,state.model)
        if state.physical.backend_context is not state.backend_context or state.physical.prepared_runtime is not state.backend_context.actual:raise ValueError('B63 actual role wiring')
    if state.compiled_context is not None:
        from .lifecycle_admission import CompiledLifecycleContext
        if type(state.compiled_context) is not CompiledLifecycleContext:
            raise TypeError('exact process-local compiled lifecycle context')
        if state.physical.static_admission is not state.compiled_context.actual:
            raise ValueError('actual static admission scope wiring')
        state.compiled_context.guard(state.root,state.model)
    elif state.physical.static_admission is not None:
        raise ValueError('unbound physical static admission')
    # Prepared capabilities are consumed only in the current owned operation.
    # Public/untrusted/checkpoint calls outside it retain the full validator.
    actual_history_runtime=forecast_history_runtime=None
    if typed and state.backend_context.job._active is not None:
        actual_history_runtime=state.backend_context.actual
        forecast_history_runtime=state.backend_context.forecast
        actual_history_runtime.require_transaction();forecast_history_runtime.require_transaction()
    if state.root.environment_ageing_policy is None:
        if state.forecast_environment_work is not None or state.environment_forecast is not None or state.environment_forecast_origin is not None or any(p.environment_ageing_state is not None for p in (state.knowledge,*state.queued)):raise ValueError('B61 foreign legacy state')
    else:
        from .environment_ageing import EnvironmentAgeingWork,guard
        if type(state.forecast_environment_work)is not EnvironmentAgeingWork or state.forecast_environment_work is state.physical.environment_ageing_work:raise ValueError('B61 independent forecast work')
        state.forecast_environment_work.validate(state.root.environment_ageing_policy)
        baseline=state.model.simulation_inputs.spacecraft_configuration.thermal.network
        for packet in (state.knowledge,*state.queued):
            packet.__post_init__();guard(state.root.environment_ageing_policy,packet.environment_ageing_state,baseline,packet.observed_at_seconds,prepared_runtime=forecast_history_runtime)
        if state.environment_forecast is not None:
            guard(state.root.environment_ageing_policy,state.environment_forecast,baseline,prepared_runtime=forecast_history_runtime)
            if state.environment_forecast.clock_seconds>state.clock:raise ValueError('B61 future forecast state')
            origin=state.environment_forecast_origin
            if type(origin)is not tuple or len(origin)!=2 or type(origin[1])is not Q:raise ValueError('B61 exact last-paid observation origin')
            guard(state.root.environment_ageing_policy,origin[0],baseline,prepared_runtime=forecast_history_runtime)
            if not origin[0].clock_seconds<=state.environment_forecast.clock_seconds or not origin[0].clock_seconds<=origin[1]<=origin[0].clock_seconds+120 or origin[1]>state.clock:raise ValueError('B61 estimate received-origin clocks')
        elif state.environment_forecast_origin is not None:raise ValueError('B61 origin without estimate')
    if state.terminal is not None:
        from .battery_terminal import admit_terminal
        t=admit_terminal(state.terminal)
        if state.root.battery_port_policy is None or t['clock']!=state.clock or state.status=='ACTIVE':raise ValueError('model terminal state binding')
    identity(state.event_chain);state.work.validate(state.root.policy)
    guard_lifecycle_physical(state.physical)
    p=state.root.policy
    from .battery_port import BatteryPortWork,BatteryPortState
    if state.root.battery_port_policy is None:
        if state.forecast_port_work is not None or state.battery_port_forecast is not None:raise ValueError('foreign legacy port forecast')
    else:
        if type(state.forecast_port_work)is not BatteryPortWork or state.forecast_port_work is state.physical.battery_port_work:raise ValueError('separate paid forecast port work')
        state.forecast_port_work.validate()
        for packet in (state.knowledge,*state.queued):
            packet.__post_init__()
            if type(packet.battery_port_state)is not BatteryPortState:raise ValueError('received port state required')
        if state.battery_port_forecast is not None:
            if type(state.battery_port_forecast)is not BatteryPortState or state.battery_port_forecast.clock_seconds>state.clock:raise ValueError('last paid port estimate')
            state.battery_port_forecast.__post_init__()
    if len(state.active)>p.active_requests or len(state.queued)>p.max_pending_packets or len(state.intents)>p.active_requests or len(state.recent)>p.recent_records:raise ValueError('LIFECYCLE_ACTIVE_MEMORY_QUOTA')
    from .solar_attitude import SolarAttitudeState
    solar=state.root.energy_attitude_policy
    for packet in (state.knowledge,*state.queued):
        if type(packet) is not LifecycleObservation:raise TypeError('exact received observation')
        if solar is None:
            if packet.solar_state is not None or packet.solar_pending is not None:raise ValueError('legacy knowledge cannot acquire solar policy state')
        else:
            packet.__post_init__()
            if type(packet.solar_state) is not SolarAttitudeState or packet.solar_state.policy_identity!=solar.identity:raise ValueError('received solar policy binding')
            if packet.solar_state.held_target is not None and packet.solar_state.held_target.role!='ACTUAL':raise ValueError('forecast cannot become received solar observation')
    if state.solar_forecast is not None:
        if solar is None or type(state.solar_forecast) is not SolarAttitudeState or state.solar_forecast.policy_identity!=solar.identity or state.solar_forecast.clock_seconds>state.clock:raise ValueError('last paid solar estimate binding')
        state.solar_forecast.__post_init__()
    for n in ('next_occurrence','retired_frontier','next_action','transition_count'):integer(getattr(state,n),n)
    if not state.retired_frontier<=state.next_occurrence<=state.root.offered_population:raise ValueError('scenario frontier')
    from .lifecycle_contract import METHOD55
    if state.root.method==METHOD55:
        if type(state.pinned_requests) is not tuple or type(state.deferred_feedback) is not tuple:raise TypeError('immutable sparse causal retention')
        if len(state.active)+len(state.pinned_requests)>p.active_requests or len(state.deferred_feedback)>p.active_requests:raise ValueError('B55_CAUSAL_PIN_CAPACITY')
        active_ord=tuple(a.ordinal for a in state.active);pins=tuple(a.ordinal for a in state.pinned_requests)
        if active_ord!=tuple(sorted(set(active_ord))) or pins!=tuple(sorted(set(pins))) or set(active_ord)&set(pins):raise ValueError('sparse request duplicate/order')
        if any(not 0<=n<state.next_occurrence for n in (*active_ord,*pins)):raise ValueError('sparse request unreleased reference')
        if any(not(a.credit_reported or a.expired_reported) for a in state.pinned_requests):raise ValueError('causal pins require public disposition')
        if state.retired_frontier!=(min(active_ord) if active_ord else state.next_occurrence):raise ValueError('sparse public retirement frontier')
        if len({f.action_id for f in state.deferred_feedback})!=len(state.deferred_feedback):raise ValueError('duplicate untransmitted feedback')
        for f in state.deferred_feedback:
            if type(f) is not LifecycleDeferredFeedback:raise TypeError('exact genuine deferred feedback')
            f.__post_init__()
            if f.completed_at_seconds>state.clock or not any(i.action.action_id==f.action_id for i in state.intents):raise ValueError('deferred feedback lacks issued command/past boundary')
        for packet in (state.knowledge,*state.queued):
            packet.__post_init__()
            if packet.service_state is None:raise ValueError('B55 received packet requires sampled service state')
    else:
        if state.pinned_requests or state.deferred_feedback:raise ValueError('legacy lifecycle cannot import recovery causal state')
        if tuple(a.ordinal for a in state.active)!=tuple(range(state.retired_frontier,state.next_occurrence)):raise ValueError('active occurrence gap/duplicate')
    if len({p.ordinal for p in state.queued})!=len(state.queued):raise ValueError('feedback duplicate')
    if any(p.received_at_seconds<=state.clock for p in state.queued):raise ValueError('due feedback must be consumed')
    if state.knowledge.observed_at_seconds>state.clock or state.knowledge.received_at_seconds>state.clock:raise ValueError('future received knowledge')
    if state.physical.transition_count!=state.transition_count or state.work.transitions_completed!=state.transition_count:raise ValueError('transition work/physical frontier')
    if state.report.state['end_seconds']!=state.clock or state.report.state['next_transition']!=state.transition_count:raise ValueError('report/state frontier')
    if state.physical.nominal_provider is not state.actual_provider or state.physical.source_authority is not state.actual_world:raise ValueError('actual scope wiring')
    state.report.validate(prepared_runtime=actual_history_runtime)
    if state.root.environment_ageing_policy is not None:
        from .environment_ageing import digest
        actual_identity=(digest(state.physical.environment_ageing_state) if actual_history_runtime is None else actual_history_runtime.environment_state_identity(state.root.environment_ageing_policy,state.physical.environment_ageing_state,baseline))
        if state.report.state['environment_ageing']['end']['state_identity']!=actual_identity:raise ValueError('B61 report/actual frontier')
    if state.root.method==METHOD55:
        from .lifecycle_report import unpack
        work=state.physical.service_work
        if work.initial_transition_count or (work.initial_clock_seconds is not None and work.initial_clock_seconds!=state.root.start_seconds):
            raise ValueError('actual service ledger must retain original policy root frontier')
        rows=[row for row in (state.report.state['sealed_totals'],state.report.state['current']) if row is not None]
        for mode,name in (('NORMAL','normal_seconds'),('SAFE','safe_seconds'),('POWER_OFF','power_off_seconds'),('RECOVERY','recovery_seconds')):
            if sum((unpack(row['power_service']['mode_durations_seconds'][mode]) for row in rows),0)!=getattr(work,name):
                raise ValueError('report/actual selected mode-duration mismatch')
        for name in ('desired_normal_load_wh','commanded_load_wh','served_receiving_load_wh','commanded_shed_demand_wh','essential_unserved_wh'):
            if sum((unpack(row['power_service']['receiving_energy_wh'][name]) for row in rows),0)!=getattr(work,name):
                raise ValueError('report/actual selected receiving-energy mismatch')
        for report_name,work_name in (('mode_transitions','transitions'),('service_interruptions','service_interruptions'),('selected_steps','selected_steps')):
            if sum(row['power_service'][report_name] for row in rows)!=getattr(work,work_name):
                raise ValueError('report/actual selected service-counter mismatch')
        if sum((unpack(row['power_service']['boot_work_seconds']) for row in rows),0)!=work.boot_work_seconds:
            raise ValueError('report/actual paid boot support mismatch')
        if state.root.energy_attitude_policy is not None:
            from .solar_lifecycle import COUNTERS,QUANTITIES
            for name in COUNTERS:
                if sum(row['solar_attitude'][name] for row in rows)!=getattr(state.physical.solar_state,name):raise ValueError('report/actual solar counter mismatch')
            for name in QUANTITIES:
                if sum((unpack(row['solar_attitude'][name]) for row in rows),0)!=getattr(state.physical.solar_state,name):raise ValueError('report/actual paid solar support mismatch')
    if state.root.policy.quiet_solver is not None:
        from .lifecycle_quiet import quiet_work_type
        if type(state.forecast_quiet_work) is not quiet_work_type(state.root.policy.quiet_solver) or state.forecast_quiet_work is state.physical.quiet_work:
            raise ValueError('independent cumulative forecast quiet ledger')
        state.forecast_quiet_work.validate(state.root.policy.quiet_solver)
    elif state.forecast_quiet_work is not None:raise ValueError('unexpected quiet work in detailed lifecycle')
    if state.root.method!='B52_CHRONOLOGICAL_NOMINAL_ACK_GATED_V1':
        tally=state.actual_world.lighting_accounting()
        from .lifecycle_orbit import _qread
        if _qread(tally['end_seconds'])!=state.clock:
            raise ValueError('selected actual illumination frontier differs from physical clock')
    return state
