"""Additive full-spatial mission coordinator, same accepted physical transactions.

No numerical owner or legacy wire identity changes. Arbitrary rational physical
cuts use the shared completion owner. Constant integral contact cells delegate
to the accepted multi-record custody/protection executor; unsupported cuts refuse.
"""
from dataclasses import dataclass, replace
from fractions import Fraction as Q
from math import ceil, degrees, fsum, isfinite
from hashlib import sha256

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
class MissionAction:
    action_id: str
    kind: str
    point_id: str = ''
    duration_seconds: int = 0
    until_seconds: int = 0

    def __post_init__(self):
        _text(self.action_id,'action ID',256)
        AcquisitionDataRecordId(self.action_id)
        if type(self.kind) is not str or self.kind not in ('POINT','CAPTURE','HOLD_UNTIL','CONTACT'):
            raise ValueError('unsupported mission action')
        _integer(self.duration_seconds,'action duration');_integer(self.until_seconds,'absolute end')
        if self.duration_seconds>120 or self.until_seconds>2**40:raise ValueError('action bound exceeded')
        if self.kind in ('POINT','CAPTURE','CONTACT'):_text(self.point_id,'catalog point',256)
        if self.kind in ('CAPTURE','CONTACT') and self.duration_seconds<=0:raise ValueError('positive action duration required')
        if self.kind=='POINT' and (self.duration_seconds or self.until_seconds):raise ValueError('point duration must be derived')
        if self.kind=='HOLD_UNTIL' and (self.point_id or self.duration_seconds):raise ValueError('hold requires only its exact end')


@dataclass(frozen=True,slots=True)
class MissionLimits:
    max_actions: int = 16
    max_physical_substeps: int = 4096
    max_runtime_upstream_entries: int = 32
    max_nominal_orbit_queries: int = 4096
    max_point_geometry_queries: int = 4096
    max_interval_seconds: int = 1
    max_action_cells: int = 512
    contact_integration_level: int = 2
    max_document_bytes: int = 16*2**20
    max_geometry_queries: int = 64
    max_geometry_operations: int = 2**22
    max_geometry_control_units: int = 2**22
    max_spatial_reserved_units: int = 2**20

    def __post_init__(self):
        bounds=dict(max_actions=16,max_physical_substeps=65536,max_runtime_upstream_entries=64,
            max_nominal_orbit_queries=16384,max_point_geometry_queries=16384,max_interval_seconds=120,
            max_action_cells=1024,contact_integration_level=6,max_document_bytes=32*2**20,max_geometry_queries=64,max_geometry_operations=2**22,max_geometry_control_units=2**22,max_spatial_reserved_units=2**20)
        for n,m in bounds.items():
            _integer(getattr(self,n),n)
            if not (0 if n=='contact_integration_level' else 1)<=getattr(self,n)<=m:
                raise ValueError('mission limit exceeded: '+n)


