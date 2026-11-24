"""B52 bounded chronological nominal orbit owner; no continuous certificate.

The original trajectory, TT epoch and fixed RK4 grid are immutable authority.
Only complete original-grid steps seed propagation. A remainder is an exact-key
derived result and is never a new origin. ``retain_from`` is the caller's explicit
earliest-needed knowledge/forecast watermark; requests before it refuse. Keeping
an old watermark that cannot fit the declared window refuses BEFORE integration.

The accepted F2 force and RK4 arithmetic are unchanged. Work fields count wrapper
reservations/completed primitive calls, not CPU operations. Failed work is never
refunded. Restore materializes trusted, externally pinned DATA and invokes no
force, integrator or historical reconstruction; it is not proof of reachability.
"""
from dataclasses import dataclass, fields, is_dataclass, asdict
from enum import Enum
from fractions import Fraction as Q
from hashlib import sha256
from math import isfinite, ulp
import json

from .orbit_j2 import J2CartesianTrajectory, _authorities, _rk4_step
from .orbit_j2_gravity import _gravity
from .orbit_config import GeometryInstant, _instant
from .frames import CartesianPosition, CartesianVelocity, CartesianState


METHOD = 'B52_NOMINAL_SLIDING_ORIGINAL_GRID_RK4_V1'
MAX_DURATION_SECONDS = 15 * 31557600
ROLES = ('ACTUAL', 'FORECAST')


def _identity(value):
    from .lifecycle_fast import authority_identity
    return authority_identity(value,lambda:_reference_identity(value))


