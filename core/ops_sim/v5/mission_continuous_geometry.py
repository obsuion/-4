"""B41 conservative closed-time point/FOV geometry from acquired B38 SI tubes.

Supported domain: spherical reference body, surface equatorial points,
MODEL_INERTIAL / actual uniform +z Earth rotation, |theta| <=32 rad, and a
held declared camera vector. No orbit propagation, serviceability or optical
resolution law. Exact rationals and Taylor/Lipschitz bounds are the authority.
"""
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction as Q
from hashlib import sha256
from math import isfinite, isqrt, ceil
import json
from .environment_forcing import _source
from .orbit_geometry import GroundPointDefinition
from .orbit_visibility import GroundVisibilityPolicy
from .orbit_config import FrameKind, _frame

MODE='CONTINUOUS_B38_SPHERE_EQUATOR_HELD_CAMERA_V1'
METHOD='RATIONAL_TAYLOR128_LIPSCHITZ_CLOSED_TUBE_V1'


@dataclass(frozen=True,slots=True)
class ContinuousGeometryPolicy:
    method: str = METHOD
    maximum_cell_seconds: Q = Q(1,2)
    maximum_cells: int = 512
    maximum_queries: int = 64
    maximum_operations: int = 2**22
    maximum_control_units: int = 2**22
    maximum_rational_bits: int = 32768
    maximum_retained_bytes: int = 8*2**20

    def __post_init__(self):
        if type(self.method) is not str or self.method!=METHOD:raise ValueError('unsupported continuous method')
        if type(self.maximum_cell_seconds) is not Q or not Q(1,64)<=self.maximum_cell_seconds<=Q(5):
            raise ValueError('bounded exact cell duration required')
        for name,cap in (('maximum_cells',512),('maximum_queries',64),('maximum_operations',2**22),
                         ('maximum_control_units',2**22),('maximum_rational_bits',32768),('maximum_retained_bytes',8*2**20)):
            v=getattr(self,name)
            if type(v) is not int or not 1<=v<=cap:raise ValueError('invalid geometry limit: '+name)
        if self.maximum_rational_bits<2048:raise ValueError('insufficient rational workspace admission')


class _AcquiredSource:
    """Process-local producer binding; never serializable input/proof authority."""
    __slots__=('source','environment','signature')
    def __init__(self,source,environment):
        self.source=source;self.environment=environment
        self.signature=_source_signature(source)


def _source_signature(source):
    # Complete output signature; JSON documents are never decoded into this owner.
    from .environment_mission_continuation import _scientific,canonical_json
    return sha256(canonical_json(_scientific(source)).encode()).hexdigest()


def _bind_acquired_source(source,environment):
    _source(source,environment)  # Accepted full ancestry/authority/partition checks.
    return _AcquiredSource(source,environment)