@dataclass(frozen=True,slots=True)
class EnvironmentMissionInputs3D:
    simulation_inputs: SimulationInputs
    initial_checkpoint: CheckpointState
    environment: EnvironmentForcingRequest
    assembly: AssemblyDesign
    capabilities: tuple[ComponentAxisBinding,...]
    actuator: ActuatorPolicy
    catalog: tuple[CatalogPoint,...]
    sampling: SamplingPolicy
    actions: tuple[MissionAction,...]
    product: MSProductSpec
    protection: ProtectionPolicy
    routing: ComponentHeatRoutingConfig
    transmitter: DownlinkTransmitterConfig
    initial_quaternion: tuple[float,float,float,float]
    camera_half_fov_rad: float
    solar_retention_loss_per_second: float
    limits: MissionLimits = MissionLimits()
    heat_contract: str = HEAT_CONTRACT
    refusal_policy: str = 'SKIP_GEOMETRY_REFUSE_PHYSICAL_ATOMIC_V1'
    geometry_mode: str = CONTINUOUS_MODE
    geometry_policy: ContinuousGeometryPolicy = ContinuousGeometryPolicy()

    def __post_init__(self):
        _type(self.simulation_inputs,SimulationInputs,'simulation inputs')
        _type(self.initial_checkpoint,CheckpointState,'initial checkpoint')
        _type(self.environment,EnvironmentForcingRequest,'environment')
        _type(self.limits,MissionLimits,'limits');self.limits.__post_init__()
        _type(self.sampling,SamplingPolicy,'sampling');self.sampling.__post_init__()
        _type(self.actions,tuple,'program')
        if not 1<=len(self.actions)<=self.limits.max_actions:raise ValueError('program exceeds action limit')
        for a in self.actions:_type(a,MissionAction,'action');a.__post_init__()
        if len({a.action_id for a in self.actions})!=len(self.actions):raise ValueError('duplicate action ID')
        _type(self.catalog,tuple,'catalog')
        if not 1<=len(self.catalog)<=self.sampling.maximum_points:raise ValueError('catalog bound exceeded')
        for p in self.catalog:_type(p,CatalogPoint,'catalog');p.__post_init__()
        ids=[p.point.point_id.value for p in self.catalog]
        if len(set(ids))!=len(ids):raise ValueError('ambiguous/duplicate catalog IDs')
        for a in self.actions:
            if a.kind!='HOLD_UNTIL' and a.point_id not in ids:raise ValueError('foreign action point')
        _type(self.product,MSProductSpec,'product');self.product.__post_init__()
        ctx=self.initial_checkpoint.restore(self.simulation_inputs)
        validate_policy(self.protection,ctx)
        admit_operational_regime(ctx)
        _type(self.routing,ComponentHeatRoutingConfig,'routing');self.routing.__post_init__()
        _type(self.transmitter,DownlinkTransmitterConfig,'transmitter');self.transmitter.__post_init__()
        origin=Q(self.environment.source_request.segment.trajectory.initial_state.position.instant.elapsed_seconds)
        source_end=Q(self.environment.source_request.segment.end.elapsed_seconds)
        if source_end-origin>120:
            raise ValueError('full upstream source span exceeds120seconds')
        if Q(ctx.simulation_time_seconds)!=origin or self.environment.start_seconds!=origin:
            raise ValueError('context and original environment anchor differ')
        if self.environment.end_seconds-origin>120 or self.environment.end_seconds.denominator!=1:
            raise ValueError('short integral outer environment domain required')
        if self.environment.end_seconds>ctx.inputs.common_world.horizon_seconds or ctx.inputs.common_world.event_ids:
            raise ValueError('explicit bounded event-free common world required')
        if ctx.spacecraft_state.data_storage.stored_records or ctx.ground_data_delivery_state.partial_transfers or ctx.ground_data_delivery_state.completed_deliveries:
            raise ValueError('program begins with empty custody; initial state is not a past acquisition')
        point_map={p.point.point_id.value:p for p in self.catalog}
        if self.product.request.target_id.value not in point_map or type(point_map[self.product.request.target_id.value].point.point_id) is not GroundTargetId:
            raise ValueError('foreign product target role/ID')
        for action in self.actions:
            if action.kind in ('POINT','CAPTURE','CONTACT'):
                expected_role=GroundStationId if action.kind=='CONTACT' else GroundTargetId
                if type(point_map[action.point_id].point.point_id) is not expected_role:
                    raise ValueError('foreign action catalog role')
            if action.kind=='CAPTURE' and action.point_id!=self.product.request.target_id.value:
                raise ValueError('capture target differs from bound product target')
        # CommonWorld owns identity/horizon/events; this new immutable program
        # owns its sole request. No imaginary world request registry.
        if self.simulation_inputs.coast_orbit is not None:
            raise ValueError('B40 orbit authority belongs only to the original environment input')
        if any(n.internal_dissipation_w!=0 for e in self.environment.profile for n in e.nodes):
            raise ValueError('mission internal heat belongs only to served electrical routing')
        _type(self.heat_contract,str,'heat contract');_type(self.refusal_policy,str,'refusal policy')
        if self.heat_contract!=HEAT_CONTRACT or self.refusal_policy!='SKIP_GEOMETRY_REFUSE_PHYSICAL_ATOMIC_V1':
            raise ValueError('unsupported heat/refusal contract')
        object.__setattr__(self,'initial_quaternion',canonical_quaternion(self.initial_quaternion))
        _number(self.camera_half_fov_rad,'camera FOV',positive=True)
        if self.camera_half_fov_rad>1.5707963267948966:raise ValueError('FOV exceeds forward hemisphere')
        _number(self.solar_retention_loss_per_second,'solar loss per second')
        if self.solar_retention_loss_per_second*120>=1:raise ValueError('solar loss outside short contract')
        from .thermal_routing import ElectricalLoadComponent
        route=next(r for r in self.routing.routes if r.component is ElectricalLoadComponent.ADCS)
        if route.thermal_node_id!=ctx.inputs.spacecraft_configuration.thermal.network.bus_node_id or route.retained_heat_fraction.value!=1:
            raise ValueError('ideal net-torque heat requires all ADCS input routed to the bus before mechanical storage adjustment')
        if any(e.loads.payload_w or e.loads.communications_w or e.loads.propulsion_w for e in self.environment.profile):
            raise ValueError('baseline mission forcing must declare acquisition/transmitter/propulsion off')
        if type(self.geometry_mode) is not str or self.geometry_mode not in (CONTINUOUS_MODE,GENERAL_MODE):
            raise ValueError('unsupported mission geometry mode')
        if self.geometry_mode==SAMPLED_MODE:
            if self.geometry_policy is not None:raise ValueError('sampled mode cannot claim continuous policy')
        else:
            domain_admission=admit_general_geometry_domain if self.geometry_mode==GENERAL_MODE else admit_geometry_domain
            for entry in self.catalog:domain_admission(self.environment,entry,self.geometry_policy)
            for n,cap in (('maximum_queries',self.limits.max_geometry_queries),('maximum_operations',self.limits.max_geometry_operations),('maximum_control_units',self.limits.max_geometry_control_units)):
                if getattr(self.geometry_policy,n)>cap:raise ValueError('geometry policy exceeds mission cumulative limit')
        compile_assembly_hardware(self.assembly,self.capabilities,self.actuator)


