"""Explicit parts+resolved-route lumped capacity; never caller-supplied mass.

Two constructor units are spent BEFORE either pass. The first pass's private
one-unit ledger is a local receipt nested inside that prepayment, not additional
authority or a refund. Final construction/hardware are genuinely recompiled.
"""
from dataclasses import dataclass,replace,asdict
from fractions import Fraction
from hashlib import sha256
from math import fsum
from .assembly import _identity
from .spacecraft_design import DesignSpecification,DesignProvenance,admit_design,number,_derived
from .design_repair import ConstructorLedger
from .lifecycle_contract import LifecycleRoot,canonical,static_admission
from .construction_coupling import compile_construction
from .harness_mass import geometry_digest
from .harness_hardware import compile_effective_hardware
from .rolling_physics import digest

METHOD='B68_DECLARED_PARTS_AND_RESOLVED_ROUTE_CAPACITY_V1'

@dataclass(frozen=True,slots=True)
class RouteThermalDeclaration:
    line_id:str
    thermal_node_id:str
    specific_heat_j_per_kg_k:float
    provenance:DesignProvenance
    def __post_init__(self):
        _identity(self.line_id,'route line');_identity(self.thermal_node_id,'capacity destination')
        number(self.specific_heat_j_per_kg_k,'route specific heat J/(kg K)',1e-12,1e8)
        if type(self.provenance)is not DesignProvenance:raise TypeError('exact route provenance')
        self.provenance.__post_init__()

@dataclass(frozen=True,slots=True)
class DesignSpecificationV2:
    base:DesignSpecification
    route_thermal:tuple
    method:str=METHOD
    def __post_init__(self):
        if type(self.base)is not DesignSpecification:raise TypeError('exact parts-only base specification')
        self.base.__post_init__()
        if type(self.method)is not str or self.method!=METHOD:raise ValueError('explicit route capacity method')
        if type(self.route_thermal)is not tuple or len(self.route_thermal)!=8:raise ValueError('exact eight route declarations')
        for d in self.route_thermal:
            if type(d)is not RouteThermalDeclaration:raise TypeError('exact route declaration')
            d.__post_init__()
        lines={d.line_id for d in self.route_thermal}
        if len(lines)!=8 or lines!={line.line_id for line in self.base.configuration.lines}:raise ValueError('missing/duplicate/foreign route declaration')
        nodes={n.node_id.value for n in self.base.configuration.thermal_network.nodes}
        if any(d.thermal_node_id not in nodes for d in self.route_thermal):raise ValueError('foreign capacity destination')
        object.__setattr__(self,'route_thermal',tuple(sorted(self.route_thermal,key=lambda d:d.line_id)))
    @property
    def declaration_identity(self):
        data=[dict(line_id=d.line_id,thermal_node_id=d.thermal_node_id,cp_hex=d.specific_heat_j_per_kg_k.hex(),provenance=asdict(d.provenance))for d in self.route_thermal]
        return sha256(canonical(dict(method=METHOD,declarations=data)).encode()).hexdigest()
    @property
    def identity(self):
        from .spacecraft_project_v3_document import specification_data
        return sha256(canonical(specification_data(self)).encode()).hexdigest()

def constructor_compile_bound(spec):
    if type(spec)is DesignSpecificationV2:return 2
    if type(spec)is DesignSpecification:return 1
    raise TypeError('exact supported specification for constructor bound')

@dataclass(frozen=True,slots=True)
class RouteThermalCompilation:
    declaration_identity:str
    route_mass_identity:str
    per_line:tuple
    groups:tuple
    base_capacities:tuple
    route_capacities:tuple
    final_capacities:tuple
    assembly_digest:str
    construction_digest:str
    augmentation_identity:str
    root_identity:str
    method:str=METHOD
    def as_data(self):
        q=lambda v:[str(v.numerator),str(v.denominator)]
        return dict(method=self.method,declaration_identity=self.declaration_identity,route_mass_identity=self.route_mass_identity,
            per_line=[dict(line_id=l,mass_exact_kg=q(m),thermal_node_id=n,cp_hex=c)for l,m,n,c in self.per_line],
            groups=[dict(thermal_node_id=n,cp_hex=c,mass_exact_kg=q(m),capacity_hex=v.hex())for n,c,m,v in self.groups],
            base_capacities=dict(self.base_capacities),route_capacities=dict(self.route_capacities),final_capacities=dict(self.final_capacities),
            assembly_digest=self.assembly_digest,construction_digest=self.construction_digest,augmentation_identity=self.augmentation_identity,root_identity=self.root_identity,
            units=dict(mass='kg exact rational',capacity='J/K',cp='J/(kg K)'),scope='DERIVED_OUTPUT_NOT_IMPORTABLE_AUTHORITY')

@dataclass(frozen=True,slots=True)
class DesignAdmissionV2:
    root:LifecycleRoot
    construction:object
    hardware:object
    specification_identity:str
    common_identity:str
    derived:tuple
    route_thermal:RouteThermalCompilation
    method:str=METHOD

