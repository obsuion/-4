"""Immutable M8 inputs and paid real M1/M4 preview. No dynamic state in inputs."""
from dataclasses import dataclass, replace, asdict
from hashlib import sha256
from pathlib import Path
from itertools import product
from .command_estimation import CommandRollingRoot
from .design_repair import (ConstructorLedger, MissionRequirements, DesignRepairSpec,
    rebuild_model, hash_identity, source_identity)
from .rolling_contract import integer
from .rolling_physics import digest
from .assembly_choices import assess_design

METHOD = 'M8_BOUNDED_PERSISTENT_CONSTRUCTOR_PROJECT_V1'
AREAS = (1e-10, 1e-6, 1e-8, 1e-7)
PREVIEW = 'M8_PAID_M1_M4_CONSTRUCTOR_PREVIEW_V1'

def project_source_identity():
    assets = Path(__file__).with_name('workbench_assets')
    body = source_identity() + '\n' + '\n'.join(p.name+':'+sha256(p.read_bytes()).hexdigest()
        for p in sorted(assets.iterdir()) if p.is_file())
    return sha256(body.encode()).hexdigest()

@dataclass(frozen=True, slots=True)
class ProjectLimits:
    maximum_jobs: int = 4
    maximum_constructor_compiles: int = 32
    execution_seconds: int = 420
    cleanup_seconds: int = 2
    maximum_store_bytes: int = 2**31
    maximum_science_bytes: int = 128*2**20
    maximum_packet_bytes: int = 64*2**20
    maximum_metadata_bytes: int = 8*2**20
    maximum_progress_bytes: int = 2**20
    maximum_exports: int = 4
    maximum_control_reserved: int = 4*2**44+2**34
    def __post_init__(self):
        caps = dict(maximum_jobs=4,maximum_constructor_compiles=32,execution_seconds=420,
            cleanup_seconds=2,maximum_store_bytes=2**31,maximum_science_bytes=128*2**20,
            maximum_packet_bytes=64*2**20,maximum_metadata_bytes=8*2**20,
            maximum_progress_bytes=2**20,maximum_exports=4,maximum_control_reserved=4*2**44+2**34)
        for n,cap in caps.items(): integer(getattr(self,n),n,1,cap)
        for n in ('maximum_constructor_compiles','maximum_store_bytes','maximum_science_bytes',
            'maximum_packet_bytes','maximum_metadata_bytes','maximum_progress_bytes','maximum_control_reserved'):
            if getattr(self,n)!=caps[n]:raise ValueError('fixed bounded publication/control contract: '+n)
        if self.cleanup_seconds!=2: raise ValueError('accepted shared cleanup allowance is two seconds')
        if self.maximum_science_bytes+self.maximum_packet_bytes+self.maximum_metadata_bytes>self.maximum_store_bytes:
            raise ValueError('one complete result/packet must fit store admission')

@dataclass(frozen=True, slots=True)
class SpacecraftProject:
    reference: CommandRollingRoot
    source_identity: str
    title: str = 'КазEOSat — мой проект'
    placement: str = 'compact'
    payload_area_m2: float = 1e-8
    requirements: MissionRequirements = MissionRequirements()
    limits: ProjectLimits = ProjectLimits()
    method: str = METHOD
    def __post_init__(self):
        if type(self.reference) is not CommandRollingRoot: raise TypeError('exact immutable command template')
        # Reuse the existing strict weak-reference/mission/domain admission.
        DesignRepairSpec(self.reference,source_identity())
        hash_identity(self.source_identity)
        if type(self.title) is not str or not 1<=len(self.title)<=120 or any(ord(c)<32 for c in self.title):
            raise ValueError('bounded plain project title')
        if type(self.placement) is not str or self.placement not in ('compact','outboard'):
            raise ValueError('only compact/outboard placement is editable')
        if type(self.payload_area_m2) is not float or self.payload_area_m2 not in AREAS:
            raise ValueError('payload area must be one of four declared binary64 SI inputs')
        if type(self.requirements) is not MissionRequirements or type(self.limits) is not ProjectLimits:
            raise TypeError('exact requirements/limits')
        self.requirements.__post_init__();self.limits.__post_init__()
        if self.requirements.minimum_credited_products>len(self.reference.requests):
            raise ValueError('required product population exceeds this mission')
        if type(self.method) is not str or self.method!=METHOD: raise ValueError('project method')
    @property
    def identity(self): return digest(self)
    @property
    def comparison_identity(self): return digest((self.reference,self.requirements))

