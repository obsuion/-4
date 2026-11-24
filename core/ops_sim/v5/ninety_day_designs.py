"""Bounded V6 research-intent authoring through the existing V3 design owners.

No catalogue lookup, saved root/result substitution, mission evaluation or file
write occurs here. The caller owns original common inputs, source binding and
constructor prepayment. The returned project is ordinary editable V3 DATA.
"""
from dataclasses import dataclass, replace
from hashlib import sha256
from math import fsum, isfinite
import json

from .assembly import MassCoverage, MountPose
from .assembly_choices import (AssemblyDesign, InstallationBox, InstallationRegion,
    PhysicalInstance, PlacementChoice, Selection, assess_design)
from .assembly_document import assembly_document_digest
from .assembly_interfaces import ThermalBinding, _port_body
from .construction_coupling import compile_construction
from .design_repair import ConstructorLedger, hash_identity
from .harness_mass import SpatialMassPoint, geometry_digest
from .lifecycle_contract import LifecycleRoot
from .spacecraft_design import DesignProvenance, specification_from_root
from .spacecraft_project import project_source_identity
from .spacecraft_project_v3 import SpacecraftProjectV3
from .spacecraft_route_thermal import (DesignSpecificationV2, DesignAdmissionV2,
    RouteThermalDeclaration, admit_design_v2, admit_compiled_design_v2)

FORMAT = 'KAZEOSAT_90D_FIVE_DESIGN_RESEARCH_INTENT_V1'
METHOD = 'CORE_90D_V6_DECLARED_FIVE_DESIGN_PRODUCER_V1'
ROUTING = 'ASSUMED_INSTALLED_EXTENTS_POSITIVE_X_RAIL_POSITIVE_Z_PLANE_V1'
ENVELOPE_PADDING_M = .001
CLEARANCE_M = .001
REGION_PADDING_M = .002
RAIL_PADDING_M = .02
MAX_INTENT_BYTES = 2**20


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False)


def _object(value, keys, label, optional=()):
    if type(value) is not dict or not set(keys) <= set(value) or set(value)-set(keys)-set(optional):
        raise ValueError('90D exact '+label+' fields')
    return value


def _text(value, label):
    if type(value) is not str or not 1 <= len(value) <= 4096 or any(ord(c) < 32 for c in value):
        raise ValueError('90D bounded plain '+label)
    value.encode('utf8', errors='strict')
    return value


def _number(value, label, low=0., high=64.):
    if type(value) not in (int, float):
        raise TypeError('90D built-in number '+label)
    value = float(value)
    if not isfinite(value) or not low <= value <= high:
        raise ValueError('90D finite bounded '+label)
    return value


def _vector(value, label, *, size=False):
    if type(value) is not list or len(value) != 3:
        raise ValueError('90D exact three-coordinate '+label)
    return tuple(_number(v, label, 1e-6 if size else -16., 8. if size else 16.) for v in value)


