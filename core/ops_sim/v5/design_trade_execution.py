"""Opt-in protected one-axis motion using the accepted EPS/thermal owners.

The caller owns the immutable trajectory/electrical contract. Runtime callbacks
are projections of that contract, not persisted authorities. The entire motion
is predicted before its single commit. A denied proposal becomes a physical hold
at the original attitude for the same duration; no partially powered turn is
invented. Numerical refinement samples both trajectory forcing and physics.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, isfinite

from .continuation import checked_checkpoint
from .engine import _validate_completed_context
from .eps_system import EPSIntervalInputs
from .integration_time import IntegrationPolicy, RationalSeconds
from .operational_protection import StandbyInputs, _validate_forcing, _violations, validate_policy
from .state import FDIRState, OperationalMode
from .substepped_execution import (
    ActionAccounting, PhysicalSample, _aggregate, _commit_action,
    _physical_substep, _sample, _validate_physical_samples,
)


def _finite(value, name):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(name + " must be a finite built-in real")
    return float(value)


@dataclass(frozen=True, slots=True)
class ProfileSample:
    time_seconds: Fraction
    angle_rad: float
    physical: PhysicalSample

    def __post_init__(self):
        if type(self.time_seconds) is not Fraction or self.time_seconds < 0:
            raise ValueError("profile sample requires nonnegative exact absolute time")
        _finite(self.angle_rad, "sample angle")
        if type(self.physical) is not PhysicalSample:
            raise TypeError("profile sample requires shared physical evidence")
        self.physical.__post_init__()


@dataclass(frozen=True, slots=True)
class ProfileInterval:
    start_seconds: Fraction
    end_seconds: Fraction
    midpoint_angle_rad: float
    omega_rad_s: float
    torque_nm: float
    diagnostics: tuple[tuple[str, float], ...]

    def __post_init__(self):
        if (type(self.start_seconds) is not Fraction or type(self.end_seconds) is not Fraction
                or not 0 <= self.start_seconds < self.end_seconds):
            raise ValueError("profile interval requires increasing exact times")
        for name in ("midpoint_angle_rad", "omega_rad_s", "torque_nm"):
            _finite(getattr(self, name), name)
        if type(self.diagnostics) is not tuple:
            raise TypeError("profile diagnostics must be immutable ordered pairs")
        keys = []
        for item in self.diagnostics:
            if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str or not item[0]:
                raise ValueError("invalid diagnostic pair")
            item[0].encode("utf-8", errors="strict")
            _finite(item[1], item[0])
            keys.append(item[0])
        if keys != sorted(set(keys)):
            raise ValueError("diagnostic names must be unique and ordered")


@dataclass(frozen=True, slots=True)
class ProfileOutcome:
    start_seconds: int
    end_seconds: int
    integration_level: int
    approved: bool
    final_angle_rad: float
    reasons: tuple[str, ...]
    samples: tuple[ProfileSample, ...]
    intervals: tuple[ProfileInterval, ...]
    accounting: ActionAccounting
    predicted_unmet_w: float

    def __post_init__(self):
        if (type(self.start_seconds) is not int or type(self.end_seconds) is not int
                or not 0 <= self.start_seconds < self.end_seconds):
            raise ValueError("profile requires increasing integer completed boundaries")
        IntegrationPolicy(self.integration_level)
        if type(self.approved) is not bool:
            raise TypeError("profile approval must be explicit")
        _finite(self.final_angle_rad, "final angle")
        if type(self.reasons) is not tuple or any(type(v) is not str or not v for v in self.reasons):
            raise ValueError("profile reasons must be explicit immutable text")
        if self.approved != (not self.reasons):
            raise ValueError("approval disagrees with prediction reasons")
        if (type(self.samples) is not tuple or type(self.intervals) is not tuple
                or not 1 <= len(self.intervals) <= 4096 or len(self.samples) != len(self.intervals) + 1):
            raise ValueError("profile requires a complete bounded physical partition")
        if type(self.accounting) is not ActionAccounting:
            raise TypeError("profile requires shared action accounting")
        self.accounting.__post_init__()
        if self.accounting.numerical_substeps != len(self.intervals):
            raise ValueError("profile accounting disagrees with partition")
        if (self.samples[0].time_seconds != self.start_seconds
                or self.samples[-1].time_seconds != self.end_seconds
                or self.samples[-1].angle_rad != self.final_angle_rad):
            raise ValueError("profile samples disagree with completed boundaries")
        for i, interval in enumerate(self.intervals):
            if type(interval) is not ProfileInterval:
                raise TypeError("invalid profile interval")
            interval.__post_init__()
            if (interval.start_seconds != self.samples[i].time_seconds
                    or interval.end_seconds != self.samples[i + 1].time_seconds):
                raise ValueError("profile interval has a gap")
        for sample in self.samples:
            if type(sample) is not ProfileSample:
                raise TypeError("invalid profile sample")
            sample.__post_init__()
        if _finite(self.predicted_unmet_w, "predicted unmet power") < 0:
            raise ValueError("unmet power must be nonnegative")


def execute_profile(context, *, duration_seconds, integration_level, start_angle_rad,
                    trajectory_at, forcing_at, policy, max_interval_seconds=5,
                    required_node_ids=None, forcing_breakpoints_seconds=()):
    """Predict and atomically execute a moving profile or same-duration hold.

    ``trajectory_at(offset: Fraction)`` returns angle [rad], rate [rad/s], torque
    [N m]. ``forcing_at(absolute_time, angle, rate, torque, moving)`` returns
    (StandbyInputs, finite scalar diagnostic dict). The held fallback is called
    with ``moving=False`` and zero rate/torque, and must exclude motor demand.
    Settling can use a constant trajectory with explicit actuator electronics.

    Optional forcing breakpoints are strictly increasing integer absolute times
    inside the action. Each span gets ceil(span / max_interval_seconds) times
    2**integration_level intervals; the entire action remains bounded by 4096.
    Forcing is sampled at each open interval's exact midpoint, so no substep
    crosses a declared discontinuity. Trajectory offsets remain relative to the
    original action start. ProfileSample.time_seconds owns the exact clock;
    embedded PhysicalSample numerators retain the legacy ordinal convention.

    This does not register callbacks as identities: the enclosing new program
    must bind every physical parameter and this partition policy, and validate
    completed state on restore. The bounded 05E wrapper retains its replay
    contract; the continuous wrapper binds a schema-5 checkpoint and evidence.
    """
    from .experiment_codec import canonical_copy
    _validate_completed_context(context)
    if type(duration_seconds) is not int or duration_seconds <= 0:
        raise ValueError("profile duration must be positive integer seconds")
    if type(max_interval_seconds) is not int or max_interval_seconds <= 0:
        raise ValueError("maximum base interval must be positive integer seconds")
    numerical = IntegrationPolicy(integration_level)
    start = context.simulation_time_seconds
    end = start + duration_seconds
    if type(forcing_breakpoints_seconds) is not tuple:
        raise TypeError("forcing breakpoints must be an immutable tuple")
    previous = start
    for boundary in forcing_breakpoints_seconds:
        if type(boundary) is not int or not previous < boundary < end:
            raise ValueError("forcing breakpoints must be ordered unique interior integer times")
        previous = boundary
    boundaries = (start,) + forcing_breakpoints_seconds + (end,)
    counts = tuple(ceil(Fraction(right - left, max_interval_seconds)) * numerical.substeps
                   for left, right in zip(boundaries[:-1], boundaries[1:]))
    count = sum(counts)
    if not 1 <= count <= 4096:
        raise ValueError("profile partition exceeds bounded physical work")
    if end > context.inputs.common_world.horizon_seconds:
        raise ValueError("profile exceeds common horizon")
    if context.inputs.common_world.event_ids:
        raise ValueError("profile requires explicit forcing without world events")
    initial_angle = _finite(start_angle_rad, "initial angle")
    policy = validate_policy(policy, context)
    required = policy.standby_node_ids if required_node_ids is None else required_node_ids
    known = {node.node_id for node in context.inputs.spacecraft_configuration.thermal.network.nodes}
    if (type(required) is not tuple or not set(policy.standby_node_ids) <= set(required) <= known
            or len(required) != len(set(required))):
        raise ValueError("motion requires known unique essential thermal nodes")
    if not callable(trajectory_at) or not callable(forcing_at):
        raise TypeError("explicit runtime trajectory and forcing projections required")

    def trajectory(offset):
        value = trajectory_at(offset)
        if type(value) is not tuple or len(value) != 3:
            raise ValueError("trajectory must return angle/rate/torque tuple")
        return tuple(_finite(x, name) for x, name in zip(value, ("angle", "rate", "torque")))

    first, last = trajectory(Fraction(0)), trajectory(Fraction(duration_seconds))
    if first[0] != initial_angle or first[1] != 0 or last[1] != 0:
        raise ValueError("profile must start at the observed attitude and be rest-to-rest")
    inputs = canonical_copy(context.inputs)
    origin = checked_checkpoint(context)
    dt_fraction = Fraction(duration_seconds, count)
    dt = RationalSeconds.from_fraction(dt_fraction)
    partition = tuple((i * dt_fraction, (i + 1) * dt_fraction, dt_fraction, dt)
                      for i in range(count))
    if forcing_breakpoints_seconds:
        partition = []
        for left, right, span_count in zip(boundaries[:-1], boundaries[1:], counts, strict=True):
            span_dt = Fraction(right - left, span_count)
            span_duration = RationalSeconds.from_fraction(span_dt)
            partition.extend((Fraction(left - start) + i * span_dt,
                              Fraction(left - start) + (i + 1) * span_dt,
                              span_dt, span_duration) for i in range(span_count))
        partition = tuple(partition)

    def proposal(moving):
        candidate = origin.restore(inputs)
        parts, intervals = [], []
        samples = [ProfileSample(Fraction(start), initial_angle, _sample(candidate, 0, required))]
        reasons = ["motion-required-node-outside-operating-at-start"] if moving and _violations(candidate, required) else []
        unmet = 0.0
        if reasons:
            return candidate, parts, samples, intervals, reasons, unmet
        for i, (left_offset, right_offset, dt_fraction, dt) in enumerate(partition):
            offset = (left_offset + right_offset) / 2
            angle, rate, torque = trajectory(offset) if moving else (initial_angle, 0., 0.)
            pair = forcing_at(Fraction(start) + offset, angle, rate, torque, moving)
            if type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not StandbyInputs or type(pair[1]) is not dict:
                raise TypeError("forcing projection requires StandbyInputs and scalar diagnostic map")
            forcing, diagnostics = pair
            forcing = canonical_copy(forcing)
            forcing.__post_init__()
            _validate_forcing(forcing, inputs.spacecraft_configuration.thermal.network)
            if forcing.solar_degradation_forcing is not None:
                raise ValueError("profile excludes solar ageing forcing; no implicit repeated allocation")
            if any(type(key) is not str or not key for key in diagnostics):
                raise ValueError("diagnostic names must be nonempty exact text")
            diagnostics = {key: _finite(diagnostics[key], key) for key in diagnostics}
            internal_heat = None
            inertia_keys = ("body_inertia_kg_m2", "rotor_inertia_kg_m2")
            if any(key in diagnostics for key in inertia_keys):
                if not all(key in diagnostics and diagnostics[key] > 0 for key in inertia_keys):
                    raise ValueError("motion kinetic heat requires positive body and rotor inertia")
                body, rotor = (diagnostics[key] for key in inertia_keys)
                start_rate = trajectory(left_offset)[1] if moving else 0.
                end_rate = trajectory(right_offset)[1] if moving else 0.
                # Ideal wheel momentum balances body angular momentum. Electrical
                # draw is not regenerative; kinetic storage is removed from heat
                # during acceleration and released as heat during braking.
                def kinetic(omega):
                    return _finite(.5*body*omega*omega + .5*(body*omega)**2/rotor, "kinetic energy")
                kinetic_start, kinetic_end = kinetic(start_rate), kinetic(end_rate)
                adjustment = (kinetic_start-kinetic_end)/float(dt_fraction)
                if -adjustment > forcing.loads.adcs_w:
                    raise ValueError("declared actuator electrical draw cannot fund kinetic storage")
                diagnostics.update(kinetic_start_j=kinetic_start, kinetic_end_j=kinetic_end,
                    actuator_heat_adjustment_w=adjustment)
                if moving:
                    internal_heat = ((inputs.spacecraft_configuration.thermal.network.bus_node_id, adjustment),)
            evidence = tuple((key, diagnostics[key]) for key in sorted(diagnostics))
            eps_inputs = EPSIntervalInputs(forcing.sunlit, forcing.incidence_angle_deg, forcing.loads)
            part, eps = _physical_substep(candidate, dt, forcing, eps_inputs, policy, None,
                standby=not moving, internal_heat_adjustments_w=internal_heat)
            if part is None:
                unmet = eps.battery.unmet_load_w
                reasons.append("motion-full-electrical-service-unavailable")
                break
            parts.append(part)
            intervals.append(ProfileInterval(Fraction(start) + left_offset,
                Fraction(start) + right_offset, angle, rate, torque, evidence))
            endpoint_angle = trajectory(right_offset)[0] if moving else initial_angle
            samples.append(ProfileSample(Fraction(start) + right_offset, endpoint_angle,
                _sample(candidate, (i+1)*duration_seconds, required, eps.battery.unmet_load_w)))
            if moving and _violations(candidate, required):
                reasons.append("motion-required-node-outside-operating-at-endpoint")
                break
        return candidate, parts, samples, intervals, reasons, unmet

    candidate, parts, samples, intervals, reasons, unmet = proposal(True)
    approved = not reasons
    if not approved:
        candidate, parts, samples, intervals, _, _ = proposal(False)
    if forcing_breakpoints_seconds:
        for i, part in enumerate(parts):
            _validate_physical_samples((part,), (samples[i].physical, samples[i + 1].physical), partition[i][3])
    else:
        _validate_physical_samples(tuple(parts), tuple(x.physical for x in samples), dt)
    accounting = _aggregate(tuple(parts))
    onboard = candidate.spacecraft_state.onboard
    old = context.spacecraft_state.onboard
    unsafe = bool(accounting.unmet_load_wh or any(s.physical.operating_node_ids for s in samples))
    onboard.operational_mode = OperationalMode.SAFE if unsafe else OperationalMode.STANDBY
    onboard.fdir_state = FDIRState.NORMAL if approved and not unsafe else FDIRState.BACKUP
    onboard.critical_energy_since_seconds = ((old.critical_energy_since_seconds
        if old.critical_energy_since_seconds is not None else start) if accounting.unmet_load_wh else None)
    candidate.simulation_time_seconds = end
    candidate.diagnostics.completed_steps = context.diagnostics.completed_steps + 1
    _validate_completed_context(candidate)
    checked_checkpoint(candidate)
    outcome = ProfileOutcome(start, end, integration_level, approved,
        last[0] if approved else initial_angle, tuple(reasons), tuple(samples), tuple(intervals), accounting, unmet)
    _commit_action(context, candidate)
    return outcome


__all__ = ["ProfileSample", "ProfileInterval", "ProfileOutcome", "execute_profile"]
