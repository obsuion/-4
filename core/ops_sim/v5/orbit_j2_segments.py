"""Bounded continuous J2 evidence from the original F4 input authority.

Cells export the actual F3 validated Picard tubes, not endpoint hulls or
nominal samples. All elapsed time boundaries are exact Fractions in seconds
relative to request.start.epoch. See M2_J2_SEGMENTS.md for the proof scope.
"""
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException
from fractions import Fraction

from .experiment_codec import canonical_copy
from .orbit_config import GeometryInstant, _exact
from .orbit_j2_binding import J2CoastOrbitInputs
from . import orbit_j2_enclosure as _f3


@dataclass(frozen=True, slots=True)
class J2SegmentRequest:
    """Complete immutable original authorities and a nonempty closed interval."""

    coast: J2CoastOrbitInputs
    start: GeometryInstant
    end: GeometryInstant

    __hash__ = None

    def __post_init__(self):
        _exact(self.coast, J2CoastOrbitInputs, "coast")
        _exact(self.start, GeometryInstant, "start")
        _exact(self.end, GeometryInstant, "end")
        # The accepted codec rebuilds every nested owner, including versions,
        # frame definitions and provenance. No deferred scenario owner is used.
        coast, start, end = canonical_copy((self.coast, self.start, self.end))
        epoch = coast.trajectory.initial_state.position.instant.epoch
        if start.epoch != epoch or end.epoch != epoch:
            raise ValueError("segment instants must retain the original TT epoch")
        if not start.elapsed_seconds < end.elapsed_seconds:
            raise ValueError("segment requires start < end")
        for name, value in (("coast", coast), ("start", start), ("end", end)):
            object.__setattr__(self, name, value)


def _request(request):
    _exact(request, J2SegmentRequest, "request")
    return J2SegmentRequest(request.coast, request.start, request.end)


@dataclass(frozen=True, slots=True)
class J2SegmentCell:
    """Derived closed coverage with directed source-step provenance.

    All times are exact elapsed SI seconds in the request TT reference epoch.
    Position/velocity bounds are MODEL_INERTIAL x,y,z in m and m/s; the full
    concrete frame is retained by result.request.coast. Source times preserve
    the direction of integration; coverage times are always chronological.
    The full source-step tube is retained even for clipped coverage.
    """

    start_seconds: Fraction
    end_seconds: Fraction
    source_initial_seconds: Fraction
    source_final_seconds: Fraction
    position_bounds_m: tuple[tuple[Decimal, Decimal], ...]
    velocity_bounds_m_per_s: tuple[tuple[Decimal, Decimal], ...]

    def __post_init__(self):
        for name in ("start_seconds", "end_seconds", "source_initial_seconds",
                     "source_final_seconds"):
            _exact(getattr(self, name), Fraction, name)
        lower, upper = sorted((self.source_initial_seconds, self.source_final_seconds))
        if not lower <= self.start_seconds < self.end_seconds <= upper:
            raise ValueError("nonempty cell must lie within its source step")
        for name in ("position_bounds_m", "velocity_bounds_m_per_s"):
            value = getattr(self, name)
            _exact(value, tuple, name)
            if len(value) != 3:
                raise ValueError("three Cartesian component intervals required")
            for pair in value:
                _exact(pair, tuple, "component interval")
                if len(pair) != 2:
                    raise ValueError("lower and upper bound required")
                for bound in pair:
                    _exact(bound, Decimal, "bound")
                    if not bound.is_finite():
                        raise ValueError("finite Decimal bounds required")
                if pair[0] > pair[1]:
                    raise ValueError("reversed component interval")


def _plan(request):
    """Constant-size exact plan. No cell collection or numerical integration."""
    anchor = Fraction(request.coast.trajectory.initial_state.position.instant.elapsed_seconds)
    start, end = Fraction(request.start.elapsed_seconds), Fraction(request.end.elapsed_seconds)
    step = Fraction(request.coast.enclosure_policy.step_seconds)
    # At most two legs, each starting at the SAME original authority.
    spans = tuple(x for x in (min(start-anchor, Fraction(0)),
                             max(end-anchor, Fraction(0))) if x)
    legs = []
    for span in spans:
        full, tail = divmod(abs(span), step)
        legs.append((span, full, tail))
    return anchor, start, end, step, tuple(legs), sum(full+bool(tail) for _, full, tail in legs)


