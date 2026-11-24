"""Continuous conditional illumination of the declared J2/affine-Sun model.

All geometry uses exact rational interval arithmetic. Actual ephemeris and
alignment errors remain unbounded; combined qualification is always unresolved.
"""
from bisect import bisect_right
from dataclasses import dataclass, field
from fractions import Fraction as Q

from .orbit_config import GeometryInstant, _exact
from .orbit_j2_binding import J2CoastOrbitInputs
from . import orbit_j2_segments as _segments
from .sun_table import SunPositionTable, _table


# 4096 J2 cells plus at most 1022 interior Sun knots, never their product.
MAX_GEOMETRY_CELLS = 5118
MAX_RATIONAL_BITS = 16384
MAX_CELL_OPERATIONS = 512
ASSESSMENT_SCOPE = "DECLARED_J2_AND_AFFINE_SUN_MODEL_WITH_B1_COMPONENT_ROUNDING"
COMBINED_REASONS = (
    "PHYSICAL_EPHEMERIS_ERROR_UNQUANTIFIED",
    "INTERPOLATION_UNIFORM_PHYSICAL_ERROR_UNQUANTIFIED",
    "SOURCE_TIME_ERROR_UNQUANTIFIED",
    "FRAME_ALIGNMENT_ERROR_UNQUANTIFIED",
    "INITIAL_STATE_AND_GRAVITY_MODEL_ERROR_NOT_BOUNDED",
)


@dataclass(frozen=True, slots=True)
class IntervalIlluminationPolicy:
    max_cells: int

    def __post_init__(self):
        _exact(self.max_cells, int, "max_cells")
        if not 1 <= self.max_cells <= MAX_GEOMETRY_CELLS:
            raise ValueError("max_cells must be in [1, 5118]")


@dataclass(frozen=True, slots=True)
class IntervalIlluminationRequest:
    coast: J2CoastOrbitInputs
    table: SunPositionTable
    start: GeometryInstant
    end: GeometryInstant
    policy: IntervalIlluminationPolicy

    __hash__ = None

    def __post_init__(self):
        # B2 rebuilds complete F4, frame, epoch and instant authorities.
        segment = _segments.J2SegmentRequest(self.coast, self.start, self.end)
        table = _table(self.table)
        _exact(self.policy, IntervalIlluminationPolicy, "policy")
        policy = IntervalIlluminationPolicy(self.policy.max_cells)
        anchor = segment.coast.trajectory.initial_state.position
        if anchor.frame != table.frame or anchor.instant.epoch != table.epoch:
            raise ValueError("orbit/table complete model frames and TT epochs must match")
        if not table.domain_seconds[0] <= segment.start.elapsed_seconds < segment.end.elapsed_seconds <= table.domain_seconds[1]:
            raise ValueError("entire interval must lie inside the closed Sun-table domain")
        for name, value in (("coast", segment.coast), ("table", table),
                            ("start", segment.start), ("end", segment.end), ("policy", policy)):
            object.__setattr__(self, name, value)


def _request(value):
    _exact(value, IntervalIlluminationRequest, "request")
    return IntervalIlluminationRequest(value.coast, value.table, value.start, value.end, value.policy)


class _WorkFailure(Exception):
    pass


class _Rational:
    """Bounded exact arithmetic; no empirical tolerances or Decimal context."""
    def __init__(self):
        self.operations = 0
        self.limit = MAX_CELL_OPERATIONS  # also bounds constant shape setup

    @staticmethod
    def checked(value):
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_RATIONAL_BITS:
            raise _WorkFailure("rational numerator/denominator bit ceiling exceeded")
        return value

    def point(self, value):
        x = self.checked(Q(value))
        return x, x

    def scalar(self, op, a, b):
        self.checked(a); self.checked(b)
        if self.operations >= self.limit:
            raise _WorkFailure("geometry rational-operation budget exhausted")
        self.operations += 1
        if op == "add": value = a+b
        elif op == "sub": value = a-b
        elif op == "mul": value = a*b
        else: value = a/b
        return self.checked(value)

    def add(self, a, b):
        return self.scalar("add", a[0], b[0]), self.scalar("add", a[1], b[1])

    def sub(self, a, b):
        return self.scalar("sub", a[0], b[1]), self.scalar("sub", a[1], b[0])

    def mul(self, a, b):
        products = tuple(self.scalar("mul", x, y) for x in a for y in b)
        return min(products), max(products)

    def square(self, a):
        squares = tuple(self.scalar("mul", x, x) for x in a)
        return (Q(0) if a[0] <= 0 <= a[1] else min(squares)), max(squares)

    def total(self, intervals):
        value = self.point(0)
        for interval in intervals:
            value = self.add(value, interval)
        return value

    def begin_cell(self):
        self.limit = self.operations + MAX_CELL_OPERATIONS


