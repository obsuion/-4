"""B52 full-domain nominal world over a bounded original-grid orbit owner.

Two explicit Sun authorities are supported. A supplied accepted Sun table must
cover the WHOLE declared domain and is never clamped or periodically repeated.
Otherwise the reduced circular Sun below is an ASSUMED synthetic scenario model,
not an ephemeris, flight calibration, or accuracy bound. Its coefficients define
distance, annual period, obliquity and phase at the original trajectory anchor.
The original frame owns uniform Earth rotation and all target/station geodesy.

Lighting is evaluated at original-anchor cell midpoints and held over each cell.
Every schedule is cut at that grid and profile/table boundaries. These sampled
holds do not certify eclipse/event times or continuous visibility. Geometry does
not imply station availability, RF admission, electrical feasibility or receipt.
"""
from dataclasses import dataclass
from fractions import Fraction as Q
from bisect import bisect_right, bisect_left
from datetime import datetime, timezone
from math import ceil, cos, sin, tau, pi, isfinite, degrees

from .lifecycle_orbit import (LifecycleOrbitProvider, MAX_DURATION_SECONDS, _identity,
    _integer, _seconds, _qdata, _qread)
from .orbit_j2 import J2CartesianTrajectory, _authorities
from .orbit_config import GeometryInstant, _instant
from .frames import CartesianPosition, CartesianDirection
from .sun_table import SunPositionTable, SunPositionSample, SunTableProvenance, evaluate_sun_position
from .ids import SourceRecordId
from .orbit_sun import SuppliedSunDirection, nominal_parallel_ray
from .environment_forcing import ForcingProfileEntry, EnvironmentForcingCell, _case
from .mission_environment import CatalogPoint, MissionPointObservation
from .orbit_geometry import evaluate_ground_point_geometry
from .orbit_visibility import evaluate_ground_visibility
from .assembly_attitude import vector, angle_between
from .assembly_attitude_3d import BodyAttitude3D


API = 'B52_NOMINAL_LIFECYCLE_WORLD_V1'
ACCOUNTING_API = 'B54_LIFECYCLE_WORLD_ACCOUNTING_V2'
LIGHT_TRACKING = 'ONLY_EXPLICIT_SELECTED_SUPPORT_COMMITS'
NOMINAL = 'NOMINAL_LONG'
SUN_METHOD = 'B52_ASSUMED_CIRCULAR_ANNUAL_SUN_V1'
LIGHT_TALLY_METHOD = 'B53_SELECTED_ACTUAL_SAMPLED_HELD_LIGHT_DURATION_V1'
LIGHT_FLAGS = ('ILLUMINATED', 'OCCULTED', 'UNRESOLVED')


