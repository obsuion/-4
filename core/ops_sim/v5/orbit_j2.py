"""Pure origin-anchored nominal Cartesian J2 coast; NOT certified integration.

Classical fixed-step RK4 uses the static MODEL_INERTIAL F1 force. Every query
reconstructs the original authorities, counts work exactly using Fraction on
the admitted binary64 times, and repeats the original signed full-step prefix.
At most one remainder follows; it must be exactly representable as binary64.
No global state-error enclosure, visibility certificate or persistence exists.

Private F1 _frame_text and _gravity are deliberate frozen-owner dependencies.
Stages use genuine CartesianPosition objects at the anchor instant: the force
is autonomous, so no rounded internal stage time is invented. Only the returned
state carries the requested instant. F1's potential arithmetic domain is also
inherited even though RK4 consumes only acceleration.

Binary64 products/sums must be finite. Nonzero products rounded to zero and
nonzero state increments swallowed by addition reject; exact cancellations
are allowed. Intermediate overflow rejects even if algebraic rearrangement
could recover a finite answer. Subnormal nonzero values retain ordinary
absolute resolution. These guards are not interval arithmetic or an error
certificate. RK4 coefficient rounding and other nonzero rounding remain.
One query costs O(steps), with no prefix cache; search-local reuse belongs to F5.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import fsum, isfinite

from .frames import CartesianPosition, CartesianState, CartesianVelocity
from .orbit_config import FrameKind, GeometryInstant, _exact, _instant, _real
from .orbit_j2_gravity import J2GravityModel, _frame_text, _gravity


def _authorities(initial: object, model: object) -> tuple[CartesianState, J2GravityModel]:
    _exact(initial, CartesianState, "initial_state")
    _exact(initial.position, CartesianPosition, "initial position")
    _exact(initial.velocity, CartesianVelocity, "initial velocity")
    # Both sides must be protected BEFORE the shared state owner compares them.
    _frame_text(initial.position.frame)
    _frame_text(initial.velocity.frame)
    state = CartesianState(initial.position, initial.velocity)
    if state.position.frame.kind is not FrameKind.MODEL_INERTIAL:
        raise ValueError("J2 coast requires MODEL_INERTIAL")
    _exact(model, J2GravityModel, "gravity_model")
    model = J2GravityModel(model.gravitational_parameter_m3_s2, model.j2,
                           model.reference_radius_m)
    return state, model


@dataclass(frozen=True, slots=True)
class J2CartesianTrajectory:
    """Original Cartesian authority and the sole, independent F1 gravity model."""

    initial_state: CartesianState
    gravity_model: J2GravityModel

    __hash__ = None

    def __post_init__(self) -> None:
        state, model = _authorities(self.initial_state, self.gravity_model)
        _gravity(model, state.position)  # Admission includes initial F1 evaluability.
        object.__setattr__(self, "initial_state", state)
        object.__setattr__(self, "gravity_model", model)


@dataclass(frozen=True, slots=True)
class J2RK4SolverConfig:
    """Explicit positive step and exact positive per-query integer work ceiling."""

    step_seconds: float
    max_steps: int

    def __post_init__(self) -> None:
        step = _real("step_seconds", self.step_seconds)
        _exact(self.max_steps, int, "max_steps")
        if step <= 0 or self.max_steps <= 0:
            raise ValueError("step_seconds and max_steps must be positive")
        object.__setattr__(self, "step_seconds", step)


def _grid(initial: GeometryInstant, requested: GeometryInstant,
          config: J2RK4SolverConfig) -> tuple[int, float, float]:
    if initial.epoch != requested.epoch:
        raise ValueError("J2 coast requires the same TT reference epoch")
    span = Fraction(requested.elapsed_seconds) - Fraction(initial.elapsed_seconds)
    full, remainder = divmod(abs(span), Fraction(config.step_seconds))
    required = full + bool(remainder)
    if required > config.max_steps:
        raise ValueError("requested J2 coast exceeds max_steps before integration")
    tail = float(remainder)
    if Fraction(tail) != remainder:
        raise ValueError("endpoint remainder must be exactly representable as binary64")
    sign = -1.0 if span < 0 else 1.0
    return full, sign * config.step_seconds, sign * tail


def _product(first: float, second: float) -> float:
    value = first * second
    if not isfinite(value) or (value == 0 and first != 0 and second != 0):
        raise ValueError("RK4 product exceeds supported binary64 arithmetic")
    return value


def _sum(terms: tuple[float, ...]) -> float:
    try:
        value = fsum(terms)
    except OverflowError as error:
        raise ValueError("RK4 sum exceeds finite binary64 arithmetic") from error
    if not isfinite(value):
        raise ValueError("RK4 sum must be finite")
    if value == 0 and sum(map(Fraction, terms), Fraction()) != 0:
        raise ValueError("nonzero RK4 sum underflows binary64")
    return value


def _advance(base: tuple[float, ...], derivative: tuple[float, ...],
             delta: float) -> tuple[float, ...]:
    result = []
    for original, rate in zip(base, derivative):
        increment = _product(delta, rate)
        value = _sum((original, increment))
        if increment != 0 and value == original:
            raise ValueError("nonzero RK4 state increment is lost in binary64 addition")
        result.append(value)
    return tuple(result)


def _force(model: J2GravityModel, anchor: CartesianPosition,
           components: tuple[float, ...]) -> tuple[float, ...]:
    position = CartesianPosition(anchor.frame, anchor.instant, components)
    return _gravity(model, position)[:3]


def _rk4_step(model: J2GravityModel, anchor: CartesianPosition,
              r: tuple[float, ...], v: tuple[float, ...],
              delta: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    half = _product(delta, 0.5)
    k1r, k1v = v, _force(model, anchor, r)
    k2r = _advance(v, k1v, half)
    k2v = _force(model, anchor, _advance(r, k1r, half))
    k3r = _advance(v, k2v, half)
    k3v = _force(model, anchor, _advance(r, k2r, half))
    k4r = _advance(v, k3v, delta)
    k4v = _force(model, anchor, _advance(r, k3r, delta))

    def average(a, b, c, d):
        return tuple(_product(_sum((w, _product(2.0, x), _product(2.0, y), z)), 1.0/6.0)
                     for w, x, y, z in zip(a, b, c, d))

    rnext = _advance(r, average(k1r, k2r, k3r, k4r), delta)
    vnext = _advance(v, average(k1v, k2v, k3v, k4v), delta)
    if not any(rnext):
        raise ValueError("RK4 endpoint reaches the singular gravity origin")
    return rnext, vnext


def evaluate_j2_cartesian_state(
    trajectory: J2CartesianTrajectory,
    instant: GeometryInstant,
    solver_config: J2RK4SolverConfig,
) -> CartesianState:
    """Evaluate signed coast from original authority; never continue a query."""
    _exact(trajectory, J2CartesianTrajectory, "trajectory")
    # Split structural reconstruction from force admission so work rejection
    # occurs before ANY force evaluation, including the initial admission check.
    state, model = _authorities(trajectory.initial_state, trajectory.gravity_model)
    requested = _instant(instant)
    _exact(solver_config, J2RK4SolverConfig, "solver_config")
    config = J2RK4SolverConfig(solver_config.step_seconds, solver_config.max_steps)
    full, delta, tail = _grid(state.position.instant, requested, config)
    _gravity(model, state.position)
    r, v = state.position.components_m, state.velocity.components_m_per_s
    for _ in range(full):
        r, v = _rk4_step(model, state.position, r, v, delta)
    if tail:
        r, v = _rk4_step(model, state.position, r, v, tail)
    return CartesianState(CartesianPosition(state.position.frame, requested, r),
                          CartesianVelocity(state.velocity.frame, requested, v))


__all__ = ["J2CartesianTrajectory", "J2RK4SolverConfig", "evaluate_j2_cartesian_state"]