def _validate_intent(data):
    _object(data, ('format','status','scope','provenance','common_modules','designs',
        'common_rules','outputs','no_execution_by_this_file'), 'intent')
    if data['format'] != FORMAT or data['status'] != 'INTENT_NOT_COMPILED_NOT_EXECUTED' or data['no_execution_by_this_file'] is not True:
        raise ValueError('90D explicit nonexecuting research intent')
    scope = _object(data['scope'], ('duration_seconds','days_of_86400_seconds','initial_anchor_seconds',
        'target_seconds','design_count','maximum_parallel_workers','default_interactive_target','quiet_target'), 'scope')
    expected = dict(duration_seconds=7776000, days_of_86400_seconds=90, initial_anchor_seconds=128,
        target_seconds=7776128, design_count=5, maximum_parallel_workers=5,
        default_interactive_target=2, quiet_target=5)
    if any(type(scope[k]) is not int or scope[k] != v for k, v in expected.items()):
        raise ValueError('90D versioned declared scope')
    provenance = _object(data['provenance'], ('classification','module_origin','no_solid_cad_or_flight_certificate'), 'provenance')
    if provenance['classification'] != 'ASSUMED_RESEARCH_ASSEMBLIES_NOT_FLIGHT_HARDWARE' or provenance['no_solid_cad_or_flight_certificate'] is not True:
        raise ValueError('90D research assumption classification')
    _text(provenance['module_origin'], 'module origin')
    modules = _object(data['common_modules'], ('battery','pv','camera'), 'module set')
    battery = _object(modules['battery'], ('mass_kg','capacity_wh','size_m','electrical_bank','port_and_ageing'), 'battery')
    pv = _object(modules['pv'], ('mass_kg','nameplate_w','size_m','orientations'), 'PV')
    camera = _object(modules['camera'], ('mass_kg','size_m','orientation'), 'camera')
    for obj, values in ((battery,dict(mass_kg=1.,capacity_wh=50.)),
                        (pv,dict(mass_kg=.4,nameplate_w=25.)), (camera,dict(mass_kg=.2))):
        for k, v in values.items():
            if _number(obj[k], k, 1e-9, 1e6) != v:
                raise ValueError('90D fixed explicitly assumed module '+k)
    for obj, size in ((battery,(.1,.1,.1)),(pv,(.1,.6,.05)),(camera,(.1,.1,.1))):
        if _vector(obj['size_m'], 'module size', size=True) != size:
            raise ValueError('90D declared uniform-cuboid module size')
    if battery['electrical_bank'] != 'IDENTICAL_PARALLEL_COMMON_SOC_AND_TEMPERATURE':
        raise ValueError('90D only supported ideal parallel bank')
    for obj, keys in ((battery,('port_and_ageing',)),(pv,('orientations',)),(camera,('orientation',))):
        for k in keys: _text(obj[k], k)
    for key in ('common_rules','outputs'):
        if type(data[key]) is not list or not 1 <= len(data[key]) <= 64:
            raise ValueError('90D bounded '+key)
        for value in data[key]: _text(value, key)
    rows = data['designs']
    if type(rows) is not list or len(rows) != 5:
        raise ValueError('90D exactly five declared designs')
    names = set()
    for row in rows:
        _object(row, ('id','core','battery_positions_m','camera_position_m','pv_positions_m',
            'nominal_battery_wh','nominal_pv_w','expected_part_mass_before_harness_kg'), 'design', ('control_pair',))
        name = _text(row['id'], 'design ID')
        if len(name) > 80 or name in names: raise ValueError('90D unique bounded design IDs')
        names.add(name)
        core = _object(row['core'], ('mass_kg','size_m','position_m'), 'occupied core')
        core_mass = _number(core['mass_kg'], 'CORE mass', 1e-9, 1e6)
        _vector(core['size_m'], 'CORE size', size=True); _vector(core['position_m'], 'CORE position')
        _vector(row['camera_position_m'], 'camera position')
        for key in ('battery_positions_m','pv_positions_m'):
            if type(row[key]) is not list or not 1 <= len(row[key]) <= 8:
                raise ValueError('90D bounded declared module positions')
            for p in row[key]: _vector(p, key)
        nb, np = len(row['battery_positions_m']), len(row['pv_positions_m'])
        for key, value in (('nominal_battery_wh',nb*50.),('nominal_pv_w',np*25.),
                ('expected_part_mass_before_harness_kg',fsum((core_mass,nb*1.,np*.4,.2)))):
            if _number(row[key], key, 1e-9, 1e6) != value:
                raise ValueError('90D declared counts/ratings/part mass disagree: '+key)
    by_id = {row['id']: row for row in rows}
    for row in rows:
        if 'control_pair' in row:
            ref_id = _text(row['control_pair'], 'placement control').split(';',1)[0].strip()
            if ref_id not in by_id or ref_id == row['id']:
                raise ValueError('90D placement-control reference')
            ref = by_id[ref_id]
            if (len(row['battery_positions_m']) != len(ref['battery_positions_m']) or
                    any(row[k] != ref[k] for k in row if k not in ('id','battery_positions_m','control_pair'))):
                raise ValueError('90D control pair changes more than battery poses')
    return data


