"""Additive full-spatial mission coordinator, same accepted physical transactions.

No numerical owner or legacy wire identity changes. Arbitrary rational physical
cuts use the shared completion owner. Constant integral contact cells delegate
to the accepted multi-record custody/protection executor; unsupported cuts refuse.
"""
from dataclasses import dataclass, replace
from fractions import Fraction as Q
from math import ceil, degrees, fsum, isfinite
from hashlib import sha256

from .long_nominal_provider import LongNominalProvider, LongNominalPolicy
from .long_environment import LongEnvironment, AcquiredLongEnvironment, NOMINAL, CONTINUOUS
from .long_general_geometry import LongGeometryPolicy, admit_long_geometry_domain, evaluate_long_geometry

from .environment_forcing import (EnvironmentForcingRequest, ForcingProfileEntry,
    adapt_environment_forcing, _type, _text, _integer, _number)
from .environment_forcing_document import environment_forcing_digest
from .assembly_attitude import ComponentAxisBinding, angle_between, vector
from .assembly_attitude_3d import (NetTorqueActuatorPolicy as ActuatorPolicy, BodyAttitude3D,
    compile_assembly_hardware_3d as compile_assembly_hardware, canonical_quaternion)
from .assembly_slew_3d import plan_target_slew_3d as plan_target_slew
from .mission_camera_3d import exact_held_camera
from .mission_environment import (CatalogPoint, SamplingPolicy, sample_catalog, sample_interval, MODE as SAMPLED_MODE)
from .mission_general_geometry import (MODE as GENERAL_MODE, GeneralGeometryPolicy,
    admit_general_geometry_domain, evaluate_general_geometry)
from .mission_continuous_geometry import (MODE as CONTINUOUS_MODE, ContinuousGeometryPolicy,
    admit_geometry_domain, _bind_acquired_source, evaluate_continuous_geometry)
from .assembly_choices import AssemblyDesign
from .context import SimulationInputs, SimulationContext
from .checkpoint import CheckpointState
from .continuation import checked_checkpoint, ImagingAction
from .engine import _validate_completed_context
from .substepped_execution import (_physical_substep, _commit_action, _aggregate,
                                   _violations, _imaging_request)
from .operational_protection import StandbyInputs, ProtectionPolicy, validate_policy
from .eps_system import EPSIntervalInputs
from .thermal_routing import ComponentHeatRoutingConfig
from .integration_time import RationalSeconds, IntegrationPolicy
from .degradation import SolarDegradationForcingInput
from .state import OperationalMode, FDIRState
from .power_loads import PowerLoadBreakdown
from .orbit_j2 import evaluate_j2_cartesian_state, J2RK4SolverConfig
from .orbit_config import GeometryInstant
from .sun_table import evaluate_sun_position
from . import orbit_sun_zonotope_local_v2 as light
from .experiment_codec import canonical_copy, canonical_content
from .adcs import CommonFrameBoresightDirection
from .ids import (ADCSBoresightFrameId, AcquisitionDataRecordId, GroundContactId,
                  ObservationOpportunityId, GroundTargetId, GroundStationId)
from .observation import ObservationOpportunity, ObservationPointing
from .observation_feasibility import ObservationManeuverCandidate
from .imaging_feasibility import ObservationAcquisitionCandidate
from .imaging_execution import ScheduledObservationAcquisitionExecution
from .imaging_resources import AcquisitionEPSIntervalEnvironment
from .payload import OpticalAcquisitionInput, OpticalAcquisitionChannelSelection
from .ms_acquisition import InitialAttitudeEvidence
from .ms_product import (MSProductSpec, MSAcquisitionPlan, MSAcquisitionEvidence,
    MSFootprint, REQUIRED_MS_CHANNELS, size_ms_grid, assess_ms_product)
from .coupled_downlink import CoupledDownlinkInputs, DownlinkTransmitterConfig
from .communications import ServiceableGroundContact
from .contact_execution import ContactPlan, ConsumedContacts, execute_contact_plan

def admit_operational_regime(context):
    """This bounded coordinator owns NORMAL activity only; no FDIR recovery.

    SAFE/BACKUP/emergency and any pending essential-energy marker require an
    accepted recovery owner outside this adapter. Reject before paid work.
    """
    onboard=context.spacecraft_state.onboard
    if (onboard.fdir_state is not FDIRState.NORMAL or
        onboard.operational_mode not in (OperationalMode.STANDBY, OperationalMode.IMAGING,
                                        OperationalMode.DOWNLINK, OperationalMode.MANEUVER) or
        onboard.critical_energy_since_seconds is not None):
        raise ValueError('UNSUPPORTED_MISSION_OPERATIONAL_REGIME')


HEAT_CONTRACT='ROUTED_INTERNAL_EXPLICIT_RADIATION_NO_DUPLICATE_V1'


@dataclass(frozen=True,slots=True)
class LongMissionAction:
    action_id: str
    kind: str
    point_id: str = ''
    duration_seconds: int = 0
    until_seconds: int = 0
    product_id: str = ''

    def __post_init__(self):
        _text(self.action_id,'action ID',256)
        AcquisitionDataRecordId(self.action_id)
        if type(self.kind) is not str or self.kind not in ('POINT','CAPTURE','HOLD_UNTIL','CONTACT'):
            raise ValueError('unsupported mission action')
        _integer(self.duration_seconds,'action duration');_integer(self.until_seconds,'absolute end')
        if self.duration_seconds>120 or self.until_seconds>2**40:raise ValueError('action bound exceeded')
        if self.kind in ('POINT','CAPTURE','CONTACT'):_text(self.point_id,'catalog point',256)
        if self.kind in ('CAPTURE','CONTACT') and self.duration_seconds<=0:raise ValueError('positive action duration required')
        if self.kind=='CAPTURE':_text(self.product_id,'product request ID',256)
        elif self.product_id:raise ValueError('only capture owns a product binding')
        if self.kind=='POINT' and (self.duration_seconds or self.until_seconds):raise ValueError('point duration must be derived')
        if self.kind=='HOLD_UNTIL' and (self.point_id or self.duration_seconds):raise ValueError('hold requires only its exact end')


@dataclass(frozen=True,slots=True)
class LongSamplingPolicy:
    maximum_interval_seconds: int = 2
    maximum_points: int = 16
    maximum_timestamps: int = 256
    def __post_init__(self):
        for n,cap in (('maximum_interval_seconds',120),('maximum_points',16),('maximum_timestamps',256)):
            if type(getattr(self,n)) is not int or not 1<=getattr(self,n)<=cap:raise ValueError('long sampling limit: '+n)