class _Arithmetic:
    def __init__(self,policy,charge):
        self.p=policy;self.charge=charge;self.operations=0;self.controls=0
    def control(self,n=1):
        self.charge('geometry_control_units',n);self.controls+=n
    def q(self,x):
        self.control()
        if type(x) not in (Q,int,float,Decimal):raise TypeError('exact finite scalar required')
        if type(x) is float and not isfinite(x):raise ValueError('nonfinite scalar')
        if type(x) is Decimal and not x.is_finite():raise ValueError('nonfinite Decimal')
        x=Q(x)
        if max(abs(x.numerator).bit_length(),x.denominator.bit_length())>self.p.maximum_rational_bits:
            raise ValueError('GEOMETRY_RATIONAL_BIT_LIMIT')
        return x
    def op(self,x,y,kind):
        x=self.q(x);y=self.q(y)
        # Conservative pre-operation bound, so temporary integers are finite too.
        if max(abs(x.numerator).bit_length(),x.denominator.bit_length())+max(abs(y.numerator).bit_length(),y.denominator.bit_length())+2>self.p.maximum_rational_bits:
            raise ValueError('GEOMETRY_RATIONAL_WORKSPACE_LIMIT')
        self.charge('geometry_operations',1);self.operations+=1
        z={'add':lambda:x+y,'sub':lambda:x-y,'mul':lambda:x*y,'div':lambda:x/y}[kind]()
        return self.q(z)
    def add(self,x,y):return self.op(x,y,'add')
    def sub(self,x,y):return self.op(x,y,'sub')
    def mul(self,x,y):return self.op(x,y,'mul')
    def div(self,x,y):return self.op(x,y,'div')
    def rounded(self,x,upper=False):
        x=self.q(x);self.control()
        k=(x.numerator*2**80)//x.denominator
        if upper and Q(k,2**80)!=x:k+=1
        return Q(k,2**80)
    def sqrt(self,x,upper=False):
        x=self.q(x)
        if x<0:raise ValueError('negative interval square root')
        self.control();self.charge('geometry_operations',1);self.operations+=1
        k=isqrt((x.numerator*2**160)//x.denominator)
        if upper and Q(k*k,2**160)<x:k+=1
        return Q(k,2**80)


def _add(a,x,y):return (a.add(x[0],y[0]),a.add(x[1],y[1]))
def _sub(a,x,y):return (a.sub(x[0],y[1]),a.sub(x[1],y[0]))
def _mul(a,x,y):
    a.control(4);z=[a.mul(u,v) for u in x for v in y];return min(z),max(z)
def _square(a,x):
    a.control(3);z=(a.mul(x[0],x[0]),a.mul(x[1],x[1]));return (Q(0) if x[0]<=0<=x[1] else min(z),max(z))
def _dot(a,x,y):
    z=(Q(0),Q(0))
    for u,v in zip(x,y):a.control();z=_add(a,z,_mul(a,u,v))
    return z
def _norm2(a,x):
    z=(Q(0),Q(0))
    for u in x:a.control();z=_add(a,z,_square(a,u))
    return z


def _trig_bounds(a,lo,hi):
    """Maclaurin through sin127/cos126; finite Lagrange remainder.

    sin/cos derivatives have absolute value <=1 for every real argument.
    Expanding at 0: |R_sin|<=|m|^129/129!, |R_cos|<=|m|^128/128!.
    Both functions are globally 1-Lipschitz: add interval radius around m.
    Final dyadic floor/ceil are exact outward conversions; no libm values.
    """
    lo=a.q(lo);hi=a.q(hi)
    if lo>hi or max(abs(lo),abs(hi))>32:raise ValueError('UNSUPPORTED_ROTATION_PHASE_DOMAIN')
    m=a.div(a.add(lo,hi),2);rad=a.div(a.sub(hi,lo),2);m2=a.mul(m,m)
    s=st=m;c=ct=Q(1)
    for k in range(1,64):
        a.control()
        st=a.div(a.mul(-m2,st),(2*k)*(2*k+1));ct=a.div(a.mul(-m2,ct),(2*k-1)*(2*k))
        s=a.add(s,st);c=a.add(c,ct)
    sr=a.div(a.mul(m2,abs(st)),128*129);cr=a.div(a.mul(m2,abs(ct)),127*128)
    def enclose(v,err):
        margin=a.add(err,rad)
        return max(Q(-1),a.rounded(a.sub(v,margin))),min(Q(1),a.rounded(a.add(v,margin),True))
    return enclose(s,sr),enclose(c,cr)


@dataclass(frozen=True,slots=True)
class ContinuousGeometryCell:
    start_seconds: Q
    end_seconds: Q
    source_piece_index: int
    source_step_id: int
    parent_boundary_id: int
    endpoint_boundary_id: int
    source_closed_support: tuple
    position_bounds_m: tuple
    ground_position_bounds_m: tuple
    ground_normal_bounds: tuple
    dependent_direction_bounds_m: tuple
    slant_range_bounds_m: tuple
    surface_departure_bounds_m: tuple
    off_nadir_cosine_bounds: tuple
    camera_dot_direction_bounds_m: tuple | None
    visibility: str
    fov: str
    status: str


@dataclass(frozen=True,slots=True)
class CameraEndRay:
    at_seconds: Q
    source_step_id: int
    source_closed_support: tuple
    origin_position_bounds_m: tuple
    held_inertial_direction: tuple
    forward_sphere_intersection: str
    first_intersection_parameter_bounds_m_per_direction_unit: tuple | None
    origin_bound_kind: str
    source_boundary_id: int | None
    held_inertial_direction_bounds: tuple
    declared_body_axis_norm_squared: Q


@dataclass(frozen=True,slots=True)
class ContinuousGeometryResult:
    mode: str
    method: str
    policy: ContinuousGeometryPolicy
    authority_digest: str
    source_signature: str
    certificate_id: str
    frame: object
    point: GroundPointDefinition
    visibility_policy: GroundVisibilityPolicy
    start_seconds: Q
    end_seconds: Q
    original_anchor_seconds: Q
    closed_support: bool
    positive_duration: bool
    status: str
    cells: tuple[ContinuousGeometryCell,...]
    start_ray: CameraEndRay | None
    end_ray: CameraEndRay | None
    operations: int
    control_units: int


def admit_geometry_domain(environment,entry,policy):
    if type(policy) is not ContinuousGeometryPolicy:raise TypeError('continuous geometry policy required')
    policy.__post_init__();entry.__post_init__()
    f=_frame(environment.source_request.segment.trajectory.initial_state.position.frame)
    p=entry.point
    if f.kind is not FrameKind.MODEL_INERTIAL or p.ellipsoid!=f.ellipsoid:
        raise ValueError('foreign full geometry frame/ellipsoid')
    if f.ellipsoid.flattening.value!=0 or p.latitude_rad.value!=0 or p.ellipsoidal_height_m.value!=0:
        raise ValueError('UNSUPPORTED_GEOMETRY_DOMAIN: spherical equatorial surface only')
    if not 0<=entry.visibility_policy.minimum_elevation_rad.value<1.5707963267948966:
        raise ValueError('unsupported minimum elevation')
    radius=Q(f.ellipsoid.equatorial_radius_m.value)
    if not 1<=radius<=2**32:raise ValueError('bounded sphere radius required')
    phase=Q(f.rotation.initial_phase_rad.value)+Q(p.longitude_rad.value)
    rate=Q(f.rotation.angular_velocity_rad_per_s.value)
    times=(environment.start_seconds,environment.end_seconds)
    if max(abs(phase+rate*t) for t in times)>32:raise ValueError('UNSUPPORTED_ROTATION_PHASE_DOMAIN')
    return f,radius,phase,rate


def _predicates(a,r,normal,radius,minimum_elevation,camera,cos_fov,camera_norm2=None):
    g=tuple(_mul(a,(radius,radius),n) for n in normal)
    d=tuple(_sub(a,x,y) for x,y in zip(g,r));rho2=_norm2(a,d);r2=_norm2(a,r)
    departure=_sub(a,_dot(a,normal,r),(radius,radius))
    outside=r2[0]>a.mul(radius,radius)
    if r2[1]<a.mul(radius,radius) or departure[1]<0:vis='BLOCKED'
    elif outside and departure[0]>0:
        sine,_=_trig_bounds(a,minimum_elevation,minimum_elevation)
        if a.mul(departure[0],departure[0])>a.mul(a.mul(max(Q(0),sine[1]),max(Q(0),sine[1])),rho2[1]):vis='VISIBLE'
        elif a.mul(departure[1],departure[1])<a.mul(a.mul(max(Q(0),sine[0]),max(Q(0),sine[0])),rho2[0]):vis='BLOCKED'
        else:vis='UNRESOLVED'
    else:vis='UNRESOLVED'
    distance=(a.sqrt(rho2[0]),a.sqrt(rho2[1],True))
    numerator=_dot(a,tuple((-x[1],-x[0]) for x in r),d)
    den=(a.sqrt(a.mul(r2[0],rho2[0])),a.sqrt(a.mul(r2[1],rho2[1]),True))
    if den[0]<=0:off=(-Q(1),Q(1))
    else:
        vals=[a.div(n,z) for n in numerator for z in den]
        off=max(-Q(1),min(vals)),min(Q(1),max(vals))
    dot=None;fov='NOT_REQUESTED'
    if camera is not None:
        c=tuple(v if type(v) is tuple else (v,v) for v in camera);dot=_dot(a,c,d);c2=_norm2(a,c)[0] if camera_norm2 is None else camera_norm2
        if c2<=0:raise ValueError('zero held camera vector')
        lower=max(Q(0),cos_fov[0]);upper=max(Q(0),cos_fov[1])
        if dot[1]<0 or (dot[1]>=0 and a.mul(dot[1],dot[1])<a.mul(a.mul(lower,lower),a.mul(c2,rho2[0]))):fov='BLOCKED'
        elif dot[0]>0 and a.mul(dot[0],dot[0])>a.mul(a.mul(upper,upper),a.mul(c2,rho2[1])):fov='VISIBLE'
        else:fov='UNRESOLVED'
    status='BLOCKED' if 'BLOCKED' in (vis,fov) else 'UNRESOLVED' if 'UNRESOLVED' in (vis,fov) else 'VISIBLE'
    return g,d,distance,departure,off,dot,vis,fov,status


def _end_ray(a,cell,time,camera,radius,source,nominal_camera,camera_norm2):
    # At a genuine source boundary, project its entire accumulated set exactly.
    # Between boundaries retain the full whole-step tube at the terminal time.
    # Neither path propagates, clips uncertainty, or accepts diagnostic JSON.
    r=cell.position_bounds_m;kind='WHOLE_CLOSED_TUBE_AT_EXACT_TIME';boundary_id=None
    step=source.steps[cell.source_step_id]
    for bid in (step.parent_boundary_id,step.endpoint_boundary_id):
        a.control();boundary=source.boundaries[bid]
        if boundary.set.time==time:
            d=boundary.set;box=[]
            for axis in range(3):
                center=a.q(d.center[axis]);rad=Q(0)
                for column in d.generators:a.control();rad=a.add(rad,abs(a.q(column[axis])))
                scale=a.q(Q(10)**boundary.scale_exponents[axis])
                box.append((a.mul(a.sub(center,rad),scale),a.mul(a.add(center,rad),scale)))
            r=tuple(box);kind='FULL_ACCUMULATED_SOURCE_BOUNDARY';boundary_id=bid
            if any(max(x[0],y[0])>min(x[1],y[1]) for x,y in zip(r,cell.position_bounds_m)):
                raise ValueError('incompatible terminal boundary and whole tube')
            break
    c=camera
    c2=camera_norm2;r2=_norm2(a,r);rc=_dot(a,r,c)
    delta=_sub(a,_square(a,rc),_mul(a,(c2,c2),_sub(a,r2,(a.mul(radius,radius),)*2)))
    hit='UNRESOLVED';parameters=None
    if r2[0]>a.mul(radius,radius) and rc[1]<0 and delta[0]>0:
        root=(a.sqrt(delta[0]),a.sqrt(delta[1],True))
        lam=_sub(a,(-rc[1],-rc[0]),root)
        parameters=(a.div(lam[0],c2),a.div(lam[1],c2))
        if parameters[0]>0:hit='VISIBLE'
    elif delta[1]<0 or rc[0]>=0:hit='BLOCKED'
    return CameraEndRay(time,cell.source_step_id,cell.source_closed_support,r,nominal_camera,hit,parameters,kind,boundary_id,camera,camera_norm2)


def evaluate_continuous_geometry(authority,environment,entry,start,end,policy,*,held_camera=None,half_fov_rad=None,held_angle_y_rad=None,body_camera_axis=None,charge):
    """Whole interval from producer-owned tubes. No result-file input path exists."""
    if type(authority) is not _AcquiredSource or authority.environment.source_request!=environment.source_request:
        raise ValueError('acquired original source authority required')
    if type(policy) is not ContinuousGeometryPolicy:raise TypeError('continuous policy required')
    policy.__post_init__();charge('geometry_queries',1)
    ar=_Arithmetic(policy,charge);ar.control(sum(len(getattr(authority.source,n)) for n in ('steps','boundaries','pieces','geometry_records')))
    if _source_signature(authority.source)!=authority.signature:raise ValueError('mutated acquired source evidence')
    digest,auth,anchor,last,edges,supports=_source(authority.source,environment)
    frame,radius,phase,rate=admit_geometry_domain(environment,entry,policy)
    if type(start) is not Q or type(end) is not Q or not environment.start_seconds<=start<=end<=environment.end_seconds:
        raise ValueError('exact in-domain closed interval required')
    for t in (start,end):
        if max(abs(t.numerator).bit_length(),t.denominator.bit_length())>256:raise ValueError('time bit limit')
    camera=None;cos_fov=None;camera_norm2=None;nominal_camera=None
    if held_camera is not None:
        if type(held_camera) is not tuple or len(held_camera)!=3:raise TypeError('held camera vector required')
        nominal_camera=tuple(ar.q(v) for v in held_camera)
        if max(map(abs,nominal_camera))>2:raise ValueError('bounded camera vector required')
        if held_angle_y_rad is None and body_camera_axis is None:
            # Public geometry-only mode: explicitly declared exact held vector.
            camera=tuple((v,v) for v in nominal_camera);camera_norm2=_norm2(ar,camera)[0]
        else:
            if type(held_angle_y_rad) is not float or not isfinite(held_angle_y_rad) or type(body_camera_axis) is not tuple or len(body_camera_axis)!=3:
                raise ValueError('held body-y angle and declared M1 body camera required')
            body=tuple(ar.q(v) for v in body_camera_axis)
            if max(map(abs,body))>2:raise ValueError('bounded body camera required')
            sn,cs=_trig_bounds(ar,Q(held_angle_y_rad),Q(held_angle_y_rad))
            camera=(_add(ar,_mul(ar,cs,(body[0],)*2),_mul(ar,sn,(body[2],)*2)),
                    (body[1],)*2,_add(ar,_mul(ar,(-sn[1],-sn[0]),(body[0],)*2),_mul(ar,cs,(body[2],)*2)))
            # Exact Ry preserves this norm; interval component dependencies do not
            # justify re-normalizing the interval box as independent coordinates.
            camera_norm2=_norm2(ar,tuple((v,v) for v in body))[0]
        if type(half_fov_rad) is not float or not isfinite(half_fov_rad) or not 0<half_fov_rad<1.5707963267948966:
            raise ValueError('supported forward FOV required')
        _,cos_fov=_trig_bounds(ar,Q(half_fov_rad),Q(half_fov_rad))
    elif any(v is not None for v in (half_fov_rad,held_angle_y_rad,body_camera_axis)):raise ValueError('FOV/body attitude requires held camera')
    plan=[]
    for i,s in enumerate(supports):
        ar.control()
        left=max(start,s.piece.start_seconds);right=min(end,s.piece.end_seconds)
        if left<right or start==end and s.piece.start_seconds<=start<=s.piece.end_seconds and not plan:
            n=max(1,ceil((right-left)/policy.maximum_cell_seconds))
            if len(plan)+n>policy.maximum_cells:raise ValueError('GEOMETRY_CELL_LIMIT')
            plan.extend((i,s,left+(right-left)*Q(j,n),left+(right-left)*Q(j+1,n)) for j in range(n))
    if not plan or plan[0][2]!=start or plan[-1][3]!=end or any(x[3]!=y[2] for x,y in zip(plan,plan[1:])):
        raise ValueError('incomplete closed source partition')
    # A conservative pre-publication record bound; all later scalars checked too.
    if (len(plan)+2)*64*(policy.maximum_rational_bits//4+256)>policy.maximum_retained_bytes:
        # Actual workspace bit cap can be much larger than published dyadic bounds.
        # Use a separate fixed 2048-bit output bound, checked below.
        if (len(plan)+2)*64*(2048//4+128)>policy.maximum_retained_bytes:raise ValueError('GEOMETRY_RETAINED_BYTES_ADMISSION')
    cells=[]
    for i,s,left,right in plan:
        ar.control();step=authority.source.steps[s.step_id];tube=step.tube
        if not tube.start_seconds<=left<=right<=tube.end_seconds:raise ValueError('foreign closed tube support')
        r=tuple(tuple(ar.q(v) for v in pair) for pair in tube.position_bounds_m)
        if any(x>y or max(abs(x),abs(y))>2**48 for x,y in r):raise ValueError('invalid bounded source position box')
        angles=[ar.add(phase,ar.mul(rate,t)) for t in (left,right)]
        sn,cs=_trig_bounds(ar,min(angles),max(angles));normal=(cs,sn,(Q(0),Q(0)))
        values=_predicates(ar,r,normal,radius,Q(entry.visibility_policy.minimum_elevation_rad.value),camera,cos_fov,camera_norm2)
        g,d,distance,departure,off,dot,vis,fov,status=values
        cells.append(ContinuousGeometryCell(left,right,i,step.id,step.parent_boundary_id,step.endpoint_boundary_id,
            (tube.source_start_seconds,tube.source_end_seconds),r,g,normal,d,distance,departure,off,dot,vis,fov,status))
    status='BLOCKED' if any(c.status=='BLOCKED' for c in cells) else 'UNRESOLVED' if any(c.status=='UNRESOLVED' for c in cells) else 'VISIBLE'
    first=last_ray=None
    if camera is not None:
        first=_end_ray(ar,cells[0],start,camera,radius,authority.source,nominal_camera,camera_norm2);last_ray=_end_ray(ar,cells[-1],end,camera,radius,authority.source,nominal_camera,camera_norm2)
        if any(ray.forward_sphere_intersection!='VISIBLE' for ray in (first,last_ray)):
            status='BLOCKED' if any(ray.forward_sphere_intersection=='BLOCKED' for ray in (first,last_ray)) else 'UNRESOLVED'
    from .environment_mission_continuation import _scientific,canonical_json
    # Saved result is comparison data only. Bound before encoding/retaining.
    def bits(v):
        if type(v) is Q:
            if max(abs(v.numerator).bit_length(),v.denominator.bit_length())>2048:raise ValueError('GEOMETRY_PUBLICATION_BIT_LIMIT')
        elif type(v) in (tuple,list):
            for x in v:bits(x)
        elif hasattr(v,'__dataclass_fields__'):
            for n in v.__dataclass_fields__:bits(getattr(v,n))
    bits(tuple(cells));bits(first);bits(last_ray)
    ar.control((len(cells)+2)*64)
    payload=canonical_json(_scientific((MODE,policy,auth,authority.signature,frame,entry,start,end,tuple(cells),first,last_ray))).encode()
    if len(payload)>policy.maximum_retained_bytes:raise ValueError('GEOMETRY_RETAINED_BYTES_LIMIT')
    ar.control((len(payload)+63)//64)
    cid=sha256(payload).hexdigest()
    return ContinuousGeometryResult(MODE,METHOD,policy,auth,authority.signature,cid,frame,entry.point,entry.visibility_policy,
        start,end,anchor,True,end>start,status,tuple(cells),first,last_ray,ar.operations,ar.controls)