def _table_authority(table):
    """Validate an immutable admitted table by data reads, without rebuilding it.

    A lifecycle world retains the original input authority. Re-copying it via
    the accepted general Sun codec would decode constructors during a cold
    advanced-state restore. This local boundary checks its declared table and
    provenance invariants directly; actual interpolation remains the accepted
    evaluate_sun_position owner, called only during new paid evolution.
    """
    if type(table) is not SunPositionTable:
        raise TypeError('exact admitted Sun table authority required')
    if type(table.interpolation) is not str or table.interpolation != 'LINEAR_POSITION_V1':
        raise ValueError('accepted Sun position interpolation required')
    if type(table.samples) is not tuple or not 2 <= len(table.samples) <= 1024:
        raise ValueError('bounded admitted Sun samples required')
    last = None
    for sample in table.samples:
        if type(sample) is not SunPositionSample or type(sample.elapsed_seconds) is not float or not isfinite(sample.elapsed_seconds):
            raise ValueError('exact finite admitted Sun sample time required')
        if last is not None and sample.elapsed_seconds <= last:
            raise ValueError('strictly ordered Sun sample times required')
        if (type(sample.position_m) is not tuple or len(sample.position_m) != 3 or
                any(type(x) is not float or not isfinite(x) for x in sample.position_m) or
                not any(sample.position_m)):
            raise ValueError('finite nonzero admitted Sun position required')
        last = sample.elapsed_seconds
    if (type(table.domain_seconds) is not tuple or len(table.domain_seconds) != 2 or
            any(type(x) is not float or not isfinite(x) for x in table.domain_seconds) or
            table.domain_seconds != (table.samples[0].elapsed_seconds, table.samples[-1].elapsed_seconds)):
        raise ValueError('Sun domain must be the exact first/last sample times')
    p = table.provenance
    if type(p) is not SunTableProvenance:
        raise TypeError('exact admitted Sun provenance required')
    def text(value):
        if type(value) is not str or not value.strip():
            raise ValueError('nonblank exact Sun provenance text required')
        value.encode('utf-8', errors='strict')
    for name in ('source_kind', 'target', 'center', 'axes', 'reference_plane', 'correction',
            'source_timescale', 'source_units', 'conversion', 'alignment', 'source_uri',
            'accuracy_policy', 'accuracy_statement', 'alignment_rationale'):
        text(getattr(p, name))
    if (p.target, p.center, p.correction, p.source_timescale, p.accuracy_policy) != ('10', '500@399', 'GEOMETRIC', 'TT', 'UNQUANTIFIED'):
        raise ValueError('unsupported admitted Sun metadata')
    if (p.source_units, p.conversion) not in (('M', 'IDENTITY_METRES'), ('KM', 'EXACT_KM_TIMES_1000')):
        raise ValueError('unsupported admitted Sun source unit conversion')
    if type(p.source_ids) is not tuple:
        raise TypeError('immutable Sun source IDs required')
    for source in p.source_ids:
        if type(source) is not SourceRecordId:
            raise TypeError('exact Sun source ID required')
        text(source.value)
    if len(set(p.source_ids)) != len(p.source_ids):
        raise ValueError('duplicate admitted Sun source IDs')
    if p.source_kind == 'SYNTHETIC':
        if (p.axes, p.reference_plane, p.alignment) != ('MODEL_INERTIAL', 'MODEL_EQUATOR', 'IDENTITY_MODEL'):
            raise ValueError('incompatible admitted synthetic Sun axes')
        if any(x is not None for x in (p.retrieved_utc, p.request_sha256, p.response_sha256, p.ephemeris_id)):
            raise ValueError('synthetic Sun must not fabricate retrieval evidence')
    elif p.source_kind == 'HORIZONS':
        if (p.axes, p.reference_plane, p.alignment) != ('ICRF', 'FRAME', 'ASSUMED_ICRF_MODEL_IDENTITY') or not p.source_ids:
            raise ValueError('incompatible admitted Horizons source binding')
        text(p.retrieved_utc); text(p.ephemeris_id)
        when = datetime.fromisoformat(p.retrieved_utc)
        if when.tzinfo is None or when.utcoffset() != timezone.utc.utcoffset(when):
            raise ValueError('Sun retrieval timestamp must declare UTC')
        for value in (p.request_sha256, p.response_sha256):
            if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('Sun retrieval lowercase SHA-256 required')
    else:
        raise ValueError('unsupported admitted Sun source kind')
    return table


@dataclass(frozen=True, slots=True)
class ReducedSunPolicy:
    """All numerical coefficients are declared ASSUMED scenario inputs in SI.

    s(lambda)=distance*(cos(lambda),cos(epsilon)*sin(lambda),
    sin(epsilon)*sin(lambda)); lambda=phase+2*pi*(t-original_anchor)/period.
    This is a deterministic derivation from the declared circle, not a sourced
    accuracy claim. Distance is fixed; no eccentricity, precession, nutation,
    aberration, UTC/TDB conversion, or solar-output ageing law is supplied here.
    """
    distance_m: float = 149597870700.0
    period_seconds: float = 31557600.0
    obliquity_rad: float = 0.40909280422232897
    phase_at_anchor_rad: float = 0.0
    provenance: str = 'ASSUMED_SYNTHETIC_CIRCULAR_SUN_NOT_FLIGHT_CALIBRATED'
    method: str = SUN_METHOD

    def __post_init__(self):
        if type(self.method) is not str or self.method != SUN_METHOD:
            raise ValueError('unknown reduced Sun method')
        for name in ('distance_m', 'period_seconds', 'obliquity_rad', 'phase_at_anchor_rad'):
            value = getattr(self, name)
            if type(value) is not float or not isfinite(value):
                raise ValueError('finite binary64 reduced Sun coefficient required: '+name)
        if not 1e9 <= self.distance_m <= 1e14 or not 86400 <= self.period_seconds <= 2**40:
            raise ValueError('reduced Sun distance/period outside declared model domain')
        if abs(self.obliquity_rad) > pi/2 or abs(self.phase_at_anchor_rad) > tau:
            raise ValueError('reduced Sun angles outside declared radians domain')
        if type(self.provenance) is not str or self.provenance != 'ASSUMED_SYNTHETIC_CIRCULAR_SUN_NOT_FLIGHT_CALIBRATED':
            raise ValueError('explicit ASSUMED reduced Sun provenance required')


