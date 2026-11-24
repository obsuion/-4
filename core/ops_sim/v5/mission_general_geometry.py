"""B43 bounded rotating geodetic ellipsoid, from whole acquired B38 tubes.

Exact declared binary/rational coefficients define the model. Ground trig,
normal, curvature, LOS and roots use charged rational outward bounds; nominal
C1/libm coordinates never authorize an action. No terrain/RF/pose-error model.
"""
from dataclasses import dataclass, fields, is_dataclass
from fractions import Fraction as Q
from hashlib import sha256
from math import ceil, isfinite, pi
from .mission_continuous_geometry import (_Arithmetic, _AcquiredSource,
    _source_signature, _trig_bounds, _add, _sub, _mul, _square, _dot, _norm2)
from .environment_forcing import _source
from .orbit_config import FrameKind, _frame

MODE = 'CONTINUOUS_B38_GEODETIC_ELLIPSOID_HELD_3D_V1'
METHOD = 'RATIONAL_GEODETIC_QUADRATIC_CLOSED_TUBE_V1'


@dataclass(frozen=True, slots=True)
class GeneralGeometryPolicy:
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


def admit_general_geometry_domain(environment, entry, policy):
    if type(policy) is not GeneralGeometryPolicy:
        raise TypeError('general geometry policy required')
    policy.__post_init__(); entry.__post_init__()
    frame = _frame(environment.source_request.segment.trajectory.initial_state.position.frame)
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
    if environment.end_seconds-environment.start_seconds > 120:
        raise ValueError('general geometry supports at most 120 seconds')
    return frame, a, f, h, Q(point.latitude_rad.value), phase, rate


def _div_positive(ar, numerator, denominator):
    if denominator[0] <= 0:
        raise ValueError('nonpositive interval divisor')
    ar.control(4)
    v = [ar.div(x, y) for x in numerator for y in denominator]
    return min(v), max(v)


def _metric_dot(ar, x, y, metric):
    return _dot(ar, x, tuple(_mul(ar, (d, d), v) for d, v in zip(metric, y)))


def _level(ar, x, metric):
    value = (Q(0), Q(0))
    for d, v in zip(metric, x):
        value = _add(ar, value, _mul(ar, (d, d), _square(ar, v)))
    return value


def _geodetic_constants(ar, a, f, h, latitude):
    """Charged once per query. h=0 uses F(g)=1, not independent g products."""
    b = ar.mul(a, ar.sub(1, f)); e2 = ar.mul(f, ar.sub(2, f))
    sn, cs = _trig_bounds(ar, latitude, latitude)
    s2 = _square(ar, sn); s2 = (max(Q(0), s2[0]), min(Q(1), s2[1]))
    den = _sub(ar, (Q(1), Q(1)), _mul(ar, (e2, e2), s2))
    root = (ar.sqrt(den[0]), ar.sqrt(den[1], True))
    N = _div_positive(ar, (a, a), root)
    da = ar.div(1, ar.mul(a, a)); db = ar.div(1, ar.mul(b, b))
    metric = (da, da, db)
    nDn = _add(ar, (da, da), _mul(ar, (ar.sub(db, da),)*2, s2))
    # g0^T D n = N/a^2; hence C=2hN/a^2+h^2 n^T D n.
    C = (Q(0), Q(0)) if h == 0 else _add(ar,
        _mul(ar, (ar.mul(ar.mul(2, h), da),)*2, N),
        _mul(ar, (ar.mul(h, h),)*2, nDn))
    return dict(a=a, b=b, h=h, e2=e2, sin_latitude=sn, cos_latitude=cs,
                N=N, metric=metric, ground_level_minus_one=C)


def _ground_bounds(ar, constants, phase, rate, left, right):
    angles = [ar.add(phase, ar.mul(rate, t)) for t in (left, right)]
    sn, cs = _trig_bounds(ar, min(angles), max(angles))
    cp = constants['cos_latitude']; sp = constants['sin_latitude']; h = constants['h']
    N = constants['N']; e2 = constants['e2']
    normal = (_mul(ar, cp, cs), _mul(ar, cp, sn), sp)
    nh = _add(ar, N, (h, h))
    vertical = _add(ar, _mul(ar, N, (ar.sub(1, e2),)*2), (h, h))
    ground = (_mul(ar, nh, normal[0]), _mul(ar, nh, normal[1]), _mul(ar, vertical, sp))
    return ground, normal