@dataclass(slots=True)
class RuntimeWork:
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
        for name,cap in (('upstream_entries',limits.max_runtime_upstream_entries),
            ('nominal_orbit_queries',limits.max_nominal_orbit_queries),
            ('point_geometry_queries',limits.max_point_geometry_queries),
            ('physical_reserved_calls',limits.max_physical_substeps),
            ('geometry_queries',limits.max_geometry_queries),('geometry_operations',limits.max_geometry_operations),
            ('geometry_control_units',limits.max_geometry_control_units),('spatial_reserved_units',limits.max_spatial_reserved_units)):
            if getattr(self,name)>cap:raise ValueError('invalid cumulative runtime work')
        if (self.physical_completed_calls>self.physical_reserved_calls or self.reconstruction_count>self.upstream_entries or
            self.contact_work_unknown_events+self.physical_work_unknown_events>self.physical_reserved_calls):
            raise ValueError('inconsistent cumulative runtime work')

    def charge(self,name,count,limits):
        self.validate(limits)
        _integer(count,'runtime charge')
        cap={'upstream_entries':limits.max_runtime_upstream_entries,
             'nominal_orbit_queries':limits.max_nominal_orbit_queries,
             'point_geometry_queries':limits.max_point_geometry_queries,
             'physical_reserved_calls':limits.max_physical_substeps,'geometry_queries':limits.max_geometry_queries,
             'geometry_operations':limits.max_geometry_operations,'geometry_control_units':limits.max_geometry_control_units,'spatial_reserved_units':limits.max_spatial_reserved_units}[name]
        if getattr(self,name)+count>cap:raise ValueError('CUMULATIVE_RUNTIME_QUOTA_EXHAUSTED:'+name)
        setattr(self,name,getattr(self,name)+count)


@dataclass(frozen=True,slots=True)
class MissionActionForcing:
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


@dataclass(slots=True)
class EnvironmentMissionState3D:
    inputs: EnvironmentMissionInputs3D
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

    def assessment(self):
        return assess_ms_product(self.inputs.product,self.acquisitions,self.context.ground_data_delivery_state,
            tuple(c for o in self.outcomes for c in o.contact_outcomes),self.context.simulation_time_seconds)


