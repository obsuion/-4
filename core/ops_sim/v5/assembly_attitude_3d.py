"""Opt-in full M1 tensor and homogeneous Hamilton body-to-inertial pose.

Fixed ideal pose, not measured attitude or uncertainty. All binary components
are declared exact real inputs. No change to the accepted principal-Y family.
"""
from dataclasses import dataclass
from fractions import Fraction as Q
from math import isfinite, fsum, hypot
from .assembly_choices import AssemblyDesign, assess_design
from .assembly import calculate_mass_properties
from .assembly_document import assembly_document_digest
from .assembly_attitude import ComponentAxisBinding, rotate, vector
from .environment_forcing import _type, _text, _number, _integer
from .orbit_config import FrameDefinition, FrameKind, _frame

MODE='M3_IDEAL_NET_BODY_TORQUE_FULL_TENSOR_V1'
POSE='M3_HAMILTON_SCALAR_FIRST_ACTIVE_BODY_TO_INERTIAL_HOMOGENEOUS_V1'
SPD_RELATIVE_FLOOR=Q(1,2**40)
SYMMETRY_RELATIVE_ALLOWANCE=Q(1,2**40)

def canonical_quaternion(value):
    _type(value,tuple,'quaternion')
    if len(value)!=4 or any(type(x) is not float or not isfinite(x) for x in value):
        raise ValueError('four finite builtin float quaternion components required')
    scale=max(abs(x) for x in value)
    if not 2**-200<=scale<=2**200:raise ValueError('quaternion norm outside bounded domain')
    # Homogeneous normalization is idempotent; no square root in the pose.
    q=tuple(x/scale for x in value)
    if next(x for x in q if x)!=abs(next(x for x in q if x)):
        q=tuple(-x for x in q)
    return tuple(0. if x==0 else x for x in q)

def quaternion_product(a,b):
    a=canonical_quaternion(a);b=canonical_quaternion(b)
    w,x,y,z=a;v,i,j,k=b
    return canonical_quaternion((w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,
        w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v))

def quaternion_matrix(q):
    w,x,y,z=canonical_quaternion(q);n=fsum(t*t for t in (w,x,y,z))
    return (((w*w+x*x-y*y-z*z)/n,2*(x*y-w*z)/n,2*(x*z+w*y)/n),
            (2*(x*y+w*z)/n,(w*w-x*x+y*y-z*z)/n,2*(y*z-w*x)/n),
            (2*(x*z-w*y)/n,2*(y*z+w*x)/n,(w*w-x*x-y*y+z*z)/n))

@dataclass(frozen=True,slots=True)
class BodyAttitude3D:
    body_frame_id: str
    inertial_frame: FrameDefinition
    at_seconds: Q
    quaternion: tuple[float,float,float,float]
    rest_since_seconds: Q
    method: str=POSE
    def __post_init__(self):
        _text(self.body_frame_id,'body frame',256);_type(self.inertial_frame,FrameDefinition,'inertial frame')
        _frame(self.inertial_frame)
        if self.inertial_frame.kind is not FrameKind.MODEL_INERTIAL:raise ValueError('foreign inertial frame kind')
        _type(self.at_seconds,Q,'pose time');_type(self.rest_since_seconds,Q,'rest time')
        if any(max(abs(x.numerator).bit_length(),x.denominator.bit_length())>128 for x in (self.at_seconds,self.rest_since_seconds)):
            raise ValueError('pose time outside bounded rational domain')
        if self.rest_since_seconds>self.at_seconds:raise ValueError('future rest time')
        if self.method!=POSE or type(self.method) is not str:raise ValueError('foreign pose method')
        object.__setattr__(self,'quaternion',canonical_quaternion(self.quaternion))
    @property
    def rotation_inertial_from_body(self):return quaternion_matrix(self.quaternion)
    def direction(self,body_direction):return vector(rotate(self.rotation_inertial_from_body,body_direction))
    def inverse_direction(self,inertial_direction):
        m=self.rotation_inertial_from_body
        return vector(rotate(tuple(zip(*m)),inertial_direction))

