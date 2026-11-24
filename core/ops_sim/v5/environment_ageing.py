"""B61 reduced, explicitly ASSUMED calendar/illumination ageing.

No UV dose, radiation fluence, AO, material calibration or continuous geometry.
Start-of-cut properties; midpoint admitted incidence/start-held pose exposure;
only selected physical cuts commit. Rational saturation avoids arbitrary clamps.
"""
from dataclasses import dataclass,fields,replace
from fractions import Fraction as Q
from math import isfinite,cos,radians
from hashlib import sha256
import json

LAW='B61_CALENDAR_ILLUMINATION_RATIONAL_SATURATION_V1'
ACCOUNTING_LAW='B62_B61_RATIONAL_SATURATION_LIFETIME_ACCOUNTING_V1'
MAX_NODES=16
MAX_LINKS=32
MAX_SECONDS=10**12

def finite(v,name,lo=0.,hi=1.e12):
    if type(v) not in (int,float) or not lo<=v<=hi or not isfinite(v):
        raise ValueError('B61_DOMAIN:'+name)
    return v

def natural(v,name,lo=0,hi=2**48):
    if type(v)is not int or not lo<=v<=hi:raise ValueError('B61_DOMAIN:'+name)

def identifier(v):
    if type(v)is not str or not 1<=len(v)<=128 or not v.isascii()or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-'for c in v):
        raise ValueError('B61 bounded declared ID')

