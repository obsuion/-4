"""Bounded, origin-anchored accumulated J2 error, policy version 1.

An outward-rounded Decimal box Taylor integrator encloses the real solution
of F1's mathematical field for the exact represented initial data. It does
not replace F2: the nominal result is obtained from F2 without alteration.
Endpoint distance to that represented result includes ALL its RK/force
rounding and truncation. See V5_J2_ENCLOSURE.md for the derivation, arithmetic
assumptions, admission limits and wrapping limitations. This is a tested
numerical enclosure implementation, not a machine-checked formal proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import (
    Context, Decimal, DecimalException, DivisionByZero, InvalidOperation,
    Overflow, ROUND_CEILING, ROUND_FLOOR, Subnormal, Underflow,
)
from fractions import Fraction
from math import isfinite, nextafter

from .frames import CartesianState
from .orbit_config import GeometryInstant, _exact, _instant, _real
from . import orbit_j2 as _coast


class _Unresolved(Exception):
    pass


@dataclass(frozen=True, slots=True)
class J2EnclosurePolicy:
    """Explicit SI policy; sixth-order Taylor with seventh-order remainder.

    40..80 decimal digits, 1..4096 enclosure steps, 1..16 Picard attempts.
    The nominal query is independently limited to 4096 RK4 steps. Steps
    must lie in [2**-20, 1024] seconds; radius floor in [1e-6, 1e12] m.
    Version 1 admits at most 86400 s and nonzero dynamical input magnitudes
    in [1e-100, 1e100]. These are computational limits, not Earth defaults.
    """

    step_seconds: float
    max_steps: int
    min_radius_m: float
    precision_digits: int
    max_picard_iterations: int

    def __post_init__(self) -> None:
        h = _real("enclosure step_seconds", self.step_seconds)
        radius = _real("min_radius_m", self.min_radius_m)
        for name, low, high in (("max_steps", 1, 4096),
                                ("precision_digits", 40, 80),
                                ("max_picard_iterations", 1, 16)):
            value = getattr(self, name)
            _exact(value, int, name)
            if not low <= value <= high:
                raise ValueError(f"{name} must be in [{low}, {high}]")
        if not 2**-20 <= h <= 1024 or not 1e-6 <= radius <= 1e12:
            raise ValueError("enclosure step or radius floor outside policy domain")
        object.__setattr__(self, "step_seconds", h)
        object.__setattr__(self, "min_radius_m", radius)


@dataclass(frozen=True, slots=True)
class _I:
    lo: Decimal
    hi: Decimal


class _Arithmetic:
    """Per-query contexts only; never use caller's ambient Decimal context."""

    def __init__(self, precision: int):
        self.picard_attempts = 0
        traps = [InvalidOperation, DivisionByZero, Overflow, Underflow, Subnormal]
        self.down = Context(prec=precision, rounding=ROUND_FLOOR,
                            Emin=-200, Emax=200, traps=traps, clamp=0, capitals=1)
        self.up = Context(prec=precision, rounding=ROUND_CEILING,
                          Emin=-200, Emax=200, traps=traps, clamp=0, capitals=1)

    @staticmethod
    def point(value: float | int | Decimal) -> _I:
        d = Decimal.from_float(value) if type(value) is float else Decimal(value)
        return _I(d, d)

    def add(self, a: _I, b: _I) -> _I:
        return _I(self.down.add(a.lo, b.lo), self.up.add(a.hi, b.hi))

    @staticmethod
    def neg(a: _I) -> _I:
        # Unary Decimal '-' is context-sensitive. copy_negate is exact.
        return _I(a.hi.copy_negate(), a.lo.copy_negate())

    def sub(self, a: _I, b: _I) -> _I:
        return self.add(a, self.neg(b))

    def mul(self, a: _I, b: _I) -> _I:
        pairs = ((x, y) for x in (a.lo, a.hi) for y in (b.lo, b.hi))
        pairs = tuple(pairs)
        return _I(min(self.down.multiply(x, y) for x, y in pairs),
                  max(self.up.multiply(x, y) for x, y in pairs))

    def div(self, a: _I, b: _I) -> _I:
        if b.lo <= 0 <= b.hi:
            raise _Unresolved("interval division contains zero")
        return self.mul(a, _I(self.down.divide(Decimal(1), b.hi),
                              self.up.divide(Decimal(1), b.lo)))

    def square(self, a: _I) -> _I:
        upper = max(self.up.multiply(x, x) for x in (a.lo, a.hi))
        lower = (Decimal(0) if a.lo <= 0 <= a.hi else
                 min(self.down.multiply(x, x) for x in (a.lo, a.hi)))
        return _I(lower, upper)

    def sqrt(self, a: _I) -> _I:
        if a.lo <= 0:
            raise _Unresolved("radius interval does not exclude zero")
        # Decimal sqrt rounds to nearest, irrespective of directed contexts.
        # Neighbors bracket it; exact rational squared checks validate that
        # bracket rather than relying on a presumed directed sqrt operation.
        lo = self.down.next_minus(self.down.sqrt(a.lo))
        hi = self.up.next_plus(self.up.sqrt(a.hi))
        if lo <= 0 or Fraction(lo)**2 > Fraction(a.lo) or Fraction(hi)**2 < Fraction(a.hi):
            raise _Unresolved("square-root arithmetic bracket failed")
        return _I(lo, hi)

    def total(self, values) -> _I:
        result = self.point(0)
        for value in values:
            result = self.add(result, value)
        return result