@dataclass(frozen=True,slots=True)
class NetTorqueActuatorPolicy:
    torque_limits_nm: tuple[float,float,float]
    rate_limits_rad_s: tuple[float,float,float]
    electronics_power_w: float
    drive_efficiency: float
    settling_seconds: int
    body_momentum_limits_nms: tuple[float,float,float]
    assumption: str
    mode: str=MODE
    def __post_init__(self):
        for n in ('torque_limits_nm','rate_limits_rad_s','body_momentum_limits_nms'):
            v=getattr(self,n);_type(v,tuple,n)
            if len(v)!=3:raise ValueError('three per-axis limits required')
            for x in v:
                _number(x,n,positive=True)
                if not 2**-30<=x<=2**30:raise ValueError('actuator limit outside bounded domain')
        _number(self.electronics_power_w,'electronics W');_number(self.drive_efficiency,'drive efficiency',positive=True)
        if self.drive_efficiency>1 or self.electronics_power_w>2**20:raise ValueError('invalid drive policy')
        _integer(self.settling_seconds,'settling')
        if self.settling_seconds>120:raise ValueError('settling bound exceeded')
        _text(self.assumption,'ideal actuator assumption')
        if type(self.mode) is not str or self.mode!=MODE:raise ValueError('foreign actuator mode')

@dataclass(frozen=True,slots=True)
class AssemblyHardware3D:
    design: AssemblyDesign
    assembly_digest: str
    mass_properties: object
    camera_body_axis: tuple
    panel_body_normal: tuple
    tensor_exact: tuple
    spd_leading_minors: tuple
    symmetry_residual_kg_m2: Q
    symmetry_allowance_kg_m2: Q
    actuator: NetTorqueActuatorPolicy
    capabilities: tuple
    method: str=MODE

def admit_tensor(tensor):
    if type(tensor) is not tuple or len(tensor)!=3 or any(type(r) is not tuple or len(r)!=3 for r in tensor):
        raise ValueError('full 3x3 immutable tensor required')
    if any(type(x) is not float or not isfinite(x) or abs(x)>2**30 for r in tensor for x in r):
        raise ValueError('tensor outside finite bounded domain')
    I=tuple(tuple(Q(x) for x in r) for r in tensor)
    scale=max(abs(x) for r in I for x in r)
    residual=max(abs(I[i][j]-I[j][i]) for i in range(3) for j in range(3))
    if residual>SYMMETRY_RELATIVE_ALLOWANCE*scale:raise ValueError('nonsymmetric tensor')
    # Admission of the quadratic form only: x^T I x = x^T sym(I) x.
    # Return and use ALL original M1 entries, never replace the authoritative I.
    a,d,f=I[0][0],I[1][1],I[2][2]
    b=(I[0][1]+I[1][0])/2;c=(I[0][2]+I[2][0])/2;e=(I[1][2]+I[2][1])/2
    minors=(a,a*d-b*b,a*d*f+2*b*c*e-a*e*e-d*c*c-f*b*b)
    if scale==0 or any(v<=SPD_RELATIVE_FLOOR*scale**(i+1) for i,v in enumerate(minors)):
        raise ValueError('singular/nonpositive/unsupported ill-conditioned tensor')
    return I,minors

def compile_assembly_hardware_3d(design,capabilities,actuator):
    _type(design,AssemblyDesign,'M1 design');_type(actuator,NetTorqueActuatorPolicy,'ideal net torque')
    actuator.__post_init__();_type(capabilities,tuple,'capabilities')
    if any(len(getattr(design,n))>32 for n in ('definitions','instances','choices','selections','allowed_regions','reserved_regions')):
        raise ValueError('spatial assembly exceeds32-entry admission domain')
    if len(capabilities)!=2 or {c.role for c in capabilities if type(c) is ComponentAxisBinding}!={'camera','panel'}:
        raise ValueError('one actual camera and panel required')
    assessment=assess_design(design)
    if not assessment.qualified or assessment.assembly is None:raise ValueError('unchecked/infeasible assembly')
    mass=calculate_mass_properties(assessment.assembly)
    if not 0<mass.total_mass_kg<=2**20 or any(not isfinite(x) for x in mass.center_body_m):
        raise ValueError('mass/COM outside bounded domain')
    I,minors=admit_tensor(mass.inertia_com_body_kg_m2)
    components={c.component_id:c for c in assessment.assembly.components};directions={}
    for b in capabilities:
        _type(b,ComponentAxisBinding,'capability');b.__post_init__()
        if b.component_id not in components:raise ValueError('foreign capability component')
        c=components[b.component_id]
        if c.mount_pose is None or c.definition.local_frame_id!=b.local_frame_id:raise ValueError('foreign/unmounted capability')
        directions[b.role]=vector(rotate(c.mount_pose.rotation_body_from_local,b.local_axis))
    return AssemblyHardware3D(design,assembly_document_digest(design),mass,directions['camera'],directions['panel'],
        I,minors,max(abs(I[i][j]-I[j][i]) for i in range(3) for j in range(3)),
        SYMMETRY_RELATIVE_ALLOWANCE*max(abs(x) for row in I for x in row),actuator,capabilities)