def _reference_identity(value):
    """Small immutable authority graph only; never a growing execution history."""
    visits = 0
    def tree(v, depth=0):
        nonlocal visits
        visits += 1
        if visits > 2**18 or depth > 48:
            raise ValueError('LIFECYCLE_STATIC_AUTHORITY_BOUND')
        if isinstance(v, Enum):
            return {'enum': type(v).__module__+'.'+type(v).__qualname__, 'name': v.name}
        if type(v) is float:
            if not isfinite(v):
                raise ValueError('finite authority value required')
            return {'float_hex': v.hex()}
        if type(v) is Q:
            return {'q': [hex(v.numerator), hex(v.denominator)]}
        if is_dataclass(v):
            return {'record': type(v).__module__+'.'+type(v).__qualname__,
                    'fields': {f.name: tree(getattr(v, f.name), depth+1) for f in fields(v)}}
        if type(v) in (tuple, list):
            return {'tuple' if type(v) is tuple else 'list': [tree(x, depth+1) for x in v]}
        if type(v) is dict and all(type(k) is str for k in v):
            return {k: tree(x, depth+1) for k, x in v.items()}
        if v is None or type(v) in (str, int, bool):
            return v
        raise TypeError('unsupported static lifecycle authority')
    return sha256(json.dumps(tree(value), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _integer(v, name, low=0, high=2**48):
    if type(v) is not int or not low <= v <= high:
        raise ValueError('bounded exact integer required: '+name)
    return v


def _seconds(v):
    if type(v) is not Q or max(abs(v.numerator).bit_length(), v.denominator.bit_length()) > 256 or abs(v) > 2**40:
        raise ValueError('bounded exact relative seconds required')
    return v


def _qdata(v):
    return [hex(v.numerator), hex(v.denominator)]


def _qread(v):
    if type(v) is not list or len(v) != 2 or any(type(x) is not str or len(x) > 68 for x in v):
        raise ValueError('canonical rational data required')
    try:
        result = Q(int(v[0], 16), int(v[1], 16))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('canonical rational data required') from error
    if _qdata(result) != v:
        raise ValueError('noncanonical rational data')
    return _seconds(result)


def _triple(v):
    if type(v) is not tuple or len(v) != 3 or any(type(x) is not float or not isfinite(x) for x in v):
        raise ValueError('three finite binary64 components required')
    return v


def _triple_data(v):
    return [x.hex() for x in v]


def _triple_read(v):
    if type(v) is not list or len(v) != 3 or any(type(x) is not str or len(x) > 32 for x in v):
        raise ValueError('canonical binary64 triple required')
    try:
        result = tuple(float.fromhex(x) for x in v)
    except ValueError as error:
        raise ValueError('canonical binary64 triple required') from error
    _triple(result)
    if _triple_data(result) != v:
        raise ValueError('noncanonical binary64 component')
    return result


@dataclass(frozen=True, slots=True)
class LifecycleOrbitPolicy:
    step_seconds: float = 10.0
    max_duration_seconds: int = MAX_DURATION_SECONDS
    max_retained_grid: int = 256
    max_tail_records: int = 128
    max_steps_per_query: int = 65536
    max_queries: int = 2**32
    max_force_reservations: int = 2**32
    max_control_units: int = 2**44
    method: str = METHOD

    def __post_init__(self):
        if type(self.method) is not str or self.method != METHOD:
            raise ValueError('unknown lifecycle orbit method')
        if type(self.step_seconds) is not float or not isfinite(self.step_seconds) or not 0 < self.step_seconds <= 120:
            raise ValueError('positive finite binary64 grid step required')
        for name, lo, cap in (
            ('max_duration_seconds', 1, MAX_DURATION_SECONDS), ('max_retained_grid', 2, 65536),
            ('max_tail_records', 0, 65536), ('max_steps_per_query', 1, 2**20),
            ('max_queries', 1, 2**40), ('max_force_reservations', 1, 2**40),
            ('max_control_units', 1, 2**48)):
            _integer(getattr(self, name), name, lo, cap)


@dataclass(slots=True)
class LifecycleOrbitWork:
    queries: int = 0
    cache_reads: int = 0
    full_steps: int = 0
    tail_steps: int = 0
    force_reserved: int = 0
    force_completed: int = 0
    control_reserved: int = 0
    unknown_primitive_events: int = 0
    cache_records: int = 0
    peak_cache_records: int = 0
    grid_evictions: int = 0
    tail_evictions: int = 0


class LifecycleOrbitProvider:
    """One scope's bounded original-grid cache and nonrefundable work ledger."""
    def __init__(self, trajectory, policy=LifecycleOrbitPolicy(), *, role='ACTUAL', charge=None):
        self._configure(trajectory, policy, role, charge)
        self.work = LifecycleOrbitWork()
        self.failed = False
        self.failure = None
        self._grid_states = {0: (self.anchor.components_m, self._initial_velocity)}
        self._low = self._high = 0
        self._tails = {}
        self.retention_floor = Q(self.anchor.instant.elapsed_seconds)
        self._reserve(1, 128)
        try:
            _gravity(self.model, self.anchor)
        except BaseException as error:
            self._unknown(error)
            raise
        self.work.force_completed += 1
        self._sync_records()

    def _configure(self, trajectory, policy, role, charge):
        if type(trajectory) is not J2CartesianTrajectory or type(policy) is not LifecycleOrbitPolicy:
            raise TypeError('exact lifecycle trajectory/policy required')
        policy.__post_init__()
        if type(role) is not str or role not in ROLES:
            raise ValueError('explicit ACTUAL/FORECAST ownership required')
        state, model = _authorities(trajectory.initial_state, trajectory.gravity_model)
        self.trajectory, self.policy, self.role = trajectory, policy, role
        self.anchor, self.model, self._charge = state.position, model, charge
        self._initial_velocity = state.velocity.components_m_per_s
        self.authority_identity = _identity((METHOD, trajectory, policy))
        self.identity = _identity((self.authority_identity, role))

    def _reserve(self, forces, controls):
        w, p = self.work, self.policy
        if w.force_reserved+forces > p.max_force_reservations or w.control_reserved+controls > p.max_control_units:
            raise ValueError('LIFECYCLE_ORBIT_QUOTA_BEFORE_WORK')
        # Each successfully published charge is immediately retained, including
        # a later callback refusal on the other channel.
        if forces:
            if self._charge is not None:
                self._charge('nominal_force_reserved', forces)
            w.force_reserved += forces
        if controls:
            if self._charge is not None:
                self._charge('nominal_control_units', controls)
            w.control_reserved += controls

    def _unknown(self, error):
        self.failed = True
        self.work.unknown_primitive_events += 1
        self.failure = (type(error).__name__+': '+str(error))[:512]
        if self._charge is not None:
            try:
                self._charge('nominal_unknown_events', 1)
            except BaseException:
                # Do not replace the original primitive exception. Local paid
                # evidence remains available even if publication also failed.
                self.failure += '; UNKNOWN_EVENT_PUBLICATION_FAILED'

    def _sync_records(self):
        self.work.cache_records = len(self._grid_states)+len(self._tails)
        self.work.peak_cache_records = max(self.work.peak_cache_records, self.work.cache_records)

    def validate(self, trajectory=None, policy=None):
        if self.failed:
            raise ValueError('LIFECYCLE_ORBIT_FAILED_NO_CONTINUATION')
        if _identity((METHOD, self.trajectory, self.policy)) != self.authority_identity:
            raise ValueError('foreign/mutated lifecycle orbit authority')
        if trajectory is not None and _identity((METHOD, trajectory, policy or self.policy)) != self.authority_identity:
            raise ValueError('foreign lifecycle trajectory/policy')

    def _floor_index(self):
        return int((self.retention_floor-Q(self.anchor.instant.elapsed_seconds))//Q(self.policy.step_seconds))

    def _evict_grid(self):
        low = min(self._high, max(self._low, self._floor_index()))
        while self._low < low:
            del self._grid_states[self._low]
            self._low += 1
            self.work.grid_evictions += 1

    def retain_from(self, seconds):
        """Advance the explicit earliest-needed watermark; never re-create a seed."""
        self.validate()
        seconds = _seconds(seconds)
        origin = Q(self.anchor.instant.elapsed_seconds)
        if not self.retention_floor <= seconds <= origin+self.policy.max_duration_seconds:
            raise ValueError('LIFECYCLE_ORBIT_RETENTION_WATERMARK')
        self._reserve(0, 64)
        self.retention_floor = seconds
        self._evict_grid()
        for key in tuple(self._tails):
            if key < seconds:
                del self._tails[key]
                self.work.tail_evictions += 1
        self._sync_records()

    def query(self, instant, *, trajectory=None):
        self.validate(trajectory)
        requested = _instant(instant)
        if requested.epoch != self.anchor.instant.epoch:
            raise ValueError('original TT epoch required')
        key, origin = Q(requested.elapsed_seconds), Q(self.anchor.instant.elapsed_seconds)
        if not origin <= key <= origin+self.policy.max_duration_seconds:
            raise ValueError('LIFECYCLE_ORBIT_DOMAIN')
        if key < self.retention_floor:
            raise ValueError('LIFECYCLE_ORBIT_SEED_EVICTED')
        full, remainder = divmod(key-origin, Q(self.policy.step_seconds))
        full = int(full)
        tail = float(remainder)
        if Q(tail) != remainder:
            raise ValueError('exact binary64 original-grid remainder required')
        if full < self._low:
            raise ValueError('LIFECYCLE_ORBIT_SEED_EVICTED')
        growth = max(0, full-self._high)
        tail_growth = int(bool(tail) and key not in self._tails)
        p, w = self.policy, self.work
        if w.queries >= p.max_queries or growth+tail_growth > p.max_steps_per_query:
            raise ValueError('LIFECYCLE_ORBIT_QUERY_QUOTA_BEFORE_WORK')
        final_low = min(full, max(self._low, self._floor_index())) if growth else self._low
        if max(self._high, full)-final_low+1 > p.max_retained_grid:
            raise ValueError('LIFECYCLE_ORBIT_RETAINED_SEED_CAPACITY_BEFORE_WORK')
        required = growth+tail_growth
        if w.force_reserved+4*required > p.max_force_reservations or w.control_reserved+128+256*required > p.max_control_units:
            raise ValueError('LIFECYCLE_ORBIT_QUOTA_BEFORE_WORK')
        if self._charge is not None:
            self._charge('nominal_orbit_queries', 1)
        w.queries += 1
        self._reserve(0, 128)
        while self._high < full:
            self._reserve(4, 256)
            try:
                value = _rk4_step(self.model, self.anchor, *self._grid_states[self._high], p.step_seconds)
            except BaseException as error:
                self._unknown(error)
                raise
            self._high += 1
            self._grid_states[self._high] = value
            w.full_steps += 1
            w.force_completed += 4
            self._evict_grid()
            self._sync_records()
        r, v = self._grid_states[full]
        w.cache_reads += 1
        if tail:
            if key in self._tails:
                r, v = self._tails[key]
                w.cache_reads += 1
            else:
                self._reserve(4, 256)
                try:
                    r, v = _rk4_step(self.model, self.anchor, r, v, tail)
                except BaseException as error:
                    self._unknown(error)
                    raise
                w.tail_steps += 1
                w.force_completed += 4
                if p.max_tail_records:
                    if len(self._tails) >= p.max_tail_records:
                        oldest = min(self._tails)
                        if key > oldest:
                            del self._tails[oldest]
                            w.tail_evictions += 1
                        else:
                            oldest = None
                    else:
                        oldest = key
                    if oldest is not None:
                        self._tails[key] = (r, v)
                self._sync_records()
        return CartesianState(CartesianPosition(self.anchor.frame, requested, r),
                              CartesianVelocity(self.anchor.frame, requested, v))

    def at_seconds(self, seconds):
        seconds = _seconds(seconds)
        instant = GeometryInstant(self.anchor.instant.epoch, float(seconds))
        if abs(Q(instant.elapsed_seconds)-seconds) > Q(ulp(instant.elapsed_seconds))/2:
            raise ValueError('undeclared lifecycle nominal time rounding')
        return self.query(instant)

    def to_data(self):
        """Bounded data only; publication accounting belongs to the outer owner."""
        return {'format': METHOD, 'identity': self.identity, 'authority_identity': self.authority_identity,
                'role': self.role, 'retention_floor': _qdata(self.retention_floor),
                'low': self._low, 'high': self._high,
                'grid': [{'index': i, 'r': _triple_data(r), 'v': _triple_data(v)}
                         for i, (r, v) in sorted(self._grid_states.items())],
                'tails': [{'time': _qdata(t), 'r': _triple_data(r), 'v': _triple_data(v)}
                          for t, (r, v) in sorted(self._tails.items())],
                'work': asdict(self.work), 'failed': self.failed, 'failure': self.failure}

    @classmethod
    def from_data(cls, trajectory, policy, data, *, charge=None):
        """Known explicit materializer: no _gravity, _rk4_step or prefix replay."""
        keys = {'format', 'identity', 'authority_identity', 'role', 'retention_floor',
                'low', 'high', 'grid', 'tails', 'work', 'failed', 'failure'}
        if type(data) is not dict or set(data) != keys or data['format'] != METHOD:
            raise ValueError('exact lifecycle orbit snapshot fields required')
        owner = cls.__new__(cls)
        owner._configure(trajectory, policy, data['role'], charge)
        if data['identity'] != owner.identity or data['authority_identity'] != owner.authority_identity:
            raise ValueError('foreign lifecycle orbit snapshot identity')
        low = _integer(data['low'], 'low grid', 0, 2**40)
        high = _integer(data['high'], 'high grid', low, 2**40)
        if type(data['grid']) is not list or len(data['grid']) != high-low+1 or len(data['grid']) > policy.max_retained_grid:
            raise ValueError('bounded contiguous retained grid required')
        grid = {}
        for index, row in zip(range(low, high+1), data['grid']):
            if type(row) is not dict or set(row) != {'index', 'r', 'v'} or type(row['index']) is not int or row['index'] != index:
                raise ValueError('contiguous original grid indices required')
            grid[index] = (_triple_read(row['r']), _triple_read(row['v']))
        origin = Q(owner.anchor.instant.elapsed_seconds)
        floor = _qread(data['retention_floor'])
        if not origin <= floor <= origin+policy.max_duration_seconds or high*Q(policy.step_seconds) > policy.max_duration_seconds:
            raise ValueError('snapshot grid/floor outside original domain')
        if low != min(high, int((floor-origin)//Q(policy.step_seconds))):
            raise ValueError('noncanonical retained grid watermark')
        if low == 0 and (_triple_data(grid[0][0]), _triple_data(grid[0][1])) != (
                _triple_data(owner.anchor.components_m), _triple_data(owner._initial_velocity)):
            raise ValueError('foreign original grid anchor')
        tails = {}
        if type(data['tails']) is not list or len(data['tails']) > policy.max_tail_records:
            raise ValueError('bounded exact-key tails required')
        last = None
        for row in data['tails']:
            if type(row) is not dict or set(row) != {'time', 'r', 'v'}:
                raise ValueError('exact tail fields required')
            t = _qread(row['time'])
            if (last is not None and t <= last) or not floor <= t <= origin+policy.max_duration_seconds:
                raise ValueError('ordered in-domain tail keys required')
            whole, remainder = divmod(t-origin, Q(policy.step_seconds))
            if not remainder or whole > high or Q(float(t)) != t:
                raise ValueError('tail must be a represented original-grid remainder')
            tails[t] = (_triple_read(row['r']), _triple_read(row['v']))
            last = t
        if type(data['work']) is not dict or set(data['work']) != set(LifecycleOrbitWork.__dataclass_fields__):
            raise ValueError('exact lifecycle orbit work fields required')
        for name, value in data['work'].items():
            _integer(value, name)
        work = LifecycleOrbitWork(**data['work'])
        if (work.queries > policy.max_queries or work.force_reserved > policy.max_force_reservations or
            work.control_reserved > policy.max_control_units or work.full_steps != high or
            work.force_completed != 1+4*(work.full_steps+work.tail_steps) or
            work.force_completed > work.force_reserved or
            work.cache_records != len(grid)+len(tails) or work.peak_cache_records < work.cache_records or
            work.peak_cache_records > policy.max_retained_grid+policy.max_tail_records or
            work.grid_evictions != low or work.tail_steps < len(tails)+work.tail_evictions or
            type(data['failed']) is not bool or work.unknown_primitive_events != int(data['failed'])):
            raise ValueError('inconsistent nonrefundable orbit work/cache ledger')
        if data['failed']:
            if type(data['failure']) is not str or not 1 <= len(data['failure']) <= 560:
                raise ValueError('failed primitive evidence required')
        elif data['failure'] is not None:
            raise ValueError('unexplained orbit failure evidence')
        owner.work, owner.failed, owner.failure = work, data['failed'], data['failure']
        owner._low, owner._high, owner._grid_states, owner._tails = low, high, grid, tails
        owner.retention_floor = floor
        return owner

    def fork(self, role='FORECAST', *, charge=None):
        """Independent owned cache, preserving the inherited paid-work baseline."""
        self.validate()
        result = self.from_data(self.trajectory, self.policy, self.to_data(), charge=charge)
        if type(role) is not str or role not in ROLES:
            raise ValueError('explicit cache ownership required')
        result.role = role
        result.identity = _identity((result.authority_identity, role))
        return result

    def accounting(self):
        return {'method': METHOD, 'identity': self.identity, 'role': self.role,
                'original_grid_step_seconds': self.policy.step_seconds,
                'retention_floor': _qdata(self.retention_floor),
                'low_grid_index': self._low, 'high_grid_index': self._high,
                'retained_grid': len(self._grid_states), 'retained_tails': len(self._tails),
                'failed': self.failed, **asdict(self.work)}
