"""B53 strictly declared synthetic long-study inputs and one-time compiler.

This module does not estimate hardware coefficients from observed survival.
All changed plant values are ASSUMED before a run. Existing payload, torque,
transmitter, electrical routing, protection and geometry owners remain active.
Compilation is allowed only at the original empty-custody initial boundary;
it is never an advanced-state migration or a continuation operation.
"""
from dataclasses import dataclass, fields, replace
from hashlib import sha256
from math import isfinite
import json


METHOD = 'B53_COMMON_ASSUMED_LUMPED_LONG_STUDY_V1'
FORMAT = 'B53_LONG_STUDY_INPUT_V1'
PROVENANCE = 'ASSUMED_SYNTHETIC_NOT_FLIGHT_CALIBRATED'
DOMAIN_SECONDS = 15*31557600
ROLES = ('BUS', 'BATTERY', 'PAYLOAD')
NODE_UNITS = (('heat_capacity_j_per_k', 'J/K'), ('radiating_area_m2', 'm^2'),
    ('emissivity', '1'), ('illuminated_solar_w', 'W'),
    ('absorbed_albedo_w', 'W'), ('absorbed_earth_ir_w', 'W'))
SCALAR_UNITS = (('housekeeping_w', 'W'), ('conductance_w_per_k', 'W/K'),
    ('sink_temperature_k', 'K'), ('initial_temperature_k', 'K'),
    ('initial_energy_fraction', '1'), ('initial_battery_retention', '1'),
    ('initial_solar_retention', '1'), ('reference_temperature_k', 'K'),
    ('calendar_damage_per_second', '1/s'), ('cycling_damage_per_normalized_throughput', '1'),
    ('calendar_activation_energy_j_per_mol', 'J/mol'),
    ('cycling_activation_energy_j_per_mol', 'J/mol'),
    ('solar_retention_loss_per_second', '1/s'), ('ageing_multiplier', '1'))


def _number(value, name, lower, upper, *, positive=False):
    if type(value) is not float or not isfinite(value) or not lower <= value <= upper:
        raise ValueError('exact finite long-study binary64 coefficient: '+name)
    if positive and value <= 0:
        raise ValueError('strictly positive long-study coefficient: '+name)
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True, slots=True)
class StudyThermalNode:
    role: str
    heat_capacity_j_per_k: float
    radiating_area_m2: float
    emissivity: float
    illuminated_solar_w: float
    absorbed_albedo_w: float
    absorbed_earth_ir_w: float

    def __post_init__(self):
        if type(self.role) is not str or self.role not in ROLES:
            raise ValueError('declared long-study thermal role required')
        _number(self.heat_capacity_j_per_k, 'heat capacity', 1., 1e9)
        _number(self.radiating_area_m2, 'radiating area', 1e-6, 100.)
        _number(self.emissivity, 'emissivity', 0., 1., positive=True)
        for name in ('illuminated_solar_w', 'absorbed_albedo_w', 'absorbed_earth_ir_w'):
            _number(getattr(self, name), name, 0., 1e5)