def _poly_mul(a, b, m, ar):
    return [ar.total(ar.mul(a[j], b[k-j]) for j in range(k+1)) for k in range(m+1)]


def _poly_square(a, m, ar):
    result = _poly_mul(a, a, m, ar)
    result[0] = ar.square(a[0])
    return result


def _field(series, model, ar):
    """Interval coefficient extension of D317/F1, same immutable authority.

    With q=x*x+y*y+z*z and b=q**(-1/2), q*b'=-b*q'/2 gives
    b[k] = sum((i/2-k)*q[i]*b[k-i], i=1..k)/(k*q[0]).
    All coefficient operations (including 1/2) are interval operations.
    This is a derivative extension, not a separately parameterized field.
    """
    m = len(series[0])-1
    x, y, z = series[:3]
    squares = [_poly_square(a, m, ar) for a in (x, y, z)]
    q = [ar.total(s[k] for s in squares) for k in range(m+1)]
    b = [ar.div(ar.point(1), ar.sqrt(q[0]))]
    for k in range(1, m+1):
        terms = (ar.mul(ar.point(i/2-k), ar.mul(q[i], b[k-i])) for i in range(1, k+1))
        b.append(ar.div(ar.total(terms), ar.mul(ar.point(k), q[0])))
    b2 = _poly_mul(b, b, m, ar)
    b3 = _poly_mul(b2, b, m, ar)
    mu = ar.point(model.gravitational_parameter_m3_s2.value)
    acceleration = [[ar.neg(ar.mul(mu, v)) for v in _poly_mul(a, b3, m, ar)]
                    for a in (x, y, z)]
    if model.j2.value != 0:
        b5 = _poly_mul(b3, b2, m, ar)
        b7 = _poly_mul(b5, b2, m, ar)
        z2b7 = _poly_mul(squares[2], b7, m, ar)
        factor = ar.mul(ar.point(1.5), ar.mul(mu, ar.mul(ar.point(model.j2.value),
                        ar.square(ar.point(model.reference_radius_m.value)))))
        for axis, a in enumerate((x, y, z)):
            term = [ar.sub(ar.mul(ar.point(5), z2b7[k]),
                           ar.mul(ar.point(3 if axis == 2 else 1), b5[k])) for k in range(m+1)]
            correction = _poly_mul(a, term, m, ar)
            acceleration[axis] = [ar.add(v, ar.mul(factor, c))
                                  for v, c in zip(acceleration[axis], correction)]
    return list(series[3:]) + acceleration


def _coefficients(box, order, model, ar):
    series = [[value] for value in box]
    for k in range(order):
        rhs = _field(series, model, ar)
        for axis in range(6):
            series[axis].append(ar.div(rhs[axis][k], ar.point(k+1)))
    return series


def _domain(box, policy, ar):
    radius2 = ar.total(ar.square(x) for x in box[:3])
    floor = ar.square(ar.point(policy.min_radius_m)).hi
    if radius2.lo < floor:
        raise _Unresolved("continuous tube cannot establish the radius floor")
    return radius2


def _inflate(box, ar):
    inflated = []
    for a in box:
        scale = max(Decimal(1), a.lo.copy_abs(), a.hi.copy_abs())
        # Inflation is a search heuristic ONLY. Inclusion is checked afterward.
        padding = ar.up.add(ar.up.divide(ar.up.subtract(a.hi, a.lo), Decimal(8)),
                            ar.up.multiply(scale, Decimal('1e-30')))
        inflated.append(_I(ar.down.subtract(a.lo, padding), ar.up.add(a.hi, padding)))
    return inflated


