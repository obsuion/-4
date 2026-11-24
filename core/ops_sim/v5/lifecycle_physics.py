"""B52 compact, chronological physical transactions over accepted pure leaves.

This is a new owner, not a relaxed AdaptivePhysicalState.  It owns no old
command, outcome, forecast or original-orbit-prefix history.  Returned outcomes
are one-transaction evidence for immediate reporting, not retained state.

The caller owns the monotone scenario/action frontier and must retain delayed
knowledge references before authorizing retirement.  ``reported_through`` is an
explicit acknowledgement of that caller obligation, not a reconstruction proof.
Actual and forecast instances must have separate contexts, providers and work.
"""
from dataclasses import dataclass, replace, fields
from copy import deepcopy
from fractions import Fraction as Q
from hashlib import sha256
from math import ceil, degrees, isfinite

from .long_mission import (LongMissionAction, RuntimeWork,
    LongMissionActionForcing, MissionPhysicalCut, MissionContactForcing,
    _entry, _product, _Refusal, admit_operational_regime)
from .assembly_attitude import angle_between
from .assembly_attitude_3d import BodyAttitude3D
from .harness_hardware import compile_effective_hardware
from .harness_slew import plan_effective_slew
from .solar_attitude import EnergyAttitudePolicy,SolarAction,paid_sun_target,panel_axis,plan_axis_slew
from .solar_lifecycle import initial_solar_state,guard_solar_physical,advance_solar_state
from .construction_coupling import compile_construction
from .construction_physics import construction_physical_substep
from .construction_service import (ConstructionServicePolicy, ConstructionServiceWork,
    ConstructionServiceDiagnostic, ConstructionServiceDomainRefusal, service_physical_substep)
from .lifecycle_service import (PowerServicePolicy, PowerServiceState, PowerServiceWork,
    initial_service_state, select_service_mode, commit_service_step)
from .construction_contact import (execute_construction_contact_plan,
    ConstructionContactForcing, ConstructionContactRefusal)
from .design_trade_physics import ElectricalLimitError
from .eps_capability import compute_eps_capability
from .continuation import checked_checkpoint, ImagingAction
from .engine import _validate_completed_context
from .experiment_codec import canonical_copy
from .substepped_execution import _aggregate, _commit_action, _violations, _imaging_request
from .operational_protection import StandbyInputs, validate_policy
from .integration_time import RationalSeconds, IntegrationPolicy
from .degradation import SolarDegradationForcingInput
from .lifecycle_quiet import EnvironmentQuietIntegrationPolicy
from .environment_ageing import EnvironmentAgeingWork,EnvironmentAgeingState
from .environment_lifecycle import prepare_cut as prepare_environment_cut,commit_cut as commit_environment_cut,metrics as environment_metrics,complete_cut as complete_environment_cut
from .state import OperationalMode, FDIRState
from .adcs import CommonFrameBoresightDirection
from .ids import (ADCSBoresightFrameId, AcquisitionDataRecordId, GroundContactId,
                  ObservationOpportunityId)
from .observation import ObservationOpportunity, ObservationPointing
from .observation_feasibility import ObservationManeuverCandidate
from .imaging_feasibility import ObservationAcquisitionCandidate
from .imaging_execution import ScheduledObservationAcquisitionExecution
from .imaging_resources import AcquisitionEPSIntervalEnvironment
from .payload import OpticalAcquisitionInput, OpticalAcquisitionChannelSelection
from .ms_acquisition import InitialAttitudeEvidence
from .ms_product import (MSProductSpec, MSAcquisitionPlan, MSAcquisitionEvidence,
    MSProductAssessment, REQUIRED_MS_CHANNELS, size_ms_grid)
from .coupled_downlink import CoupledDownlinkInputs
from .communications import ServiceableGroundContact
from .contact_execution import ContactPlan, ConsumedContacts
from .onboard_data import OnboardAcquisitionDataRecord
from .lifecycle_quiet import (QuietIntegrationPolicy, QuietControllerState, QuietWork, quiet_work_for, quiet_work_type,
    QuietSample, QuietTrial, QuietTrialRefusal, integrate_quiet_hold)

from .battery_port import BatteryPortPolicy, BatteryPortState, BatteryPortWork, BatteryPortDomainError, ocv_resistance
from .battery_port_construction import PortServiceDiagnostic
from .lifecycle_quiet import BatteryQuietIntegrationPolicy

METHOD = 'B52_COMPACT_ACTUAL_PHYSICAL_V1'


def _admit_lifecycle_context(context, service_policy):
    """Explicit additive regime owner; legacy NORMAL-only guard is unchanged."""
    if service_policy is None:
        return admit_operational_regime(context)
    if type(service_policy) is not PowerServicePolicy:
        raise TypeError('exact recovery regime policy required')
    service_policy.__post_init__()
    onboard = context.spacecraft_state.onboard
    if (onboard.fdir_state not in (FDIRState.NORMAL, FDIRState.BACKUP) or
            onboard.operational_mode not in (OperationalMode.SAFE, OperationalMode.STANDBY,
                OperationalMode.IMAGING, OperationalMode.DOWNLINK, OperationalMode.MANEUVER)):
        raise ValueError('unsupported B55 onboard regime')
    marker = onboard.critical_energy_since_seconds
    if marker is not None and (type(marker) is not int or not 0 <= marker <= context.simulation_time_seconds):
        raise ValueError('invalid B55 sampled essential-service marker')


def _component_service_powers(diagnostic):
    names = tuple(field.name for field in fields(diagnostic.desired_loads))
    desired = sum((Q(getattr(diagnostic.desired_loads, name)) for name in names), Q())
    commanded = sum((Q(getattr(diagnostic.commanded_loads, name)) for name in names), Q())
    served = sum((Q(getattr(diagnostic.served_loads, name)) for name in names), Q())
    unmet = sum((Q(getattr(diagnostic.commanded_loads, name))-Q(getattr(diagnostic.served_loads, name))
                 for name in ('base_bus_w', 'obc_w')), Q())
    return desired, commanded, served, unmet