def _refinement_plan(segment, table):
    """Exact time-only preflight, bounded by B2's admitted step count.

    None means B2's own horizon/work gate will reject; call that owner once to
    retain its actual failure evidence, with no expensive integration.
    """
    anchor, start, end, step, legs, count = _segments._plan(segment)
    if count > segment.coast.enclosure_policy.max_steps or any(abs(d) > 86400 for d, _, _ in legs):
        return None
    boundaries = {start, end}
    for span, full, tail in legs:
        sign = -1 if span < 0 else 1
        for k in range(1, full+1):
            t = anchor+sign*k*step
            if start < t < end:
                boundaries.add(t)
        # The tail ends at the far request boundary already included above.
    if start < anchor < end:
        boundaries.add(anchor)
    boundaries.update(Q(s.elapsed_seconds) for s in table.samples if start < Q(s.elapsed_seconds) < end)
    return tuple(sorted(boundaries))


def _sun_envelope(table, index, start, end, ar):
    left, right = table.samples[index:index+2]
    t0, t1 = Q(left.elapsed_seconds), Q(right.elapsed_seconds)
    span = ar.scalar("sub", t1, t0)
    weights = tuple(ar.scalar("div", ar.scalar("sub", t, t0), span) for t in (start, end))
    if not 0 <= weights[0] < weights[1] <= 1:
        raise _WorkFailure("internal Sun interpolation partition mismatch")
    exact, envelope = [], []
    for a, b in zip(left.position_m, right.position_m):
        a, b = Q(a), Q(b)
        delta = ar.scalar("sub", b, a)
        values = tuple(ar.scalar("add", a, ar.scalar("mul", w, delta)) for w in weights)
        lo, hi = min(values), max(values)
        exact.append((lo, hi))
        # Correctly rounded rational->binary64 conversion is monotone. Thus
        # min(lo,RN(lo)), max(hi,RN(hi)) contains the exact affine range AND
        # RN(x) for every x in that range, including subnormal/zero results.
        # Convex interpolation of finite nodes cannot overflow binary64.
        rounded_lo, rounded_hi = Q(float(lo)), Q(float(hi))
        envelope.append((min(lo, rounded_lo), max(hi, rounded_hi)))
    return weights, tuple(exact), tuple(envelope)


def _shape_weights(ellipsoid, ar):
    a, f = Q(ellipsoid.equatorial_radius_m.value), Q(ellipsoid.flattening.value)
    b = ar.scalar("mul", a, ar.scalar("sub", Q(1), f))
    equator = ar.scalar("div", Q(1), ar.scalar("mul", a, a))
    polar = ar.scalar("div", Q(1), ar.scalar("mul", b, b))
    return equator, equator, polar


def _geometry(position, sun, weights, ar):
    direction = tuple(ar.sub(s, r) for s, r in zip(sun, position))
    A = ar.total(ar.mul(ar.square(d), (q, q)) for d, q in zip(direction, weights))
    B = ar.total(ar.mul(ar.mul(r, d), (q, q)) for r, d, q in zip(position, direction, weights))
    C = ar.sub(ar.total(ar.mul(ar.square(r), (q, q)) for r, q in zip(position, weights)), ar.point(1))
    D = ar.sub(ar.mul(A, C), ar.square(B))
    sun_norm = ar.total(ar.square(s) for s in sun)
    if sun_norm[0] <= 0:
        assessment, reason = "UNRESOLVED", "SUN_VECTOR_NONZERO_NOT_ESTABLISHED"
    elif C[0] <= 0:
        assessment, reason = "UNRESOLVED", "SPACECRAFT_NOT_PROVEN_STRICTLY_EXTERIOR"
    elif A[0] <= 0:
        assessment, reason = "UNRESOLVED", "SPACECRAFT_TO_SUN_NONZERO_NOT_ESTABLISHED"
    elif B[0] >= 0 or D[0] > 0:
        assessment, reason = "ILLUMINATED", "WHOLE_CELL_EXCLUDES_CLOSED_EARTH_HALF_RAY"
    elif B[1] < 0 and D[1] <= 0:
        assessment, reason = "OCCULTED", "WHOLE_CELL_MEETS_CLOSED_EARTH_HALF_RAY_INCLUDING_CONTACT"
    else:
        assessment, reason = "UNRESOLVED", "SHADOW_BOUNDARY_OR_DEPENDENCY_AMBIGUITY"
    return direction, A, B, C, D, sun_norm, assessment, reason


@dataclass(frozen=True, slots=True)
class IntervalIlluminationCell:
    """Derived evidence only; exact elapsed seconds and SI rational bounds.

    j2_cell_index references result.j2_evidence.cells without shrinking its
    position/velocity tube. Sun index references the original adjacent nodes.
    Quadratic A,B,C,D are dimensionless with d expressed in metres and lambda
    dimensionless. Closed cells share endpoints. No event accuracy is claimed.
    """
    start_seconds: Q
    end_seconds: Q
    j2_cell_index: int
    sun_segment_index: int
    sun_weights: tuple[Q, Q]
    exact_sun_bounds_m: tuple
    provider_sun_bounds_m: tuple
    position_bounds_m: tuple
    direction_bounds_m: tuple
    A: tuple[Q, Q]
    B: tuple[Q, Q]
    C: tuple[Q, Q]
    D: tuple[Q, Q]
    sun_norm_squared_m2: tuple[Q, Q]
    assessment: str
    reason: str
    scope: str = field(init=False, default=ASSESSMENT_SCOPE)