def _los_predicate(ar, A, B, C, spacecraft_level):
    """Sound sufficient tests; BLOCKED is a uniformly violating cell witness.

    For A>0 the unrestricted minimum is C-B^2/A. Its outward lower
    bound proves clear (even when the vertex is outside the segment).
    A fixed u in (0,1) with polynomial upper<0 proves penetration.
    Surface C=0 and B<0 proves entry by the right derivative at u=0.
    Equalities/uncertain domains remain boundary/unresolved, not occultation.
    """
    if C[1] < 0:
        return 'BLOCKED', 'GROUND_INSIDE', None
    if spacecraft_level[1] < 0:
        return 'BLOCKED', 'SPACECRAFT_INSIDE', None
    outside = spacecraft_level[0] > 0
    if C == (Q(0), Q(0)):
        if B[1] < 0:
            u = min(Q(1, 2), ar.rounded(ar.div(-B[1], A[1]))) if A[1] > 0 else Q(1, 2)
            if u <= 0:return 'BLOCKED', 'SURFACE_INTERIOR_ENTRY', None
            value = _add(ar, _mul(ar, A, (ar.mul(u, u),)*2), _mul(ar, B, (ar.mul(2, u),)*2))
            return 'BLOCKED', 'SURFACE_INTERIOR_ENTRY', (u, (ar.rounded(value[0]), ar.rounded(value[1], True)))
        if outside and A[0] > 0 and B[0] > 0:
            return 'CLEAR', 'SURFACE_OUTWARD', None
        return 'UNRESOLVED', 'SURFACE_TANGENCY_OR_BOUNDARY', None
    if A[0] > 0 and C[0] > 0 and outside:
        if B[0] >= 0:
            return 'CLEAR', 'MONOTONE_OUTWARD', None
        minimum = ar.sub(C[0], ar.div(_square(ar, B)[1], A[0]))
        if minimum > 0:
            return 'CLEAR', 'WHOLE_LINE_MINIMUM_POSITIVE', None
        if ar.add(A[1], B[1]) <= 0:
            return 'CLEAR', 'MONOTONE_INWARD_OUTSIDE_ENDPOINT', None
    witnesses = [Q(1, 2), Q(1, 4), Q(3, 4)]
    amid = ar.div(ar.add(A[0], A[1]), 2)
    if amid > 0:
        u = ar.rounded(ar.div(-ar.div(ar.add(B[0], B[1]), 2), amid))
        if 0 < u < 1:
            witnesses.append(u)
    for u in witnesses:
        ar.control()
        value = _add(ar, _add(ar, _mul(ar, A, (ar.mul(u, u),)*2),
                             _mul(ar, B, (ar.mul(2, u),)*2)), C)
        if value[1] < 0:
            return 'BLOCKED', 'INTERIOR_PENETRATION_WITNESS', (u, (ar.rounded(value[0]), ar.rounded(value[1], True)))
    if A[0] == A[1] and B[0] == B[1] and C[0] == C[1] and A[0] > 0:
        u = ar.div(-B[0], A[0])
        if 0 < u < 1 and ar.sub(C[0], ar.div(ar.mul(B[0], B[0]), A[0])) == 0:
            return 'UNRESOLVED', 'INTERIOR_TANGENCY', (u, (Q(0), Q(0)))
    return 'UNRESOLVED', 'BOUNDARY_OR_MINIMUM_UNCERTAINTY', None


@dataclass(frozen=True, slots=True)
class GeneralGeometryCell:
    start_seconds: Q
    end_seconds: Q
    source_piece_index: int
    source_step_id: int
    parent_boundary_id: int
    endpoint_boundary_id: int
    source_closed_support: tuple
    position_bounds_m: tuple
    ground_position_bounds_m: tuple
    ground_normal_bounds: tuple
    dependent_direction_bounds_m: tuple
    slant_range_bounds_m: tuple
    los_quadratic_ABC: tuple
    los: str
    los_reason: str
    interior_witness: tuple | None
    elevation_sine_bounds: tuple
    geocentric_off_nadir_cosine_bounds: tuple
    camera_dot_direction_bounds_m: tuple | None
    visibility: str
    fov: str
    status: str