def _natural(value, name, maximum=2**48, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('strict lifecycle integer: '+name)


@dataclass(frozen=True, slots=True)
class LifecyclePhysicsLimits:
    """New cumulative allowances; units are reservations, not CPU operations.

    The old per-invocation class limits are unchanged.  There are no periodic
    resets or refunds, and local evidence/active-custody bounds are independent
    of these lifetime counters.  Admission does not prove a horizon affordable.
    """
    max_actions: int = 2**24
    max_active_products: int = 32
    max_physical_substeps: int = 2**30
    max_runtime_upstream_entries: int = 2**20
    max_runtime_entries: int = 2**20
    max_nominal_orbit_queries: int = 2**32
    max_point_geometry_queries: int = 2**30
    max_interval_seconds: int = 30
    detailed_interval_seconds: int = 2
    max_action_cells: int = 256
    contact_integration_level: int = 2
    max_document_bytes: int = 64*2**20
    max_retained_cuts: int = 256
    max_geometry_queries: int = 1
    max_geometry_operations: int = 1
    max_geometry_control_units: int = 1
    max_spatial_reserved_units: int = 2**46
    max_nominal_force_reserved: int = 2**32
    max_nominal_control_units: int = 2**46
    max_index_control_units: int = 2**46
    max_output_control_units: int = 2**46
    max_construction_line_calls: int = 2**34
    max_construction_compilations: int = 2**24
    max_construction_control_units: int = 2**46
    max_harness_compilations: int = 2**24
    max_harness_control_units: int = 2**46
    method: str = 'B52_CUMULATIVE_PHYSICAL_ALLOWANCES_V1'

    def __post_init__(self):
        for field in fields(self):
            if field.name != 'method':
                _natural(getattr(self, field.name), field.name, minimum=0 if field.name == 'contact_integration_level' else 1)
        if self.method != 'B52_CUMULATIVE_PHYSICAL_ALLOWANCES_V1':
            raise ValueError('unsupported lifecycle physical allowance method')
        if self.max_active_products > 32 or self.max_action_cells > 512 or self.max_retained_cuts > 512:
            raise ValueError('bounded local custody/evidence required')
        if self.max_interval_seconds > 120 or self.detailed_interval_seconds > 10 or self.contact_integration_level > 4:
            raise ValueError('local physical numerical policy outside admission')
        if self.max_document_bytes > 64*2**20:
            raise ValueError('lifecycle physical bytes exceed 64 MiB')


@dataclass(frozen=True, slots=True)
class LifecycleConstructionLimits:
    max_line_calls: int
    max_compilations: int
    max_control_units: int
    method: str = 'B52_CUMULATIVE_CONSTRUCTION_WORK_V1'

    def __post_init__(self):
        for name in ('max_line_calls', 'max_compilations', 'max_control_units'):
            _natural(getattr(self, name), name, minimum=1)
        if self.method != 'B52_CUMULATIVE_CONSTRUCTION_WORK_V1':
            raise ValueError('unsupported cumulative construction work')


@dataclass(slots=True)
class LifecycleConstructionWork:
    line_calls_reserved: int = 0
    line_calls_returned: int = 0
    line_calls_refused: int = 0
    line_work_unknown: int = 0
    compilation_calls: int = 0
    control_units: int = 0
    reconstruction_count: int = 0

    def validate(self, limits):
        limits.__post_init__()
        for field in fields(self):
            _natural(getattr(self, field.name), field.name)
        if (self.line_calls_reserved > limits.max_line_calls or
                self.compilation_calls > limits.max_compilations or
                self.control_units > limits.max_control_units):
            raise ValueError('cumulative lifecycle construction quota')
        if self.line_calls_returned+self.line_calls_refused+self.line_work_unknown > self.line_calls_reserved:
            raise ValueError('construction work exceeds paid reservation')

    def reserve_lines(self, count, limits):
        self.validate(limits); _natural(count, 'line reservation')
        if self.line_calls_reserved+count > limits.max_line_calls:
            raise ValueError('LIFECYCLE_CONSTRUCTION_LINE_QUOTA')
        self.line_calls_reserved += count

    def reserve_compile(self, limits):
        self.validate(limits)
        if self.compilation_calls+1 > limits.max_compilations or self.control_units+32768 > limits.max_control_units:
            raise ValueError('LIFECYCLE_CONSTRUCTION_COMPILATION_QUOTA')
        self.compilation_calls += 1; self.control_units += 32768


@dataclass(slots=True)
class LifecycleHarnessWork:
    max_compilations: int
    max_control_units: int
    compilation_calls: int = 0
    control_reserved_units: int = 0
    reconstruction_count: int = 0

    def validate(self, policy):
        policy.__post_init__()
        for field in fields(self):
            _natural(getattr(self, field.name), field.name)
        if (self.compilation_calls > self.max_compilations or self.control_reserved_units > self.max_control_units or
                self.control_reserved_units != self.compilation_calls*policy.control_units_per_compile):
            raise ValueError('cumulative lifecycle harness quota/accounting')

    def reserve_compile(self, policy):
        self.validate(policy)
        if (self.compilation_calls+1 > self.max_compilations or
                self.control_reserved_units+policy.control_units_per_compile > self.max_control_units):
            raise ValueError('LIFECYCLE_HARNESS_COMPILATION_QUOTA')
        self.compilation_calls += 1
        self.control_reserved_units += policy.control_units_per_compile


@dataclass(frozen=True, slots=True)
class LifecyclePhysicalModel:
    base: object
    environment: object
    limits: LifecyclePhysicsLimits = LifecyclePhysicsLimits()
    simulation_inputs: object = None
    method: str = METHOD
    quiet_policy: QuietIntegrationPolicy | None = None
    service_policy: PowerServicePolicy | None = None
    energy_attitude_policy: EnergyAttitudePolicy | None = None
    battery_port_policy: BatteryPortPolicy | None = None
    environment_ageing_policy: object | None = None

    def __post_init__(self):
        if type(self.limits) is not LifecyclePhysicsLimits or self.method != METHOD:
            raise ValueError('explicit lifecycle physical model required')
        self.limits.__post_init__()
        if self.service_policy is not None:
            if type(self.service_policy) is not PowerServicePolicy:
                raise TypeError('explicit construction recovery policy required')
            self.service_policy.__post_init__()
        if self.energy_attitude_policy is not None:
            if type(self.energy_attitude_policy) is not EnergyAttitudePolicy or self.service_policy is None:raise TypeError('explicit solar policy requires construction power service')
            self.energy_attitude_policy.__post_init__()
        if self.battery_port_policy is not None:
            if type(self.battery_port_policy)is not BatteryPortPolicy or self.service_policy is None:raise TypeError('port requires service model')
            self.battery_port_policy.__post_init__()
            if self.quiet_policy is not None and type(self.quiet_policy) not in (BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy):raise ValueError('unit-aware port numerics')
        if self.quiet_policy is not None:
            if type(self.quiet_policy) not in (QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy):
                raise TypeError('explicit versioned quiet policy required')
            self.quiet_policy.__post_init__()
        if self.environment_ageing_policy is not None:
            from .environment_ageing import admit_network
            admit_network(self.base.simulation_inputs.spacecraft_configuration.thermal.network,self.environment_ageing_policy)
            if self.quiet_policy is not None and type(self.quiet_policy)is not EnvironmentQuietIntegrationPolicy:raise ValueError('B61 unit-aware quiet required')
        if self.simulation_inputs is None:
            object.__setattr__(self, 'simulation_inputs', self.base.simulation_inputs)
        if self.environment.mode != 'NOMINAL_LONG':
            raise ValueError('lifecycle physical owner is nominal only')
        if self.environment.end_seconds > self.simulation_inputs.common_world.horizon_seconds:
            raise ValueError('new simulation world must cover lifecycle horizon')
        if self.simulation_inputs.spacecraft_configuration != self.base.simulation_inputs.spacecraft_configuration:
            raise ValueError('hardware/configuration authority changed in world adapter')
        if self.simulation_inputs.coast_orbit is not None or self.simulation_inputs.common_world.event_ids:
            raise ValueError('lifecycle world alone owns event-free orbit authority')

    def __getattr__(self, name):
        return getattr(self.base, name)

    @property
    def geometry_mode(self):
        return 'NOMINAL_LONG'

    @property
    def construction_limits(self):
        p = self.limits
        return LifecycleConstructionLimits(p.max_construction_line_calls, p.max_construction_compilations,
                                           p.max_construction_control_units)


@dataclass(frozen=True, slots=True)
class LifecyclePhysicalInputs:
    model: LifecyclePhysicalModel
    products: tuple

    def __getattr__(self, name):
        return getattr(self.model, name)


@dataclass(frozen=True, slots=True)
class LifecycleConstructionBinding:
    compilation: object
    work: LifecycleConstructionWork


@dataclass(frozen=True, slots=True)
class LifecycleHarnessBinding:
    hardware: object
    work: LifecycleHarnessWork


@dataclass(frozen=True, slots=True)
class LifecycleReceipt:
    """Compact completion witness derived only from returned actual service."""
    record: object
    completing_contact: ServiceableGroundContact
    completion_seconds: Q

    def __post_init__(self):
        if type(self.record) is not OnboardAcquisitionDataRecord or type(self.completing_contact) is not ServiceableGroundContact:
            raise TypeError('exact actual record/completing contact required')
        self.record.__post_init__(); self.completing_contact.__post_init__()
        if type(self.completion_seconds) is not Q or not (
                self.completing_contact.start_time_seconds < self.completion_seconds <=
                self.completing_contact.end_time_seconds):
            raise ValueError('receipt time outside completing service')

    @property
    def record_id(self): return self.record.record_id
    @property
    def request_id(self): return self.record.imaging_request_id


@dataclass(frozen=True, slots=True)
class PendingLifecycleAction:
    action: LongMissionAction
    origin_seconds: int
    end_seconds: int
    original_attitude: BodyAttitude3D
    slew: object = None
    geometry: tuple = ()
    acquired_record: object = None
    acquisition_plan: object = None
    payload_w: float = 0.
    solar_target: object | None = None

    @property
    def kind(self): return self.action.kind


@dataclass(frozen=True, slots=True)
class LifecycleRefusalDetail:
    """Actual returned acquisition-owner evidence, never a guessed forecast."""
    stage: str
    code: str
    owner: str
    evaluated_calls: tuple
    quantities: tuple
    method: str = 'B53_ACTUAL_ACQUISITION_REFUSAL_V1'

    def __post_init__(self):
        if (self.stage not in ('VIEW', 'SETTLING', 'STORAGE') or
                type(self.code) is not str or not self.code or len(self.code) > 100 or
                type(self.owner) is not str or not self.owner or len(self.owner) > 200 or
                self.method != 'B53_ACTUAL_ACQUISITION_REFUSAL_V1'):
            raise ValueError('strict actual acquisition refusal identity')
        if type(self.evaluated_calls) is not tuple or not 1 <= len(self.evaluated_calls) <= 8:
            raise ValueError('bounded acquisition owner-call evidence required')
        names = []
        for name, count in self.evaluated_calls:
            if type(name) is not str or not name or len(name) > 100:
                raise ValueError('named acquisition owner call required')
            _natural(count, 'acquisition call count', maximum=2, minimum=1); names.append(name)
        if len(set(names)) != len(names): raise ValueError('duplicate acquisition owner call')
        if type(self.quantities) is not tuple or len(self.quantities) > 12:
            raise ValueError('bounded acquisition refusal quantities required')
        names = []
        for name, value in self.quantities:
            if (type(name) is not str or not name or len(name) > 100 or
                    type(value) not in (str, int, float) or
                    type(value) is str and len(value) > 200 or
                    type(value) in (int, float) and not isfinite(value)):
                raise ValueError('finite acquisition refusal quantity required')
            names.append(name)
        if len(set(names)) != len(names): raise ValueError('duplicate acquisition refusal quantity')


@dataclass(frozen=True, slots=True)
class LifecycleActionOutcome:
    action_id: str
    kind: str
    status: str
    reason: str | None
    start_seconds: int
    end_seconds: int
    geometry: tuple
    cuts: tuple
    contact_outcomes: tuple
    acquired_record: object
    acquisition_plan: object
    attitude: BodyAttitude3D
    accounting: object
    slew: object = None
    contact_forcing: tuple = ()
    failure_diagnostic: tuple = ()
    method: str = METHOD
    refusal_detail: LifecycleRefusalDetail | None = None
    service_work_before: PowerServiceWork | None = None
    service_work_after: PowerServiceWork | None = None
    service_state_after: PowerServiceState | None = None
    solar_target: object | None = None
    solar_state_before: object | None = None
    solar_state_after: object | None = None
    battery_port_state_before: object | None = None
    battery_port_state_after: object | None = None
    environment_ageing_state_before: object | None = None
    environment_ageing_state_after: object | None = None

    @property
    def continuous_geometry(self):
        # Explicit absence, never an acquired interval certificate.
        return None


@dataclass(slots=True)
class LifecyclePhysicalState:
    inputs: LifecyclePhysicalInputs
    context: object
    attitude: BodyAttitude3D
    runtime_work: RuntimeWork
    nominal_provider: object
    source_authority: object
    construction: LifecycleConstructionBinding
    harness: LifecycleHarnessBinding
    acquisitions: tuple = ()
    receipts: tuple = ()
    consumed_through_seconds: int = 0
    transition_count: int = 0
    completed_actions: int = 0
    pending: PendingLifecycleAction | None = None
    reported_through_seconds: int = 0
    quiet_controller: QuietControllerState | None = None
    quiet_work: QuietWork | None = None
    static_admission: object | None = None
    prepared_runtime: object | None = None
    backend_context: object | None = None
    service_state: PowerServiceState | None = None
    service_work: PowerServiceWork | None = None
    service_allocation_work: ConstructionServiceWork | None = None
    last_service_diagnostic: ConstructionServiceDiagnostic | None = None
    solar_state: object | None = None
    battery_port_state: BatteryPortState | None = None
    battery_port_work: BatteryPortWork | None = None
    environment_ageing_state: EnvironmentAgeingState | None = None
    environment_ageing_work: EnvironmentAgeingWork | None = None


def _checked_lifecycle_checkpoint(state, context):
    """Versioned wrapper; accepted legacy helper and all physics stay intact."""
    if state.static_admission is None:
        return checked_checkpoint(context)
    from .lifecycle_admission import AdmittedInputs
    if type(state.static_admission) is not AdmittedInputs:
        raise TypeError('exact local static admission required')
    state.static_admission.guard(context.inputs,role=state.nominal_provider.role)
    return state.static_admission.checked_checkpoint(context)


def _validate_products(products, limits):
    if type(products) is not tuple or len(products) > limits.max_active_products:
        raise ValueError('LIFECYCLE_ACTIVE_PRODUCT_CAPACITY')
    for product in products:
        if type(product) is not MSProductSpec:
            raise TypeError('exact active MS product required')
        product.__post_init__()
    if len({p.request.request_id for p in products}) != len(products):
        raise ValueError('duplicate active request')


def start_lifecycle_physical(model, context, attitude, products, nominal_provider, source_authority,
                             *, runtime_work=None, consumed_through_seconds=None,
                             acquisitions=(), receipts=(), pending=None,
                             quiet_controller=None, quiet_work=None, static_admission=None,
                             service_state=None, service_work=None, service_allocation_work=None,
                              last_service_diagnostic=None,solar_state=None,battery_port_state=None,battery_port_work=None,environment_ageing_state=None,environment_ageing_work=None):
    if type(model) is not LifecyclePhysicalModel or type(attitude) is not BodyAttitude3D:
        raise TypeError('new lifecycle physical model and exact 3D pose required')
    model.__post_init__(); attitude.__post_init__()
    if context.inputs != model.simulation_inputs or attitude.at_seconds != context.simulation_time_seconds:
        raise ValueError('lifecycle world/context/pose mismatch')
    _validate_products(products, model.limits)
    if static_admission is None: checked_checkpoint(context)
    else:
        from .lifecycle_admission import AdmittedInputs
        if type(static_admission) is not AdmittedInputs:raise TypeError('exact local static admission')
        static_admission.guard(context.inputs,role=nominal_provider.role)
        static_admission.checked_checkpoint(context)
    validate_policy(model.protection, context); _admit_lifecycle_context(context, model.service_policy)
    rt = RuntimeWork() if runtime_work is None else runtime_work
    if type(rt) is not RuntimeWork: raise TypeError('exact runtime work required')
    rt.charge('runtime_entries', 1, model.limits)
    cw = LifecycleConstructionWork(); cw.reserve_compile(model.construction_limits)
    compilation = compile_construction(model.assembly, model.configuration)
    hw = LifecycleHarnessWork(model.limits.max_harness_compilations, model.limits.max_harness_control_units)
    hw.reserve_compile(model.augmentation.policy)
    hardware = compile_effective_hardware(model.assembly, model.capabilities, model.actuator,
                                           model.configuration, model.augmentation)
    t = context.simulation_time_seconds
    frontier = t if consumed_through_seconds is None else consumed_through_seconds
    _natural(frontier, 'consumed frontier', maximum=t)
    if model.quiet_policy is None:
        if quiet_controller is not None or quiet_work is not None:
            raise ValueError('quiet restart/forecast state requires an explicit policy')
    else:
        if quiet_controller is None:
            quiet_controller = QuietControllerState(Q(t), model.quiet_policy.maximum_macro_seconds,method=model.quiet_policy.method)
        if quiet_work is None: quiet_work = quiet_work_for(model.quiet_policy)
        if type(quiet_controller) is not QuietControllerState or type(quiet_work) is not quiet_work_type(model.quiet_policy):
            raise TypeError('exact restart/forecast quiet controller and work required')
        quiet_controller.validate(model.quiet_policy, clock=t)
        quiet_work.validate(model.quiet_policy)
    if model.environment_ageing_policy is not None:
        from .environment_ageing import initial_state,retention
        if environment_ageing_state is None:
            environment_ageing_state=initial_state(model.environment_ageing_policy,t,context.inputs.spacecraft_configuration.thermal.network,context.spacecraft_state.degradation.solar.generation_retention)
            context.spacecraft_state.degradation.solar.generation_retention=retention(model.environment_ageing_policy,environment_ageing_state)
        if environment_ageing_work is None:environment_ageing_work=EnvironmentAgeingWork()
    state = LifecyclePhysicalState(LifecyclePhysicalInputs(model, products), context, attitude, rt,
        nominal_provider, source_authority, LifecycleConstructionBinding(compilation, cw),
        LifecycleHarnessBinding(hardware, hw), acquisitions=acquisitions, receipts=receipts,
        consumed_through_seconds=frontier, pending=pending, reported_through_seconds=t,
        quiet_controller=quiet_controller, quiet_work=quiet_work,static_admission=static_admission,
        service_state=(initial_service_state(Q(t)) if model.service_policy is not None and service_state is None else service_state),
        service_work=(PowerServiceWork() if model.service_policy is not None and service_work is None else service_work),
        service_allocation_work=(ConstructionServiceWork() if model.service_policy is not None and service_allocation_work is None else service_allocation_work),
        last_service_diagnostic=last_service_diagnostic,environment_ageing_state=environment_ageing_state,environment_ageing_work=environment_ageing_work,
        battery_port_state=(BatteryPortState(Q(t),resistance_damage=model.battery_port_policy.initial_resistance_damage) if model.battery_port_policy is not None and battery_port_state is None else battery_port_state),
        battery_port_work=(BatteryPortWork() if model.battery_port_policy is not None and battery_port_work is None else battery_port_work),
        solar_state=(initial_solar_state(model.energy_attitude_policy,t) if model.energy_attitude_policy is not None and solar_state is None else solar_state))
    guard_lifecycle_physical(state)
    return state


def guard_lifecycle_physical(state):
    """Bounded admission: neither history scan nor recompilation/hash of prefix."""
    if type(state) is not LifecyclePhysicalState or type(state.inputs) is not LifecyclePhysicalInputs:
        raise TypeError('compact lifecycle physical state required')
    if state.inputs.environment_ageing_policy is None:
        if state.environment_ageing_state is not None or state.environment_ageing_work is not None:raise ValueError('legacy cannot import B61 ageing state')
    else:
        from .environment_ageing import guard,retention
        guard(state.inputs.environment_ageing_policy,state.environment_ageing_state,state.context.inputs.spacecraft_configuration.thermal.network,state.context.simulation_time_seconds)
        if type(state.environment_ageing_work)is not EnvironmentAgeingWork:raise TypeError('B61 exact paid work')
        state.environment_ageing_work.validate(state.inputs.environment_ageing_policy)
        if state.context.spacecraft_state.degradation.solar.generation_retention!=retention(state.inputs.environment_ageing_policy,state.environment_ageing_state):raise ValueError('B61 PV/history consistency')
        if state.environment_ageing_state.calendar_seconds!=Q(state.inputs.environment_ageing_policy.initial_calendar_seconds)+state.environment_ageing_state.clock_seconds-state.inputs.environment.start_seconds:raise ValueError('B61 elapsed calendar authority')
    p = state.inputs.limits
    if state.static_admission is not None:
        from .lifecycle_admission import AdmittedInputs
        if type(state.static_admission) is not AdmittedInputs:raise TypeError('exact local static admission')
        state.static_admission.guard(state.context.inputs,role=state.nominal_provider.role)
    _validate_products(state.inputs.products, p)
    if state.context.inputs != state.inputs.simulation_inputs:
        raise ValueError('foreign lifecycle context authority')
    if state.attitude.at_seconds != state.context.simulation_time_seconds:
        raise ValueError('stale lifecycle attitude')
    state.attitude.__post_init__(); _validate_completed_context(state.context)
    state.runtime_work.validate(p)
    state.construction.work.validate(state.inputs.construction_limits)
    state.harness.work.validate(state.inputs.augmentation.policy)
    if state.inputs.battery_port_policy is None:
        if state.battery_port_state is not None or state.battery_port_work is not None:raise ValueError('port history requires explicit model')
    else:
        if type(state.battery_port_state)is not BatteryPortState or type(state.battery_port_work)is not BatteryPortWork:raise TypeError('port history/work required')
        state.battery_port_state.__post_init__();state.battery_port_work.validate()
        if state.battery_port_state.clock_seconds!=Q(state.context.simulation_time_seconds):raise ValueError('port/physical clock mismatch')
        if state.battery_port_state.resistance_damage>state.inputs.battery_port_policy.maximum_resistance_damage:raise ValueError('port damage outside declared domain')
        if state.nominal_provider.role=='ACTUAL' and (state.service_work is None or state.battery_port_state.selected_steps!=state.service_work.selected_steps or state.battery_port_work.ageing_returned<state.battery_port_state.selected_steps):raise ValueError('selected actual port/service history mismatch')
    if state.inputs.service_policy is None:
        if any(value is not None for value in (state.service_state, state.service_work,
                state.service_allocation_work, state.last_service_diagnostic)):
            raise ValueError('service state requires its explicit recovery policy')
    else:
        if (type(state.service_state) is not PowerServiceState or
                type(state.service_work) is not PowerServiceWork or
                type(state.service_allocation_work) is not ConstructionServiceWork):
            raise TypeError('persisted selected service state and paid allocation work required')
        state.service_state.__post_init__(); state.service_work.__post_init__()
        state.service_allocation_work.validate()
        if state.service_state.clock_seconds != Q(state.context.simulation_time_seconds):
            raise ValueError('service/physical clock mismatch')
        if state.service_work.through_seconds is not None and state.service_work.through_seconds != state.service_state.clock_seconds:
            raise ValueError('service ledger/physical frontier mismatch')
        if state.service_work.initial_transition_count+state.service_work.transitions != state.service_state.transition_count:
            raise ValueError('service ledger/physical transition mismatch')
        if state.last_service_diagnostic is not None and type(state.last_service_diagnostic) not in (ConstructionServiceDiagnostic,PortServiceDiagnostic):
            raise TypeError('exact last selected service diagnostic required')
        if state.last_service_diagnostic is not None:
            state.last_service_diagnostic.__post_init__()
            if (state.last_service_diagnostic.end_seconds != state.service_state.clock_seconds or
                    state.last_service_diagnostic.selected_electrical.compilation_digest !=
                    state.construction.compilation.configuration_digest):
                raise ValueError('last selected service diagnostic clock/construction binding mismatch')
    if state.inputs.quiet_policy is None:
        if state.quiet_controller is not None or state.quiet_work is not None:
            raise ValueError('quiet state requires its explicit numerical policy')
    else:
        if type(state.quiet_controller) is not QuietControllerState or type(state.quiet_work) is not quiet_work_type(state.inputs.quiet_policy):
            raise TypeError('persisted quiet controller and cumulative work required')
        state.quiet_controller.validate(state.inputs.quiet_policy, clock=state.context.simulation_time_seconds)
        state.quiet_work.validate(state.inputs.quiet_policy)
    if (state.harness.work.max_compilations != p.max_harness_compilations or
            state.harness.work.max_control_units != p.max_harness_control_units):
        raise ValueError('changed cumulative harness allowances')
    for name in ('transition_count', 'completed_actions', 'consumed_through_seconds', 'reported_through_seconds'):
        _natural(getattr(state, name), name)
    if state.completed_actions > p.max_actions or state.transition_count < state.completed_actions:
        raise ValueError('lifecycle action allowance/accounting')
    if max(state.consumed_through_seconds, state.reported_through_seconds) > state.context.simulation_time_seconds:
        raise ValueError('future custody/report frontier')
    active = {p.request.request_id for p in state.inputs.products}
    if type(state.acquisitions) is not tuple or type(state.receipts) is not tuple:
        raise TypeError('immutable bounded active evidence required')
    for acquisition in state.acquisitions:
        if type(acquisition) is not MSAcquisitionEvidence:
            raise TypeError('exact acquisition association required')
        acquisition.__post_init__()
    if any(e.plan.request.request_id not in active for e in state.acquisitions):
        raise ValueError('orphan active acquisition')
    if len(state.acquisitions) > p.max_active_products or len(state.receipts) > p.max_active_products:
        raise ValueError('LIFECYCLE_ACTIVE_CUSTODY_CAPACITY')
    if len({e.record.record_id for e in state.acquisitions}) != len(state.acquisitions):
        raise ValueError('duplicate active acquisition')
    if len({r.record_id for r in state.receipts}) != len(state.receipts):
        raise ValueError('duplicate compact receipt')
    acquired = {e.record.record_id: e.record for e in state.acquisitions}
    custody = state.context.ground_data_delivery_state
    stored = state.context.spacecraft_state.data_storage.stored_records
    if max(len(stored), len(custody.partial_transfers), len(custody.completed_deliveries)) > p.max_active_products:
        raise ValueError('LIFECYCLE_ACTIVE_CUSTODY_CAPACITY')
    if any(record.record_id not in acquired or acquired[record.record_id] != record for record in stored):
        raise ValueError('onboard record lacks active acquisition association')
    delivered = {d.record.record_id: d for d in custody.completed_deliveries}
    for receipt in state.receipts:
        if type(receipt) is not LifecycleReceipt: raise TypeError('exact lifecycle receipt required')
        receipt.__post_init__()
        delivery = delivered.get(receipt.record_id)
        if (acquired.get(receipt.record_id) != receipt.record or delivery is None or
                delivery.record != receipt.record or delivery.completing_contact != receipt.completing_contact):
            raise ValueError('receipt differs from actual active custody')
    if set(delivered) != {r.record_id for r in state.receipts}:
        raise ValueError('completed custody lacks exact compact receipt')
    if state.pending is not None:
        pending = state.pending
        if type(pending) is not PendingLifecycleAction or type(pending.action) not in ((LongMissionAction,SolarAction) if state.inputs.energy_attitude_policy is not None else (LongMissionAction,)):
            raise TypeError('exact pending lifecycle action required')
        pending.action.__post_init__(); pending.original_attitude.__post_init__()
        _natural(pending.origin_seconds, 'pending origin'); _natural(pending.end_seconds, 'pending end')
        if not (pending.origin_seconds <= state.context.simulation_time_seconds < pending.end_seconds):
            raise ValueError('stale pending physical action')
        if pending.original_attitude.at_seconds != pending.origin_seconds:
            raise ValueError('pending origin/pose mismatch')
        if pending.kind in ('POINT','SOLAR_POINT'):
            if (pending.slew is None or pending.slew.initial != pending.original_attitude or
                    pending.end_seconds != pending.origin_seconds+pending.slew.duration_seconds):
                raise ValueError('pending POINT must retain original full paid plan')
        elif pending.end_seconds != (pending.action.until_seconds if pending.kind in ('HOLD_UNTIL','SOLAR_HOLD') else pending.origin_seconds+pending.action.duration_seconds):
            raise ValueError('pending physical duration changed')
    _admit_lifecycle_context(state.context, state.inputs.service_policy)
    guard_solar_physical(state)


def _forcing(state, hardware, a, b, quaternion, *, adcs_w=0., payload_w=0.):
    schedule = state.source_authority.schedule(Q(a), Q(b))
    if not schedule.cells or any(c.assessment == 'UNRESOLVED' for c in schedule.cells):
        raise _Refusal('UNRESOLVED_ILLUMINATION')
    incidence, camera, panel = state.source_authority.orientation_inputs(hardware, (Q(a)+Q(b))/2, quaternion)
    from .environment_forcing import _case
    cases = []
    for cell in schedule.cells:
        profile = state.inputs.environment.profile[cell.profile_index]
        profile = replace(profile, incidence_angle_deg=incidence,
            loads=replace(profile.loads, adcs_w=profile.loads.adcs_w+adcs_w,
                          payload_w=profile.loads.payload_w+payload_w))
        cases.append(_case(profile, cell.assessment == 'ILLUMINATED'))
    if any(case != cases[0] for case in cases[1:]):
        raise ValueError('physical cut crosses forcing change')
    case = cases[0]
    return LongMissionActionForcing(case.eps_inputs.load_breakdown, case.sunlit, incidence,
        state.inputs.routing, case.thermal_inputs, case.heat_source_inputs), case.eps_inputs, camera, panel, tuple(c.support_index for c in schedule.cells)


def quiet_step_limit(state, proposed_seconds, detailed_seconds=2):
    """Conservative detailed fallback, not a certified wider thermal macrostep.

    A fixed 60-second dispatch chunk does not authorize one 60-second thermal
    step.  No wide bound for nonlinear radiation/electrical and capacity
    protection is established here, so every actual quiet physical step uses
    the same explicitly admitted detailed maximum.  Source/event cuts may
    shorten it further.  This is a nominal sampled policy, not continuous
    threshold safety or event-time accuracy.
    """
    _natural(proposed_seconds, 'proposed quiet step', maximum=120, minimum=1)
    _natural(detailed_seconds, 'detailed quiet fallback', maximum=10, minimum=1)
    return min(proposed_seconds, detailed_seconds)


def _partition(state, a, b, *, pending=None, reserve=True):
    schedule = state.source_authority.schedule(Q(a), Q(b))
    if any(c.assessment == 'UNRESOLVED' and c.end_seconds > c.start_seconds for c in schedule.cells):
        raise _Refusal('UNRESOLVED_ILLUMINATION')
    points = {Q(a), Q(b)} | {x for c in schedule.cells for x in (c.start_seconds, c.end_seconds)}
    if pending is not None and pending.slew is not None:
        points |= {Q(pending.origin_seconds)+x for x in pending.slew.cuts()
                   if Q(a) < Q(pending.origin_seconds)+x < Q(b)}
    cuts = []
    maximum = (quiet_step_limit(state, state.inputs.limits.max_interval_seconds,
                               state.inputs.limits.detailed_interval_seconds)
               if pending is None or pending.kind in ('HOLD_UNTIL','SOLAR_HOLD')
               else state.inputs.limits.detailed_interval_seconds)
    for left, right in zip(sorted(points), sorted(points)[1:]):
        n = ceil((right-left)/maximum)
        if len(cuts)+n > min(state.inputs.limits.max_action_cells, state.inputs.limits.max_retained_cuts):
            raise _Refusal('LIFECYCLE_LOCAL_ACTION_PARTITION_LIMIT')
        cuts.extend((left+(right-left)*Q(i, n), left+(right-left)*Q(i+1, n)) for i in range(n))
    if reserve: state.runtime_work.charge('physical_reserved_calls', len(cuts), state.inputs.limits)
    return tuple(cuts)


def _physical_piece(state, candidate, hardware, a, b, pending):
    required = state.inputs.protection.imaging_node_ids if pending.kind in ('POINT', 'CAPTURE') else state.inputs.protection.standby_node_ids
    if _violations(candidate, required): raise _Refusal('OPERATING_TEMPERATURE_AT_START')
    cuts = []; parts = []; slew = pending.slew; environment_history=state.environment_ageing_state
    for left, right in _partition(state, a, b, pending=pending):
        midpoint = (left+right)/2
        quaternion = state.attitude.quaternion if slew is None else slew.quaternion_at(midpoint-Q(pending.origin_seconds))
        k0 = k1 = Q(0); draw = adjustment = 0.
        if slew is not None:
            k0 = slew.kinetic_j(left-Q(pending.origin_seconds)); k1 = slew.kinetic_j(right-Q(pending.origin_seconds))
            storage = float((k1-k0)/(right-left))
            draw = hardware.actuator.electronics_power_w+max(0., storage)/hardware.actuator.drive_efficiency
            adjustment = -storage
        forcing, eps, camera, panel, supports = _forcing(state, hardware, left, right, quaternion,
                                                       adcs_w=draw, payload_w=pending.payload_w)
        loss = 0. if state.inputs.environment_ageing_policy is not None else state.inputs.solar_retention_loss_per_second*float(right-left)
        solar = None if loss == 0 else SolarDegradationForcingInput(loss)
        binding,next_environment=prepare_environment_cut(state,candidate,environment_history,left,right,forcing)
        physical_leaf=construction_physical_substep
        extra={}
        if binding is not None:
            from .environment_thermal import construction_environment_substep
            physical_leaf=construction_environment_substep;extra['environment_binding']=binding
        try:
            part, result = physical_leaf(candidate, RationalSeconds.from_fraction(right-left),
                forcing, eps, state.inputs.protection, solar, compilation=state.construction.compilation,
                work=state.construction.work, limits=state.inputs.construction_limits, standby=False,
                internal_heat_adjustments_w=None if slew is None else
                    ((candidate.inputs.spacecraft_configuration.thermal.network.bus_node_id, adjustment),),**extra)
        except ElectricalLimitError as error:
            raise _Refusal('CONSTRUCTION_ELECTRICAL_REFUSED:'+str(error)) from error
        except BaseException:
            state.runtime_work.physical_work_unknown_events += 1
            raise
        state.runtime_work.physical_completed_calls += 1
        if part is None: raise _Refusal('FULL_ELECTRICAL_SERVICE_UNAVAILABLE')
        part=complete_environment_cut(candidate,state.inputs.environment_ageing_policy,environment_history,next_environment,part)
        environment_history=next_environment
        cuts.append(MissionPhysicalCut(left, right, supports, forcing.incidence_angle_deg, camera, panel,
            float(k0), float(k1), draw, adjustment, part, quaternion,
            None if slew is None else slew.euler_at(midpoint-Q(pending.origin_seconds)), k0, k1))
        parts.append(part)
        if _violations(candidate, required):
            raise _Refusal('OPERATING_TEMPERATURE_AT_ENDPOINT',
                           diagnostic=('PAID_PRIVATE_ENDPOINT_NOT_PUBLISHED', right, part))
    return tuple(cuts), _aggregate(tuple(parts)),environment_history


def _quiet_clone_context(context):
    """Copy bounded dynamic state; immutable, already admitted inputs stay shared.

    The accepted coupled substep changes physical state only. All mutable runtime
    records are still copied, so discarded full/half proposals cannot alias the
    published context. This avoids copying/revalidating immutable model graphs
    for each trial; it does not disable any leaf validation.
    """
    return deepcopy(context, {id(context.inputs): context.inputs})


@dataclass(slots=True)
class _ServiceCandidate:
    """Private physical AND selected-mode transaction; never a shared cache."""
    context: object
    service_state: PowerServiceState
    service_work: PowerServiceWork
    last_service_diagnostic: ConstructionServiceDiagnostic | None = None
    battery_port_state: BatteryPortState | None = None
    environment_ageing_state: EnvironmentAgeingState | None = None


def _service_candidate(state, context):
    return _ServiceCandidate(context, state.service_state, state.service_work,
                             state.last_service_diagnostic,state.battery_port_state,state.environment_ageing_state)


def _clone_service_candidate(value):
    return replace(value, context=_quiet_clone_context(value.context))


def _service_leaf(state, private, hardware, left, right, pending, *, stationary=True):
    """One paid proposal; caller selects this whole bundle or discards it."""
    context = private.context
    capacity = compute_eps_capability(context.inputs.spacecraft_configuration.eps,
                                      context.spacecraft_state.degradation).battery_usable_capacity_wh
    decision = select_service_mode(state.inputs.service_policy, private.service_state,
        clock_seconds=Q(left), energy_wh=context.spacecraft_state.battery.energy_wh,
        usable_capacity_wh=capacity, stationary=stationary)
    if not decision.supported:
        raise _Refusal('UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY')
    if pending.kind not in ('HOLD_UNTIL','SOLAR_HOLD') and decision.state.mode != 'NORMAL':
        raise _Refusal('B55_POWER_SERVICE_INTERRUPTED:'+decision.state.mode)
    required = (state.inputs.protection.imaging_node_ids if pending.kind in ('POINT', 'CAPTURE') else
                state.inputs.protection.standby_node_ids)
    nodes = tuple(n.node_id for n in context.spacecraft_state.thermal.node_states)
    if _violations(context, nodes, survival=True):
        raise _Refusal('B55_SURVIVAL_TEMPERATURE_AT_START')
    if decision.state.mode == 'NORMAL' and _violations(context, required):
        raise _Refusal('OPERATING_TEMPERATURE_AT_START')
    slew = pending.slew
    midpoint = (left+right)/2
    quaternion = state.attitude.quaternion if slew is None else slew.quaternion_at(midpoint-Q(pending.origin_seconds))
    k0 = k1 = Q(0); draw = adjustment = 0.
    if slew is not None:
        k0 = slew.kinetic_j(left-Q(pending.origin_seconds)); k1 = slew.kinetic_j(right-Q(pending.origin_seconds))
        storage = float((k1-k0)/(right-left))
        draw = hardware.actuator.electronics_power_w+max(0., storage)/hardware.actuator.drive_efficiency
        adjustment = -storage
    forcing, eps, camera, panel, supports = _forcing(state, hardware, left, right,
        quaternion, adcs_w=draw, payload_w=pending.payload_w)
    loss = 0. if state.inputs.environment_ageing_policy is not None else state.inputs.solar_retention_loss_per_second*float(right-left)
    solar = None if loss == 0 else SolarDegradationForcingInput(loss)
    binding,next_environment=prepare_environment_cut(state,context,private.environment_ageing_state,left,right,forcing)
    state.runtime_work.charge('physical_reserved_calls', 1, state.inputs.limits)
    try:
        from .lifecycle_backend import service_call
        part, carrier = service_call(state,service_physical_substep,context, RationalSeconds.from_fraction(right-left),
            forcing, eps, state.inputs.protection, solar,
            compilation=state.construction.compilation, service_policy=ConstructionServicePolicy(),
            service_mode=decision.state.mode, service_work=state.service_allocation_work,
            work=state.construction.work, limits=state.inputs.construction_limits,
            start_seconds=left, end_seconds=right,
            battery_port_policy=state.inputs.battery_port_policy,battery_port_state=private.battery_port_state,
            battery_port_work=state.battery_port_work,environment_binding=binding,
            internal_heat_adjustments_w=None if slew is None else
                ((context.inputs.spacecraft_configuration.thermal.network.bus_node_id, adjustment),))
    except BatteryPortDomainError as error:
        raise _Refusal('BATTERY_PORT_DOMAIN_REFUSED:'+str(error)) from error
    except ConstructionServiceDomainRefusal as error:
        raise _Refusal('UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY',
            diagnostic=('PAID_PRIVATE_SERVICE_PROPOSAL_NOT_PUBLISHED', error.diagnostic)) from error
    except ElectricalLimitError as error:
        raise _Refusal('CONSTRUCTION_ELECTRICAL_REFUSED:'+str(error),
            diagnostic=() if not hasattr(error, 'diagnostic') else
                ('PAID_PRIVATE_ELECTRICAL_REFUSAL', error.diagnostic)) from error
    except BaseException:
        state.runtime_work.physical_work_unknown_events += 1
        raise
    state.runtime_work.physical_completed_calls += 1
    part=complete_environment_cut(context,state.inputs.environment_ageing_policy,private.environment_ageing_state,next_environment,part)
    private.environment_ageing_state=next_environment
    diagnostic = part.service
    if slew is not None and not diagnostic.full_commanded_service:
        raise _Refusal('UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY',
            diagnostic=('PAID_PRIVATE_SERVICE_PROPOSAL_NOT_PUBLISHED', diagnostic))
    if _violations(context, nodes, survival=True):
        raise _Refusal('B55_SURVIVAL_TEMPERATURE_AT_ENDPOINT',
            diagnostic=('PAID_PRIVATE_ENDPOINT_NOT_PUBLISHED', right, part))
    if decision.state.mode == 'NORMAL' and _violations(context, required):
        raise _Refusal('OPERATING_TEMPERATURE_AT_ENDPOINT',
            diagnostic=('PAID_PRIVATE_ENDPOINT_NOT_PUBLISHED', right, part))
    desired_q, commanded_q, served_q, unmet_q = _component_service_powers(diagnostic)
    advanced, work = commit_service_step(state.inputs.service_policy, decision, private.service_work,
        duration_seconds=right-left, desired_normal_load_w=desired_q,
        commanded_load_w=commanded_q, served_receiving_load_w=served_q,
        essential_unserved_w=unmet_q,
        essential_fully_served=diagnostic.essential_fully_served,
        tx_fully_served=False)
    private.service_state = advanced; private.service_work = work
    private.last_service_diagnostic = diagnostic
    if state.inputs.battery_port_policy is not None:private.battery_port_state=part.port_state_after
    cut = MissionPhysicalCut(left, right, supports, forcing.incidence_angle_deg, camera, panel,
        float(k0), float(k1), draw, adjustment, part, quaternion,
        None if slew is None else slew.euler_at(midpoint-Q(pending.origin_seconds)), k0, k1)
    return private, cut


def _service_physical_piece(state, candidate, hardware, a, b, pending):
    private = _service_candidate(state, candidate); cuts = []; end = Q(a); interruption = None
    integral_private, integral_count, integral_end = private, 0, Q(a)
    for left, right in _partition(state, a, b, pending=pending, reserve=False):
        proposal = _clone_service_candidate(private)
        try:
            proposal, cut = _service_leaf(state, proposal, hardware, left, right, pending,
                stationary=pending.slew is None or left == Q(pending.origin_seconds))
        except _Refusal as error:
            if not cuts: raise
            if end.denominator != 1:
                error = _Refusal(str(error), diagnostic=(
                    'PAID_PRIVATE_FRACTIONAL_PREFIX_NOT_PUBLISHED', end, error.diagnostic))
                private, cuts, end = integral_private, cuts[:integral_count], integral_end
                if not cuts: raise error
            interruption = error; break
        private = proposal; cuts.append(cut); end = right
        if right.denominator == 1:
            integral_private, integral_count, integral_end = private, len(cuts), right
        if pending.kind not in ('HOLD_UNTIL','SOLAR_HOLD') and not cut.part.service.full_commanded_service:
            interruption = _Refusal('B55_POWER_SERVICE_INTERRUPTED:PARTIAL_RECEIVING_SERVICE',
                diagnostic=('SELECTED_SERVICE_INTERRUPTION', cut.part.service)); break
    if end.denominator != 1 and interruption is not None:
        interruption = _Refusal(str(interruption), diagnostic=(
            'PAID_PRIVATE_FRACTIONAL_PREFIX_NOT_PUBLISHED', end, interruption.diagnostic))
        private, cuts, end = integral_private, cuts[:integral_count], integral_end
        if not cuts: raise interruption
    if end.denominator != 1:
        raise ValueError('lifecycle selected service boundary must remain integral')
    return private, tuple(cuts), _aggregate(tuple(c.part for c in cuts)), end.numerator, interruption


def _quiet_state_values(context, port_state=None, port_policy=None,environment=None):
    s = context.spacecraft_state
    extra=()
    if port_state is not None:
        cap=compute_eps_capability(context.inputs.spacecraft_configuration.eps,s.degradation).battery_usable_capacity_wh
        network=context.inputs.spacecraft_configuration.thermal.network
        t=next(n.temperature_k for n in s.thermal.node_states if n.node_id==network.battery_node_id)
        voc,r,unused=ocv_resistance(port_policy,port_state,s.battery.energy_wh,cap,t)
        extra=(('port_voltage_v',voc if port_state.last_voltage_v is None else port_state.last_voltage_v),
            ('port_ocv_v',voc),('port_current_a',0. if port_state.last_current_a is None else port_state.last_current_a),
            ('port_resistance_ohm',r),('port_resistance_damage',port_state.resistance_damage),
            ('port_weighted_seconds',port_state.temperature_weighted_seconds),
            ('port_ohmic_heat_wh',port_state.ohmic_heat_wh),('port_converter_loss_wh',port_state.converter_loss_wh))
    return (*extra,('energy_wh', s.battery.energy_wh),
        ('throughput_wh', s.degradation.battery.cumulative_energy_throughput_wh),
        ('battery_retention', s.degradation.battery.usable_capacity_retention),
        ('solar_retention', s.degradation.solar.generation_retention),
        *(('temperature:'+n.node_id.value, n.temperature_k) for n in s.thermal.node_states)) + (() if environment is None else environment_metrics(*environment))


def _quiet_sample(state, context, part, *, service_private=None):
    policy = state.inputs.quiet_policy
    account = _aggregate((part,))
    dt_hours = part.eps_result.battery.dt_seconds/3600.
    integrals = (*tuple((f.name, getattr(account, f.name)) for f in fields(account)
                       if f.name != 'numerical_substeps'),
        ('wire_loss_wh', (part.electrical.pv_wire_loss_w+part.electrical.receiving_wire_loss_w)*dt_hours),
        ('source_generation_wh', part.electrical.source_generation_w*dt_hours),
        ('receiving_load_wh', part.electrical.receiving_load_w*dt_hours))
    battery = part.eps_result.battery
    clipping = part.battery_capacity_reconciliation_result.unavailable_energy_wh
    regime = (battery.charge_input_w > 0, battery.discharge_output_w > 0,
        battery.curtailed_generation_w > 0, clipping > 0,
        battery.unmet_load_w > 0,
        battery.start_energy_wh == part.eps_capability_result.battery_usable_capacity_wh)
    network = {n.node_id: n for n in context.inputs.spacecraft_configuration.thermal.network.nodes}
    required = set(state.inputs.protection.standby_node_ids)
    margin = policy.guard_temperature_margin_k
    near = context.spacecraft_state.battery.energy_wh <= policy.guard_energy_margin_wh or any(
        min(n.temperature_k-network[n.node_id].operating_min_temperature_k.value,
            network[n.node_id].operating_max_temperature_k.value-n.temperature_k) <= margin
        for n in context.spacecraft_state.thermal.node_states if n.node_id in required)
    if service_private is not None:
        service = service_private.service_state
        capacity = part.eps_capability_result.battery_usable_capacity_wh
        energy = context.spacecraft_state.battery.energy_wh
        regime += (part.service.service_mode, service.essential_serviceable,
                   service.boot_progress_seconds >= state.inputs.service_policy.boot_duration_seconds)
        # Stable active zero-energy OFF is NOT an approaching low-energy event.
        # The same full/two-half thermal/ageing/integral screens still apply.
        # SAFE/OFF do not transition at LOW or E=0.  They can leave only at
        # HIGH with essential service and dwell. Regime equality and the same
        # full/fine physical/integral error checks remain mandatory, including
        # tiny charging and small positive unspent allocation-grid residues.
        energy_fractions = ((state.inputs.service_policy.high_usable_capacity_fraction,)
            if part.service.service_mode in ('SAFE', 'POWER_OFF') else
            (state.inputs.service_policy.low_usable_capacity_fraction,
             state.inputs.service_policy.high_usable_capacity_fraction))
        near_energy = any(abs(energy-capacity*fraction) <= policy.guard_energy_margin_wh
                          for fraction in energy_fractions)
        # Evaluate sampled transition eligibility from BOTH returned support
        # endpoints, including capacity ageing/reconciliation. A large valid
        # draw/charge can jump across the fixed near-energy margin while full
        # and half trials still share their start-sampled mode.
        start_capacity_q = Q(part.eps_capability_result.battery_usable_capacity_wh)
        end_capacity_q = Q(part.battery_capacity_reconciliation_result.end_usable_capacity_wh)
        start_energy_q = Q(battery.start_energy_wh)
        end_energy_q = Q(part.battery_capacity_reconciliation_result.authoritative_end_energy_wh)
        low_fraction_q = Q(state.inputs.service_policy.low_usable_capacity_fraction)
        high_fraction_q = Q(state.inputs.service_policy.high_usable_capacity_fraction)
        low_start = start_energy_q-start_capacity_q*low_fraction_q
        low_end = end_energy_q-end_capacity_q*low_fraction_q
        high_start = start_energy_q-start_capacity_q*high_fraction_q
        high_end = end_energy_q-end_capacity_q*high_fraction_q
        if part.service.service_mode == 'NORMAL':
            crossed_low = low_start > 0 and low_end <= 0
            near_energy = (near_energy or energy <= policy.guard_energy_margin_wh or
                           crossed_low or low_end <= 0)
        elif part.service.service_mode == 'RECOVERY':
            near_energy = near_energy or (low_start > 0 and low_end <= 0) or low_end <= 0
        elif part.service.service_mode in ('SAFE', 'POWER_OFF'):
            near_energy = near_energy or high_start < 0 <= high_end
        low_name, high_name = (('operating_min_temperature_k', 'operating_max_temperature_k')
            if part.service.service_mode == 'NORMAL' else ('survival_min_temperature_k', 'survival_max_temperature_k'))
        near = near_energy or any(min(n.temperature_k-getattr(network[n.node_id], low_name).value,
            getattr(network[n.node_id], high_name).value-n.temperature_k) <= margin
            for n in context.spacecraft_state.thermal.node_states
            if part.service.service_mode != 'NORMAL' or n.node_id in required)
        if (part.service.service_mode in ('SAFE', 'POWER_OFF') and
                service.essential_serviceable and
                high_end >= 0):
            # HIGH can be attained before dwell is over. Full/two-half trials
            # can agree on the old sampled mode while both cross dwell expiry;
            # guard its pending/overdue release independently of energy error.
            remaining_dwell = (state.inputs.service_policy.minimum_dwell_seconds-
                               (service.clock_seconds-service.entered_at_seconds))
            near = near or remaining_dwell <= policy.maximum_macro_seconds
        if service.mode == 'RECOVERY' and service.boot_progress_seconds < state.inputs.service_policy.boot_duration_seconds:
            near = near or state.inputs.service_policy.boot_duration_seconds-service.boot_progress_seconds <= policy.maximum_macro_seconds
    if state.inputs.battery_port_policy is not None:
        integrals+= (('port_ohmic_heat_wh',battery.ohmic_heat_wh),('port_converter_loss_wh',battery.converter_loss_wh))
        regime+=(battery.limiting_reason,battery.current_a>0,battery.current_a<0)
        near=near or battery.near_boundary
    return QuietSample(_quiet_state_values(context,None if service_private is None else service_private.battery_port_state,
        state.inputs.battery_port_policy,None if state.inputs.environment_ageing_policy is None or service_private is None else (state,context,service_private.environment_ageing_state)), integrals, regime, near)


def _service_quiet_physical_piece(state, candidate, hardware, a, b, pending):
    from .lifecycle_typed_context import TypedBackendContext
    from .lifecycle_typed_backend import FULL_DOMAINS
    if type(state.backend_context)is TypedBackendContext and state.backend_context.selection in FULL_DOMAINS:
        return state.backend_context.quiet_piece(state,candidate,hardware,Q(a),Q(b),pending)
    schedule = state.source_authority.schedule(Q(a), Q(b))
    if not schedule.cells or any(c.assessment == 'UNRESOLVED' for c in schedule.cells):
        raise _Refusal('UNRESOLVED_ILLUMINATION')
    points = sorted({Q(a), Q(b)} | {x for c in schedule.cells for x in (c.start_seconds, c.end_seconds)})
    private = _service_candidate(state, candidate); controller = state.quiet_controller; selected = []

    def step(value, left, right):
        try:
            value, cut = _service_leaf(state, value, hardware, left, right, pending)
        except _Refusal as error:
            raise QuietTrialRefusal(error) from error
        return QuietTrial(value, cut, _quiet_sample(state, value.context, cut.part, service_private=value))

    try:
        for left, right in zip(points, points[1:]):
            result = __import__(__package__+'.lifecycle_backend',fromlist=['quiet_call']).quiet_call(state,integrate_quiet_hold,private, left, right, policy=state.inputs.quiet_policy,
                controller=controller, work=state.quiet_work,
                clone_context=_clone_service_candidate,
                state_values=lambda value: _quiet_state_values(value.context,value.battery_port_state,state.inputs.battery_port_policy,None if state.inputs.environment_ageing_policy is None else (state,value.context,value.environment_ageing_state)), step=step)
            private = result.context; controller = result.controller; selected.extend(result.cuts)
            if len(selected) > state.inputs.limits.max_retained_cuts:
                raise _Refusal('LIFECYCLE_LOCAL_ACTION_PARTITION_LIMIT')
    except QuietTrialRefusal as error:
        raise error.original from error
    return private, tuple(selected), _aggregate(tuple(c.part for c in selected)), controller


def _quiet_physical_piece(state, candidate, hardware, a, b, pending):
    """New numerical owner for stationary HOLD only; same accepted coupled leaf.

    Source cuts remain exact. Full and half proposals are private, fully paid,
    and only selected two-half cuts reach actual energy/extrema/report owners.
    POINT/CAPTURE/CONTACT never enter this function.
    """
    if pending.kind not in ('HOLD_UNTIL','SOLAR_HOLD') or pending.slew is not None or pending.payload_w != 0:
        raise ValueError('quiet integration requires a stationary, unloaded HOLD')
    required = state.inputs.protection.standby_node_ids
    if _violations(candidate, required): raise _Refusal('OPERATING_TEMPERATURE_AT_START')
    schedule = state.source_authority.schedule(Q(a), Q(b))
    if not schedule.cells or any(c.assessment == 'UNRESOLVED' for c in schedule.cells):
        raise _Refusal('UNRESOLVED_ILLUMINATION')
    points = sorted({Q(a), Q(b)} | {x for c in schedule.cells for x in (c.start_seconds, c.end_seconds)})
    if len(points)-1 > state.inputs.limits.max_action_cells:
        raise _Refusal('LIFECYCLE_LOCAL_ACTION_PARTITION_LIMIT')
    selected = []; controller = state.quiet_controller

    def step(context, left, right):
        state.runtime_work.charge('physical_reserved_calls', 1, state.inputs.limits)
        forcing, eps, camera, panel, supports = _forcing(state, hardware, left, right, state.attitude.quaternion)
        loss = 0. if state.inputs.environment_ageing_policy is not None else state.inputs.solar_retention_loss_per_second*float(right-left)
        solar = None if loss == 0 else SolarDegradationForcingInput(loss)
        try:
            part, unused = construction_physical_substep(context,
                RationalSeconds.from_fraction(right-left), forcing, eps, state.inputs.protection,
                solar, compilation=state.construction.compilation, work=state.construction.work,
                limits=state.inputs.construction_limits, standby=False)
        except ElectricalLimitError as error:
            raise QuietTrialRefusal(_Refusal('CONSTRUCTION_ELECTRICAL_REFUSED:'+str(error))) from error
        except BaseException:
            state.runtime_work.physical_work_unknown_events += 1
            raise
        state.runtime_work.physical_completed_calls += 1
        if part is None:
            raise QuietTrialRefusal(_Refusal('FULL_ELECTRICAL_SERVICE_UNAVAILABLE'))
        if _violations(context, required):
            raise QuietTrialRefusal(_Refusal('OPERATING_TEMPERATURE_AT_ENDPOINT',
                diagnostic=('PAID_PRIVATE_ENDPOINT_NOT_PUBLISHED', right, part)))
        cut = MissionPhysicalCut(left, right, supports, forcing.incidence_angle_deg, camera, panel,
            0., 0., 0., 0., part, state.attitude.quaternion, None, Q(0), Q(0))
        return QuietTrial(context, cut, _quiet_sample(state, context, part))

    try:
        for left, right in zip(points, points[1:]):
            result = __import__(__package__+'.lifecycle_backend',fromlist=['quiet_call']).quiet_call(state,integrate_quiet_hold,candidate, left, right, policy=state.inputs.quiet_policy,
                controller=controller, work=state.quiet_work, clone_context=_quiet_clone_context,
                state_values=_quiet_state_values, step=step)
            candidate = result.context; controller = result.controller
            selected.extend(result.cuts)
            if len(selected) > state.inputs.limits.max_retained_cuts:
                raise _Refusal('LIFECYCLE_LOCAL_ACTION_PARTITION_LIMIT')
    except QuietTrialRefusal as error:
        raise error.original from error
    return candidate, tuple(selected), _aggregate(tuple(c.part for c in selected)), controller


def _capture_definition(state, candidate, action, hardware, observations):
    start = candidate.simulation_time_seconds; end = start+action.duration_seconds
    product = _product(state, action.product_id)
    if any(e.plan.request.request_id == product.request.request_id for e in state.acquisitions):
        raise _Refusal('ACTIVE_PRODUCT_ALREADY_ACQUIRED')
    if not product.acquisition_start_seconds <= start < end <= product.acquisition_end_seconds:
        raise _Refusal('ACQUISITION_WINDOW_MISSED')
    if any(not observation.visible for observation in observations):
        raise _Refusal('TARGET_NOMINAL_SAMPLED_NOT_VISIBLE')
    camera = state.attitude.direction(hardware.camera_body_axis)
    if any(angle_between(camera, observation.direction.components) > state.inputs.camera_half_fov_rad for observation in observations):
        raise _Refusal('CAMERA_TARGET_SEPARATION_EXCEEDS_FOV')
    entry = observations[0]; azimuth = entry.geometry.orbital_azimuth_rad
    if azimuth is None:
        if entry.off_nadir_rad != 0: raise _Refusal('UNDEFINED_LOCAL_VIEW_AZIMUTH')
        azimuth = 0.
    opportunity = ObservationOpportunity(ObservationOpportunityId('b44.'+action.action_id), product.request.request_id,
        start, end, action.duration_seconds, ObservationPointing(degrees(entry.off_nadir_rad), degrees(azimuth)%360))
    boresight = CommonFrameBoresightDirection(ADCSBoresightFrameId('b44-long-full-spatial-model-inertial-bound-in-packet'), *camera)
    config = candidate.inputs.spacecraft_configuration.payload.optical_acquisition
    footprint = product.footprint
    optical = OpticalAcquisitionInput(footprint.width_m, footprint.length_m, action.duration_seconds,
                                      OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY)
    execution = ScheduledObservationAcquisitionExecution(ObservationAcquisitionCandidate(
        ObservationManeuverCandidate(opportunity, boresight), optical), start)
    forcing, _, _, _, _ = _forcing(state, hardware, Q(start), Q(start), state.attitude.quaternion)
    association = MSAcquisitionPlan(1, product.request, product.capture_group,
        size_ms_grid(footprint, config.multispectral_reference_sample_spacing_m.value,
                     config.multispectral_reference_sample_spacing_m.value, REQUIRED_MS_CHANNELS,
                     int(config.acquisition_bits_per_sample.value)),
        'Declared common synthetic MS capability, integer grid, no calibrated optical performance.')
    image = ImagingAction(action.action_id, execution, AcquisitionDataRecordId('b44.'+action.action_id),
        AcquisitionEPSIntervalEnvironment(forcing.sunlit, forcing.incidence_angle_deg, forcing.loads),
        state.inputs.routing, forcing.thermal_inputs, forcing.external_heat_sources, None)
    if state.attitude.rest_since_seconds.denominator != 1:
        raise ValueError('settled attitude requires integral origin')
    previous = InitialAttitudeEvidence(state.attitude.rest_since_seconds.numerator, boresight,
        'Actual completed spatial M3 rest/settling, camera body axis from declared M1 mount.')
    record, loads = _diagnosed_imaging_request(state, candidate, previous, image, association)
    return record, association, loads.load_breakdown.payload_w-forcing.loads.payload_w


def _diagnosed_imaging_request(state, context, previous, image, association):
    """Single-pass initial-attitude adapter with exact lower-owner refusal data.

    This is the same owner chain as substepped_execution._imaging_request's
    InitialAttitudeEvidence branch. It does not call that wrapper and then
    repeat a failed computation for diagnosis. Original metadata-validation
    errors remain exceptions. No optical/storage/protection criterion changes.
    """
    from .adcs import compute_boresight_transition
    from .observation_feasibility import evaluate_observation_view_feasibility
    from .ms_acquisition import validate_ms_acquisition
    from .payload import compute_optical_acquisition
    from .storage import evaluate_storage_admission, StorageAdmissionStatus
    from .eps_system import EPSIntervalInputs
    from .imaging_resources import _checked_sum
    cfg = context.inputs.spacecraft_configuration
    if (any(r.record_id == image.record_id for r in context.spacecraft_state.data_storage.stored_records) or
            any(d.record.record_id == image.record_id for d in context.ground_data_delivery_state.completed_deliveries)):
        raise ValueError('imaging record ID already has an acquisition')
    # Separate declared bookkeeping reservation; no extra scientific evaluation.
    state.runtime_work.charge('spatial_reserved_units', 1024, state.inputs.limits)
    validate_ms_acquisition(image, cfg.payload.optical_acquisition, association)
    previous.__post_init__()
    candidate = image.execution.candidate
    view = evaluate_observation_view_feasibility(cfg.adcs.agile_pointing,
        candidate.maneuver_candidate.opportunity)
    transition = compute_boresight_transition(cfg.adcs.agile_pointing,
        previous.common_frame_boresight, candidate.maneuver_candidate.common_frame_boresight)
    calls = (('validate_ms_acquisition', 1), ('evaluate_observation_view_feasibility', 1),
             ('compute_boresight_transition', 1))
    ready = Q(previous.at_seconds)+Q(transition.total_transition_time_seconds)
    if not view.feasible:
        detail = LifecycleRefusalDetail('VIEW', 'ACQUISITION_VIEW_ENVELOPE_REFUSED',
            'observation_feasibility.evaluate_observation_view_feasibility', calls,
            (('requested_view_angle_deg', view.requested_view_angle_from_nadir_deg),
             ('maximum_view_angle_deg', view.maximum_view_angle_from_nadir_deg)))
        raise _Refusal(detail.code, diagnostic=('B53_ACTUAL_ACQUISITION_REFUSAL_V1', detail))
    if ready > image.execution.scheduled_start_seconds:
        detail = LifecycleRefusalDetail('SETTLING', 'ACQUISITION_SETTLING_NOT_READY',
            'adcs.compute_boresight_transition', calls,
            (('rest_since_seconds', previous.at_seconds),
             ('transition_seconds', transition.total_transition_time_seconds),
             ('ready_seconds_exact', str(ready)),
             ('scheduled_start_seconds', image.execution.scheduled_start_seconds)))
        raise _Refusal(detail.code, diagnostic=('B53_ACTUAL_ACQUISITION_REFUSAL_V1', detail))
    optical = compute_optical_acquisition(cfg.payload.optical_acquisition, candidate.acquisition_input)
    bits = float(association.sizing.stored_bits)
    opportunity = candidate.maneuver_candidate.opportunity
    acquisition = candidate.acquisition_input
    record = OnboardAcquisitionDataRecord(image.record_id, opportunity.request_id,
        opportunity.opportunity_id, image.execution.scheduled_start_seconds,
        acquisition.imaging_duration_seconds, acquisition.channel_selection, bits, bits)
    admission = evaluate_storage_admission(cfg.storage, context.spacecraft_state.data_storage.stored_records, record)
    if admission.status is not StorageAdmissionStatus.ADMISSIBLE:
        detail = LifecycleRefusalDetail('STORAGE', 'ACQUISITION_STORAGE_INSUFFICIENT_CAPACITY',
            'storage.evaluate_storage_admission',
            (*calls, ('compute_optical_acquisition', 1), ('evaluate_storage_admission', 1)),
            (('requested_bits', record.stored_equivalent_bits),
             ('available_bits', admission.available_capacity_bits_before),
             ('occupied_bits', admission.stored_equivalent_bits_before),
             ('capacity_bits', admission.configured_usable_capacity_bits)))
        raise _Refusal(detail.code, diagnostic=('B53_ACTUAL_ACQUISITION_REFUSAL_V1', detail))
    environment = image.environment
    loads = replace(environment.non_acquisition_loads,
        payload_w=_checked_sum('combined payload request', environment.non_acquisition_loads.payload_w,
                              optical.requested_acquisition_power_w))
    return record, EPSIntervalInputs(environment.sunlit, environment.incidence_angle_deg, loads)


def _contact_piece(state, candidate, action, hardware, a, b):
    entry = _entry(state, action.point_id, station=True)
    observations = state.source_authority.observations(entry, Q(a), Q(b), state.inputs.sampling)
    if not entry.station_available or not entry.rf_admitted or any(not o.serviceable_nominal for o in observations):
        raise _Refusal('STATION_GEOMETRY_OR_DECLARED_SERVICE_UNAVAILABLE')
    rate = candidate.inputs.spacecraft_configuration.communications.nominal_downlink_data_rate_bps.value
    if type(rate) not in (int, float) or rate != int(rate) or int(rate) != entry.nominal_rate_bps:
        raise ValueError('station rate differs from communications authority')
    if a < state.consumed_through_seconds:
        raise ValueError('contact is behind monotone consumed frontier')
    schedule = state.source_authority.schedule(Q(a), Q(b))
    if any(c.assessment == 'UNRESOLVED' for c in schedule.cells): raise _Refusal('UNRESOLVED_ILLUMINATION')
    boundaries = sorted({Q(a), Q(b)} | {x for c in schedule.cells for x in (c.start_seconds, c.end_seconds)})
    if any(x.denominator != 1 for x in boundaries): raise _Refusal('UNSUPPORTED_FRACTIONAL_CONTACT_FORCING_CUT')
    if len(boundaries)-1 > min(128, state.inputs.limits.max_retained_cuts):
        raise _Refusal('LIFECYCLE_LOCAL_CONTACT_PARTITION_LIMIT')
    contacts = []; bindings = []; receipts = []; consumed = ConsumedContacts(())
    environment_history=state.environment_ageing_state
    n = IntegrationPolicy(state.inputs.limits.contact_integration_level).substeps
    for i, (left, right) in enumerate(zip(boundaries, boundaries[1:])):
        forcing, _, camera, panel, supports = _forcing(state, hardware, left, right, state.attitude.quaternion)
        loss = 0. if state.inputs.environment_ageing_policy is not None else state.inputs.solar_retention_loss_per_second*float(right-left)
        solar = None if loss == 0 else SolarDegradationForcingInput(loss)
        tx = CoupledDownlinkInputs(state.inputs.transmitter, forcing.loads, forcing.sunlit,
            forcing.incidence_angle_deg, state.inputs.routing, forcing.thermal_inputs, forcing.external_heat_sources, solar)
        idle = StandbyInputs(forcing.loads, forcing.sunlit, forcing.incidence_angle_deg,
            forcing.routing_config, forcing.thermal_inputs, forcing.external_heat_sources, solar,
            'Declared essential contact idle; derived incidence.')
        token = sha256(action.action_id.encode('utf-8')).hexdigest()[:32]
        contact = ServiceableGroundContact(GroundContactId('b52.'+token+'.'+str(left.numerator)),
            entry.point.point_id, left.numerator, right.numerator)
        ids = tuple(r.record_id for r in candidate.spacecraft_state.data_storage.stored_records)
        state.runtime_work.charge('physical_reserved_calls', n*(2*len(ids)+1), state.inputs.limits)
        try:
            contact_leaf=execute_construction_contact_plan;extra={}
            if state.inputs.environment_ageing_policy is not None:
                from .environment_contact import execute_environment_contact_plan
                contact_leaf=execute_environment_contact_plan
                extra=dict(environment_policy=state.inputs.environment_ageing_policy,environment_state=environment_history,environment_work=state.environment_ageing_work)
            result = contact_leaf(candidate, ContactPlan(contact, ids, tx, idle),
                consumed_contacts=consumed, policy=state.inputs.protection,
                integration=IntegrationPolicy(state.inputs.limits.contact_integration_level),
                compilation=state.construction.compilation, work=state.construction.work,
                limits=state.inputs.construction_limits,**extra)
            if extra:result,environment_history=result
        except ConstructionContactRefusal as error:
            state.runtime_work.physical_completed_calls += error.returned_physical_calls
            raise _Refusal('CONSTRUCTION_CONTACT_ELECTRICAL_REFUSED:'+error.reason,
                diagnostic=('KNOWN_ELECTRICAL_CONTACT_REFUSAL_V1', error.reason, error.offset_bits,
                    error.standby, error.evaluations, error.returned_physical_calls,
                    error.returned_thermal_calls, tuple(contacts), tuple(bindings))) from error
        except BaseException:
            state.runtime_work.contact_work_unknown_events += 1
            raise
        state.runtime_work.physical_completed_calls += result.outcome.evaluated_eps_substeps
        if (result.outcome.denied_record_id is not None or result.outcome.accounting.unmet_load_wh > 0 or
                candidate.spacecraft_state.onboard.fdir_state is not FDIRState.NORMAL or
                candidate.spacecraft_state.onboard.operational_mode is OperationalMode.SAFE or
                candidate.spacecraft_state.onboard.critical_energy_since_seconds is not None or
                _violations(candidate, state.inputs.protection.standby_node_ids)):
            raise _Refusal('CONTACT_EXISTING_PROTECTION_REFUSED')
        contacts.append(result.outcome); consumed = result.consumed_contacts
        for service in result.outcome.services:
            if service.completed:
                receipts.append(LifecycleReceipt(service.record, result.outcome.contact,
                    Q(result.outcome.contact.start_time_seconds)+service.end_offset.fraction))
        legacy = MissionContactForcing(left, right, supports, forcing.incidence_angle_deg, camera, panel,
                                       tx, idle, contact.contact_id)
        bindings.append(ConstructionContactForcing(legacy, result.evaluations))
    return observations, tuple(contacts), tuple(bindings), tuple(receipts),environment_history


def _service_contact_piece(state, candidate, action, hardware, a, b):
    from .lifecycle_service_contact import execute_service_contact_plan, ServiceContactDomainRefusal
    entry = _entry(state, action.point_id, station=True)
    observations = state.source_authority.observations(entry, Q(a), Q(b), state.inputs.sampling)
    if not entry.station_available or not entry.rf_admitted or any(not o.serviceable_nominal for o in observations):
        raise _Refusal('STATION_GEOMETRY_OR_DECLARED_SERVICE_UNAVAILABLE')
    rate = candidate.inputs.spacecraft_configuration.communications.nominal_downlink_data_rate_bps.value
    if type(rate) not in (int, float) or rate != int(rate) or int(rate) != entry.nominal_rate_bps:
        raise ValueError('station rate differs from communications authority')
    if a < state.consumed_through_seconds:
        raise ValueError('contact is behind monotone consumed frontier')
    schedule = state.source_authority.schedule(Q(a), Q(b))
    if any(c.assessment == 'UNRESOLVED' for c in schedule.cells): raise _Refusal('UNRESOLVED_ILLUMINATION')
    points = {Q(a), Q(b)} | {x for cell in schedule.cells for x in (cell.start_seconds, cell.end_seconds)}
    points.update(Q(second) for second in range(a+1, b))
    boundaries = sorted(points)
    if any(x.denominator != 1 for x in boundaries): raise _Refusal('UNSUPPORTED_FRACTIONAL_CONTACT_FORCING_CUT')
    if len(boundaries)-1 > min(128, state.inputs.limits.max_retained_cuts):
        raise _Refusal('LIFECYCLE_LOCAL_CONTACT_PARTITION_LIMIT')
    private = _service_candidate(state, candidate)
    contacts = []; bindings = []; receipts = []; consumed = ConsumedContacts(())
    n = IntegrationPolicy(state.inputs.limits.contact_integration_level).substeps
    end = a; interruption = None
    from .lifecycle_native_state import contact_service_binding
    from .contact_execution import _prepare_contact,_bind_contact_cut
    contact_backend=contact_service_binding(state)
    contact_integration=IntegrationPolicy(state.inputs.limits.contact_integration_level)
    contact_preparation=_prepare_contact(contact_backend,private.context,state.inputs.protection,contact_integration)
    try:
        for left, right in zip(boundaries, boundaries[1:]):
            forcing, _, camera, panel, supports = _forcing(state, hardware, left, right, state.attitude.quaternion)
            loss = 0. if state.inputs.environment_ageing_policy is not None else state.inputs.solar_retention_loss_per_second*float(right-left)
            solar = None if loss == 0 else SolarDegradationForcingInput(loss)
            tx = CoupledDownlinkInputs(state.inputs.transmitter, forcing.loads, forcing.sunlit,
                forcing.incidence_angle_deg, state.inputs.routing, forcing.thermal_inputs, forcing.external_heat_sources, solar)
            idle = StandbyInputs(forcing.loads, forcing.sunlit, forcing.incidence_angle_deg,
                forcing.routing_config, forcing.thermal_inputs, forcing.external_heat_sources, solar,
                'B55 positive authored essential contact idle; current-attitude PV.')
            token = sha256(action.action_id.encode('utf-8')).hexdigest()[:32]
            contact = ServiceableGroundContact(GroundContactId('b55.'+token+'.'+str(left.numerator)),
                entry.point.point_id, left.numerator, right.numerator)
            ids = tuple(record.record_id for record in private.context.spacecraft_state.data_storage.stored_records)
            state.runtime_work.charge('physical_reserved_calls', n*(2*len(ids)+1), state.inputs.limits)
            proposal = _clone_service_candidate(private)
            _bind_contact_cut(contact_preparation,proposal.context)
            prior_completed = state.service_allocation_work.selected_coupled_calls
            try:
                result = execute_service_contact_plan(proposal.context, ContactPlan(contact, ids, tx, idle),
                    consumed_contacts=consumed, policy=state.inputs.protection,
                    integration=contact_integration,
                    compilation=state.construction.compilation, work=state.construction.work,
                    limits=state.inputs.construction_limits, service_policy=state.inputs.service_policy,
                    service_state=private.service_state, service_work=private.service_work,
                    allocation_work=state.service_allocation_work,battery_port_policy=state.inputs.battery_port_policy,
                    battery_port_state=private.battery_port_state,battery_port_work=state.battery_port_work,
                    environment_ageing_policy=state.inputs.environment_ageing_policy,environment_ageing_state=private.environment_ageing_state,environment_ageing_work=state.environment_ageing_work,
                    backend_service=contact_backend,_contact_preparation=contact_preparation)
            except BatteryPortDomainError as error:
                if not contacts:raise _Refusal('BATTERY_PORT_DOMAIN_REFUSED:'+str(error)) from error
                interruption=_Refusal('BATTERY_PORT_DOMAIN_REFUSED:'+str(error));break
            except ElectricalLimitError as error:
                diagnostic = () if not hasattr(error, 'diagnostic') else ('PAID_PRIVATE_CONTACT_ELECTRICAL_REFUSAL', error.diagnostic)
                if not contacts: raise _Refusal('CONSTRUCTION_CONTACT_ELECTRICAL_REFUSED:'+str(error), diagnostic=diagnostic) from error
                interruption = _Refusal('CONSTRUCTION_CONTACT_ELECTRICAL_REFUSED:'+str(error), diagnostic=diagnostic); break
            except ServiceContactDomainRefusal as error:
                if not contacts: raise _Refusal(str(error), diagnostic=error.diagnostic) from error
                interruption = _Refusal(str(error), diagnostic=error.diagnostic); break
            finally:
                state.runtime_work.physical_completed_calls += (
                    state.service_allocation_work.selected_coupled_calls-prior_completed)
            private = replace(proposal, service_state=result.service_state,
                service_work=result.service_work, last_service_diagnostic=result.last_service_diagnostic,battery_port_state=result.battery_port_state,environment_ageing_state=result.environment_ageing_state)
            contacts.append(result.outcome); consumed = result.consumed_contacts; end = right.numerator
            for service in result.outcome.services:
                if service.completed:
                    receipts.append(LifecycleReceipt(service.record, result.outcome.contact,
                        Q(result.outcome.contact.start_time_seconds)+service.end_offset.fraction))
            legacy = MissionContactForcing(left, right, supports, forcing.incidence_angle_deg,
                camera, panel, tx, idle, contact.contact_id)
            bindings.append(ConstructionContactForcing(legacy, result.evaluations))
            if result.outcome.denied_record_id is not None or result.service_state.mode != 'NORMAL':
                interruption = _Refusal('B55_POWER_SERVICE_INTERRUPTED:CONTACT_TX_UNAVAILABLE',
                    diagnostic=('SELECTED_SERVICE_INTERRUPTION', result.last_service_diagnostic)); break
    finally:
        if contact_preparation is not None:contact_preparation.close()
    return private, observations, tuple(contacts), tuple(bindings), tuple(receipts), end, interruption


def _prepare_pending(state, action):
    a = state.context.simulation_time_seconds; hardware = state.harness.hardware
    geometry = (); slew = None; record = association = None; payload = 0.;solar_target=None
    if type(action) is SolarAction:
        if state.inputs.energy_attitude_policy is None or action.policy_identity!=state.inputs.energy_attitude_policy.identity:raise ValueError('solar action explicit policy mismatch')
    state.runtime_work.charge('spatial_reserved_units', 65536, state.inputs.limits)
    if state.inputs.service_policy is not None and action.kind not in ('HOLD_UNTIL','SOLAR_HOLD'):
        capability = compute_eps_capability(state.context.inputs.spacecraft_configuration.eps,
                                            state.context.spacecraft_state.degradation)
        decision = select_service_mode(state.inputs.service_policy, state.service_state,
            clock_seconds=Q(a), energy_wh=state.context.spacecraft_state.battery.energy_wh,
            usable_capacity_wh=capability.battery_usable_capacity_wh, stationary=True)
        if not decision.supported or decision.state.mode != 'NORMAL':
            raise _Refusal('B55_POWER_SERVICE_INTERRUPTED:'+decision.state.mode)
    if action.kind == 'SOLAR_POINT':
        try:
            axis=panel_axis(hardware)
            solar_target=paid_sun_target(state.source_authority,a)
            state.runtime_work.charge('spatial_reserved_units',65536+2048,state.inputs.limits)
            slew=plan_axis_slew(hardware,state.attitude,axis,solar_target.direction_inertial,work=state.harness.work,policy=state.inputs.augmentation.policy)
        except ValueError as error:raise _Refusal('SOLAR_SLEW_ADMISSION_REFUSED:'+str(error)) from error
        b=a+slew.duration_seconds
        cfg=state.construction.compilation.configuration
        capacity=compute_eps_capability(state.context.inputs.spacecraft_configuration.eps,state.context.spacecraft_state.degradation).battery_usable_capacity_wh
        eta=state.context.inputs.spacecraft_configuration.eps.battery.discharge_efficiency.value
        required=cfg.bus_voltage_v*cfg.bus_current_limit_a*(slew.duration_seconds+state.inputs.energy_attitude_policy.minimum_hold_reserve_seconds)/(3600*eta)
        reserve=capacity*state.inputs.service_policy.low_usable_capacity_fraction
        if state.context.spacecraft_state.battery.energy_wh<required+reserve:raise _Refusal('B56_SOLAR_SLEW_AND_MINIMUM_HOLD_RESERVE_UNAVAILABLE')
    elif action.kind == 'POINT':
        geometry = state.source_authority.observations(_entry(state, action.point_id), Q(a), Q(a), state.inputs.sampling)
        if not geometry[0].visible: raise _Refusal('TARGET_POINTING_GEOMETRY_REFUSED')
        state.runtime_work.charge('spatial_reserved_units', 65536+2048, state.inputs.limits)
        slew = plan_effective_slew(hardware, state.attitude, geometry[0].direction.components,
            work=state.harness.work, policy=state.inputs.augmentation.policy)
        b = a+slew.duration_seconds
        if state.inputs.service_policy is not None:
            # Conservative zero-PV full maneuver payment plus declared reserve.
            # Housekeeping/source wire losses are bounded by the installed bus
            # V*I ceiling; drive work is also contained in that same ceiling.
            cfg = state.construction.compilation.configuration
            capacity = compute_eps_capability(state.context.inputs.spacecraft_configuration.eps,
                state.context.spacecraft_state.degradation).battery_usable_capacity_wh
            eta = state.context.inputs.spacecraft_configuration.eps.battery.discharge_efficiency.value
            required_wh = cfg.bus_voltage_v*cfg.bus_current_limit_a*slew.duration_seconds/(3600*eta)
            reserve = capacity*state.inputs.service_policy.point_reserve_fraction
            if state.context.spacecraft_state.battery.energy_wh < required_wh+reserve:
                raise _Refusal('B55_POINT_ENERGY_RESERVE_UNAVAILABLE')
    elif action.kind in ('HOLD_UNTIL','SOLAR_HOLD'):
        b = action.until_seconds
        if b < a: raise _Refusal('HOLD_END_ALREADY_PASSED')
    else:
        b = a+action.duration_seconds
        if b > state.inputs.environment.end_seconds:
            raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
        if action.kind == 'CAPTURE':
            geometry = state.source_authority.observations(_entry(state, action.point_id), Q(a), Q(b), state.inputs.sampling)
            record, association, payload = _capture_definition(state, state.context, action, hardware, geometry)
    if b > state.inputs.environment.end_seconds: raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
    return PendingLifecycleAction(action, a, b, state.attitude, slew, geometry, record, association, payload,solar_target)


def execute_lifecycle_action(state, action, *, products=None, expected_sequence=None, stop_at_seconds=None):
    """Start exactly one command; optional cuts carry its original physical plan."""
    guard_lifecycle_physical(state)
    if state.pending is not None: raise ValueError('pending lifecycle action must finish before dispatch')
    if type(action) not in ((LongMissionAction,SolarAction) if state.inputs.energy_attitude_policy is not None else (LongMissionAction,)): raise TypeError('exact leaf action required')
    action.__post_init__()
    if expected_sequence is not None and expected_sequence != state.completed_actions:
        raise ValueError('stale lifecycle action frontier')
    if state.completed_actions >= state.inputs.limits.max_actions:
        raise ValueError('LIFECYCLE_ACTION_QUOTA')
    if products is not None:
        _validate_products(products, state.inputs.limits)
        old = {p.request.request_id: p for p in state.inputs.products}
        new = {p.request.request_id: p for p in products}
        if any(identifier not in new or new[identifier] != product for identifier, product in old.items()):
            raise ValueError('use explicit retirement before removing/changing active product')
        state = replace(state, inputs=replace(state.inputs, products=products))
    state.source_authority.guard()
    try:
        pending = _prepare_pending(state, action)
    except _Refusal as error:
        return _refused(state, action, error)
    return _execute_piece(state, pending, stop_at_seconds=stop_at_seconds)


def resume_pending_lifecycle_action(state, *, stop_at_seconds=None):
    guard_lifecycle_physical(state)
    if state.pending is None: raise ValueError('no pending lifecycle action')
    state.source_authority.guard()
    return _execute_piece(state, state.pending, stop_at_seconds=stop_at_seconds)


def _refused(state, action, error, *, pending=None):
    a = state.context.simulation_time_seconds
    # A previously committed moving phase cannot silently become a rested pose.
    # Its explicit pending state remains for inspection/INCOMPLETE handling.
    retained = state.pending if state.pending is not None and state.pending.kind in ('POINT','SOLAR_POINT') else None
    outcome = LifecycleActionOutcome(action.action_id, action.kind, 'refused', str(error), a, a,
        () if pending is None else pending.geometry, (), (), None, None, state.attitude, None,
        None if pending is None else pending.slew, failure_diagnostic=error.diagnostic,
        refusal_detail=error.diagnostic[1] if len(error.diagnostic) == 2 and
            type(error.diagnostic[1]) is LifecycleRefusalDetail else None,
        service_work_before=state.service_work, service_work_after=state.service_work,
        service_state_after=state.service_state,solar_state_before=state.solar_state,
        environment_ageing_state_before=state.environment_ageing_state,environment_ageing_state_after=state.environment_ageing_state,
        solar_state_after=advance_solar_state(state.solar_state,action,None,(),a,a,'refused',str(error),state.source_authority,state.inputs.energy_attitude_policy))
    result = replace(state, transition_count=state.transition_count+1,
                     completed_actions=state.completed_actions+(retained is None), pending=retained,solar_state=outcome.solar_state_after)
    guard_lifecycle_physical(result)
    return result, outcome


def _execute_piece(state, pending, *, stop_at_seconds=None):
    action = pending.action; a = state.context.simulation_time_seconds
    if stop_at_seconds is not None:
        _natural(stop_at_seconds, 'physical cut', maximum=state.inputs.environment.end_seconds)
        if stop_at_seconds <= a: raise ValueError('physical cut must advance a pending action')
    b = pending.end_seconds if stop_at_seconds is None else min(pending.end_seconds, stop_at_seconds)
    # The compiled boundary has already admitted the original immutable input
    # graph. A generic canonical_copy here would create an equal FOREIGN graph
    # and invalidate that authority; copy dynamic state only, with an explicit
    # input memo. This also applies to the detailed compatibility branch. The
    # complete mutable guards at entry and checkpoint checks before publication
    # remain in force. Legacy BASELINE behavior is unchanged.
    candidate = (_quiet_clone_context(state.context) if
                 state.inputs.quiet_policy is not None or state.static_admission is not None else
                 checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs)))
    hardware = state.harness.hardware; geometry = pending.geometry; cuts = (); accounting = None
    contacts = (); bindings = (); receipts = (); record = association = None; attitude = state.attitude
    quiet_controller = state.quiet_controller
    service_private = None; interruption = None;environment_history=state.environment_ageing_state
    try:
        if action.kind == 'CONTACT' and state.inputs.service_policy is not None:
            service_private, geometry, contacts, bindings, receipts, b, interruption = _service_contact_piece(
                state, candidate, action, hardware, a, b)
            candidate = service_private.context
        elif action.kind == 'CONTACT':
            geometry, contacts, bindings, receipts,environment_history = _contact_piece(state, candidate, action, hardware, a, b)
        elif b > a and state.inputs.service_policy is not None:
            if action.kind in ('HOLD_UNTIL','SOLAR_HOLD') and state.inputs.quiet_policy is not None:
                service_private, cuts, accounting, quiet_controller = _service_quiet_physical_piece(
                    state, candidate, hardware, a, b, pending)
            else:
                service_private, cuts, accounting, b, interruption = _service_physical_piece(
                    state, candidate, hardware, a, b, pending)
            candidate = service_private.context
        elif b > a and action.kind in ('HOLD_UNTIL','SOLAR_HOLD') and state.inputs.quiet_policy is not None:
            if state.inputs.environment_ageing_policy is None:
                candidate, cuts, accounting, quiet_controller = _quiet_physical_piece(state,candidate,hardware,a,b,pending)
            else:
                candidate,cuts,accounting,quiet_controller,environment_history=_environment_quiet_physical_piece(state,candidate,hardware,a,b,pending)
        elif b > a:
            cuts, accounting,environment_history = _physical_piece(state, candidate, hardware, a, b, pending)
        complete = b == pending.end_seconds and interruption is None
        if action.kind in ('POINT','SOLAR_POINT'):
            attitude = BodyAttitude3D(state.attitude.body_frame_id, state.attitude.inertial_frame, Q(b),
                pending.slew.quaternion_at(Q(b-pending.origin_seconds)),
                Q(pending.origin_seconds+pending.slew.rest_start_offset_seconds) if complete else
                    min(pending.original_attitude.rest_since_seconds, Q(a)))
        else: attitude = replace(attitude, at_seconds=Q(b))
        if quiet_controller is not None and quiet_controller.clock_seconds != Q(b):
            quiet_controller = replace(quiet_controller, clock_seconds=Q(b),
                last_step_seconds=Q(0), phase='DETAILED_ACTION')
        if action.kind == 'CAPTURE' and complete:
            record, association = pending.acquired_record, pending.acquisition_plan
            candidate.spacecraft_state.data_storage.stored_records += (record,)
        candidate.simulation_time_seconds = b
        candidate.diagnostics.completed_steps = state.context.diagnostics.completed_steps+1
        if action.kind != 'CONTACT':
            candidate.spacecraft_state.onboard.operational_mode = {'POINT': OperationalMode.MANEUVER,
                'SOLAR_POINT': OperationalMode.MANEUVER,'SOLAR_HOLD': OperationalMode.STANDBY,
                'CAPTURE': OperationalMode.IMAGING, 'HOLD_UNTIL': OperationalMode.STANDBY}[action.kind]
        if service_private is not None and action.kind != 'CONTACT':
            onboard = candidate.spacecraft_state.onboard
            service = service_private.service_state
            if service.mode != 'NORMAL' or not service.essential_serviceable:
                onboard.operational_mode = OperationalMode.SAFE
                onboard.fdir_state = FDIRState.BACKUP
                onboard.critical_energy_since_seconds = (
                    state.context.spacecraft_state.onboard.critical_energy_since_seconds
                    if state.context.spacecraft_state.onboard.critical_energy_since_seconds is not None else a
                ) if not service.essential_serviceable else None
            else:
                onboard.fdir_state = FDIRState.NORMAL
                onboard.critical_energy_since_seconds = None
        _admit_lifecycle_context(candidate, state.inputs.service_policy)
        _validate_completed_context(candidate); _checked_lifecycle_checkpoint(state,candidate)
        acquisitions = state.acquisitions if record is None else (*state.acquisitions, MSAcquisitionEvidence(record, association))
        if len(acquisitions) > state.inputs.limits.max_active_products or len(state.receipts)+len(receipts) > state.inputs.limits.max_active_products:
            raise ValueError('LIFECYCLE_ACTIVE_CUSTODY_CAPACITY')
        if {r.record_id for r in state.receipts} & {r.record_id for r in receipts}:
            raise ValueError('duplicate completing receipt')
        projected = replace(state, context=candidate, attitude=attitude, acquisitions=acquisitions,
            receipts=(*state.receipts, *receipts), pending=(None if complete or interruption is not None and action.kind not in ('POINT','SOLAR_POINT') else pending),
            consumed_through_seconds=b if action.kind == 'CONTACT' else state.consumed_through_seconds,
            transition_count=state.transition_count+1,
            completed_actions=state.completed_actions+(complete or interruption is not None and action.kind not in ('POINT','SOLAR_POINT')),
            quiet_controller=quiet_controller,
            service_state=state.service_state if service_private is None else service_private.service_state,
            service_work=state.service_work if service_private is None else service_private.service_work,
            last_service_diagnostic=state.last_service_diagnostic if service_private is None else service_private.last_service_diagnostic,
            environment_ageing_state=environment_history if service_private is None else service_private.environment_ageing_state,
            battery_port_state=state.battery_port_state if service_private is None else service_private.battery_port_state,
            solar_state=advance_solar_state(state.solar_state,action,pending.solar_target,cuts,a,b,
                'refused' if interruption is not None else 'completed' if complete else 'partial',None if interruption is None else str(interruption),state.source_authority,state.inputs.energy_attitude_policy))
        guard_lifecycle_physical(projected); state.source_authority.guard()
    except _Refusal as error:
        return _refused(state, action, error, pending=pending)
    except ValueError as error:
        if state.inputs.environment_ageing_policy is None or not str(error).startswith('B61'):raise
        return _refused(state,action,_Refusal('B61_ENVIRONMENT_DOMAIN_REFUSED:'+str(error)),pending=pending)
    outcome = LifecycleActionOutcome(action.action_id, action.kind,
        'refused' if interruption is not None else 'completed' if complete else 'partial',
        str(interruption) if interruption is not None else None, a, b, geometry, cuts, contacts,
        record, association, attitude, accounting, pending.slew, bindings,
        failure_diagnostic=() if interruption is None else interruption.diagnostic,
        service_work_before=state.service_work, service_work_after=projected.service_work,
        service_state_after=projected.service_state,solar_target=pending.solar_target,
        solar_state_before=state.solar_state,solar_state_after=projected.solar_state,
        battery_port_state_before=state.battery_port_state,battery_port_state_after=projected.battery_port_state,
        environment_ageing_state_before=state.environment_ageing_state,environment_ageing_state_after=projected.environment_ageing_state)
    if state.quiet_work is not None and action.kind in ('HOLD_UNTIL','SOLAR_HOLD'):
        state.quiet_work.committed_parts += len(cuts)
        state.quiet_work.committed_seconds += Q(b-a)
        state.quiet_work.validate(state.inputs.quiet_policy)
    _commit_action(state.context, candidate)
    return replace(projected, context=state.context), outcome


