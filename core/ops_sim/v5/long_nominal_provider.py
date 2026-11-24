"""Opt-in binary64 nominal original-grid cache; never a proof/transport seed.

The accepted F2 RK4 primitive is unchanged. Full signed prefixes and exact-key
tails are separate. Reservations are wrapper scheduling units, not measured
Decimal leaf operations. A failed primitive's internal work remains UNKNOWN.
"""
from dataclasses import dataclass, asdict
from fractions import Fraction as Q
from hashlib import sha256
from math import isfinite, ulp
import json
from .orbit_j2 import (_authorities, _grid, _rk4_step, J2CartesianTrajectory,
                       J2RK4SolverConfig)
from .orbit_j2_gravity import _gravity
from .orbit_config import GeometryInstant, _instant
from .frames import CartesianPosition, CartesianVelocity, CartesianState

METHOD='B44_NOMINAL_ORIGINAL_GRID_PREFIX_V1'

def _digest(value):
    from .environment_mission_general_continuation import _scientific
    return sha256(json.dumps(_scientific(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

@dataclass(frozen=True,slots=True)
class LongNominalPolicy:
    method: str = METHOD
    step_seconds: float = 10.
    max_steps: int = 20000
    max_queries: int = 65536
    max_cache_records: int = 65536
    max_force_reservations: int = 262144
    max_control_units: int = 2**27
    max_duration_seconds: int = 86400
    def __post_init__(self):
        if type(self.method) is not str or self.method!=METHOD:raise ValueError('unknown nominal method')
        if type(self.step_seconds) is not float or not isfinite(self.step_seconds) or not 0<self.step_seconds<=120:raise ValueError('finite positive binary64 step required')
        for n,cap in (('max_steps',20000),('max_queries',65536),('max_cache_records',65536),('max_force_reservations',262144),('max_control_units',2**27),('max_duration_seconds',86400)):
            if type(getattr(self,n)) is not int or not 1<=getattr(self,n)<=cap:raise ValueError('nominal limit: '+n)

@dataclass(slots=True)
class NominalWork:
    queries: int = 0
    cache_reads: int = 0
    cache_records: int = 0
    full_steps: int = 0
    tail_steps: int = 0
    force_reserved: int = 0
    force_completed: int = 0
    control_reserved: int = 0
    unknown_primitive_events: int = 0

class LongNominalProvider:
    """Mutable derived process-local cache owned by one immutable identity."""
    def __init__(self,trajectory,policy=LongNominalPolicy(),*,charge=None):
        if type(trajectory) is not J2CartesianTrajectory or type(policy) is not LongNominalPolicy:raise TypeError('exact trajectory/policy required')
        policy.__post_init__()
        state,model=_authorities(trajectory.initial_state,trajectory.gravity_model)
        self.trajectory=trajectory;self.policy=policy;self.identity=_digest((METHOD,trajectory,policy));self._charge=charge
        self.anchor=state.position;self.model=model;self.work=NominalWork()
        self._prefix={1:[(state.position.components_m,state.velocity.components_m_per_s)],-1:[(state.position.components_m,state.velocity.components_m_per_s)]}
        self._tails={};self.failed=False
        self._reserve(1,1,128)
        try:_gravity(model,state.position)
        except BaseException:self._unknown();raise
        self.work.force_completed+=1;self.work.cache_records=1
    def _unknown(self):
        self.work.unknown_primitive_events+=1;self.failed=True
        if self._charge is not None:self._charge('nominal_unknown_events',1)
    def _reserve(self,forces,records,controls):
        w=self.work;p=self.policy
        if w.force_reserved+forces>p.max_force_reservations or w.cache_records+records>p.max_cache_records or w.control_reserved+controls>p.max_control_units:raise ValueError('NOMINAL_CACHE_QUOTA_BEFORE_WORK')
        if self._charge is not None:
            self._charge('nominal_force_reserved',forces);self._charge('nominal_control_units',controls)
        w.force_reserved+=forces;w.control_reserved+=controls
    def validate(self,trajectory=None,policy=None):
        if self.failed:raise ValueError('NOMINAL_PROVIDER_FAILED_NO_CONTINUATION')
        if _digest((METHOD,self.trajectory,self.policy))!=self.identity or trajectory is not None and _digest((METHOD,trajectory,policy or self.policy))!=self.identity:raise ValueError('foreign/mutated nominal authority')
    def query(self,instant,*,trajectory=None):
        self.validate(trajectory);requested=_instant(instant);w=self.work;p=self.policy
        if w.queries>=p.max_queries:raise ValueError('nominal query quota')
        full,delta,tail=_grid(self.anchor.instant,requested,J2RK4SolverConfig(p.step_seconds,p.max_steps))
        if abs(Q(requested.elapsed_seconds)-Q(self.anchor.instant.elapsed_seconds))>p.max_duration_seconds:raise ValueError('nominal duration cap')
        if self._charge is not None:self._charge('nominal_orbit_queries',1)
        self._reserve(0,0,128);w.queries+=1
        sign=-1 if delta<0 else 1;prefix=self._prefix[sign]
        # Prospective complete growth admission before any new RK4 call.
        growth=max(0,full+1-len(prefix));key=Q(requested.elapsed_seconds)
        records=growth+int(bool(tail) and key not in self._tails)
        forces=4*records
        if w.force_reserved+forces>p.max_force_reservations or w.cache_records+records>p.max_cache_records or w.control_reserved+256*records>p.max_control_units:raise ValueError('NOMINAL_CACHE_QUOTA_BEFORE_WORK')
        while len(prefix)<=full:
            self._reserve(4,1,256)
            try:value=_rk4_step(self.model,self.anchor,*prefix[-1],delta)
            except BaseException:self._unknown();raise
            prefix.append(value);w.full_steps+=1;w.force_completed+=4;w.cache_records+=1
        r,v=prefix[full];w.cache_reads+=1
        if tail:
            if key in self._tails:r,v=self._tails[key];w.cache_reads+=1
            else:
                self._reserve(4,1,256)
                try:r,v=_rk4_step(self.model,self.anchor,r,v,tail)
                except BaseException:self._unknown();raise
                self._tails[key]=(r,v);w.tail_steps+=1;w.force_completed+=4;w.cache_records+=1
        return CartesianState(CartesianPosition(self.anchor.frame,requested,r),CartesianVelocity(self.anchor.frame,requested,v))
    def at_seconds(self,seconds):
        if type(seconds) is not Q or max(abs(seconds.numerator).bit_length(),seconds.denominator.bit_length())>256:raise ValueError('bounded exact relative seconds required')
        t=GeometryInstant(self.anchor.instant.epoch,float(seconds))
        if abs(Q(t.elapsed_seconds)-seconds)>Q(ulp(t.elapsed_seconds))/2:raise ValueError('undeclared nominal time rounding')
        return self.query(t)
    def accounting(self):return dict(method=METHOD,identity=self.identity,**asdict(self.work))