@dataclass(frozen=True,slots=True)
class LongMissionLimits:
    max_actions: int = 128
    max_products: int = 16
    max_physical_substeps: int = 65536
    max_runtime_upstream_entries: int = 16
    max_runtime_entries: int = 32
    max_nominal_orbit_queries: int = 65536
    max_point_geometry_queries: int = 16384
    max_interval_seconds: int = 30
    max_action_cells: int = 4096
    contact_integration_level: int = 2
    max_document_bytes: int = 256*2**20
    max_retained_cuts: int = 4096
    max_geometry_queries: int = 64
    max_geometry_operations: int = 2**26
    max_geometry_control_units: int = 2**26
    max_spatial_reserved_units: int = 2**26
    max_nominal_force_reserved: int = 2**20
    max_nominal_control_units: int = 2**30
    max_index_control_units: int = 2**30
    max_output_control_units: int = 2**34
    def __post_init__(self):
        caps=dict(max_actions=128,max_products=16,max_physical_substeps=65536,max_runtime_upstream_entries=16,max_runtime_entries=32,max_nominal_orbit_queries=65536,max_point_geometry_queries=16384,max_interval_seconds=120,max_action_cells=8192,contact_integration_level=6,max_document_bytes=512*2**20,max_retained_cuts=8192,max_geometry_queries=64,max_geometry_operations=2**30,max_geometry_control_units=2**30,max_spatial_reserved_units=2**26,max_nominal_force_reserved=2**20,max_nominal_control_units=2**30,max_index_control_units=2**30)
        caps['max_output_control_units']=2**34
        for n,cap in caps.items():
            _integer(getattr(self,n),n)
            if not (0 if n=='contact_integration_level' else 1)<=getattr(self,n)<=cap:raise ValueError('long mission limit: '+n)
        if self.max_document_bytes<16*2**20:raise ValueError('long document allowance too small')

@dataclass(frozen=True,slots=True)
class LongMissionInputs:
    simulation_inputs: SimulationInputs
    initial_checkpoint: CheckpointState
    environment: LongEnvironment
    assembly: AssemblyDesign
    capabilities: tuple[ComponentAxisBinding,...]
    actuator: ActuatorPolicy
    catalog: tuple[CatalogPoint,...]
    sampling: LongSamplingPolicy
    actions: tuple[LongMissionAction,...]
    products: tuple[MSProductSpec,...]
    protection: ProtectionPolicy
    routing: ComponentHeatRoutingConfig
    transmitter: DownlinkTransmitterConfig
    initial_quaternion: tuple[float,float,float,float]
    camera_half_fov_rad: float
    solar_retention_loss_per_second: float
    nominal_policy: LongNominalPolicy = LongNominalPolicy()
    limits: LongMissionLimits = LongMissionLimits()
    geometry_policy: LongGeometryPolicy = LongGeometryPolicy()
    api: str = 'B44_LONG_CONNECTED_MISSION_V5'
    heat_contract: str = HEAT_CONTRACT
    refusal_policy: str = 'SKIP_GEOMETRY_REFUSE_PHYSICAL_ATOMIC_V1'
    def __post_init__(self):
        for v,c,n in ((self.simulation_inputs,SimulationInputs,'simulation'),(self.initial_checkpoint,CheckpointState,'checkpoint'),(self.environment,LongEnvironment,'environment'),(self.limits,LongMissionLimits,'limits'),(self.sampling,LongSamplingPolicy,'sampling'),(self.nominal_policy,LongNominalPolicy,'nominal'),(self.geometry_policy,LongGeometryPolicy,'geometry')):
            _type(v,c,n)
        for v in (self.environment,self.limits,self.sampling,self.nominal_policy,self.geometry_policy):v.__post_init__()
        if self.api!='B44_LONG_CONNECTED_MISSION_V5' or type(self.api) is not str:raise ValueError('unsupported long API')
        if type(self.actions) is not tuple or not 1<=len(self.actions)<=self.limits.max_actions:raise ValueError('program bound')
        for a in self.actions:_type(a,LongMissionAction,'action');a.__post_init__()
        if len({a.action_id for a in self.actions})!=len(self.actions):raise ValueError('duplicate action ID')
        if type(self.catalog) is not tuple or not 1<=len(self.catalog)<=self.sampling.maximum_points:raise ValueError('catalog bound')
        for e in self.catalog:_type(e,CatalogPoint,'catalog');e.__post_init__();admit_long_geometry_domain(self.environment,e,self.geometry_policy)
        points={e.point.point_id.value:e for e in self.catalog}
        if len(points)!=len(self.catalog):raise ValueError('duplicate catalog point')
        if type(self.products) is not tuple or not 1<=len(self.products)<=self.limits.max_products:raise ValueError('product bound')
        for p in self.products:_type(p,MSProductSpec,'product');p.__post_init__()
        ids={p.request.request_id.value:p for p in self.products}
        if len(ids)!=len(self.products) or len({p.capture_group for p in self.products})!=len(self.products):raise ValueError('ambiguous product binding')
        for p in self.products:
            if p.request.target_id.value not in points or type(points[p.request.target_id.value].point.point_id) is not GroundTargetId:raise ValueError('foreign product target')
            if not self.environment.start_seconds<=p.acquisition_start_seconds<p.acquisition_end_seconds<=p.delivery_deadline_seconds<=self.environment.end_seconds:raise ValueError('product outside world')
        for a in self.actions:
            if a.kind!='HOLD_UNTIL':
                if a.point_id not in points or type(points[a.point_id].point.point_id) is not (GroundStationId if a.kind=='CONTACT' else GroundTargetId):raise ValueError('foreign catalog role')
            if a.kind=='CAPTURE' and (a.product_id not in ids or a.point_id!=ids[a.product_id].request.target_id.value):raise ValueError('foreign capture/product binding')
        ctx=self.initial_checkpoint.restore(self.simulation_inputs);validate_policy(self.protection,ctx);admit_operational_regime(ctx)
        if Q(ctx.simulation_time_seconds)!=self.environment.start_seconds or self.environment.end_seconds>ctx.inputs.common_world.horizon_seconds or ctx.inputs.common_world.event_ids:raise ValueError('original event-free world boundary required')
        if self.simulation_inputs.coast_orbit is not None:raise ValueError('long input alone owns orbit')
        if ctx.spacecraft_state.data_storage.stored_records or ctx.ground_data_delivery_state.partial_transfers or ctx.ground_data_delivery_state.completed_deliveries:raise ValueError('initial custody must be empty')
        _type(self.routing,ComponentHeatRoutingConfig,'routing');self.routing.__post_init__()
        _type(self.transmitter,DownlinkTransmitterConfig,'transmitter');self.transmitter.__post_init__()
        if any(n.internal_dissipation_w!=0 for e in self.environment.profile for n in e.nodes):raise ValueError('routed internal heat only')
        if any(e.loads.payload_w or e.loads.communications_w or e.loads.propulsion_w for e in self.environment.profile):raise ValueError('baseline mission loads must leave acquisition/transmitter off')
        from .thermal_routing import ElectricalLoadComponent
        route=next(r for r in self.routing.routes if r.component is ElectricalLoadComponent.ADCS)
        if route.thermal_node_id!=ctx.inputs.spacecraft_configuration.thermal.network.bus_node_id or route.retained_heat_fraction.value!=1:raise ValueError('ADCS storage adjustment requires full bus route')
        if self.heat_contract!=HEAT_CONTRACT or self.refusal_policy!='SKIP_GEOMETRY_REFUSE_PHYSICAL_ATOMIC_V1':raise ValueError('unsupported heat/refusal contract')
        object.__setattr__(self,'initial_quaternion',canonical_quaternion(self.initial_quaternion))
        _number(self.camera_half_fov_rad,'FOV',positive=True)
        if self.camera_half_fov_rad>=1.5707963267948966:raise ValueError('forward FOV required')
        _number(self.solar_retention_loss_per_second,'loss rate')
        if self.solar_retention_loss_per_second*120>=1:raise ValueError('per-cut retention domain')
        span=self.environment.end_seconds-self.environment.start_seconds
        needed=ceil(span/Q(self.nominal_policy.step_seconds))
        if needed>self.nominal_policy.max_steps:raise ValueError('nominal original-grid admission')
        if self.limits.max_output_control_units<8*2**20+(self.limits.max_document_bytes+63)//64:raise ValueError('output-control admission before work')
        compile_assembly_hardware(self.assembly,self.capabilities,self.actuator)
        from .long_mission_document import input_data,canonical_json,_bounded_tree
        data=input_data(self);_bounded_tree(data)
        if len(canonical_json(data).encode())>16*2**20:raise ValueError('long immutable input byte admission')
    @property
    def geometry_mode(self):return self.environment.mode

