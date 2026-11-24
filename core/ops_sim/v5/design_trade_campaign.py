"""Immutable, opt-in Task05E inputs; archived V7 programs are not reinterpreted.

The EPS scalar-incidence interface carries delivered array power through an
explicit equivalent-angle adapter. Actual wing normals/incidence and the
external string/regulator losses are separate diagnostic authorities.
"""

from dataclasses import asdict, dataclass, fields, replace
from math import acos, cos, degrees, isfinite, radians, sin

from . import ids
from .adcs import CommonFrameBoresightDirection
from .campaign_contract import ReleasedMSRequest
from .checkpoint import CheckpointState
from .communications import ServiceableGroundContact
from .comparison_campaign import build_inputs_program as reference_program, parameter
from .design_trade_design import DesignAssumptions, derive_design, design_record, solar_input, load_input
from .experiment_codec import canonical_content, content_digest
from .ms_acquisition import InitialAttitudeEvidence
from .observation import ObservationPointing
from .power_loads import PowerLoadBreakdown
from .thermal import ThermalIntervalInputs, ThermalNodeBoundaryInput


@dataclass(frozen=True, slots=True)
class TradeSpec:
    design_id: str
    workload: str
    variant: str
    level: int
    assumptions: DesignAssumptions = DesignAssumptions()
    version: int = 1
    torque_nm: float = .02
    momentum_nms: float = .2
    rate_deg_s: float = 2.
    rotor_inertia_kg_m2: float = .00034
    settle_seconds: int = 5
    motor_w: float = 25.
    hold_w: float = .5
    sun_angle_deg: float = 20.
    eclipse_end_seconds: int = 30
    horizon: int = 1600
    initial_fraction: float = .25
    mode_factor: float = 1.
    max_interval_seconds: int = 5
    core_specific_heat_j_kg_k: float = 900.
    payload_specific_heat_j_kg_k: float = 700.
    battery_specific_heat_j_kg_k: float = 900.
    sink_temperature_k: float = 280.
    exposure_seconds: int = 60
    first_window_seconds: int = 60
    window_seconds: int = 70
    close_cadence_seconds: int = 130
    relaxed_cadence_seconds: int = 200
    pointing_amplitude_deg: float = 30.
    contact_start_seconds: int = 1450
    contact_end_seconds: int = 1490
    delivery_deadline_seconds: int = 1550
    max_advances: int = 16

    def __post_init__(self):
        if type(self.design_id) is not str or self.design_id not in {
                f'B{b}-A{a}' for b in (2,4,6,8) for a in (2,4,6)}:
            raise ValueError('unknown bounded component allocation')
        if type(self.workload) is not str or self.workload not in ('relaxed','close'):
            raise ValueError('unknown common workload')
        if type(self.variant) is not str or self.variant not in ('FULL','RESOURCE_ONLY'):
            raise ValueError('unknown declared physical variant')
        if type(self.level) is not int or self.level not in (1,2):
            raise ValueError('study admits levels one and two')
        if type(self.assumptions) is not DesignAssumptions:
            raise TypeError('exact immutable design assumptions required')
        self.assumptions.__post_init__()
        if type(self.version) is not int or self.version != 1:
            raise ValueError('unsupported new-study contract version')
        integer_names = ('settle_seconds','eclipse_end_seconds','horizon','max_interval_seconds',
            'exposure_seconds','first_window_seconds','window_seconds','close_cadence_seconds',
            'relaxed_cadence_seconds','contact_start_seconds','contact_end_seconds','delivery_deadline_seconds','max_advances')
        for n in integer_names:
            if type(getattr(self,n)) is not int or getattr(self,n) <= 0:
                raise ValueError(n+' must be a positive exact integer')
        for f in fields(self):
            if f.name in ('design_id','workload','variant','level','assumptions','version',*integer_names):
                continue
            v=getattr(self,f.name)
            if type(v) is not float or not isfinite(v) or v <= 0:
                raise ValueError(f.name+' must be a positive finite built-in float')
        if not 0 < self.initial_fraction <= 1 or not .5 <= self.mode_factor <= 1.5:
            raise ValueError('initial reserve or mode-power sensitivity outside study')
        if self.pointing_amplitude_deg > 45 or self.sun_angle_deg > 90:
            raise ValueError('outside reduced viewing/illumination domain')
        if not self.eclipse_end_seconds < self.first_window_seconds:
            raise ValueError('all held acquisitions must be after prescribed eclipse')
        if self.window_seconds < self.exposure_seconds:
            raise ValueError('window cannot fit acquisition')
        if not (self.first_window_seconds+5*self.relaxed_cadence_seconds+self.window_seconds
                < self.contact_start_seconds < self.contact_end_seconds
                <= self.delivery_deadline_seconds < self.horizon):
            raise ValueError('workload/contact/horizon partition is inconsistent')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
            raise ValueError('exact new-study fields required')
        v=dict(value);a=v['assumptions']
        if type(a) is not dict or set(a)!={f.name for f in fields(DesignAssumptions)}:
            raise ValueError('exact design-assumption fields required')
        a=dict(a)
        for n in ('core_size_m','wire_areas_mm2'):
            if type(a[n]) not in (tuple,list): raise TypeError('invalid assumption sequence')
            a[n]=tuple(a[n])
        v['assumptions']=DesignAssumptions(**a)
        return cls(**v)

    def inertia(self, design):
        if self.variant=='FULL': return design.inertia_y_kg_m2
        a=self.assumptions
        return a.core_mass_kg*(a.core_size_m[0]**2+a.core_size_m[2]**2)/12*a.core_inertia_scale


