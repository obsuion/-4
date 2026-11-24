"""Standalone TT and model Earth definitions; no runtime clock binding.

SI units and binary64 arithmetic are used. TT Julian days start at noon in
the TT calendar convention, not civil midnight. A split date has one integer
day and a fraction in [0, 1); it is never collapsed into a large float.
The representation envelope is |day| <= 2**31-1, |elapsed| <= 2**40 s.
These arithmetic limits are not an approved mission horizon. Fractional-day
rounding costs at most 2**-54 day (about 4.8 ps); elapsed binary64 resolution
near 2**40 s is about 244 microseconds. No UTC/TDB conversion is provided.

S008 records the NGA reference parameters and the author-approved model
assumptions. WGS84 shape alone supplies neither a terrestrial realization
nor gravity. Uniform rotation is an explicit approximation, even when its
rate is the published nominal reference. Epoch and phase are caller inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from math import isfinite, pi
from numbers import Integral, Real

from .ids import ParameterId, SourceRecordId
from .parameters import ScalarParameter
from .provenance import (
    ParameterProvenance, ProvenanceClass, ProvenanceStatus, SensitivityRange,
)


_MAX_DAY = 2**31 - 1
_MAX_ELAPSED_SECONDS = 2**40
_MIN_AXIS_RATIO_SQUARED = 2.0**-40


def _real(name: str, value: object) -> float:
    """Normalize Real inputs; do not silently round integer inputs."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a finite real number, not bool")
    try:
        result = float(value)
    except (OverflowError, ValueError, TypeError) as error:
        raise ValueError(f"{name} is outside binary64 arithmetic") from error
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    if isinstance(value, Integral) and int(result) != int(value):
        raise ValueError(f"{name} loses integer precision in binary64")
    if result == 0 and value != 0:
        raise ValueError(f"{name} underflows binary64 representation")
    return 0.0 if result == 0 else result


def _exact(value: object, cls: type, name: str) -> None:
    if type(value) is not cls:
        raise TypeError(f"{name} must be an exact {cls.__name__}")


def _parameter(value: object, identifier: str, units: str) -> ScalarParameter:
    """Rebuild the complete nested provenance graph, including forged values."""
    _exact(value, ScalarParameter, identifier)
    p = value.provenance
    _exact(p, ParameterProvenance, "provenance")
    if not any(p.classification is member for member in ProvenanceClass):
        raise ValueError("provenance classification must be an actual enum member")
    if not any(p.status is member for member in ProvenanceStatus):
        raise ValueError("provenance status must be an actual enum member")
    _exact(p.parameter_id, ParameterId, "parameter_id")
    parameter_id = ParameterId(p.parameter_id.value)
    if parameter_id.value != identifier or p.units != units:
        raise ValueError(f"parameter must use {identifier!r} and units {units!r}")
    _exact(p.source_ids, tuple, "source_ids")
    sources = []
    for source in p.source_ids:
        _exact(source, SourceRecordId, "source_id")
        sources.append(SourceRecordId(source.value))
    bounds = p.sensitivity_range
    if bounds is not None:
        _exact(bounds, SensitivityRange, "sensitivity_range")
        SensitivityRange(bounds.lower, bounds.upper)
    original_provenance = ParameterProvenance(
        parameter_id, p.classification, p.units, tuple(sources), p.status,
        p.rationale, p.derivation, bounds,
    )
    ScalarParameter(value.value, original_provenance)
    if bounds is not None:
        bounds = SensitivityRange(_real("lower", bounds.lower), _real("upper", bounds.upper))
    provenance = ParameterProvenance(
        parameter_id, p.classification, p.units, tuple(sources), p.status,
        p.rationale, p.derivation, bounds,
    )
    return ScalarParameter(_real(identifier, value.value), provenance)


@dataclass(frozen=True, slots=True)
class TTEpoch:
    """Canonical TT Julian date: integer boundaries are TT noon boundaries."""

    julian_day: int
    fractional_day: float

    def __post_init__(self) -> None:
        _exact(self.julian_day, int, "julian_day")
        if abs(self.julian_day) > _MAX_DAY:
            raise ValueError("julian_day exceeds the supported integer-day envelope")
        fraction = _real("fractional_day", self.fractional_day)
        if not 0 <= self.fractional_day < 1 or not 0 <= fraction < 1:
            raise ValueError("fractional_day must be in [0, 1)")
        object.__setattr__(self, "fractional_day", fraction)


def _epoch(value: object) -> TTEpoch:
    _exact(value, TTEpoch, "epoch")
    return TTEpoch(value.julian_day, value.fractional_day)


def _elapsed(value: object) -> float:
    elapsed = _real("elapsed_seconds", value)
    if abs(value) > _MAX_ELAPSED_SECONDS or abs(elapsed) > _MAX_ELAPSED_SECONDS:
        raise ValueError("elapsed_seconds exceeds 2**40 s arithmetic envelope")
    return elapsed