@dataclass(slots=True)
class RuntimeWork:
    output_control_units: int = 0
    runtime_entries: int = 0
    nominal_force_reserved: int = 0
    nominal_force_completed: int = 0
    nominal_control_units: int = 0
    index_control_units: int = 0
    nominal_unknown_events: int = 0
    upstream_entries: int = 0
    nominal_orbit_queries: int = 0
    point_geometry_queries: int = 0
    physical_reserved_calls: int = 0
    physical_completed_calls: int = 0
    reconstruction_count: int = 0
    geometry_queries: int = 0
    geometry_operations: int = 0
    geometry_control_units: int = 0
    contact_work_unknown_events: int = 0
    physical_work_unknown_events: int = 0
    spatial_reserved_units: int = 0

    def validate(self,limits):
        for name in self.__dataclass_fields__:_integer(getattr(self,name),'runtime '+name)
        for name,cap in (('output_control_units',limits.max_output_control_units),('runtime_entries',limits.max_runtime_entries),('nominal_unknown_events',limits.max_nominal_force_reserved),('nominal_force_reserved',limits.max_nominal_force_reserved),('nominal_control_units',limits.max_nominal_control_units),('index_control_units',limits.max_index_control_units),('upstream_entries',limits.max_runtime_upstream_entries),
            ('nominal_orbit_queries',limits.max_nominal_orbit_queries),
            ('point_geometry_queries',limits.max_point_geometry_queries),
            ('physical_reserved_calls',limits.max_physical_substeps),
            ('geometry_queries',limits.max_geometry_queries),('geometry_operations',limits.max_geometry_operations),
            ('geometry_control_units',limits.max_geometry_control_units),('spatial_reserved_units',limits.max_spatial_reserved_units)):
            if getattr(self,name)>cap:raise ValueError('invalid cumulative runtime work')
        if (self.physical_completed_calls>self.physical_reserved_calls or self.nominal_force_completed>self.nominal_force_reserved or self.nominal_unknown_events>self.nominal_force_reserved or self.reconstruction_count>self.runtime_entries or
            self.contact_work_unknown_events+self.physical_work_unknown_events>self.physical_reserved_calls):
            raise ValueError('inconsistent cumulative runtime work')

    def charge(self,name,count,limits):
        self.validate(limits)
        _integer(count,'runtime charge')
        cap={'output_control_units':limits.max_output_control_units,'runtime_entries':limits.max_runtime_entries,'nominal_unknown_events':limits.max_nominal_force_reserved,'nominal_force_reserved':limits.max_nominal_force_reserved,'nominal_control_units':limits.max_nominal_control_units,'index_control_units':limits.max_index_control_units,'upstream_entries':limits.max_runtime_upstream_entries,
             'nominal_orbit_queries':limits.max_nominal_orbit_queries,
             'point_geometry_queries':limits.max_point_geometry_queries,
             'physical_reserved_calls':limits.max_physical_substeps,'geometry_queries':limits.max_geometry_queries,
             'geometry_operations':limits.max_geometry_operations,'geometry_control_units':limits.max_geometry_control_units,'spatial_reserved_units':limits.max_spatial_reserved_units}[name]
        if getattr(self,name)+count>cap:raise ValueError('CUMULATIVE_RUNTIME_QUOTA_EXHAUSTED:'+name)
        setattr(self,name,getattr(self,name)+count)


@dataclass(frozen=True,slots=True)
class LongMissionActionForcing:
    """Private adapter to the real physical completion owner, not standby admission."""
    loads: PowerLoadBreakdown
    sunlit: bool
    incidence_angle_deg: float
    routing_config: ComponentHeatRoutingConfig
    thermal_inputs: object
    external_heat_sources: object
    solar_degradation_forcing: object = None

    def __post_init__(self):
        EPSIntervalInputs(self.sunlit,self.incidence_angle_deg,self.loads)
        self.routing_config.__post_init__()
        self.thermal_inputs.__post_init__();self.external_heat_sources.__post_init__()
        if any(n.internal_dissipation_w!=0 for n in self.external_heat_sources.node_sources):
            raise ValueError('only routed internal heat is allowed')


