"""B56 explicit reduced Sun target, panel-axis rest-to-rest plan and policy.

All policy coefficients are ASSUMED. The constructive rational M3/B46 bounds
are reused for a caller-declared BODY axis; hardware/camera are never replaced.
Quaternion samples remain the accepted nominal libm interpolation, not a wheel
plant, free tumble model, closed-loop tracker or physical accuracy certificate.
"""
from dataclasses import dataclass,asdict
from fractions import Fraction as Q
from hashlib import sha256
from math import isfinite,hypot,atan2,pi,ceil
import json
from .assembly_slew_3d import cross,dot,matvec,sqrt_bounds,bounded_direction,STEERING_ZERO_RAD
from .assembly_attitude_3d import BodyAttitude3D
from .harness_slew import EffectiveSpatialSlew
from .harness_hardware import EffectiveAssemblyHardware,validate_effective_hardware

METHOD='B56_ONBOARD_PREVENTIVE_SOLAR_ATTITUDE_V1'
SENSOR='ASSUMED_EXACT_DECLARED_MODEL_SUN_AND_RESTED_POSE_NOT_FLIGHT_SENSOR'

def _integer(v,name,lo=0,hi=2**48):
    if type(v) is not int or not lo<=v<=hi:raise ValueError('exact bounded solar integer: '+name)
    return v
def _identity(v):
    if type(v) is not str or len(v)!=64 or set(v)-set('0123456789abcdef'):raise ValueError('solar identity')
def _seconds(v):
    if type(v) is not Q or v<0 or max(abs(v.numerator).bit_length(),v.denominator.bit_length())>256:raise ValueError('bounded exact solar seconds')
def _digest(v):return sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

@dataclass(frozen=True,slots=True)
class EnergyAttitudePolicy:
    entry_usable_fraction: float = .50
    exit_usable_fraction: float = .75
    minimum_dwell_seconds: int = 600
    minimum_hold_reserve_seconds: int = 60
    repoint_interval_seconds: int = 1800
    repoint_angle_deg: float = 10.
    controller_scope: str = 'ONBOARD_AUTONOMY_NO_EARLY_GROUND_ACK'
    target_assumption: str = SENSOR
    placement_domain: str = 'ONE_MOUNT_DERIVED_EFFECTIVE_PANEL_NORMAL'
    preemption: str = 'FINISH_EXISTING_PAID_ACTION_NO_CUSTODY_ERASURE'
    method: str = METHOD
    def __post_init__(self):
        for name in ('entry_usable_fraction','exit_usable_fraction','repoint_angle_deg'):
            v=getattr(self,name)
            if type(v) is not float or not isfinite(v):raise ValueError('exact finite solar policy float')
        if not 0<self.entry_usable_fraction<self.exit_usable_fraction<1 or not 0<self.repoint_angle_deg<=90:raise ValueError('solar hysteresis/angle domain')
        _integer(self.minimum_dwell_seconds,'dwell',1,3600)
        _integer(self.minimum_hold_reserve_seconds,'hold reserve',1,self.minimum_dwell_seconds)
        _integer(self.repoint_interval_seconds,'repoint interval',self.minimum_dwell_seconds,86400)
        expected=dict(controller_scope='ONBOARD_AUTONOMY_NO_EARLY_GROUND_ACK',target_assumption=SENSOR,
            placement_domain='ONE_MOUNT_DERIVED_EFFECTIVE_PANEL_NORMAL',preemption='FINISH_EXISTING_PAID_ACTION_NO_CUSTODY_ERASURE',method=METHOD)
        if any(type(getattr(self,n)) is not str or getattr(self,n)!=v for n,v in expected.items()):raise ValueError('explicit solar assumptions/method')
    @property
    def identity(self):self.__post_init__();return _digest(asdict(self))

def requested_energy_policy(selection):
    if type(selection) is not str:raise TypeError('explicit solar policy selection')
    if selection=='LEGACY':return None
    if selection==METHOD:return EnergyAttitudePolicy()
    raise ValueError('unknown energy-attitude policy selector')

