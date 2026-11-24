"""Constructive conservative triangular rest-to-rest spatial net-torque model.

No search, wheel plant, regeneration or minimum-time claim. Rational guards
cover every phase. Nominal quaternion interpolation uses binary libm outputs.
"""
from dataclasses import dataclass
from fractions import Fraction as Q
from math import atan2, sin, cos, pi, ceil, isqrt, hypot, isfinite
from .assembly_attitude_3d import (AssemblyHardware3D, BodyAttitude3D,
    compile_assembly_hardware_3d, quaternion_product)
from .assembly_attitude import vector
from .environment_forcing import _type

METHOD='M3_CONSERVATIVE_TRIANGULAR_SPATIAL_REST_TO_REST_V1'
ROOT_BITS=80
STEERING_ZERO_RAD=2**-45

def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def matvec(I,v):return tuple(dot(row,v) for row in I)
def sqrt_bounds(x):
    _type(x,Q,'rational root input')
    if x<0 or max(x.numerator.bit_length(),x.denominator.bit_length())>2048:
        raise ValueError('root outside bounded rational domain')
    n=isqrt((x.numerator<<(2*ROOT_BITS))//x.denominator)
    lo=Q(n,2**ROOT_BITS)
    return lo,lo if lo*lo==x else Q(n+1,2**ROOT_BITS)

def bounded_direction(v):
    _type(v,tuple,'direction')
    if len(v)!=3 or any(type(x) not in (int,float) or not isfinite(x) for x in v):raise ValueError('finite direction required')
    norm=hypot(*v)
    if not 2**-100<=norm<=2**100:raise ValueError('direction norm outside bounded domain')
    return vector(v)

@dataclass(frozen=True,slots=True)
class SpatialEulerSample:
    offset_seconds: Q
    theta_rad: Q
    omega_body_rad_s: tuple
    alpha_body_rad_s2: tuple
    momentum_body_nms: tuple
    gyro_torque_nm: tuple
    net_torque_nm: tuple
    kinetic_j: Q
    mechanical_power_w: Q
    phase: str

@dataclass(frozen=True,slots=True)
class SpatialSlew:
    hardware: AssemblyHardware3D
    initial: BodyAttitude3D
    axis_body: tuple
    theta_rad: Q
    acceleration_rad_s2: Q
    acceleration_seconds: Q
    peak_rate_rad_s: Q
    effective_inertia_kg_m2: Q
    unit_axis_abs_upper: tuple
    inertia_axis_abs_upper: tuple
    gyro_coefficients_exact: tuple
    whole_torque_abs_upper_nm: tuple
    whole_rate_abs_upper_rad_s: tuple
    whole_body_momentum_abs_upper_nms: tuple
    duration_seconds: int
    rest_start_offset_seconds: int
    method: str=METHOD
    @property
    def motion_seconds(self):return 2*self.acceleration_seconds
    def cuts(self):
        return tuple(sorted({Q(0),self.acceleration_seconds,self.motion_seconds,
            Q(self.rest_start_offset_seconds),Q(self.duration_seconds)}))
    def scalar_state(self,t):
        _type(t,Q,'exact slew offset')
        if not 0<=t<=self.duration_seconds:raise ValueError('offset outside profile')
        a=self.acceleration_rad_s2;T=self.acceleration_seconds
        if self.theta_rad==0 or t>=2*T:return self.theta_rad,Q(0),Q(0),'REST'
        if t<T:return a*t*t/2,a*t,a,'ACCELERATING'
        s=t-T
        return self.theta_rad/2+self.peak_rate_rad_s*s-a*s*s/2,self.peak_rate_rad_s-a*s,-a,'BRAKING'
    def quaternion_at(self,t):
        theta,_,_,_=self.scalar_state(t)
        norm=hypot(*self.axis_body);u=tuple(x/norm for x in self.axis_body)
        h=float(theta)/2
        return quaternion_product(self.initial.quaternion,(cos(h),*(x*sin(h) for x in u)))
    def kinetic_j(self,t):
        _,w,_,_=self.scalar_state(t)
        return self.effective_inertia_kg_m2*w*w/2
    def euler_at(self,t):
        theta,w,a,phase=self.scalar_state(t)
        norm=hypot(*self.axis_body);u=tuple(x/norm for x in self.axis_body)
        I=self.hardware.mass_properties.inertia_com_body_kg_m2
        omega=tuple(x*float(w) for x in u);alpha=tuple(x*float(a) for x in u)
        H=matvec(I,omega);gyro=cross(omega,H);Ia=matvec(I,alpha)
        return SpatialEulerSample(t,theta,omega,alpha,H,gyro,tuple(x+y for x,y in zip(Ia,gyro)),
            self.kinetic_j(t),self.effective_inertia_kg_m2*a*w,phase)

def plan_target_slew_3d(hardware,attitude,target_direction):
    _type(hardware,AssemblyHardware3D,'actual full-tensor hardware');_type(attitude,BodyAttitude3D,'3D pose')
    attitude.__post_init__()
    if hardware!=compile_assembly_hardware_3d(hardware.design,hardware.capabilities,hardware.actuator):
        raise ValueError('foreign/stale derived hardware')
    if attitude.body_frame_id!=hardware.design.body_frame_id:raise ValueError('foreign body frame')
    camera=bounded_direction(hardware.camera_body_axis)
    goal=bounded_direction(attitude.inverse_direction(bounded_direction(target_direction)))
    axis=cross(camera,goal);sine=hypot(*axis);cosine=max(-1.,min(1.,dot(camera,goal)))
    angle=atan2(sine,cosine)
    if angle<STEERING_ZERO_RAD:angle=0.;axis=(0.,0.,1.)
    elif sine<STEERING_ZERO_RAD:
        # Exact/near antiparallel: deterministic least-aligned coordinate axis.
        index=min(range(3),key=lambda i:(abs(camera[i]),i))
        basis=tuple(1. if i==index else 0. for i in range(3));axis=bounded_direction(cross(camera,basis))
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
        T=max(sqrt_bounds(theta/acap)[1],theta/wcap)
        # Round UP to a 2^-40 second grid, leaving guards conservative.
        T=Q(ceil(T*2**40),2**40);a=theta/(T*T);peak=theta/T
    else:T=a=peak=Q(0)
    tau=tuple(l*a+abs(g)*peak*peak for l,g in zip(L,G))
    rates=tuple(u*peak for u in U);H=tuple(l*peak for l in L)
    if any(x>lim for x,lim in zip(tau,torque)) or any(x>Q(lim) for x,lim in zip(rates,p.rate_limits_rad_s)) or any(x>Q(lim) for x,lim in zip(H,p.body_momentum_limits_nms)):
        raise ValueError('whole-phase actuator exhaustion')
    rest=ceil(2*T);duration=rest+p.settling_seconds
    if duration>120:raise ValueError('spatial slew exceeds short action bound')
    return SpatialSlew(hardware,attitude,axis,theta,a,T,peak,eff,U,L,G,tau,rates,H,duration,rest)