@dataclass(frozen=True, slots=True)
class LifecycleStudyInput:
    nodes: tuple = (
        StudyThermalNode('BUS', 20000., .04, .8, 2., .5, 2.),
        StudyThermalNode('BATTERY', 10000., .02, .8, 1., .2, .6),
        StudyThermalNode('PAYLOAD', 8000., .04, .8, 2., .3, 1.))
    housekeeping_w: float = 4.
    conductance_w_per_k: float = .4
    sink_temperature_k: float = 270.
    initial_temperature_k: float = 300.
    initial_energy_fraction: float = .8
    initial_battery_retention: float = 1.
    initial_solar_retention: float = 1.
    reference_temperature_k: float = 298.15
    calendar_damage_per_second: float = 1e-10
    cycling_damage_per_normalized_throughput: float = 1e-5
    calendar_activation_energy_j_per_mol: float = 20000.
    cycling_activation_energy_j_per_mol: float = 20000.
    solar_retention_loss_per_second: float = 1e-10
    ageing_multiplier: float = 1.
    latency_seconds: int = 1
    maximum_duration_seconds: int = DOMAIN_SECONDS
    provenance: str = PROVENANCE
    method: str = METHOD

    def __post_init__(self):
        if type(self.nodes) is not tuple or len(self.nodes) != 3:
            raise ValueError('exactly three declared thermal study roles required')
        if any(type(n) is not StudyThermalNode for n in self.nodes):
            raise TypeError('exact immutable study thermal nodes required')
        if tuple(n.role for n in self.nodes) != ROLES:
            raise ValueError('ordered disjoint BUS/BATTERY/PAYLOAD study roles required')
        for n in self.nodes:
            n.__post_init__()
        for name in ('housekeeping_w', 'conductance_w_per_k'):
            _number(getattr(self, name), name, 1e-12, 1e5)
        for name in ('sink_temperature_k', 'initial_temperature_k', 'reference_temperature_k'):
            _number(getattr(self, name), name, 100., 500.)
        for name in ('initial_energy_fraction', 'initial_battery_retention', 'initial_solar_retention'):
            _number(getattr(self, name), name, 0., 1., positive=True)
        for name in ('calendar_damage_per_second', 'solar_retention_loss_per_second'):
            _number(getattr(self, name), name, 1e-16, 1e-5)
        _number(self.cycling_damage_per_normalized_throughput, 'cycling damage', 1e-16, .1)
        _number(self.ageing_multiplier, 'predeclared rate sensitivity multiplier', .125, 8.)
        for name in ('calendar_activation_energy_j_per_mol', 'cycling_activation_energy_j_per_mol'):
            _number(getattr(self, name), name, 0., 1e5)
        if type(self.latency_seconds) is not int or not 0 <= self.latency_seconds <= 120:
            raise ValueError('exact declared study latency seconds required')
        if type(self.maximum_duration_seconds) is not int or not 1 <= self.maximum_duration_seconds <= DOMAIN_SECONDS:
            raise ValueError('finite long-study seconds domain required')
        if type(self.provenance) is not str or self.provenance != PROVENANCE or type(self.method) is not str or self.method != METHOD:
            raise ValueError('explicit ASSUMED study identity required')

    @property
    def content_digest(self):
        return sha256(canonical(study_to_data(self)).encode('utf-8')).hexdigest()


def common_study_input():
    return LifecycleStudyInput()


def study_to_data(study):
    if type(study) is not LifecycleStudyInput:
        raise TypeError('exact long-study input required')
    study.__post_init__()
    return dict(format=FORMAT, method=study.method, provenance=study.provenance,
        maximum_duration_seconds=study.maximum_duration_seconds, latency_seconds=study.latency_seconds,
        scalars={name:dict(value_hex=getattr(study,name).hex(), units=unit)
                 for name,unit in SCALAR_UNITS},
        nodes=[dict(role=n.role, parameters={name:dict(value_hex=getattr(n,name).hex(),units=unit)
                 for name,unit in NODE_UNITS}) for n in study.nodes])


def study_from_data(data):
    keys={'format','method','provenance','maximum_duration_seconds','latency_seconds','scalars','nodes'}
    if type(data) is not dict or set(data) != keys or data['format'] != FORMAT:
        raise ValueError('exact long-study document fields required')
    def parameters(raw, units):
        if type(raw) is not dict or set(raw) != {name for name,_ in units}:
            raise ValueError('exact long-study parameter fields required')
        out={}
        for name,unit in units:
            item=raw[name]
            if type(item) is not dict or set(item)!={'value_hex','units'} or type(item['units']) is not str or item['units']!=unit or type(item['value_hex']) is not str:
                raise ValueError('exact long-study units/value representation required: '+name)
            if len(item['value_hex'])>64:
                raise ValueError('bounded long-study binary64 coefficient representation required')
            try:
                value=float.fromhex(item['value_hex'])
            except (OverflowError,ValueError) as error:
                raise ValueError('finite canonical long-study binary64 coefficient required') from error
            if not isfinite(value) or value.hex()!=item['value_hex']:
                raise ValueError('canonical finite binary64 long-study coefficient required')
            out[name]=value
        return out
    if type(data['nodes']) is not list or len(data['nodes'])!=3:
        raise ValueError('bounded exact long-study node records required')
    nodes=[]
    for item in data['nodes']:
        if type(item) is not dict or set(item)!={'role','parameters'}:
            raise ValueError('exact long-study node document required')
        nodes.append(StudyThermalNode(item['role'],**parameters(item['parameters'],NODE_UNITS)))
    result=LifecycleStudyInput(nodes=tuple(nodes),**parameters(data['scalars'],SCALAR_UNITS),
        maximum_duration_seconds=data['maximum_duration_seconds'],latency_seconds=data['latency_seconds'],
        method=data['method'],provenance=data['provenance'])
    if study_to_data(result)!=data:
        raise ValueError('noncanonical long-study document')
    return result