def edit_project(project, *, placement=None,payload_area_m2=None,requirements=None,title=None):
    if type(project) is not SpacecraftProject:
        from .spacecraft_project_v2 import SpacecraftProjectV2
        from .spacecraft_project_v3 import SpacecraftProjectV3
        if type(project)not in (SpacecraftProjectV2,SpacecraftProjectV3):raise TypeError('exact project input')
        if placement is not None or payload_area_m2 is not None:
            raise ValueError('V2 design specification requires explicit JSON revision, not legacy preset controls')
        return replace(project,**{n:v for n,v in dict(requirements=requirements,title=title).items()if v is not None})
    return replace(project,**{n:v for n,v in dict(placement=placement,payload_area_m2=payload_area_m2,
        requirements=requirements,title=title).items() if v is not None})

def require_short_project(project):
    """Admit only the legacy rolling contract, before short-job side effects.

    A general project owns a complete LifecycleRoot. Its base cannot stand in
    for the scenario, environment, battery port, or lifecycle policy wrappers.
    """
    if type(project) is not SpacecraftProject:
        raise ValueError('GENERAL_PROJECT_REQUIRES_FULL_LIFECYCLE_DISPATCH')
    return project

def materialize_project(project, ledger):
    from .spacecraft_project_v3 import SpacecraftProjectV3
    if type(project)is SpacecraftProjectV3:
        from .spacecraft_project_v3 import materialize_project as materialize_v3
        return materialize_v3(project,ledger)
    if type(project)is not SpacecraftProject:
        from .spacecraft_project_v2 import materialize_project as materialize_v2
        return materialize_v2(project,ledger)
    if type(project) is not SpacecraftProject or type(ledger) is not ConstructorLedger:
        raise TypeError('exact project and paid constructor ledger')
    project.__post_init__()
    if project.source_identity!=project_source_identity(): raise ValueError('PROJECT_SOURCE_MISMATCH')
    model,construction,hardware=rebuild_model(project.reference,project.placement,project.payload_area_m2,ledger)
    root=replace(project.reference,reference=replace(project.reference.reference,model=model))
    return root,construction,hardware

def preview_project(project, ledger):
    from .spacecraft_project_v3 import SpacecraftProjectV3
    if type(project)is SpacecraftProjectV3:
        from .spacecraft_project_v3 import preview_project as preview_v3
        return preview_v3(project,ledger)
    if type(project)is not SpacecraftProject:
        from .spacecraft_project_v2 import preview_project as preview_v2
        return preview_v2(project,ledger)
    root,compiled,hardware=materialize_project(project,ledger)
    return _preview_materialized(project,ledger,root,compiled,hardware)

