"""B46 rigid/lumped harness mass closure. Inputs never contain a supplied tensor.

WireSpec total conductor mass is authoritative binary64. Exact rational
length shares allocate that total; intrinsic rods use exact endpoint dyadics.
Both co-routed conductors, point-reduced slack and each series connector have
distinct descendant physical coverage. No CAD/clearance/flexible-body claim.
"""
from dataclasses import dataclass,replace
from fractions import Fraction as Q
from math import dist,isfinite
from .assembly import _identity,_vector,_overlap,calculate_mass_properties,AssemblyMassProperties
from .assembly_choices import assess_design
from .assembly_interfaces import ElectricalPort,_port_body
from .assembly_document import assembly_document_digest
from .construction_coupling import compile_construction,digest
from .assembly_attitude_3d import admit_tensor

METHOD='B46_EXCLUDED_BASE_INCLUDED_RIGID_RODS_POINT_SLACK_CONNECTORS_V1'


def _digest(value):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('exact SHA256 binding required')


@dataclass(frozen=True,slots=True)
class SpatialMassPoint:
    frame_id: str
    coordinates_m: tuple
    instance_id: str | None = None
    frame_kind: str = 'BODY'
    def __post_init__(self):
        _identity(self.frame_id,'mass point frame');_identity(self.frame_kind,'mass point kind')
        object.__setattr__(self,'coordinates_m',_vector(self.coordinates_m,'mass point metres'))
        if any(abs(x)>64 for x in self.coordinates_m):raise ValueError('mass point outside64m domain')
        if self.frame_kind=='BODY':
            if self.instance_id is not None:raise ValueError('body point cannot claim local instance')
        elif self.frame_kind=='COMPONENT_LOCAL':_identity(self.instance_id,'local point instance')
        else:raise ValueError('unsupported mass point frame')


@dataclass(frozen=True,slots=True)
class RouteMassDistribution:
    line_id: str
    geometry_digest: str
    slack_point: SpatialMassPoint | None
    connector_points: tuple[SpatialMassPoint,...]
    rationale: str
    slack_model: str = 'DECLARED_POINT_MASS_TWO_CONDUCTORS_V1'
    def __post_init__(self):
        _identity(self.line_id,'mass line');_digest(self.geometry_digest);_identity(self.rationale,'mass spatial rationale')
        _identity(self.slack_model,'slack model')
        if self.slack_model!='DECLARED_POINT_MASS_TWO_CONDUCTORS_V1':raise ValueError('unsupported slack spatial model')
        if self.slack_point is not None:
            if type(self.slack_point) is not SpatialMassPoint:raise TypeError('exact slack point')
            object.__setattr__(self,'slack_point',replace(self.slack_point))
        if type(self.connector_points) is not tuple or len(self.connector_points)>2048 or any(type(p) is not SpatialMassPoint for p in self.connector_points):raise ValueError('bounded explicit connector points')
        object.__setattr__(self,'connector_points',tuple(replace(p) for p in self.connector_points))


@dataclass(frozen=True,slots=True)
class HarnessMassPolicy:
    max_contributions: int = 2048
    max_fraction_bits: int = 4096
    max_runtime_compiles: int = 128
    control_units_per_compile: int = 2**20
    max_runtime_control_units: int = 2**27
    def __post_init__(self):
        for name,cap in (('max_contributions',2048),('max_fraction_bits',4096),('max_runtime_compiles',128),('max_runtime_control_units',2**27)):
            v=getattr(self,name)
            if type(v) is not int or not 1<=v<=cap:raise ValueError('finite harness policy:'+name)
        if type(self.control_units_per_compile) is not int or self.control_units_per_compile!=2**20:raise ValueError('fixed harness compilation control reservation')


@dataclass(frozen=True,slots=True)
class HarnessAugmentationInputs:
    assembly_digest: str
    construction_digest: str
    body_frame_id: str
    routes: tuple[RouteMassDistribution,...]
    policy: HarnessMassPolicy = HarnessMassPolicy()
    method: str = METHOD
    def __post_init__(self):
        _digest(self.assembly_digest);_digest(self.construction_digest);_identity(self.body_frame_id,'augmentation frame');_identity(self.method,'mass method')
        if self.method!=METHOD:raise ValueError('unsupported augmentation method')
        if type(self.policy) is not HarnessMassPolicy:raise TypeError('harness policy required')
        self.policy.__post_init__()
        if type(self.routes) is not tuple or len(self.routes)!=8 or any(type(r) is not RouteMassDistribution for r in self.routes):raise ValueError('exact eight route distributions required')
        values=tuple(replace(r) for r in self.routes)
        if len({r.line_id for r in values})!=8:raise ValueError('duplicate route mass ownership')
        object.__setattr__(self,'routes',tuple(sorted(values,key=lambda r:r.line_id)))