@dataclass(frozen=True, slots=True)
class LifecycleWorld:
    trajectory: J2CartesianTrajectory
    start_seconds: Q
    end_seconds: Q
    node_ids: tuple
    profile: tuple
    sun: ReducedSunPolicy = ReducedSunPolicy()
    sun_table: object = None
    lighting_step_seconds: int = 60
    max_lighting_records: int = 256
    max_schedule_cells: int = 256
    max_index_control_units: int = 2**40
    mode: str = NOMINAL
    api: str = API

    def __post_init__(self):
        if type(self.trajectory) is not J2CartesianTrajectory:
            raise TypeError('original Cartesian trajectory required')
        state, _ = _authorities(self.trajectory.initial_state, self.trajectory.gravity_model)
        a, b = _seconds(self.start_seconds), _seconds(self.end_seconds)
        if a != Q(state.position.instant.elapsed_seconds) or not 0 < b-a <= MAX_DURATION_SECONDS:
            raise ValueError('original anchor and finite <=15 Julian year world domain required')
        if type(self.sun) is not ReducedSunPolicy:
            raise TypeError('explicit reduced Sun policy required')
        self.sun.__post_init__()
        if self.sun_table is not None:
            table = _table_authority(self.sun_table)
            if type(table.frame) is not type(state.position.frame) or type(table.epoch) is not type(state.position.instant.epoch):
                raise TypeError('exact admitted Sun frame and epoch required')
            if table.frame != state.position.frame or table.epoch != state.position.instant.epoch:
                raise ValueError('Sun/world original frame or TT epoch mismatch')
            if not Q(table.domain_seconds[0]) <= a < b <= Q(table.domain_seconds[1]):
                raise ValueError('SUN_TABLE_WHOLE_DOMAIN_COVERAGE_REQUIRED_NO_CLAMP')
        if type(self.node_ids) is not tuple or not 1 <= len(self.node_ids) <= 64 or len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError('bounded distinct thermal node IDs required')
        if type(self.profile) is not tuple or not 1 <= len(self.profile) <= 128:
            raise ValueError('bounded full-domain forcing profile required')
        last = a
        for entry in self.profile:
            if type(entry) is not ForcingProfileEntry:
                raise TypeError('exact forcing profile entry required')
            entry.__post_init__()
            if entry.start_seconds != last or {n.node_id for n in entry.nodes} != set(self.node_ids):
                raise ValueError('forcing profile gap/foreign thermal nodes')
            last = entry.end_seconds
        if last != b:
            raise ValueError('forcing profile must cover the whole lifecycle domain')
        for name, cap in (('lighting_step_seconds', 120), ('max_lighting_records', 65536),
                          ('max_schedule_cells', 8192), ('max_index_control_units', 2**48)):
            _integer(getattr(self, name), name, 1, cap)
        if type(self.mode) is not str or self.mode != NOMINAL or type(self.api) is not str or self.api != API:
            raise ValueError('explicit B52 nominal world identity required')


@dataclass(frozen=True, slots=True)
class LifecycleSchedule:
    cells: tuple


@dataclass(frozen=True, slots=True)
class LifecycleLightingDelta:
    """Prepared selected support, never a query/forecast/trial observation."""
    identity: str
    start_seconds: Q
    end_seconds: Q
    durations: tuple
    spans: tuple
    method: str = LIGHT_TALLY_METHOD

    def __post_init__(self):
        if type(self.identity) is not str or len(self.identity) != 64 or any(c not in '0123456789abcdef' for c in self.identity):
            raise ValueError('exact lighting consumption owner digest required')
        if type(self.start_seconds) is not Q or type(self.end_seconds) is not Q or self.start_seconds > self.end_seconds:
            raise ValueError('ordered exact lighting consumption seconds required')
        if type(self.method) is not str or self.method != LIGHT_TALLY_METHOD:
            raise ValueError('explicit selected sampled-held lighting duration method required')
        if type(self.durations) is not tuple or len(self.durations) != 3 or any(type(v) is not Q or v < 0 for v in self.durations):
            raise ValueError('three exact nonnegative lighting durations required')
        if sum(self.durations, Q(0)) != self.end_seconds-self.start_seconds:
            raise ValueError('lighting delta must partition the selected interval')
        if type(self.spans) is not tuple or len(self.spans) > 8192:
            raise ValueError('bounded immutable selected lighting support required')
        totals = {flag: Q(0) for flag in LIGHT_FLAGS}; last = self.start_seconds
        for span in self.spans:
            if type(span) is not tuple or len(span) != 3:
                raise ValueError('exact selected lighting span required')
            a,b,flag = span
            if type(a) is not Q or type(b) is not Q or not a == last < b or type(flag) is not str or flag not in totals:
                raise ValueError('contiguous selected lighting support required')
            totals[flag] += b-a; last = b
        if last != self.end_seconds or tuple(totals[f] for f in LIGHT_FLAGS) != self.durations:
            raise ValueError('selected lighting support/totals mismatch')


