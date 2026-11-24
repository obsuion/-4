"""Additive long total-domain / bounded local-query B43 geometry adapter.
Uses unchanged rational ellipsoid derivation and whole original B38 tubes.
Index acquisition validates ancestry once; caller guards source at actions.
"""
from dataclasses import dataclass, fields, is_dataclass
from fractions import Fraction as Q
from hashlib import sha256
from math import ceil, isfinite, pi
from .mission_continuous_geometry import _Arithmetic, _trig_bounds, _norm2
from .mission_general_geometry import (_geodetic_constants, _ground_bounds,
    _cell, _end_ray, GeneralGeometryCell, GeneralGeometryResult)
from .long_environment import AcquiredLongEnvironment
from .orbit_config import FrameKind, _frame
MODE='CONTINUOUS_ACQUIRED_LONG'
METHOD='B44_LONG_RATIONAL_GEODETIC_CLOSED_TUBE_V1'

@dataclass(frozen=True, slots=True)
class LongGeometryPolicy:
    method: str = METHOD
    maximum_cell_seconds: Q = Q(1, 2)
    maximum_cells: int = 512
    maximum_queries: int = 64
    maximum_operations: int = 2**22
    maximum_control_units: int = 2**22
    maximum_rational_bits: int = 32768
    maximum_retained_bytes: int = 8*2**20

    def __post_init__(self):
        if type(self.method) is not str or self.method != METHOD:
            raise ValueError('unsupported general geometry method')
        if type(self.maximum_cell_seconds) is not Q or not Q(1, 64) <= self.maximum_cell_seconds <= 5:
            raise ValueError('bounded exact cell duration required')
        for name, cap in (('maximum_cells', 512), ('maximum_queries', 64),
                          ('maximum_operations', 2**22), ('maximum_control_units', 2**22),
                          ('maximum_rational_bits', 32768), ('maximum_retained_bytes', 8*2**20)):
            v = getattr(self, name)
            if type(v) is not int or not 1 <= v <= cap:
                raise ValueError('invalid general geometry limit: '+name)
        if self.maximum_rational_bits < 2048:
            raise ValueError('insufficient rational workspace admission')


def admit_long_geometry_domain(environment, entry, policy):
    if type(policy) is not LongGeometryPolicy:
        raise TypeError('general geometry policy required')
    policy.__post_init__(); entry.__post_init__()
    frame = _frame(environment.trajectory.initial_state.position.frame)
    point = entry.point
    if frame.kind is not FrameKind.MODEL_INERTIAL or point.ellipsoid != frame.ellipsoid:
        raise ValueError('foreign full frame/ellipsoid')
    a = Q(frame.ellipsoid.equatorial_radius_m.value)
    f = Q(frame.ellipsoid.flattening.value)
    h = Q(point.ellipsoidal_height_m.value)
    if not 6000000 <= a <= 7000000 or not 0 <= f <= Q(1, 100) or not -100000 <= h <= 1000000:
        raise ValueError('unsupported bounded Earth shape/height domain')
    if not -pi/2 <= entry.visibility_policy.minimum_elevation_rad.value <= pi/2:
        raise ValueError('unsupported geodetic elevation')
    phase = Q(frame.rotation.initial_phase_rad.value)+Q(point.longitude_rad.value)
    rate = Q(frame.rotation.angular_velocity_rad_per_s.value)
    if max(abs(phase+rate*t) for t in (environment.start_seconds, environment.end_seconds)) > 32:
        raise ValueError('UNSUPPORTED_ROTATION_PHASE_DOMAIN')
    if environment.end_seconds-environment.start_seconds > 86400:
        raise ValueError('long source domain exceeds one day')
    return frame, a, f, h, Q(point.latitude_rad.value), phase, rate