def _parameter(old, value, rationale, *, sensitivity=None):
    from .provenance import ProvenanceClass, ProvenanceStatus
    # The accepted B48 input-only codec admits ParameterProvenance but not the
    # optional SensitivityRange record. Keep that boundary unchanged. B53's
    # strict study declaration owns the multiplier domain; preserve these
    # derived absolute limits as exact hex metadata in the parent's units.
    if sensitivity is not None:
        lower,upper=sensitivity
        if not lower<=value<=upper:
            raise ValueError('study parameter outside declared sensitivity domain')
        rationale+=' Declared sensitivity domain ['+lower.hex()+','+upper.hex()+'] '+old.units+'; B53 study multiplier domain [0.125,8].'
    provenance=replace(old.provenance, classification=ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
        status=ProvenanceStatus.TO_VERIFY,source_ids=(),rationale=rationale,derivation=None,
        sensitivity_range=None)
    return replace(old,value=value,provenance=provenance)


def _roles(network):
    roles=dict(zip(ROLES,(network.bus_node_id,network.battery_node_id,network.payload_node_id)))
    if len(set(roles.values()))!=3 or set(roles.values())!={n.node_id for n in network.nodes}:
        raise ValueError('study compiler requires exactly the three distinct declared thermal roles')
    return roles


def compile_study_base(base, study):
    """Compile a new ORIGINAL input once; no dynamics, campaigns or retagging.

    Geometry, products, service assumptions, flight loads, routing, protection,
    inertia and battery/array allocations are inherited. Thermal parameters and
    ageing assumptions are deliberately different input authorities. The input
    remains the short-domain base used by the lifecycle long-world compiler.
    """
    from .command_estimation import CommandRollingRoot
    from .checkpoint import CheckpointState
    from .environment_forcing import _case
    from .construction_coupling import digest
    if type(base) is not CommandRollingRoot or type(study) is not LifecycleStudyInput:
        raise TypeError('exact original command base and long-study input required')
    study.__post_init__()
    cp=base.initial_checkpoint
    original=base.model.environment.start_seconds
    if (type(cp) is not CheckpointState or cp.simulation_time_seconds!=original or
            cp.spacecraft.data_storage.stored_records or cp.ground_data_delivery.partial_transfers or
            cp.ground_data_delivery.completed_deliveries or cp.diagnostics.completed_steps):
        raise ValueError('STUDY_COMPILER_ORIGINAL_EMPTY_INITIAL_BOUNDARY_ONLY')
    model=base.model;cfg=model.simulation_inputs.spacecraft_configuration
    roles=_roles(cfg.thermal.network);by_id={roles[n.role]:n for n in study.nodes}
    rationale=('ASSUMED B53 predeclared common synthetic lumped study '+study.content_digest+
        '; no flight calibration, measured-survival fit, continuous safety or hardware-winner claim.')
    nodes=[]
    for node in cfg.thermal.network.nodes:
        inputs=by_id[node.node_id]
        nodes.append(replace(node,**{name:_parameter(getattr(node,name),getattr(inputs,name),rationale)
            for name in ('heat_capacity_j_per_k','radiating_area_m2','emissivity')}))
        if not node.operating_min_temperature_k.value <= study.initial_temperature_k <= node.operating_max_temperature_k.value:
            raise ValueError('declared study initial temperature outside inherited operating domain')
    links=tuple(replace(link,conductance_w_per_k=_parameter(link.conductance_w_per_k,
        study.conductance_w_per_k,rationale)) for link in cfg.thermal.network.links)
    network=replace(cfg.thermal.network,nodes=tuple(nodes),links=links)
    age=cfg.degradation.battery_ageing_model;m=study.ageing_multiplier
    ageing=replace(age,
        reference_temperature_k=_parameter(age.reference_temperature_k,study.reference_temperature_k,rationale),
        calendar_damage_rate_per_second_at_reference=_parameter(age.calendar_damage_rate_per_second_at_reference,
            study.calendar_damage_per_second*m,rationale,sensitivity=(study.calendar_damage_per_second*.125,study.calendar_damage_per_second*8.)),
        cycling_damage_per_normalized_energy_throughput_at_reference=_parameter(age.cycling_damage_per_normalized_energy_throughput_at_reference,
            study.cycling_damage_per_normalized_throughput*m,rationale,sensitivity=(study.cycling_damage_per_normalized_throughput*.125,study.cycling_damage_per_normalized_throughput*8.)),
        calendar_activation_energy_j_per_mol=_parameter(age.calendar_activation_energy_j_per_mol,study.calendar_activation_energy_j_per_mol,rationale),
        cycling_activation_energy_j_per_mol=_parameter(age.cycling_activation_energy_j_per_mol,study.cycling_activation_energy_j_per_mol,rationale))
    degradation=replace(cfg.degradation,battery_ageing_model=ageing,
        initial_battery_usable_capacity_retention=_parameter(cfg.degradation.initial_battery_usable_capacity_retention,study.initial_battery_retention,rationale),
        initial_solar_generation_retention=_parameter(cfg.degradation.initial_solar_generation_retention,study.initial_solar_retention,rationale),
        initial_battery_energy_throughput_wh=_parameter(cfg.degradation.initial_battery_energy_throughput_wh,0.,rationale))
    configuration=replace(cfg,thermal=replace(cfg.thermal,network=network),degradation=degradation)
    simulation=replace(model.simulation_inputs,spacecraft_configuration=configuration)
    profile=[]
    for entry in model.environment.profile:
        forcing=tuple(replace(n,sink_temperature_k=study.sink_temperature_k,internal_dissipation_w=0.,
            illuminated_solar_w=by_id[n.node_id].illuminated_solar_w,
            absorbed_albedo_w=by_id[n.node_id].absorbed_albedo_w,
            absorbed_earth_ir_w=by_id[n.node_id].absorbed_earth_ir_w,sink_includes=()) for n in entry.nodes)
        profile.append(replace(entry,loads=replace(entry.loads,base_bus_w=study.housekeeping_w),nodes=forcing,
            non_overlap_assumption=rationale+' Prescribed external solar/albedo/IR heat excludes routed loads and EPS/wire losses; sink_includes=(). Electrical PV generation is separate, not a thermal closure proof.',
            internal_includes_eps_losses=False))
    environment=replace(model.environment,profile=tuple(profile))
    boundaries=_case(profile[0],False).thermal_inputs
    construction=replace(model.configuration,thermal_network=network,thermal_boundaries=boundaries,
        rationale=rationale+' Existing assembly, harness mass, conductors, routes and load branches unchanged.')
    augmentation=replace(model.augmentation,construction_digest=digest(construction))
    newmodel=replace(model,simulation_inputs=simulation,environment=environment,configuration=construction,
        augmentation=augmentation,solar_retention_loss_per_second=study.solar_retention_loss_per_second*m)
    battery=replace(cp.spacecraft.degradation.battery,usable_capacity_retention=study.initial_battery_retention,
        cumulative_energy_throughput_wh=0.)
    solar=replace(cp.spacecraft.degradation.solar,generation_retention=study.initial_solar_retention)
    thermal=replace(cp.spacecraft.thermal,node_states=tuple(replace(n,temperature_k=study.initial_temperature_k)
        for n in cp.spacecraft.thermal.node_states))
    energy=configuration.eps.battery.nominal_energy_wh.value*study.initial_battery_retention*study.initial_energy_fraction
    initial=replace(cp,spacecraft=replace(cp.spacecraft,battery_energy_wh=energy,thermal=thermal,
        degradation=replace(cp.spacecraft.degradation,battery=battery,solar=solar)))
    resource=replace(base.initial_estimate.resources,battery_energy_wh=energy,battery_retention=study.initial_battery_retention,
        solar_retention=study.initial_solar_retention,throughput_wh=0.,observed_temperatures=thermal.node_states)
    estimate=replace(base.initial_estimate,resources=resource)
    reference=replace(base.reference,model=newmodel,initial_checkpoint=initial,initial_estimate=estimate)
    result=replace(base,reference=reference)
    validate_study_base(result,study)
    return result