def _preview_materialized(project,ledger,root,compiled,hardware):
    """Render admitted derived owners; never infer geometry from preset names."""
    general=type(project)is not SpacecraftProject
    assessment=assess_design(root.model.assembly)
    components=[]
    for c in assessment.assembly.components:
        size=c.definition.size_m;rotation=c.rotation_body_from_local
        # Cuboid dimensions extend about local COM; r_B is already mounted COM.
        vertices=[tuple(c.center_body_m[i]+sum(rotation[i][j]*s[j]*size[j]/2 for j in range(3))
            for i in range(3)) for s in product((-1,1),repeat=3)]
        components.append(dict(id=c.component_id,definition=asdict(c.definition),center_body_m=c.center_body_m,
            rotation_body_from_local=rotation,vertices_body_m=vertices,
            mount=None if c.mount_pose is None else asdict(c.mount_pose),
            mass_coverage=None if c.mass_coverage is None else asdict(c.mass_coverage),
            editable_placement=general or c.component_id in ('battery-left','battery-right')))
    lines={l.line_id:l for l in root.model.configuration.lines};routes=[];ports=[]
    for b in compiled.branches:
        line=lines[b.line_id];wire=b.wire
        routes.append(dict(id=b.line_id,points_body_m=(b.source_body_m,*line.waypoints_body_m,b.load_body_m),
            polyline_length_m=b.polyline_length_m,slack_m=line.slack_m,
            one_way_length_m=wire.one_way_length_m,conductor_length_m=wire.loop_length_m,
            cross_section_m2=wire.cross_section_m2,resistance_ohm=wire.resistance_ohm,
            resistivity_ohm_m=wire.resistivity_ohm_m,density_kg_m3=wire.density_kg_m3,
            current_limit_a=wire.current_limit_a,max_drop_v=wire.max_drop_v,
            heat_node_id=b.heat_node_id,mass_status=b.mass_status))
        for port_id,point in ((line.source_port_id,b.source_body_m),(line.load_port_id,b.load_body_m)):
            p=next(p for p in root.model.configuration.ports if p.port_id==port_id)
            ports.append(dict(id=p.port_id,instance_id=p.instance_id,local_frame_id=p.local_frame_id,
                position_local_m=p.position_local_m,position_body_m=point,role=p.role))
    props=hardware.mass_properties;base=hardware.base_hardware.mass_properties
    indexed={c.component_id:c for c in assessment.assembly.components}
    mount_vectors=[dict(role=b.role,component_id=b.component_id,local_frame_id=b.local_frame_id,
        origin_body_m=indexed[b.component_id].mount_pose.origin_body_m,local_axis=b.local_axis,
        direction_body=hardware.camera_body_axis if b.role=='camera' else hardware.panel_body_normal,
        assumption=b.assumption) for b in hardware.capabilities]
    return dict(format=PREVIEW,project_identity=project.identity,source_identity=project.source_identity,
        root_identity=digest(root),hardware_identity=digest(hardware),construction_identity=compiled.configuration_digest,
        body_frame_id=root.model.assembly.body_frame_id,
        units=dict(position='m',mass='kg',inertia='kg m^2',conductor_area='m^2',resistance='ohm'),
        components=components,ports=ports,routes=routes,mount_vectors=mount_vectors,camera_body_axis=hardware.camera_body_axis,
        panel_body_normal=hardware.panel_body_normal,base_mass_kg=base.total_mass_kg,
        added_harness_mass_kg=props.total_mass_kg-base.total_mass_kg,
        added_harness_mass_exact_kg=str(hardware.augmentation.added_mass_exact_kg),
        mass_properties=asdict(props),constructor_work=asdict(ledger),
        declaration_checks=dict(installation=assessment.installation_status,mass_accounting=assessment.mass_accounting_status),
        assumptions=['ASSUMED uniform cuboids, authored mounts and route/slack rules',
            'Ideal regulated star, wire-loss heat, lumped thermal and ideal net-body-torque model',
            ('Immutable user common mission/world/controller; authored ASSUMED coefficients are not flight calibration'
                if general else '600 s synthetic nominal geometry/forcing, 40 s observation delay; no flight certificate')],
        grant='CONSTRUCTOR_PREVIEW_ONLY_NO_MISSION_OR_VISIBILITY_CREDIT')


def constructor_compile_bound(project):
    from .spacecraft_project_v2 import SpacecraftProjectV2
    from .spacecraft_project_v3 import SpacecraftProjectV3
    if type(project)is SpacecraftProject:return 1
    if type(project)in (SpacecraftProjectV2,SpacecraftProjectV3):
        from .spacecraft_route_thermal import constructor_compile_bound as bound
        return bound(project.specification)
    raise TypeError('exact project constructor requirement')


def materialize_design_project(project,ledger):
    from .spacecraft_project_v2 import SpacecraftProjectV2,materialize_lifecycle_project as old
    from .spacecraft_project_v3 import SpacecraftProjectV3,materialize_lifecycle_project as route
    if type(project)is SpacecraftProjectV2:return old(project,ledger)
    if type(project)is SpacecraftProjectV3:return route(project,ledger)
    raise TypeError('exact full lifecycle project family')
