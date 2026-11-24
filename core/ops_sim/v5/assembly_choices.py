"""Finite authored assembly choices and declared installation checks.

See M1_ASSEMBLY_CHOICES.md. Geometry is independent of mass cuboids.
M1-A owns all frame/placement/mass validation and tensor calculations.
"""

from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations

from .assembly import (
    ComponentPlacement, MassCoverage, MountPose, SpacecraftAssembly, UniformCuboid,
    Vector3, _identities, _identity, _mount, _overlap, _real, _vector,
)


def _copy(value, owner):
    if type(value) is not owner:
        raise TypeError(f"exact {owner.__name__} required")
    return replace(value)


def _records(values, owner, key, *, nonempty=False):
    if type(values) is not tuple or (nonempty and not values):
        raise TypeError(f"{'nonempty ' if nonempty else ''}exact tuple of {owner.__name__} required")
    admitted = tuple(_copy(v, owner) for v in values)
    ids = [getattr(v, key) for v in admitted]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate {owner.__name__} ID")
    return tuple(sorted(admitted, key=lambda v: getattr(v, key)))


@dataclass(frozen=True, slots=True)
class InstallationBox:
    """Authored body-frame AABB in metres, never inferred from a mass model."""

    lower_m: Vector3
    upper_m: Vector3

    def __post_init__(self):
        lower, upper = _vector(self.lower_m, "lower_m"), _vector(self.upper_m, "upper_m")
        if any(lo >= hi for lo, hi in zip(lower, upper, strict=True)):
            raise ValueError("installation box must have three positive extents")
        object.__setattr__(self, "lower_m", lower)
        object.__setattr__(self, "upper_m", upper)


@dataclass(frozen=True, slots=True)
class InstallationRegion:
    region_id: str
    box: InstallationBox

    def __post_init__(self):
        _identity(self.region_id, "region_id")
        object.__setattr__(self, "box", _copy(self.box, InstallationBox))


@dataclass(frozen=True, slots=True)
class PhysicalInstance:
    instance_id: str
    definition_id: str
    mass_coverage: MassCoverage | None

    def __post_init__(self):
        _identity(self.instance_id, "instance_id")
        _identity(self.definition_id, "definition_id")
        if self.mass_coverage is not None:
            object.__setattr__(self, "mass_coverage", _copy(self.mass_coverage, MassCoverage))


@dataclass(frozen=True, slots=True)
class PlacementChoice:
    choice_id: str
    definition_id: str
    allowed_instance_ids: tuple[str, ...]
    pose: MountPose
    envelope: InstallationBox | None
    allowed_region_id: str | None
    exclusive: bool

    def __post_init__(self):
        _identity(self.choice_id, "choice_id")
        _identity(self.definition_id, "definition_id")
        allowed = _identities(self.allowed_instance_ids, "allowed_instance_ids")
        if not allowed:
            raise ValueError("a placement choice must permit at least one physical instance")
        object.__setattr__(self, "allowed_instance_ids", tuple(sorted(allowed)))
        pose = _mount(self.pose)
        if pose.choice_id != self.choice_id:
            raise ValueError("choice ID must agree with its authoritative pose")
        object.__setattr__(self, "pose", replace(pose, occupied_slots=tuple(sorted(pose.occupied_slots))))
        if type(self.exclusive) is not bool:
            raise TypeError("exclusive must be a built-in bool")
        if self.envelope is None:
            if self.allowed_region_id is not None:
                raise ValueError("an absent envelope cannot reference an allowed region")
        else:
            object.__setattr__(self, "envelope", _copy(self.envelope, InstallationBox))
            _identity(self.allowed_region_id, "allowed_region_id")


@dataclass(frozen=True, slots=True)
class Selection:
    instance_id: str
    choice_id: str

    def __post_init__(self):
        _identity(self.instance_id, "instance_id")
        _identity(self.choice_id, "choice_id")