def validate_study_base(base, study):
    """Read-only bounded coefficient binding; never invokes the compiler/solver."""
    if type(study) is not LifecycleStudyInput:
        raise TypeError('exact long-study input required')
    study.__post_init__()
    model=base.model;cfg=model.simulation_inputs.spacecraft_configuration;roles=_roles(cfg.thermal.network)
    by_id={roles[n.role]:n for n in study.nodes};cp=base.initial_checkpoint
    for node in cfg.thermal.network.nodes:
        for name in ('heat_capacity_j_per_k','radiating_area_m2','emissivity'):
            if getattr(node,name).value!=getattr(by_id[node.node_id],name):
                raise ValueError('long-study node coefficient/base binding')
    if any(link.conductance_w_per_k.value!=study.conductance_w_per_k for link in cfg.thermal.network.links):
        raise ValueError('long-study conductive coupling/base binding')
    age=cfg.degradation.battery_ageing_model;m=study.ageing_multiplier
    expected=(('reference_temperature_k',study.reference_temperature_k),
        ('calendar_damage_rate_per_second_at_reference',study.calendar_damage_per_second*m),
        ('cycling_damage_per_normalized_energy_throughput_at_reference',study.cycling_damage_per_normalized_throughput*m),
        ('calendar_activation_energy_j_per_mol',study.calendar_activation_energy_j_per_mol),
        ('cycling_activation_energy_j_per_mol',study.cycling_activation_energy_j_per_mol))
    if any(getattr(age,n).value!=value for n,value in expected) or model.solar_retention_loss_per_second!=study.solar_retention_loss_per_second*m:
        raise ValueError('long-study ageing/base binding')
    for entry in model.environment.profile:
        if entry.loads.base_bus_w!=study.housekeeping_w or entry.internal_includes_eps_losses:
            raise ValueError('long-study housekeeping/base binding')
        for n in entry.nodes:
            inputs=by_id[n.node_id]
            if (n.sink_temperature_k!=study.sink_temperature_k or n.internal_dissipation_w!=0. or n.sink_includes or
                any(getattr(n,name)!=getattr(inputs,name) for name in ('illuminated_solar_w','absorbed_albedo_w','absorbed_earth_ir_w'))):
                raise ValueError('long-study external heat/base binding')
    expected_energy=cfg.eps.battery.nominal_energy_wh.value*study.initial_battery_retention*study.initial_energy_fraction
    if (cp.simulation_time_seconds!=model.environment.start_seconds or cp.spacecraft.battery_energy_wh!=expected_energy or
            cp.spacecraft.degradation.battery.usable_capacity_retention!=study.initial_battery_retention or
            cp.spacecraft.degradation.solar.generation_retention!=study.initial_solar_retention or
            cp.spacecraft.degradation.battery.cumulative_energy_throughput_wh!=0. or
            any(n.temperature_k!=study.initial_temperature_k for n in cp.spacecraft.thermal.node_states)):
        raise ValueError('long-study declared original initial state/base binding')
    return study.content_digest