class AcquiredLifecycleWorld:
    """One actual/forecast scope's bounded lighting cache and static world index."""
    def __init__(self, environment, provider, *, charge=None):
        self._configure(environment, provider, charge)
        self.controls = self.lookups = self.guards = self.sun_queries = 0
        self.lighting_evaluations = self.lighting_evictions = self.peak_lighting_records = 0
        self.retention_floor = environment.start_seconds
        self._lighting = {}
        self.pay(512)

    def _configure(self, environment, provider, charge):
        if type(environment) is not LifecycleWorld or type(provider) is not LifecycleOrbitProvider:
            raise TypeError('exact lifecycle world and orbit owners required')
        environment.__post_init__()
        provider.validate(environment.trajectory)
        if environment.end_seconds-environment.start_seconds > provider.policy.max_duration_seconds:
            raise ValueError('orbit policy does not cover the full world')
        self.environment, self.provider, self._charge = environment, provider, charge
        self.role = provider.role
        self.identity = _identity((API, environment, self.role))
        self.controls = 0
        self._consumed_through = environment.start_seconds
        self._light_durations = {flag: Q(0) for flag in LIGHT_FLAGS}
        self._light_commits = 0
        self._profiles = tuple(e.start_seconds for e in environment.profile)
        self._profile_cuts = tuple(e.end_seconds for e in environment.profile[:-1])
        self._table_cuts = (() if environment.sun_table is None else
                            tuple(Q(s.elapsed_seconds) for s in environment.sun_table.samples[1:-1]))
        self.source = self.source_digest = self.authority_digest = self.signature = None
        self.supports = self.ancestry = ()
        self.steps = {}

    def pay(self, count):
        _integer(count, 'world prospective control work')
        if self.controls+count > self.environment.max_index_control_units:
            raise ValueError('LIFECYCLE_WORLD_CONTROL_QUOTA_BEFORE_WORK')
        if self._charge is not None:
            self._charge('index_control_units', count)
        self.controls += count

    def _domain(self, a, b):
        a, b = _seconds(a), _seconds(b)
        if not self.environment.start_seconds <= a <= b <= self.environment.end_seconds:
            raise ValueError('exact in-domain lifecycle interval required')
        if a < self.retention_floor:
            raise ValueError('LIFECYCLE_WORLD_BEFORE_RETAINED_WINDOW')

    def guard(self):
        self.pay(512)
        self.guards += 1
        self.provider.validate(self.environment.trajectory)
        if _identity((API, self.environment, self.role)) != self.identity:
            raise ValueError('foreign/mutated lifecycle world authority')

    def sun_position(self, instant):
        instant = _instant(instant)
        e = self.environment
        if instant.epoch != e.trajectory.initial_state.position.instant.epoch:
            raise ValueError('Sun query requires original TT epoch')
        seconds = Q(instant.elapsed_seconds)
        self._domain(seconds, seconds)
        self.pay(64)
        self.sun_queries += 1
        if e.sun_table is not None:
            return evaluate_sun_position(e.sun_table, instant)
        p = e.sun
        phase = p.phase_at_anchor_rad+tau*float((seconds-e.start_seconds) % Q(p.period_seconds))/p.period_seconds
        xyz = (p.distance_m*cos(phase), p.distance_m*cos(p.obliquity_rad)*sin(phase),
               p.distance_m*sin(p.obliquity_rad)*sin(phase))
        return CartesianPosition(e.trajectory.initial_state.position.frame, instant, xyz)

    def _nominal_light(self, index):
        if index not in self._lighting:
            e = self.environment
            a = e.start_seconds+index*e.lighting_step_seconds
            b = min(e.end_seconds, a+e.lighting_step_seconds)
            self._domain(a, b)
            orbit = self.provider.at_seconds((a+b)/2)
            sun = self.sun_position(orbit.position.instant)
            direction = CartesianDirection(orbit.position.frame, orbit.position.instant,
                tuple(s-r for s, r in zip(sun.components_m, orbit.position.components_m)))
            table = e.sun_table
            origin = ('EXTERNALLY_SUPPLIED' if table is not None and table.provenance.source_kind != 'SYNTHETIC' else 'SYNTHETIC')
            source_ids = () if table is None else table.provenance.source_ids
            supplied = SuppliedSunDirection(direction, origin, source_ids,
                'B52 nominal parallel-ray sample held on the original lighting grid; no interval or event-time certificate.')
            assessment = nominal_parallel_ray(orbit.position, supplied)
            if assessment == 'TANGENT':
                assessment = 'UNRESOLVED'
            if assessment not in ('ILLUMINATED', 'OCCULTED', 'UNRESOLVED'):
                raise ValueError('LIFECYCLE_NOMINAL_LIGHTING_UNSUPPORTED:'+str(assessment))
            self.pay(256)
            self.lighting_evaluations += 1
            if len(self._lighting) >= e.max_lighting_records:
                # Pure derived lighting can be evicted; unlike orbital seeds it
                # is not needed to define a future integration rounding path.
                oldest = min(self._lighting)
                if index > oldest:
                    del self._lighting[oldest]
                    self.lighting_evictions += 1
                else:
                    return assessment
            self._lighting[index] = assessment
            self.peak_lighting_records = max(self.peak_lighting_records, len(self._lighting))
        self.pay(16)
        return self._lighting[index]

    def schedule(self, a, b):
        self._domain(a, b)
        e = self.environment
        self.pay(64)
        self.lookups += 1
        first = int((a-e.start_seconds)//e.lighting_step_seconds)
        last = int((b-e.start_seconds)//e.lighting_step_seconds)
        if last-first+1 > e.max_schedule_cells+1:
            raise ValueError('LIFECYCLE_FORCING_CELL_CAPACITY_BEFORE_WORK')
        points = {a, b}
        for cuts in (self._profile_cuts, self._table_cuts):
            left, right = bisect_right(cuts, a), bisect_left(cuts, b)
            points.update(cuts[left:right])
        points.update(e.start_seconds+i*e.lighting_step_seconds
                      for i in range(first+1, last+1) if a < e.start_seconds+i*e.lighting_step_seconds < b)
        ordered = sorted(points)
        pairs = tuple(zip(ordered, ordered[1:])) if a < b else ((a, b),)
        if len(pairs) > e.max_schedule_cells:
            raise ValueError('LIFECYCLE_FORCING_CELL_CAPACITY_BEFORE_WORK')
        self.pay(128*len(pairs))
        cells = []
        total = ceil((e.end_seconds-e.start_seconds)/e.lighting_step_seconds)
        for left, right in pairs:
            mid = (left+right)/2
            profile = max(0, bisect_right(self._profiles, mid)-1)
            index = min(total-1, int((mid-e.start_seconds)//e.lighting_step_seconds))
            assessment = self._nominal_light(index)
            alternatives = tuple(_case(e.profile[profile], flag) for flag in
                ((True, False) if assessment == 'UNRESOLVED' else (assessment == 'ILLUMINATED',)))
            cells.append(EnvironmentForcingCell(left, right, assessment, index, profile, alternatives))
        return LifecycleSchedule(tuple(cells))

    def orientation_inputs(self, hardware, time, quaternion):
        """Same M3 body-axis/common-inertial convention as accepted physics leaves."""
        time = _seconds(time)
        self._domain(time, time)
        if self._charge is not None:
            self._charge('spatial_reserved_units', 128)
        orbit = self.provider.at_seconds(time)
        sun = self.sun_position(orbit.position.instant)
        direction = vector(tuple(a-b for a, b in zip(sun.components_m, orbit.position.components_m)))
        pose = BodyAttitude3D(hardware.design.body_frame_id, orbit.position.frame, time, quaternion, time)
        camera, panel = pose.direction(hardware.camera_body_axis), pose.direction(hardware.panel_body_normal)
        return degrees(angle_between(panel, direction)), camera, panel

    def observations(self, entry, a, b, sampling):
        self._domain(a, b)
        if type(entry) is not CatalogPoint:
            raise TypeError('accepted explicit catalog point required')
        entry.__post_init__()
        interval = _integer(sampling.maximum_interval_seconds, 'geometry interval', 1, 120)
        maximum = _integer(sampling.maximum_timestamps, 'geometry timestamps', 1, 8192)
        count = max(1, ceil((b-a)/interval))
        if (count+1 if a < b else 1) > maximum:
            raise ValueError('LIFECYCLE_GEOMETRY_SAMPLE_CAPACITY_BEFORE_WORK')
        times = tuple(a+(b-a)*Q(i, count) for i in range(count+1)) if a < b else (a,)
        if entry.point.ellipsoid != self.environment.trajectory.initial_state.position.frame.ellipsoid:
            raise ValueError('foreign target/station ellipsoid')
        result = []
        for t in times:
            if self._charge is not None:
                self._charge('point_geometry_queries', 1)
            orbit = self.provider.at_seconds(t)
            geometry = evaluate_ground_point_geometry(entry.point, orbit)
            visibility = evaluate_ground_visibility(entry.point, orbit, entry.visibility_policy)
            result.append(MissionPointObservation(entry.point.point_id, t, orbit.position.instant,
                Q(orbit.position.instant.elapsed_seconds)-t, geometry, visibility,
                entry.station_available, entry.rf_admitted, entry.nominal_rate_bps,
                entry.service_assumption, API))
        return tuple(result)

    def prepare_support_delta(self, a, b):
        """Read already evaluated support before selected context publication.

        There is no orbit/Sun/geometry call here. Retained cache data must cover
        the entire interval. Trial/forecast schedules never advance this tally.
        Preparation work is prospective and nonrefunded even if a later physical
        admission refuses the selected context. Commit is a small data operation.
        """
        a,b = _seconds(a),_seconds(b)
        if self.role != 'ACTUAL':
            raise ValueError('FORECAST_LIGHTING_CONSUMPTION_FORBIDDEN')
        if a != self._consumed_through:
            raise ValueError('LIGHTING_SELECTED_CONSUMPTION_GAP_OR_DUPLICATE')
        self._domain(a,b)
        e = self.environment
        first = int((a-e.start_seconds)//e.lighting_step_seconds)
        count = 0 if a == b else ceil((b-e.start_seconds)/e.lighting_step_seconds)-first
        if count > e.max_schedule_cells:
            raise ValueError('LIGHTING_SELECTED_CONSUMPTION_SPAN_CAP_BEFORE_WORK')
        self.pay(64+32*count)
        spans=[]; totals={flag:Q(0) for flag in LIGHT_FLAGS}; left=a
        for index in range(first,first+count):
            right=min(b,e.start_seconds+(index+1)*e.lighting_step_seconds)
            flag=self._lighting.get(index)
            if flag not in LIGHT_FLAGS:
                raise ValueError('LIGHTING_CONSUMPTION_REQUIRES_EXISTING_SELECTED_SUPPORT')
            if left < right:
                spans.append((left,right,flag));totals[flag]+=right-left;left=right
        return LifecycleLightingDelta(self.identity,a,b,tuple(totals[f] for f in LIGHT_FLAGS),tuple(spans))

    def commit_support_delta(self, delta):
        """Commit one prepared contiguous interval alongside selected physics.

        This consumes only saved classifications. It certifies neither a
        continuous eclipse nor a dynamically reachable fabricated snapshot.
        """
        if type(delta) is not LifecycleLightingDelta:
            raise TypeError('exact prepared lighting consumption required')
        delta.__post_init__()
        if (self.role != 'ACTUAL' or delta.identity != self.identity or
                delta.start_seconds != self._consumed_through or delta.end_seconds > self.environment.end_seconds):
            raise ValueError('foreign/stale selected lighting consumption')
        for a,b,flag in delta.spans:
            index=int((a-self.environment.start_seconds)//self.environment.lighting_step_seconds)
            right=self.environment.start_seconds+(index+1)*self.environment.lighting_step_seconds
            if b>right or self._lighting.get(index)!=flag:
                raise ValueError('prepared lighting consumption differs from retained sampled support')
        if delta.end_seconds == delta.start_seconds:
            return
        for flag, duration in zip(LIGHT_FLAGS,delta.durations):
            self._light_durations[flag] += duration
        self._consumed_through = delta.end_seconds
        self._light_commits += 1

    def consume_support(self, a, b):
        """Convenience transaction for an already returned selected interval."""
        delta=self.prepare_support_delta(a,b)
        self.commit_support_delta(delta)
        return delta

    def lighting_accounting(self):
        e=self.environment
        return dict(method=LIGHT_TALLY_METHOD, units='s',
            scope=('SELECTED_ACTUAL_CONSUMED_SUPPORT' if self.role == 'ACTUAL' else
                   'INHERITED_ACTUAL_PREFIX_ONLY_NO_FORECAST_CONSUMPTION'),
            start_seconds=_qdata(e.start_seconds),end_seconds=_qdata(self._consumed_through),
            covered_seconds=_qdata(self._consumed_through-e.start_seconds),
            illuminated_seconds=_qdata(self._light_durations['ILLUMINATED']),
            occulted_seconds=_qdata(self._light_durations['OCCULTED']),
            unresolved_seconds=_qdata(self._light_durations['UNRESOLVED']),
            selected_commits=self._light_commits,
            qualification='NOMINAL_SAMPLED_HELD_GRID_NOT_CONTINUOUS_ECLIPSE_OR_EVENT_TIME')

    def next_boundary_after(self, time):
        time = _seconds(time)
        self._domain(time, time)
        e = self.environment
        if time == e.end_seconds:
            return e.end_seconds
        index = int((time-e.start_seconds)//e.lighting_step_seconds)+1
        candidates = [e.end_seconds, e.start_seconds+index*e.lighting_step_seconds]
        for cuts in (self._profile_cuts, self._table_cuts):
            i = bisect_right(cuts, time)
            if i < len(cuts):
                candidates.append(cuts[i])
        return min(candidates)

    def retain_from(self, seconds):
        seconds = _seconds(seconds)
        if not self.retention_floor <= seconds <= self.environment.end_seconds:
            raise ValueError('monotone lifecycle world retention watermark required')
        e = self.environment
        # Keep the *whole* current sampled-light cell, including its midpoint.
        cell_start = e.start_seconds+int((seconds-e.start_seconds)//e.lighting_step_seconds)*e.lighting_step_seconds
        floor = max(e.start_seconds, min(cell_start, seconds))
        self.pay(64)
        self.provider.retain_from(max(self.provider.retention_floor, floor))
        self.retention_floor = floor
        for index in tuple(self._lighting):
            if e.start_seconds+(index+1)*e.lighting_step_seconds <= floor:
                del self._lighting[index]
                self.lighting_evictions += 1

    def to_data(self):
        return {'format': API, 'identity': self.identity, 'provider_identity': self.provider.identity,
                'role': self.role, 'retention_floor': _qdata(self.retention_floor),
                'lighting': [[i, s] for i, s in sorted(self._lighting.items())],
                'controls': self.controls, 'lookups': self.lookups, 'guards': self.guards,
                'sun_queries': self.sun_queries, 'lighting_evaluations': self.lighting_evaluations,
                'lighting_evictions': self.lighting_evictions,
                'peak_lighting_records': self.peak_lighting_records,
                'lighting_consumption': self.lighting_accounting()}

    @classmethod
    def from_data(cls, environment, provider, data, *, charge=None):
        keys = {'format', 'identity', 'provider_identity', 'role', 'retention_floor', 'lighting',
                'controls', 'lookups', 'guards', 'sun_queries', 'lighting_evaluations',
                'lighting_evictions', 'peak_lighting_records', 'lighting_consumption'}
        if type(data) is not dict or set(data) != keys or data['format'] != API:
            raise ValueError('exact lifecycle world snapshot fields required')
        owner = cls.__new__(cls)
        owner._configure(environment, provider, charge)
        if data['identity'] != owner.identity or data['provider_identity'] != provider.identity or data['role'] != owner.role:
            raise ValueError('foreign lifecycle world snapshot ownership')
        floor = _qread(data['retention_floor'])
        if not environment.start_seconds <= floor <= environment.end_seconds:
            raise ValueError('world snapshot retention floor outside domain')
        if (floor-environment.start_seconds) % environment.lighting_step_seconds:
            raise ValueError('world snapshot retention floor must retain whole lighting cells')
        if type(data['lighting']) is not list or len(data['lighting']) > environment.max_lighting_records:
            raise ValueError('bounded lighting snapshot required')
        lighting, last = {}, -1
        total = ceil((environment.end_seconds-environment.start_seconds)/environment.lighting_step_seconds)
        for row in data['lighting']:
            if type(row) is not list or len(row) != 2:
                raise ValueError('exact lighting cache entry required')
            index = _integer(row[0], 'lighting index', 0, total-1)
            if index <= last or type(row[1]) is not str or row[1] not in ('ILLUMINATED', 'OCCULTED', 'UNRESOLVED'):
                raise ValueError('ordered lighting cache status required')
            if environment.start_seconds+(index+1)*environment.lighting_step_seconds <= floor:
                raise ValueError('obsolete lighting cache entry')
            lighting[index] = row[1]
            last = index
        for name in keys-{'format', 'identity', 'provider_identity', 'role', 'retention_floor', 'lighting', 'lighting_consumption'}:
            value = _integer(data[name], name)
            setattr(owner, name, value)
        minimum_controls = (512+64*owner.lookups+512*owner.guards+
                            64*owner.sun_queries+256*owner.lighting_evaluations)
        if (owner.controls < minimum_controls or owner.controls > environment.max_index_control_units or
            owner.peak_lighting_records > environment.max_lighting_records or
            owner.peak_lighting_records < len(lighting) or
            owner.lighting_evaluations < len(lighting)+owner.lighting_evictions):
            raise ValueError('inconsistent world work/cache ledger')
        tally=data['lighting_consumption']
        expected_fields={'method','units','scope','start_seconds','end_seconds','covered_seconds',
            'illuminated_seconds','occulted_seconds','unresolved_seconds','selected_commits','qualification'}
        if type(tally) is not dict or set(tally)!=expected_fields:
            raise ValueError('exact selected lighting tally snapshot required')
        start,end=_qread(tally['start_seconds']),_qread(tally['end_seconds'])
        values={flag:_qread(tally[name]) for flag,name in zip(LIGHT_FLAGS,
            ('illuminated_seconds','occulted_seconds','unresolved_seconds'))}
        covered=_qread(tally['covered_seconds'])
        commits=_integer(tally['selected_commits'],'selected lighting commits')
        if (start!=environment.start_seconds or not start<=end<=environment.end_seconds or
                covered!=end-start or any(v<0 for v in values.values()) or
                sum(values.values(),Q(0))!=covered or (covered==0)!=(commits==0)):
            raise ValueError('lighting tally must partition the exact consumed prefix')
        owner._consumed_through=end;owner._light_durations=values;owner._light_commits=commits
        if owner.lighting_accounting()!=tally:
            raise ValueError('lighting tally snapshot units/method/scope mismatch')
        owner.retention_floor, owner._lighting = floor, lighting
        return owner

    def fork(self, provider, *, charge=None):
        self.guard()
        data = self.to_data()
        data['role'], data['provider_identity'] = provider.role, provider.identity
        data['identity'] = _identity((API, self.environment, provider.role))
        data['lighting_consumption'] = dict(data['lighting_consumption'],scope=(
            'SELECTED_ACTUAL_CONSUMED_SUPPORT' if provider.role == 'ACTUAL' else
            'INHERITED_ACTUAL_PREFIX_ONLY_NO_FORECAST_CONSUMPTION'))
        return self.from_data(self.environment, provider, data, charge=charge)

    def accounting(self):
        e = self.environment
        # Observational wire version only. Native world/snapshot/identity stay
        # on API above; legacy roots can honestly expose an empty tracked prefix.
        return {'api': ACCOUNTING_API, 'identity': self.identity, 'role': self.role, 'mode': NOMINAL,
                'controls': self.controls, 'lookups': self.lookups, 'guards': self.guards,
                'sun_queries': self.sun_queries, 'lighting_evaluations': self.lighting_evaluations,
                'lighting_evictions': self.lighting_evictions, 'retained_lighting': len(self._lighting),
                'peak_lighting_records': self.peak_lighting_records,
                'original_anchor': _qdata(e.start_seconds),
                'lighting_grid_seconds': e.lighting_step_seconds,
                'lighting_consumption': self.lighting_accounting(),
                'lighting_tracking': LIGHT_TRACKING,
                'sun_authority': 'FULL_DOMAIN_SUPPLIED_TABLE' if e.sun_table is not None else SUN_METHOD,
                'qualification': 'NOMINAL_SAMPLED_NOT_CONTINUOUS_OR_PHYSICALLY_CALIBRATED'}