@dataclass(frozen=True, slots=True)
class AssemblyDesign:
    body_frame_id: str
    definitions: tuple[UniformCuboid, ...]
    instances: tuple[PhysicalInstance, ...]
    choices: tuple[PlacementChoice, ...]
    selections: tuple[Selection, ...]
    allowed_regions: tuple[InstallationRegion, ...]
    reserved_regions: tuple[InstallationRegion, ...]
    clearance_m: float

    def __post_init__(self):
        _identity(self.body_frame_id, "body_frame_id")
        for name, owner, key, nonempty in (
            ("definitions", UniformCuboid, "definition_id", True),
            ("instances", PhysicalInstance, "instance_id", True),
            ("choices", PlacementChoice, "choice_id", True),
            ("selections", Selection, "instance_id", True),
            ("allowed_regions", InstallationRegion, "region_id", False),
            ("reserved_regions", InstallationRegion, "region_id", False),
        ):
            object.__setattr__(self, name, _records(getattr(self, name), owner, key, nonempty=nonempty))
        clearance = _real(self.clearance_m, "clearance_m")
        if clearance < 0:
            raise ValueError("clearance_m must be nonnegative")
        object.__setattr__(self, "clearance_m", clearance)
        definitions = {d.definition_id: d for d in self.definitions}
        instances = {i.instance_id: i for i in self.instances}
        choices = {c.choice_id: c for c in self.choices}
        regions = {r.region_id for r in self.allowed_regions}
        if regions & {r.region_id for r in self.reserved_regions}:
            raise ValueError("region IDs must be unique across allowed and reserved regions")
        for instance in self.instances:
            if instance.definition_id not in definitions:
                raise ValueError(f"unknown definition for instance {instance.instance_id!r}")
        for choice in self.choices:
            if choice.definition_id not in definitions:
                raise ValueError(f"unknown definition for choice {choice.choice_id!r}")
            if choice.pose.body_frame_id != self.body_frame_id:
                raise ValueError(f"wrong body frame for choice {choice.choice_id!r}")
            definition = definitions[choice.definition_id]
            if choice.pose.local_frame_id != definition.local_frame_id:
                raise ValueError(f"wrong local frame for choice {choice.choice_id!r}")
            if choice.envelope is not None and choice.allowed_region_id not in regions:
                raise ValueError(f"unknown allowed region for choice {choice.choice_id!r}")
            for instance_id in choice.allowed_instance_ids:
                if instance_id not in instances:
                    raise ValueError(f"unknown compatible instance {instance_id!r}")
                if instances[instance_id].definition_id != choice.definition_id:
                    raise ValueError(f"incompatible definition for choice {choice.choice_id!r}, instance {instance_id!r}")
            # Also reject an unrepresentable derived COM in an unused choice.
            ComponentPlacement.from_mount(choice.allowed_instance_ids[0], definition, choice.pose)
        if {s.instance_id for s in self.selections} != set(instances):
            raise ValueError("selections must cover every physical instance exactly once")
        for selection in self.selections:
            if selection.choice_id not in choices:
                raise ValueError(f"unknown selected choice {selection.choice_id!r}")
            choice = choices[selection.choice_id]
            if selection.instance_id not in choice.allowed_instance_ids:
                raise ValueError(f"incompatible choice {choice.choice_id!r} for instance {selection.instance_id!r}")


@dataclass(frozen=True, slots=True)
class InstallationViolation:
    code: str
    component_ids: tuple[str, ...]
    choice_ids: tuple[str, ...]
    resource_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DesignAssessment:
    violations: tuple[InstallationViolation, ...]
    installation_status: str
    mass_accounting_status: str
    assembly: SpacecraftAssembly | None

    @property
    def declared_constraints_satisfied(self) -> bool:
        return not self.violations

    @property
    def qualified(self) -> bool:
        return (not self.violations and self.installation_status == "CHECKED_DECLARATIONS"
                and self.mass_accounting_status == "CHECKED_DECLARATIONS")


def _contained(inner: InstallationBox, outer: InstallationBox, clearance: float) -> bool:
    g = Fraction(clearance)
    return all(Fraction(inner.lower_m[i]) - Fraction(outer.lower_m[i]) >= g
               and Fraction(outer.upper_m[i]) - Fraction(inner.upper_m[i]) >= g
               for i in range(3))


def _conflict(a: InstallationBox, b: InstallationBox, clearance: float) -> bool:
    g = Fraction(clearance)
    return all(max(Fraction(b.lower_m[i]) - Fraction(a.upper_m[i]),
                   Fraction(a.lower_m[i]) - Fraction(b.upper_m[i])) < g for i in range(3))