@dataclass(frozen=True, slots=True)
class ResearchIntent:
    raw_json: str

    def __post_init__(self):
        if type(self.raw_json) is not str or len(self.raw_json.encode('utf8')) > MAX_INTENT_BYTES:
            raise ValueError('90D bounded original UTF8 intent')
        def pairs(items):
            out = {}
            for k, v in items:
                if k in out: raise ValueError('90D duplicate JSON key')
                out[k] = v
            return out
        def constant(value): raise ValueError('90D nonfinite JSON constant '+value)
        _validate_intent(json.loads(self.raw_json, object_pairs_hook=pairs, parse_constant=constant))

    @property
    def data(self): return json.loads(self.raw_json)

    @property
    def raw_sha256(self): return sha256(self.raw_json.encode('utf8')).hexdigest()


def loads_intent(raw):
    if type(raw) is bytes: raw = raw.decode('utf8', errors='strict')
    if type(raw) is not str: raise TypeError('90D exact UTF8 bytes or string')
    return ResearchIntent(raw)


@dataclass(frozen=True, slots=True)
class AuthoredDesign:
    project: SpacecraftProjectV3
    intent: ResearchIntent
    design_id: str
    audit_json: str

    def __post_init__(self):
        if type(self.project) is not SpacecraftProjectV3 or type(self.intent) is not ResearchIntent:
            raise TypeError('90D exact V3 project and original intent')
        self.project.__post_init__(); self.intent.__post_init__()
        audit = json.loads(self.audit_json)
        if (audit['method'] != METHOD or audit['design_id'] != self.design_id or
                audit['intent_sha256'] != self.intent.raw_sha256 or
                audit['project_identity'] != self.project.identity or
                audit['specification_identity'] != self.project.specification.identity or
                audit['common_identity'] != self.project.common.identity):
            raise ValueError('90D authored input/audit binding mismatch')

    @property
    def audit(self): return json.loads(self.audit_json)


def _surface(size):
    x,y,z = size
    return 2.*fsum((x*y,x*z,y*z))


def _bounds(center, size, rotation):
    half = tuple(fsum(abs(rotation[i][j])*size[j]/2. for j in range(3)) for i in range(3))
    return tuple(center[i]-half[i] for i in range(3)), tuple(center[i]+half[i] for i in range(3))


def _route(start, end, upper):
    x,z = upper[0]+RAIL_PADDING_M, upper[2]+RAIL_PADDING_M
    candidates = ((start[0],start[1],z),(x,start[1],z),(x,end[1],z),(end[0],end[1],z))
    points = []
    for p in candidates:
        if p != (points[-1] if points else start): points.append(p)
    if points and points[-1] == end: points.pop()
    return tuple(points)