@dataclass(frozen=True,slots=True)
class MissionPhysicalCut:
    start_seconds: Q
    end_seconds: Q
    source_support_indices: tuple[int,...]
    incidence_angle_deg: float
    camera_inertial: tuple
    panel_inertial: tuple
    kinetic_start_j: float
    kinetic_end_j: float
    actuator_draw_w: float
    heat_adjustment_w: float
    part: object
    pose_quaternion: tuple
    euler_midpoint: object
    kinetic_start_exact_j: Q
    kinetic_end_exact_j: Q


@dataclass(frozen=True,slots=True)
class MissionContactForcing:
    start_seconds: Q
    end_seconds: Q
    source_support_indices: tuple
    incidence_angle_deg: float
    camera_inertial: tuple
    panel_inertial: tuple
    transmitter_inputs: CoupledDownlinkInputs
    idle_inputs: StandbyInputs
    contact_id: GroundContactId


@dataclass(frozen=True,slots=True)
class EnvironmentActionOutcome:
    action_id: str
    kind: str
    status: str
    reason: str | None
    start_seconds: int
    end_seconds: int
    geometry: tuple
    cuts: tuple[MissionPhysicalCut,...]
    contact_outcomes: tuple
    acquired_record: object
    acquisition_plan: object
    attitude: BodyAttitude3D
    accounting: object
    slew: object = None
    contact_forcing: tuple[MissionContactForcing,...] = ()
    continuous_geometry: object = None
    failure_diagnostic: tuple = ()


@dataclass(slots=True)
class LongMissionState:
    inputs: LongMissionInputs
    context: SimulationContext
    attitude: BodyAttitude3D
    cursor: int
    outcomes: tuple[EnvironmentActionOutcome,...]
    acquisitions: tuple[MSAcquisitionEvidence,...]
    consumed_contacts: ConsumedContacts
    runtime_work: RuntimeWork
    source_result: object
    input_digest: str
    source_authority: object = None

    nominal_provider: object = None
    nominal_prior_completed: int = 0
    nominal_prior_unknown: int = 0
    construction: object = None
    harness: object = None
    def assessment(self):
        return tuple(assess_ms_product(p,self.acquisitions,self.context.ground_data_delivery_state,
            tuple(c for o in self.outcomes for c in o.contact_outcomes),self.context.simulation_time_seconds) for p in self.inputs.products)


def start_long_mission(inputs,*,runtime_work=None):
    _type(inputs,LongMissionInputs,'long mission inputs');inputs.__post_init__()
    from .long_mission_document import mission_input_digest
    work=RuntimeWork() if runtime_work is None else runtime_work
    _type(work,RuntimeWork,'runtime work');work.validate(inputs.limits)
    work.charge('runtime_entries',1,inputs.limits)
    pay=lambda n,c:work.charge(n,c,inputs.limits)
    before_done=work.nominal_force_completed;before_unknown=work.nominal_unknown_events
    provider=LongNominalProvider(inputs.environment.trajectory,inputs.nominal_policy,charge=pay)
    work.nominal_force_completed+=provider.work.force_completed
    source=None
    if inputs.environment.mode==CONTINUOUS:
        work.charge('upstream_entries',1,inputs.limits)
        source=light.evaluate_zonotope_local_illumination_v2(inputs.environment.source_request)
        if not source.coverage_complete:raise ValueError('UPSTREAM_NO_COMPLETE_COVERAGE:'+str(source.reason))
    authority=AcquiredLongEnvironment(inputs.environment,provider,source,charge=pay)
    ctx=inputs.initial_checkpoint.restore(canonical_copy(inputs.simulation_inputs))
    work.charge('spatial_reserved_units',65536,inputs.limits)
    hardware=compile_assembly_hardware(inputs.assembly,inputs.capabilities,inputs.actuator)
    attitude=BodyAttitude3D(hardware.design.body_frame_id,inputs.environment.trajectory.initial_state.position.frame,
        Q(ctx.simulation_time_seconds),inputs.initial_quaternion,Q(ctx.simulation_time_seconds))
    return LongMissionState(inputs,ctx,attitude,0,(),(),ConsumedContacts(()),work,source,mission_input_digest(inputs),authority,provider,before_done,before_unknown)

class _Refusal(ValueError):
    def __init__(self,reason,*,diagnostic=()):
        super().__init__(reason);self.diagnostic=diagnostic


def _charge(state,name,count):state.runtime_work.charge(name,count,state.inputs.limits)


def _entry(state,identifier,station=False):
    matches=[p for p in state.inputs.catalog if p.point.point_id.value==identifier]
    if len(matches)!=1 or type(matches[0].point.point_id) is not (GroundStationId if station else GroundTargetId):
        raise ValueError('foreign catalog role/ID')
    return matches[0]


def _product(state,identifier):
    matches=[p for p in state.inputs.products if p.request.request_id.value==identifier]
    if len(matches)!=1:raise ValueError('unknown bound product')
    return matches[0]


def _observations(state,entry,a,b):
    from .mission_environment import MissionPointObservation
    from .orbit_geometry import evaluate_ground_point_geometry
    from .orbit_visibility import evaluate_ground_visibility
    a=Q(a);b=Q(b);p=state.inputs.sampling
    n=max(1,ceil((b-a)/p.maximum_interval_seconds))
    if n+1>p.maximum_timestamps:raise ValueError('local sample admission')
    times=tuple(a+(b-a)*Q(i,n) for i in range(n+1)) if a<b else (a,)
    out=[]
    for t in times:
        _charge(state,'point_geometry_queries',1)
        orbit=state.nominal_provider.at_seconds(t)
        g=evaluate_ground_point_geometry(entry.point,orbit);vis=evaluate_ground_visibility(entry.point,orbit,entry.visibility_policy)
        out.append(MissionPointObservation(entry.point.point_id,t,orbit.position.instant,Q(orbit.position.instant.elapsed_seconds)-t,g,vis,entry.station_available,entry.rf_admitted,entry.nominal_rate_bps,entry.service_assumption,'B44_NOMINAL_LONG_POINT_GRID_V1'))
    return tuple(out)


def _continuous_admission(state,entry,a,b,hardware,*,capture=False):
    if state.inputs.geometry_mode==NOMINAL:return None
    p=state.inputs.geometry_policy
    return evaluate_long_geometry(state.source_authority,state.inputs.environment,entry,Q(a),Q(b),p,
        held_camera=exact_held_camera(state.attitude,hardware.camera_body_axis,p,charge=lambda n,c:_charge(state,n,c)) if capture else None,
        half_fov_rad=state.inputs.camera_half_fov_rad if capture else None,charge=lambda n,c:_charge(state,n,c))


