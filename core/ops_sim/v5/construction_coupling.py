"""B45 explicit ideal regulated-star construction; no circuit or routing solver."""
from dataclasses import dataclass, replace
from hashlib import sha256
from itertools import combinations
from math import dist, fsum, isfinite
from .assembly import _identity, _overlap
from .assembly_choices import assess_design
from .assembly_document import assembly_document_digest
from .assembly_interfaces import (ElectricalPort, LineConnection, ThermalBinding, _port_body, _network)
from .experiment_codec import canonical_copy
from .thermal_routing import ElectricalLoadComponent
from .thermal import ThermalIntervalInputs
from .thermal_config import ThermalNetworkConfig


def _positive(value, name):
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(name+' requires finite positive built-in number')
    return float(value)


def digest(value):
    from .long_mission_continuation import _scientific
    from .long_mission_document import canonical_json
    return sha256(canonical_json(dict(domain='B45_REGULATED_STAR_V1',value=_scientific(value))).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ReceivingBranch:
    component: ElectricalLoadComponent
    line_id: str
    def __post_init__(self):
        if type(self.component) is not ElectricalLoadComponent:raise TypeError('exact load component required')
        _identity(self.line_id,'receiving line')


@dataclass(frozen=True, slots=True)
class ConstructionConfiguration:
    assembly_digest: str
    body_frame_id: str
    bus_instance_id: str
    bus_voltage_v: float
    bus_current_limit_a: float
    pv_source_voltage_v: float
    pv_line_id: str
    ports: tuple[ElectricalPort,...]
    lines: tuple[LineConnection,...]
    receiving: tuple[ReceivingBranch,...]
    thermal_bindings: tuple[ThermalBinding,...]
    thermal_network: object
    thermal_boundaries: ThermalIntervalInputs
    rationale: str
    topology: str = 'IDEAL_REGULATED_SINGLE_BUS_STAR_V1'
    generation_model: str = 'SOURCE_CURRENT_P_OVER_V_AVAILABLE_PV_V1'
    regulator_loss_model: str = 'IDEAL_ZERO_LOSS_V1'
    def __post_init__(self):
        if type(self.assembly_digest) is not str or len(self.assembly_digest)!=64 or any(c not in '0123456789abcdef' for c in self.assembly_digest):raise ValueError('assembly digest')
        for name in ('body_frame_id','bus_instance_id','pv_line_id','rationale'):_identity(getattr(self,name),name)
        for name in ('bus_voltage_v','bus_current_limit_a','pv_source_voltage_v'):
            object.__setattr__(self,name,_positive(getattr(self,name),name))
        for name in ('topology','generation_model','regulator_loss_model'):_identity(getattr(self,name),name)
        if self.topology!='IDEAL_REGULATED_SINGLE_BUS_STAR_V1' or self.generation_model!='SOURCE_CURRENT_P_OVER_V_AVAILABLE_PV_V1' or self.regulator_loss_model!='IDEAL_ZERO_LOSS_V1':raise ValueError('unsupported topology/converter/source model')
        for name,owner,key,cap in (('ports',ElectricalPort,'port_id',64),('lines',LineConnection,'line_id',64),('receiving',ReceivingBranch,'component',7),('thermal_bindings',ThermalBinding,'instance_id',32)):
            values=getattr(self,name)
            if type(values) is not tuple or not 1<=len(values)<=cap:raise ValueError(name+' bounded tuple required')
            if any(type(v) is not owner for v in values):raise TypeError('exact '+owner.__name__+' required')
            values=tuple(replace(v) for v in values)
            if len({getattr(v,key) for v in values})!=len(values):raise ValueError('duplicate '+name)
            object.__setattr__(self,name,tuple(sorted(values,key=lambda v:str(getattr(v,key)))))
        if type(self.thermal_network) is not ThermalNetworkConfig:raise TypeError('exact thermal network required')
        if len(self.thermal_network.nodes)>64 or len(self.thermal_network.links)>256:raise ValueError('bounded thermal graph')
        object.__setattr__(self,'thermal_network',_network(self.thermal_network))
        if type(self.thermal_boundaries) is not ThermalIntervalInputs:raise TypeError('thermal boundaries required')
        object.__setattr__(self,'thermal_boundaries',canonical_copy(self.thermal_boundaries))
        nodes={n.node_id.value for n in self.thermal_network.nodes}
        if {n.node_id.value for n in self.thermal_boundaries.node_boundaries}!=nodes:raise ValueError('complete thermal boundaries required')
        if {b.component for b in self.receiving}!=set(ElectricalLoadComponent):raise ValueError('complete receiving component ownership')
        lines={l.line_id:l for l in self.lines};ports={p.port_id:p for p in self.ports}
        if {b.line_id for b in self.receiving}|{self.pv_line_id}!=set(lines) or len(lines)!=8:raise ValueError('one PV and seven independently owned load branches required')
        endpoints=[];used=set()
        for line in self.lines:
            if len(line.waypoints_body_m)>64:raise ValueError('route waypoint cap')
            if line.source_port_id not in ports or line.load_port_id not in ports:raise ValueError('unknown port')
            a,b=ports[line.source_port_id],ports[line.load_port_id]
            if a.role!='SOURCE' or b.role!='LOAD':raise ValueError('source/load endpoint roles')
            if line.line_id==self.pv_line_id:
                if a.instance_id==self.bus_instance_id or b.instance_id!=self.bus_instance_id:raise ValueError('PV source must terminate at bus')
            elif a.instance_id!=self.bus_instance_id:raise ValueError('cross-fed/cascaded/loop topology unsupported')
            if line.operating_point.power_w!=0:raise ValueError('static operating point is not dynamic authority; use zero declaration')
            if line.mass.status not in ('INCLUDED','EXCLUDED'):raise ValueError('explicit harness mass boundary required')
            if line.wire_loss_node_id not in nodes:raise ValueError('missing/unknown wire heat destination')
            if a.port_id in used or b.port_id in used:raise ValueError('each port belongs to exactly one branch')
            used.update((a.port_id,b.port_id));endpoints.extend((a.instance_id,b.instance_id))
        if used!=set(ports):raise ValueError('unused port')
        bindings={b.instance_id:b for b in self.thermal_bindings}
        if not set(endpoints)<=set(bindings) or any(b.node_id not in nodes for b in bindings.values()):raise ValueError('missing instance thermal binding')
        for a,b in combinations(self.thermal_bindings,2):
            if a.node_id==b.node_id and (a.lumping_group is None or a.lumping_group!=b.lumping_group):raise ValueError('explicit thermal lumping required')
            if a.lumping_group is not None and a.lumping_group==b.lumping_group and a.node_id!=b.node_id:raise ValueError('lumping group spans nodes')


@dataclass(frozen=True, slots=True)
class CompiledBranch:
    line_id: str
    source_body_m: tuple
    load_body_m: tuple
    polyline_length_m: float
    wire: object
    heat_node_id: str
    mass_status: str


@dataclass(frozen=True, slots=True)
class ConstructionCompilation:
    configuration: ConstructionConfiguration
    configuration_digest: str
    branches: tuple[CompiledBranch,...]
    conductor_mass_kg: float
    connector_mass_kg: float
    mass_scope: str


def compile_construction(design, configuration):
    if type(configuration) is not ConstructionConfiguration:raise TypeError('construction configuration required')
    configuration=replace(configuration)
    if assembly_document_digest(design)!=configuration.assembly_digest or design.body_frame_id!=configuration.body_frame_id:raise ValueError('stale assembly/interface binding')
    if len(design.instances)>32:raise ValueError('assembly instance cap')
    assessment=assess_design(design)
    if not assessment.qualified or assessment.mass_accounting_status!='CHECKED_DECLARATIONS' or assessment.installation_status!='CHECKED_DECLARATIONS':raise ValueError('qualified declared assembly required')
    components={c.component_id:c for c in assessment.assembly.components}
    ports={p.port_id:p for p in configuration.ports}
    instances={i.instance_id:i for i in design.instances}
    for p in configuration.ports:
        if p.instance_id not in components or p.local_frame_id!=components[p.instance_id].definition.local_frame_id:raise ValueError('foreign local port frame/instance')
    if any(b.instance_id not in instances for b in configuration.thermal_bindings):raise ValueError('foreign thermal instance')
    for line in configuration.lines:
        claim=line.mass
        if claim.status=='INCLUDED':
            if claim.included_instance_id not in instances:raise ValueError('foreign mass owner')
            owner=instances[claim.included_instance_id].mass_coverage
            if owner is None or any(not any(p[:len(q)]==q for q in owner.paths) for p in claim.coverage.paths):raise ValueError('harness not covered by included owner')
        else:
            if any(i.mass_coverage is not None and any(_overlap(p,q) for p in claim.coverage.paths for q in i.mass_coverage.paths) for i in design.instances):raise ValueError('excluded harness already assembled')
    for a,b in combinations(configuration.lines,2):
        if any(_overlap(p,q) for p in a.mass.coverage.paths for q in b.mass.coverage.paths):raise ValueError('overlapping harness mass claims')
    branches=[]
    for line in configuration.lines:
        a,b=ports[line.source_port_id],ports[line.load_port_id]
        start,end=_port_body(a,components[a.instance_id]),_port_body(b,components[b.instance_id])
        points=(start,*line.waypoints_body_m,end)
        length=fsum(dist(a,b) for a,b in zip(points,points[1:]))
        wire=line.wire.at_length(length+line.slack_m)
        branches.append(CompiledBranch(line.line_id,start,end,length,wire,line.wire_loss_node_id,line.mass.status))
    return ConstructionCompilation(configuration,digest(configuration),tuple(branches),
        fsum(b.wire.conductor_mass_kg for b in branches),fsum(b.wire.connector_total_mass_kg for b in branches),
        'DECLARED_INCLUDED_NO_NUMERICAL_MASS_CLOSURE' if all(b.mass_status=='INCLUDED' for b in branches) else 'NOT_MASS_CLOSED_EXCLUDED_HARNESS')
