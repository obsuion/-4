"""Immutable, static uniform-cuboid assemblies; see M1_ASSEMBLY.md.

This module does not change campaign execution, persistence or attitude dynamics.
Vectors are right-handed Cartesian SI; rotations map component to body axes.
"""

from dataclasses import dataclass, replace
from math import fsum, isfinite

from .design_trade_design import DesignAssumptions, derive_design


Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]
IDENTITY: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
UNIFORM_CUBOID = "ASSUMED_UNIFORM_CUBOID"
LEGACY_BODY_FRAME = "05E_CORE_CENTERED_BODY"
# Binary64 representation tolerance, not a physical orientation uncertainty.
ROTATION_RESIDUAL_LIMIT = 64 * 2.0**-53


def _identity(value: str, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be nonempty and contain no NUL")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must be valid UTF-8 text") from exc
    return value


def _real(value: float, name: str) -> float:
    if type(value) not in (int, float):
        raise TypeError(f"{name} must be a built-in int or float")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} is outside binary64 range") from exc
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _vector(value: Vector3, name: str) -> Vector3:
    if type(value) is not tuple or len(value) != 3:
        raise TypeError(f"{name} must be an exact three-tuple")
    return tuple(_real(x, name) for x in value)


def _rotation(value: Matrix3) -> Matrix3:
    if type(value) is not tuple or len(value) != 3:
        raise TypeError("rotation must be an exact tuple of three rows")
    r = tuple(_vector(row, "rotation row") for row in value)
    try:
        residual = max(abs(fsum(r[k][i] * r[k][j] for k in range(3))
                           - float(i == j)) for i in range(3) for j in range(3))
        determinant = fsum((
            r[0][0] * r[1][1] * r[2][2], r[0][1] * r[1][2] * r[2][0],
            r[0][2] * r[1][0] * r[2][1], -r[0][2] * r[1][1] * r[2][0],
            -r[0][1] * r[1][0] * r[2][2], -r[0][0] * r[1][2] * r[2][1],
        ))
    except (OverflowError, ValueError) as exc:
        raise ValueError("rotation arithmetic outside binary64 range") from exc
    if (not isfinite(residual) or not isfinite(determinant)
            or residual > ROTATION_RESIDUAL_LIMIT
            or abs(determinant - 1.0) > ROTATION_RESIDUAL_LIMIT):
        raise ValueError("rotation must be proper orthogonal (no reflection or repair)")
    return r


@dataclass(frozen=True, slots=True)
class UniformCuboid:
    """Definition of an assumed mass distribution, not a qualified solid part.

    size_m follows local x/y/z. center_local_m is the mass center in that
    local frame; dimensions extend equally about it, including zero limits.
    """

    definition_id: str
    local_frame_id: str
    mass_kg: float
    size_m: Vector3
    center_local_m: Vector3
    mass_distribution: str

    def __post_init__(self) -> None:
        _identity(self.definition_id, "definition_id")
        _identity(self.local_frame_id, "local_frame_id")
        mass = _real(self.mass_kg, "mass_kg")
        if mass <= 0:
            raise ValueError("mass_kg must be positive")
        size = _vector(self.size_m, "size_m")
        if any(x < 0 for x in size):
            raise ValueError("size_m must be nonnegative")
        if type(self.mass_distribution) is not str:
            raise TypeError("mass_distribution must be an exact string")
        if self.mass_distribution != UNIFORM_CUBOID:
            raise ValueError("only ASSUMED_UNIFORM_CUBOID is supported")
        object.__setattr__(self, "mass_kg", mass)
        object.__setattr__(self, "size_m", size)
        object.__setattr__(self, "center_local_m",
                           _vector(self.center_local_m, "center_local_m"))

    @property
    def idealization(self) -> str:
        """Explicit rank of the declared distribution; no inferred thickness."""
        return ("point", "line", "plate", "cuboid")[sum(x > 0 for x in self.size_m)]