def _orientation_inputs(state,hardware,time,quaternion,loads=None):
    _charge(state,'spatial_reserved_units',128)
    orbit=state.nominal_provider.at_seconds(Q(time));sun=evaluate_sun_position(state.inputs.environment.table,orbit.position.instant)
    direction=vector(tuple(a-b for a,b in zip(sun.components_m,orbit.position.components_m)))
    attitude=BodyAttitude3D(hardware.design.body_frame_id,orbit.position.frame,Q(time),quaternion,Q(time))
    camera=attitude.direction(hardware.camera_body_axis);panel=attitude.direction(hardware.panel_body_normal)
    return degrees(angle_between(panel,direction)),camera,panel


def _schedule(state,a,b):return state.source_authority.schedule(Q(a),Q(b))


def _forcing(state,hardware,a,b,quaternion,*,adcs_w=0.,payload_w=0.):
    schedule=_schedule(state,a,b)
    if any(c.assessment=='UNRESOLVED' for c in schedule.cells):raise _Refusal('UNRESOLVED_ILLUMINATION')
    incidence,camera,panel=_orientation_inputs(state,hardware,(Q(a)+Q(b))/2,quaternion)
    from .environment_forcing import _case
    cases=[]
    for c in schedule.cells:
        e=state.inputs.environment.profile[c.profile_index]
        e=replace(e,incidence_angle_deg=incidence,loads=replace(e.loads,adcs_w=e.loads.adcs_w+adcs_w,payload_w=e.loads.payload_w+payload_w))
        cases.append(_case(e,c.assessment=='ILLUMINATED'))
    if any(c!=cases[0] for c in cases[1:]):raise ValueError('physical cut crosses forcing change')
    c=cases[0]
    return LongMissionActionForcing(c.eps_inputs.load_breakdown,c.sunlit,incidence,state.inputs.routing,c.thermal_inputs,c.heat_source_inputs),c.eps_inputs,camera,panel,tuple(c.support_index for c in schedule.cells)


def _partition(state,a,b,extra=()):
    schedule=_schedule(state,a,b)
    if any(c.assessment=='UNRESOLVED' and c.end_seconds>c.start_seconds for c in schedule.cells):
        raise _Refusal('UNRESOLVED_ILLUMINATION')
    points={Q(a),Q(b)}|{x for c in schedule.cells for x in (c.start_seconds,c.end_seconds)}
    points|={Q(a)+x for x in extra if Q(0)<x<Q(b)-Q(a)}
    ordered=sorted(points);cuts=[]
    for x,y in zip(ordered,ordered[1:]):
        n=ceil((y-x)/state.inputs.limits.max_interval_seconds)
        if len(cuts)+n>state.inputs.limits.max_action_cells:raise _Refusal('ACTION_PARTITION_LIMIT')
        cuts.extend((x+(y-x)*Q(i,n),x+(y-x)*Q(i+1,n)) for i in range(n))
    if len(cuts)>state.inputs.limits.max_action_cells:raise _Refusal('ACTION_PARTITION_LIMIT')
    retained=sum(len(o.cuts)+len(o.contact_forcing) for o in state.outcomes)
    if retained+len(cuts)>state.inputs.limits.max_retained_cuts or 16*2**20+(retained+len(cuts))*65536>state.inputs.limits.max_document_bytes:raise _Refusal('CAUSAL_RETAINED_BYTES_ADMISSION')
    # Reserve the complete possible physical work before any primitive action.
    _charge(state,'physical_reserved_calls',len(cuts))
    return tuple(cuts)


def _physical_action(state,candidate,hardware,a,b,*,slew=None,payload_w=0.,required=None):
    required=state.inputs.protection.standby_node_ids if required is None else required
    if _violations(candidate,required):raise _Refusal('OPERATING_TEMPERATURE_AT_START')
    partition=_partition(state,a,b,() if slew is None else slew.cuts())
    cuts=[];parts=[]
    for left,right in partition:
        mid=(left+right)/2
        quaternion=state.attitude.quaternion if slew is None else slew.quaternion_at(mid-Q(a))
        k0=k1=Q(0);draw=adjustment=0.
        if slew is not None:
            k0=slew.kinetic_j(left-Q(a));k1=slew.kinetic_j(right-Q(a))
            storage=float((k1-k0)/(right-left))
            # No regeneration: positive mechanical storage must be electrically funded.
            draw=hardware.actuator.electronics_power_w+max(0.,storage)/hardware.actuator.drive_efficiency
            adjustment=-storage
        forcing,eps_inputs,camera,panel,supports=_forcing(state,hardware,left,right,quaternion,adcs_w=draw,payload_w=payload_w)
        solar=(None if state.inputs.solar_retention_loss_per_second==0 else
            SolarDegradationForcingInput(state.inputs.solar_retention_loss_per_second*float(right-left)))
        duration=RationalSeconds.from_fraction(right-left)
        try:
            physical=_physical_substep
            keywords={}
            if state.construction is not None:
                from .construction_physics import construction_physical_substep
                from .design_trade_physics import ElectricalLimitError
                physical=construction_physical_substep;keywords.update(compilation=state.construction.compilation,work=state.construction.work,limits=state.construction.inputs.limits)
            part,eps=physical(candidate,duration,forcing,eps_inputs,state.inputs.protection,solar,**keywords,
                standby=False,internal_heat_adjustments_w=None if slew is None else
                ((candidate.inputs.spacecraft_configuration.thermal.network.bus_node_id,adjustment),))
        except ValueError as exc:
            if state.construction is not None:
                from .design_trade_physics import ElectricalLimitError
                if isinstance(exc,ElectricalLimitError):
                    raise _Refusal('CONSTRUCTION_ELECTRICAL_REFUSED:'+str(exc)) from exc
            state.runtime_work.physical_work_unknown_events+=1
            raise
        except BaseException:
            state.runtime_work.physical_work_unknown_events+=1
            raise
        state.runtime_work.physical_completed_calls+=1
        if part is None:raise _Refusal('FULL_ELECTRICAL_SERVICE_UNAVAILABLE')
        cuts.append(MissionPhysicalCut(left,right,supports,forcing.incidence_angle_deg,camera,panel,float(k0),float(k1),draw,adjustment,part,quaternion,
            None if slew is None else slew.euler_at(mid-Q(a)),k0,k1));parts.append(part)
        if _violations(candidate,required):raise _Refusal('OPERATING_TEMPERATURE_AT_ENDPOINT',diagnostic=('PAID_PRIVATE_ENDPOINT_NOT_PUBLISHED',right,part))
    return tuple(cuts),_aggregate(tuple(parts))


