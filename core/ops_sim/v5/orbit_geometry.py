"""Instantaneous simultaneous geometry, not visibility or spacecraft attitude.

Only the supplied point/state are inputs. A owns geodesy and active rotations;
no orbit query, runtime owner, catalog, service mask or checkpoint is involved.
Geographic inputs are NOT covered by the B2 manifest. See D306/S008.

Numerical resolution policy (binary64 u=2**-53): separation must exceed
64 ulps of the largest supplied/derived position component. This conservative
coordinate-resolution admission rule is not an estimate of B1 or A error.
Normalized cross products reserve 64u for normalization/products/subtraction;
their norm must exceed that budget to define a transverse orbital axis.
Azimuth projection floors are 64u (ENU) and 64u*(1+1/sin(r,v)) (orbital),
reserving one operation budget plus cross-normalization conditioning. These
are explicit working resolution policies, not certified interval bounds.
Below them azimuth is unresolved, without changing the ray or other angles.
Exact zero projection is distinguished from nonzero unresolved projection.
Normalization/product underflow or rounded nonzero cancellation aborts the
query; such lost evidence is never reclassified as a zero projection.

A's geodetic/phase arithmetic, supplied-state propagation error and physical
model error are separate. No universal angular or pass-timing accuracy follows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from math import atan2, cos, fsum, hypot, isfinite, nextafter, sin, tau, ulp

from .frames import (
    CartesianDirection, CartesianState, CartesianVelocity, _position, _velocity,
    geodetic_normal, geodetic_position, transform_direction, transform_state,
)
from .ids import GroundStationId, GroundTargetId
from .orbit_binding import _id, _parameter_text, _text
from .orbit_config import (
    FrameDefinition, FrameKind, GeodeticLocation, ReferenceEllipsoid,
    _ellipsoid, _exact, _parameter,
)
from .parameters import ScalarParameter


_RESOLUTION = 64 * 2.0**-53


def _ellipsoid_text(ellipsoid: ReferenceEllipsoid) -> None:
    _text(ellipsoid.name)
    _parameter_text(ellipsoid.equatorial_radius_m)
    _parameter_text(ellipsoid.flattening)


def _frame_text(frame: FrameDefinition) -> None:
    _text(frame.kind.value)
    _ellipsoid_text(frame.ellipsoid)
    _parameter_text(frame.rotation.initial_phase_rad)
    _parameter_text(frame.rotation.angular_velocity_rad_per_s)


@dataclass(frozen=True, slots=True)
class GroundPointDefinition:
    """Explicit geodetic radians/ellipsoidal metres, each with provenance.

    A owns the unwrapped latitude/longitude and inward-normal height domain.
    At a pole, the supplied longitude selects a local meridian convention.
    A negative height supplies no terrain or unobstructed-ray evidence.
    """

    point_id: GroundStationId | GroundTargetId
    ellipsoid: ReferenceEllipsoid
    latitude_rad: ScalarParameter
    longitude_rad: ScalarParameter
    ellipsoidal_height_m: ScalarParameter

    def __post_init__(self) -> None:
        if type(self.point_id) not in (GroundStationId, GroundTargetId):
            raise TypeError("point_id must be exact GroundStationId or GroundTargetId")
        identity = _id(self.point_id, type(self.point_id))
        ellipsoid = _ellipsoid(self.ellipsoid)
        _ellipsoid_text(ellipsoid)
        parameters = tuple(_parameter(value, identifier, units) for value, identifier, units in (
            (self.latitude_rad, "orbit.ground-point.geodetic-latitude", "rad"),
            (self.longitude_rad, "orbit.ground-point.east-longitude", "rad"),
            (self.ellipsoidal_height_m, "orbit.ground-point.ellipsoidal-height", "m"),
        ))
        for parameter in parameters:
            _parameter_text(parameter)
        # Preserve A's range checks on ORIGINAL reals before binary64 rounding.
        GeodeticLocation(ellipsoid, self.latitude_rad.value, self.longitude_rad.value,
                         self.ellipsoidal_height_m.value)
        object.__setattr__(self, "point_id", identity)
        object.__setattr__(self, "ellipsoid", ellipsoid)
        for name, parameter in zip(("latitude_rad", "longitude_rad", "ellipsoidal_height_m"), parameters):
            object.__setattr__(self, name, parameter)

    @property
    def geodetic_location(self) -> GeodeticLocation:
        # Rebuild on access too: forged evidence never becomes an alternate codec.
        point = _point(self)
        return GeodeticLocation(point.ellipsoid, point.latitude_rad.value,
                                point.longitude_rad.value, point.ellipsoidal_height_m.value)


def _point(value: object) -> GroundPointDefinition:
    _exact(value, GroundPointDefinition, "point")
    return GroundPointDefinition(value.point_id, value.ellipsoid, value.latitude_rad,
                                 value.longitude_rad, value.ellipsoidal_height_m)


def _state(value: object) -> CartesianState:
    _exact(value, CartesianState, "spacecraft_state")
    position, velocity = _position(value.position), _velocity(value.velocity)
    # Check BOTH complete frames before equality can invoke metadata comparison.
    _frame_text(position.frame)
    _frame_text(velocity.frame)
    state = CartesianState(position, velocity)
    if state.position.frame.kind is not FrameKind.MODEL_INERTIAL:
        raise ValueError("spacecraft_state must use MODEL_INERTIAL axes")
    return state


def _finite(value: float) -> float:
    if not isfinite(value):
        raise ValueError("geometry exceeds finite binary64 arithmetic")
    return value


def _unit(vector, name):
    scale = max(map(abs, vector))
    if scale == 0:
        raise ValueError(name + " is zero")
    scaled = tuple(x/scale for x in vector)
    if any(x != 0 and y == 0 for x, y in zip(vector, scaled)):
        raise ValueError(name + " normalization underflows")
    length = hypot(*scaled)
    result = tuple(x/length for x in scaled)
    if any(x != 0 and y == 0 for x, y in zip(scaled, result)):
        raise ValueError(name + " normalization underflows")
    return result


def _dot(a, b):
    try:
        products = tuple(x*y for x, y in zip(a, b))
        if any(x != 0 and y != 0 and p == 0 for x, y, p in zip(a, b, products)):
            raise ValueError("geometry product underflows")
        result = _finite(fsum(products))
        # A rounded cancellation must not be advertised as exact alignment.
        if result == 0 and sum(Fraction(x)*Fraction(y) for x, y in zip(a, b)) != 0:
            raise ValueError("geometry cancellation is numerically unresolved")
        return result
    except OverflowError as error:
        raise ValueError("geometry dot product exceeds binary64 arithmetic") from error


def _cross(a, b):
    return (_dot((a[1], -a[2]), (b[2], b[1])), _dot((a[2], -a[0]), (b[0], b[2])),
            _dot((a[0], -a[1]), (b[1], b[0])))


def _azimuth(y, x, resolution):
    if hypot(x, y) <= resolution:
        return None
    angle = atan2(y, x)
    if angle < 0:
        angle += tau
        # Nearest binary64 addition can round a negative tiny angle to tau.
        # Choose its inward neighbour (<=1 ulp), never rotate/quantize the ray.
        if angle == tau:
            angle = nextafter(tau, 0.0)
    return 0.0 if angle == 0 else angle


def _azimuth_status(projection, resolution):
    return "zero_projection" if projection == 0 else (
        "unresolved_projection" if projection <= resolution else "resolved")


@dataclass(frozen=True, slots=True)
class GroundPointGeometry:
    """Derived snapshot. Constructor accepts only the two complete inputs.

    All Cartesian outputs use the supplied instant and complete inertial frame.
    Orbital x follows transverse INERTIAL motion; z is geocentric nadir;
    y=z cross x. Azimuths run north-to-east and orbital x-to-y, respectively.
    Range rate is positive for separation, with no Doppler interpretation.
    Neither incidence nor off-nadir is clipped to an imaging envelope.
    """

    point: GroundPointDefinition
    spacecraft_state: CartesianState
    ground_state: CartesianState = field(init=False)
    ground_to_spacecraft: CartesianDirection = field(init=False)
    spacecraft_to_ground: CartesianDirection = field(init=False)
    orbital_x: CartesianDirection = field(init=False)
    orbital_y: CartesianDirection = field(init=False)
    orbital_z: CartesianDirection = field(init=False)
    slant_range_m: float = field(init=False)
    slant_range_rate_m_per_s: float = field(init=False)
    elevation_rad: float = field(init=False)
    ground_azimuth_rad: float | None = field(init=False)
    incidence_rad: float = field(init=False)
    off_nadir_rad: float = field(init=False)
    orbital_azimuth_rad: float | None = field(init=False)
    ground_azimuth_projection_norm: float = field(init=False)
    ground_azimuth_resolution: float = field(init=False)
    orbital_azimuth_projection_norm: float = field(init=False)
    orbital_azimuth_resolution: float = field(init=False)

    def __post_init__(self) -> None:
        point, state = _point(self.point), _state(self.spacecraft_state)
        axes, when = state.position.frame, state.position.instant
        if point.ellipsoid != axes.ellipsoid:
            raise ValueError("point and spacecraft ellipsoid definitions differ")
        fixed = FrameDefinition(FrameKind.EARTH_FIXED, axes.ellipsoid, axes.rotation)
        location = point.geodetic_location
        ground = transform_state(CartesianState(
            geodetic_position(location, fixed, when), CartesianVelocity(fixed, when, (0., 0., 0.))), axes)
        r, v = state.position.components_m, state.velocity.components_m_per_s
        rg, vg = ground.position.components_m, ground.velocity.components_m_per_s
        d = tuple(_finite(a-b) for a, b in zip(r, rg))
        rho = _finite(hypot(*d))
        if rho == 0:
            raise ValueError("ground-spacecraft separation is zero")
        if rho <= 64*ulp(max(map(abs, r+rg))):
            raise ValueError("ground-spacecraft separation is numerically unresolved")
        u = _unit(d, "relative direction")
        q = tuple(-x for x in u)
        rhat, vhat = _unit(r, "spacecraft radius"), _unit(v, "spacecraft velocity")
        h = _cross(rhat, vhat)
        sine = hypot(*h)
        if sine == 0:
            raise ValueError("orbital basis is degenerate: radial motion")
        if sine <= _RESOLUTION:
            raise ValueError("orbital basis is numerically unresolved")
        hhat = _unit(h, "angular momentum direction")
        # (r x v) x r = |r|^2 v - (r.v)r, hence x is transverse velocity.
        x_local = _unit(_cross(hhat, rhat), "transverse direction")
        y_local, z_local = tuple(-x for x in hhat), tuple(-x for x in rhat)
        phi, lon = location.latitude_rad, location.longitude_rad
        east = (-sin(lon), cos(lon), 0.)
        north = (-sin(phi)*cos(lon), -sin(phi)*sin(lon), cos(phi))
        def rotated(vector):
            return _unit(transform_direction(CartesianDirection(fixed, when, vector), axes).components, "ENU axis")
        east, north = rotated(east), rotated(north)
        up = rotated(geodetic_normal(location, fixed, when).components)
        e, n, vertical = _dot(u, east), _dot(u, north), _dot(u, up)
        qx, qy, qz = _dot(q, x_local), _dot(q, y_local), _dot(q, z_local)
        ground_projection, orbital_projection = hypot(e, n), hypot(qx, qy)
        orbital_resolution = _RESOLUTION*(1+1/sine)
        def direction(vector):
            return CartesianDirection(axes, when, vector)
        values = {
            "point": point, "spacecraft_state": state, "ground_state": ground,
            "ground_to_spacecraft": direction(u), "spacecraft_to_ground": direction(q),
            "orbital_x": direction(x_local), "orbital_y": direction(y_local), "orbital_z": direction(z_local),
            "slant_range_m": rho,
            "slant_range_rate_m_per_s": _dot(u, tuple(_finite(a-b) for a, b in zip(v, vg))),
            "elevation_rad": atan2(vertical, ground_projection),
            "ground_azimuth_rad": _azimuth(e, n, _RESOLUTION),
            "incidence_rad": atan2(hypot(*_cross(up, u)), _dot(up, u)),
            "off_nadir_rad": atan2(orbital_projection, qz),
            "orbital_azimuth_rad": _azimuth(qy, qx, orbital_resolution),
            "ground_azimuth_projection_norm": ground_projection, "ground_azimuth_resolution": _RESOLUTION,
            "orbital_azimuth_projection_norm": orbital_projection, "orbital_azimuth_resolution": orbital_resolution,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def ground_azimuth_status(self) -> str:
        return _azimuth_status(self.ground_azimuth_projection_norm, self.ground_azimuth_resolution)

    @property
    def orbital_azimuth_status(self) -> str:
        return _azimuth_status(self.orbital_azimuth_projection_norm, self.orbital_azimuth_resolution)


def evaluate_ground_point_geometry(
    point: GroundPointDefinition, spacecraft_state: CartesianState,
) -> GroundPointGeometry:
    """Evaluate one explicit instant; no propagation, visibility or persistence."""
    return GroundPointGeometry(point, spacecraft_state)


__all__ = ["GroundPointDefinition", "GroundPointGeometry", "evaluate_ground_point_geometry"]