def _status(specified: int, total: int) -> str:
    return "UNSPECIFIED" if specified == 0 else "CHECKED_DECLARATIONS" if specified == total else "PARTIAL"


def assess_design(design: AssemblyDesign) -> DesignAssessment:
    """Resolve authoritative choices and collect every independent rule violation."""
    design = _copy(design, AssemblyDesign)
    definitions = {d.definition_id: d for d in design.definitions}
    instances = {i.instance_id: i for i in design.instances}
    choices = {c.choice_id: c for c in design.choices}
    regions = {r.region_id: r.box for r in design.allowed_regions}
    resolved = []
    active = []
    violations = []
    for selection in design.selections:
        instance, choice = instances[selection.instance_id], choices[selection.choice_id]
        resolved.append(ComponentPlacement.from_mount(instance.instance_id,
            definitions[instance.definition_id], choice.pose, mass_coverage=instance.mass_coverage))
        active.append((instance, choice))
        if choice.envelope is not None:
            if not _contained(choice.envelope, regions[choice.allowed_region_id], design.clearance_m):
                violations.append(InstallationViolation("OUTSIDE_ALLOWED_REGION",
                    (instance.instance_id,), (choice.choice_id,), (choice.allowed_region_id,)))
            for reserved in design.reserved_regions:
                if _conflict(choice.envelope, reserved.box, design.clearance_m):
                    violations.append(InstallationViolation("RESERVED_REGION_CONFLICT",
                        (instance.instance_id,), (choice.choice_id,), (reserved.region_id,)))
    for (ia, a), (ib, b) in combinations(active, 2):
        ids, choice_ids = (ia.instance_id, ib.instance_id), (a.choice_id, b.choice_id)
        if (a.envelope is not None and b.envelope is not None and (a.exclusive or b.exclusive)
                and _conflict(a.envelope, b.envelope, design.clearance_m)):
            violations.append(InstallationViolation("EXCLUSIVE_ENVELOPE_CONFLICT", ids, choice_ids))
        slots = tuple(sorted(set(a.pose.occupied_slots) & set(b.pose.occupied_slots)))
        if slots:
            violations.append(InstallationViolation("EXCLUSIVE_SLOT_CONFLICT", ids, choice_ids, slots))
        if ia.mass_coverage is not None and ib.mass_coverage is not None:
            if any(_overlap(x, y) for x in ia.mass_coverage.paths for y in ib.mass_coverage.paths):
                violations.append(InstallationViolation("MASS_COVERAGE_OVERLAP", ids, choice_ids))
    # M1-A remains the final authority. Do not build an invalid assembly by
    # dropping coverage/slots just to calculate a number for an inadmissible input.
    assembly = None
    if not any(v.code in ("EXCLUSIVE_SLOT_CONFLICT", "MASS_COVERAGE_OVERLAP") for v in violations):
        assembly = SpacecraftAssembly(design.body_frame_id, tuple(resolved))
    ordered = tuple(sorted(violations, key=lambda v: (v.code, v.component_ids, v.choice_ids, v.resource_ids)))
    return DesignAssessment(ordered,
        _status(sum(c.envelope is not None for _, c in active), len(active)),
        _status(sum(i.mass_coverage is not None for i, _ in active), len(active)), assembly)


def verify_resolved_assembly(design: AssemblyDesign, supplied: SpacecraftAssembly) -> None:
    """Reject caller-authored poses/definitions/coverage masquerading as selections.

    Ordering is immaterial. No geometric tolerance or display-name inference.
    Checking authorization alone does not override installation violations.
    """
    expected = assess_design(design).assembly
    if expected is None:
        raise ValueError("selected coverage/slots do not permit a valid M1-A assembly")
    supplied = _copy(supplied, SpacecraftAssembly)
    supplied_components = tuple(replace(c, mount_pose=replace(c.mount_pose,
        occupied_slots=tuple(sorted(c.mount_pose.occupied_slots)))) if c.mount_pose is not None else c
        for c in supplied.components)
    if (supplied.body_frame_id != expected.body_frame_id
            or sorted(supplied_components, key=lambda c: c.component_id)
            != sorted(expected.components, key=lambda c: c.component_id)):
        raise ValueError("supplied assembly does not match authoritative selected poses and instances")
