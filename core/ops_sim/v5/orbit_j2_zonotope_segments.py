"""Original-anchor continuous SI tubes from the accepted all-set v3 transport.

No nominal coast, endpoint dispatch, supplied box or restart is used. One query
owns one v3 ledger; only completely published closed partitions are evidence.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from math import isfinite

from . import orbit_j2 as _coast
from . import orbit_j2_zonotope as _z
from .frames import CartesianPosition, CartesianState, CartesianVelocity
from .orbit_config import GeometryInstant, TTEpoch, _exact, _instant

SEGMENT_API_ID = "m2-j2-zonotope-segments-v1"
SEGMENT_API_VERSION = 1
PUBLICATION_VERSION = 1
_QUERY_CONTROL = 2048
_CELL_CONTROL = 1024 + 12 * (64 + 4 * 1024)
_FINAL_CONTROL = 2048 + 90 * (64 + 4 * 1024)
_PARTITION_PER_CELL = 256 + 12 * (32 + 1024)


def _fixed(value, expected, name):
    _exact(value, type(expected), name)
    if value != expected:
        raise ValueError("unsupported segment " + name)


def _structure(trajectory, end, policy):
    _exact(trajectory, _coast.J2CartesianTrajectory, "trajectory")
    _exact(trajectory.initial_state, CartesianState, "initial_state")
    state = trajectory.initial_state
    _exact(state.position, CartesianPosition, "position")
    _exact(state.velocity, CartesianVelocity, "velocity")
    _exact(trajectory.gravity_model, _coast.J2GravityModel, "gravity_model")
    _exact(policy, _z.J2ZonotopePolicyV3, "policy")
    _z._check_v3_policy_identity(policy)
    _exact(policy.base_policy, _z._old.J2EnclosurePolicy, "base_policy")
    p = policy.base_policy
    for name in ("step_seconds", "min_radius_m"):
        _exact(getattr(p, name), float, name)
    # Constant-size structural checks; no frame/provenance scan or force here.
    _z._old.J2EnclosurePolicy(p.step_seconds, p.max_steps, p.min_radius_m,
                              p.precision_digits, p.max_picard_iterations)
    _exact(policy.scale_exponents, tuple, "scale_exponents")
    if len(policy.scale_exponents) != 6:
        raise ValueError("six scales required")
    for value in policy.scale_exponents:
        _exact(value, int, "scale exponent")
        if not -32 <= value <= 32:
            raise ValueError("scale exponent outside [-32,32]")
    _exact(policy.max_scalar_operations, int, "max_scalar_operations")
    if not 1 <= policy.max_scalar_operations <= 2**31:
        raise ValueError("scalar ceiling outside [1,2**31]")
    for vector in (state.position, state.velocity):
        _exact(vector.components_m if vector is state.position else vector.components_m_per_s,
               tuple, "components")
        values = vector.components_m if vector is state.position else vector.components_m_per_s
        if len(values) != 3:
            raise ValueError("three SI components required")
        for value in values:
            _exact(value, float, "SI component")
            if not isfinite(value):
                raise ValueError("finite SI component required")
    _exact(end, GeometryInstant, "end")
    for instant in (state.position.instant, state.velocity.instant, end):
        _exact(instant, GeometryInstant, "instant")
        _exact(instant.elapsed_seconds, float, "elapsed seconds")
    origin = state.position.instant
    for epoch in (origin.epoch, end.epoch):
        _exact(epoch, TTEpoch, "epoch")
        # Epoch constructor is a bounded scalar schema check, not TT-date/grid arithmetic.
        TTEpoch(epoch.julian_day, epoch.fractional_day)
    if not isfinite(origin.elapsed_seconds) or not isfinite(end.elapsed_seconds):
        raise ValueError("finite elapsed seconds required")
    if origin.epoch != end.epoch:
        raise ValueError("same original TT epoch required")
    if not origin.elapsed_seconds < end.elapsed_seconds:
        raise ValueError("forward nonempty original-anchor span required")


@dataclass(frozen=True, slots=True)
class J2ZonotopeSegmentRequest:
    trajectory: _coast.J2CartesianTrajectory
    end: GeometryInstant
    policy: _z.J2ZonotopePolicyV3
    api_id: str = field(init=False, default=SEGMENT_API_ID)
    api_version: int = field(init=False, default=SEGMENT_API_VERSION)
    publication_version: int = field(init=False, default=PUBLICATION_VERSION)

    __hash__ = None

    def __post_init__(self):
        _structure(self.trajectory, self.end, self.policy)


def _request(request):
    _exact(request, J2ZonotopeSegmentRequest, "request")
    for name, expected in (("api_id", SEGMENT_API_ID), ("api_version", 1),
                           ("publication_version", PUBLICATION_VERSION)):
        _fixed(getattr(request, name), expected, name)
    _structure(request.trajectory, request.end, request.policy)
    return request


def _time(value):
    _exact(value, Fraction, "elapsed seconds")
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > 4096:
        raise ValueError("time exceeds accepted rational domain")


def _plain_vector(values):
    _exact(values, tuple, "plain vector")
    if len(values) != 6:
        raise ValueError("six components required")
    for value in values:
        _exact(value, Decimal, "plain Decimal")
        if not value.is_finite():
            raise ValueError("finite plain Decimal required")


@dataclass(frozen=True, slots=True)
class J2ZonotopeSegmentCell:
    """Whole closed source support; SI bounds enclose every time on that step."""
    start_seconds: Fraction
    end_seconds: Fraction
    source_step_index: int
    source_start_seconds: Fraction
    source_end_seconds: Fraction
    position_bounds_m: tuple[tuple[Decimal, Decimal], ...]
    velocity_bounds_m_per_s: tuple[tuple[Decimal, Decimal], ...]

    def __post_init__(self):
        for t in (self.start_seconds, self.end_seconds,
                  self.source_start_seconds, self.source_end_seconds):
            _time(t)
        _exact(self.source_step_index, int, "source_step_index")
        if not 0 <= self.source_step_index < 4096:
            raise ValueError("source step outside bounded grid")
        if (not self.start_seconds < self.end_seconds or
                self.start_seconds != self.source_start_seconds or
                self.end_seconds != self.source_end_seconds):
            raise ValueError("whole forward closed source support required")
        for vector in (self.position_bounds_m, self.velocity_bounds_m_per_s):
            _exact(vector, tuple, "component bounds")
            if len(vector) != 3:
                raise ValueError("three Cartesian bounds required")
            for pair in vector:
                _exact(pair, tuple, "interval pair")
                if len(pair) != 2:
                    raise ValueError("two interval endpoints required")
                for value in pair:
                    _exact(value, Decimal, "plain interval endpoint")
                    if not value.is_finite():
                        raise ValueError("finite interval endpoint required")
                if pair[0] > pair[1]:
                    raise ValueError("reversed interval")


@dataclass(frozen=True, slots=True)
class J2ZonotopeSegmentDiagnostic:
    """Plain derived scaled set; its scales/frame belong to result.request.

    This record is never accepted as propagation or checkpoint authority.
    """
    center: tuple[Decimal, ...]
    generators: tuple[tuple[Decimal, ...], ...]
    births: tuple[int, ...]
    time: Fraction

    def __post_init__(self):
        _plain_vector(self.center)
        _exact(self.generators, tuple, "generators")
        _exact(self.births, tuple, "births")
        if len(self.generators) > 12 or len(self.births) != len(self.generators):
            raise ValueError("reduced diagnostic shape required")
        for column in self.generators:
            _plain_vector(column)
        for birth in self.births:
            _exact(birth, int, "birth")
            if not 0 <= birth <= 2**20:
                raise ValueError("birth outside accepted domain")
        if len(set(self.births)) != len(self.births):
            raise ValueError("duplicate birth")
        _time(self.time)


def _publish_bounds(tube, ar):
    """Exact plain copies: no rounding, ambient arithmetic or float cast."""
    ar.charge(2)
    if type(tube) is not tuple or len(tube) != 6:
        raise _z._Unresolved("six SI tube intervals required")
    output = []
    for interval in tube:
        ar.charge()
        _exact(interval, _z._I, "transport interval")
        ar.charge(2)
        for bound in (interval.lo, interval.hi):
            if type(bound) not in (Decimal, _z._D):
                raise _z._Unresolved("unsupported proof endpoint type")
            if type(bound) is _z._D and bound._ar is not ar:
                raise _z._Unresolved("mixed query publication endpoint")
        _z._decimal_rank_admission(interval.lo, ar)
        _z._decimal_rank_admission(interval.hi, ar)
        lo, hi = ar.point(interval.lo).lo, ar.point(interval.hi).hi
        if lo > hi:
            raise _z._Unresolved("reversed transport interval")
        output.append((_z._plain(lo, ar), _z._plain(hi, ar)))
    return tuple(output)


# Local seams preserve the accepted source; tests may inject failures HERE.
_transport = _z._transport_step_v3


def _publish_cell(tube, start, end, index, ar):
    ar.reserve(_CELL_CONTROL, "segment closed-cell validation/copy/allocation")
    bounds = _publish_bounds(tube, ar)
    return J2ZonotopeSegmentCell(start, end, index, start, end, bounds[:3], bounds[3:])


@dataclass(frozen=True, slots=True)
class J2ZonotopeSegmentResult:
    request: J2ZonotopeSegmentRequest
    status: str = field(init=False, default="unresolved")
    reason: str | None = field(init=False, default=None)
    cells: tuple[J2ZonotopeSegmentCell, ...] | None = field(init=False, default=None)
    final_endpoint_intervals: tuple[tuple[Decimal, Decimal], ...] | None = field(init=False, default=None)
    final_diagnostic: J2ZonotopeSegmentDiagnostic | None = field(init=False, default=None)
    planned_steps: int = field(init=False, default=0)
    attempted_steps: int = field(init=False, default=0)
    completed_steps: int = field(init=False, default=0)
    picard_attempts: int = field(init=False, default=0)
    reductions: int = field(init=False, default=0)
    charged_leaf_operations: int = field(init=False, default=0)
    reserved_control_operations: int = field(init=False, default=0)
    scalar_operations: int = field(init=False, default=0)
    budget_rejected: bool = field(init=False, default=False)
    api_id: str = field(init=False, default=SEGMENT_API_ID)
    api_version: int = field(init=False, default=1)
    publication_version: int = field(init=False, default=PUBLICATION_VERSION)
    transport_resource_policy_version: int = field(init=False, default=3)
    kernel_id: str = field(init=False, default="incremental-j2-jet-v1")
    method_id: str = field(init=False, default=_z.METHOD_ID)
    method_version: int = field(init=False, default=1)

    __hash__ = None

    def __post_init__(self):
        request = _request(self.request)
        p = request.policy
        ar = _z._CoefficientArithmeticV3(p.base_policy.precision_digits, p.max_scalar_operations)
        try:
            self._evaluate(ar)
        except Exception as error:
            object.__setattr__(self, "reason", type(error).__name__ + ": " + str(error))
        finally:
            # Diagnostic retention only; no proof work/charge after rejection.
            for key, value in (("attempted_steps", ar.attempted_steps),
                               ("completed_steps", ar.completed_steps),
                               ("picard_attempts", ar.picard_attempts),
                               ("reductions", ar.reductions),
                               ("charged_leaf_operations", ar.leaf_operations),
                               ("reserved_control_operations", ar.reserved_units),
                               ("scalar_operations", ar.operations),
                               ("budget_rejected", ar.rejected)):
                object.__setattr__(self, key, value)

    def _evaluate(self, ar):
        ar.reserve(_QUERY_CONTROL, "segment structural normalization/grid/control")
        req = self.request
        p = _z.J2ZonotopePolicyV3(req.policy.base_policy, req.policy.scale_exponents,
                                  req.policy.max_scalar_operations)
        _z._reserve_authority_metadata(req.trajectory, ar)
        state, model = _coast._authorities(req.trajectory.initial_state, req.trajectory.gravity_model)
        ar.charge(3)
        trajectory = object.__new__(_coast.J2CartesianTrajectory)
        object.__setattr__(trajectory, "initial_state", state)
        object.__setattr__(trajectory, "gravity_model", model)
        end_instant = _instant(req.end)
        normalized = J2ZonotopeSegmentRequest(trajectory, end_instant, p)
        object.__setattr__(self, "request", normalized)
        anchor = _z._fraction(state.position.instant.elapsed_seconds, ar)
        end = _z._fraction(end_instant.elapsed_seconds, ar)
        span = _z._radd(end, _z._rmul(_z._fraction(-1, ar), anchor, ar), ar)
        step = _z._fraction(p.base_policy.step_seconds, ar)
        ar.charge(8)  # exact divmod, count, integer/boolean and ceiling guards
        full, remainder = divmod(span, step)
        count = int(full + bool(remainder))
        object.__setattr__(self, "planned_steps", count)
        if _z._rcompare(span, _z._fraction(86400, ar), ar) > 0 or count > p.base_policy.max_steps:
            raise _z._Unresolved("horizon or segment-step ceiling exceeded before transport")
        values = (*state.position.components_m, *state.velocity.components_m_per_s,
                  model.gravitational_parameter_m3_s2.value, model.j2.value,
                  model.reference_radius_m.value, p.base_policy.step_seconds)
        ar.charge(40)  # ten constant-size finite/envelope checks before execution
        if any(v != 0 and not 1e-100 <= abs(v) <= 1e100 for v in values):
            raise _z._Unresolved("dynamical input outside F3 arithmetic envelope")
        z = _z._initial_set(values[:6], p.scale_exponents, ar, anchor)
        ar.reserve(128, "initial domain legacy control")
        _z._old._domain(_z._project_box(z, p.scale_exponents, ar), p.base_policy, ar)
        ar.reserve(64, "bounded internal cell list allocation")
        pending = []
        for index in range(count):
            ar.charge(4)  # grid selection/index/control before execution
            duration = step if index < full else remainder
            start = _z._radd(anchor, _z._rmul(_z._fraction(index, ar), step, ar), ar)
            if _z._rcompare(z.time, start, ar) != 0:
                raise _z._Unresolved("transport time differs from original grid")
            next_time = _z._radd(start, duration, ar)
            h = ar.div(ar.point(duration.numerator), ar.point(duration.denominator))
            # Full propagated set carried across steps. Returned tube is SI.
            z, tube = _transport(z, h, model, p, ar, index, next_time)
            cell = _publish_cell(tube, start, next_time, index, ar)
            ar.reserve(16, "internal cell list append")
            pending.append(cell)
        ar.reserve(_FINAL_CONTROL + _PARTITION_PER_CELL * count,
                   "complete partition/final diagnostic validation/publication")
        if (len(pending) != count or not pending or
                _z._rcompare(pending[0].start_seconds, anchor, ar) != 0 or
                _z._rcompare(pending[-1].end_seconds, end, ar) != 0):
            raise _z._Unresolved("incomplete closed partition")
        for index, cell in enumerate(pending):
            cell.__post_init__()
            if cell.source_step_index != index:
                raise _z._Unresolved("source step identity mismatch")
            if index and _z._rcompare(pending[index-1].end_seconds, cell.start_seconds, ar) != 0:
                raise _z._Unresolved("gap in closed partition")
        final_box = _z._project_box(z, p.scale_exponents, ar)
        endpoints = _publish_bounds(final_box, ar)
        plain = _z._plain_set(z, ar)
        diagnostic = J2ZonotopeSegmentDiagnostic(plain.center, plain.generators, plain.births, plain.time)
        if _z._rcompare(diagnostic.time, end, ar) != 0:
            raise _z._Unresolved("final diagnostic time mismatch")
        # Complete atomic publication only after every debit/check succeeded.
        cells = tuple(pending)
        for name, value in (("cells", cells), ("final_endpoint_intervals", endpoints),
                             ("final_diagnostic", diagnostic), ("status", "enclosed")):
            object.__setattr__(self, name, value)


def evaluate_j2_zonotope_segments(request):
    return J2ZonotopeSegmentResult(request)


__all__ = ["J2ZonotopeSegmentRequest", "J2ZonotopeSegmentCell",
           "J2ZonotopeSegmentDiagnostic", "J2ZonotopeSegmentResult",
           "evaluate_j2_zonotope_segments"]
