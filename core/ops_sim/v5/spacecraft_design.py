"""B66 supported assembly-to-plant admission, not a catalogue or CAD compiler.

DESIGNS owns specification authoring/search. This owner derives the supported
parallel-bank/collinear-PV/lumped-thermal plant and independently admits its
compiled root. No dynamic state, successful service, or flight data is inferred.
"""
from dataclasses import dataclass, replace, fields
from math import fsum, isfinite

from .assembly import _identity
from .assembly_choices import AssemblyDesign, assess_design
from .assembly_document import assembly_document_digest
from .assembly_attitude import ComponentAxisBinding, vector
from .assembly_attitude_3d import NetTorqueActuatorPolicy, rotate
from .battery_port import BatteryPortPolicy
from .construction_coupling import ConstructionConfiguration, compile_construction
from .harness_mass import HarnessAugmentationInputs, geometry_digest
from .harness_hardware import compile_effective_hardware
from .lifecycle_contract import LifecycleRoot
from .design_repair import ConstructorLedger
from .rolling_physics import digest
from .configuration import PayloadConfig, PayloadMode
from .coupled_downlink import DownlinkTransmitterConfig
from .thermal_routing import ComponentHeatRoutingConfig, ElectricalLoadComponent
from .power_loads import PowerLoadBreakdown
from .ids import SourceRecordId

METHOD = 'B66_DECLARED_ASSEMBLY_PLANT_V1'
PARALLEL = 'IDENTICAL_PARALLEL_MODULES_COMMON_SOC_TEMPERATURE_IDEAL_INTERNAL_BUS_V1'
PV_MODEL = 'COORIENTED_PARALLEL_RATED_PV_IDEAL_INTERNAL_BUS_V1'


def number(value, name, lo=0., hi=1e12):
    if type(value) is not float or not isfinite(value) or not lo <= value <= hi:
        raise ValueError('B66 finite binary64 ' + name)
    return value


def records(value, owner, key, *, minimum=1, maximum=32):
    if type(value) is not tuple or not minimum <= len(value) <= maximum:
        raise ValueError('B66 bounded declared ' + owner.__name__)
    for item in value:
        if type(item) is not owner:
            raise TypeError('B66 exact ' + owner.__name__)
        item.__post_init__()
    if len({getattr(v, key) for v in value}) != len(value):
        raise ValueError('B66 duplicate physical declaration')
    return tuple(sorted(value, key=lambda v: getattr(v, key)))


@dataclass(frozen=True, slots=True)
class DesignProvenance:
    classification: str
    source_ids: tuple
    rationale: str

    def __post_init__(self):
        if type(self.classification) is not str or self.classification not in ('SOURCE', 'DERIVED', 'ASSUMED'):
            raise ValueError('explicit SOURCE/DERIVED/ASSUMED')
        if type(self.source_ids) is not tuple or len(self.source_ids) > 32:
            raise ValueError('bounded source IDs')
        for value in self.source_ids:
            _identity(value, 'source ID')
            SourceRecordId(value)
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError('duplicate source ID')
        if self.classification == 'SOURCE' and not self.source_ids:
            raise ValueError('SOURCE requires declared traceable source IDs')
        _identity(self.rationale, 'physical assumption/derivation')


@dataclass(frozen=True, slots=True)
class BatteryModule:
    instance_id: str
    nominal_energy_wh: float
    maximum_charge_bus_w: float
    maximum_discharge_bus_w: float
    port_policy: BatteryPortPolicy | None
    provenance: DesignProvenance

    def __post_init__(self):
        _identity(self.instance_id, 'battery physical instance')
        for name in ('nominal_energy_wh', 'maximum_charge_bus_w', 'maximum_discharge_bus_w'):
            number(getattr(self, name), name, 1e-12, 1e9)
        if self.port_policy is not None:
            if type(self.port_policy) is not BatteryPortPolicy:
                raise TypeError('exact per-module port policy')
            self.port_policy.__post_init__()
        if type(self.provenance) is not DesignProvenance:
            raise TypeError('explicit battery provenance')
        self.provenance.__post_init__()


