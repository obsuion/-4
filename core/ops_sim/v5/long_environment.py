"""Versioned long world and indexed original-anchor forcing authority.

NOMINAL_LONG lighting is held on an explicit original-anchor sample grid.
CONTINUOUS_ACQUIRED_LONG uses complete B38 CLOSED supports without narrowing
tubes. Neither mode encloses the EPS/thermal integration.
"""
from dataclasses import dataclass, replace
from fractions import Fraction as Q
from bisect import bisect_right, bisect_left
from math import ceil
from .environment_forcing import (ForcingProfileEntry, EnvironmentForcingRequest,
    ForcingPolicy, EnvironmentForcingCell, _source, _case)
from .long_nominal_provider import LongNominalProvider, LongNominalPolicy, _digest
from .orbit_j2 import J2CartesianTrajectory, _authorities
from .sun_table import SunPositionTable, evaluate_sun_position, _table
from .orbit_sun import SuppliedSunDirection, nominal_parallel_ray
from .frames import CartesianDirection
from . import orbit_sun_zonotope_local_v2 as light

NOMINAL='NOMINAL_LONG'
CONTINUOUS='CONTINUOUS_ACQUIRED_LONG'
API='B44_LONG_ENVIRONMENT_V1'

@dataclass(frozen=True,slots=True)
class LongEnvironment:
    trajectory: J2CartesianTrajectory
    table: SunPositionTable
    start_seconds: Q
    end_seconds: Q
    node_ids: tuple
    profile: tuple
    mode: str
    source_request: object = None
    lighting_step_seconds: int = 30
    max_source_records: int = 16384
    max_index_control_units: int = 2**27
    def __post_init__(self):
        if type(self.trajectory) is not J2CartesianTrajectory:raise TypeError('original trajectory required')
        state,_=_authorities(self.trajectory.initial_state,self.trajectory.gravity_model)
        table=_table(self.table)
        if table.frame!=state.position.frame or table.epoch!=state.position.instant.epoch:raise ValueError('foreign full Sun frame/epoch')
        if type(self.mode) is not str or self.mode not in (NOMINAL,CONTINUOUS):raise ValueError('explicit long mode required')
        if any(type(t) is not Q or max(abs(t.numerator).bit_length(),t.denominator.bit_length())>256 for t in (self.start_seconds,self.end_seconds)):raise ValueError('bounded exact time required')
        if self.start_seconds!=Q(state.position.instant.elapsed_seconds) or not 0<self.end_seconds-self.start_seconds<=86400 or self.end_seconds.denominator!=1:raise ValueError('original integral endpoint/horizon required')
        if not Q(table.samples[0].elapsed_seconds)<=self.start_seconds<self.end_seconds<=Q(table.samples[-1].elapsed_seconds):raise ValueError('Sun table domain incomplete')
        if type(self.node_ids) is not tuple or not 1<=len(self.node_ids)<=64 or len(set(self.node_ids))!=len(self.node_ids):raise ValueError('bounded unique thermal nodes required')
        if type(self.profile) is not tuple or not 1<=len(self.profile)<=128:raise ValueError('bounded profile required')
        last=self.start_seconds
        for e in self.profile:
            if type(e) is not ForcingProfileEntry:raise TypeError('profile entry required')
            e.__post_init__()
            if e.start_seconds!=last or {n.node_id for n in e.nodes}!=set(self.node_ids):raise ValueError('profile gap/foreign nodes')
            last=e.end_seconds
        if last!=self.end_seconds:raise ValueError('incomplete long forcing profile')
        for n,cap in (('lighting_step_seconds',120),('max_source_records',16384),('max_index_control_units',2**27)):
            v=getattr(self,n)
            if type(v) is not int or not 1<=v<=cap:raise ValueError('long environment limit: '+n)
        if self.mode==NOMINAL:
            if self.source_request is not None:raise ValueError('nominal world cannot claim acquired proof request')
        else:
            q=light._request(self.source_request) # Original producer static admission, unchanged caps.
            if q.segment.trajectory!=self.trajectory or q.table!=self.table or Q(q.segment.end.elapsed_seconds)!=self.end_seconds:raise ValueError('foreign continuous original authority/domain')
            steps=ceil((self.end_seconds-self.start_seconds)/Q(q.segment.policy.base_policy.step_seconds))
            if steps>min(q.policy.max_initial_steps,q.segment.policy.base_policy.max_steps):raise ValueError('CONTINUOUS_INITIAL_STEP_ADMISSION_BEFORE_EVALUATION')
    def forcing_request(self):
        if self.mode!=CONTINUOUS:raise ValueError('nominal has no continuous forcing request')
        return EnvironmentForcingRequest(self.source_request,self.start_seconds,self.end_seconds,self.node_ids,self.profile,
            ForcingPolicy(max_source_records=self.max_source_records))

