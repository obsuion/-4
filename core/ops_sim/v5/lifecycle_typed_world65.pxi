# B65 machine storage with the exact Python math intrinsic barriers retained.
# No C libm, FMA, reassociation, approximate reciprocal or floating time decisions.
_w65_pow = pow

cdef double _w65_product(double a,double b) except *:
    cdef double value=a*b
    if not c_isfinite(value) or (value==0. and a!=0. and b!=0.):
        raise ValueError('RK4 product exceeds supported binary64 arithmetic')
    return value

cdef double _w65_sum(object terms) except *:
    cdef double value
    try:value=fsum(terms)
    except OverflowError as error:raise ValueError('RK4 sum exceeds finite binary64 arithmetic') from error
    if not c_isfinite(value):raise ValueError('RK4 sum must be finite')
    if value==0. and sum(map(Fraction,terms),Fraction())!=0:
        raise ValueError('nonzero RK4 sum underflows binary64')
    return value

cdef void _w65_advance(double* base,double* derivative,double delta,double* result) except *:
    cdef int i
    cdef double increment,value
    for i in range(3):
        increment=_w65_product(delta,derivative[i]);value=_w65_sum((base[i],increment))
        if increment!=0. and value==base[i]:raise ValueError('nonzero RK4 state increment is lost in binary64 addition')
        result[i]=value

cdef double _w65_qproduct(double* factors,int count,double radius,int power) except *:
    cdef int i,exponent=0,shift
    cdef double mantissa=1.,part,result,divisor
    # The short-circuit scan occurs before frexp, exactly as in the reference.
    for i in range(count):
        if factors[i]==0.:return 0.
    for i in range(count):
        part,shift=_w_frexp(factors[i]);mantissa=mantissa*part;exponent+=shift
    part,shift=_w_frexp(radius)
    # CPython float power retained. C pow or repeated multiplication would be
    # a different operation association on this numerical barrier.
    divisor=_w65_pow(part,power);mantissa=mantissa/divisor;exponent-=shift*power
    try:result=_w_ldexp(mantissa,exponent)
    except OverflowError as error:raise ValueError('gravity term exceeds finite binary64 arithmetic') from error
    if not c_isfinite(result)or result==0.:raise ValueError('nonzero gravity term is outside binary64 representation')
    return result

cdef double _w65_gsum(double first,double second) except *:
    cdef double result
    try:result=fsum((first,second))
    except OverflowError as error:raise ValueError('gravity output exceeds finite binary64 arithmetic') from error
    if not c_isfinite(result):raise ValueError('gravity output must be finite')
    return result

cdef void _w65_gravity(double mu,double j2,double rg,double* position,double* result) except *:
    cdef double radius,q,potential,pc,central[3],correction[3],factors[7]
    cdef int i
    radius=_w_hypot(position[0],position[1],position[2])
    if radius==0. or not c_isfinite(radius):raise ValueError('gravity requires a finite nonzero position norm')
    factors[0]=-mu
    for i in range(3):
        factors[1]=position[i];central[i]=_w65_qproduct(factors,2,radius,3)
    potential=_w65_qproduct(factors,1,radius,1)
    if j2==0.:
        for i in range(3):result[i]=central[i]
        result[3]=potential;return
    factors[0]=position[2];factors[1]=position[2];q=_w65_qproduct(factors,2,radius,2)
    factors[0]=1.5;factors[1]=mu;factors[2]=j2;factors[3]=rg;factors[4]=rg
    for i in range(3):
        factors[5]=position[i];factors[6]=5*q-(3 if i==2 else 1)
        correction[i]=_w65_qproduct(factors,7,radius,5)
    factors[0]=.5;factors[5]=3*q-1;pc=_w65_qproduct(factors,6,radius,3)
    for i in range(3):result[i]=_w65_gsum(central[i],correction[i])
    result[3]=_w65_gsum(potential,pc)

cdef void _w65_average(double* a,double* b,double* c,double* d,double* result) except *:
    cdef int i
    for i in range(3):
        result[i]=_w65_product(_w65_sum((a[i],_w65_product(2.,b[i]),_w65_product(2.,c[i]),d[i])),1./6.)

cdef object _w65_step(double mu,double j2,double rg,object r,object v,double delta,double scratch[24][4]):
    cdef int i
    cdef double half=_w65_product(delta,.5)
    for i in range(3):scratch[0][i]=r[i];scratch[1][i]=v[i];scratch[2][i]=v[i]
    # Rows 2/3,4/5,6/7,8/9 are k1..k4; 10/11 temporary states;
    # 12/13 averages and 14/15 endpoints. Scratch belongs to one plan/role.
    _w65_gravity(mu,j2,rg,scratch[0],scratch[3])
    _w65_advance(scratch[1],scratch[3],half,scratch[4])
    _w65_advance(scratch[0],scratch[2],half,scratch[10]);_w65_gravity(mu,j2,rg,scratch[10],scratch[5])
    _w65_advance(scratch[1],scratch[5],half,scratch[6])
    _w65_advance(scratch[0],scratch[4],half,scratch[10]);_w65_gravity(mu,j2,rg,scratch[10],scratch[7])
    _w65_advance(scratch[1],scratch[7],delta,scratch[8])
    _w65_advance(scratch[0],scratch[6],delta,scratch[10]);_w65_gravity(mu,j2,rg,scratch[10],scratch[9])
    _w65_average(scratch[2],scratch[4],scratch[6],scratch[8],scratch[12])
    _w65_average(scratch[3],scratch[5],scratch[7],scratch[9],scratch[13])
    _w65_advance(scratch[0],scratch[12],delta,scratch[14]);_w65_advance(scratch[1],scratch[13],delta,scratch[15])
    if scratch[14][0]==0. and scratch[14][1]==0. and scratch[14][2]==0.:raise ValueError('RK4 endpoint reaches the singular gravity origin')
    return (scratch[14][0],scratch[14][1],scratch[14][2]),(scratch[15][0],scratch[15][1],scratch[15][2])

def _b65_world_kernel(mu,j2,rg,r,v,delta):
    """Private differential fixture entry, not propagation/checkpoint authority."""
    cdef double scratch[24][4]
    if any(type(x)is not float or not _w_finite(x)for x in(mu,j2,rg,delta))or type(r)is not tuple or type(v)is not tuple or len(r)!=3 or len(v)!=3 or any(type(x)is not float or not _w_finite(x)for x in(*r,*v)):
        raise ValueError('B65 fixture exact finite binary64 domain')
    return _w65_step(mu,j2,rg,r,v,delta,scratch)