def study_provenance(study):
    """Portable units/domain/ownership, including deliberately unclosed routes."""
    study.__post_init__()
    return dict(method=METHOD,input_digest=study.content_digest,classification='ASSUMED',
        domain=dict(relative_start_seconds=0,maximum_duration_seconds=study.maximum_duration_seconds,
            thermal_model='three lumped role nodes; prescribed environment; inherited operating/protection bounds',
            accuracy='nominal reduced model; no continuous, ephemeris or physical calibration certificate'),
        parameters=study_to_data(study),
        derivations=dict(thermal='C_i*dT_i/dt=Q_routed_i+Q_prescribed_i+sum_j G_ij*(T_j-T_i)-epsilon_i*sigma*A_i*(T_i^4-T_sink_i^4)',
            calendar='damage=rate_per_second*temperature_acceleration*duration_seconds',
            cycling='damage=damage_per_normalized_throughput*temperature_acceleration*(throughput_Wh/nameplate_Wh)',
            solar='existing owner applies one per-selected-interval retention factor from loss_per_second*dt; no second application',
            initial_energy='energy_Wh=nameplate_Wh*initial_capacity_retention*initial_energy_fraction'),
        limiting_cases=dict(calendar_reference_30days=study.calendar_damage_per_second*study.ageing_multiplier*2592000.,
            cycling_one_nameplate_throughput=study.cycling_damage_per_normalized_throughput*study.ageing_multiplier,
            solar_first_order_30days=study.solar_retention_loss_per_second*study.ageing_multiplier*2592000.),
        inherited_owners=('actual payload acquisition power','actual transmitter power','paid moving-attitude torque/power',
            'declared branch wires/routing and EPS losses','protection/capability thresholds','actual geometry and service declarations'),
        exclusions=('Prescribed solar/albedo/IR are not additionally derived from PV incidence or absorbed area.',
            'Effective sink is an independent ASSUMED boundary; sink_includes is empty.',
            'No battery resistance/voltage model, flight heat budget, guaranteed survival or hardware ranking.'),
        sensitivity='Freeze multiplier0.5 or2 as a distinct root before run; positive calendar/cycling/solar rates remain enabled.')
