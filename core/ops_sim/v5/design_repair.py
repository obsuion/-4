"""Finite input-only M7 edits; accepted M1/M4 owners derive all hardware.

This first domain is the authored B42/B47 two-battery construction, with its
declared bracket detour and endpoint connectors. It is not a routing solver.
"""
from dataclasses import dataclass, replace, fields
from hashlib import sha256
from pathlib import Path
from .rolling_contract import integer, finite
from .command_estimation import CommandRollingRoot
from .rolling_physics import digest
from .assembly_document import assembly_document_digest
from .assembly_choices import InstallationBox
from .construction_coupling import compile_construction
from .harness_mass import geometry_digest, SpatialMassPoint
from .harness_hardware import compile_effective_hardware

METHOD = 'M7_FINITE_BATTERY_PLACEMENT_PAYLOAD_AREA_V1'
SELECTION = 'FEASIBLE_THEN_ADDED_MASS_THEN_ACTUATOR_AND_WIRE_ENERGY_THEN_ID_V1'
# Exact authored numeric transforms: examples/m3_spatial_constructor_mission_demo.py.
# Rotations, mount/slot identities, definitions and mass coverage stay unchanged.
PLACEMENTS = {
    'compact': ((-.25, -.15, .1), (.25, .15, -.1)),
    'outboard': ((-.7, -.15, .1), (.7, .15, -.1)),
}
BATTERIES = ('battery-left', 'battery-right')


def source_identity():
    """Actual local Python owner/constructor binding, excluding deferred input.

    The complete review snapshot supplies the broader file manifest. This
    runtime binding deliberately excludes docs, tests and generated results.
    """
    root = Path(__file__).resolve().parents[2]
    names = sorted(p.relative_to(root).as_posix() for folder in ('ops_sim', 'examples')
        for p in (root / folder).rglob('*.py')
        if '__pycache__' not in p.parts and p.name != 'scenario_inputs.py')
    if not 1 <= len(names) <= 1024:
        raise ValueError('bounded source binding population')
    body = '\n'.join(n + ':' + sha256((root / n).read_bytes()).hexdigest() for n in names)
    return sha256(body.encode()).hexdigest()


def hash_identity(v):
    if type(v) is not str or len(v) != 64 or any(c not in '0123456789abcdef' for c in v):
        raise ValueError('exact lowercase SHA-256 identity')
    return v


def selected_battery_choices(design):
    selections = {s.instance_id: s.choice_id for s in design.selections}
    choices = {c.choice_id: c for c in design.choices}
    if not set(BATTERIES) <= set(selections):
        raise ValueError('declared two-battery domain required')
    return tuple(choices[selections[n]] for n in BATTERIES)


def placement_name(design):
    choices = selected_battery_choices(design)
    origins = tuple(c.pose.origin_body_m for c in choices)
    name = next((n for n, p in PLACEMENTS.items() if origins == p), None)
    if name is None:
        raise ValueError('outside declared compact/outboard transform domain')
    for c in choices:
        if c.envelope != InstallationBox(tuple(x - .06 for x in c.pose.origin_body_m),
                                        tuple(x + .06 for x in c.pose.origin_body_m)):
            raise ValueError('declared battery installation envelope changed')
    return name


@dataclass(slots=True)
class ConstructorLedger:
    maximum_compiles: int = 256
    compiles: int = 0
    control_reserved: int = 0

    def validate(self):
        integer(self.maximum_compiles, 'constructor cap', 1, 256)
        integer(self.compiles, 'constructor count', 0, self.maximum_compiles)
        integer(self.control_reserved, 'constructor control', 0, self.maximum_compiles * 16 * 2**20)
        if self.control_reserved != self.compiles * 16 * 2**20:
            raise ValueError('constructor work reset')

    def reserve(self):
        self.validate()
        if self.compiles == self.maximum_compiles:
            raise ValueError('M7_CONSTRUCTOR_ADMISSION')
        # One input guard compilation, one new compilation, effective hardware
        # (assembly + harness + construction) and bounded port/coverage checks.
        # Existing harness compile reservation is 2**20; sixteen is a declared
        # conservative control reservation, not an arithmetic operation count.
        self.compiles += 1
        self.control_reserved += 16 * 2**20


def payload_area(model):
    return next(l.wire.cross_section_m2 for l in model.configuration.lines if l.line_id == 'payload-line')


