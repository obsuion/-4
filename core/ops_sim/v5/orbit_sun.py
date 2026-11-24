"""Read-only orbit/Sun point queries. See M2_ORBIT_SUN.md for proof scope."""
from dataclasses import dataclass
from fractions import Fraction
from math import hypot

from .experiment_codec import canonical_copy
from .frames import CartesianDirection, CartesianPosition, CartesianState, transform_direction
from .ids import SourceRecordId
from .orbit import evaluate_two_body_state
from .orbit_binding import CoastOrbitInputs
from .orbit_config import GeometryInstant, _exact
from .orbit_j2_binding import J2CoastOrbitInputs
from .orbit_j2_enclosure import J2EnclosureResult, evaluate_j2_enclosure


def _text(value, name):
    _exact(value, str, name)
    value.encode("utf-8", errors="strict")
    if not value.strip():
        raise ValueError(name + " must be nonblank")
    return value


def _direction(value):
    _exact(value, CartesianDirection, "direction")
    # CartesianDirection is deliberately absent from the old codec allowlist.
    frame, instant, components = canonical_copy((value.frame, value.instant, value.components))
    return CartesianDirection(frame, instant, components)


@dataclass(frozen=True, slots=True)
class SuppliedSunDirection:
    """Per-instant spacecraft-to-Sun ray; magnitude has no physical meaning."""
    direction: CartesianDirection
    origin: str
    source_ids: tuple[SourceRecordId, ...]
    rationale: str

    def __post_init__(self):
        direction = _direction(self.direction)
        origin = _text(self.origin, "origin")
        if origin not in ("SYNTHETIC", "EXTERNALLY_SUPPLIED"):
            raise ValueError("unsupported Sun provenance origin")
        _exact(self.source_ids, tuple, "source_ids")
        sources = canonical_copy(self.source_ids)
        for source in sources:
            _exact(source, SourceRecordId, "source ID")
        if len(set(sources)) != len(sources):
            raise ValueError("duplicate Sun source ID")
        if origin == "EXTERNALLY_SUPPLIED" and not sources:
            raise ValueError("external Sun input requires source IDs")
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "source_ids", sources)
        _text(self.rationale, "rationale")


def _sun(value):
    _exact(value, SuppliedSunDirection, "sun")
    return SuppliedSunDirection(value.direction, value.origin, value.source_ids, value.rationale)


def _matching_direction(frame, instant, direction):
    if direction.instant != instant:
        raise ValueError("Sun and query instants/epochs must match exactly")
    if direction.frame == frame:
        return direction, False
    return transform_direction(direction, frame), True


@dataclass(frozen=True, slots=True)
class OrbitSunQuery:
    coast: CoastOrbitInputs | J2CoastOrbitInputs
    instant: GeometryInstant
    sun: SuppliedSunDirection

    def __post_init__(self):
        if type(self.coast) not in (CoastOrbitInputs, J2CoastOrbitInputs):
            raise TypeError("query requires existing coast input owner")
        coast = canonical_copy(self.coast)
        _exact(self.instant, GeometryInstant, "instant")
        instant = canonical_copy(self.instant)
        sun = _sun(self.sun)
        anchor = coast.trajectory.initial_state.position
        if instant.epoch != anchor.instant.epoch:
            raise ValueError("query must retain original TT reference epoch")
        _matching_direction(anchor.frame, instant, sun.direction)
        object.__setattr__(self, "coast", coast)
        object.__setattr__(self, "instant", instant)
        object.__setattr__(self, "sun", sun)


@dataclass(frozen=True, slots=True)
class ShadowAssessment:
    nominal: str | None
    qualified: str
    reason: str
    scope: str = "EXACT_DECLARED_EARTH_AND_SUN_RAY; J2_ENDPOINT_NUMERICAL_ERROR_ONLY"


@dataclass(frozen=True, slots=True)
class OrbitSunResult:
    query: OrbitSunQuery
    orbit_state: CartesianState | None
    sun_direction: CartesianDirection
    unit_sun_direction: CartesianDirection
    shadow: ShadowAssessment
    j2_evidence: J2EnclosureResult | None


# Exact rational interval algebra only for the derived quadratic, not an ODE.
def _add(x, y):
    return (x[0]+y[0], x[1]+y[1])


def _mul(x, y):
    p = [a*b for a in x for b in y]
    return min(p), max(p)


def _square(x):
    return (Fraction(0) if x[0] <= 0 <= x[1] else min(x[0]**2, x[1]**2),
            max(x[0]**2, x[1]**2))


def _coefficients(ellipsoid, direction, box):
    a = Fraction(ellipsoid.equatorial_radius_m.value)
    b = a * (1-Fraction(ellipsoid.flattening.value))
    q = (1/a**2, 1/a**2, 1/b**2)
    d = tuple(Fraction(v) for v in direction)
    A = sum(w*v*v for w, v in zip(q, d))
    B = (Fraction(0), Fraction(0))
    C = (Fraction(-1), Fraction(-1))
    for x, v, w in zip(box, d, q):
        B = _add(B, _mul(x, (v*w, v*w)))
        C = _add(C, _mul(_square(x), (w, w)))
    B2 = _square(B)
    AC = _mul((A, A), C)
    D = (AC[0]-B2[1], AC[1]-B2[0])
    return B, C, D


