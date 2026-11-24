"""M1-derived mount vectors and a checked principal-body-y nominal wheel mode.

Full assembly tensor is consumed. This is not general three-axis dynamics.
Torque/rate/momentum, rotor and electrical assumptions are declared inputs.
"""
from dataclasses import dataclass
from fractions import Fraction as Q
from math import acos, atan2, ceil, cos, sin, hypot, pi, isfinite, fsum
from .assembly_choices import AssemblyDesign, assess_design
from .assembly import calculate_mass_properties
from .assembly_document import assembly_document_digest
from .design_trade_physics import SlewProfile
from .environment_forcing import _type, _text, _number
from .orbit_config import FrameDefinition

MODE='PRINCIPAL_BODY_Y_REST_TO_REST_WHEEL_V1'


def vector(value):
    _type(value,tuple,'axis')
    if len(value)!=3 or any(type(x) not in (int,float) or not isfinite(x) for x in value):
        raise ValueError('three finite builtin direction coordinates required')
    norm=hypot(*value)
    if norm==0:raise ValueError('zero direction')
    return tuple(float(x)/norm for x in value)


def angle_between(a,b):
    a,b=vector(a),vector(b)
    return acos(max(-1.,min(1.,fsum(x*y for x,y in zip(a,b)))))


def rotate(matrix,direction):
    return tuple(fsum(row[i]*direction[i] for i in range(3)) for row in matrix)


@dataclass(frozen=True,slots=True)
class ComponentAxisBinding:
    role: str
    component_id: str
    local_frame_id: str
    local_axis: tuple[float,float,float]
    assumption: str

    def __post_init__(self):
        if type(self.role) is not str or self.role not in ('camera','panel'):raise ValueError('unsupported capability role')
        _text(self.component_id,'component ID',256);_text(self.local_frame_id,'local frame',256)
        _text(self.assumption,'capability assumption')
        axis=vector(self.local_axis)
        if abs(hypot(*self.local_axis)-1.)>2**-40:raise ValueError('explicit unit local direction required')
        object.__setattr__(self,'local_axis',axis)


@dataclass(frozen=True,slots=True)
class ActuatorPolicy:
    torque_nm: float
    maximum_rate_rad_s: float
    momentum_nms: float
    rotor_inertia_kg_m2: float
    drive_efficiency: float
    electronics_power_w: float
    settling_seconds: int
    principal_relative_tolerance: float
    assumption: str
    mode: str = MODE

    def __post_init__(self):
        for n in ('torque_nm','maximum_rate_rad_s','momentum_nms','rotor_inertia_kg_m2','drive_efficiency'):
            _number(getattr(self,n),n,positive=True)
        _number(self.electronics_power_w,'electronics W')
        if self.drive_efficiency>1:raise ValueError('efficiency exceeds1')
        _type(self.settling_seconds,int,'settling seconds')
        if not 0<=self.settling_seconds<=120:raise ValueError('settling outside bounded domain')
        _number(self.principal_relative_tolerance,'principal numerical tolerance',positive=True)
        if self.principal_relative_tolerance>2**-30:raise ValueError('principal-axis tolerance too broad')
        _text(self.assumption,'actuator assumptions')
        if type(self.mode) is not str or self.mode!=MODE:raise ValueError('unsupported actuator mode')


@dataclass(frozen=True,slots=True)
class AssemblyHardware:
    design: AssemblyDesign
    assembly_digest: str
    mass_properties: object
    camera_body_axis: tuple
    panel_body_normal: tuple
    principal_y_residual_kg_m2: float
    principal_y_allowance_kg_m2: float
    inertia_y_kg_m2: float
    actuator: ActuatorPolicy
    capabilities: tuple[ComponentAxisBinding,...]


