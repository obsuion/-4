# Included inside the bound _lifecycle_typed extension; no model callbacks.
# Source equations/ordering: lifecycle_orbit.query; orbit_j2 RK4;
# orbit_j2_gravity; lifecycle_world.schedule/sun_position/orientation_inputs;
# orbit_sun exact nominal quadratic; assembly_attitude(_3d) pose math.
from bisect import bisect_right as _w_right, bisect_left as _w_left
from math import (frexp as _w_frexp, ldexp as _w_ldexp, hypot as _w_hypot,
                  isfinite as _w_finite, ulp as _w_ulp, sin as _w_sin,
                  cos as _w_cos, tau as _w_tau, degrees as _w_degrees,
                  acos as _w_acos, ceil as _w_ceil)
from . import lifecycle_typed_world as _world_admission_import
cdef object _world_admission_owner=_world_admission_import
cdef object _world_admission_callable=_world_admission_import.admit_world_plan
cdef object _world_admission_code=_world_admission_callable.__code__
cdef object _world_admission_defaults=_world_admission_callable.__defaults__
cdef object _world_admission_kwdefaults=_world_admission_callable.__kwdefaults__
cdef object _world_admission_closure=_world_admission_callable.__closure__

cdef object _w_seconds(object value):
    if type(value) is not Fraction or max(abs(value.numerator).bit_length(), value.denominator.bit_length()) > 256 or abs(value) > 2**40:
        raise ValueError('bounded exact relative seconds required')
    return value

cdef object _w_product(object a, object b):
    value=a*b
    if not _w_finite(value) or (value==0 and a!=0 and b!=0):
        raise ValueError('RK4 product exceeds supported binary64 arithmetic')
    return value

cdef object _w_sum(object terms):
    try:value=fsum(terms)
    except OverflowError as error:raise ValueError('RK4 sum exceeds finite binary64 arithmetic') from error
    if not _w_finite(value):raise ValueError('RK4 sum must be finite')
    if value==0 and sum(map(Fraction,terms),Fraction())!=0:
        raise ValueError('nonzero RK4 sum underflows binary64')
    return value

cdef object _w_advance(object base,object derivative,object delta):
    result=[]
    for original,rate in zip(base,derivative):
        increment=_w_product(delta,rate);value=_w_sum((original,increment))
        if increment!=0 and value==original:raise ValueError('nonzero RK4 state increment is lost in binary64 addition')
        result.append(value)
    return tuple(result)

cdef object _w_qproduct(object factors,object radius,object power):
    if any(value==0 for value in factors):return 0.0
    mantissa,exponent=1.0,0
    for value in factors:
        part,shift=_w_frexp(value);mantissa*=part;exponent+=shift
    part,shift=_w_frexp(radius);mantissa/=part**power;exponent-=shift*power
    try:result=_w_ldexp(mantissa,exponent)
    except OverflowError as error:raise ValueError('gravity term exceeds finite binary64 arithmetic') from error
    if not _w_finite(result) or result==0:raise ValueError('nonzero gravity term is outside binary64 representation')
    return result

cdef object _w_gsum(object first,object second):
    try:result=fsum((first,second))
    except OverflowError as error:raise ValueError('gravity output exceeds finite binary64 arithmetic') from error
    if not _w_finite(result):raise ValueError('gravity output must be finite')
    return result

cdef object _w_gravity(object mu,object j2,object rg,object position):
    x,y,z=position;radius=_w_hypot(x,y,z)
    if radius==0 or not _w_finite(radius):raise ValueError('gravity requires a finite nonzero position norm')
    central=tuple(_w_qproduct((-mu,component),radius,3) for component in (x,y,z))
    potential=_w_qproduct((-mu,),radius,1)
    if j2==0:return (*central,potential)
    q=_w_qproduct((z,z),radius,2)
    correction=tuple(_w_qproduct((1.5,mu,j2,rg,rg,component,5*q-offset),radius,5)
                     for component,offset in ((x,1),(y,1),(z,3)))
    pc=_w_qproduct((0.5,mu,j2,rg,rg,3*q-1),radius,3)
    return (*(_w_gsum(a,b) for a,b in zip(central,correction)),_w_gsum(potential,pc))

cdef object _w_average(object a,object b,object c,object d):
    return tuple(_w_product(_w_sum((w,_w_product(2.0,x),_w_product(2.0,y),z)),1.0/6.0)
                 for w,x,y,z in zip(a,b,c,d))