def author_project(common, intent, design_id, ledger, *, source_identity=None):
    """Spend one authoring unit before seed/geometry/route-owner work.

    This is a bounded installation author, not a collision solver. A genuine
    geometry refusal is returned to the caller before any mission freeze; no
    automatic outcome-dependent pose correction occurs.
    """
    if type(common) is not LifecycleRoot or type(intent) is not ResearchIntent or type(ledger) is not ConstructorLedger:
        raise TypeError('90D exact common root, original intent and paid ledger')
    common.__post_init__(); intent.__post_init__(); _text(design_id, 'design ID')
    rows = intent.data['designs']; row = next((r for r in rows if r['id'] == design_id), None)
    if row is None: raise ValueError('90D undeclared design ID')
    sid = project_source_identity() if source_identity is None else source_identity
    hash_identity(sid)
    if sid != project_source_identity(): raise ValueError('90D PROJECT_SOURCE_MISMATCH')
    ledger.reserve()
    seed = specification_from_root(common)
    assessed = assess_design(seed.assembly)
    if not assessed.qualified or assessed.assembly is None: raise ValueError('90D seed installation refused')
    old = {c.component_id:c for c in assessed.assembly.components}
    camera_axis = next(c for c in seed.capabilities if c.role == 'camera')
    panel_axis = next(c for c in seed.capabilities if c.role == 'panel')
    camera, panel = old[camera_axis.component_id], old[panel_axis.component_id]
    battery = old[seed.batteries[0].instance_id]; core = old[seed.configuration.bus_instance_id]
    modules = intent.data['common_modules']
    battery_ids = tuple('battery-'+str(i+1).zfill(3) for i in range(len(row['battery_positions_m'])))
    pv_ids = tuple('pv-'+str(i+1).zfill(3) for i in range(len(row['pv_positions_m'])))
    definitions = dict(core=replace(core.definition,definition_id='core',mass_kg=float(row['core']['mass_kg']),size_m=tuple(map(float,row['core']['size_m'])),center_local_m=(0.,0.,0.)),
        battery=replace(battery.definition,definition_id='battery',mass_kg=1.,size_m=(.1,.1,.1),center_local_m=(0.,0.,0.)),
        camera=replace(camera.definition,definition_id='camera',mass_kg=.2,size_m=(.1,.1,.1),center_local_m=(0.,0.,0.)),
        panel=replace(panel.definition,definition_id='panel',mass_kg=.4,size_m=(.1,.6,.05),center_local_m=(0.,0.,0.)))
    placed = [('core','core',tuple(map(float,row['core']['position_m'])),core.rotation_body_from_local),
        ('camera','camera',tuple(map(float,row['camera_position_m'])),camera.rotation_body_from_local)]
    placed += [(n,'battery',tuple(map(float,p)),battery.rotation_body_from_local) for n,p in zip(battery_ids,row['battery_positions_m'])]
    placed += [(n,'panel',tuple(map(float,p)),panel.rotation_body_from_local) for n,p in zip(pv_ids,row['pv_positions_m'])]
    frame = seed.assembly.body_frame_id
    bounds = {n:_bounds(p,definitions[k].size_m,rotation) for n,k,p,rotation in placed}
    lower = tuple(min(lo[i] for lo,hi in bounds.values()) for i in range(3))
    upper = tuple(max(hi[i] for lo,hi in bounds.values()) for i in range(3))
    instances=[];choices=[];selections=[]
    for name,kind,position,rotation in placed:
        definition=definitions[kind]; mount='mount-'+name
        pose=MountPose(mount,mount,frame,definition.local_frame_id,position,rotation,(name,))
        lo,hi=bounds[name]
        envelope=InstallationBox(tuple(v-ENVELOPE_PADDING_M for v in lo),tuple(v+ENVELOPE_PADDING_M for v in hi))
        instances.append(PhysicalInstance(name,kind,MassCoverage((('90d-declared-parts',name),))))
        choices.append(PlacementChoice(mount,kind,(name,),pose,envelope,'installed-envelope',True))
        selections.append(Selection(name,mount))
    extra=ENVELOPE_PADDING_M+REGION_PADDING_M
    region=InstallationRegion('installed-envelope',InstallationBox(tuple(v-extra for v in lower),tuple(v+extra for v in upper)))
    assembly=AssemblyDesign(frame,tuple(definitions.values()),tuple(instances),tuple(choices),tuple(selections),(region,),(),CLEARANCE_M)
    assessment=assess_design(assembly)
    if not assessment.qualified or assessment.assembly is None:
        raise ValueError('90D_GEOMETRY_REFUSED_BEFORE_SCIENCE:'+repr(assessment.violations))
    components={c.component_id:c for c in assessment.assembly.components}
    node_core=next(p.node_id for p in seed.thermal_parts if p.instance_id==core.component_id)
    node_battery=next(p.node_id for p in seed.thermal_parts if p.instance_id==battery.component_id)
    node_camera=next(p.node_id for p in seed.thermal_parts if p.instance_id==camera.component_id)
    oldparts={p.instance_id:p for p in seed.thermal_parts}
    area_fraction=oldparts[core.component_id].radiating_area_m2/_surface(core.definition.size_m)
    if not 0. < area_fraction <= 1.: raise ValueError('90D_SEED_CORE_RADIATOR_NOT_A_SUPPORTED_EXPOSED_FRACTION')
    provenance=DesignProvenance('ASSUMED',(),
        '90D explicitly assumed uniform-cuboid research modules and occupied CORE equipment/support lump; no vendor, CAD, strength or flight qualification. Intent SHA256='+intent.raw_sha256)
    parts=[];thermal_bindings=[]
    for name,kind,p,rotation in placed:
        template=oldparts[{'core':core.component_id,'battery':battery.component_id,'camera':camera.component_id,'panel':panel.component_id}[kind]]
        area=_surface(definitions[kind].size_m)*area_fraction if kind=='core' else template.radiating_area_m2
        node={'core':node_core,'battery':node_battery,'camera':node_camera,'panel':node_core}[kind]
        parts.append(replace(template,instance_id=name,node_id=node,radiating_area_m2=area,provenance=provenance))
        group='90d-battery-common-lump' if kind=='battery' else '90d-bus-common-lump' if kind in ('core','panel') else None
        thermal_bindings.append(ThermalBinding(name,node,group))
    ports=[]
    for port in seed.configuration.ports:
        name='core' if port.instance_id==core.component_id else 'camera' if port.instance_id==camera.component_id else pv_ids[0] if port.instance_id==panel.component_id else None
        if name is None: raise ValueError('90D explicit starter port ownership required')
        ports.append(replace(port,instance_id=name,local_frame_id=components[name].definition.local_frame_id))
    by_port={p.port_id:p for p in ports};lines=[]
    for line in seed.configuration.lines:
        start=_port_body(by_port[line.source_port_id],components[by_port[line.source_port_id].instance_id])
        end=_port_body(by_port[line.load_port_id],components[by_port[line.load_port_id].instance_id])
        mass=replace(line.mass,coverage=MassCoverage((('90d-external-harness',line.line_id),)))
        lines.append(replace(line,waypoints_body_m=_route(start,end,upper),mass=mass))
    cfg=replace(seed.configuration,assembly_digest=assembly_document_digest(assembly),bus_instance_id='core',ports=tuple(ports),lines=tuple(lines),thermal_bindings=tuple(thermal_bindings),
        rationale='90D ASSUMED peripheral-rail routing; occupied CORE covers supports/equipment once; external wire mass excluded and resolved separately; ideal internal bank leads unresolved.')
    construction=compile_construction(assembly,cfg)
    branches={b.line_id:b for b in construction.branches};by_line={l.line_id:l for l in cfg.lines};routes=[]
    for shape in seed.augmentation.routes:
        branch=branches[shape.line_id];line=by_line[shape.line_id]
        if line.wire.connector_count!=2: raise ValueError('90D seed requires two declared endpoint connectors')
        point=lambda p:SpatialMassPoint(frame,p)
        routes.append(replace(shape,geometry_digest=geometry_digest(branch,line),
            slack_point=point(line.waypoints_body_m[0]) if line.slack_m else None,
            connector_points=(point(branch.source_body_m),point(branch.load_body_m)),
            rationale='90D true endpoint connectors and declared +Z rail slack point; no internal bank-lead loss model.'))
    augmentation=replace(seed.augmentation,assembly_digest=cfg.assembly_digest,construction_digest=construction.configuration_digest,routes=tuple(routes))
    bmodule=seed.batteries[0]
    batteries=tuple(replace(bmodule,instance_id=n,nominal_energy_wh=50.,provenance=provenance)for n in battery_ids)
    pmodule=seed.pv_modules[0]
    seed_rating=pmodule.active_area_m2*pmodule.reference_irradiance_w_m2*pmodule.conversion_efficiency
    active=pmodule.active_area_m2 if seed_rating==25. else 25./(pmodule.reference_irradiance_w_m2*pmodule.conversion_efficiency)
    panels=tuple(replace(pmodule,instance_id=n,active_area_m2=active,provenance=provenance)for n in pv_ids)
    capabilities=tuple(replace(c,component_id='camera',local_frame_id=definitions['camera'].local_frame_id)if c.role=='camera'else
        replace(c,component_id=pv_ids[0],local_frame_id=definitions['panel'].local_frame_id)for c in seed.capabilities)
    base=replace(seed,assembly=assembly,configuration=cfg,augmentation=augmentation,capabilities=capabilities,
        batteries=batteries,pv_modules=panels,thermal_parts=tuple(parts),provenance=provenance)
    declarations=tuple(RouteThermalDeclaration(line.line_id,node_core,385.,
        DesignProvenance('ASSUMED',(),'90D common copper-equivalent conductor/slack/connector effective cp385 J/(kg K), capacity to existing BUS node; no new thermal nodes or hardware calibration.'))for line in cfg.lines)
    project=SpacecraftProjectV3(common,DesignSpecificationV2(base,declarations),sid,title='90D '+design_id)
    seed_audit=[]
    for role,component,mass,size in (('battery',battery,1.,(.1,.1,.1)),('pv',panel,.4,(.1,.6,.05)),('camera',camera,.2,(.1,.1,.1))):
        for key,before,after in (('mass_kg',component.definition.mass_kg,mass),('size_m',component.definition.size_m,size)):
            seed_audit.append(dict(role=role,quantity=key,seed=before,declared=after,conflict=before!=after))
    for role,before,after in (('battery_wh',bmodule.nominal_energy_wh,50.),('pv_w',pmodule.active_area_m2*pmodule.reference_irradiance_w_m2*pmodule.conversion_efficiency,25.)):
        seed_audit.append(dict(role=role,quantity='rating',seed=before,declared=after,conflict=before!=after))
    original_modes=common.base.model.simulation_inputs.spacecraft_configuration.payload.supported_modes
    admitted_modes=seed.functional.payload_configuration.supported_modes
    seed_audit.append(dict(role='camera',quantity='legacy_supported_modes_metadata',
        seed=[m.value for m in original_modes],declared=[m.value for m in admitted_modes],
        conflict=original_modes!=admitted_modes,
        resolution='Existing specification_from_root explicitly declares the lifecycle-consumed MS capability as ASSUMED; legacy PAN metadata is not new hardware evidence.'))
    audit=dict(method=METHOD,design_id=design_id,intent_sha256=intent.raw_sha256,project_identity=project.identity,
        specification_identity=project.specification.identity,common_identity=common.identity,source_identity=sid,
        seed_conflicts=seed_audit,geometry_repairs=[],intent_coordinate_diff=[],
        final_component_centers_body_m={c.component_id:c.center_body_m for c in assessment.assembly.components},
        final_rotations_body_from_local={c.component_id:c.rotation_body_from_local for c in assessment.assembly.components},
        overall_bounds_body_m=dict(lower=lower,upper=upper),occupied_CORE='Uniform cuboid equipment/support lump, not empty exterior shell',
        installation=dict(envelope_padding_m=ENVELOPE_PADDING_M,clearance_m=CLEARANCE_M,region_padding_m=REGION_PADDING_M,checked='GENUINE_ASSESS_DESIGN'),
        routing=dict(method=ROUTING,rail_padding_m=RAIL_PADDING_M,internal_battery_and_PV_bank_leads='IDEAL_UNRESOLVED_NO_SEPARATE_LOSS_CLAIM',external_branches=8,wire_rule='Same exact inherited per-line wire/slack/connector declarations for every design'),
        thermal=dict(core_exposed_fraction=area_fraction,core_radiating_area_m2=next(p.radiating_area_m2 for p in parts if p.instance_id=='core'),
            core_area_formula='seed_core_area/seed_core_surface * 2*(xy+xz+yz)',route_specific_heat_j_per_kg_k=385.,route_capacity_destination=node_core,
            part_specific_heat_rule='Retain inherited per-role seed cp; genuine mass*cp and route m*cp owners recompute; no compensating cp',
            new_nodes=False,links='Exact inherited graph',external_forcing='Exact common prescribed forcing; no geometric heating/shadow inference'),
        initial_usable_energy_fraction=seed.initial_usable_energy_fraction,initial_temperatures_k=seed.initial_temperatures_k,
        constructor_units=dict(author=1,compile=2,independent_confirmation=2),authority='PROJECT_INPUT_ONLY_NOT_A_COMPILED_ROOT_OR_MISSION_RESULT')
    return AuthoredDesign(project,intent,design_id,_canonical(audit))