def compile_assembly_hardware(design,capabilities,actuator):
    _type(design,AssemblyDesign,'assembly design');_type(actuator,ActuatorPolicy,'actuator')
    actuator.__post_init__();_type(capabilities,tuple,'capabilities')
    for b in capabilities:_type(b,ComponentAxisBinding,'capability')
    if len(capabilities)!=2 or {c.role for c in capabilities}!= {'camera','panel'}:
        raise ValueError('one camera and one panel capability required')
    assessment=assess_design(design)
    if not assessment.qualified or assessment.assembly is None:
        raise ValueError('assembly requires checked declared mass/installation constraints')
    # The actual accepted M1 mass owner, not a caller scalar or stored result.
    mass=calculate_mass_properties(assessment.assembly);components={c.component_id:c for c in assessment.assembly.components}
    directions={}
    for b in capabilities:
        _type(b,ComponentAxisBinding,'capability');b.__post_init__()
        if b.component_id not in components:raise ValueError('foreign capability component')
        c=components[b.component_id]
        if c.mount_pose is None or c.definition.local_frame_id!=b.local_frame_id:
            raise ValueError('capability requires explicit matching M1 mount')
        directions[b.role]=vector(rotate(c.mount_pose.rotation_body_from_local,b.local_axis))
    I=mass.inertia_com_body_kg_m2;scale=max(abs(x) for row in I for x in row)
    residual=hypot(I[0][1],I[2][1]);allowance=actuator.principal_relative_tolerance*scale
    if I[1][1]<=0 or residual>allowance:
        raise ValueError('UNSUPPORTED_NON_PRINCIPAL_Y_INERTIA')
    if abs(directions['camera'][1])>2**-40:raise ValueError('camera axis outside supported rotation plane')
    return AssemblyHardware(design,assembly_document_digest(design),mass,directions['camera'],
        directions['panel'],residual,allowance,I[1][1],actuator,capabilities)


@dataclass(frozen=True,slots=True)
class BodyAttitude:
    body_frame_id: str
    inertial_frame: FrameDefinition
    at_seconds: Q
    angle_y_rad: float
    rest_since_seconds: Q

    def __post_init__(self):
        _text(self.body_frame_id,'body frame',256);_type(self.inertial_frame,FrameDefinition,'inertial frame')
        _type(self.at_seconds,Q,'attitude time');_type(self.rest_since_seconds,Q,'rest time')
        if self.rest_since_seconds>self.at_seconds:raise ValueError('future rest state')
        if type(self.angle_y_rad) is not float or not isfinite(self.angle_y_rad):raise ValueError('finite attitude angle required')

    @property
    def rotation_inertial_from_body(self):
        c,s=cos(self.angle_y_rad),sin(self.angle_y_rad)
        return ((c,0.,s),(0.,1.,0.),(-s,0.,c))

    def direction(self,body_direction):return vector(rotate(self.rotation_inertial_from_body,body_direction))


@dataclass(frozen=True,slots=True)
class AssemblySlew:
    initial: BodyAttitude
    final_angle_rad: float
    signed_direction: int
    profile: SlewProfile
    duration_seconds: int
    rest_start_offset_seconds: int
    hardware: AssemblyHardware

    def angle_at(self,offset):
        return self.initial.angle_y_rad+self.signed_direction*self.profile.angle_at(float(offset))

    def kinetic_j(self,offset):
        w=self.profile.omega_at(float(offset));I=self.hardware.inertia_y_kg_m2
        return .5*I*w*w+.5*(I*w)**2/self.hardware.actuator.rotor_inertia_kg_m2

    def cuts(self):
        p=self.profile
        return tuple(sorted({Q(0),Q(self.duration_seconds),Q(p.acceleration_s),
            Q(p.acceleration_s+p.coast_s),Q(p.duration_s),Q(self.rest_start_offset_seconds)}))


def plan_target_slew(hardware,attitude,target_direction):
    _type(hardware,AssemblyHardware,'assembly hardware');_type(attitude,BodyAttitude,'attitude')
    attitude.__post_init__()
    if attitude.body_frame_id!=hardware.design.body_frame_id:raise ValueError('foreign body frame')
    target=vector(target_direction)
    if abs(target[1])>2**-40:raise ValueError('UNSUPPORTED_TARGET_OUTSIDE_PRINCIPAL_Y_PLANE')
    body=hardware.camera_body_axis
    beta=atan2(-body[2],body[0]);goal=atan2(-target[2],target[0])-beta
    difference=atan2(sin(goal-attitude.angle_y_rad),cos(goal-attitude.angle_y_rad))
    if abs(difference)<2**-45:difference=0.0
    p=hardware.actuator;profile=SlewProfile(abs(difference),hardware.inertia_y_kg_m2,
        p.torque_nm,p.maximum_rate_rad_s,p.momentum_nms)
    rest=ceil(profile.duration_s);duration=rest+p.settling_seconds
    if duration>120:raise ValueError('slew exceeds short action bound')
    return AssemblySlew(attitude,attitude.angle_y_rad+difference,1 if difference>=0 else -1,
                        profile,duration,rest,hardware)