def rebuild_model(base, name, area, ledger):
    """One paid bounded construction; no flight state or cache is an argument."""
    if type(base) is not CommandRollingRoot or type(ledger) is not ConstructorLedger:
        raise TypeError('exact command root and constructor ledger required')
    base.__post_init__()
    if type(name) is not str or name not in PLACEMENTS:
        raise ValueError('declared placement')
    finite(area, 'declared payload area m2', 1e-10, 1e-6)
    ledger.reserve()  # Before any geometry/derived-hardware computation.
    model = base.model
    placement_name(model.assembly)
    old_choices = selected_battery_choices(model.assembly)
    updates = {}
    for old, origin in zip(old_choices, PLACEMENTS[name]):
        updates[old.choice_id] = replace(old, pose=replace(old.pose, origin_body_m=origin),
            envelope=InstallationBox(tuple(x - .06 for x in origin), tuple(x + .06 for x in origin)))
    design = replace(model.assembly, choices=tuple(updates.get(c.choice_id, c) for c in model.assembly.choices))
    old_compiled = compile_construction(model.assembly, model.configuration)
    left = old_choices[0].pose.origin_body_m
    detour = next(l for l in model.configuration.lines if l.line_id == 'base-bus-line')
    if detour.waypoints_body_m != (left,):
        raise ValueError('undeclared bracket routing rule')
    lines = tuple(replace(l, waypoints_body_m=(PLACEMENTS[name][0],)) if l.line_id == detour.line_id
        else replace(l, wire=replace(l.wire, cross_section_m2=area)) if l.line_id == 'payload-line'
        else l for l in model.configuration.lines)
    cfg = replace(model.configuration, assembly_digest=assembly_document_digest(design), lines=lines)
    compiled = compile_construction(design, cfg)
    old_branches = {b.line_id: b for b in old_compiled.branches}
    branches = {b.line_id: b for b in compiled.branches}
    index = {l.line_id: l for l in cfg.lines}
    routes = []
    for route in model.augmentation.routes:
        old, new = old_branches[route.line_id], branches[route.line_id]
        if route.geometry_digest != geometry_digest(old, next(l for l in model.configuration.lines if l.line_id == route.line_id)):
            raise ValueError('stale original mass route')
        # The bounded authored distribution is endpoint connectors and midpoint
        # offset slack. Explicit local points retain their local coordinates;
        # accepted M4 resolves them against the selected new mount.
        connectors = []
        if len(route.connector_points) != 2:
            raise ValueError('declared two endpoint connectors required')
        for point, old_end, new_end in zip(route.connector_points,
                (old.source_body_m, old.load_body_m), (new.source_body_m, new.load_body_m)):
            if point.frame_kind == 'BODY':
                if point.frame_id != design.body_frame_id or point.coordinates_m != old_end:
                    raise ValueError('undeclared connector redistribution')
                point = replace(point, coordinates_m=new_end)
            connectors.append(point)
        slack = route.slack_point
        if slack is not None and slack.frame_kind == 'BODY':
            def centroid(branch):
                mid = tuple((branch.source_body_m[i] + branch.load_body_m[i]) / 2 for i in range(3))
                return (mid[0] + .025, mid[1], mid[2] + .025)
            if slack.coordinates_m != centroid(old) or slack.frame_id != design.body_frame_id:
                raise ValueError('undeclared slack redistribution')
            slack = replace(slack, coordinates_m=centroid(new))
        routes.append(replace(route, geometry_digest=geometry_digest(new, index[route.line_id]),
                              slack_point=slack, connector_points=tuple(connectors)))
    augmentation = replace(model.augmentation, assembly_digest=cfg.assembly_digest,
        construction_digest=compiled.configuration_digest, routes=tuple(routes))
    result = replace(model, assembly=design, configuration=cfg, augmentation=augmentation)
    hardware = compile_effective_hardware(design, result.capabilities, result.actuator, cfg, augmentation)
    return result, compiled, hardware