def _capture_definition(state,candidate,action,hardware,observations):
    start=candidate.simulation_time_seconds;end=start+action.duration_seconds
    product=_product(state,action.product_id)
    if not product.acquisition_start_seconds<=start<end<=product.acquisition_end_seconds:
        raise _Refusal('ACQUISITION_WINDOW_MISSED')
    if any(not o.visible for o in observations):raise _Refusal('TARGET_NOMINAL_SAMPLED_NOT_VISIBLE')
    camera=state.attitude.direction(hardware.camera_body_axis)
    if any(angle_between(camera,o.direction.components)>state.inputs.camera_half_fov_rad for o in observations):
        raise _Refusal('CAMERA_TARGET_SEPARATION_EXCEEDS_FOV')
    entry=observations[0];azimuth=entry.geometry.orbital_azimuth_rad
    if azimuth is None:
        if entry.off_nadir_rad!=0:raise _Refusal('UNDEFINED_LOCAL_VIEW_AZIMUTH')
        azimuth=0.  # Exact nominal nadir: azimuth is immaterial, C1 status retained.
    opportunity=ObservationOpportunity(ObservationOpportunityId('b44.'+action.action_id),product.request.request_id,
        start,end,action.duration_seconds,ObservationPointing(degrees(entry.off_nadir_rad),degrees(azimuth)%360))
    boresight=CommonFrameBoresightDirection(ADCSBoresightFrameId('b44-long-full-spatial-model-inertial-bound-in-packet'),*camera)
    cfg=candidate.inputs.spacecraft_configuration.payload.optical_acquisition
    footprint=product.footprint
    optical=OpticalAcquisitionInput(footprint.width_m,footprint.length_m,action.duration_seconds,
        OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY)
    execution=ScheduledObservationAcquisitionExecution(ObservationAcquisitionCandidate(
        ObservationManeuverCandidate(opportunity,boresight),optical),start)
    forcing,eps,_,_,_=_forcing(state,hardware,Q(start),Q(start),state.attitude.quaternion)
    association=MSAcquisitionPlan(1,product.request,product.capture_group,
        size_ms_grid(footprint,cfg.multispectral_reference_sample_spacing_m.value,
            cfg.multispectral_reference_sample_spacing_m.value,REQUIRED_MS_CHANNELS,int(cfg.acquisition_bits_per_sample.value)),
        'Declared common synthetic MS capability, integer grid, no calibrated optical performance.')
    image=ImagingAction(action.action_id,execution,AcquisitionDataRecordId('b44.'+action.action_id),
        AcquisitionEPSIntervalEnvironment(forcing.sunlit,forcing.incidence_angle_deg,forcing.loads),
        state.inputs.routing,forcing.thermal_inputs,forcing.external_heat_sources,None)
    if state.attitude.rest_since_seconds.denominator!=1:raise ValueError('settled attitude requires integral origin')
    previous=InitialAttitudeEvidence(state.attitude.rest_since_seconds.numerator,boresight,
        'Actual completed spatial M3 rest/settling, camera body axis from declared M1 mount.')
    record,loads=_imaging_request(candidate,previous,image,association)
    if record is None:raise _Refusal('EXISTING_ACQUISITION_SEQUENCE_OR_STORAGE_REFUSED')
    return record,association,loads.load_breakdown.payload_w-forcing.loads.payload_w


def _contact_action(state,candidate,action,hardware,observations):
    a=candidate.simulation_time_seconds;b=a+action.duration_seconds
    entry=_entry(state,action.point_id,station=True)
    if (not entry.station_available or not entry.rf_admitted or
        state.inputs.geometry_mode==NOMINAL and any(not o.serviceable_nominal for o in observations)):
        raise _Refusal('STATION_GEOMETRY_OR_DECLARED_SERVICE_UNAVAILABLE')
    rate=candidate.inputs.spacecraft_configuration.communications.nominal_downlink_data_rate_bps.value
    if type(rate) not in (int,float) or rate!=int(rate) or int(rate)!=entry.nominal_rate_bps:
        raise ValueError('declared station rate differs from communications authority')
    schedule=_schedule(state,a,b)
    if any(c.assessment=='UNRESOLVED' for c in schedule.cells):raise _Refusal('UNRESOLVED_ILLUMINATION')
    # The old contact owner has a constant-input contract. Split only at exact
    # integral source/profile cuts; a fractional discontinuity explicitly refuses.
    boundaries=sorted({Q(a),Q(b)}|{x for c in schedule.cells for x in (c.start_seconds,c.end_seconds)})
    if any(x.denominator!=1 for x in boundaries):raise _Refusal('UNSUPPORTED_FRACTIONAL_CONTACT_FORCING_CUT')
    retained=sum(len(o.cuts)+len(o.contact_forcing) for o in state.outcomes)
    if retained+len(boundaries)-1>state.inputs.limits.max_retained_cuts or 16*2**20+(retained+len(boundaries)-1)*65536>state.inputs.limits.max_document_bytes:
        raise _Refusal('CAUSAL_RETAINED_BYTES_ADMISSION')
    contacts=[];bindings=[];consumed=state.consumed_contacts
    n=IntegrationPolicy(state.inputs.limits.contact_integration_level).substeps
    for i,(left,right) in enumerate(zip(boundaries,boundaries[1:])):
        forcing,_,camera,panel,supports=_forcing(state,hardware,left,right,state.attitude.quaternion)
        loss=state.inputs.solar_retention_loss_per_second*float(right-left)
        solar=None if loss==0 else SolarDegradationForcingInput(loss)
        tx=CoupledDownlinkInputs(state.inputs.transmitter,forcing.loads,forcing.sunlit,
            forcing.incidence_angle_deg,state.inputs.routing,forcing.thermal_inputs,forcing.external_heat_sources,solar)
        idle=StandbyInputs(forcing.loads,forcing.sunlit,forcing.incidence_angle_deg,forcing.routing_config,
            forcing.thermal_inputs,forcing.external_heat_sources,solar,'Declared essential contact idle; derived incidence.')
        contact=ServiceableGroundContact(GroundContactId('b44.'+action.action_id+'.'+str(i)),entry.point.point_id,
                                        left.numerator,right.numerator)
        ids=tuple(r.record_id for r in candidate.spacecraft_state.data_storage.stored_records)
        # Charged conservative reservation includes accepted-owner predictions/idle.
        _charge(state,'physical_reserved_calls',n*(2*len(ids)+1))
        try:
            executor=execute_contact_plan;keywords={}
            if state.construction is not None:
                from .construction_contact import execute_construction_contact_plan
                executor=execute_construction_contact_plan;keywords.update(compilation=state.construction.compilation,work=state.construction.work,limits=state.construction.inputs.limits)
            result=executor(candidate,ContactPlan(contact,ids,tx,idle),consumed_contacts=consumed,
                policy=state.inputs.protection,integration=IntegrationPolicy(state.inputs.limits.contact_integration_level),**keywords)
        except BaseException:
            if state.construction is not None:
                from .construction_contact import ConstructionContactRefusal
                import sys
                error=sys.exc_info()[1]
                if type(error) is ConstructionContactRefusal:
                    state.runtime_work.physical_completed_calls+=error.returned_physical_calls
                    raise _Refusal('CONSTRUCTION_CONTACT_ELECTRICAL_REFUSED:'+error.reason,
                        diagnostic=('KNOWN_ELECTRICAL_CONTACT_REFUSAL_V1',error.reason,error.offset_bits,error.standby,
                            error.evaluations,error.returned_physical_calls,error.returned_thermal_calls,
                            tuple(contacts),tuple(bindings))) from error
            # No authoritative returned work count exists; neither guess nor refund.
            state.runtime_work.contact_work_unknown_events+=1
            raise
        # Returned authoritative work is spent even if the atomic outer action refuses.
        state.runtime_work.physical_completed_calls+=result.outcome.evaluated_eps_substeps
        if (result.outcome.denied_record_id is not None or result.outcome.accounting.unmet_load_wh>0 or
            candidate.spacecraft_state.onboard.fdir_state is not FDIRState.NORMAL or
            candidate.spacecraft_state.onboard.operational_mode is OperationalMode.SAFE or
            candidate.spacecraft_state.onboard.critical_energy_since_seconds is not None or
            _violations(candidate,state.inputs.protection.standby_node_ids)):
            raise _Refusal('CONTACT_EXISTING_PROTECTION_REFUSED')
        contacts.append(result.outcome);consumed=result.consumed_contacts
        binding=MissionContactForcing(left,right,supports,forcing.incidence_angle_deg,camera,panel,tx,idle,contact.contact_id)
        if state.construction is not None:
            from .construction_contact import ConstructionContactForcing
            binding=ConstructionContactForcing(binding,result.evaluations)
        bindings.append(binding)
    return tuple(contacts),consumed,tuple(bindings)