def compile_project(authored, ledger):
    if type(authored) is not AuthoredDesign: raise TypeError('90D exact authored design')
    authored.__post_init__()
    return admit_design_v2(authored.project.specification,authored.project.common,ledger)


def confirm_compiled(authored, proposed_root, ledger):
    if type(authored) is not AuthoredDesign: raise TypeError('90D exact authored design')
    authored.__post_init__()
    return admit_compiled_design_v2(authored.project.specification,authored.project.common,proposed_root,ledger)


def design_report(authored, admission):
    """Derived public DATA from an actual paid admission, never new authority."""
    if type(authored) is not AuthoredDesign or type(admission) is not DesignAdmissionV2:
        raise TypeError('90D authored design and actual admission required')
    authored.__post_init__()
    if admission.specification_identity!=authored.project.specification.identity or admission.common_identity!=authored.project.common.identity or admission.route_thermal.root_identity!=admission.root.identity:
        raise ValueError('90D stale admission report binding')
    mass=admission.hardware.mass_properties;cfg=admission.root.base.model.simulation_inputs.spacecraft_configuration
    return dict(format='CORE_90D_V6_ACTUAL_DESIGN_ADMISSION_REPORT_V1',design_id=authored.design_id,
        source_identity=authored.project.source_identity,project_identity=authored.project.identity,specification_identity=admission.specification_identity,
        common_identity=admission.common_identity,root_identity=admission.root.identity,authoring=authored.audit,
        mass=dict(part_mass_kg=admission.hardware.augmentation.base_mass_properties.total_mass_kg,
            harness_mass_exact_kg=[str(admission.hardware.augmentation.added_mass_exact_kg.numerator),str(admission.hardware.augmentation.added_mass_exact_kg.denominator)],
            total_mass_kg=mass.total_mass_kg,COM_body_m=mass.center_body_m,inertia_COM_body_kg_m2=mass.inertia_com_body_kg_m2),
        nominal_battery_wh=cfg.eps.battery.nominal_energy_wh.value,nominal_pv_w=cfg.eps.solar_array.nominal_generation_w.value,
        initial_energy_wh=admission.root.base.initial_checkpoint.spacecraft.battery_energy_wh,
        routes=[dict(line_id=b.line_id,source_body_m=b.source_body_m,load_body_m=b.load_body_m,polyline_length_m=b.polyline_length_m,
            loop_length_including_slack_m=b.wire.loop_length_m,resistance_ohm=b.wire.resistance_ohm,
            current_limit_a=b.wire.current_limit_a,max_drop_v=b.wire.max_drop_v,
            conductor_mass_kg=b.wire.conductor_mass_kg,connector_mass_kg=b.wire.connector_total_mass_kg,
            loss_scope='Existing dynamic constant-power/generated line owners; zero constructor operating power is not mission loss evidence')for b in admission.construction.branches],
        thermal_plant=[dict(node=n.node_id.value,capacity_j_per_k=n.heat_capacity_j_per_k.value,radiating_area_m2=n.radiating_area_m2.value,emissivity=n.emissivity.value)for n in cfg.thermal.network.nodes],
        route_mass_cp=admission.route_thermal.as_data(),mission_execution='NOT_PERFORMED_BY_PRODUCER',
        physical_qualification='NOT_ESTABLISHED_ASSUMED_RIGID_LUMPED_RESEARCH_DESIGNS')