@dataclass(frozen=True,slots=True)
class SolarTarget:
    world_identity: str
    role: str
    clock_seconds: Q
    frame: object
    epoch_identity: str
    direction_inertial: tuple
    assumption: str = SENSOR
    def __post_init__(self):
        from .frames import FrameDefinition,FrameKind,_frame
        _identity(self.world_identity);_identity(self.epoch_identity);_seconds(self.clock_seconds)
        if type(self.role) is not str or self.role not in ('ACTUAL','FORECAST'):raise ValueError('solar target role')
        if type(self.frame) is not FrameDefinition:raise TypeError('exact solar inertial frame')
        _frame(self.frame)
        if self.frame.kind is not FrameKind.MODEL_INERTIAL:raise ValueError('solar target inertial kind')
        v=bounded_direction(self.direction_inertial)
        if max(abs(a-b) for a,b in zip(v,self.direction_inertial))>2**-40:raise ValueError('unit solar direction')
        if type(self.assumption) is not str or self.assumption!=SENSOR:raise ValueError('solar sensor assumption')

@dataclass(frozen=True,slots=True)
class SolarAction:
    action_id: str
    kind: str
    policy_identity: str
    until_seconds: int | None = None
    authority: str = 'ONBOARD_AUTONOMOUS_PREVENTIVE_CHARGE'
    def __post_init__(self):
        if type(self.action_id) is not str or not self.action_id or len(self.action_id)>256:raise ValueError('solar command identity')
        _identity(self.policy_identity)
        if type(self.kind) is not str or self.kind not in ('SOLAR_POINT','SOLAR_HOLD'):raise ValueError('typed solar action purpose')
        if self.kind=='SOLAR_POINT':
            if self.until_seconds is not None:raise ValueError('Sun point duration belongs to paid planner')
        else:_integer(self.until_seconds,'solar hold end',1)
        if type(self.authority) is not str or self.authority!='ONBOARD_AUTONOMOUS_PREVENTIVE_CHARGE':raise ValueError('solar command lineage')

@dataclass(frozen=True,slots=True)
class SolarAttitudeState:
    policy_identity: str
    clock_seconds: Q
    phase: str = 'MISSION'
    ordinal: int = 0
    entered_at_seconds: Q = Q(0)
    minimum_until_seconds: Q = Q(0)
    next_point_check_seconds: Q = Q(0)
    held_target: SolarTarget | None = None
    last_action_id: str = ''
    reason: str = 'INITIAL_MISSION'
    point_attempts: int = 0
    point_completions: int = 0
    point_refusals: int = 0
    paid_point_seconds: Q = Q(0)
    actuator_requested_wh: Q = Q(0)
    charge_hold_seconds: Q = Q(0)
    positive_charge_hold_seconds: Q = Q(0)
    last_incidence_deg: float | None = None
    last_illumination: str | None = None
    last_support: tuple = ()
    def __post_init__(self):
        _identity(self.policy_identity)
        for n in ('clock_seconds','entered_at_seconds','minimum_until_seconds','next_point_check_seconds','paid_point_seconds','actuator_requested_wh','charge_hold_seconds','positive_charge_hold_seconds'):_seconds(getattr(self,n))
        if type(self.phase) is not str or self.phase not in ('MISSION','CHARGE'):raise ValueError('solar phase')
        for n in ('ordinal','point_attempts','point_completions','point_refusals'):_integer(getattr(self,n),n)
        if self.point_completions+self.point_refusals>self.point_attempts or self.positive_charge_hold_seconds>self.charge_hold_seconds:raise ValueError('solar cumulative balance')
        for n in ('last_action_id','reason'):
            v=getattr(self,n)
            if type(v) is not str or len(v)>256:raise ValueError('bounded solar state text')
        if self.held_target is not None:
            if type(self.held_target) is not SolarTarget:raise TypeError('exact held Sun target')
            self.held_target.__post_init__()
            if self.held_target.clock_seconds>self.clock_seconds:raise ValueError('future held solar target')
        if self.last_incidence_deg is not None and (type(self.last_incidence_deg) is not float or not isfinite(self.last_incidence_deg) or not 0<=self.last_incidence_deg<=180):raise ValueError('last actual solar incidence')
        if self.last_illumination is not None and self.last_illumination not in ('ILLUMINATED','OCCULTED','UNRESOLVED','UNAVAILABLE'):raise ValueError('solar support illumination')
        if type(self.last_support) is not tuple or len(self.last_support) not in (0,2):raise ValueError('solar support tuple')
        if self.last_support:
            for x in self.last_support:_seconds(x)
            if not self.last_support[0]<self.last_support[1]<=self.clock_seconds:raise ValueError('solar last support clock')

@dataclass(frozen=True,slots=True)
class SolarSpatialSlew(EffectiveSpatialSlew):
    method: str = 'B56_EFFECTIVE_EXPLICIT_BODY_AXIS_SPATIAL_SLEW_V1'
    commanded_body_axis: tuple = (0.,0.,1.)