def direction(angle_rad):
    return CommonFrameBoresightDirection(ids.ADCSBoresightFrameId('task05e-prescribed-inertial'),
                                        sin(angle_rad),0.,cos(angle_rad))


def build_program(spec):
    if type(spec) is not TradeSpec: raise TypeError('exact TradeSpec required')
    spec.__post_init__()
    design=derive_design(int(spec.design_id[1]),int(spec.design_id[-1]),spec.assumptions)
    if not design.accepted: raise ValueError('infeasible full design: '+','.join(design.rejection_reasons))
    old,base=reference_program('J-E1',level=spec.level,mode_factor=1.)
    identity=content_digest('task05e-spec-v1',spec.to_dict())[:20]
    p=lambda old,v,derived=False:parameter(old.parameter_id.value,old.units,float(v),
        derivation='Task05E explicit component allocation and declared assumptions; full source/consumer ledger' if derived else None,
        rationale='Task05E assumption or allocation derivation; see V5_DESIGN_TRADE_SOURCES.md and bound TradeSpec')
    cfg=old.spacecraft_configuration
    a=spec.assumptions
    battery=replace(cfg.eps.battery,nominal_energy_wh=p(cfg.eps.battery.nominal_energy_wh,design.capacity_wh,True),
        charge_efficiency=p(cfg.eps.battery.charge_efficiency,a.charge_efficiency),
        discharge_efficiency=p(cfg.eps.battery.discharge_efficiency,a.discharge_efficiency),
        max_charge_input_power_w=p(cfg.eps.battery.max_charge_input_power_w,design.charge_bus_w,True),
        max_discharge_output_power_w=p(cfg.eps.battery.max_discharge_output_power_w,design.discharge_bus_w,True))
    array=replace(cfg.eps.solar_array,nominal_generation_w=p(cfg.eps.solar_array.nominal_generation_w,45*design.arrays,True))
    nodes=[]
    for n in cfg.thermal.network.nodes:
        name=n.node_id.value
        mass=(design.total_mass_kg-design.arrays*.650-design.packs*.486-46. if name=='bus'
              else design.packs*.486 if name=='battery' else 46.)
        cp=(spec.core_specific_heat_j_kg_k if name=='bus' else spec.battery_specific_heat_j_kg_k
            if name=='battery' else spec.payload_specific_heat_j_kg_k)
        area=.02*design.packs if name=='battery' else .4 if name=='bus' else .2
        nodes.append(replace(n,heat_capacity_j_per_k=p(n.heat_capacity_j_per_k,mass*cp,True),
            emissivity=p(n.emissivity,.2),radiating_area_m2=p(n.radiating_area_m2,area)))
    cfg=replace(cfg,configuration_id=ids.SpacecraftConfigurationId('task05e-'+identity),
        label='Task05E '+spec.design_id,eps=replace(cfg.eps,battery=battery,solar_array=array),
        payload=replace(cfg.payload,optical_acquisition=replace(cfg.payload.optical_acquisition,
            acquisition_power_w=p(cfg.payload.optical_acquisition.acquisition_power_w,93*spec.mode_factor))),
        thermal=replace(cfg.thermal,network=replace(cfg.thermal.network,nodes=tuple(nodes))))
    world=replace(old.common_world,world_id=ids.WorldId('task05e-world-'+spec.workload),
        scenario_id=ids.ScenarioId('task05e-'+spec.workload),horizon_seconds=spec.horizon)
    env=replace(old.environment_config,environment_id=ids.EnvironmentId('task05e-fixed-sun-eclipse'))
    model=replace(old.model_manifest,manifest_id=ids.ModelManifestId('task05e-'+identity),
        spacecraft_configuration_id=cfg.configuration_id,world_id=world.world_id,scenario_id=world.scenario_id,
        environment_id=env.environment_id,controller_id=ids.ControllerId('task05e-received-earliest-deadline-v1'))
    inputs=replace(old,spacecraft_configuration=cfg,common_world=world,environment_config=env,
        scenario_config=replace(old.scenario_config,scenario_id=world.scenario_id),model_manifest=model)
    context=base.initial_checkpoint.restore(old)
    context=replace(context,inputs=inputs,
        controller_state=replace(context.controller_state,controller_id=model.controller_id))
    context.spacecraft_state.battery.energy_wh=design.capacity_wh*spec.initial_fraction
    context.controller_state=replace(context.controller_state,controller_id=model.controller_id)
    requests=[];opportunities=[]
    cadence=spec.close_cadence_seconds if spec.workload=='close' else spec.relaxed_cadence_seconds
    for i,(r,o) in enumerate(zip(base.requests,base.opportunities)):
        start=spec.first_window_seconds+i*cadence;angle=radians(spec.pointing_amplitude_deg*(1 if i%2==0 else -1))
        request=replace(r.product.request,request_id=ids.ImagingRequestId(f'task05e-r{i}'),target_id=ids.GroundTargetId(f'task05e-target{i}'))
        footprint=replace(r.product.footprint,region_id=f'task05e-region{i}')
        product=replace(r.product,request=request,capture_group=f'task05e-capture{i}',footprint=footprint,
            acquisition_start_seconds=start,acquisition_end_seconds=start+spec.window_seconds,
            delivery_deadline_seconds=spec.delivery_deadline_seconds)
        opportunity=replace(o.opportunity,opportunity_id=ids.ObservationOpportunityId(f'task05e-op{i}'),request_id=request.request_id,
            window_start_seconds=start,window_end_seconds=start+spec.window_seconds,
            imaging_duration_seconds=spec.exposure_seconds,
            pointing=ObservationPointing(spec.pointing_amplitude_deg,0. if i%2==0 else 180.))
        candidate=replace(o.candidate,maneuver_candidate=replace(o.candidate.maneuver_candidate,
            opportunity=opportunity,common_frame_boresight=direction(angle)),
            acquisition_input=replace(o.candidate.acquisition_input,imaging_duration_seconds=spec.exposure_seconds))
        acquisition=replace(o.acquisition,request=request,capture_group=product.capture_group,
            sizing=replace(o.acquisition.sizing,footprint=footprint))
        requests.append(ReleasedMSRequest(product,0));opportunities.append(replace(o,candidate=candidate,acquisition=acquisition))
    contact=ServiceableGroundContact(ids.GroundContactId('task05e-declared-contact'),ids.GroundStationId('task05e-synthetic-station'),
        spec.contact_start_seconds,spec.contact_end_seconds)
    wait=replace(base.forcing[0].standby,thermal_inputs=ThermalIntervalInputs(tuple(
        ThermalNodeBoundaryInput(n.node_id,spec.sink_temperature_k) for n in nodes)),
        rationale='Task05E boundary template; actual incidence and wiring recomputed from held or executed attitude')
    template=replace(base.forcing[0],start_seconds=0,end_seconds=spec.horizon,standby=wait,
        transmitter=replace(base.forcing[0].transmitter,electrical_power_w=p(
            base.forcing[0].transmitter.electrical_power_w,93*spec.mode_factor)))
    program=replace(base,initial_checkpoint=CheckpointState.from_context(context),
        initial_attitude=InitialAttitudeEvidence(0,direction(0.),'Explicit settled zero-angle initial attitude; subsequent turns are paid'),
        requests=tuple(requests),opportunities=tuple(opportunities),contacts=(contact,),forcing=(template,),
        assumptions=('Separate Task05E wrapper owns explicit attitude and physically executed motion; embedded V7 types retain old semantics.',
            'Reference MS sampling/footprint approximation held fixed at different pointings; no radiometric or full optical-geometry validation.',
            'Arrays rigid/locked to body, prescribed inertial Sun and target/station directions; no free tracking, RF or orbit qualification.',
            'Thermal capacities derived from declared masses/specific heats; boundary, emissivity, areas and material values are assumptions.',
            'Solar wire/converter dissipation exported outside the three-node network; load-wire and actuator heat routed to bus exactly once.',
            'All six requests received at origin, same earliest-window policy; no scoring truth used for decisions.'))
    return inputs,program,design