@dataclass(frozen=True, slots=True)
class PVModule:
    instance_id: str
    normal_local: tuple
    active_area_m2: float
    reference_irradiance_w_m2: float
    conversion_efficiency: float
    provenance: DesignProvenance

    def __post_init__(self):
        _identity(self.instance_id, 'PV physical instance')
        # Optical direction is declared separately from the mass cuboid axes.
        # Existing starters already use non-cardinal local mount directions.
        if (type(self.normal_local) is not tuple or len(self.normal_local) != 3 or
                any(type(x) is not float for x in self.normal_local) or
                any(not isfinite(x) for x in self.normal_local)):
            raise ValueError('PV requires an explicit finite local normal')
        object.__setattr__(self, 'normal_local', vector(self.normal_local))
        number(self.active_area_m2, 'active PV m2', 1e-12, 1e6)
        number(self.reference_irradiance_w_m2, 'rating irradiance W/m2', 1e-12, 1e6)
        number(self.conversion_efficiency, 'PV efficiency', 1e-12, 1.)
        if type(self.provenance) is not DesignProvenance:
            raise TypeError('explicit PV provenance')
        self.provenance.__post_init__()


@dataclass(frozen=True, slots=True)
class ThermalPart:
    instance_id: str
    node_id: str
    specific_heat_j_per_kg_k: float
    radiating_area_m2: float
    emissivity: float
    provenance: DesignProvenance

    def __post_init__(self):
        _identity(self.instance_id, 'thermal physical instance')
        _identity(self.node_id, 'lumped node')
        number(self.specific_heat_j_per_kg_k, 'specific heat J/(kg K)', 1e-12, 1e8)
        number(self.radiating_area_m2, 'radiating m2', 0., 1e6)
        number(self.emissivity, 'emissivity', 0., 1.)
        if type(self.provenance) is not DesignProvenance:
            raise TypeError('explicit thermal provenance')
        self.provenance.__post_init__()


@dataclass(frozen=True, slots=True)
class FunctionalPlant:
    """Declared supported optical/RF/load functions, separate from mass shapes.

    Aggregate demand is an explicit authored equipment-group property. It is
    not inferred from display names or cuboid volume. Moving ADCS still uses
    the separately declared actuator and freshly derived full inertia tensor.
    """
    payload_configuration: PayloadConfig
    transmitter: DownlinkTransmitterConfig
    routing: ComponentHeatRoutingConfig
    baseline_loads: PowerLoadBreakdown
    camera_half_fov_rad: float
    provenance: DesignProvenance

    def __post_init__(self):
        for name, owner in (('payload_configuration', PayloadConfig),
                ('transmitter', DownlinkTransmitterConfig), ('routing', ComponentHeatRoutingConfig),
                ('baseline_loads', PowerLoadBreakdown), ('provenance', DesignProvenance)):
            value = getattr(self, name)
            if type(value) is not owner:
                raise TypeError('exact declared functional ' + owner.__name__)
            value.__post_init__()
        number(self.camera_half_fov_rad, 'camera half FOV rad', 1e-12, 1.5707963267948965)
        if PayloadMode.MULTISPECTRAL not in self.payload_configuration.supported_modes:
            raise ValueError('this lifecycle consumer requires explicitly supported multispectral acquisition')
        if self.baseline_loads.payload_w or self.baseline_loads.communications_w or self.baseline_loads.propulsion_w:
            raise ValueError('dynamic acquisition/RF/propulsion cannot be double-counted as baseline load')