def _resolved_masses(hardware):
    """Both independent authenticated closure views must agree exactly."""
    a=hardware.augmentation
    masses={line:Fraction(0)for line,*_ in a.route_closure}
    if len(masses)!=8 or len(a.route_closure)!=8:raise ValueError('genuine eight-route closure required')
    for c in a.contributions:
        if c.line_id not in masses or type(c.mass_kg)is not Fraction:raise ValueError('foreign route mass contribution')
        masses[c.line_id]+=c.mass_kg
    for line,conductor,connector,allocated,count,points in a.route_closure:
        if masses[line]!=allocated or allocated!=conductor+connector:raise ValueError('per-line exact route closure')
    if sum(masses.values(),Fraction(0))!=a.added_mass_exact_kg:raise ValueError('total exact route mass closure')
    return masses

def admit_design_v2(spec,common,ledger):
    if type(spec)is not DesignSpecificationV2 or type(common)is not LifecycleRoot or type(ledger)is not ConstructorLedger:raise TypeError('exact route design/common/ledger')
    spec.__post_init__();common.__post_init__()
    # No geometry or first pass precedes the complete conservative prepayment.
    ledger.reserve();ledger.reserve()
    first=admit_design(spec.base,common,ConstructorLedger(maximum_compiles=1))
    masses=_resolved_masses(first.hardware)
    declarations={d.line_id:d for d in spec.route_thermal}
    grouped={}
    for line in sorted(masses):
        d=declarations[line];key=(d.thermal_node_id,d.specific_heat_j_per_kg_k.hex())
        grouped[key]=grouped.get(key,Fraction(0))+masses[line]
    groups=tuple((node,cp,mass,float(mass)*float.fromhex(cp))for (node,cp),mass in sorted(grouped.items()))
    network=first.root.base.model.configuration.thermal_network
    base_c={n.node_id.value:n.heat_capacity_j_per_k.value for n in network.nodes}
    route_c={node:fsum(v for n,cp,m,v in groups if n==node)for node in sorted(base_c)}
    final_c={node:base_c[node]+route_c[node]for node in sorted(base_c)}
    mass_identity=digest((tuple(sorted(masses.items())),first.hardware.augmentation.contributions))
    nodes=[]
    for node in network.nodes:
        parameter=_derived(node.heat_capacity_j_per_k,final_c[node.node_id.value],
            METHOD+'; parts fsum + fsum(sorted exact-mass/cp groups); declaration='+spec.declaration_identity+'; resolved_routes='+mass_identity,
            tuple(d.provenance for d in spec.route_thermal))
        parameter=replace(parameter,provenance=replace(parameter.provenance,rationale='B68 authored effective route cp includes conductor/slack/connectors; lumped capacity destination is independent of loss destination; not calibrated hardware truth.'))
        nodes.append(replace(node,heat_capacity_j_per_k=parameter))
    network=replace(network,nodes=tuple(nodes))
    model=first.root.base.model
    cfg=replace(model.configuration,thermal_network=network)
    construction=compile_construction(spec.base.assembly,cfg)
    branches={b.line_id:b for b in construction.branches};lines={l.line_id:l for l in cfg.lines}
    augmentation=replace(model.augmentation,construction_digest=construction.configuration_digest,
        routes=tuple(replace(r,geometry_digest=geometry_digest(branches[r.line_id],lines[r.line_id]))for r in model.augmentation.routes))
    hardware=compile_effective_hardware(spec.base.assembly,spec.base.capabilities,spec.base.actuator,cfg,augmentation)
    if _resolved_masses(hardware)!=masses:raise ValueError('thermal capacity cannot change mechanical route masses')
    for before,after in ((first.hardware.mass_properties,hardware.mass_properties),
                         (first.hardware.augmentation.contributions,hardware.augmentation.contributions),
                         (first.construction.branches,construction.branches),
                         (first.hardware.tensor_exact,hardware.tensor_exact)):
        if digest(before)!=digest(after):raise ValueError('thermal-only second pass changed mechanics/electrical routes')
    sim=model.simulation_inputs;sc=sim.spacecraft_configuration
    sim=replace(sim,spacecraft_configuration=replace(sc,thermal=replace(sc.thermal,network=network)))
    model=replace(model,configuration=cfg,augmentation=augmentation,simulation_inputs=sim)
    base=first.root.base;base=replace(base,reference=replace(base.reference,model=model))
    study=first.root.study
    if study is not None:
        from .lifecycle_study import _roles
        roles=_roles(network)
        study=replace(study,nodes=tuple(replace(n,heat_capacity_j_per_k=final_c[roles[n.role].value])for n in study.nodes))
    root=replace(first.root,base=base,study=study)
    if root.environment_ageing_policy is not None:
        from .environment_ageing import admit_network
        admit_network(network,root.environment_ageing_policy)
    static_admission(root)
    audit=RouteThermalCompilation(spec.declaration_identity,mass_identity,
        tuple((line,masses[line],declarations[line].thermal_node_id,declarations[line].specific_heat_j_per_kg_k.hex())for line in sorted(masses)),
        groups,tuple(sorted(base_c.items())),tuple(sorted(route_c.items())),tuple(sorted(final_c.items())),
        cfg.assembly_digest,construction.configuration_digest,digest(hardware.augmentation),root.identity)
    return DesignAdmissionV2(root,construction,hardware,spec.identity,common.identity,first.derived,audit)

def admit_compiled_design_v2(spec,common,proposed_root,ledger):
    result=admit_design_v2(spec,common,ledger)
    from .lifecycle_document import dumps_root
    if type(proposed_root)is not LifecycleRoot or dumps_root(proposed_root)!=dumps_root(result.root):raise ValueError('B68_COMPILED_ROUTE_THERMAL_SPECIFICATION_OR_COMMON_MISMATCH')
    return result