def panel_axis(hardware):
    if type(hardware) is not EffectiveAssemblyHardware:raise TypeError('effective full-tensor harness hardware')
    if len(hardware.capabilities)!=2 or sum(c.role=='panel' for c in hardware.capabilities)!=1:raise ValueError('UNSUPPORTED_SOLAR_MULTIPLE_PANEL_NORMALS')
    return bounded_direction(hardware.panel_body_normal)

def paid_sun_target(world,clock):
    """Separate ACTUAL/FORECAST paid orbit+Sun queries; no hidden observation."""
    from .rolling_physics import digest
    t=Q(clock);world.guard();world.pay(128)
    orbit=world.provider.at_seconds(t);sun=world.sun_position(orbit.position.instant)
    return SolarTarget(world.identity,world.role,t,orbit.position.frame,
        digest(orbit.position.instant.epoch),bounded_direction(tuple(s-r for s,r in zip(sun.components_m,orbit.position.components_m))))

def plan_axis_slew(hardware,attitude,body_axis,target_direction,*,work=None,policy=None):
    if type(hardware) is not EffectiveAssemblyHardware or type(attitude) is not BodyAttitude3D:raise TypeError('explicit effective hardware/3D pose')
    if work is not None:work.reserve_compile(policy)
    attitude.__post_init__();validate_effective_hardware(hardware)
    if attitude.body_frame_id!=hardware.design.body_frame_id:raise ValueError('foreign body frame')
    axis0=bounded_direction(body_axis)
    goal=bounded_direction(attitude.inverse_direction(bounded_direction(target_direction)))
    axis=cross(axis0,goal);sine=hypot(*axis);cosine=max(-1.,min(1.,dot(axis0,goal)));angle=atan2(sine,cosine)
    if angle<STEERING_ZERO_RAD:angle=0.;axis=(0.,0.,1.)
    elif sine<STEERING_ZERO_RAD:
        index=min(range(3),key=lambda i:(abs(axis0[i]),i));basis=tuple(1. if i==index else 0. for i in range(3))
        axis=bounded_direction(cross(axis0,basis))
        if next(x for x in axis if abs(x)>STEERING_ZERO_RAD)<0:axis=tuple(-x for x in axis)
        angle=pi
    else:axis=bounded_direction(axis)
    v=tuple(Q(x) for x in axis);s=dot(v,v);root_lo,_=sqrt_bounds(s)
    if root_lo<=0:raise ValueError('unsupported axis norm')
    Iv=matvec(hardware.tensor_exact,v);G=tuple(x/s for x in cross(v,Iv));eff=dot(v,Iv)/s
    U=tuple(abs(x)/root_lo for x in v);L=tuple(abs(x)/root_lo for x in Iv)
    p=hardware.actuator;torque=tuple(Q(x) for x in p.torque_limits_nm)
    acap=min(t/(2*l) for t,l in zip(torque,L) if l)
    wcaps=[Q(r)/u for r,u in zip(p.rate_limits_rad_s,U) if u]
    wcaps += [Q(h)/l for h,l in zip(p.body_momentum_limits_nms,L) if l]
    wcaps += [sqrt_bounds(t/(2*abs(g)))[0] for t,g in zip(torque,G) if g]
    wcap=min(wcaps);theta=Q(float(angle))
    if theta:
        T=max(sqrt_bounds(theta/acap)[1],theta/wcap);T=Q(ceil(T*2**40),2**40);a=theta/(T*T);peak=theta/T
    else:T=a=peak=Q(0)
    tau=tuple(l*a+abs(g)*peak*peak for l,g in zip(L,G));rates=tuple(u*peak for u in U);H=tuple(l*peak for l in L)
    if any(x>lim for x,lim in zip(tau,torque)) or any(x>Q(lim) for x,lim in zip(rates,p.rate_limits_rad_s)) or any(x>Q(lim) for x,lim in zip(H,p.body_momentum_limits_nms)):raise ValueError('whole-phase actuator exhaustion')
    rest=ceil(2*T);duration=rest+p.settling_seconds
    if duration>120:raise ValueError('spatial slew exceeds short action bound')
    return SolarSpatialSlew(hardware,attitude,axis,theta,a,T,peak,eff,U,L,G,tau,rates,H,duration,rest,commanded_body_axis=body_axis)