def tt_date_at(epoch: TTEpoch, elapsed_seconds: float) -> TTEpoch:
    """Map an explicit reference TT date and signed seconds to a split TT date.

    Rational arithmetic on the admitted binary inputs performs carry exactly;
    only the final fractional day is rounded. Offsets below its resolution may
    round away. This does not make the returned date arbitrary precision.
    """
    epoch = _epoch(epoch)
    elapsed = _elapsed(elapsed_seconds)
    total = Fraction(epoch.fractional_day) + Fraction(elapsed) / 86400
    carry, remainder = divmod(total, 1)
    fraction = float(remainder)
    if fraction == 1.0:  # Rounding at the upper boundary requires canonical carry.
        carry += 1
        fraction = 0.0
    return TTEpoch(epoch.julian_day + carry, fraction)


def elapsed_seconds_between(epoch: TTEpoch, date: TTEpoch) -> float:
    """Split difference rounded once, then checked against the seconds envelope.

    The envelope applies to the returned binary64 value: fractional-day
    rounding at an endpoint can straddle the exact rational limit by picoseconds.
    Rounding to the nearest float is not clipping an out-of-range float.
    """
    epoch, date = _epoch(epoch), _epoch(date)
    seconds = 86400 * (
        date.julian_day - epoch.julian_day
        + Fraction(date.fractional_day) - Fraction(epoch.fractional_day)
    )
    # Bounded integer days ensure this conversion cannot overflow binary64.
    return _elapsed(float(seconds))


@dataclass(frozen=True, slots=True)
class GeometryInstant:
    """An evaluation instant relative to an explicit TT epoch; signed seconds."""

    epoch: TTEpoch
    elapsed_seconds: float

    def __post_init__(self) -> None:
        epoch, elapsed = _epoch(self.epoch), _elapsed(self.elapsed_seconds)
        tt_date_at(epoch, elapsed)  # Check resulting date is representable too.
        object.__setattr__(self, "epoch", epoch)
        object.__setattr__(self, "elapsed_seconds", elapsed)


def _instant(value: object) -> GeometryInstant:
    _exact(value, GeometryInstant, "instant")
    return GeometryInstant(value.epoch, value.elapsed_seconds)


@dataclass(frozen=True, slots=True)
class ReferenceEllipsoid:
    """Independent a/f parameters; derived b and e2 are never persisted.

    Supported conditioning: (b/a)**2 >= 2**-40, finite positive a*(b/a)**2
    and b, and finite a/(b/a). This bounds N/a by 2**20 but does not promise
    Earth-scale error bounds for extreme shapes or dimensions.
    """

    name: str
    equatorial_radius_m: ScalarParameter
    flattening: ScalarParameter

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name or self.name != self.name.strip():
            raise ValueError("ellipsoid name must be nonempty canonical text")
        a = _parameter(self.equatorial_radius_m, "orbit.earth.equatorial-radius", "m")
        f = _parameter(self.flattening, "orbit.earth.flattening", "1")
        if self.equatorial_radius_m.value <= 0 or not 0 <= self.flattening.value < 1 or a.value <= 0 or not 0 <= f.value < 1:
            raise ValueError("ellipsoid requires a > 0 and 0 <= f < 1")
        ratio = 1.0 - f.value
        q = ratio * ratio
        if self.flattening.value > 1 - 2**-20 or q < _MIN_AXIS_RATIO_SQUARED:
            raise ValueError("ellipsoid exceeds supported axis-ratio conditioning")
        if not all(isfinite(x) and x > 0 for x in (
            a.value * ratio, a.value * q, a.value / ratio,
        )):
            raise ValueError("ellipsoid derived radii must be finite and positive")
        object.__setattr__(self, "equatorial_radius_m", a)
        object.__setattr__(self, "flattening", f)

    @property
    def polar_radius_m(self) -> float:
        return self.equatorial_radius_m.value * (1.0 - self.flattening.value)

    @property
    def eccentricity_squared(self) -> float:
        return self.flattening.value * (2.0 - self.flattening.value)


def _ellipsoid(value: object) -> ReferenceEllipsoid:
    _exact(value, ReferenceEllipsoid, "ellipsoid")
    return ReferenceEllipsoid(value.name, value.equatorial_radius_m, value.flattening)


@dataclass(frozen=True, slots=True)
class GeodeticLocation:
    """Geodetic radians and ellipsoidal metres, never geoid/sea-level height.

    Latitude [-pi/2, pi/2], east longitude [-pi, pi), no implicit wrapping or
    height. The supported inward normal extension is h > -a*(1-f)**2, the
    negative minimum meridional curvature radius. It admits negative heights
    while excluding inward normal folds and their degenerate boundary.
    """

    ellipsoid: ReferenceEllipsoid
    latitude_rad: float
    longitude_rad: float
    ellipsoidal_height_m: float

    def __post_init__(self) -> None:
        ellipsoid = _ellipsoid(self.ellipsoid)
        lat = _real("latitude_rad", self.latitude_rad)
        lon = _real("longitude_rad", self.longitude_rad)
        height = _real("ellipsoidal_height_m", self.ellipsoidal_height_m)
        if (not -pi / 2 <= self.latitude_rad <= pi / 2
                or not -pi <= self.longitude_rad < pi
                or not -pi / 2 <= lat <= pi / 2 or not -pi <= lon < pi):
            raise ValueError("geodetic angles outside canonical ranges")
        q = (1.0 - ellipsoid.flattening.value)**2
        if self.ellipsoidal_height_m <= -ellipsoid.equatorial_radius_m.value * q or height <= -ellipsoid.equatorial_radius_m.value * q:
            raise ValueError("height reaches the unsupported inward normal domain")
        object.__setattr__(self, "ellipsoid", ellipsoid)
        object.__setattr__(self, "latitude_rad", lat)
        object.__setattr__(self, "longitude_rad", lon)
        object.__setattr__(self, "ellipsoidal_height_m", height)