@dataclass(frozen=True,slots=True)
class LongSchedule:
    cells: tuple

class AcquiredLongEnvironment:
    """One acquisition validation/index; whole source scans only at action guards.

    Control units charge index construction, complete mutation guards and local
    lookups. Supports retain producer IDs/whole tubes. No serialized index trust.
    """
    def __init__(self,environment,provider,source=None,*,charge=None):
        if type(environment) is not LongEnvironment or type(provider) is not LongNominalProvider:raise TypeError('long owners required')
        environment.__post_init__();provider.validate(environment.trajectory)
        self.environment=environment;self.provider=provider;self.source=source;self._charge=charge
        self.identity=_digest((API,environment));self.controls=0;self.lookups=0;self.guards=0
        self.supports=();self.ancestry=();self.signature=None;self.authority_digest=None;self.source_digest=None
        self._lighting={}
        if environment.mode==CONTINUOUS:
            records=sum(len(getattr(source,n,())) for n in ('pieces','windows','boundaries','steps','geometry_records','trials'))
            self.pay(512+128*records)
            self.source_digest,self.authority_digest,anchor,last,self.ancestry,self.supports=_source(source,environment.forcing_request())
            if (anchor,last)!=(environment.start_seconds,environment.end_seconds):raise ValueError('foreign full source domain')
            from .mission_continuous_geometry import _source_signature
            self.signature=_source_signature(source)
            self._starts=tuple(x.piece.start_seconds for x in self.supports)
            self._ends=tuple(x.piece.end_seconds for x in self.supports)
        elif source is not None:raise ValueError('nominal cannot accept a certificate')
        self._profiles=tuple(x.start_seconds for x in environment.profile)
        self._profile_cuts=tuple(x.end_seconds for x in environment.profile[:-1])
        self._table_cuts=tuple(Q(x.elapsed_seconds) for x in environment.table.samples[1:-1])
        self.steps={} if source is None else {s.id:s for s in source.steps}
    def pay(self,n):
        if type(n) is not int or n<0 or self.controls+n>self.environment.max_index_control_units:raise ValueError('LONG_INDEX_CONTROL_QUOTA')
        if self._charge is not None:self._charge('index_control_units',n)
        self.controls+=n
    def guard(self):
        self.pay(512);self.guards+=1;self.provider.validate(self.environment.trajectory)
        if _digest((API,self.environment))!=self.identity:raise ValueError('mutated long environment')
        if self.source is not None:
            from .mission_continuous_geometry import _source_signature
            self.pay(128*sum(len(getattr(self.source,n)) for n in ('pieces','windows','boundaries','steps','geometry_records','trials')))
            if _source_signature(self.source)!=self.signature:raise ValueError('mutated acquired source')
    def selected(self,a,b):
        self._domain(a,b)
        if self.source is None:raise ValueError('nominal has no whole tube')
        self.pay(64);self.lookups+=1
        first=max(0,bisect_left(self._ends,a));last=bisect_right(self._starts,b)
        # CLOSED endpoint selection retains both adjacent supports. Positive
        # duration cells later use interiors, with exact no-gap coverage checks.
        result=tuple((i,self.supports[i]) for i in range(first,last))
        self.pay(16*len(result));return result
    def _domain(self,a,b):
        if type(a) is not Q or type(b) is not Q or not self.environment.start_seconds<=a<=b<=self.environment.end_seconds:raise ValueError('exact in-domain long interval required')
    def _nominal_light(self,i):
        if i not in self._lighting:
            e=self.environment
            a=e.start_seconds+i*e.lighting_step_seconds;b=min(e.end_seconds,a+e.lighting_step_seconds)
            orbit=self.provider.at_seconds((a+b)/2);sun=evaluate_sun_position(e.table,orbit.position.instant)
            direction=CartesianDirection(orbit.position.frame,orbit.position.instant,tuple(x-y for x,y in zip(sun.components_m,orbit.position.components_m)))
            origin='SYNTHETIC' if e.table.provenance.source_kind=='SYNTHETIC' else 'EXTERNALLY_SUPPLIED'
            s=SuppliedSunDirection(direction,origin,e.table.provenance.source_ids,'Nominal parallel-ray lighting sample held on the declared original-anchor grid; no interval certificate.')
            status=nominal_parallel_ray(orbit.position,s)
            name=status.value if hasattr(status,'value') else str(status)
            if name not in ('ILLUMINATED','OCCULTED'):raise ValueError('NOMINAL_LIGHTING_UNSUPPORTED:'+name)
            self.pay(256);self._lighting[i]=name
        self.pay(16);return self._lighting[i]
    def schedule(self,a,b):
        self._domain(a,b);e=self.environment;self.pay(64);self.lookups+=1
        points={a,b}
        for cuts in (self._profile_cuts,self._table_cuts):
            l=bisect_right(cuts,a);r=bisect_left(cuts,b);points.update(cuts[l:r]);self.pay(16*(r-l+1))
        selected=()
        if e.mode==CONTINUOUS:
            selected=self.selected(a,b)
            points.update(t for _,s in selected for t in (s.piece.start_seconds,s.piece.end_seconds) if a<t<b)
        else:
            first=int((a-e.start_seconds)//e.lighting_step_seconds);last=int((b-e.start_seconds)//e.lighting_step_seconds)
            if last-first+1>8192:raise ValueError('nominal lighting partition cap')
            points.update(e.start_seconds+i*e.lighting_step_seconds for i in range(first+1,last+1) if a<e.start_seconds+i*e.lighting_step_seconds<b)
        ordered=sorted(points);pairs=list(zip(ordered,ordered[1:])) if a<b else [(a,b)]
        if len(pairs)>8192:raise ValueError('long forcing cell cap')
        self.pay(128*len(pairs));cells=[]
        for left,right in pairs:
            mid=(left+right)/2;pi=max(0,bisect_right(self._profiles,mid)-1)
            if e.mode==CONTINUOUS:
                idx=max(0,min(len(self.supports)-1,bisect_right(self._starts,mid)-1));assessment=self.supports[idx].piece.assessment
            else:
                idx=min(ceil((e.end_seconds-e.start_seconds)/e.lighting_step_seconds)-1,int((mid-e.start_seconds)//e.lighting_step_seconds));assessment=self._nominal_light(idx)
            alternatives=tuple(_case(e.profile[pi],flag) for flag in ((True,False) if assessment=='UNRESOLVED' else (assessment=='ILLUMINATED',)))
            cells.append(EnvironmentForcingCell(left,right,assessment,idx,pi,alternatives))
        return LongSchedule(tuple(cells))
    def accounting(self):return dict(api=API,identity=self.identity,mode=self.environment.mode,controls=self.controls,lookups=self.lookups,guards=self.guards,source_signature=self.signature,source_supports=len(self.supports),nominal_lighting_samples=len(self._lighting))