def validate_intervention(a, b, hypothesis):
    """Exact recomputed dependent authority, never caller-supplied identities."""
    if type(a) is not CommandRollingRoot or type(b) is not CommandRollingRoot:
        raise TypeError('command roots required')
    if digest(a) == digest(b):
        raise ValueError('NO_OP_INTERVENTION')
    target = placement_name(b.model.assembly)
    area = payload_area(b.model)
    if hypothesis == 'ASSEMBLY_PLACEMENT':
        if digest(a.model.assembly) == digest(b.model.assembly) or area != payload_area(a.model):
            raise ValueError('meaningful placement-only change required')
    elif hypothesis == 'PAYLOAD_WIRE_CROSS_SECTION':
        if digest(a.model.assembly) != digest(b.model.assembly) or area == payload_area(a.model):
            raise ValueError('meaningful area-only change required')
    else:
        raise ValueError('explicit area or placement hypothesis required')
    model, _, _ = rebuild_model(a, target, area, ConstructorLedger(maximum_compiles=1))
    expected = replace(a, reference=replace(a.reference, model=model))
    if digest(expected) != digest(b):
        raise ValueError('INTERVENTION_CHANGED_UNDECLARED_AUTHORITY_OR_DEPENDENT_FIELDS')


@dataclass(frozen=True, slots=True)
class MissionRequirements:
    minimum_credited_products: int = 2
    minimum_priority_score: float = .5
    maximum_unmet_load_wh: float = 0.
    maximum_actual_refusals: int = 0

    def __post_init__(self):
        integer(self.minimum_credited_products, 'required products', 1, 16)
        finite(self.minimum_priority_score, 'required score', 0., 1.)
        finite(self.maximum_unmet_load_wh, 'permitted unmet Wh', 0., 1e6)
        integer(self.maximum_actual_refusals, 'permitted returned refusals', 0, 64)


@dataclass(frozen=True, slots=True)
class StudyLimits:
    max_catalogue_roots: int = 8
    max_actual_starts: int = 9
    max_reconstructions: int = 1
    max_constructor_compiles: int = 256
    max_metadata_bytes: int = 16 * 2**20
    max_retained_case_bytes: int = 2**30
    max_decision_attempts: int = 10 * 64
    max_control_reserved: int = 10 * 2**44 + 2**34
    max_reencoded_bytes: int = 10 * 512 * 2**20

    def __post_init__(self):
        caps = dict(max_catalogue_roots=8, max_actual_starts=9, max_reconstructions=1,
            max_constructor_compiles=256, max_metadata_bytes=16*2**20,
            max_retained_case_bytes=2**30, max_decision_attempts=640,
            max_control_reserved=10*2**44+2**34, max_reencoded_bytes=10*512*2**20)
        for f in fields(self):
            integer(getattr(self, f.name), f.name, 1, caps[f.name])


@dataclass(frozen=True, slots=True)
class DesignRepairSpec:
    reference: CommandRollingRoot
    source_identity: str
    placements: tuple = ('compact', 'outboard')
    payload_areas_m2: tuple = (1e-10, 1e-6, 1e-8, 1e-7)
    requirements: MissionRequirements = MissionRequirements()
    limits: StudyLimits = StudyLimits()
    selection_rule: str = SELECTION
    method: str = METHOD

    def __post_init__(self):
        if type(self.reference) is not CommandRollingRoot:
            raise TypeError('source-bound command-informed input root required')
        self.reference.__post_init__(); hash_identity(self.source_identity)
        if type(self.method) is not str or self.method != METHOD or type(self.selection_rule) is not str or self.selection_rule != SELECTION:
            raise ValueError('fixed finite repair method and selection')
        if type(self.placements) is not tuple or not 1 <= len(self.placements) <= 2 or any(type(n) is not str or n not in PLACEMENTS for n in self.placements) or len(set(self.placements)) != len(self.placements):
            raise ValueError('bounded unique placement names')
        if type(self.payload_areas_m2) is not tuple or not 1 <= len(self.payload_areas_m2) <= 4:
            raise ValueError('bounded declared area tuple')
        for a in self.payload_areas_m2:
            finite(a, 'area m2', 1e-10, 1e-6)
            if type(a) is not float:
                raise TypeError('canonical binary64 area input')
        if len(set(self.payload_areas_m2)) != len(self.payload_areas_m2):
            raise ValueError('duplicate physical area')
        if self.placements[0] != 'compact' or self.payload_areas_m2[0] != 1e-10:
            raise ValueError('first catalogue member must be original weak reference')
        if type(self.requirements) is not MissionRequirements or type(self.limits) is not StudyLimits:
            raise TypeError('exact requirements and limits')
        self.requirements.__post_init__(); self.limits.__post_init__()
        if len(self.placements) * len(self.payload_areas_m2) > self.limits.max_catalogue_roots:
            raise ValueError('catalogue admission')
        root = self.reference
        if placement_name(root.model.assembly) != 'compact' or payload_area(root.model) != 1e-10:
            raise ValueError('original compact weak-wire reference required')
        if root.knowledge_mode.latency_seconds != 40 or int(root.model.environment.start_seconds) != 128 or int(root.model.environment.end_seconds) != 728:
            raise ValueError('bounded C40 600-second study required')

    @property
    def identity(self):
        return digest(self)