def start_environment_mission(inputs,*,runtime_work=None):
    _type(inputs,EnvironmentMissionInputs3D,'mission inputs');inputs.__post_init__()
    from .environment_mission_3d_document import mission_input_digest
    work=RuntimeWork() if runtime_work is None else runtime_work
    _type(work,RuntimeWork,'runtime work');work.validate(inputs.limits)
    q=inputs.environment.source_request
    if q.policy.max_initial_steps+q.policy.max_refinement_steps>256:raise ValueError('short upstream step bound exceeded')
    work.charge('upstream_entries',1,inputs.limits)
    source=light.evaluate_zonotope_local_illumination_v2(q)
    if not source.coverage_complete:raise ValueError('UPSTREAM_NO_COMPLETE_COVERAGE:'+str(source.reason))
    adapt_environment_forcing(source,inputs.environment)
    ctx=inputs.initial_checkpoint.restore(canonical_copy(inputs.simulation_inputs))
    work.charge('spatial_reserved_units',65536,inputs.limits)
    hardware=compile_assembly_hardware(inputs.assembly,inputs.capabilities,inputs.actuator)
    attitude=BodyAttitude3D(hardware.design.body_frame_id,q.segment.trajectory.initial_state.position.frame,
        Q(ctx.simulation_time_seconds),inputs.initial_quaternion,Q(ctx.simulation_time_seconds))
    return EnvironmentMissionState3D(inputs,ctx,attitude,0,(),(),ConsumedContacts(()),work,source,mission_input_digest(inputs),
        _bind_acquired_source(source,inputs.environment) if inputs.geometry_mode in (CONTINUOUS_MODE,GENERAL_MODE) else None)

class _Refusal(ValueError):
    pass


def _charge(state,name,count):state.runtime_work.charge(name,count,state.inputs.limits)


def _entry(state,identifier,station=False):
    matches=[p for p in state.inputs.catalog if p.point.point_id.value==identifier]
    if len(matches)!=1 or type(matches[0].point.point_id) is not (GroundStationId if station else GroundTargetId):
        raise ValueError('foreign catalog role/ID')
    return matches[0]


def _observations(state,entry,a,b):
    return sample_interval(state.inputs.environment.source_request,entry,Q(a),Q(b),state.inputs.sampling,
        charge=lambda n,c:_charge(state,n,c))


def _continuous_admission(state,entry,a,b,hardware,*,capture=False):
    if state.inputs.geometry_mode not in (CONTINUOUS_MODE,GENERAL_MODE):return None
    p=state.inputs.geometry_policy
    if state.source_authority is None or state.source_authority.source is not state.source_result:
        raise ValueError('foreign acquired geometry authority')
    def pay(name,count):
        cap={'geometry_queries':p.maximum_queries,'geometry_operations':p.maximum_operations,
             'geometry_control_units':p.maximum_control_units}[name]
        if getattr(state.runtime_work,name)+count>cap:raise ValueError('CUMULATIVE_GEOMETRY_QUOTA_EXHAUSTED:'+name)
        _charge(state,name,count)
    evaluate=evaluate_general_geometry if state.inputs.geometry_mode==GENERAL_MODE else evaluate_continuous_geometry
    return evaluate(state.source_authority,state.inputs.environment,entry,Q(a),Q(b),p,
        held_camera=exact_held_camera(state.attitude,hardware.camera_body_axis,p,charge=pay) if capture else None,
        half_fov_rad=state.inputs.camera_half_fov_rad if capture else None,
charge=pay)


def _orientation_inputs(state,hardware,time,quaternion,loads=None):
    _charge(state,'spatial_reserved_units',128)
    q=state.inputs.environment.source_request;instant=GeometryInstant(q.segment.end.epoch,float(time))
    _charge(state,'nominal_orbit_queries',1)
    orbit=evaluate_j2_cartesian_state(q.segment.trajectory,instant,
        J2RK4SolverConfig(state.inputs.sampling.nominal_step_seconds,state.inputs.sampling.nominal_max_steps))
    sun=evaluate_sun_position(q.table,instant)
    direction=vector(tuple(a-b for a,b in zip(sun.components_m,orbit.position.components_m)))
    attitude=BodyAttitude3D(hardware.design.body_frame_id,orbit.position.frame,Q(time),quaternion,Q(time))
    camera=attitude.direction(hardware.camera_body_axis);panel=attitude.direction(hardware.panel_body_normal)
    incidence=degrees(angle_between(panel,direction))
    return incidence,camera,panel