def _advance_long_mission(state,*,expected_action_id=None):
    """One private action, validated before one outer commit. Refusal never moves context."""
    _type(state,LongMissionState,'mission state')
    from .long_mission_document import mission_input_digest
    if mission_input_digest(state.inputs)!=state.input_digest:raise ValueError('foreign/modified mission inputs')
    validate_context_inputs(state)
    if state.construction is not None:
        from .construction_mission import guard_construction_state
        guard_construction_state(state)
    if state.cursor!=len(state.outcomes) or not 0<=state.cursor<len(state.inputs.actions):raise ValueError('invalid/completed cursor')
    state.runtime_work.validate(state.inputs.limits)
    admit_operational_regime(state.context)
    state.attitude.__post_init__()
    from .orbit_config import _frame
    expected_frame=state.inputs.environment.trajectory.initial_state.position.frame
    if _frame(state.attitude.inertial_frame)!=expected_frame or state.attitude.body_frame_id!=state.inputs.assembly.body_frame_id:
        raise ValueError('foreign attitude/world or assembly body frame')
    initial=state.inputs.initial_checkpoint.restore(state.inputs.simulation_inputs)
    expected_time=initial.simulation_time_seconds if state.cursor==0 else state.outcomes[-1].end_seconds
    expected_steps=initial.diagnostics.completed_steps+sum(o.status=='completed' for o in state.outcomes)
    if state.context.simulation_time_seconds!=expected_time or state.context.diagnostics.completed_steps!=expected_steps or state.attitude.at_seconds!=Q(expected_time):
        raise ValueError('STALE_OR_REPLAYED_ACTION_STATE')
    action=state.inputs.actions[state.cursor]
    if expected_action_id is not None and expected_action_id!=action.action_id:raise ValueError('duplicate/foreign action entry')
    if any(o.action_id==action.action_id for o in state.outcomes):raise ValueError('completed action cannot replay')
    reserve_output(state)
    state.source_authority.guard()
    candidate=checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs))
    _charge(state,'spatial_reserved_units',65536)
    hardware=(state.harness.hardware if state.harness is not None and state.harness.hardware is not None else
        compile_assembly_hardware(state.inputs.assembly,state.inputs.capabilities,state.inputs.actuator))
    a=candidate.simulation_time_seconds;b=a;geometry=();cuts=();accounting=None;record=association=None;contacts=();contact_forcing=();consumed=state.consumed_contacts;slew=None;attitude=state.attitude;continuous=None
    try:
        if action.kind=='POINT':
            geometry=_observations(state,_entry(state,action.point_id),a,a)
            if not geometry[0].visible:raise _Refusal('TARGET_POINTING_GEOMETRY_REFUSED')
            _charge(state,'spatial_reserved_units',65536+2048)
            if state.harness is not None and state.harness.hardware is not None:
                from .harness_slew import plan_effective_slew
                slew=plan_effective_slew(hardware,state.attitude,geometry[0].direction.components,work=state.harness.work,policy=state.harness.inputs.augmentation.policy)
            else:slew=plan_target_slew(hardware,state.attitude,geometry[0].direction.components)
            b=a+slew.duration_seconds
            if b>state.inputs.environment.end_seconds:raise _Refusal('SLEW_EXCEEDS_ENVIRONMENT_DOMAIN')
            if b>a:
                cuts,accounting=_physical_action(state,candidate,hardware,a,b,slew=slew,required=state.inputs.protection.imaging_node_ids)
            attitude=BodyAttitude3D(state.attitude.body_frame_id,state.attitude.inertial_frame,Q(b),
                slew.quaternion_at(Q(slew.duration_seconds)),Q(a+slew.rest_start_offset_seconds))
        elif action.kind=='HOLD_UNTIL':
            b=action.until_seconds
            if b<a:raise _Refusal('HOLD_END_ALREADY_PASSED')
            if b>state.inputs.environment.end_seconds:raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
            if b>a:cuts,accounting=_physical_action(state,candidate,hardware,a,b)
            attitude=replace(attitude,at_seconds=Q(b))
        elif action.kind=='CAPTURE':
            b=a+action.duration_seconds
            if b>state.inputs.environment.end_seconds:raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
            if not _product(state,action.product_id).acquisition_start_seconds<=a<b<=_product(state,action.product_id).acquisition_end_seconds:
                raise _Refusal('ACQUISITION_WINDOW_MISSED')
            continuous=_continuous_admission(state,_entry(state,action.point_id),a,b,hardware,capture=True)
            if continuous is not None and continuous.status!='VISIBLE':raise _Refusal('CONTINUOUS_CAPTURE_'+continuous.status)
            geometry=_observations(state,_entry(state,action.point_id),a,b)
            record,association,payload=_capture_definition(state,candidate,action,hardware,geometry)
            cuts,accounting=_physical_action(state,candidate,hardware,a,b,payload_w=payload,
                                             required=state.inputs.protection.imaging_node_ids)
            candidate.spacecraft_state.data_storage.stored_records+=(record,)
            attitude=replace(attitude,at_seconds=Q(b))
        else:
            b=a+action.duration_seconds
            if b>state.inputs.environment.end_seconds:raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
            continuous=_continuous_admission(state,_entry(state,action.point_id,station=True),a,b,hardware)
            if continuous is not None and continuous.status!='VISIBLE':raise _Refusal('CONTINUOUS_CONTACT_'+continuous.status)
            geometry=_observations(state,_entry(state,action.point_id,station=True),a,b)
            contacts,consumed,contact_forcing=_contact_action(state,candidate,action,hardware,geometry)
            attitude=replace(attitude,at_seconds=Q(b))
        if b>state.inputs.environment.end_seconds:raise _Refusal('ACTION_EXCEEDS_BOUND_ENVIRONMENT')
        candidate.simulation_time_seconds=b
        candidate.diagnostics.completed_steps=state.context.diagnostics.completed_steps+1
        if action.kind!='CONTACT':
            # The private reduced physical action neither owns nor performs recovery.
            admit_operational_regime(candidate)
            candidate.spacecraft_state.onboard.operational_mode={'POINT':OperationalMode.MANEUVER,'CAPTURE':OperationalMode.IMAGING,'HOLD_UNTIL':OperationalMode.STANDBY}[action.kind]
        admit_operational_regime(candidate)
        _validate_completed_context(candidate);checked_checkpoint(candidate)
    except _Refusal as refusal:
        outcome=EnvironmentActionOutcome(action.action_id,action.kind,'refused',str(refusal),a,a,geometry,(),(),None,None,state.attitude,None,slew,continuous_geometry=continuous,failure_diagnostic=refusal.diagnostic)
        result=replace(state,cursor=state.cursor+1,outcomes=(*state.outcomes,outcome))
        _publication_admission(result)
        return result
    # All late primitive errors propagate with original context/cursor intact.
    outcome=EnvironmentActionOutcome(action.action_id,action.kind,'completed',None,a,b,geometry,cuts,contacts,record,association,attitude,accounting,slew,contact_forcing,continuous)
    acquisitions=state.acquisitions if record is None else (*state.acquisitions,MSAcquisitionEvidence(record,association))
    state.source_authority.guard()
    projected=replace(state,context=candidate,attitude=attitude,cursor=state.cursor+1,outcomes=(*state.outcomes,outcome),acquisitions=acquisitions,consumed_contacts=consumed)
    _publication_admission(projected)
    _commit_action(state.context,candidate)
    return replace(state,attitude=attitude,cursor=state.cursor+1,outcomes=(*state.outcomes,outcome),
                   acquisitions=acquisitions,consumed_contacts=consumed)