@dataclass(frozen=True, slots=True)
class EditManifest:
    specification_identity: str
    base_root_identity: str
    candidate_root_identity: str
    variant_identity: str
    placement: str
    payload_area_m2: float
    kind: str
    edited_fields: tuple
    dependent_owners: tuple = ('M1_ASSEMBLY', 'M4_CONSTRUCTION', 'M4_HARNESS_MASS', 'M4_EFFECTIVE_TENSOR')


@dataclass(frozen=True, slots=True)
class CompiledVariant:
    index: int
    root: CommandRollingRoot
    manifest: EditManifest
    construction: object
    hardware: object


def compile_catalogue(spec, ledger):
    if type(spec) is not DesignRepairSpec:
        raise TypeError('exact finite specification')
    spec.__post_init__()
    result = []; seen = set()
    for name in spec.placements:
        for area in spec.payload_areas_m2:
            model, compiled, hardware = rebuild_model(spec.reference, name, area, ledger)
            root = replace(spec.reference, reference=replace(spec.reference.reference, model=model))
            root_id = digest(root)
            if root_id in seen:
                continue
            seen.add(root_id)
            placement_edit = digest(model.assembly) != digest(spec.reference.model.assembly)
            area_edit = area != payload_area(spec.reference.model)
            kind = 'COMBINED_PLACEMENT_AND_PAYLOAD_AREA' if placement_edit and area_edit else 'ASSEMBLY_PLACEMENT' if placement_edit else 'PAYLOAD_WIRE_CROSS_SECTION' if area_edit else 'BASELINE_IDENTITY'
            edited = (('battery-left.mount.origin_body_m', 'battery-right.mount.origin_body_m') if placement_edit else ()) + (('payload-line.wire.cross_section_m2',) if area_edit else ())
            identity = digest((spec.identity, root_id, kind, edited))
            manifest = EditManifest(spec.identity, digest(spec.reference), root_id, identity, name, area, kind, edited)
            result.append(CompiledVariant(len(result), root, manifest, compiled, hardware))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class RepairProposal:
    proposal_identity: str
    finding_id: str
    evidence_scope: str
    owner_reason: str
    candidate_variant_ids: tuple
    edited_fields: tuple
    intervention_kind: str
    expected_tradeoff: str
    status: str = 'PROPOSAL_ONLY_NO_EXECUTION_GRANT'


def propose_repairs(spec, catalogue, diagnosis):
    from .mission_diagnosis import MissionDiagnosis
    if type(diagnosis) is not MissionDiagnosis or diagnosis.root_identity != digest(spec.reference):
        raise ValueError('source-bound weak reference diagnosis required')
    diagnosis.__post_init__()
    if diagnosis.model_identity != digest(spec.reference.model):
        raise ValueError('diagnosis model substitution')
    result = []
    for f in diagnosis.findings:
        if f.scope not in ('FORECAST', 'ACTUAL') or f.category not in ('FULL_ELECTRICAL_SERVICE', 'RETURNED_ELECTRICAL_LIMIT'):
            continue
        for v in catalogue:
            if v.manifest.payload_area_m2 <= payload_area(spec.reference.model):continue
            candidates=(v.manifest.variant_identity,)
            result.append(RepairProposal(digest((spec.identity, f.finding_id, candidates)), f.finding_id,
                f.scope, f.owner_reason, candidates, v.manifest.edited_fields,v.manifest.kind,
                'Larger declared conductor area may reduce voltage loss; adds rigid wire mass and changes COM/full inertia. Any combined placement is a declared engineering comparison, not an attributed battery fault. Actual feasibility must be evaluated.'))
            if len(result)>=64:break
        if len(result) >= 64:
            break
    return tuple(result)