def _initial_box(coast, ar):
    """Shared original-point admission; no propagation or derived seed input."""
    state, model = coast.trajectory.initial_state, coast.trajectory.gravity_model
    values = (*state.position.components_m, *state.velocity.components_m_per_s,
              model.gravitational_parameter_m3_s2.value, model.j2.value,
              model.reference_radius_m.value, coast.solver_config.step_seconds)
    if any(x != 0 and not 1e-100 <= abs(x) <= 1e100 for x in values):
        raise _f3._Unresolved("dynamical input outside F3 arithmetic envelope")
    initial = [ar.point(x) for x in values[:6]]
    _f3._domain(initial, coast.enclosure_policy, ar)
    return initial


def _validated_step(box, signed_duration, model, policy, ar):
    """One unchanged F3 call, returning its endpoint AND continuous tube."""
    h = ar.div(ar.point(signed_duration.numerator), ar.point(signed_duration.denominator))
    return _f3._step_with_tube(box, h, model, policy, ar)


@dataclass(frozen=True, slots=True)
class J2SegmentResult:
    """Atomic recomputed evidence; no cells are exposed on UNRESOLVED.

    Completed Taylor steps and all attempted Picard inclusions are diagnostic
    counts. planned_steps includes every prefix and both signed legs. There is
    no nominal evaluation, nominal bound, event, illumination or visibility flag.
    Only request is an input; constructing/replacing a result recomputes it.
    """

    request: J2SegmentRequest
    status: str = field(init=False, default="unresolved")
    reason: str | None = field(init=False, default=None)
    cells: tuple[J2SegmentCell, ...] | None = field(init=False, default=None)
    planned_steps: int = field(init=False, default=0)
    enclosure_steps: int = field(init=False, default=0)
    picard_attempts: int = field(init=False, default=0)
    nominal_steps: int = field(init=False, default=0)
    policy_version: int = field(init=False, default=1)

    __hash__ = None

    def __post_init__(self):
        request = _request(self.request)
        object.__setattr__(self, "request", request)
        ar = _f3._Arithmetic(request.coast.enclosure_policy.precision_digits)
        try:
            self._evaluate(ar)
        except (_f3._Unresolved, DecimalException, OverflowError) as error:
            object.__setattr__(self, "reason", str(error) or type(error).__name__)
        finally:
            object.__setattr__(self, "picard_attempts", ar.picard_attempts)

    def _evaluate(self, ar):
        request = self.request
        coast = request.coast
        policy = coast.enclosure_policy
        anchor, start, end, step, legs, count = _plan(request)
        object.__setattr__(self, "planned_steps", count)
        # One total ceiling: prefixes and both signed legs count. The horizon
        # applies to each original-anchor span, as in F3 endpoint admission.
        if any(abs(span) > 86400 for span, _, _ in legs) or count > policy.max_steps:
            raise _f3._Unresolved("horizon or total enclosure-step budget exceeded before integration")
        model = coast.trajectory.gravity_model
        initial = _initial_box(coast, ar)
        # Allocation only after exact work/domain admission. At most 4096 cells,
        # with 6 pairs of Decimal endpoints each, and 65536 Picard attempts.
        cells = []
        for span, full, tail in legs:
            box = initial
            sign = -1 if span < 0 else 1
            source_initial = anchor
            for index in range(full+bool(tail)):
                duration = step if index < full else tail
                signed_duration = sign*duration
                source_final = source_initial+signed_duration
                box, tube, _ = _validated_step(box, signed_duration, model, policy, ar)
                object.__setattr__(self, "enclosure_steps", self.enclosure_steps+1)
                lo, hi = sorted((source_initial, source_final))
                lo, hi = max(start, lo), min(end, hi)
                if lo < hi:
                    bounds = tuple((a.lo, a.hi) for a in tube)
                    cells.append(J2SegmentCell(lo, hi, source_initial, source_final,
                                               bounds[:3], bounds[3:]))
                source_initial = source_final
        cells.sort(key=lambda cell: cell.start_seconds)
        # No publication until every leg and the complete covering partition
        # has succeeded. These are internal assertions, not physics tolerances.
        if (not cells or cells[0].start_seconds != start or cells[-1].end_seconds != end
                or any(a.end_seconds != b.start_seconds for a, b in zip(cells, cells[1:]))):
            raise _f3._Unresolved("internal continuous coverage partition failed")
        object.__setattr__(self, "cells", tuple(cells))
        object.__setattr__(self, "status", "enclosed")


def evaluate_j2_segments(request) -> J2SegmentResult:
    return J2SegmentResult(request)


__all__ = ["J2SegmentRequest", "J2SegmentCell", "J2SegmentResult", "evaluate_j2_segments"]