def evaluate_long_geometry(authority, environment, entry, start, end, policy, *, held_camera=None, half_fov_rad=None, charge):
    if type(authority) is not AcquiredLongEnvironment or authority.environment is not environment or authority.source is None:
        raise ValueError('indexed original long acquired authority required')
    if type(start) is not Q or type(end) is not Q or end-start>120:
        raise ValueError('bounded local geometry query at most120seconds')
    frame, a, f, h, latitude, phase, rate = admit_long_geometry_domain(environment, entry, policy)
    charge('geometry_queries', 1)
    local = dict(geometry_queries=1, geometry_operations=0, geometry_control_units=0)
    def pay(name, count):
        local[name] += count
        charge(name, count)  # Attempted costs retained, including the refusal.
        cap = {'geometry_operations': policy.maximum_operations, 'geometry_control_units': policy.maximum_control_units}.get(name)
        if cap is not None and local[name] > cap:
            raise ValueError('GENERAL_GEOMETRY_QUERY_QUOTA:'+name)
    ar = _Arithmetic(policy, pay)
    auth=authority.authority_digest;anchor=environment.start_seconds
    if type(start) is not Q or type(end) is not Q or not environment.start_seconds <= start <= end <= environment.end_seconds:
        raise ValueError('exact in-domain closed interval required')
    for t in (start, end):
        if max(abs(t.numerator).bit_length(), t.denominator.bit_length()) > 256:
            raise ValueError('time bit limit')
    constants = _geodetic_constants(ar, a, f, h, latitude)
    sine_gate, _ = _trig_bounds(ar, Q(entry.visibility_policy.minimum_elevation_rad.value), Q(entry.visibility_policy.minimum_elevation_rad.value))
    camera = None; nominal_camera = None; c2 = None; cos_fov = None
    if held_camera is not None:
        if type(held_camera) is not tuple or len(held_camera) != 3:
            raise TypeError('exact held 3D camera required')
        nominal_camera = tuple(ar.q(v) for v in held_camera)
        if max(map(abs, nominal_camera)) > 2:
            raise ValueError('bounded camera vector required')
        camera = tuple((v, v) for v in nominal_camera); c2 = _norm2(ar, camera)[0]
        if c2 <= 0:
            raise ValueError('zero held camera vector')
        if type(half_fov_rad) is not float or not isfinite(half_fov_rad) or not 0 < half_fov_rad < pi/2:
            raise ValueError('supported forward FOV required')
        _, cos_fov = _trig_bounds(ar, Q(half_fov_rad), Q(half_fov_rad))
    elif half_fov_rad is not None:
        raise ValueError('FOV requires held camera')
    plan = []
    for i, support in authority.selected(start,end):
        ar.control(); left = max(start, support.piece.start_seconds); right = min(end, support.piece.end_seconds)
        if left < right or start == end and support.piece.start_seconds <= start <= support.piece.end_seconds and not plan:
            n = max(1, ceil((right-left)/policy.maximum_cell_seconds))
            if len(plan)+n > policy.maximum_cells:
                raise ValueError('GEOMETRY_CELL_LIMIT')
            plan.extend((i, support, left+(right-left)*Q(j, n), left+(right-left)*Q(j+1, n)) for j in range(n))
    if not plan or plan[0][2] != start or plan[-1][3] != end or any(x[3] != y[2] for x, y in zip(plan, plan[1:])):
        raise ValueError('incomplete closed source partition')
    if (len(plan)+2)*128*(2048//4+128) > policy.maximum_retained_bytes:
        raise ValueError('GEOMETRY_RETAINED_BYTES_ADMISSION')
    cells = []
    for i, support, left, right in plan:
        ar.control(); step = authority.source.steps[support.step_id]; tube = step.tube
        if not tube.start_seconds <= left <= right <= tube.end_seconds:
            raise ValueError('foreign closed tube support')
        r = tuple(tuple(ar.q(v) for v in pair) for pair in tube.position_bounds_m)
        if any(x > y or max(abs(x), abs(y)) > 2**30 for x, y in r):
            raise ValueError('invalid Earth-scale source position box')
        ground, normal = _ground_bounds(ar, constants, phase, rate, left, right)
        result = _cell(ar, r, ground, normal, constants, sine_gate, camera, cos_fov, c2)
        cells.append(GeneralGeometryCell(left, right, i, step.id, step.parent_boundary_id, step.endpoint_boundary_id,
            (tube.source_start_seconds, tube.source_end_seconds), r, ground, normal, *result))
    status = 'BLOCKED' if any(c.status == 'BLOCKED' for c in cells) else 'UNRESOLVED' if any(c.status == 'UNRESOLVED' for c in cells) else 'VISIBLE'
    first = terminal = None
    if camera is not None:
        first = _end_ray(ar, cells[0], start, camera, constants['metric'], authority.source, nominal_camera, c2)
        terminal = _end_ray(ar, cells[-1], end, camera, constants['metric'], authority.source, nominal_camera, c2)
    # A height target and reference-body ray intersection are distinct objects.
    # Intersection diagnostics do not override a proved target LOS/FOV result.
    def bits(v):
        if type(v) is Q and max(abs(v.numerator).bit_length(), v.denominator.bit_length()) > 2048:
            raise ValueError('GEOMETRY_PUBLICATION_BIT_LIMIT')
        if type(v) in (tuple, list):
            for x in v: bits(x)
        elif is_dataclass(v):
            for field in fields(v): bits(getattr(v, field.name))
    const = tuple(sorted(constants.items()))
    bits((tuple(cells), first, terminal, const)); ar.control((len(cells)+2)*128)
    from .environment_mission_continuation import _scientific, canonical_json
    convention = 'DECLARED_POLAR_MERIDIAN_AZIMUTH_UNDEFINED_AT_POLE' if abs(float(latitude)) == pi/2 else 'DECLARED_EAST_LONGITUDE_GEODETIC_NORMAL'
    payload = canonical_json(_scientific((MODE, policy, auth, authority.signature, frame, entry, start, end, convention, const, tuple(cells), first, terminal))).encode()
    if len(payload) > policy.maximum_retained_bytes:
        raise ValueError('GEOMETRY_RETAINED_BYTES_LIMIT')
    ar.control((len(payload)+63)//64)
    return GeneralGeometryResult(MODE, METHOD, policy, auth, authority.signature, sha256(payload).hexdigest(), frame,
        entry.point, entry.visibility_policy, start, end, anchor, True, end > start, convention, const, status,
        tuple(cells), first, terminal, ar.operations, ar.controls)