def _schedule(state,a,b):
    request=replace(state.inputs.environment,start_seconds=Q(a),end_seconds=Q(b))
    return adapt_environment_forcing(state.source_result,request)


def _forcing(state,hardware,a,b,quaternion,*,adcs_w=0.,payload_w=0.):
    schedule=_schedule(state,a,b)
    if any(c.assessment=='UNRESOLVED' and c.end_seconds>c.start_seconds for c in schedule.cells):
        raise _Refusal('UNRESOLVED_ILLUMINATION')
    midpoint=(Q(a)+Q(b))/2
    incidence,camera,panel=_orientation_inputs(state,hardware,midpoint,quaternion)
    index=schedule.cells[0].profile_index;base=state.inputs.environment.profile[index]
    loads=replace(base.loads,adcs_w=base.loads.adcs_w+adcs_w,payload_w=base.loads.payload_w+payload_w)
    profile=tuple(replace(e,incidence_angle_deg=incidence,loads=replace(e.loads,
        adcs_w=e.loads.adcs_w+adcs_w,payload_w=e.loads.payload_w+payload_w)) for e in state.inputs.environment.profile)
    derived=replace(state.inputs.environment,start_seconds=Q(a),end_seconds=Q(b),profile=profile)
    s=adapt_environment_forcing(state.source_result,derived)
    cases=[c.alternatives[0] for c in s.cells]
    # Each physical caller split at every source/profile cut before reaching here.
    if any(c!=cases[0] for c in cases[1:]):raise ValueError('physical substep crosses forcing discontinuity')
    case=cases[0]
    forcing=MissionActionForcing(case.eps_inputs.load_breakdown,case.sunlit,incidence,state.inputs.routing,
        case.thermal_inputs,case.heat_source_inputs)
    return forcing,case.eps_inputs,camera,panel,tuple(c.support_index for c in s.cells)


def _partition(state,a,b,extra=()):
    schedule=_schedule(state,a,b)
    if any(c.assessment=='UNRESOLVED' and c.end_seconds>c.start_seconds for c in schedule.cells):
        raise _Refusal('UNRESOLVED_ILLUMINATION')
    points={Q(a),Q(b)}|{x for c in schedule.cells for x in (c.start_seconds,c.end_seconds)}
    points|={Q(a)+x for x in extra if Q(0)<x<Q(b)-Q(a)}
    ordered=sorted(points);cuts=[]
    for x,y in zip(ordered,ordered[1:]):
        n=ceil((y-x)/state.inputs.limits.max_interval_seconds)
        cuts.extend((x+(y-x)*Q(i,n),x+(y-x)*Q(i+1,n)) for i in range(n))
    if len(cuts)>state.inputs.limits.max_action_cells:raise _Refusal('ACTION_PARTITION_LIMIT')
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
            part,eps=_physical_substep(candidate,duration,forcing,eps_inputs,state.inputs.protection,solar,
                standby=False,internal_heat_adjustments_w=None if slew is None else
                ((candidate.inputs.spacecraft_configuration.thermal.network.bus_node_id,adjustment),))
        except BaseException:
            state.runtime_work.physical_work_unknown_events+=1
            raise
        state.runtime_work.physical_completed_calls+=1
        if part is None:raise _Refusal('FULL_ELECTRICAL_SERVICE_UNAVAILABLE')
        cuts.append(MissionPhysicalCut(left,right,supports,forcing.incidence_angle_deg,camera,panel,float(k0),float(k1),draw,adjustment,part,quaternion,
            None if slew is None else slew.euler_at(mid-Q(a)),k0,k1));parts.append(part)
        if _violations(candidate,required):raise _Refusal('OPERATING_TEMPERATURE_AT_ENDPOINT')
    return tuple(cuts),_aggregate(tuple(parts))