cdef class TypedWorldPlan:
    cdef object data,role,transaction,context,source,provider,world,policy
    cdef object mu,j2,rg,profiles,profile_cuts,table_cuts,profile_data,node_ids
    cdef object camera,panel,quaternion,routing,provider_charge,world_charge
    cdef object external_seal,external_pins,token,counts
    cdef object pid
    cdef double mu65,j265,rg65
    cdef double scratch65[24][4]
    cdef bint machine65
    def __init__(self,object data,object key=None):
        if key is not _WORLD_FACTORY:raise TypeError('B64 compiled world factory required')
        self.data=data;self.role=data['role'];self.transaction=data['transaction'];self.context=data['context']
        self.source=data['source'];self.provider=data['provider'];self.world=data['world'];self.policy=data['policy']
        self.mu=data['mu'];self.j2=data['j2'];self.rg=data['gravity_radius']
        # Domain decided once, before any numerical operation or reservation.
        self.machine65=_B65 and all(type(x)is float or type(x)is int and abs(x)<=2**53 for x in(self.mu,self.j2,self.rg))
        if self.machine65:self.mu65=float(self.mu);self.j265=float(self.j2);self.rg65=float(self.rg)
        self.profiles=data['profiles'];self.profile_cuts=data['profile_cuts'];self.table_cuts=data['table_cuts']
        self.profile_data=data['profile_data'];self.node_ids=data['node_ids']
        self.camera=data['camera'];self.panel=data['panel'];self.quaternion=data['quaternion'];self.routing=data['routing']
        self.provider_charge=data['provider_charge'];self.world_charge=data['world_charge']
        self.external_seal=data['external_seal'];self.external_pins=data['external_pins'];self.token=object();self.pid=os.getpid()
        self.counts=dict(admissions=1,forcing_attempts=0,forcing_returned=0,support_attempts=0,support_returned=0,
                         orbit_queries=0,rk4_steps=0,lighting_samples=0,sun_queries=0,materializations=0)
        _w_guard(self)
    def validate(self):
        _w_guard(self);self.external_seal.guard()
        from .lifecycle_prepared import _exact_tree
        if _exact_tree(self.data['physical'].attitude)!=self.data['attitude_tree']:
            raise ValueError('B64 compiled world stationary attitude drift')
        p=self.external_pins;s=self.source;o=self.provider
        current=(self.role._external_model,s.environment,o.trajectory,o.policy,o.work,o._grid_states,o._tails,
                 s._lighting,s._profiles,s._profile_cuts,s._table_cuts,o._charge,s._charge)
        if any(a is not b for a,b in zip(p,current)):raise ValueError('B64 compiled world static/cache owner drift')
        return True
    def snapshot(self):
        self.validate()
        return dict(method='B64_COMPILED_CURRENT_WORLD_FORCING_V1',role=self.role.role,**self.counts,
            scope='OPERATIONAL_CALLS_NOT_ADDITIONAL_SCIENTIFIC_FEES')
    def __copy__(self):raise TypeError('B64 compiled world authority cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('B64 compiled world authority cannot be copied')
    def __reduce_ex__(self,protocol):raise TypeError('B64 compiled world authority is not persisted DATA')

cdef object _WORLD_FACTORY=object()
cdef object _WORLD_DATA_FACTORY=object()

cdef class WorldForcingData:
    """Same-extension immutable primitive cut; never checkpoint DATA."""
    cdef object _values,_owner
    def __init__(self,object values,object owner,object key=None):
        if key is not _WORLD_DATA_FACTORY:raise TypeError('B64 private world DATA factory required')
        self._values=values;self._owner=owner
    def __getitem__(self,key):return self._values[key]
    def get(self,key,default=None):return self._values.get(key,default)
    def __copy__(self):raise TypeError('B64 world DATA cannot be copied')
    def __deepcopy__(self,memo):raise TypeError('B64 world DATA cannot be copied')
    def __reduce_ex__(self,protocol):raise TypeError('B64 world DATA is not persisted authority')

cdef void _w_tick(TypedWorldPlan p,object key) except *:
    if p.counts[key]>=2**40:raise ValueError('B64_WORLD_OPERATIONAL_COUNTER_LIMIT')
    p.counts[key]+=1

cdef void _w_guard(TypedWorldPlan p) except *:
    if (p.pid!=os.getpid() or p.role._job._active is not p.transaction or p.transaction._phase!='ACTIVE' or
            p.role._job is not p.context.job or p.provider.work is not p.external_pins[4] or
            p.data['physical'].backend_context is not p.context or
            p.data['physical'].prepared_runtime is not p.role or
            p.provider._grid_states is not p.external_pins[5] or p.provider._tails is not p.external_pins[6] or
            p.source._lighting is not p.external_pins[7] or p.provider._charge is not p.provider_charge or
            p.source._charge is not p.world_charge or p.provider.failed):
        raise ValueError('B64 inactive/foreign compiled world plan')

include "lifecycle_typed_world65.pxi"

cdef object _w_rk4(TypedWorldPlan p,object r,object v,object delta):
    if _B65:
        key65='machine_world_steps'if p.machine65 else'reference_world_steps'
        if p.context.job._validation._counts[key65]>=2**40:raise ValueError('B65 world operational limit')
        p.context.job._validation._counts[key65]+=1
    if p.machine65:
        result65=_w65_step(p.mu65,p.j265,p.rg65,r,v,delta,p.scratch65)
        _w_tick(p,'rk4_steps')
        return result65
    half=_w_product(delta,0.5)
    k1r,k1v=v,_w_gravity(p.mu,p.j2,p.rg,r)[:3]
    k2r=_w_advance(v,k1v,half)
    k2v=_w_gravity(p.mu,p.j2,p.rg,_w_advance(r,k1r,half))[:3]
    k3r=_w_advance(v,k2v,half)
    k3v=_w_gravity(p.mu,p.j2,p.rg,_w_advance(r,k2r,half))[:3]
    k4r=_w_advance(v,k3v,delta)
    k4v=_w_gravity(p.mu,p.j2,p.rg,_w_advance(r,k3r,delta))[:3]
    rn=_w_advance(r,_w_average(k1r,k2r,k3r,k4r),delta)
    vn=_w_advance(v,_w_average(k1v,k2v,k3v,k4v),delta)
    if not any(rn):raise ValueError('RK4 endpoint reaches the singular gravity origin')
    _w_tick(p,'rk4_steps')
    return rn,vn

cdef void _w_reserve(TypedWorldPlan p,object forces,object controls) except *:
    w=p.provider.work;q=p.policy
    if w.force_reserved+forces>q.max_force_reservations or w.control_reserved+controls>q.max_control_units:
        raise ValueError('LIFECYCLE_ORBIT_QUOTA_BEFORE_WORK')
    if forces:
        if p.provider_charge is not None:p.provider_charge('nominal_force_reserved',forces)
        w.force_reserved+=forces
    if controls:
        if p.provider_charge is not None:p.provider_charge('nominal_control_units',controls)
        w.control_reserved+=controls

cdef void _w_unknown(TypedWorldPlan p,object error) except *:
    o=p.provider;o.failed=True;o.work.unknown_primitive_events+=1
    o.failure=(type(error).__name__+': '+str(error))[:512]
    if p.provider_charge is not None:
        try:p.provider_charge('nominal_unknown_events',1)
        except BaseException:o.failure+='; UNKNOWN_EVENT_PUBLICATION_FAILED'

cdef void _w_sync(TypedWorldPlan p) except *:
    o=p.provider;w=o.work;w.cache_records=len(o._grid_states)+len(o._tails)
    w.peak_cache_records=max(w.peak_cache_records,w.cache_records)

cdef object _w_floor(TypedWorldPlan p):
    return int((p.provider.retention_floor-Fraction(p.data['origin']))//Fraction(p.policy.step_seconds))

cdef void _w_evict(TypedWorldPlan p) except *:
    o=p.provider;low=min(o._high,max(o._low,_w_floor(p)))
    while o._low<low:
        del o._grid_states[o._low];o._low+=1;o.work.grid_evictions+=1

cdef object _w_at(TypedWorldPlan p,object seconds):
    seconds=_w_seconds(seconds);elapsed=float(seconds)
    if abs(Fraction(elapsed)-seconds)>Fraction(_w_ulp(elapsed))/2:
        raise ValueError('undeclared lifecycle nominal time rounding')
    key=Fraction(elapsed);origin=Fraction(p.data['origin']);o=p.provider;q=p.policy;w=o.work
    if not origin<=key<=origin+q.max_duration_seconds:raise ValueError('LIFECYCLE_ORBIT_DOMAIN')
    if key<o.retention_floor:raise ValueError('LIFECYCLE_ORBIT_SEED_EVICTED')
    full,remainder=divmod(key-origin,Fraction(q.step_seconds));full=int(full);tail=float(remainder)
    if Fraction(tail)!=remainder:raise ValueError('exact binary64 original-grid remainder required')
    if full<o._low:raise ValueError('LIFECYCLE_ORBIT_SEED_EVICTED')
    growth=max(0,full-o._high);tg=int(bool(tail)and key not in o._tails)
    if w.queries>=q.max_queries or growth+tg>q.max_steps_per_query:raise ValueError('LIFECYCLE_ORBIT_QUERY_QUOTA_BEFORE_WORK')
    final_low=min(full,max(o._low,_w_floor(p)))if growth else o._low
    if max(o._high,full)-final_low+1>q.max_retained_grid:raise ValueError('LIFECYCLE_ORBIT_RETAINED_SEED_CAPACITY_BEFORE_WORK')
    required=growth+tg
    if w.force_reserved+4*required>q.max_force_reservations or w.control_reserved+128+256*required>q.max_control_units:
        raise ValueError('LIFECYCLE_ORBIT_QUOTA_BEFORE_WORK')
    if p.provider_charge is not None:p.provider_charge('nominal_orbit_queries',1)
    w.queries+=1;_w_tick(p,'orbit_queries');_w_reserve(p,0,128)
    while o._high<full:
        _w_reserve(p,4,256)
        seed=o._grid_states[o._high]
        try:value=_w_rk4(p,seed[0],seed[1],q.step_seconds)
        except BaseException as error:_w_unknown(p,error);raise
        o._high+=1;o._grid_states[o._high]=value;w.full_steps+=1;w.force_completed+=4
        _w_evict(p);_w_sync(p)
    r,v=o._grid_states[full];w.cache_reads+=1
    if tail:
        if key in o._tails:r,v=o._tails[key];w.cache_reads+=1
        else:
            _w_reserve(p,4,256)
            try:r,v=_w_rk4(p,r,v,tail)
            except BaseException as error:_w_unknown(p,error);raise
            w.tail_steps+=1;w.force_completed+=4
            if q.max_tail_records:
                if len(o._tails)>=q.max_tail_records:
                    oldest=min(o._tails)
                    if key>oldest:del o._tails[oldest];w.tail_evictions+=1
                    else:oldest=None
                else:oldest=key
                if oldest is not None:o._tails[key]=(r,v)
            _w_sync(p)
    return r,v,elapsed

cdef void _w_pay(TypedWorldPlan p,object count) except *:
    s=p.source
    if type(count)is not int or not 0<=count<=2**48:raise ValueError('bounded exact integer required: world prospective control work')
    if s.controls+count>p.world.max_index_control_units:raise ValueError('LIFECYCLE_WORLD_CONTROL_QUOTA_BEFORE_WORK')
    if p.world_charge is not None:p.world_charge('index_control_units',count)
    s.controls+=count

cdef void _w_domain(TypedWorldPlan p,object a,object b) except *:
    a=_w_seconds(a);b=_w_seconds(b)
    if not p.world.start_seconds<=a<=b<=p.world.end_seconds:raise ValueError('exact in-domain lifecycle interval required')
    if a<p.source.retention_floor:raise ValueError('LIFECYCLE_WORLD_BEFORE_RETAINED_WINDOW')

cdef object _w_sun(TypedWorldPlan p,object elapsed):
    seconds=Fraction(elapsed);_w_domain(p,seconds,seconds);_w_pay(p,64)
    p.source.sun_queries+=1;_w_tick(p,'sun_queries');e=p.world
    if e.sun_table is not None:
        table=e.sun_table;t=elapsed
        if not table.domain_seconds[0]<=t<=table.domain_seconds[1]:raise ValueError('Sun query outside closed table domain')
        times=tuple(s.elapsed_seconds for s in table.samples);i=_w_right(times,t)-1;left=table.samples[i]
        if t==left.elapsed_seconds:xyz=left.position_m
        else:
            right=table.samples[i+1]
            weight=(Fraction(t)-Fraction(left.elapsed_seconds))/(Fraction(right.elapsed_seconds)-Fraction(left.elapsed_seconds))
            xyz=tuple(float((1-weight)*Fraction(a)+weight*Fraction(b))for a,b in zip(left.position_m,right.position_m))
        if not any(xyz):raise ValueError('geocentric Sun position must be nonzero')
    else:
        q=e.sun;phase=q.phase_at_anchor_rad+_w_tau*float((seconds-e.start_seconds)%Fraction(q.period_seconds))/q.period_seconds
        xyz=(q.distance_m*_w_cos(phase),q.distance_m*_w_cos(q.obliquity_rad)*_w_sin(phase),q.distance_m*_w_sin(q.obliquity_rad)*_w_sin(phase))
    if len(xyz)!=3 or any(type(x)not in(int,float)or not _w_finite(x)for x in xyz):raise ValueError('finite Sun position required')
    return tuple(float(x)for x in xyz)

cdef object _w_iadd(object x,object y):return x[0]+y[0],x[1]+y[1]
cdef object _w_imul(object x,object y):
    products=[a*b for a in x for b in y];return min(products),max(products)
cdef object _w_isquare(object x):
    return (Fraction(0)if x[0]<=0<=x[1]else min(x[0]**2,x[1]**2),max(x[0]**2,x[1]**2))

cdef object _w_nominal(TypedWorldPlan p,object r,object direction):
    ellipsoid=p.data['frame'].ellipsoid;a=Fraction(ellipsoid.equatorial_radius_m.value)
    b=a*(1-Fraction(ellipsoid.flattening.value));q=(1/a**2,1/a**2,1/b**2)
    d=tuple(Fraction(v)for v in direction);box=tuple((Fraction(x),Fraction(x))for x in r)
    A=sum(w*v*v for w,v in zip(q,d));B=(Fraction(0),Fraction(0));C=(Fraction(-1),Fraction(-1))
    for x,v,w in zip(box,d,q):B=_w_iadd(B,_w_imul(x,(v*w,v*w)));C=_w_iadd(C,_w_imul(_w_isquare(x),(w,w)))
    B2=_w_isquare(B);AC=_w_imul((A,A),C);D=(AC[0]-B2[1],AC[1]-B2[0])
    if C[0]<=0:return 'INVALID_POSITION'
    if B[0]>=0 or D[0]>0:return 'ILLUMINATED'
    return 'TANGENT'if D[0]==0 else'OCCULTED'

cdef object _w_light(TypedWorldPlan p,object index):
    s=p.source;e=p.world
    if index not in s._lighting:
        a=e.start_seconds+index*e.lighting_step_seconds;b=min(e.end_seconds,a+e.lighting_step_seconds);_w_domain(p,a,b)
        r,v,t=_w_at(p,(a+b)/2);sun=_w_sun(p,t);direction=tuple(x-y for x,y in zip(sun,r))
        if not any(direction)or any(not _w_finite(x)for x in direction):raise ValueError('direction must be nonzero and finite')
        assessment=_w_nominal(p,r,direction)
        if assessment=='TANGENT':assessment='UNRESOLVED'
        if assessment not in ('ILLUMINATED','OCCULTED','UNRESOLVED'):raise ValueError('LIFECYCLE_NOMINAL_LIGHTING_UNSUPPORTED:'+str(assessment))
        _w_pay(p,256);s.lighting_evaluations+=1;_w_tick(p,'lighting_samples')
        if len(s._lighting)>=e.max_lighting_records:
            oldest=min(s._lighting)
            if index>oldest:del s._lighting[oldest];s.lighting_evictions+=1
            else:return assessment
        s._lighting[index]=assessment;s.peak_lighting_records=max(s.peak_lighting_records,len(s._lighting))
    _w_pay(p,16);return s._lighting[index]

cdef object _w_schedule(TypedWorldPlan p,object a,object b):
    _w_domain(p,a,b);e=p.world;_w_pay(p,64);p.source.lookups+=1
    first=int((a-e.start_seconds)//e.lighting_step_seconds);last=int((b-e.start_seconds)//e.lighting_step_seconds)
    if last-first+1>e.max_schedule_cells+1:raise ValueError('LIFECYCLE_FORCING_CELL_CAPACITY_BEFORE_WORK')
    points={a,b}
    for cuts in (p.profile_cuts,p.table_cuts):points.update(cuts[_w_right(cuts,a):_w_left(cuts,b)])
    points.update(e.start_seconds+i*e.lighting_step_seconds for i in range(first+1,last+1)if a<e.start_seconds+i*e.lighting_step_seconds<b)
    ordered=sorted(points);pairs=tuple(zip(ordered,ordered[1:]))if a<b else((a,b),)
    if len(pairs)>e.max_schedule_cells:raise ValueError('LIFECYCLE_FORCING_CELL_CAPACITY_BEFORE_WORK')
    _w_pay(p,128*len(pairs));cells=[];total=_w_ceil((e.end_seconds-e.start_seconds)/e.lighting_step_seconds)
    for left,right in pairs:
        mid=(left+right)/2;profile=max(0,_w_right(p.profiles,mid)-1)
        index=min(total-1,int((mid-e.start_seconds)//e.lighting_step_seconds))
        cells.append((left,right,_w_light(p,index),index,profile))
    return tuple(cells)

cdef object _w_vector(object value):
    if type(value)is not tuple or len(value)!=3 or any(type(x)not in(int,float)or not _w_finite(x)for x in value):
        raise ValueError('three finite builtin direction coordinates required')
    norm=_w_hypot(*value)
    if norm==0:raise ValueError('zero direction')
    return tuple(float(x)/norm for x in value)

cdef object _w_quaternion(object value):
    if type(value)is not tuple or len(value)!=4 or any(type(x)is not float or not _w_finite(x)for x in value):raise ValueError('four finite builtin float quaternion components required')
    scale=max(abs(x)for x in value)
    if not 2**-200<=scale<=2**200:raise ValueError('quaternion norm outside bounded domain')
    q=tuple(x/scale for x in value)
    if next(x for x in q if x)!=abs(next(x for x in q if x)):q=tuple(-x for x in q)
    return tuple(0. if x==0 else x for x in q)

cdef object _w_matrix(object value):
    w,x,y,z=_w_quaternion(_w_quaternion(value));n=fsum(t*t for t in(w,x,y,z))
    return (((w*w+x*x-y*y-z*z)/n,2*(x*y-w*z)/n,2*(x*z+w*y)/n),
            (2*(x*y+w*z)/n,(w*w-x*x+y*y-z*z)/n,2*(y*z-w*x)/n),
            (2*(x*z-w*y)/n,2*(y*z+w*x)/n,(w*w-x*x-y*y+z*z)/n))

cdef object _w_direction(object matrix,object direction):
    return _w_vector(tuple(fsum(row[i]*direction[i]for i in range(3))for row in matrix))

cdef object _typed_support_points(TypedWorldPlan p,object a,object b):
    _enter(10);_w_guard(p);_w_tick(p,'support_attempts')
    cells=_w_schedule(p,_w_seconds(a),_w_seconds(b))
    if not cells or any(c[2]=='UNRESOLVED'for c in cells):
        from .long_mission import _Refusal
        raise _Refusal('UNRESOLVED_ILLUMINATION')
    points=tuple(sorted({a,b}|{x for c in cells for x in(c[0],c[1])}))
    _w_tick(p,'support_returned')
    return points

cdef object _typed_forcing_at(TypedWorldPlan p,object a,object b):
    _enter(10);_w_guard(p);_w_tick(p,'forcing_attempts')
    a=_w_seconds(a);b=_w_seconds(b);cells=_w_schedule(p,a,b)
    if not cells or any(c[2]=='UNRESOLVED'for c in cells):
        from .long_mission import _Refusal
        raise _Refusal('UNRESOLVED_ILLUMINATION')
    time=(a+b)/2;_w_domain(p,time,time)
    if p.world_charge is not None:p.world_charge('spatial_reserved_units',128)
    r,v,t=_w_at(p,time);sun=_w_sun(p,t);direction=_w_vector(tuple(x-y for x,y in zip(sun,r)))
    matrix=_w_matrix(p.quaternion);camera=_w_direction(matrix,p.camera);panel=_w_direction(matrix,p.panel)
    va,vb=_w_vector(panel),_w_vector(direction)
    incidence=_w_degrees(_w_acos(max(-1.,min(1.,fsum(x*y for x,y in zip(va,vb))))))
    cases=[]
    for cell in cells:
        data=p.profile_data[cell[4]];loads=list(data['loads']);loads[2]=loads[2]+0.;loads[3]=loads[3]+0.
        sunlit=cell[2]=='ILLUMINATED'
        external=tuple((n[2]if sunlit else 0,n[3],n[4])for n in data['nodes'])
        cases.append((sunlit,tuple(loads),external,tuple(n[0]for n in data['nodes']),
                      tuple(n[1]for n in data['nodes']),cell[4]))
    # Profile identity may change while its physical forcing is identical.
    if any(case[:5]!=cases[0][:5]for case in cases[1:]):raise ValueError('physical cut crosses forcing change')
    sunlit,loads,external,sinks,internal,profile=cases[0]
    result=dict(method='B64_COMPILED_CURRENT_WORLD_FORCING_V1',
        start=a,end=b,sunlit=sunlit,incidence=incidence,loads=loads,external_heat=external,sink_values=sinks,
        camera=camera,panel=panel,supports=tuple(c[3]for c in cells),quaternion=p.quaternion,
        profile_index=profile,forcing=None,eps=None)
    _w_tick(p,'forcing_returned')
    return WorldForcingData(result,p.token,_WORLD_DATA_FACTORY)

cdef object _typed_world_records(TypedWorldPlan p,object data):
    _w_guard(p)
    if type(data)is not WorldForcingData or (<WorldForcingData>data)._owner is not p.token:
        raise ValueError('B64 foreign saved forcing DATA')
    from .power_loads import PowerLoadBreakdown
    from .eps_system import EPSIntervalInputs
    from .thermal import ThermalIntervalInputs,ThermalNodeBoundaryInput
    from .thermal_coupling import ThermalHeatSourceInputs,ThermalNodeHeatSourceInput
    from .long_mission import LongMissionActionForcing
    loads=PowerLoadBreakdown(*data['loads']);sunlit=data['sunlit'];incidence=data['incidence']
    nodes=p.profile_data[data['profile_index']]['nodes']
    ordered=sorted(range(len(p.node_ids)),key=lambda i:p.node_ids[i].canonical)
    thermal=ThermalIntervalInputs(tuple(ThermalNodeBoundaryInput(p.node_ids[i],nodes[i][0])for i in ordered))
    heat=ThermalHeatSourceInputs(tuple(ThermalNodeHeatSourceInput(p.node_ids[i],nodes[i][1],
        nodes[i][2]if sunlit else 0,nodes[i][3],nodes[i][4])for i in ordered))
    eps=EPSIntervalInputs(sunlit,incidence,loads)
    forcing=LongMissionActionForcing(loads,sunlit,incidence,p.routing,thermal,heat)
    _w_tick(p,'materializations')
    return forcing,eps

cdef object _typed_prepare_world(object physical,object hardware,object pending):
    if (_world_admission_owner.admit_world_plan is not _world_admission_callable or
            _world_admission_callable.__code__ is not _world_admission_code or
            _world_admission_callable.__defaults__ is not _world_admission_defaults or
            _world_admission_callable.__kwdefaults__ is not _world_admission_kwdefaults or
            _world_admission_callable.__closure__ is not _world_admission_closure):
        raise ValueError('B64 compiled world admission callable drift')
    return TypedWorldPlan(_world_admission_callable(physical,hardware,pending),_WORLD_FACTORY)

def prepare_world(physical,hardware,pending):
    plan=_typed_prepare_world(physical,hardware,pending)
    plan.validate()
    return plan

def world_forcing(TypedWorldPlan plan,left,right):
    plan.validate()
    try:result=_typed_forcing_at(plan,left,right)
    except BaseException as primary:
        try:plan.validate()
        except BaseException as secondary:primary.add_note('B64 world exit guard: '+type(secondary).__name__+': '+str(secondary)[:1024])
        raise
    plan.validate()
    return result

def world_support_points(TypedWorldPlan plan,left,right):
    plan.validate()
    try:result=_typed_support_points(plan,left,right)
    except BaseException as primary:
        try:plan.validate()
        except BaseException as secondary:primary.add_note('B64 world exit guard: '+type(secondary).__name__+': '+str(secondary)[:1024])
        raise
    plan.validate()
    return result

def materialize_world_forcing(TypedWorldPlan plan,data):
    plan.validate()
    result=_typed_world_records(plan,data)
    plan.validate()
    return result

def materialize_world_forcings(TypedWorldPlan plan,data):
    """One selected batch boundary, no repeated immutable topology traversal."""
    plan.validate()
    if type(data)is not tuple or len(data)>65536:
        raise ValueError('B64 bounded exact selected forcing batch required')
    result=[]
    for item in data:result.append(_typed_world_records(plan,item))
    plan.validate()
    return tuple(result)