def _definition(value: UniformCuboid) -> UniformCuboid:
    if type(value) is not UniformCuboid:
        raise TypeError("exact UniformCuboid required")
    return UniformCuboid(value.definition_id, value.local_frame_id, value.mass_kg,
                         value.size_m, value.center_local_m, value.mass_distribution)


def _identities(value: tuple[str, ...], name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    admitted = tuple(_identity(x, name) for x in value)
    if len(set(admitted)) != len(admitted):
        raise ValueError(f"{name} must be unique")
    return admitted


def _overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    length = min(len(left), len(right))
    return left[:length] == right[:length]


@dataclass(frozen=True, slots=True)
class MassCoverage:
    """Declared physical ownership paths, independent of component/catalog IDs.

    A path claims its whole subtree: ('bus',) includes ('bus', 'payload').
    These are accounting partitions, not mounting/geometry hierarchies.
    None on a placement means unspecified; an empty declaration is invalid.
    """

    paths: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if type(self.paths) is not tuple or not self.paths:
            raise TypeError("mass coverage requires a nonempty exact tuple of paths")
        admitted = []
        for path in self.paths:
            if type(path) is not tuple or not path:
                raise TypeError("a mass path must be a nonempty exact tuple")
            path = tuple(_identity(part, "mass path segment") for part in path)
            if any(_overlap(path, other) for other in admitted):
                raise ValueError("overlapping mass claims within one declaration")
            admitted.append(path)
        object.__setattr__(self, "paths", tuple(sorted(admitted)))


@dataclass(frozen=True, slots=True)
class MountPose:
    """Selected authored mount/choice with explicit exclusive slot claims.

    origin_body_m is p_B. The UniformCuboid local frame is the local mount
    frame C, whose center_local_m is c_C. No mechanical-fit inference.
    Empty occupied_slots explicitly declares no exclusive slot claims.
    """

    mount_id: str
    choice_id: str
    body_frame_id: str
    local_frame_id: str
    origin_body_m: Vector3
    rotation_body_from_local: Matrix3
    occupied_slots: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("mount_id", "choice_id", "body_frame_id", "local_frame_id"):
            _identity(getattr(self, name), name)
        object.__setattr__(self, "origin_body_m", _vector(self.origin_body_m, "origin_body_m"))
        object.__setattr__(self, "rotation_body_from_local", _rotation(self.rotation_body_from_local))
        object.__setattr__(self, "occupied_slots", _identities(self.occupied_slots, "occupied_slots"))


def _mount(value: MountPose) -> MountPose:
    if type(value) is not MountPose:
        raise TypeError("exact MountPose required")
    return MountPose(value.mount_id, value.choice_id, value.body_frame_id,
                     value.local_frame_id, value.origin_body_m,
                     value.rotation_body_from_local, value.occupied_slots)


def _mounted_center(definition: UniformCuboid, mount: MountPose) -> Vector3:
    if mount.local_frame_id != definition.local_frame_id:
        raise ValueError("mount local frame must match component local frame")
    try:
        return _vector(tuple(fsum((mount.origin_body_m[i], fsum(
            mount.rotation_body_from_local[i][k] * definition.center_local_m[k]
            for k in range(3)))) for i in range(3)), "mounted center")
    except OverflowError as exc:
        raise ValueError("mount arithmetic outside binary64 range") from exc


@dataclass(frozen=True, slots=True)
class ComponentPlacement:
    """One physical instance: p_B = center_body + R (p_C - center_local).

    center_body_m places the COM directly, not the component-frame origin.
    Rows of rotation_body_from_local form R; columns are C axes in B.
    """

    component_id: str
    definition: UniformCuboid
    body_frame_id: str
    center_body_m: Vector3
    rotation_body_from_local: Matrix3
    mass_coverage: MassCoverage | None = None
    mount_pose: MountPose | None = None

    def __post_init__(self) -> None:
        _identity(self.component_id, "component_id")
        _identity(self.body_frame_id, "body_frame_id")
        object.__setattr__(self, "definition", _definition(self.definition))
        object.__setattr__(self, "center_body_m", _vector(self.center_body_m, "center_body_m"))
        object.__setattr__(self, "rotation_body_from_local",
                           _rotation(self.rotation_body_from_local))
        if self.mass_coverage is not None:
            if type(self.mass_coverage) is not MassCoverage:
                raise TypeError("exact MassCoverage or None required")
            object.__setattr__(self, "mass_coverage", MassCoverage(self.mass_coverage.paths))
        if self.mount_pose is not None:
            mount = _mount(self.mount_pose)
            if (mount.body_frame_id != self.body_frame_id
                    or mount.rotation_body_from_local != self.rotation_body_from_local
                    or _mounted_center(self.definition, mount) != self.center_body_m):
                raise ValueError("mount metadata must reproduce the direct-COM placement")
            object.__setattr__(self, "mount_pose", mount)

    @classmethod
    def from_mount(cls, component_id: str, definition: UniformCuboid,
                   mount_pose: MountPose, *, mass_coverage: MassCoverage | None = None
                   ) -> "ComponentPlacement":
        """Derive r_B = p_B + R_BC c_C once, retaining the authored mount pose.

        definition.center_local_m is explicitly relative to the local mount
        origin in this constructor. The ordinary constructor stays direct-COM.
        """
        definition, mount = _definition(definition), _mount(mount_pose)
        return cls(component_id, definition, mount.body_frame_id,
                   _mounted_center(definition, mount), mount.rotation_body_from_local,
                   mass_coverage, mount)


def _placement(value: ComponentPlacement) -> ComponentPlacement:
    if type(value) is not ComponentPlacement:
        raise TypeError("exact ComponentPlacement required")
    return ComponentPlacement(value.component_id, value.definition, value.body_frame_id,
                              value.center_body_m, value.rotation_body_from_local,
                              value.mass_coverage, value.mount_pose)


@dataclass(frozen=True, slots=True)
class SpacecraftAssembly:
    """Authored static inputs; no operational or mutable simulator state."""

    body_frame_id: str
    components: tuple[ComponentPlacement, ...]

    def __post_init__(self) -> None:
        _identity(self.body_frame_id, "body_frame_id")
        if type(self.components) is not tuple or not self.components:
            raise TypeError("components must be a nonempty exact tuple")
        admitted = tuple(_placement(c) for c in self.components)
        if len({c.component_id for c in admitted}) != len(admitted):
            raise ValueError("component IDs must be unique")
        definitions = {}
        mass_claims = []
        occupied_slots = set()
        for c in admitted:
            if c.body_frame_id != self.body_frame_id:
                raise ValueError("component body frame must match assembly body frame")
            key = c.definition.definition_id
            if key in definitions and definitions[key] != c.definition:
                raise ValueError("one definition ID cannot denote different properties")
            definitions[key] = c.definition
            if c.mass_coverage is not None:
                for path in c.mass_coverage.paths:
                    for prior_path, prior_id in mass_claims:
                        if _overlap(path, prior_path):
                            raise ValueError(f"overlapping mass claims: {prior_id!r}, {c.component_id!r}")
                    mass_claims.append((path, c.component_id))
            if c.mount_pose is not None:
                for slot in c.mount_pose.occupied_slots:
                    if slot in occupied_slots:
                        raise ValueError(f"declared mount occupancy conflict: {slot!r}")
                    occupied_slots.add(slot)
        object.__setattr__(self, "components", admitted)

    @property
    def mass_accounting_status(self) -> str:
        specified = sum(c.mass_coverage is not None for c in self.components)
        return ("UNSPECIFIED" if specified == 0 else
                "CHECKED_DECLARATIONS" if specified == len(self.components) else "PARTIAL")

    @property
    def mount_accounting_status(self) -> str:
        specified = sum(c.mount_pose is not None for c in self.components)
        return ("UNSPECIFIED" if specified == 0 else
                "CHECKED_DECLARATIONS" if specified == len(self.components) else "PARTIAL")


@dataclass(frozen=True, slots=True)
class AssemblyMassProperties:
    """Derived output: tensor about center_body_m, expressed in body_frame_id.

    This output is not accepted as input, authoritative saved state, or a cache.
    """

    body_frame_id: str
    total_mass_kg: float
    center_body_m: Vector3
    inertia_com_body_kg_m2: Matrix3

    def __post_init__(self) -> None:
        _identity(self.body_frame_id, "body_frame_id")
        mass = _real(self.total_mass_kg, "total_mass_kg")
        if mass <= 0:
            raise ValueError("total_mass_kg must be positive")
        object.__setattr__(self, "total_mass_kg", mass)
        object.__setattr__(self, "center_body_m", _vector(self.center_body_m, "center_body_m"))
        tensor = self.inertia_com_body_kg_m2
        if type(tensor) is not tuple or len(tensor) != 3:
            raise TypeError("tensor must be an exact tuple of three rows")
        tensor = tuple(_vector(row, "tensor row") for row in tensor)
        if any(tensor[i][j] != tensor[j][i] for i in range(3) for j in range(3)):
            raise ValueError("derived tensor must be symmetric")
        object.__setattr__(self, "inertia_com_body_kg_m2", tensor)


def calculate_mass_properties(assembly: SpacecraftAssembly) -> AssemblyMassProperties:
    """Sum rotated centroidal tensors and parallel-axis terms about total COM.

    Revalidate nested inputs at the calculation boundary. Sorting physical IDs
    fixes reduction order; math.fsum reduces cancellation in signed entries.
    Unrepresentable intermediate arithmetic fails explicitly, never clamps.
    """
    if type(assembly) is not SpacecraftAssembly:
        raise TypeError("exact SpacecraftAssembly required")
    admitted = SpacecraftAssembly(assembly.body_frame_id, assembly.components)
    components = sorted(admitted.components, key=lambda c: c.component_id)
    try:
        mass = fsum(c.definition.mass_kg for c in components)
        center = tuple(fsum(c.definition.mass_kg * c.center_body_m[i]
                            for c in components) / mass for i in range(3))
        # Diagonal shifts sum the other squared coordinates directly to avoid
        # cancellation from (d dot d) - d_i**2. Off-diagonal signs are negative.
        contributions = {(i, j): [] for i in range(3) for j in range(i, 3)}
        for c in components:
            m, size = c.definition.mass_kg, c.definition.size_m
            local = tuple(m * fsum(size[k] ** 2 for k in range(3) if k != i) / 12
                          for i in range(3))
            r = c.rotation_body_from_local
            d = tuple(c.center_body_m[i] - center[i] for i in range(3))
            for i, j in contributions:
                rotated = fsum(r[i][k] * local[k] * r[j][k] for k in range(3))
                shift = (m * fsum(d[k] ** 2 for k in range(3) if k != i)
                         if i == j else -m * d[i] * d[j])
                contributions[i, j].append(fsum((rotated, shift)))
        entries = {key: fsum(values) for key, values in contributions.items()}
        tensor = tuple(tuple(entries[min(i, j), max(i, j)] for j in range(3))
                       for i in range(3))
        return AssemblyMassProperties(admitted.body_frame_id, mass, center, tensor)
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError("assembly arithmetic outside binary64 range") from exc


class UnsupportedLegacyInertiaScale(ValueError):
    """The scalar legacy adjustment does not define a 3-D mass distribution."""


@dataclass(frozen=True, slots=True)
class AllocationAssembly:
    """05E feasibility metadata alongside static mass inputs, not in the tensor."""

    design_id: str
    assembly: SpacecraftAssembly
    accepted: bool
    rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _identity(self.design_id, "design_id")
        if type(self.assembly) is not SpacecraftAssembly:
            raise TypeError("exact SpacecraftAssembly required")
        object.__setattr__(self, "assembly", SpacecraftAssembly(
            self.assembly.body_frame_id, self.assembly.components))
        if type(self.accepted) is not bool:
            raise TypeError("accepted must be a built-in bool")
        reasons = _identities(self.rejection_reasons, "rejection_reasons")
        if self.accepted != (not reasons):
            raise ValueError("accepted must agree with the absence of rejection reasons")
        object.__setattr__(self, "rejection_reasons", reasons)


def _05e_coverage(packs: int, arrays: int, regulator_banks: int) -> dict[str, MassCoverage]:
    """Explicit join to the accepted inventory IDs; never parse display names.

    This is an ownership ledger only: no duplicated masses, geometry or catalog.
    Missing/extra inventory IDs fail closed at the adapter boundary.
    """
    ledger = {"core_including_imager_and_actuator": MassCoverage((("05E", "core"),))}

    def claim(key: str, *path: str) -> None:
        ledger[key] = MassCoverage((("05E", *path),))

    for row in range(packs // 2):
        for side in (-1, 1):
            claim(f"battery_{row}_{side}", "battery", str(row), str(side))
            claim(f"battery_{row}_{side}_external_mount", "battery_external_mount", str(row), str(side))
    for row in range(arrays // 2):
        for side in (-1, 1):
            key = f"array_{row}_{side}"
            claim(key + "_deployed", "array", str(row), str(side), "wing")
            claim(key + "_catalog_root_parts", "array", str(row), str(side), "root_parts")
            claim(key + "_external_adapter", "array_external_adapter", str(row), str(side))
            for kind in range(2):
                for number in range(3):
                    wire = key + f"_external_string_{kind}_{number}"
                    path = ("external_string", str(row), str(side), str(kind), str(number))
                    claim(wire, *path, "conductors_and_connectors")
                    claim(wire + "_insulation", *path, "insulation")
    for bank in range(regulator_banks):
        claim(f"regulator_equivalent_bank_{bank}", "regulator", str(bank))
    claim("main_load_harness", "main_harness", "conductors_and_connectors")
    claim("main_load_harness_insulation", "main_harness", "insulation")
    return ledger


def convert_05e_allocation(packs: int, arrays: int,
                         assumptions: DesignAssumptions | None = None) -> AllocationAssembly:
    """Convert the authoritative 05E inventory, without running a campaign.

    Validate the scale before scalar inertia arithmetic; derive_design owns
    counts and inventory. No stale TradeDesign is trusted.
    Retain derive_design's acceptance/reasons without promoting static mass
    validity into hardware feasibility. No mount pose is invented for old boxes.
    """
    if assumptions is not None and type(assumptions) is not DesignAssumptions:
        raise TypeError("exact DesignAssumptions required")
    admitted = DesignAssumptions() if assumptions is None else replace(assumptions)
    if admitted.core_inertia_scale != 1.0:
        raise UnsupportedLegacyInertiaScale(
            "full-tensor conversion requires core_inertia_scale == 1; "
            "a Y-only adjustment supplies no 3-D mass distribution")
    design = derive_design(packs, arrays, admitted)
    coverage = _05e_coverage(packs, arrays, design.regulator_banks)
    if set(coverage) != {c.name for c in design.components}:
        raise ValueError("05E ownership ledger does not match authoritative inventory IDs")
    assembly = SpacecraftAssembly(LEGACY_BODY_FRAME, tuple(
        ComponentPlacement(c.name,
            UniformCuboid("05E/" + c.name, "05E/" + c.name + "/LOCAL",
                          c.mass_kg, c.size_m, (0.0, 0.0, 0.0), UNIFORM_CUBOID),
            LEGACY_BODY_FRAME, c.center_m, IDENTITY, coverage[c.name])
        for c in design.components))
    return AllocationAssembly(design.design_id, assembly, design.accepted, design.rejection_reasons)


def assembly_from_05e(packs: int, arrays: int,
                      assumptions: DesignAssumptions | None = None) -> SpacecraftAssembly:
    """Backward-compatible static-only view; use convert_05e_allocation for feasibility."""
    return convert_05e_allocation(packs, arrays, assumptions).assembly