def _alternative_seed(box, ar):
    # One bounded search alternative; never replace the incoming uncertainty.
    inflated = []
    for a in box:
        scale = max(Decimal(1), a.lo.copy_abs(), a.hi.copy_abs())
        padding = ar.up.add(ar.up.divide(ar.up.subtract(a.hi, a.lo), Decimal(16)),
                            ar.up.multiply(scale, Decimal('1e-30')))
        inflated.append(_I(ar.down.subtract(a.lo, padding), ar.up.add(a.hi, padding)))
    return inflated


def _tube(box, h, model, policy, ar):
    time = _I(min(Decimal(0), h.lo), max(Decimal(0), h.hi))
    candidate = _inflate(box, ar)
    for attempt in range(1, policy.max_picard_iterations+1):
        ar.picard_attempts += 1
        try:
            _domain(candidate, policy, ar)
        except _Unresolved as error:
            if attempt != 1 or str(error) != "continuous tube cannot establish the radius floor":
                raise
            _domain(box, policy, ar)
            if attempt == policy.max_picard_iterations:
                raise
            candidate = _alternative_seed(box, ar)
            if len(candidate) != len(box) or not all(
                    b.lo <= a.lo and a.hi <= b.hi for a, b in zip(box, candidate)):
                raise _Unresolved("alternative Picard seed does not contain incoming box")
            # The rejected trial is charged; check the alternative next iteration.
            continue
        f = _field([[a] for a in candidate], model, ar)
        image = [ar.add(a, ar.mul(time, f[i][0])) for i, a in enumerate(box)]
        if all(b.lo < a.lo and a.hi < b.hi for a, b in zip(image, candidate)):
            return candidate, attempt
        # Do not repeatedly inflate already-contained coordinates: doing so
        # can make a dependent coordinate chase an unnecessarily growing box.
        candidate = [a if a.lo < b.lo and b.hi < a.hi else
                     _inflate([_I(min(a.lo, b.lo), max(a.hi, b.hi))], ar)[0]
                     for a, b in zip(candidate, image)]
    raise _Unresolved("Picard inclusion work exhausted")


def _step_with_tube(box, h, model, policy, ar):
    """Shared validated step; retain the actual Picard tube as evidence."""
    tube, attempts = _tube(box, h, model, policy, ar)
    coefficients = _coefficients(box, 6, model, ar)
    remainder = _coefficients(tube, 7, model, ar)
    endpoint = []
    for polynomial, derivative in zip(coefficients, remainder):
        value = derivative[7]
        for k in range(6, -1, -1):
            value = ar.add(polynomial[k], ar.mul(h, value))
        endpoint.append(value)
    _domain(endpoint, policy, ar)
    return endpoint, tube, attempts


def _step(box, h, model, policy, ar):
    endpoint, _, attempts = _step_with_tube(box, h, model, policy, ar)
    return endpoint, attempts


def _upper_float(value):
    result = float(value)
    if not isfinite(result):
        raise _Unresolved("error bound exceeds finite binary64")
    if Decimal.from_float(result) < value:
        result = nextafter(result, float('inf'))
    if not isfinite(result):
        raise _Unresolved("error bound exceeds finite binary64")
    return result