@dataclass(frozen=True,slots=True)
class MassContribution:
    contribution_id: str
    line_id: str
    kind: str
    coverage: tuple[str,...]
    mass_kg: Q
    center_body_m: tuple[Q,...]
    intrinsic_tensor_body_kg_m2: tuple
    endpoints_body_m: tuple


@dataclass(frozen=True,slots=True)
class HarnessMassCompilation:
    input_digest: str
    construction_digest: str
    base_mass_properties: AssemblyMassProperties
    effective_mass_properties: AssemblyMassProperties
    contributions: tuple[MassContribution,...]
    added_mass_exact_kg: Q
    effective_mass_exact_kg: Q
    effective_center_exact_m: tuple
    effective_tensor_exact_kg_m2: tuple
    route_closure: tuple
    tensor_as_binary64: tuple
    spd_leading_minors: tuple
    mass_scope: str = 'MASS_CLOSED_WITHIN_RIGID_LUMPED_B46_MODEL'
    method: str = METHOD


def geometry_digest(branch,line):return digest((branch,line.waypoints_body_m,line.slack_m,line.mass))


def resolve_point(point,design,components):
    point=replace(point)
    if point.frame_kind=='BODY':
        if point.frame_id!=design.body_frame_id:raise ValueError('foreign body mass-point frame')
        value=point.coordinates_m
    else:
        if point.instance_id not in components:raise ValueError('foreign local mass point instance')
        c=components[point.instance_id]
        if point.frame_id!=c.definition.local_frame_id:raise ValueError('foreign local mass-point frame')
        p=ElectricalPort('b46-local-mass-point',point.instance_id,point.frame_id,point.coordinates_m,'LOAD')
        value=_port_body(p,c)
    if any(not isfinite(x) or abs(x)>64 for x in value):raise ValueError('resolved mass point outside bounded body geometry')
    return tuple(Q(x) for x in value)


def _parallel(d):
    return tuple(tuple(sum(d[k]*d[k] for k in range(3) if k!=i) if i==j else -d[i]*d[j] for j in range(3)) for i in range(3))


def combine_mass_properties(base,contributions):
    """Exact shift-to-new-COM sum; no origin subtraction cancellation."""
    m0=Q(base.total_mass_kg);c0=tuple(Q(x) for x in base.center_body_m)
    mass=m0+sum(c.mass_kg for c in contributions)
    center=tuple((m0*c0[i]+sum(c.mass_kg*c.center_body_m[i] for c in contributions))/mass for i in range(3))
    shift=_parallel(tuple(x-y for x,y in zip(c0,center)))
    tensor=[[Q(base.inertia_com_body_kg_m2[i][j])+m0*shift[i][j] for j in range(3)] for i in range(3)]
    for c in contributions:
        shift=_parallel(tuple(x-y for x,y in zip(c.center_body_m,center)))
        for i in range(3):
            for j in range(3):tensor[i][j]+=c.intrinsic_tensor_body_kg_m2[i][j]+c.mass_kg*shift[i][j]
    return mass,center,tuple(tuple(row) for row in tensor)