def _capture_definition(state,candidate,action,hardware,observations):
    start=candidate.simulation_time_seconds;end=start+action.duration_seconds
    product=state.inputs.product
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
    opportunity=ObservationOpportunity(ObservationOpportunityId('b42.'+action.action_id),product.request.request_id,
        start,end,action.duration_seconds,ObservationPointing(degrees(entry.off_nadir_rad),degrees(azimuth)%360))
    boresight=CommonFrameBoresightDirection(ADCSBoresightFrameId('b42-full-spatial-model-inertial-bound-in-packet'),*camera)
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
    image=ImagingAction(action.action_id,execution,AcquisitionDataRecordId('b42.'+action.action_id),
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
        state.inputs.geometry_mode==SAMPLED_MODE and any(not o.serviceable_nominal for o in observations)):
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
        contact=ServiceableGroundContact(GroundContactId('b42.'+action.action_id+'.'+str(i)),entry.point.point_id,
                                        left.numerator,right.numerator)
        ids=tuple(r.record_id for r in candidate.spacecraft_state.data_storage.stored_records)
        # Charged conservative reservation includes accepted-owner predictions/idle.
        _charge(state,'physical_reserved_calls',n*(2*len(ids)+1))
        try:
            result=execute_contact_plan(candidate,ContactPlan(contact,ids,tx,idle),consumed_contacts=consumed,
                policy=state.inputs.protection,integration=IntegrationPolicy(state.inputs.limits.contact_integration_level))
        except BaseException:
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
        bindings.append(MissionContactForcing(left,right,supports,forcing.incidence_angle_deg,camera,panel,tx,idle,contact.contact_id))
    return tuple(contacts),consumed,tuple(bindings)


def advance_environment_mission(state,*,expected_action_id=None):
    """One private action, validated before one outer commit. Refusal never moves context."""
    _type(state,EnvironmentMissionState3D,'mission state')
    from .environment_mission_3d_document import mission_input_digest
    if mission_input_digest(state.inputs)!=state.input_digest:raise ValueError('foreign/modified mission inputs')
    if state.cursor!=len(state.outcomes) or not 0<=state.cursor<len(state.inputs.actions):raise ValueError('invalid/completed cursor')
    state.runtime_work.validate(state.inputs.limits)
    admit_operational_regime(state.context)
    state.attitude.__post_init__()
    from .orbit_config import _frame
    expected_frame=state.inputs.environment.source_request.segment.trajectory.initial_state.position.frame
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
    candidate=checked_checkpoint(state.context).restore(canonical_copy(state.context.inputs))
    _charge(state,'spatial_reserved_units',65536)
    hardware=compile_assembly_hardware(state.inputs.assembly,state.inputs.capabilities,state.inputs.actuator)
    a=candidate.simulation_time_seconds;b=a;geometry=();cuts=();accounting=None;record=association=None;contacts=();contact_forcing=();consumed=state.consumed_contacts;slew=None;attitude=state.attitude;continuous=None
    try:
        if action.kind=='POINT':
            geometry=_observations(state,_entry(state,action.point_id),a,a)
            if not geometry[0].visible:raise _Refusal('TARGET_POINTING_GEOMETRY_REFUSED')
            _charge(state,'spatial_reserved_units',65536+2048)
            slew=plan_target_slew(hardware,state.attitude,geometry[0].direction.components)
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
            if not state.inputs.product.acquisition_start_seconds<=a<b<=state.inputs.product.acquisition_end_seconds:
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
        outcome=EnvironmentActionOutcome(action.action_id,action.kind,'refused',str(refusal),a,a,geometry,(),(),None,None,state.attitude,None,slew,continuous_geometry=continuous)
        return replace(state,cursor=state.cursor+1,outcomes=(*state.outcomes,outcome))
    # All late primitive errors propagate with original context/cursor intact.
    outcome=EnvironmentActionOutcome(action.action_id,action.kind,'completed',None,a,b,geometry,cuts,contacts,record,association,attitude,accounting,slew,contact_forcing,continuous)
    acquisitions=state.acquisitions if record is None else (*state.acquisitions,MSAcquisitionEvidence(record,association))
    _commit_action(state.context,candidate)
    return replace(state,attitude=attitude,cursor=state.cursor+1,outcomes=(*state.outcomes,outcome),
                   acquisitions=acquisitions,consumed_contacts=consumed)


def scientific_projection(state):
    """Declared before comparisons: everything causal, runtime work separately."""
    return dict(input_digest=state.input_digest,original_source_result=state.source_result,checkpoint=checked_checkpoint(state.context).to_dict(),
        attitude=state.attitude,cursor=state.cursor,outcomes=state.outcomes,acquisitions=state.acquisitions,
        consumed_contacts=state.consumed_contacts,assessment=state.assessment())