def _cell(ar, r, g, n, constants, sine_gate, camera, cos_fov, c2):
    v = tuple(_sub(ar, x, y) for x, y in zip(r, g)); d = tuple((-x[1], -x[0]) for x in v)
    rho2 = _norm2(ar, v); r2 = _norm2(ar, r)
    distance = (ar.sqrt(rho2[0]), ar.sqrt(rho2[1], True))
    metric = constants['metric']
    A = _level(ar, v, metric); B = _metric_dot(ar, g, v, metric)
    C = constants['ground_level_minus_one']
    space = _sub(ar, _level(ar, r, metric), (Q(1), Q(1)))
    los, reason, witness = _los_predicate(ar, A, B, C, space)
    numerator = _dot(ar, n, v)
    elevation = (-Q(1), Q(1)) if distance[0] <= 0 else _div_positive(ar, numerator, distance)
    above = 'VISIBLE' if elevation[0] > sine_gate[1] else 'BLOCKED' if elevation[1] < sine_gate[0] else 'UNRESOLVED'
    vis = 'BLOCKED' if los == 'BLOCKED' or above == 'BLOCKED' else 'VISIBLE' if los == 'CLEAR' and above == 'VISIBLE' else 'UNRESOLVED'
    den = (ar.sqrt(ar.mul(r2[0], rho2[0])), ar.sqrt(ar.mul(r2[1], rho2[1]), True))
    off = (-Q(1), Q(1)) if den[0] <= 0 else _div_positive(ar, _dot(ar, tuple((-x[1], -x[0]) for x in r), d), den)
    off = (max(-Q(1), off[0]), min(Q(1), off[1]))  # Exact cosine domain intersection.
    dot = None; fov = 'NOT_REQUESTED'
    if camera is not None:
        dot = _dot(ar, camera, d)
        if dot[1] < 0 or (dot[1] >= 0 and ar.mul(dot[1], dot[1]) < ar.mul(ar.mul(max(Q(0), cos_fov[0]), max(Q(0), cos_fov[0])), ar.mul(c2, rho2[0]))):
            fov = 'BLOCKED'
        elif dot[0] > 0 and ar.mul(dot[0], dot[0]) > ar.mul(ar.mul(max(Q(0), cos_fov[1]), max(Q(0), cos_fov[1])), ar.mul(c2, rho2[1])):
            fov = 'VISIBLE'
        else:
            fov = 'UNRESOLVED'
    status = 'BLOCKED' if 'BLOCKED' in (vis, fov) else 'UNRESOLVED' if 'UNRESOLVED' in (vis, fov) else 'VISIBLE'
    return (d, distance, (A, B, C), los, reason, witness, elevation, off, dot, vis, fov, status)


@dataclass(frozen=True, slots=True)
class EllipsoidEndRay:
    at_seconds: Q
    source_step_id: int
    source_closed_support: tuple
    origin_position_bounds_m: tuple
    held_inertial_direction: tuple
    forward_ellipsoid_intersection: str
    first_intersection_parameter_bounds_m_per_direction_unit: tuple | None
    second_intersection_parameter_bounds_m_per_direction_unit: tuple | None
    quadratic_Ar_Br_Cr: tuple
    discriminant_bounds: tuple
    origin_bound_kind: str
    source_boundary_id: int | None
    declared_body_axis_norm_squared: Q