@dataclass(frozen=True, slots=True)
class DesignSpecification:
    assembly: AssemblyDesign
    configuration: ConstructionConfiguration
    augmentation: HarnessAugmentationInputs
    capabilities: tuple
    actuator: NetTorqueActuatorPolicy
    batteries: tuple
    pv_modules: tuple
    thermal_parts: tuple
    initial_usable_energy_fraction: float
    initial_temperatures_k: tuple
    provenance: DesignProvenance
    functional: FunctionalPlant
    battery_connection: str = PARALLEL
    pv_connection: str = PV_MODEL
    method: str = METHOD

    def __post_init__(self):
        for name, owner in (('assembly', AssemblyDesign), ('configuration', ConstructionConfiguration),
                            ('augmentation', HarnessAugmentationInputs), ('actuator', NetTorqueActuatorPolicy),
                            ('provenance', DesignProvenance), ('functional', FunctionalPlant)):
            value = getattr(self, name)
            if type(value) is not owner:
                raise TypeError('B66 exact ' + owner.__name__)
            value.__post_init__()
        if len(self.assembly.instances) > 32:
            raise ValueError('M4 32-entry spatial domain')
        if type(self.capabilities) is not tuple or len(self.capabilities) != 2:
            raise ValueError('one camera and one effective panel axis')
        for value in self.capabilities:
            if type(value) is not ComponentAxisBinding:
                raise TypeError('exact component axis')
            value.__post_init__()
        for name, owner in (('batteries', BatteryModule), ('pv_modules', PVModule), ('thermal_parts', ThermalPart)):
            object.__setattr__(self, name, records(getattr(self, name), owner, 'instance_id'))
        number(self.initial_usable_energy_fraction, 'initial usable energy fraction', 0., 1.)
        if type(self.initial_temperatures_k) is not tuple or not 1 <= len(self.initial_temperatures_k) <= 64:
            raise ValueError('complete declared initial temperatures')
        names = set()
        for pair in self.initial_temperatures_k:
            if type(pair) is not tuple or len(pair) != 2:
                raise TypeError('node/temperature pair')
            _identity(pair[0], 'initial thermal node')
            number(pair[1], 'initial K', 1., 1000.)
            if pair[0] in names:
                raise ValueError('duplicate initial temperature')
            names.add(pair[0])
        object.__setattr__(self, 'initial_temperatures_k', tuple(sorted(self.initial_temperatures_k)))
        if (type(self.method) is not str or self.method != METHOD or
                type(self.battery_connection) is not str or self.battery_connection != PARALLEL or
                type(self.pv_connection) is not str or self.pv_connection != PV_MODEL):
            raise ValueError('unsupported bank/circuit/model; no implicit equivalent')
        ids = {i.instance_id for i in self.assembly.instances}
        batteries = {b.instance_id for b in self.batteries}
        panels = {p.instance_id for p in self.pv_modules}
        if not batteries <= ids or not panels <= ids or batteries & panels:
            raise ValueError('functional physical ownership must be disjoint and assembled')
        camera = next((c.component_id for c in self.capabilities if c.role == 'camera'), None)
        panel = next((c.component_id for c in self.capabilities if c.role == 'panel'), None)
        ports = {p.port_id: p for p in self.configuration.ports}
        lines = {l.line_id: l for l in self.configuration.lines}
        payload_line = next(b.line_id for b in self.configuration.receiving if b.component is ElectricalLoadComponent.PAYLOAD)
        if camera in batteries | panels or ports[lines[payload_line].load_port_id].instance_id != camera:
            raise ValueError('camera functional axis and actual payload branch must have one declared physical owner')
        if panel not in panels or ports[lines[self.configuration.pv_line_id].source_port_id].instance_id not in panels:
            raise ValueError('effective panel axis and aggregate PV branch require declared PV bank owners')
        if {p.instance_id for p in self.thermal_parts} != ids:
            raise ValueError('each physical instance requires exactly one declared thermal part')
        nodes = {n.node_id.value for n in self.configuration.thermal_network.nodes}
        if any(r.thermal_node_id.value not in nodes for r in self.functional.routing.routes):
            raise ValueError('functional heat route requires an existing declared thermal node')
        adcs_route = next(r for r in self.functional.routing.routes if r.component is ElectricalLoadComponent.ADCS)
        if (adcs_route.thermal_node_id != self.configuration.thermal_network.bus_node_id or
                adcs_route.retained_heat_fraction.value != 1.):
            raise ValueError('paid ADCS storage adjustment requires full bus heat route')
        if {p.node_id for p in self.thermal_parts} != nodes or names != nodes:
            raise ValueError('complete thermal capacity/radiator/initial-state declarations')
        by_instance = {p.instance_id: p.node_id for p in self.thermal_parts}
        if any(by_instance[b.instance_id] != b.node_id for b in self.configuration.thermal_bindings):
            raise ValueError('functional and M4 instance thermal bindings disagree')
        battery_node = self.configuration.thermal_network.battery_node_id.value
        if any(by_instance[b.instance_id] != battery_node for b in self.batteries):
            raise ValueError('common-temperature battery bank requires one battery node')

    @property
    def identity(self):
        from .spacecraft_project_v2_document import specification_data
        from .lifecycle_contract import canonical
        from hashlib import sha256
        return sha256(canonical(specification_data(self)).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DesignAdmission:
    root: LifecycleRoot
    construction: object
    hardware: object
    specification_identity: str
    common_identity: str
    derived: tuple
    method: str = METHOD


def _derived(parameter, value, explanation, provenances=()):
    from .provenance import ProvenanceClass, ProvenanceStatus
    sources = tuple(SourceRecordId(n) for n in sorted({n for p in provenances for n in p.source_ids}))
    classes = ','.join(sorted({p.classification for p in provenances}))
    return replace(parameter, value=value, provenance=replace(parameter.provenance,
        classification=ProvenanceClass.DERIVED_VALUE, status=ProvenanceStatus.TO_VERIFY,
        rationale='B66 declared supported design composition; not flight calibration.',
        source_ids=sources, derivation=explanation+'; declared input classes='+classes, sensitivity_range=None))


def _bank(spec, common):
    first = spec.batteries[0]
    # Equal electrical modules maintain common SOC under equal parallel current.
    # Different structural definitions/masses/poses remain fully supported.
    for b in spec.batteries[1:]:
        if any(getattr(b, n) != getattr(first, n) for n in
               ('nominal_energy_wh', 'maximum_charge_bus_w', 'maximum_discharge_bus_w', 'port_policy')):
            raise ValueError('HETEROGENEOUS_PARALLEL_BATTERY_DYNAMICS_UNSUPPORTED')
    count = len(spec.batteries)
    port = first.port_policy
    if (port is None) != (common.battery_port_policy is None):
        raise ValueError('explicit legacy Wh versus Rint bank family; no silent upgrade')
    if port is not None:
        port = replace(port, resistance_reference_ohm=port.resistance_reference_ohm/count,
            maximum_charge_current_a=port.maximum_charge_current_a*count,
            maximum_discharge_current_a=port.maximum_discharge_current_a*count,
            maximum_charge_bus_w=port.maximum_charge_bus_w*count,
            maximum_discharge_bus_w=port.maximum_discharge_bus_w*count,
            cycling_damage_per_chemical_wh=port.cycling_damage_per_chemical_wh/count)
    return (fsum(b.nominal_energy_wh for b in spec.batteries),
            fsum(b.maximum_charge_bus_w for b in spec.batteries),
            fsum(b.maximum_discharge_bus_w for b in spec.batteries), port)


def admit_design(specification, common_root, ledger):
    """Paid engine plant owner; does not search designs or infer missing inputs."""
    if type(specification) is not DesignSpecification or type(common_root) is not LifecycleRoot or type(ledger) is not ConstructorLedger:
        raise TypeError('exact design, common lifecycle root and constructor ledger')
    specification.__post_init__(); common_root.__post_init__()
    spec = specification; base = common_root.base; old = base.model
    if spec.assembly.body_frame_id != old.assembly.body_frame_id:
        raise ValueError('BODY_FRAME_CHANGE_REQUIRES_EXPLICIT_COMMON_INITIAL_ATTITUDE_TRANSFORM')
    cp = base.initial_checkpoint
    if (cp.diagnostics.completed_steps or cp.simulation_time_seconds != old.environment.start_seconds or
            cp.spacecraft.data_storage.stored_records or cp.ground_data_delivery.partial_transfers or
            cp.ground_data_delivery.completed_deliveries):
        raise ValueError('B66_INITIAL_EMPTY_CUSTODY_ONLY_NO_RETAG')
    ledger.reserve()  # Spend before geometry/tensor/composition, including refusal.
    assessment = assess_design(spec.assembly)
    if not assessment.qualified or assessment.assembly is None:
        raise ValueError('B66_DECLARED_ASSEMBLY_INSTALLATION_OR_MASS_REFUSED')
    components = {c.component_id: c for c in assessment.assembly.components}
    cap, charge, discharge, port = _bank(spec, common_root)
    original_cfg = old.simulation_inputs.spacecraft_configuration
    battery = original_cfg.eps.battery
    battery = replace(battery, **{name: _derived(getattr(battery, name), value, explanation,
        tuple(b.provenance for b in spec.batteries))
        for name, value, explanation in (
            ('nominal_energy_wh', cap, 'sum of declared identical parallel module Wh'),
            ('max_charge_input_power_w', charge, 'sum of declared module charge bus W'),
            ('max_discharge_output_power_w', discharge, 'sum of declared module discharge bus W'))})
    ratings = []
    directions = []
    for p in spec.pv_modules:
        c = components[p.instance_id]
        sx, sy, sz = c.definition.size_m
        # Orthogonal projection of the declared cuboid envelope onto the plane
        # normal to n. Active area is AUTHOR INPUT, never inferred as this cap.
        face = fsum((abs(p.normal_local[0])*sy*sz,
                     abs(p.normal_local[1])*sx*sz, abs(p.normal_local[2])*sx*sy))
        if p.active_area_m2 > face:
            raise ValueError('PV_ACTIVE_AREA_EXCEEDS_DECLARED_PROJECTED_CUBOID_ENVELOPE')
        directions.append(vector(rotate(c.rotation_body_from_local, p.normal_local)))
        ratings.append(p.active_area_m2*p.reference_irradiance_w_m2*p.conversion_efficiency)
    if any(d != directions[0] for d in directions):
        raise ValueError('NONCOORIENTED_PV_REQUIRES_NEW_MULTIPANEL_PHYSICS_OWNER')
    solar = original_cfg.eps.solar_array
    solar = replace(solar, nominal_generation_w=_derived(solar.nominal_generation_w, fsum(ratings),
        'sum active area m2 * declared rating irradiance W/m2 * conversion efficiency; common irradiance factor',
        tuple(p.provenance for p in spec.pv_modules)))
    network = spec.configuration.thermal_network
    old_nodes = {n.node_id.value for n in old.configuration.thermal_network.nodes}
    if {n.node_id.value for n in network.nodes} != old_nodes:
        raise ValueError('NEW_THERMAL_NODE_REQUIRES_EXPLICIT_COMMON_ENVIRONMENT_FORCING_OWNER')
    nodes = []
    for node in network.nodes:
        parts = [p for p in spec.thermal_parts if p.node_id == node.node_id.value]
        capacity = fsum(components[p.instance_id].definition.mass_kg*p.specific_heat_j_per_kg_k for p in parts)
        area = fsum(p.radiating_area_m2 for p in parts)
        if area <= 0.:
            raise ValueError('positive declared node radiating area required')
        epsilon = fsum(p.radiating_area_m2*p.emissivity for p in parts)/area
        nodes.append(replace(node,
            heat_capacity_j_per_k=_derived(node.heat_capacity_j_per_k, capacity, 'sum physical instance mass kg * declared specific heat J/(kg K)', tuple(p.provenance for p in parts)),
            radiating_area_m2=_derived(node.radiating_area_m2, area, 'sum declared exposed radiating areas; no geometric self-shadow inference', tuple(p.provenance for p in parts)),
            emissivity=_derived(node.emissivity, epsilon, 'area-weighted emissivity at the explicitly common lump temperature', tuple(p.provenance for p in parts))))
    network = replace(network, nodes=tuple(nodes))
    cfg = replace(original_cfg, eps=replace(original_cfg.eps, battery=battery, solar_array=solar),
        thermal=replace(original_cfg.thermal, network=network), payload=spec.functional.payload_configuration)
    simulation = replace(old.simulation_inputs, spacecraft_configuration=cfg)
    construction_cfg = replace(spec.configuration, assembly_digest=assembly_document_digest(spec.assembly), thermal_network=network)
    construction = compile_construction(spec.assembly, construction_cfg)
    branches = {b.line_id: b for b in construction.branches}
    lines = {l.line_id: l for l in construction_cfg.lines}
    augmentation = replace(spec.augmentation, assembly_digest=construction_cfg.assembly_digest,
        construction_digest=construction.configuration_digest,
        routes=tuple(replace(r, geometry_digest=geometry_digest(branches[r.line_id], lines[r.line_id])) for r in spec.augmentation.routes))
    hardware = compile_effective_hardware(spec.assembly, spec.capabilities, spec.actuator, construction_cfg, augmentation)
    if hardware.panel_body_normal != directions[0]:
        raise ValueError('effective panel capability does not represent every declared PV module')
    environment = replace(old.environment, profile=tuple(replace(p, loads=spec.functional.baseline_loads)
        for p in old.environment.profile))
    model = replace(old, assembly=spec.assembly, capabilities=spec.capabilities, actuator=spec.actuator,
        simulation_inputs=simulation, configuration=construction_cfg, augmentation=augmentation,
        environment=environment, transmitter=spec.functional.transmitter, routing=spec.functional.routing,
        camera_half_fov_rad=spec.functional.camera_half_fov_rad)
    temps = dict(spec.initial_temperatures_k)
    template = cp.spacecraft.thermal.node_states[0]
    thermal = replace(cp.spacecraft.thermal, node_states=tuple(replace(template, node_id=n.node_id,
        temperature_k=temps[n.node_id.value]) for n in network.nodes))
    energy = cap*cp.spacecraft.degradation.battery.usable_capacity_retention*spec.initial_usable_energy_fraction
    initial = replace(cp, spacecraft=replace(cp.spacecraft, battery_energy_wh=energy, thermal=thermal))
    resource = replace(base.initial_estimate.resources, battery_energy_wh=energy, observed_temperatures=thermal.node_states)
    estimate = replace(base.initial_estimate, resources=resource)
    command = replace(base, reference=replace(base.reference, model=model, initial_checkpoint=initial, initial_estimate=estimate))
    study = common_root.study
    if study is not None:
        from .lifecycle_study import _roles
        roles = _roles(network); by_id = {n.node_id: n for n in network.nodes}
        if len(set(temps.values())) != 1:
            raise ValueError('legacy common study requires one explicitly declared initial temperature')
        study = replace(study, nodes=tuple(replace(n,
            heat_capacity_j_per_k=by_id[roles[n.role]].heat_capacity_j_per_k.value,
            radiating_area_m2=by_id[roles[n.role]].radiating_area_m2.value,
            emissivity=by_id[roles[n.role]].emissivity.value) for n in study.nodes),
            initial_energy_fraction=spec.initial_usable_energy_fraction, initial_temperature_k=next(iter(temps.values())),
            housekeeping_w=spec.functional.baseline_loads.base_bus_w)
    env_policy = common_root.environment_ageing_policy
    if env_policy is not None:
        # Existing policy must admit the new baseline. Never silently reset its
        # coefficients/limits/initial accumulated exposure to pass the builder.
        from .environment_ageing import admit_network
        admit_network(network, env_policy)
    root = replace(common_root, base=command, study=study, battery_port_policy=port)
    from .lifecycle_contract import static_admission
    static_admission(root)
    derived = (('battery_count', len(spec.batteries)), ('pv_count', len(spec.pv_modules)),
        ('battery_nominal_wh', cap), ('pv_rated_w', fsum(ratings)),
        ('mass_kg', hardware.mass_properties.total_mass_kg), ('harness_added_mass_kg', float(hardware.augmentation.added_mass_exact_kg)))
    return DesignAdmission(root, construction, hardware, spec.identity, common_root.identity, derived)


def admit_compiled_design(specification, common_root, compiled_root, ledger):
    """Independent engine recomputation of a DESIGNS compiler's proposed root."""
    result = admit_design(specification, common_root, ledger)
    from .lifecycle_document import dumps_root
    if type(compiled_root) is not LifecycleRoot or dumps_root(compiled_root) != dumps_root(result.root):
        raise ValueError('COMPILED_DESIGN_SPECIFICATION_OR_COMMON_AUTHORITY_MISMATCH')
    return result


def specification_from_root(common):
    """Explicit ASSUMED seed for editing; no inferred catalogue hardware truth.

    This convenience adapter recognizes the archived five-instance starter.
    Arbitrary new specs are admitted by DesignSpecification, not this adapter.
    """
    if type(common) is not LifecycleRoot:
        raise TypeError('exact initial common root')
    m = common.base.model; cfg = m.simulation_inputs.spacecraft_configuration
    assessed = assess_design(m.assembly)
    components = {c.component_id: c for c in assessed.assembly.components}
    ids = set(components)
    if not {'battery-left', 'battery-right'} <= ids:
        raise ValueError('no implicit battery-role inference: import an explicitly declared specification')
    provenance = DesignProvenance('ASSUMED', (),
        'Editable aggregate-equivalent demo: explicit ASSUMED MS equipment declaration (legacy supported_modes PAN metadata is not MS capability evidence); per-instance allocation and 1000 W/m2 PV rating are not sourced hardware measurements.')
    bp = common.battery_port_policy
    if bp is not None:
        bp = replace(bp, resistance_reference_ohm=bp.resistance_reference_ohm*2,
            maximum_charge_current_a=bp.maximum_charge_current_a/2,
            maximum_discharge_current_a=bp.maximum_discharge_current_a/2,
            maximum_charge_bus_w=bp.maximum_charge_bus_w/2,
            maximum_discharge_bus_w=bp.maximum_discharge_bus_w/2,
            cycling_damage_per_chemical_wh=bp.cycling_damage_per_chemical_wh*2)
    batteries = tuple(BatteryModule(n, cfg.eps.battery.nominal_energy_wh.value/2,
        cfg.eps.battery.max_charge_input_power_w.value/2, cfg.eps.battery.max_discharge_output_power_w.value/2,
        bp, provenance) for n in ('battery-left', 'battery-right'))
    panel_axis = next(c for c in m.capabilities if c.role == 'panel')
    normal = panel_axis.local_axis
    c = components[panel_axis.component_id]
    sx, sy, sz = c.definition.size_m
    area = fsum((abs(normal[0])*sy*sz, abs(normal[1])*sx*sz, abs(normal[2])*sx*sy))
    pv = (PVModule(c.component_id, normal, area, 1000., cfg.eps.solar_array.nominal_generation_w.value/(area*1000.), provenance),)
    assignments = {b.instance_id: b.node_id for b in m.configuration.thermal_bindings}
    assignments.update({n: cfg.thermal.network.battery_node_id.value for n in ('battery-left', 'battery-right')})
    if set(assignments) != ids:
        raise ValueError('starter lacks explicit thermal role; provide a general specification')
    nodes = {n.node_id.value: n for n in cfg.thermal.network.nodes}
    total = {n: fsum(components[i].definition.mass_kg for i in ids if assignments[i] == n) for n in nodes}
    parts = tuple(ThermalPart(i, assignments[i], nodes[assignments[i]].heat_capacity_j_per_k.value/total[assignments[i]],
        nodes[assignments[i]].radiating_area_m2.value*components[i].definition.mass_kg/total[assignments[i]],
        nodes[assignments[i]].emissivity.value, provenance) for i in sorted(ids))
    cp = common.base.initial_checkpoint
    usable = cfg.eps.battery.nominal_energy_wh.value*cp.spacecraft.degradation.battery.usable_capacity_retention
    if any(p.loads != m.environment.profile[0].loads for p in m.environment.profile):
        raise ValueError('piecewise functional baseline needs explicit versioned load schedule')
    # The archived legacy demo declares PAN metadata even though its lifecycle
    # owner runs MS. Do not copy that contradiction into an admitted new design.
    # This explicit ASSUMED demo declaration changes only the NEW specification;
    # it does not rewrite common input or claim measured equipment capability.
    demo_payload = replace(cfg.payload, supported_modes=(PayloadMode.MULTISPECTRAL,))
    functional = FunctionalPlant(demo_payload, m.transmitter, m.routing, m.environment.profile[0].loads,
        m.camera_half_fov_rad, provenance)
    return DesignSpecification(m.assembly, m.configuration, m.augmentation, m.capabilities, m.actuator,
        batteries, pv, parts, cp.spacecraft.battery_energy_wh/usable,
        tuple((n.node_id.value, n.temperature_k) for n in cp.spacecraft.thermal.node_states), provenance, functional)