def assess_lifecycle_product(state, product):
    """Single complete-MS-record credit, exact actual receipt time, no history."""
    if type(product) is not MSProductSpec: raise TypeError('exact MS product required')
    product.__post_init__(); now = state.context.simulation_time_seconds
    acquisitions = [e for e in state.acquisitions if e.plan.request.request_id == product.request.request_id]
    receipts = {r.record_id: r for r in state.receipts}
    deliveries = {d.record.record_id: d for d in state.context.ground_data_delivery_state.completed_deliveries}
    reasons = []
    for evidence in acquisitions:
        plan = evidence.plan; record = evidence.record
        if plan.request.target_id != product.request.target_id: reasons.append('wrong-target'); continue
        if plan.capture_group != product.capture_group or plan.sizing.footprint != product.footprint:
            reasons.append('incompatible-capture-group'); continue
        if not product.acquisition_start_seconds <= record.scheduled_start_seconds < record.scheduled_start_seconds+record.acquisition_duration_seconds <= product.acquisition_end_seconds:
            reasons.append('outside-acquisition-window'); continue
        if plan.sizing.spacing_x_m > product.maximum_spacing_x_m or plan.sizing.spacing_y_m > product.maximum_spacing_y_m:
            reasons.append('sampling-criterion-failed'); continue
        if not set(product.required_channels) <= set(plan.sizing.captured_channels):
            reasons.append('missing-required-channels'); continue
        receipt = receipts.get(record.record_id); delivery = deliveries.get(record.record_id)
        if receipt is None or delivery is None: reasons.append('not-delivered'); continue
        if receipt.record != record or delivery.record != record or delivery.completing_contact != receipt.completing_contact:
            raise ValueError('compact receipt/acquisition/custody mismatch')
        if receipt.completion_seconds > product.delivery_deadline_seconds:
            reasons.append('late-delivery'); continue
        return MSProductAssessment('credited', (), (record.record_id,), receipt.completion_seconds)
    return MSProductAssessment('expired' if now >= product.delivery_deadline_seconds else 'pending',
        tuple(dict.fromkeys(reasons)) or ('not-acquired',), (), None)