def _geometry_cell(table, source, j2_index, sun_index, start, end, weights, ar):
    """Shared unchanged whole-cell envelope/ray kernel; does not propagate."""
    ar.begin_cell()
    interpolation, exact, sun = _sun_envelope(table, sun_index, start, end, ar)
    position = tuple((ar.checked(Q(lo)), ar.checked(Q(hi))) for lo, hi in source.position_bounds_m)
    geometry = _geometry(position, sun, weights, ar)
    return IntervalIlluminationCell(start, end, j2_index, sun_index, interpolation,
                                    exact, sun, position, *geometry)


@dataclass(frozen=True, slots=True)
class IntervalIlluminationResult:
    """Complete partition is separate from classification and physical truth.

    status='complete' may include UNRESOLVED geometry cells. Computational
    failure has status='unresolved', cells=None, and preserved upstream/work
    diagnostics. Only the request is constructible reconstruction authority.
    """
    request: IntervalIlluminationRequest
    status: str = field(init=False, default="unresolved")
    reason: str | None = field(init=False, default=None)
    cells: tuple[IntervalIlluminationCell, ...] | None = field(init=False, default=None)
    j2_evidence: _segments.J2SegmentResult | None = field(init=False, default=None)
    planned_geometry_cells: int | None = field(init=False, default=None)
    geometry_cells_evaluated: int = field(init=False, default=0)
    arithmetic_operations: int = field(init=False, default=0)
    propagation_calls: int = field(init=False, default=0)
    all_cells_classified: bool = field(init=False, default=False)
    combined_qualification: str = field(init=False, default="UNRESOLVED")
    combined_reasons: tuple[str, ...] = field(init=False, default=COMBINED_REASONS)

    __hash__ = None

    def __post_init__(self):
        object.__setattr__(self, "request", _request(self.request))
        ar = _Rational()
        try:
            self._evaluate(ar)
        except (_WorkFailure, OverflowError, ZeroDivisionError) as error:
            object.__setattr__(self, "reason", str(error) or type(error).__name__)
        finally:
            object.__setattr__(self, "arithmetic_operations", ar.operations)

    def _evaluate(self, ar):
        request = self.request
        segment = _segments.J2SegmentRequest(request.coast, request.start, request.end)
        plan = _refinement_plan(segment, request.table)
        if plan is not None:
            count = len(plan)-1
            object.__setattr__(self, "planned_geometry_cells", count)
            if count > request.policy.max_cells or count > MAX_GEOMETRY_CELLS:
                raise _WorkFailure("geometry-cell budget exceeded before propagation")
        object.__setattr__(self, "propagation_calls", 1)
        evidence = _segments.evaluate_j2_segments(segment)
        object.__setattr__(self, "j2_evidence", evidence)
        if evidence.status != "enclosed":
            raise _WorkFailure("J2_SEGMENTS_UNRESOLVED: "+str(evidence.reason))
        if plan is None:
            raise _WorkFailure("upstream preflight/coverage contract mismatch")
        weights = _shape_weights(request.table.frame.ellipsoid, ar)
        knots = tuple(Q(s.elapsed_seconds) for s in request.table.samples)
        j = 0
        k = bisect_right(knots, plan[0])-1
        cells = []
        for start, end in zip(plan, plan[1:]):
            while j+1 < len(evidence.cells) and evidence.cells[j].end_seconds <= start:
                j += 1
            while k+1 < len(knots)-1 and knots[k+1] <= start:
                k += 1
            source = evidence.cells[j]
            if not source.start_seconds <= start < end <= source.end_seconds:
                raise _WorkFailure("J2/refinement coverage mismatch")
            cells.append(_geometry_cell(request.table, source, j, k, start, end, weights, ar))
            object.__setattr__(self, "geometry_cells_evaluated", len(cells))
        if not cells or cells[0].start_seconds != Q(request.start.elapsed_seconds) or cells[-1].end_seconds != Q(request.end.elapsed_seconds):
            raise _WorkFailure("incomplete final coverage")
        object.__setattr__(self, "cells", tuple(cells))
        object.__setattr__(self, "all_cells_classified", all(c.assessment != "UNRESOLVED" for c in cells))
        object.__setattr__(self, "status", "complete")


def evaluate_interval_illumination(request) -> IntervalIlluminationResult:
    return IntervalIlluminationResult(request)


__all__ = ["IntervalIlluminationPolicy", "IntervalIlluminationRequest", "IntervalIlluminationCell",
           "IntervalIlluminationResult", "evaluate_interval_illumination"]