def _ray_quadratic(ar, r, camera, metric):
    Ar = _metric_dot(ar, camera, camera, metric)
    if Ar[0] <= 0:
        raise ValueError('zero/uncertain held ray norm')
    Br = _metric_dot(ar, r, camera, metric)
    Cr = _sub(ar, _level(ar, r, metric), (Q(1), Q(1)))
    delta = _sub(ar, _square(ar, Br), _mul(ar, Ar, Cr))
    first = second = None; status = 'UNRESOLVED'
    if Cr[1] < 0:
        status = 'SPACECRAFT_INSIDE'
    elif delta[1] < 0:
        status = 'NO_INTERSECTION'
    elif Cr[0] > 0 and Br[0] >= 0:
        status = 'NO_FORWARD_INTERSECTION'
    elif Cr[0] > 0 and Br[1] < 0 and delta[0] > 0:
        root = (ar.sqrt(delta[0]), ar.sqrt(delta[1], True))
        minus_B = (-Br[1], -Br[0])
        first = _div_positive(ar, _sub(ar, minus_B, root), Ar)
        second = _div_positive(ar, _add(ar, minus_B, root), Ar)
        if first[0] > 0:
            status = 'VISIBLE'
        else:
            first = second = None
    elif delta == (Q(0), Q(0)):
        status = 'GRAZING'
    return status, first, second, (Ar, Br, Cr), delta


def _end_ray(ar, cell, time, camera, metric, source, nominal_camera, c2):
    r = cell.position_bounds_m; kind = 'WHOLE_CLOSED_TUBE_AT_EXACT_TIME'; bid = None
    step = source.steps[cell.source_step_id]
    for identifier in (step.parent_boundary_id, step.endpoint_boundary_id):
        ar.control(); boundary = source.boundaries[identifier]
        if boundary.set.time == time:
            box = []
            for axis in range(3):
                center = ar.q(boundary.set.center[axis]); rad = Q(0)
                for column in boundary.set.generators:
                    ar.control(); rad = ar.add(rad, abs(ar.q(column[axis])))
                scale = ar.q(Q(10)**boundary.scale_exponents[axis])
                box.append((ar.mul(ar.sub(center, rad), scale), ar.mul(ar.add(center, rad), scale)))
            r = tuple(box); kind = 'FULL_ACCUMULATED_SOURCE_BOUNDARY'; bid = identifier
            if any(max(x[0], y[0]) > min(x[1], y[1]) for x, y in zip(r, cell.position_bounds_m)):
                raise ValueError('incompatible terminal boundary and whole tube')
            break
    status, first, second, coeff, delta = _ray_quadratic(ar, r, camera, metric)
    return EllipsoidEndRay(time, step.id, cell.source_closed_support, r, nominal_camera,
        status, first, second, coeff, delta, kind, bid, c2)


@dataclass(frozen=True, slots=True)
class GeneralGeometryResult:
    mode: str
    method: str
    policy: GeneralGeometryPolicy
    authority_digest: str
    source_signature: str
    certificate_id: str
    frame: object
    point: object
    visibility_policy: object
    start_seconds: Q
    end_seconds: Q
    original_anchor_seconds: Q
    closed_support: bool
    positive_duration: bool
    longitude_convention: str
    geodetic_constants: tuple
    status: str
    cells: tuple
    start_ray: EllipsoidEndRay | None
    end_ray: EllipsoidEndRay | None
    operations: int
    control_units: int


def evaluate_general_geometry(authority, environment, entry, start, end, policy, *, held_camera=None, half_fov_rad=None, charge):
    if type(authority) is not _AcquiredSource or authority.environment.source_request != environment.source_request:
        raise ValueError('acquired original source authority required')
    frame, a, f, h, latitude, phase, rate = admit_general_geometry_domain(environment, entry, policy)
    charge('geometry_queries', 1)
    local = dict(geometry_queries=1, geometry_operations=0, geometry_control_units=0)
    def pay(name, count):
        local[name] += count
        charge(name, count)  # Attempted costs retained, including the refusal.
        cap = {'geometry_operations': policy.maximum_operations, 'geometry_control_units': policy.maximum_control_units}.get(name)
        if cap is not None and local[name] > cap:
            raise ValueError('GENERAL_GEOMETRY_QUERY_QUOTA:'+name)
    ar = _Arithmetic(policy, pay)
    ar.control(sum(len(getattr(authority.source, n)) for n in ('steps', 'boundaries', 'pieces', 'geometry_records')))
    if _source_signature(authority.source) != authority.signature:
        raise ValueError('mutated acquired source evidence')
    digest, auth, anchor, last, edges, supports = _source(authority.source, environment)
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
    for i, support in enumerate(supports):
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