@dataclass(frozen=True, slots=True)
class J2EnclosureResult:
    """Recomputed evidence; infinity-norm endpoint errors, metres and m/s.

    status='unresolved' ALWAYS has None bounds/intervals/nominal_state.
    Complete original authorities, TT instant and both policies are retained.
    No persistence, generated ID, visibility claim or continuation is supplied.
    """

    trajectory: _coast.J2CartesianTrajectory
    instant: GeometryInstant
    solver_config: _coast.J2RK4SolverConfig
    policy: J2EnclosurePolicy
    status: str = field(init=False)
    reason: str | None = field(init=False)
    nominal_state: CartesianState | None = field(init=False)
    endpoint_intervals: tuple[tuple[Decimal, Decimal], ...] | None = field(init=False)
    position_error_bound_m: float | None = field(init=False)
    velocity_error_bound_m_per_s: float | None = field(init=False)
    enclosure_steps: int = field(init=False)
    nominal_steps: int = field(init=False)
    picard_attempts: int = field(init=False)
    policy_version: int = field(init=False, default=1)

    __hash__ = None

    def __post_init__(self):
        _exact(self.trajectory, _coast.J2CartesianTrajectory, "trajectory")
        state, model = _coast._authorities(self.trajectory.initial_state, self.trajectory.gravity_model)
        instant = _instant(self.instant)
        _exact(self.solver_config, _coast.J2RK4SolverConfig, "solver_config")
        config = _coast.J2RK4SolverConfig(self.solver_config.step_seconds, self.solver_config.max_steps)
        _exact(self.policy, J2EnclosurePolicy, "policy")
        policy = J2EnclosurePolicy(self.policy.step_seconds, self.policy.max_steps,
                                   self.policy.min_radius_m, self.policy.precision_digits,
                                   self.policy.max_picard_iterations)
        if state.position.instant.epoch != instant.epoch:
            raise ValueError("J2 enclosure requires the same TT reference epoch")
        # Rebuild even zero-span evidence. Invalid F1 authority remains an error.
        trajectory = _coast.J2CartesianTrajectory(state, model)
        for key, value in (("trajectory", trajectory), ("instant", instant),
                           ("solver_config", config), ("policy", policy)):
            object.__setattr__(self, key, value)
        for key in ("nominal_state", "endpoint_intervals", "position_error_bound_m",
                    "velocity_error_bound_m_per_s", "reason"):
            object.__setattr__(self, key, None)
        for key in ("enclosure_steps", "nominal_steps", "picard_attempts"):
            object.__setattr__(self, key, 0)
        object.__setattr__(self, "status", "unresolved")
        ar = _Arithmetic(policy.precision_digits)
        try:
            self._evaluate(ar)
        except (_Unresolved, DecimalException, OverflowError) as error:
            object.__setattr__(self, "reason", str(error))
        finally:
            object.__setattr__(self, "picard_attempts", ar.picard_attempts)

    def _evaluate(self, ar):
        t, p, c = self.trajectory, self.policy, self.solver_config
        state, model = t.initial_state, t.gravity_model
        span = Fraction(self.instant.elapsed_seconds)-Fraction(state.position.instant.elapsed_seconds)
        nf, nr = divmod(abs(span), Fraction(c.step_seconds))
        full, remainder = divmod(abs(span), Fraction(p.step_seconds))
        if abs(span) > 86400 or nf+bool(nr) > min(c.max_steps, 4096) or full+bool(remainder) > p.max_steps:
            raise _Unresolved("horizon or step work ceiling exceeded before integration")
        # F2 owns representable remainder admission; do not invent another grid.
        try:
            _coast._grid(state.position.instant, self.instant, c)
        except ValueError as error:
            raise _Unresolved(str(error)) from error
        values = (*state.position.components_m, *state.velocity.components_m_per_s,
                  model.gravitational_parameter_m3_s2.value, model.j2.value,
                  model.reference_radius_m.value, c.step_seconds)
        if any(x != 0 and not 1e-100 <= abs(x) <= 1e100 for x in values):
            raise _Unresolved("dynamical input outside F3 arithmetic envelope")
        box = [ar.point(x) for x in values[:6]]
        _domain(box, p, ar)
        sign = -1 if span < 0 else 1
        for step in range(full+bool(remainder)):
            dt = Fraction(p.step_seconds) if step < full else remainder
            h = ar.div(ar.point(sign*dt.numerator), ar.point(dt.denominator))
            box, _ = _step(box, h, model, p, ar)
            object.__setattr__(self, "enclosure_steps", step+1)
        try:
            nominal = _coast.evaluate_j2_cartesian_state(t, self.instant, c)
        except ValueError as error:
            raise _Unresolved("F2 nominal arithmetic: "+str(error)) from error
        object.__setattr__(self, "nominal_steps", int(nf+bool(nr)))
        components = (*nominal.position.components_m, *nominal.velocity.components_m_per_s)
        distances = [ar.sub(a, ar.point(x)) for a, x in zip(box, components)]
        radii = [max(a.lo.copy_abs(), a.hi.copy_abs()) for a in distances]
        position, velocity = _upper_float(max(radii[:3])), _upper_float(max(radii[3:]))
        # Publish success atomically only after every computation has passed.
        for key, value in (("nominal_state", nominal),
                           ("endpoint_intervals", tuple((a.lo, a.hi) for a in box)),
                           ("position_error_bound_m", position),
                           ("velocity_error_bound_m_per_s", velocity), ("status", "enclosed")):
            object.__setattr__(self, key, value)


def evaluate_j2_enclosure(trajectory, instant, solver_config, policy) -> J2EnclosureResult:
    return J2EnclosureResult(trajectory, instant, solver_config, policy)


__all__ = ["J2EnclosurePolicy", "J2EnclosureResult", "evaluate_j2_enclosure"]