def digest(v):
    from .long_mission_continuation import _scientific
    return sha256(json.dumps(_scientific(v),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

@dataclass(frozen=True,slots=True)
class EmissivityAgeing:
    node_id: str
    asymptote: float
    calendar_rate_per_second: float=0.
    exposure_rate_per_second: float=0.
    exposure_factor: float=1.
    def __post_init__(self):
        identifier(self.node_id);finite(self.asymptote,'epsilon asymptote',0.,1.)
        for n in ('calendar_rate_per_second','exposure_rate_per_second'):finite(getattr(self,n),n,0.,1.)
        finite(self.exposure_factor,'node exposure factor',0.,1.)

@dataclass(frozen=True,slots=True)
class ConductanceAgeing:
    link_id: str
    asymptote_w_per_k: float
    calendar_rate_per_second: float=0.
    exposure_rate_per_second: float=0.
    exposure_factor: float=1.
    def __post_init__(self):
        identifier(self.link_id);finite(self.asymptote_w_per_k,'G asymptote',1.e-12,1.e12)
        for n in ('calendar_rate_per_second','exposure_rate_per_second'):finite(getattr(self,n),n,0.,1.)
        finite(self.exposure_factor,'link exposure factor',0.,1.)

@dataclass(frozen=True,slots=True)
class EnvironmentAgeingPolicy:
    pv_floor_fraction: float=.5
    pv_calendar_rate_per_second: float=0.
    pv_exposure_rate_per_second: float=0.
    emissivity: tuple=()
    conductance: tuple=()
    initial_calendar_seconds: int=0
    initial_pv_exposure_seconds: float=0.
    initial_thermal_exposure_seconds: float=0.
    maximum_proposals: int=2**34
    assumption: str='ASSUMED_NOT_CALIBRATED'
    method: str=LAW
    def __post_init__(self):
        if type(self.method)is not str or self.method not in(LAW,ACCOUNTING_LAW):raise ValueError('B61 exact equation version')
        if type(self.assumption)is not str or self.assumption not in ('ASSUMED_NOT_CALIBRATED','SYNTHETIC_ACCELERATED_ASSUMED'):raise ValueError('B61 assumption provenance')
        finite(self.pv_floor_fraction,'positive PV floor',1.e-12,1.)
        for n in ('pv_calendar_rate_per_second','pv_exposure_rate_per_second'):finite(getattr(self,n),n,0.,1.)
        natural(self.initial_calendar_seconds,'initial assumed calendar',hi=MAX_SECONDS)
        for n in ('initial_pv_exposure_seconds','initial_thermal_exposure_seconds'):finite(getattr(self,n),n,0.,MAX_SECONDS)
        natural(self.maximum_proposals,'finite work cap',1,2**48 if self.method==ACCOUNTING_LAW else 2**36)
        for seq,owner,key,limit in ((self.emissivity,EmissivityAgeing,'node_id',MAX_NODES),(self.conductance,ConductanceAgeing,'link_id',MAX_LINKS)):
            if type(seq)is not tuple or len(seq)>limit or any(type(x)is not owner for x in seq):raise ValueError('B61 exact bounded graph domain')
            for x in seq:x.__post_init__()
            ids=tuple(getattr(x,key)for x in seq)
            if ids!=tuple(sorted(set(ids))):raise ValueError('B61 unique ordered property IDs')
    @property
    def identity(self):return digest(self)

@dataclass(frozen=True,slots=True)
class EnvironmentAgeingState:
    clock_seconds: Q
    calendar_seconds: Q
    pv_exposure_seconds: float
    thermal_exposure_seconds: float
    reference_solar_retention: float
    policy_identity: str
    baseline_network_identity: str
    selected_cuts: int=0
    def __post_init__(self):
        for n in ('clock_seconds','calendar_seconds'):
            v=getattr(self,n)
            if type(v)is not Q or not 0<=v<=MAX_SECONDS or v.numerator.bit_length()>128 or v.denominator.bit_length()>128:raise ValueError('B61 exact bounded clock')
        for n in ('pv_exposure_seconds','thermal_exposure_seconds'):finite(getattr(self,n),n,0.,MAX_SECONDS)
        finite(self.reference_solar_retention,'initial retention',1.e-12,1.)
        natural(self.selected_cuts,'selected cuts',hi=2**36)
        for n in ('policy_identity','baseline_network_identity'):
            v=getattr(self,n)
            if type(v)is not str or len(v)!=64 or any(c not in '0123456789abcdef'for c in v):raise ValueError('B61 state provenance')

@dataclass(slots=True)
class EnvironmentAgeingWork:
    proposed: int=0
    returned: int=0
    failed: int=0
    control_units: int=0
    effective_networks: int=0
    def validate(self,p):
        for f in fields(self):natural(getattr(self,f.name),f.name,hi=2**64 if p.method==ACCOUNTING_LAW else 2**56)
        if p.method==ACCOUNTING_LAW and self.control_units!=self.proposed*(256+64*(len(p.emissivity)+len(p.conductance))):raise ValueError('B62 exact nonrefundable environment control ledger')
        if self.proposed>p.maximum_proposals or self.returned+self.failed>self.proposed or self.effective_networks>self.proposed:raise ValueError('B61 work balance')
    def reserve(self,p):
        self.validate(p)
        if self.proposed>=p.maximum_proposals:raise ValueError('B61_AGEING_WORK_LIMIT')
        self.proposed+=1;self.control_units+=256+64*(len(p.emissivity)+len(p.conductance))

def admit_network(network,p):
    p.__post_init__()
    from .thermal_config import ThermalNetworkConfig
    if type(network)is not ThermalNetworkConfig or len(network.nodes)>MAX_NODES or len(network.links)>MAX_LINKS:raise ValueError('B61 bounded baseline thermal graph')
    network.__post_init__()
    if not {x.node_id for x in p.emissivity}<={n.node_id.value for n in network.nodes} or not {x.link_id for x in p.conductance}<={l.link_id.value for l in network.links}:raise ValueError('B61 foreign thermal property ID')
    return digest(network)

def initial_state(p,clock,network,solar):
    h=admit_network(network,p)
    return EnvironmentAgeingState(Q(clock),Q(p.initial_calendar_seconds),p.initial_pv_exposure_seconds,p.initial_thermal_exposure_seconds,solar,p.identity,h)

def guard(p,s,network,clock=None,*,prepared_runtime=None):
    if prepared_runtime is not None:
        from .lifecycle_job_prepared import PreparedRoleState
        if type(prepared_runtime)is not PreparedRoleState:raise TypeError("B69 exact live history role")
        prepared_runtime.guard_environment_history(p,s,network,clock)
        return
    if type(p)is not EnvironmentAgeingPolicy or type(s)is not EnvironmentAgeingState:raise TypeError('B61 exact policy/state')
    p.__post_init__();s.__post_init__()
    if s.policy_identity!=p.identity or s.baseline_network_identity!=admit_network(network,p) or clock is not None and s.clock_seconds!=Q(clock):raise ValueError('B61 stale/foreign state or baseline')

def saturate(initial,asymptote,calendar,exposure,kc,kx):
    # x/(1+x) formulation preserves exact initial for x=0 and avoids
    # subtractive cancellation in small changes. x <= 2e12, finite by domain.
    x=kc*float(calendar)+kx*exposure
    return initial+(asymptote-initial)*(x/(1.+x))

def retention(p,s):
    return saturate(s.reference_solar_retention,s.reference_solar_retention*p.pv_floor_fraction,
        s.calendar_seconds,s.pv_exposure_seconds,p.pv_calendar_rate_per_second,p.pv_exposure_rate_per_second)

def propose(p,s,network,left,right,sunlit,incidence_angle_deg,work,*,prepared_runtime=None):
    work.reserve(p)
    try:
        if prepared_runtime is None:guard(p,s,network,left)
        else:
            from .lifecycle_job_prepared import PreparedRoleState
            if type(prepared_runtime)is not PreparedRoleState:raise TypeError('B68 exact live prepared role')
            prepared_runtime.guard_environment_history(p,s,network,left)
        nxt=_propose_validated(p,s,left,right,sunlit,incidence_angle_deg)
        nxt.__post_init__();work.returned+=1
        return nxt
    except BaseException:work.failed+=1;raise

def _propose_validated(p,s,left,right,sunlit,incidence_angle_deg):
    """One unchanged transition law; callers validate static/history first."""
    if type(left)is not Q or type(right)is not Q or not 0<right-left<=120:raise ValueError('B61 bounded exact physical cut')
    if type(sunlit)is not bool:raise TypeError('B61 actual admitted lighting boolean')
    finite(incidence_angle_deg,'incidence degrees',0.,180.)
    dt=float(right-left);weight=max(0.,cos(radians(incidence_angle_deg)))if sunlit else 0.
    nxt=replace(s,clock_seconds=right,calendar_seconds=s.calendar_seconds+(right-left),
        pv_exposure_seconds=s.pv_exposure_seconds+dt*weight,
        thermal_exposure_seconds=s.thermal_exposure_seconds+(dt if sunlit else 0.),selected_cuts=s.selected_cuts+1)
    return nxt


def state_metrics(p,s,network):
    from .environment_thermal import effective_network
    e=effective_network(p,s,network)
    return (('environment_calendar_seconds',float(s.calendar_seconds)),('environment_pv_exposure_seconds',s.pv_exposure_seconds),
        ('environment_thermal_exposure_seconds',s.thermal_exposure_seconds),('environment_pv_retention',retention(p,s)),
        *(("environment_epsilon:"+n.node_id.value,n.emissivity.value)for n in e.network.nodes),
        *(("environment_conductance:"+l.link_id.value,l.conductance_w_per_k.value)for l in e.network.links))
