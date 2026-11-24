"""Static assembly adapters; existing electrical/thermal owners retain physics.

See M1_ASSEMBLY_INTERFACES.md. A usable compilation is a static diagnostic,
not a mission power grant, a thermal transition, or hardware mass closure.
"""

from dataclasses import dataclass, fields, replace
from itertools import combinations
from math import dist, fsum

from .assembly import MassCoverage, Vector3, _identity, _overlap, _real, _vector
from .assembly_choices import AssemblyDesign, DesignAssessment, _copy, _records, assess_design
from .assembly_document import assembly_document_digest
from .design_trade_physics import (
    ElectricalLimitError, ElectricalLineResult, WireSpec, constant_power_load, generated_power_line,
)
from .experiment_codec import canonical_copy
from .ids import ThermalNodeId
from .thermal import ThermalAppliedHeatInputs, ThermalIntervalInputs, ThermalNodeAppliedHeatInput
from .thermal_config import ThermalNetworkConfig


def _digest(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('digest must be a lowercase SHA-256 hex string')
    return value


def _enum(value, options, name):
    _identity(value, name)
    if value not in options:
        raise ValueError(f'unsupported {name}: {value}')


def _nonnegative(value, name):
    value = _real(value, name)
    if value < 0:
        raise ValueError(f'{name} must be nonnegative')
    return value


@dataclass(frozen=True, slots=True)
class ElectricalPort:
    port_id: str
    instance_id: str
    local_frame_id: str
    position_local_m: Vector3
    role: str

    def __post_init__(self):
        for name in ('port_id', 'instance_id', 'local_frame_id'):
            _identity(getattr(self, name), name)
        _enum(self.role, ('SOURCE', 'LOAD'), 'port role')
        object.__setattr__(self, 'position_local_m', _vector(self.position_local_m, 'local port'))


@dataclass(frozen=True, slots=True)
class WireProperties:
    """WireSpec's authored properties; length is deliberately absent."""
    cross_section_m2: float
    resistivity_ohm_m: float
    density_kg_m3: float
    connector_resistance_ohm: float
    connector_count: int
    connector_mass_kg: float
    current_limit_a: float
    max_drop_v: float

    def __post_init__(self):
        spec = WireSpec(0.0, **{f.name: getattr(self, f.name) for f in fields(self)})
        for f in fields(self):
            object.__setattr__(self, f.name, getattr(spec, f.name))

    def at_length(self, length_m):
        admitted = _copy(self, WireProperties)
        return WireSpec(length_m, **{f.name: getattr(admitted, f.name) for f in fields(admitted)})


@dataclass(frozen=True, slots=True)
class OperatingPoint:
    mode: str
    source_voltage_v: float
    power_w: float

    def __post_init__(self):
        _enum(self.mode, ('CONSTANT_LOAD', 'GENERATED'), 'line mode')
        voltage = _real(self.source_voltage_v, 'source voltage')
        if voltage <= 0:
            raise ValueError('source voltage must be positive')
        object.__setattr__(self, 'source_voltage_v', voltage)
        object.__setattr__(self, 'power_w', _nonnegative(self.power_w, 'operating power'))


@dataclass(frozen=True, slots=True)
class HarnessMassDeclaration:
    status: str
    coverage: MassCoverage | None
    included_instance_id: str | None

    def __post_init__(self):
        _enum(self.status, ('INCLUDED', 'EXCLUDED', 'UNSPECIFIED'), 'harness mass status')
        if self.status == 'UNSPECIFIED':
            if self.coverage is not None or self.included_instance_id is not None:
                raise ValueError('unspecified harness mass cannot claim an owner or coverage')
        else:
            object.__setattr__(self, 'coverage', _copy(self.coverage, MassCoverage))
            if self.status == 'INCLUDED':
                _identity(self.included_instance_id, 'included mass owner')
            elif self.included_instance_id is not None:
                raise ValueError('excluded harness mass cannot name an included owner')


@dataclass(frozen=True, slots=True)
class LineConnection:
    line_id: str
    source_port_id: str
    load_port_id: str
    waypoints_body_m: tuple[Vector3, ...]
    slack_m: float
    wire: WireProperties
    operating_point: OperatingPoint
    mass: HarnessMassDeclaration
    wire_loss_node_id: str | None

    def __post_init__(self):
        for name in ('line_id', 'source_port_id', 'load_port_id'):
            _identity(getattr(self, name), name)
        if self.source_port_id == self.load_port_id:
            raise ValueError('line endpoints must be distinct')
        if type(self.waypoints_body_m) is not tuple:
            raise TypeError('waypoints require an exact ordered tuple')
        object.__setattr__(self, 'waypoints_body_m', tuple(_vector(v, 'waypoint') for v in self.waypoints_body_m))
        object.__setattr__(self, 'slack_m', _nonnegative(self.slack_m, 'slack'))
        for name, owner in (('wire', WireProperties), ('operating_point', OperatingPoint),
                            ('mass', HarnessMassDeclaration)):
            object.__setattr__(self, name, _copy(getattr(self, name), owner))
        if self.wire_loss_node_id is not None:
            _identity(self.wire_loss_node_id, 'wire loss node')
            ThermalNodeId(self.wire_loss_node_id)


@dataclass(frozen=True, slots=True)
class ThermalBinding:
    instance_id: str
    node_id: str
    lumping_group: str | None

    def __post_init__(self):
        _identity(self.instance_id, 'thermal instance')
        _identity(self.node_id, 'thermal node')
        ThermalNodeId(self.node_id)
        if self.lumping_group is not None:
            _identity(self.lumping_group, 'lumping group')


def _network(value):
    if type(value) is not ThermalNetworkConfig:
        raise TypeError('exact ThermalNetworkConfig required')
    # Revalidate every nested parameter/provenance/ID, then canonicalize sets.
    value = canonical_copy(value)
    def parameter(p):
        return replace(p, provenance=replace(p.provenance,
            source_ids=tuple(sorted(p.provenance.source_ids, key=lambda s: s.value))))
    nodes = tuple(replace(n, **{f.name: parameter(getattr(n, f.name))
                  for f in fields(n) if f.name != 'node_id'}) for n in value.nodes)
    links = tuple(replace(l, conductance_w_per_k=parameter(l.conductance_w_per_k)) for l in value.links)
    return replace(value, nodes=tuple(sorted(nodes, key=lambda n: n.node_id.value)),
                   links=tuple(sorted(links, key=lambda l: l.link_id.value)))


@dataclass(frozen=True, slots=True)
class AssemblyInterfaces:
    assembly_digest: str
    body_frame_id: str
    ports: tuple[ElectricalPort, ...]
    lines: tuple[LineConnection, ...]
    thermal_bindings: tuple[ThermalBinding, ...]
    thermal_network: ThermalNetworkConfig | None
    thermal_boundaries: ThermalIntervalInputs | None
    supply_assumption: str
    supply_rationale: str

    def __post_init__(self):
        _digest(self.assembly_digest)
        _identity(self.body_frame_id, 'body frame')
        _enum(self.supply_assumption, ('IDEAL_INDEPENDENT_SOURCES',), 'supply assumption')
        _identity(self.supply_rationale, 'supply rationale')
        for name, owner, key in (('ports', ElectricalPort, 'port_id'),
                                  ('lines', LineConnection, 'line_id'),
                                  ('thermal_bindings', ThermalBinding, 'instance_id')):
            object.__setattr__(self, name, _records(getattr(self, name), owner, key))
        if self.thermal_network is not None:
            object.__setattr__(self, 'thermal_network', _network(self.thermal_network))
        if self.thermal_boundaries is not None:
            if type(self.thermal_boundaries) is not ThermalIntervalInputs:
                raise TypeError('exact ThermalIntervalInputs required')
            boundaries = canonical_copy(self.thermal_boundaries)
            object.__setattr__(self, 'thermal_boundaries', replace(boundaries,
                node_boundaries=tuple(sorted(boundaries.node_boundaries, key=lambda n: n.node_id.value))))
        ports = {p.port_id: p for p in self.ports}
        pairs = set()
        for line in self.lines:
            if line.source_port_id not in ports or line.load_port_id not in ports:
                raise ValueError('missing line endpoint')
            a, b = ports[line.source_port_id], ports[line.load_port_id]
            if a.role != 'SOURCE' or b.role != 'LOAD' or a.instance_id == b.instance_id:
                raise ValueError('incompatible source/load ports')
            pair = (a.port_id, b.port_id)
            if pair in pairs:
                raise ValueError('ambiguous duplicate connection')
            pairs.add(pair)
        if self.thermal_network is not None:
            nodes = {n.node_id.value for n in self.thermal_network.nodes}
            references = [b.node_id for b in self.thermal_bindings]
            references += [l.wire_loss_node_id for l in self.lines if l.wire_loss_node_id is not None]
            if self.thermal_boundaries is not None:
                references += [b.node_id.value for b in self.thermal_boundaries.node_boundaries]
            if any(n not in nodes for n in references):
                raise ValueError('unknown thermal node reference')
        for a, b in combinations(self.thermal_bindings, 2):
            if a.lumping_group is not None and a.lumping_group == b.lumping_group and a.node_id != b.node_id:
                raise ValueError('one lumping group cannot denote different nodes')


def validate_binding(design: AssemblyDesign, interfaces: AssemblyInterfaces):
    """Malformed/stale inputs fail before any feasibility or physics calculation."""
    design, interfaces = _copy(design, AssemblyDesign), _copy(interfaces, AssemblyInterfaces)
    if assembly_document_digest(design) != interfaces.assembly_digest:
        raise ValueError('assembly document digest mismatch')
    if interfaces.body_frame_id != design.body_frame_id:
        raise ValueError('interface body frame mismatch')
    instances = {i.instance_id: i for i in design.instances}
    definitions = {d.definition_id: d for d in design.definitions}
    for p in interfaces.ports:
        if p.instance_id not in instances:
            raise ValueError('unknown port instance')
        if p.local_frame_id != definitions[instances[p.instance_id].definition_id].local_frame_id:
            raise ValueError('port local frame mismatch')
    for binding in interfaces.thermal_bindings:
        if binding.instance_id not in instances:
            raise ValueError('unknown thermal instance')
    for line in interfaces.lines:
        owner = line.mass.included_instance_id
        if owner is not None and owner not in instances:
            raise ValueError('unknown included mass owner')
    return design, interfaces


@dataclass(frozen=True, slots=True)
class InterfaceIssue:
    category: str
    code: str
    affected_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class LineDiagnostic:
    line_id: str
    source_body_m: Vector3
    load_body_m: Vector3
    polyline_length_m: float
    wire: WireSpec
    electrical: ElectricalLineResult
    harness_mass_status: str
    wire_loss_node_id: str | None


@dataclass(frozen=True, slots=True)
class SubsystemCompilation:
    assembly_digest: str
    lines: tuple[LineDiagnostic, ...]
    thermal_network: ThermalNetworkConfig
    thermal_boundaries: ThermalIntervalInputs
    wire_loss_heat: ThermalAppliedHeatInputs
    heat_accounting_boundary: str = 'WIRE_LOSS_ONLY_STATIC_OPERATING_POINT'


@dataclass(frozen=True, slots=True)
class InterfaceAssessment:
    assembly_assessment: DesignAssessment
    issues: tuple[InterfaceIssue, ...]
    line_diagnostics: tuple[LineDiagnostic, ...]
    compilation: SubsystemCompilation | None


def _port_body(port, component):
    offset = tuple(_real(port.position_local_m[i] - component.definition.center_local_m[i],
                         'port local offset') for i in range(3))
    try:
        return _vector(tuple(component.center_body_m[i] + fsum(
            component.rotation_body_from_local[i][j] * offset[j] for j in range(3))
            for i in range(3)), 'body port')
    except (OverflowError, ValueError) as exc:
        raise ValueError('port transform exceeds finite arithmetic domain') from exc


def compile_interfaces(design: AssemblyDesign, interfaces: AssemblyInterfaces) -> InterfaceAssessment:
    design, interfaces = validate_binding(design, interfaces)
    assessment = assess_design(design)
    issues = []
    def issue(category, code, ids=(), detail=''):
        issues.append(InterfaceIssue(category, code, tuple(ids), detail))
    for v in assessment.violations:
        issue('CONSTRAINT', 'ASSEMBLY_' + v.code, v.component_ids + v.choice_ids, repr(v.resource_ids))
    if assessment.installation_status != 'CHECKED_DECLARATIONS' or assessment.mass_accounting_status != 'CHECKED_DECLARATIONS':
        issue('INCOMPLETE', 'ASSEMBLY_DECLARATIONS_INCOMPLETE')
    ports = {p.port_id: p for p in interfaces.ports}
    used_ports, instance_lines = set(), {}
    for line in interfaces.lines:
        for pid in (line.source_port_id, line.load_port_id):
            used_ports.add(pid)
            instance_lines.setdefault(ports[pid].instance_id, []).append(line.line_id)
    unsupported = False
    for iid, lines in sorted(instance_lines.items()):
        if len(lines) > 1:
            unsupported = True
            issue('UNSUPPORTED', 'SHARED_INSTANCE_TOPOLOGY', (iid, *lines))
    for pid in sorted(set(ports) - used_ports):
        issue('INCOMPLETE', 'UNCONNECTED_PORT', (pid,))
    bindings = {b.instance_id: b for b in interfaces.thermal_bindings}
    for iid in sorted({p.instance_id for p in interfaces.ports} - set(bindings)):
        issue('INCOMPLETE', 'MISSING_INSTANCE_THERMAL_BINDING', (iid,))
    for a, b in combinations(interfaces.thermal_bindings, 2):
        if a.node_id == b.node_id and (a.lumping_group is None or a.lumping_group != b.lumping_group):
            issue('INCOMPLETE', 'UNDECLARED_THERMAL_LUMPING', (a.instance_id, b.instance_id, a.node_id))
    network = interfaces.thermal_network
    if network is None:
        issue('INCOMPLETE', 'MISSING_THERMAL_NETWORK')
    nodes = set() if network is None else {n.node_id.value for n in network.nodes}
    boundaries = interfaces.thermal_boundaries
    if boundaries is None:
        issue('INCOMPLETE', 'MISSING_THERMAL_BOUNDARIES')
    elif network is not None:
        missing = nodes - {b.node_id.value for b in boundaries.node_boundaries}
        for nid in sorted(missing):
            issue('INCOMPLETE', 'MISSING_NODE_BOUNDARY', (nid,))
    instances = {i.instance_id: i for i in design.instances}
    for line in interfaces.lines:
        if line.wire_loss_node_id is None:
            issue('INCOMPLETE', 'MISSING_WIRE_HEAT_DESTINATION', (line.line_id,))
        mass = line.mass
        if mass.status == 'UNSPECIFIED':
            issue('INCOMPLETE', 'UNSPECIFIED_HARNESS_MASS', (line.line_id,))
        elif mass.status == 'INCLUDED':
            owner = instances[mass.included_instance_id].mass_coverage
            if owner is None or any(not any(p[:len(q)] == q for q in owner.paths) for p in mass.coverage.paths):
                issue('CONSTRAINT', 'HARNESS_NOT_COVERED_BY_OWNER', (line.line_id, mass.included_instance_id))
        else:
            for instance in design.instances:
                if instance.mass_coverage is not None and any(_overlap(p, q)
                    for p in mass.coverage.paths for q in instance.mass_coverage.paths):
                    issue('CONSTRAINT', 'EXCLUDED_HARNESS_ALREADY_ASSEMBLED', (line.line_id, instance.instance_id))
    for a, b in combinations(interfaces.lines, 2):
        if a.mass.coverage is not None and b.mass.coverage is not None and any(
            _overlap(p, q) for p in a.mass.coverage.paths for q in b.mass.coverage.paths):
            issue('CONSTRAINT', 'HARNESS_MASS_OVERLAP', (a.line_id, b.line_id))
    diagnostics = []
    if assessment.qualified and not unsupported:
        components = {c.component_id: c for c in assessment.assembly.components}
        for line in interfaces.lines:
            a, b = ports[line.source_port_id], ports[line.load_port_id]
            start, end = _port_body(a, components[a.instance_id]), _port_body(b, components[b.instance_id])
            points = (start, *line.waypoints_body_m, end)
            try:
                length = _nonnegative(fsum(dist(a, b) for a, b in zip(points, points[1:])), 'polyline length')
                wire = line.wire.at_length(_nonnegative(length + line.slack_m, 'one way length'))
            except OverflowError as exc:
                raise ValueError('route exceeds finite arithmetic domain') from exc
            point = line.operating_point
            evaluate = constant_power_load if point.mode == 'CONSTANT_LOAD' else generated_power_line
            try:
                result = evaluate(wire, point.source_voltage_v, point.power_w)
            except ElectricalLimitError as exc:
                issue('CONSTRAINT', 'ELECTRICAL_LIMIT', (line.line_id,), str(exc))
                continue
            diagnostics.append(LineDiagnostic(line.line_id, start, end, length, wire, result,
                                              line.mass.status, line.wire_loss_node_id))
    ordered = tuple(sorted(issues, key=lambda i: (i.category, i.code, i.affected_ids, i.detail)))
    diagnostics = tuple(diagnostics)
    compilation = None
    if not ordered:
        heat = ThermalAppliedHeatInputs(tuple(ThermalNodeAppliedHeatInput(ThermalNodeId(nid),
            _nonnegative(fsum(d.electrical.loss_w for d in diagnostics if d.wire_loss_node_id == nid),
                         'node wire heat')) for nid in sorted(nodes)))
        compilation = SubsystemCompilation(interfaces.assembly_digest, diagnostics, network, boundaries, heat)
    return InterfaceAssessment(assessment, ordered, diagnostics, compilation)