def compile_harness_mass(design,configuration,inputs):
    if type(inputs) is not HarnessAugmentationInputs:raise TypeError('exact harness augmentation input required')
    inputs=replace(inputs);construction=compile_construction(design,configuration)
    if inputs.assembly_digest!=assembly_document_digest(design) or inputs.construction_digest!=construction.configuration_digest or inputs.body_frame_id!=design.body_frame_id:raise ValueError('stale assembly/construction mass binding')
    assessment=assess_design(design);base=calculate_mass_properties(assessment.assembly)
    components={c.component_id:c for c in assessment.assembly.components}
    if len(components)>32 or any(any(abs(x)>64 for x in c.center_body_m) for c in components.values()):raise ValueError('bounded base mass geometry required')
    distributions={r.line_id:r for r in inputs.routes};lines={l.line_id:l for l in configuration.lines}
    if set(distributions)!=set(lines):raise ValueError('omitted/foreign harness route')
    if any(l.mass.status!='EXCLUDED' for l in lines.values()):raise ValueError('INCLUDED_AGGREGATE_DISTRIBUTION_UNSUPPORTED_NO_DOUBLE_ADDITION')
    # Cardinality admission precedes contribution allocation and rational work.
    upper=sum(2*(len(l.waypoints_body_m)+1)+2+len(distributions[l.line_id].connector_points) for l in lines.values())
    if upper>inputs.policy.max_contributions:raise ValueError('harness contribution admission exceeded')
    rows=[];closure=[]
    zero=tuple(tuple(Q(0) for _ in range(3)) for _ in range(3))
    for branch in construction.branches:
        line=lines[branch.line_id];shape=distributions[line.line_id]
        if shape.geometry_digest!=geometry_digest(branch,line):raise ValueError('stale route/shape digest')
        if len(line.mass.coverage.paths)!=1:raise ValueError('one disjoint route coverage lineage required')
        root=line.mass.coverage.paths[0]
        if branch.wire.connector_count!=len(shape.connector_points):raise ValueError('omitted/repeated connector distribution')
        if line.slack_m>0 and shape.slack_point is None or line.slack_m==0 and shape.slack_point is not None:raise ValueError('explicit slack distribution must match actual slack')
        points=(branch.source_body_m,*line.waypoints_body_m,branch.load_body_m)
        if any(any(abs(x)>64 for x in p) for p in points):raise ValueError('route geometry outside64m')
        lengths=tuple(Q(dist(a,b)) for a,b in zip(points,points[1:]));weight=sum(lengths)+Q(line.slack_m)
        conductor=Q(branch.wire.conductor_mass_kg);before=len(rows)
        if conductor>0 and weight<=0:raise ValueError('positive conductor mass without geometry')
        def append(tag,kind,mass,center,J,endpoints=()):
            if mass<=0 or mass>2**20:raise ValueError('positive bounded contribution mass required')
            rows.append(MassContribution(line.line_id+':'+tag,line.line_id,kind,root+(tag,),mass,center,J,endpoints))
        for index,(a,b,length) in enumerate(zip(points,points[1:],lengths)):
            if length==0:continue
            p,q=tuple(Q(x) for x in a),tuple(Q(x) for x in b)
            d=tuple(y-x for x,y in zip(p,q));center=tuple((x+y)/2 for x,y in zip(p,q))
            for polarity in ('positive','return'):
                mass=conductor*length/(2*weight)
                # m/12*(||d||²I-dd^T), algebraically identical to unit-rod law.
                parallel=_parallel(d);J=tuple(tuple(mass*value/12 for value in row) for row in parallel)
                append('conductor-'+polarity+'-segment-'+str(index),'UNIFORM_SLENDER_ROD',mass,center,J,(p,q))
        if line.slack_m>0:
            center=resolve_point(shape.slack_point,design,components)
            for polarity in ('positive','return'):
                mass=conductor*Q(line.slack_m)/(2*weight)
                if mass>0:append('slack-'+polarity,'DECLARED_POINT_SLACK',mass,center,zero)
        connector_total=Q(branch.wire.connector_total_mass_kg)
        for index,point in enumerate(shape.connector_points):
            mass=connector_total/branch.wire.connector_count;center=resolve_point(point,design,components)
            if mass>0:append('connector-'+str(index),'DECLARED_POINT_CONNECTOR',mass,center,zero)
        allocated=sum(c.mass_kg for c in rows[before:])
        expected=conductor+connector_total
        if allocated!=expected:raise ValueError('exact conductor/connector mass closure failed')
        closure.append((line.line_id,conductor,connector_total,allocated,branch.wire.connector_count,len(shape.connector_points)))
    if len(rows)>inputs.policy.max_contributions or len({r.contribution_id for r in rows})!=len(rows):raise ValueError('duplicate/over-cap contribution')
    # compile_construction proves distinct route roots disjoint from each
    # other and the base. Distinct generated ONE-level tags under each root
    # prove every contribution disjoint without an unbounded quadratic scan.
    if len({r.coverage for r in rows})!=len(rows):raise ValueError('overlapping physical contribution claims')
    mass,center,tensor=combine_mass_properties(base,tuple(rows))
    for value in (mass,*center,*(x for row in tensor for x in row)):
        if max(abs(value.numerator).bit_length(),value.denominator.bit_length())>inputs.policy.max_fraction_bits:raise ValueError('bounded exact mass arithmetic exhausted')
    if not 0<mass<=2**20:raise ValueError('effective mass outside bounded domain')
    binary=tuple(tuple(float(x) for x in row) for row in tensor);I,minors=admit_tensor(binary)
    effective=AssemblyMassProperties(design.body_frame_id,float(mass),tuple(float(x) for x in center),binary)
    return HarnessMassCompilation(digest(inputs),construction.configuration_digest,base,effective,tuple(rows),
        sum(r.mass_kg for r in rows),mass,center,tensor,tuple(closure),binary,minors)