def pending_pins_product(pending, request_id):
    """Exact action types, never a fabricated product field on solar intent."""
    if type(request_id) is not str: raise TypeError('exact request pin identity')
    if pending is None: return False
    action = pending.action
    if type(action) is SolarAction:
        if action.kind not in ('SOLAR_POINT', 'SOLAR_HOLD'): raise ValueError('unknown solar pending kind')
        return False
    if type(action) is LongMissionAction:
        # A CONTACT consumes the active custody population, including partial
        # transfers. Its action has no individual product_id by design.
        return action.kind == 'CONTACT' or action.product_id == request_id
    raise TypeError('unknown pending product-pin action type')


def retire_lifecycle_products(state, request_ids, *, reported_through_seconds, allow_discard_expired=False):
    """Explicitly release accounted active custody; cumulative work never resets.

    The caller also guarantees no pending/late observation, command or report
    references these requests.  The lifecycle coordinator enforces that causal
    pin set.  This low-level primitive enforces actual disposition/time facts.
    """
    guard_lifecycle_physical(state)
    _natural(reported_through_seconds, 'reported frontier', maximum=state.context.simulation_time_seconds)
    if reported_through_seconds < state.reported_through_seconds: raise ValueError('report frontier cannot rewind')
    if (type(allow_discard_expired) is not bool or type(request_ids) is not tuple or
            any(type(value) is not str for value in request_ids) or len(set(request_ids)) != len(request_ids)):
        raise ValueError('explicit distinct retirement requests required')
    ids = set(request_ids)
    products = {p.request.request_id.value: p for p in state.inputs.products}
    if not ids <= set(products): raise ValueError('unknown or previously retired request')
    if any(pending_pins_product(state.pending, rid) for rid in ids):
        raise ValueError('pending action pins request')
    for identifier in ids:
        product = products[identifier]; assessment = assess_lifecycle_product(state, product)
        if assessment.status == 'pending': raise ValueError('pending product cannot retire')
        if assessment.status == 'expired' and (not allow_discard_expired or reported_through_seconds < product.delivery_deadline_seconds):
            raise ValueError('expired disposition requires explicit accounted discard')
        if assessment.completion_time_seconds is not None and assessment.completion_time_seconds > reported_through_seconds:
            raise ValueError('unreported completed product cannot retire')
    candidate = (_checked_lifecycle_checkpoint(state,state.context).restore(state.context.inputs) if state.static_admission is not None else
                 checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs)))
    removed = {e.record.record_id for e in state.acquisitions if e.plan.request.request_id.value in ids}
    candidate.spacecraft_state.data_storage.stored_records = tuple(r for r in candidate.spacecraft_state.data_storage.stored_records if r.record_id not in removed)
    candidate.ground_data_delivery_state.partial_transfers = tuple(p for p in candidate.ground_data_delivery_state.partial_transfers if p.record_id not in removed)
    candidate.ground_data_delivery_state.completed_deliveries = tuple(d for d in candidate.ground_data_delivery_state.completed_deliveries if d.record.record_id not in removed)
    result = replace(state, context=candidate,
        inputs=replace(state.inputs, products=tuple(p for p in state.inputs.products if p.request.request_id.value not in ids)),
        acquisitions=tuple(e for e in state.acquisitions if e.record.record_id not in removed),
        receipts=tuple(r for r in state.receipts if r.record_id not in removed),
        reported_through_seconds=reported_through_seconds)
    guard_lifecycle_physical(result); _commit_action(state.context, candidate)
    return replace(result, context=state.context), tuple(sorted(removed, key=lambda r: r.value))