def _nominal(position, direction):
    point = tuple((Fraction(x), Fraction(x)) for x in position.components_m)
    B, C, D = _coefficients(position.frame.ellipsoid, direction.components, point)
    if C[0] <= 0:
        return "INVALID_POSITION"
    if B[0] >= 0 or D[0] > 0:
        return "ILLUMINATED"
    return "TANGENT" if D[0] == 0 else "OCCULTED"


def nominal_parallel_ray(position: CartesianPosition, sun: SuppliedSunDirection) -> str:
    """Exact nominal sign for represented point; no orbital error qualification."""
    _exact(position, CartesianPosition, "position")
    position = canonical_copy(position)
    sun = _sun(sun)
    direction, _ = _matching_direction(position.frame, position.instant, sun.direction)
    return _nominal(position, direction)


def _qualified(ellipsoid, direction, endpoints):
    box = tuple((Fraction(lo), Fraction(hi)) for lo, hi in endpoints[:3])
    B, C, D = _coefficients(ellipsoid, direction.components, box)
    if C[0] <= 0:
        return "UNRESOLVED", "ENDPOINT_BOX_NOT_STRICTLY_EXTERIOR"
    if B[0] >= 0 or D[0] > 0:
        return "ILLUMINATED", "J2_ENDPOINT_BOX_EXCLUDES_CLOSED_EARTH_RAY"
    if B[1] < 0 and D[1] <= 0:
        return "OCCULTED", "J2_ENDPOINT_BOX_INTERSECTS_CLOSED_EARTH_RAY"
    return "UNRESOLVED", "ENDPOINT_BOX_STRADDLES_SHADOW_BOUNDARY"


def _result(query, state, evidence):
    frame = query.coast.trajectory.initial_state.position.frame
    direction, rotated = _matching_direction(frame, query.instant, query.sun.direction)
    scale = max(abs(x) for x in direction.components)
    scaled = tuple(x/scale for x in direction.components)
    length = hypot(*scaled)
    unit = CartesianDirection(frame, query.instant, tuple(x/length for x in scaled))
    nominal = None if state is None else _nominal(state.position, direction)
    if evidence is not None and evidence.status != "enclosed":
        qualified, reason = "UNRESOLVED", "J2_F3_UNRESOLVED: "+str(evidence.reason)
    elif nominal == "INVALID_POSITION":
        qualified, reason = "UNRESOLVED", "NOMINAL_POSITION_NOT_STRICTLY_EXTERIOR"
    elif evidence is None:
        qualified, reason = "UNRESOLVED", "TWO_BODY_HAS_NO_COMPLETE_ENDPOINT_ENCLOSURE"
    elif rotated:
        qualified, reason = "UNRESOLVED", "SUN_FRAME_TRANSFORM_ERROR_NOT_ENCLOSED"
    else:
        qualified, reason = _qualified(frame.ellipsoid, direction, evidence.endpoint_intervals)
    return OrbitSunResult(query, state, direction, unit,
                          ShadowAssessment(nominal, qualified, reason), evidence)


def _evaluate_coast_at(coast, instant):
    """Internal shared dispatch; callers validate immutable query inputs first."""
    if type(coast) is CoastOrbitInputs:
        return evaluate_two_body_state(coast.trajectory, instant, coast.solver_config), None
    evidence = evaluate_j2_enclosure(coast.trajectory, instant,
                                    coast.solver_config, coast.enclosure_policy)
    return evidence.nominal_state, evidence


def evaluate_orbit_sun(query: OrbitSunQuery) -> OrbitSunResult:
    """Evaluate the original coast at query.instant; retain unresolved F3."""
    _exact(query, OrbitSunQuery, "query")
    query = OrbitSunQuery(query.coast, query.instant, query.sun)
    state, evidence = _evaluate_coast_at(query.coast, query.instant)
    return _result(query, state, evidence)


def evaluate_context_orbit_sun(context, sun: SuppliedSunDirection) -> OrbitSunResult:
    """Use accepted context validators/query paths; never advance the clock."""
    from .context import SimulationContext, evaluate_context_coast, evaluate_context_j2_enclosure
    from .engine import _validate_completed_context

    _exact(context, SimulationContext, "context")
    _validate_completed_context(context)
    coast = context.inputs.coast_orbit
    if type(coast) not in (CoastOrbitInputs, J2CoastOrbitInputs):
        raise TypeError("context requires existing coast input owner")
    epoch = coast.trajectory.initial_state.position.instant.epoch
    query = OrbitSunQuery(coast, GeometryInstant(epoch, context.simulation_time_seconds), sun)
    if type(coast) is CoastOrbitInputs:
        return _result(query, evaluate_context_coast(context), None)
    evidence = evaluate_context_j2_enclosure(context)
    return _result(query, evidence.nominal_state, evidence)