def forcing_at(spec, program, design, time_seconds, angle_rad, phase='hold', load_kind='standby'):
    if phase not in ('motion','settle','hold') or load_kind not in ('standby','imaging','contact'):
        raise ValueError('unknown physical load phase')
    sunlit=time_seconds>=spec.eclipse_end_seconds
    incidence=max(0.,cos(angle_rad-radians(spec.sun_angle_deg))) if sunlit else 0.
    solar=solar_input(design,incidence,ideal_wiring=spec.variant=='RESOURCE_ONLY')
    effective=degrees(acos(min(1.,max(0.,solar.delivered_bus_w/(45*design.arrays)))))
    actuator=spec.motor_w if phase in ('motion','settle') else spec.hold_w
    mission=93*spec.mode_factor if load_kind!='standby' else 0.
    terminal=12.+actuator+mission
    wire=load_input(design,terminal)
    load_loss=wire.loss_w if spec.variant=='FULL' else 0.
    wait=replace(program.forcing[0].standby,loads=PowerLoadBreakdown(12.+load_loss,0.,actuator,0.,0.,0.,0.),
        sunlit=bool(sunlit),incidence_angle_deg=effective,
        rationale='Task05E equivalent EPS delivery angle; geometric incidence and source-side losses separately recorded')
    diagnostics=dict(geometric_incidence=incidence,wing_normal_x=sin(angle_rad),wing_normal_z=cos(angle_rad),
        solar_source_w=solar.nominal_power_w,solar_bus_w=solar.delivered_bus_w,
        solar_wire_loss_w=solar.harness_heat_w,solar_converter_loss_w=solar.converter_heat_w,
        load_wire_loss_w=load_loss,load_current_a=terminal/design.assumptions.load_bus_v if spec.variant=='RESOURCE_ONLY' else wire.current_a,
        load_voltage_drop_v=0. if spec.variant=='RESOURCE_ONLY' else wire.voltage_drop_v,
        actuator_electrical_w=actuator,terminal_load_w=terminal,
        body_inertia_kg_m2=spec.inertia(design),rotor_inertia_kg_m2=spec.rotor_inertia_kg_m2)
    return wait,diagnostics


def input_digest(spec):
    inputs,program,design=build_program(spec)
    return content_digest('task05e-coupled-input-v1',
        dict(spec=spec.to_dict(),design=design_record(design),inputs=canonical_content(inputs),program=canonical_content(program)))