def _environment_quiet_physical_piece(state,candidate,hardware,a,b,pending):
    """Bounded nonservice quiet consumer; same full/two-half paid engine."""
    from .environment_lifecycle import EnvironmentPrivate
    from .environment_thermal import construction_environment_substep
    schedule=state.source_authority.schedule(Q(a),Q(b))
    if not schedule.cells or any(c.assessment=='UNRESOLVED'for c in schedule.cells):raise _Refusal('UNRESOLVED_ILLUMINATION')
    points=sorted({Q(a),Q(b)}|{x for c in schedule.cells for x in (c.start_seconds,c.end_seconds)})
    private=EnvironmentPrivate(candidate,state.environment_ageing_state);controller=state.quiet_controller;selected=[]
    required=state.inputs.protection.standby_node_ids
    def values(v):return _quiet_state_values(v.context,environment=(state,v.context,v.history))
    def step(v,left,right):
        state.runtime_work.charge('physical_reserved_calls',1,state.inputs.limits)
        forcing,eps,camera,panel,supports=_forcing(state,hardware,left,right,state.attitude.quaternion)
        binding,nxt=prepare_environment_cut(state,v.context,v.history,left,right,forcing)
        part,carrier=construction_environment_substep(v.context,RationalSeconds.from_fraction(right-left),forcing,eps,state.inputs.protection,None,
            compilation=state.construction.compilation,work=state.construction.work,limits=state.inputs.construction_limits,environment_binding=binding)
        state.runtime_work.physical_completed_calls+=1
        if part is None:raise QuietTrialRefusal(_Refusal('FULL_ELECTRICAL_SERVICE_UNAVAILABLE'))
        part=complete_environment_cut(v.context,state.inputs.environment_ageing_policy,v.history,nxt,part);v.history=nxt
        if _violations(v.context,required):raise QuietTrialRefusal(_Refusal('OPERATING_TEMPERATURE_AT_ENDPOINT'))
        cut=MissionPhysicalCut(left,right,supports,forcing.incidence_angle_deg,camera,panel,0.,0.,0.,0.,part,state.attitude.quaternion,None,Q(0),Q(0))
        sample=_quiet_sample(state,v.context,part)
        sample=replace(sample,state_values=values(v))
        return QuietTrial(v,cut,sample)
    try:
        for left,right in zip(points,points[1:]):
            result=__import__(__package__+'.lifecycle_backend',fromlist=['quiet_call']).quiet_call(state,integrate_quiet_hold,private,left,right,policy=state.inputs.quiet_policy,controller=controller,work=state.quiet_work,
                clone_context=lambda v:EnvironmentPrivate(_quiet_clone_context(v.context),v.history),state_values=values,step=step)
            private=result.context;controller=result.controller;selected.extend(result.cuts)
            if len(selected)>state.inputs.limits.max_retained_cuts:raise _Refusal('LIFECYCLE_LOCAL_ACTION_PARTITION_LIMIT')
    except QuietTrialRefusal as error:raise error.original from error
    return private.context,tuple(selected),_aggregate(tuple(c.part for c in selected)),controller,private.history