def advance_long_mission(state,*,expected_action_id=None):
    try:return _advance_long_mission(state,expected_action_id=expected_action_id)
    finally:
        if state.nominal_provider is not None:
            state.runtime_work.nominal_force_completed=state.nominal_prior_completed+state.nominal_provider.work.force_completed
            state.runtime_work.nominal_unknown_events=state.nominal_prior_unknown+state.nominal_provider.work.unknown_primitive_events

def _publication_admission(state):
    """Full causal tree/byte validation before outer context publication.

    Per-cut 64KiB scheduling allowance is prospective; the exact encoder is
    also checked transactionally and never silently drops causal fields.
    """
    from .long_mission_continuation import scientific_bytes
    scientific_bytes(state,reserve=False)


def scientific_projection(state):
    projection=dict(api=state.inputs.api,mode=state.inputs.environment.mode,input_digest=state.input_digest,
        original_world_identity=state.source_authority.identity,nominal_provider_identity=state.nominal_provider.identity,
        original_source_result=state.source_result,checkpoint=checked_checkpoint(state.context).to_dict(),
        attitude=state.attitude,cursor=state.cursor,outcomes=state.outcomes,acquisitions=state.acquisitions,
        consumed_contacts=state.consumed_contacts,assessments=state.assessment(),
        nominal_evidence=dict(identity=state.nominal_provider.identity,method=state.inputs.nominal_policy.method,time_rule='BINARY64_HALF_ULP_ORIGINAL_GRID_REMAINDER_SEPARATE'),
        environment_evidence=dict(identity=state.source_authority.identity,mode=state.inputs.environment.mode,source_signature=state.source_authority.signature,original_anchor=state.inputs.environment.start_seconds,lighting_grid_seconds=state.inputs.environment.lighting_step_seconds))
    if state.construction is not None:
        projection['construction']=dict(api='B45_CONSTRUCTION_MISSION_V1',input_digest=state.construction.input_digest,
            configuration_digest=state.construction.compilation.configuration_digest,
            compilation=state.construction.compilation)
    if state.harness is not None:
        projection['harness']=dict(api=state.harness.inputs.api,mode=state.harness.inputs.mass_mode,input_digest=state.harness.input_digest,
            augmentation_inputs=state.harness.inputs.augmentation,mass_scope=state.harness.mass_scope,effective_hardware=state.harness.hardware)
    return projection


def reserve_output(state,count=1):
    # Prospective schema visits + encoded64-byte blocks at admitted maxima.
    # A reservation is not CPU seconds or a measured number of scalar leaves.
    units=(8*2**20+(state.inputs.limits.max_document_bytes+63)//64)*count
    _charge(state,'output_control_units',units)


def validate_context_inputs(state):
    if canonical_content(state.context.inputs)!=canonical_content(state.inputs.simulation_inputs):
        raise ValueError('MUTATED_CONTEXT_INPUT_AUTHORITY')