class FrameKind(str, Enum):
    EARTH_FIXED = "EARTH_FIXED"
    MODEL_INERTIAL = "MODEL_INERTIAL"


@dataclass(frozen=True, slots=True)
class UniformRotationDefinition:
    """Active positive-z rotation theta0 + omega*t; constant rate is a model.

    theta0 must be in [-pi, pi); omega is signed and may be zero. The epoch
    never determines theta0. These axes are not GCRS/ITRS, TEME or SPICE J2000.
    """

    epoch: TTEpoch
    initial_phase_rad: ScalarParameter
    angular_velocity_rad_per_s: ScalarParameter

    def __post_init__(self) -> None:
        epoch = _epoch(self.epoch)
        phase = _parameter(self.initial_phase_rad, "orbit.rotation.initial-phase", "rad")
        rate = _parameter(self.angular_velocity_rad_per_s, "orbit.rotation.angular-rate", "rad/s")
        if not -pi <= self.initial_phase_rad.value < pi or not -pi <= phase.value < pi:
            raise ValueError("initial phase must be in [-pi, pi)")
        object.__setattr__(self, "epoch", epoch)
        object.__setattr__(self, "initial_phase_rad", phase)
        object.__setattr__(self, "angular_velocity_rad_per_s", rate)


def _rotation(value: object) -> UniformRotationDefinition:
    _exact(value, UniformRotationDefinition, "rotation")
    return UniformRotationDefinition(value.epoch, value.initial_phase_rad, value.angular_velocity_rad_per_s)


@dataclass(frozen=True, slots=True)
class FrameDefinition:
    """Complete model axes: common centre/north z, explicit epoch and rotation.

    EARTH_FIXED x points at geodetic (0,0), y completes the right-handed basis.
    MODEL_INERTIAL axes are fixed; Rz(theta) maps fixed components into them.
    Kind alone is insufficient identity: ellipsoid and full rotation metadata
    participate in compatibility. No mutable registry or local orbital frame.
    """

    kind: FrameKind
    ellipsoid: ReferenceEllipsoid
    rotation: UniformRotationDefinition

    def __post_init__(self) -> None:
        _exact(self.kind, FrameKind, "kind")
        if not any(self.kind is member for member in FrameKind):
            raise ValueError("kind must be an actual frame enum member")
        object.__setattr__(self, "ellipsoid", _ellipsoid(self.ellipsoid))
        object.__setattr__(self, "rotation", _rotation(self.rotation))


def _frame(value: object) -> FrameDefinition:
    _exact(value, FrameDefinition, "frame")
    return FrameDefinition(value.kind, value.ellipsoid, value.rotation)


def _nga_parameter(identifier: str, units: str, value: float, *, derivation: str | None = None) -> ScalarParameter:
    return ScalarParameter(value, ParameterProvenance(
        ParameterId(identifier),
        ProvenanceClass.DERIVED_VALUE if derivation else ProvenanceClass.PUBLIC_SPECIFICATION,
        units, (SourceRecordId("nga-wgs84-defining-parameters"),),
        ProvenanceStatus.VERIFIED, derivation=derivation,
    ))


def wgs84_reference_ellipsoid() -> ReferenceEllipsoid:
    """NGA WGS84 defining shape parameters only; S008, Defining Parameters."""
    return ReferenceEllipsoid(
        "WGS84",
        _nga_parameter("orbit.earth.equatorial-radius", "m", 6_378_137.0),
        _nga_parameter("orbit.earth.flattening", "1", 1.0 / 298.257223563,
                       derivation="f = 1 / 298.257223563 from NGA reciprocal flattening"),
    )


def nominal_earth_angular_velocity() -> ScalarParameter:
    """NGA nominal mean rate; holding it constant is a separate model assumption."""
    return _nga_parameter("orbit.rotation.angular-rate", "rad/s", 7.292115e-5)


__all__ = [
    "TTEpoch", "GeometryInstant", "tt_date_at", "elapsed_seconds_between",
    "ReferenceEllipsoid", "GeodeticLocation", "FrameKind", "FrameDefinition",
    "UniformRotationDefinition", "wgs84_reference_ellipsoid",
    "nominal_earth_angular_velocity",
]
