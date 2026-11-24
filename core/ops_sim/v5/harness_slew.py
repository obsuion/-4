"""B46 validated opt-in planner; unchanged accepted pure M3 formulas/pose.

Copied constructive formula evaluates all nine effective tensor entries,
I*axis, axis-cross-Iaxis, rate/momentum/torque and mechanical work guards.
No old hardware impersonation or old compiler monkeypatch.
"""
from dataclasses import dataclass
from fractions import Fraction as Q
from math import atan2,hypot,pi,ceil
from .assembly_slew_3d import (SpatialSlew,cross,dot,matvec,sqrt_bounds,bounded_direction,STEERING_ZERO_RAD)
from .assembly_attitude_3d import BodyAttitude3D
from .harness_hardware import EffectiveAssemblyHardware,validate_effective_hardware
from .environment_forcing import _type

@dataclass(frozen=True,slots=True)
class EffectiveSpatialSlew(SpatialSlew):
    hardware: EffectiveAssemblyHardware
    method: str = 'B46_EFFECTIVE_FULL_TENSOR_CONSERVATIVE_SPATIAL_SLEW_V1'

def plan_effective_slew(hardware,attitude,target_direction,*,work=None,policy=None):
    _type(hardware,EffectiveAssemblyHardware,'derived B46 effective hardware');_type(attitude,BodyAttitude3D,'3D pose')
    if work is not None:work.reserve_compile(policy)
    attitude.__post_init__()
    validate_effective_hardware(hardware)
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
    return EffectiveSpatialSlew(hardware,attitude,axis,theta,a,T,peak,eff,U,L,G,tau,rates,H,duration,rest)
