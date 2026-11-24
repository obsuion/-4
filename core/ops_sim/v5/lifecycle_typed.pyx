# cython: language_level=3, infer_types=False, annotation_typing=False
# cython: boundscheck=True, wraparound=False, cdivision=False, overflowcheck=True, auto_pickle=False
"""B64 indexed binary64 coupled-cut owner.

Only exact arithmetic/clock/fee and Python-math intrinsic barriers cross into
Python inside the cut. No model/service/thermal callback is accepted. Static
and scratch arrays are private cdef storage and never exported by reference.
"""
from libc.stdint cimport uint64_t
from libc.math cimport isfinite as c_isfinite
from cpython.float cimport PyFloat_AS_DOUBLE
from fractions import Fraction
from math import fsum, sqrt, exp, nextafter, cos, radians
import sys
import os

from .design_trade_physics import ElectricalLimitError
from .battery_port import BatteryPortDomainError

_B65 = __name__ == 'ops_sim.v5._lifecycle_typed65'
METHOD = 'B65_TYPED_EXECUTION_V2' if _B65 else 'B64_TYPED_EXECUTION_V1'
ARITHMETIC = 'ORDERED_TYPED_BINARY64_WITH_EXACT_INTEGER_BARRIERS_V1'
_NAMES = ('service_port_substep', 'allocation_trial', 'electrical_line',
          'battery_port_transition', 'thermal_transition',
          'battery_degradation', 'solar_degradation', 'port_ageing',
          'quiet_interval', 'quiet_error_norm', 'world_forcing')
cdef uint64_t _counts[11]
cdef uint64_t _total = 0
cdef bint _exhausted = False
cdef uint64_t _limit = 72057594037927936

cdef void _enter(int i) except *:
    global _total, _exhausted
    if _exhausted or _total >= _limit or _counts[i] >= _limit:
        _exhausted = True
        raise ValueError('B64_TYPED_ENTRY_MONITOR_SATURATED')
    _total += 1
    _counts[i] += 1

def native_entry_counts():
    return dict(format='B65_MONOTONE_TYPED_ENTRY_COUNTS_V2' if _B65 else 'B64_MONOTONE_TYPED_ENTRY_COUNTS_V1',
        method='B65_TYPED_NUMERICAL_ENTRY_MONITOR_V2' if _B65 else 'B64_TYPED_NUMERICAL_ENTRY_MONITOR_V1', limit=2**56,
        total=int(_total), counts={n: int(_counts[i]) for i,n in enumerate(_NAMES)},
        exhausted=bool(_exhausted), gil_held=True, reset_available=False,
        python_implementation=sys.implementation.name,
        python_cache_tag=sys.implementation.cache_tag,
        python_version=sys.version, platform=sys.platform,
        module_basename=os.path.basename(__file__),
        source_binding='ACTUAL_EXTENSION_AND_SOURCE_BUILD_RECEIPT_REQUIRED',
        scope='OPERATIONAL_ENTRY_ATTEMPTS_NOT_SCIENTIFIC_WORK_OR_DYNAMIC_STATE')

def typed_capability():
    return dict(method=METHOD, arithmetic=ARITHMETIC,
        typed_contiguous_numeric_state=True, full_coupled=True,
        python_model_callbacks=False, python_model_callbacks_scope='COUPLED_CUT_AND_CLOSED_WORLD_QUIET_ONLY',
        quiet_interval_callback_free=True,
        scope='REQUIRES_BOUND_BUILD_RUNTIME_SOURCE_AND_FULL_SCIENTIFIC_EQUALITY',speedup='UNPROVEN',
        module_basename=os.path.basename(__file__),python_implementation=sys.implementation.name,
        python_cache_tag=sys.implementation.cache_tag,python_version=sys.version,platform=sys.platform,
        exact_integer_and_fraction=True, actual_math_fsum=True,
        direct_c_libm=False, changes_scientific_work=False, canary=sizeof(double)==8,
        limits=dict(nodes=64,links=256,branches=8,loads=7),
        capability_screen=dict(binary64_storage=sizeof(double)==8,
            indexed_arrays=True,ordered_arithmetic=True,exact_time_barrier=True,
            guarded_nonzero_underflow=True,independent_scratch=True,no_model_callbacks=True),
        entry_monitor=dict(method='B65_TYPED_NUMERICAL_ENTRY_MONITOR_V2' if _B65 else 'B64_TYPED_NUMERICAL_ENTRY_MONITOR_V1',
                           limit=2**56,names=_NAMES))

cdef double _finite(double value, object name) except *:
    if not c_isfinite(value):
        raise ValueError(str(name)+' cannot be represented as finite')
    return value

cdef double _mul(double a,double b,object name) except *:
    cdef double v=a*b
    _finite(v,name)
    if a != 0. and b != 0. and v == 0.:
        raise ValueError(str(name)+' cannot represent a nonzero product')
    return v

cdef double _div(double a,double b,object name) except *:
    cdef double v
    if b == 0.: raise ValueError(str(name)+' denominator must not be zero')
    v=a/b
    _finite(v,name)
    if a != 0. and v == 0.:
        raise ValueError(str(name)+' cannot represent a nonzero quotient')
    return v

cdef double _number(object value,object name) except *:
    # Arbitrary integers are not silently narrowed. Mixed binary64 inputs
    # admit exact conversion only; exact clocks/work never use this bridge.
    if type(value) is float:
        return _finite(PyFloat_AS_DOUBLE(value),name)
    if type(value) is int and -2**53 <= value <= 2**53:
        return float(value)
    raise ValueError('B64_TYPED_UNSUPPORTED_NUMERIC_DOMAIN:'+str(name))

cdef double _port_real(double v,object name,double lo=0.,double hi=1.e12) except *:
    if not c_isfinite(v) or v < lo or v > hi:
        raise BatteryPortDomainError('BATTERY_PORT_DOMAIN:'+str(name))
    return v

cdef struct Trial:
    double loads[7]
    double lines[8][8]
    double port[22]
    double source_generation
    double delivered_generation
    double receiving_load
    double source_load
    double pv_loss
    double wire_loss
    int reason
    bint near
    bint fully

cdef class IndexedStatic:
    cdef bint _initialized
    cdef bint _ready
    cdef int n,l,battery,bus,ocv_n,bisections
    cdef double capacity[64]
    cdef double area[64]
    cdef double emissivity[64]
    cdef double sink[64]
    cdef int link_a[256]
    cdef int link_b[256]
    cdef double conductance[256]
    cdef int branch_heat[8]
    cdef int receiving_order[7]
    cdef int priority[7]
    cdef int route[7]
    cdef double retained[7]
    cdef double resistance[8]
    cdef double current_limit[8]
    cdef double drop_limit[8]
    cdef double harness_mass[8]
    cdef double ocv_s[16]
    cdef double ocv_v[16]
    cdef double p[23]
    cdef double bus_voltage,pv_voltage,bus_limit,nominal_energy,nominal_solar
    cdef double charge_limit,discharge_limit,reference_temperature,calendar_rate,cycle_rate,calendar_activation,cycle_activation
    cdef object metadata
    cdef object static_pins
    cdef object port_policy

    def __init__(self, object data):
        cdef int i,j
        if type(self)is not IndexedStatic:raise TypeError('B64 exact indexed static owner required')
        if self._initialized:raise TypeError('B64 indexed static authority cannot be reinitialized')
        self._initialized=True
        if type(data) is not dict: raise TypeError('B64 exact indexed input DATA')
        required={'nodes','links','branches','receiving_order','priority','routes','ocv','port',
                  'bus_voltage','pv_voltage','bus_limit','nominal_energy','nominal_solar',
                  'charge_limit','discharge_limit','reference_temperature','calendar_rate',
                  'cycle_rate','calendar_activation','cycle_activation','bisections',
                  'battery_index','bus_index','metadata','static_pins','port_policy'}
        if set(data)!=required: raise ValueError('B64 exact indexed input fields')
        nodes=data['nodes']; links=data['links']; branches=data['branches']; routes=data['routes']
        if (type(nodes)is not tuple or not 1<=len(nodes)<=64 or type(links)is not tuple or len(links)>256 or
                type(branches)is not tuple or len(branches)!=8 or type(routes)is not tuple or len(routes)!=7):
            raise ValueError('B64 typed topology capacity')
        self.n=len(nodes);self.l=len(links)
        self.battery=data['battery_index'];self.bus=data['bus_index']
        if (type(data['battery_index'])is not int or type(data['bus_index'])is not int or
                not 0<=self.battery<self.n or not 0<=self.bus<self.n):
            raise ValueError('B64 typed battery/bus index')
        for i in range(self.n):
            if type(nodes[i])is not tuple or len(nodes[i])!=4:raise ValueError('B64 typed node row')
            self.capacity[i]=_number(nodes[i][0],'capacity')
            self.area[i]=_number(nodes[i][1],'area')
            self.emissivity[i]=_number(nodes[i][2],'emissivity')
            self.sink[i]=_number(nodes[i][3],'sink')
            if self.capacity[i]<=0 or self.area[i]<0 or not 0<=self.emissivity[i]<=1 or self.sink[i]<=0:raise ValueError('B64 typed node domain')
        for i in range(self.l):
            if type(links[i])is not tuple or len(links[i])!=3:raise ValueError('B64 typed link row')
            a,b,g=links[i]
            if type(a)is not int or type(b)is not int or not 0<=a<self.n or not 0<=b<self.n or a==b:raise ValueError('B64 typed link endpoint')
            self.link_a[i]=a;self.link_b[i]=b;self.conductance[i]=_number(g,'conductance')
            if self.conductance[i]<0:raise ValueError('B64 typed conductance')
        for i in range(8):
            row=branches[i]
            if type(row)is not tuple or len(row)!=5:raise ValueError('B64 typed branch row')
            self.resistance[i]=_number(row[0],'wire resistance');self.current_limit[i]=_number(row[1],'wire current limit')
            self.drop_limit[i]=_number(row[2],'wire drop limit');self.harness_mass[i]=_number(row[3],'wire mass')
            if self.resistance[i]<0 or self.current_limit[i]<=0 or self.drop_limit[i]<0 or self.harness_mass[i]<0:
                raise ValueError('B64 typed wire domain')
            if type(row[4])is not int or not 0<=row[4]<self.n:raise ValueError('B64 typed branch heat index')
            self.branch_heat[i]=row[4]
        for name in ('receiving_order','priority'):
            order=data[name]
            if type(order)is not tuple or sorted(order)!=list(range(7)) or any(type(x)is not int for x in order):raise ValueError('B64 exact load ordering')
        for i in range(7):
            self.receiving_order[i]=data['receiving_order'][i];self.priority[i]=data['priority'][i]
            row=routes[i]
            if type(row)is not tuple or len(row)!=2 or type(row[0])is not int or not 0<=row[0]<self.n:raise ValueError('B64 route index')
            self.route[i]=row[0];self.retained[i]=_number(row[1],'retained heat fraction')
            if not 0<=self.retained[i]<=1:raise ValueError('B64 typed retained heat domain')
        curve=data['ocv'];self.ocv_n=len(curve)
        if type(curve)is not tuple or not 2<=self.ocv_n<=16:raise ValueError('B64 OCV shape')
        for i in range(self.ocv_n):self.ocv_s[i]=_number(curve[i][0],'OCV fraction');self.ocv_v[i]=_number(curve[i][1],'OCV V')
        if type(data['port'])is not tuple or len(data['port'])!=23:raise ValueError('B64 port constants')
        for i in range(23):self.p[i]=_number(data['port'][i],'port constant')
        self.bus_voltage=_number(data['bus_voltage'],'bus V');self.pv_voltage=_number(data['pv_voltage'],'PV V');self.bus_limit=_number(data['bus_limit'],'bus I')
        if self.bus_voltage<=0 or self.pv_voltage<=0 or self.bus_limit<=0:raise ValueError('B64 typed positive bus domain')
        self.nominal_energy=_number(data['nominal_energy'],'nominal Wh');self.nominal_solar=_number(data['nominal_solar'],'nominal solar W')
        self.charge_limit=_number(data['charge_limit'],'charge bus W');self.discharge_limit=_number(data['discharge_limit'],'discharge bus W')
        self.reference_temperature=_number(data['reference_temperature'],'ageing reference K')
        self.calendar_rate=_number(data['calendar_rate'],'calendar rate');self.cycle_rate=_number(data['cycle_rate'],'cycle rate')
        self.calendar_activation=_number(data['calendar_activation'],'calendar activation');self.cycle_activation=_number(data['cycle_activation'],'cycle activation')
        if type(data['bisections'])is not int or data['bisections']!=32:raise ValueError('B64 fixed allocation grid')
        self.bisections=32;self.metadata=data['metadata'];self.static_pins=data['static_pins'];self.port_policy=data['port_policy']
        self._ready=True

    def shape(self):
        _require_static_ready(self)
        return dict(nodes=self.n,links=self.l,branches=8,loads=7,storage='PRIVATE_C_DOUBLE_ARRAYS')

cdef void _require_static_ready(IndexedStatic model) except *:
    if type(model)is not IndexedStatic or not model._ready:
        raise TypeError('B64 indexed static authority is not initialized')

cdef class TypedDynamic:
    cdef double energy,retention,throughput,solar,damage,weighted,chemical,ohmic,converter
    cdef double t[64]
    cdef object exact
    cdef object owner
    def __init__(self, IndexedStatic owner, object data):
        cdef int i
        _require_static_ready(owner)
        if type(data)is not dict or set(data)!={'energy','temperatures','retention','throughput','solar','damage','weighted','chemical','ohmic','converter','exact'}:
            raise ValueError('B64 exact dynamic DATA shape')
        if type(data['temperatures'])is not tuple or len(data['temperatures'])!=owner.n:raise ValueError('B64 dynamic temperature shape')
        self.owner=owner;self.energy=_number(data['energy'],'energy');self.retention=_number(data['retention'],'retention')
        self.throughput=_number(data['throughput'],'throughput');self.solar=_number(data['solar'],'solar retention')
        self.damage=_number(data['damage'],'port damage');self.weighted=_number(data['weighted'],'weighted seconds')
        self.chemical=_number(data['chemical'],'chemical Wh');self.ohmic=_number(data['ohmic'],'Ohm Wh');self.converter=_number(data['converter'],'converter Wh')
        for name in ('damage','weighted','chemical','ohmic','converter'):
            if type(data[name])is not float or not 0<=data[name]<=1.e12:
                raise BatteryPortDomainError('BATTERY_PORT_STATE_TYPE' if type(data[name])is not float else 'BATTERY_PORT_DOMAIN:'+name)
        for i in range(owner.n):
            if type(data['temperatures'][i])is not float:
                raise ValueError('B64_TYPED_UNSUPPORTED_NUMERIC_DOMAIN:binary64 temperature state')
            self.t[i]=_number(data['temperatures'][i],'temperature')
            if self.t[i]<=0:raise ValueError('B64 positive dynamic temperature')
        if self.energy<0 or not 0<self.retention<=1 or not 0<self.solar<=1:raise ValueError('B64 dynamic energy/retention')
        exact=data['exact']
        if (type(exact)is not tuple or len(exact)!=2 or type(exact[0])is not Fraction or
                exact[0]<0 or exact[0].denominator.bit_length()>4096):
            raise BatteryPortDomainError('BATTERY_PORT_STATE_CLOCK')
        if type(exact[1])is not int or not 0<=exact[1]<=2**40:raise BatteryPortDomainError('BATTERY_PORT_STATE_STEPS')
        self.exact=exact
    def snapshot(self):
        cdef IndexedStatic m=self.owner
        return dict(energy=self.energy,temperatures=tuple(self.t[i] for i in range(m.n)),
            retention=self.retention,throughput=self.throughput,solar=self.solar,damage=self.damage,
            weighted=self.weighted,chemical=self.chemical,ohmic=self.ohmic,converter=self.converter,exact=self.exact)

cdef void _line(IndexedStatic m,int b,double voltage,double power,bint generated,double *out) except *:
    cdef double current,discriminant,loss,drop,source,delivered,root
    _enter(2)
    if voltage<=0 or power<0 or not c_isfinite(power):raise ValueError('B64 finite nonnegative wire power')
    if generated:
        current=_finite(power/voltage,'line current')
        loss=_finite(current*current*m.resistance[b],'wire loss')
        source=power;delivered=power-loss
    else:
        if power==0 or m.resistance[b]==0:current=power/voltage
        else:
            discriminant=_finite(voltage*voltage-4*m.resistance[b]*power,'circuit discriminant')
            if discriminant<=0:raise ElectricalLimitError('constant-power circuit has no stable low-current root')
            root=sqrt(discriminant)
            current=_finite(2*power/(voltage+root),'line current')
        loss=_finite(current*current*m.resistance[b],'wire loss')
        source=_finite(power+loss,'source power');delivered=power
    drop=_finite(current*m.resistance[b],'voltage drop')
    loss=_finite(current*drop,'wire loss')
    if current>m.current_limit[b]:raise ElectricalLimitError('wire current limit exceeded')
    if drop>m.drop_limit[b]:raise ElectricalLimitError('wire voltage-drop limit exceeded')
    if drop>=voltage:raise ElectricalLimitError('receiving voltage is nonpositive')
    out[0]=current;out[1]=drop;out[2]=loss;out[3]=source;out[4]=delivered;out[5]=voltage-drop;out[6]=m.resistance[b];out[7]=m.harness_mass[b]

cdef void _port(IndexedStatic m,TypedDynamic d,double gen,double load,double dt,double usable,Trial *r) except *:
    cdef double e=d.energy,t=d.t[m.battery],voc=0.,resistance,s,exponent,a,b,va,vb
    cdef double needed,eta,ilim,chemical_limit,imax,terminal_cap,bus_cap,cap_w,proposed,pterminal,disc,current,vt,chemical,delta,end,heat,conv,ohm_wh,conv_wh,unmet,root,square_value,exp_value
    cdef bint charging,in_window,available,boundary
    cdef int i,reason
    _enter(3)
    _port_real(usable,'usable Wh',1.e-12);_port_real(e,'stored Wh',0.,usable)
    _port_real(t,'temperature K',m.p[11],m.p[12]);_port_real(gen,'generation W');_port_real(load,'load W')
    if d.damage>m.p[6]:raise BatteryPortDomainError('BATTERY_PORT_DAMAGE_DOMAIN')
    s=e/usable
    for i in range(m.ocv_n-1):
        if s<=m.ocv_s[i+1]:
            a=m.ocv_s[i];b=m.ocv_s[i+1];va=m.ocv_v[i];vb=m.ocv_v[i+1]
            voc=va+(vb-va)*((s-a)/(b-a));break
    voc+=m.p[0]*(t-m.p[1]);exponent=m.p[3]*(m.p[1]-t)
    if abs(exponent)>32:raise BatteryPortDomainError('BATTERY_PORT_EXPONENT_DOMAIN')
    # Python pow/exp bridges retain Python float exponentiation/libm behavior.
    square_input=float(1-s)
    square=square_input**2
    square_value=square;exp_value=exp(exponent)
    resistance=m.p[2]*(1+d.damage)*(1+m.p[4]*square_value)*exp_value
    _port_real(voc,'derived Voc',1.e-12,100.);_port_real(resistance,'derived R',0.,100.)
    charging=gen>=load;needed=abs(gen-load);eta=m.p[20] if charging else m.p[19]
    ilim=m.p[16] if charging else m.p[15]
    chemical_limit=((usable-e) if charging else e)*3600/dt
    imax=min(ilim,chemical_limit/voc);in_window=m.p[13]<=voc<=m.p[14]
    if not in_window:imax=0.
    if resistance:
        if in_window:
            if charging:imax=min(imax,(m.p[14]-voc)/resistance)
            else:imax=min(imax,min(voc/(2*resistance),(voc-m.p[13])/resistance))
        else:imax=0.
    terminal_cap=imax*(voc+(imax*resistance if charging else -imax*resistance))
    bus_cap=terminal_cap/eta if charging else terminal_cap*eta
    cap_w=min(m.charge_limit,m.p[18]) if charging else min(m.discharge_limit,m.p[17])
    proposed=min(needed,cap_w,bus_cap);reason=0 if proposed==needed else 1
    for i in range(9):
        pterminal=proposed*eta if charging else proposed/eta
        disc=voc*voc+(4*resistance*pterminal if charging else -4*resistance*pterminal)
        if not c_isfinite(disc):raise BatteryPortDomainError('BATTERY_PORT_DISCRIMINANT_OVERFLOW')
        boundary=disc<=0
        if disc<0:
            current=0.;vt=voc;available=False
        else:
            if resistance==0:current=pterminal/voc
            else:
                root=sqrt(disc);current=2*pterminal/(voc+root)
            vt=voc+(current*resistance if charging else -current*resistance)
            if not c_isfinite(current)or not c_isfinite(vt):raise BatteryPortDomainError('BATTERY_PORT_SOLUTION_OVERFLOW')
            available=current<=ilim and ((m.p[13] if proposed else min(voc,m.p[13]))<=vt<=(m.p[14] if proposed else max(voc,m.p[14])))
        chemical=voc*abs(current);delta=chemical*dt/3600
        end=e+delta if charging else e-delta
        if available and 0<=end<=usable:break
        if i==8:raise BatteryPortDomainError('BATTERY_PORT_FEASIBILITY_ROUNDING_UNAVAILABLE')
        proposed=nextafter(proposed,0.);reason=2
    heat=current*current*resistance;conv=proposed-pterminal if charging else pterminal-proposed
    ohm_wh=heat*dt/3600;conv_wh=conv*dt/3600;unmet=0. if charging else needed-proposed
    r.port[0]=dt;r.port[1]=e;r.port[2]=end;r.port[3]=gen;r.port[4]=load;r.port[5]=load-unmet;r.port[6]=unmet
    r.port[7]=proposed if charging else 0.;r.port[8]=0. if charging else proposed;r.port[9]=needed-proposed if charging else 0.
    r.port[10]=ohm_wh+conv_wh;r.port[11]=ohm_wh;r.port[12]=conv_wh;r.port[13]=delta
    r.port[14]=chemical if charging else 0.;r.port[15]=0. if charging else chemical
    r.port[16]=voc;r.port[17]=resistance;r.port[18]=-current if charging else current;r.port[19]=vt;r.port[20]=disc
    r.port[21]=0.;r.reason=reason
    r.near=boundary or proposed<needed or (proposed>0 and min(vt-m.p[13],m.p[14]-vt)<.2) or ilim-current<.05

cdef void _trial(IndexedStatic m,TypedDynamic d,double *loads,double generation,double dt,double usable,
                 object service_work,object port_work,object wire_work,object limits,bint bisect,Trial *out) except *:
    cdef int i,b,f
    cdef object currents=[],sources=[],losses=[]
    _enter(1);service_work.reserve(bisection=bool(bisect))
    try:
        if wire_work is not None:wire_work.reserve_lines(8,limits)
        try:_line(m,0,m.pv_voltage,generation,True,&out.lines[0][0])
        except ElectricalLimitError:
            if wire_work is not None:wire_work.line_calls_refused+=1
            raise
        except BaseException:
            if wire_work is not None:wire_work.line_work_unknown+=1
            raise
        if wire_work is not None:wire_work.line_calls_returned+=1
        for i in range(7):
            f=m.receiving_order[i];b=i+1
            try:_line(m,b,m.bus_voltage,loads[f],False,&out.lines[b][0])
            except ElectricalLimitError:
                if wire_work is not None:wire_work.line_calls_refused+=1
                raise
            except BaseException:
                if wire_work is not None:wire_work.line_work_unknown+=1
                raise
            if wire_work is not None:wire_work.line_calls_returned+=1
            currents.append(out.lines[b][0]);sources.append(out.lines[b][3]);losses.append(out.lines[b][2])
        current=fsum(currents)
        if not c_isfinite(current)or current>m.bus_limit:raise ElectricalLimitError('aggregate regulated bus current limit exceeded')
        out.source_load=fsum(sources);out.wire_loss=fsum(losses)
        port_work.reserve()
        try:_port(m,d,out.lines[0][4],out.source_load,dt,usable,out)
        except BatteryPortDomainError:port_work.refused+=1;raise
        except BaseException:port_work.unknown+=1;raise
        port_work.returned+=1
        for i in range(7):out.loads[i]=loads[i]
        out.source_generation=generation;out.delivered_generation=out.lines[0][4]
        out.receiving_load=sum([loads[i] for i in range(7)])
        out.pv_loss=out.lines[0][2];out.fully=out.port[6]==0
    except ElectricalLimitError:service_work.eps_calls_refused+=1;raise
    except BaseException:service_work.eps_work_unknown+=1;raise
    service_work.eps_calls_returned+=1

cdef object _trial_data(Trial *r):
    cdef int i,j
    cdef object loads=[],lines=[],port=[],row
    for i in range(7):loads.append(r.loads[i])
    for i in range(8):
        row=[]
        for j in range(8):row.append(r.lines[i][j])
        lines.append(tuple(row))
    for i in range(21):port.append(r.port[i])
    return dict(loads=tuple(loads),lines=tuple(lines),
        port=tuple(port),reason=('AVAILABLE','CURRENT_VOLTAGE_OR_ENERGY_LIMIT','DIRECTED_FEASIBILITY_ROUNDING')[r.reason],
        near=bool(r.near),fully_served=bool(r.fully),source_generation_w=r.source_generation,
        delivered_generation_w=r.delivered_generation,receiving_load_w=r.receiving_load,
        source_load_w=r.source_load,pv_wire_loss_w=r.pv_loss,receiving_wire_loss_w=r.wire_loss)

cdef double _acceleration(double temperature,double reference,double activation) except *:
    cdef double inverse,inverse_reference,difference,ratio,magnitude,exponent,result
    if activation==0 or temperature==reference:return 1.
    inverse=_div(1.,temperature,'inverse temperature');inverse_reference=_div(1.,reference,'inverse reference temperature')
    difference=_finite(inverse-inverse_reference,'inverse-temperature difference')
    ratio=_div(activation,8.31446261815324,'activation-energy ratio')
    magnitude=_mul(ratio,difference,'Arrhenius exponent');exponent=_mul(-1.,magnitude,'Arrhenius exponent')
    try:result=exp(exponent)
    except (OverflowError,TypeError,ValueError) as error:raise ValueError('temperature acceleration cannot be represented as finite') from error
    _finite(result,'temperature acceleration')
    if result<=0:raise ValueError('temperature acceleration cannot be represented as positive')
    return result

cdef object _coupled_cut(IndexedStatic m,TypedDynamic d,object boundary,object service_work,object port_work,object wire_work,object limits):
    """One complete private allocation and coupled cut; no state publication.

    Boundary DATA is prepared by the explicit typed-state adapter. Full and
    selected electrical results are materialized only after trial selection.
    """
    cdef double desired[7],commanded[7],served[7],probe[7]
    cdef double temp[64],conductive[64],routed[64],wire[64],applied[64],eps[64],g[256],newt[64]
    cdef double thermal[64][8],flows[256],dt,usable,solar_nominal,generation,incidence,incidence_factor
    cdef double requested,low,high,midpoint,best,smallest,essential_unserved,combined,value,diff,flow,radiative,exchange,net,delta,representative
    cdef double charge,discharge,increment,calendar_acc,cycle_acc,calendar_damage,normalized,cycle_damage,total_damage,end_retention,end_throughput,end_capacity,unavailable,end_energy,end_solar,exponent,acceleration,damage
    cdef int i,j,k,a,b,f
    cdef object entry_trials
    cdef bint served_reuse[7]
    cdef bint full_valid=False,available,below=False,full_service,essential_full,radio
    cdef Trial full,selected,attempt
    cdef object initial_refusal=None
    _enter(0)
    if d.owner is not m:raise ValueError('B64 foreign typed dynamic owner')
    if type(boundary)is not dict:raise TypeError('B64 exact coupled boundary')
    start,end,duration=boundary['start'],boundary['end'],boundary['duration']
    if type(start)is not Fraction or type(end)is not Fraction or end<=start:raise ValueError('B64 exact coupled support')
    from .integration_time import checked_duration,RationalSeconds
    if type(duration)is not RationalSeconds or duration.fraction!=end-start:raise ValueError('B64 exact coupled duration')
    dt=checked_duration(duration)
    mode=boundary['mode']
    if type(mode)is not str or mode not in ('NORMAL','SAFE','POWER_OFF','RECOVERY'):raise ValueError('known construction service mode required')
    service_work.validate();port_work.validate()
    if wire_work is not None:wire_work.validate(limits)
    for i in range(7):
        desired[i]=_number(boundary['loads'][i],'desired W')
        if desired[i]<0:raise ValueError('nonnegative desired W')
        commanded[i]=desired[i] if mode=='NORMAL' or i in (0,4) else 0.
    # Actual dataclass field indices are passed explicitly by preparation.
    essential=boundary['essential_indices']
    for i in range(7):
        if mode!='NORMAL':commanded[i]=desired[i] if i in essential else 0.
    if fsum([desired[i] for i in essential])<=0:raise ValueError('positive authored essential demand required')
    usable=_mul(m.nominal_energy,d.retention,'battery usable capacity')
    solar_nominal=_mul(m.nominal_solar,d.solar,'solar nominal generation capability')
    incidence=_number(boundary['incidence'],'incidence')
    if not 0<=incidence<=180 or type(boundary['sunlit'])is not bool:raise ValueError('B64 illumination domain')
    incidence_factor=0. if incidence>=90 else cos(radians(incidence))
    generation=solar_nominal*(1. if boundary['sunlit'] else 0.)*incidence_factor
    entry_trials=service_work.allocation_trials
    try:
        _trial(m,d,&commanded[0],generation,dt,usable,service_work,port_work,wire_work,limits,False,&full)
        full_valid=True
    except ElectricalLimitError as error:initial_refusal=str(error)
    if full_valid and full.fully:
        selected=full
        for i in range(7):served[i]=commanded[i];served_reuse[i]=True
    else:
        for i in range(7):served[i]=0.;served_reuse[i]=False
        try:_trial(m,d,&served[0],generation,dt,usable,service_work,port_work,wire_work,limits,False,&selected)
        except ElectricalLimitError as error:
            # Materialization adapter builds the original bounded failure diagnostic.
            raise CoupledElectricalRefusal(str(error),None if not full_valid else _trial_data(&full),service_work.allocation_trials-entry_trials) from error
        if not selected.fully:raise ValueError('zero receiving load failed EPS admission')
        available=not(selected.delivered_generation==0 and d.energy==0)
        quanta=[commanded[i]/(2**m.bisections) for i in range(7) if commanded[i]>0]
        below=full_valid and bool(quanta) and min(quanta)>0 and full.port[5]<min(quanta)
        if below:available=False
        if available:
            for k in range(7):
                f=m.priority[k];requested=commanded[f]
                if requested==0:continue
                for i in range(7):probe[i]=served[i]
                probe[f]=requested
                try:
                    if service_work.allocation_trials-entry_trials>=233:raise ValueError('CONSTRUCTION_SERVICE_LOCAL_TRIAL_QUOTA')
                    _trial(m,d,&probe[0],generation,dt,usable,service_work,port_work,wire_work,limits,False,&attempt)
                    ok=bool(attempt.fully)
                except ElectricalLimitError:ok=False
                if ok:
                    selected=attempt;served[f]=requested;served_reuse[f]=True;continue
                low=0.;high=requested;best=served[f]
                for j in range(m.bisections):
                    midpoint=low+(high-low)/2
                    if midpoint==low or midpoint==high:break
                    for i in range(7):probe[i]=served[i]
                    probe[f]=midpoint
                    try:
                        if service_work.allocation_trials-entry_trials>=233:raise ValueError('CONSTRUCTION_SERVICE_LOCAL_TRIAL_QUOTA')
                        _trial(m,d,&probe[0],generation,dt,usable,service_work,port_work,wire_work,limits,True,&attempt)
                        ok=bool(attempt.fully)
                    except ElectricalLimitError:ok=False
                    if ok:low=midpoint;best=midpoint;selected=attempt
                    else:high=midpoint
                served[f]=best;served_reuse[f]=False
    essential_unserved=fsum([commanded[i]-served[i] for i in essential])
    essential_full=all(commanded[i]==served[i] for i in essential)
    full_service=all(commanded[i]==served[i] for i in range(7))
    radio=mode=='NORMAL' and essential_full and commanded[boundary['communications_index']]==served[boundary['communications_index']]
    for i in range(m.n):
        temp[i]=d.t[i];conductive[i]=0.;routed[i]=0.
        eps[i]=_number(boundary['emissivity'][i],'effective emissivity')
        wire[i]=fsum([selected.lines[j][2] for j in range(8) if m.branch_heat[j]==i])
    # Routing uses sequential component order, not fsum or reordered nodes.
    for i in range(7):
        value=_mul(served[i],m.retained[i],'retained heat')
        routed[m.route[i]]=_finite(routed[m.route[i]]+value,'node internal heat')
    adjustments=boundary['adjustments']
    if any(_number(x,'mechanical heat')!=0 for x in adjustments) and (mode!='NORMAL' or not full_service):
        failure_data=dict(full=None if not full_valid else _trial_data(&full),selected=_trial_data(&selected),
            served=tuple(served[i] for i in range(7)),served_reuse=tuple(bool(served_reuse[i]) for i in range(7)),
            shed=fsum([desired[i]-commanded[i] for i in range(7)]),essential_unserved=essential_unserved,
            essential_full=bool(essential_full),full_service=bool(full_service),radio=bool(radio),
            initial_refusal=initial_refusal,trials=service_work.allocation_trials-entry_trials,mode=mode)
        raise CoupledDomainRefusal('UNSUPPORTED_UNPOWERED_MECHANICAL_TRANSITION',failure_data)
    ledgers=[]
    for i in range(m.n):
        combined=routed[i]+wire[i]+_number(adjustments[i],'mechanical heat')
        if not c_isfinite(combined)or combined<0:raise ValueError('finite nonnegative combined heat required')
        irreversible=selected.port[11]*3600/dt if i==m.battery else 0.
        if i==m.bus:irreversible+=selected.port[12]*3600/dt
        values=(combined,*boundary['external_heat'][i],irreversible)
        # Old thermal ledger starts at exact int zero, then follows tuple order.
        total=0
        for value_object in values:total+=value_object
        applied[i]=_number(total,'total applied heat')
        ledgers.append((*values,total))
    _enter(4)
    for i in range(m.l):
        a=m.link_a[i];b=m.link_b[i];g[i]=_number(boundary['conductance'][i],'effective conductance')
        diff=_finite(temp[a]-temp[b],'temperature difference')
        flow=_mul(g[i],diff,'conductive heat flow')
        conductive[a]=_finite(conductive[a]-flow,'conductive heat into')
        conductive[b]=_finite(conductive[b]+flow,'conductive heat into');flows[i]=flow
    for i in range(m.n):
        # Python's float **4 is intentionally a narrow intrinsic bridge.
        sink4=boundary['sink_values'][i]**4
        node4=boundary['start_temperature_values'][i]**4
        if not c_isfinite(float(sink4))or not c_isfinite(float(node4)):raise ValueError('thermal fourth power cannot be represented as finite')
        if boundary['sink_values'][i]!=0 and sink4==0 or boundary['start_temperature_values'][i]!=0 and node4==0:raise ValueError('thermal fourth power cannot represent a positive value')
        power_difference=sink4-node4
        diff=float(power_difference)
        _finite(diff,'radiative fourth-power difference')
        radiative=_mul(_mul(_mul(eps[i],5.670374419e-8,'radiative heat'),m.area[i],'radiative heat'),diff,'radiative heat')
        exchange=_finite(conductive[i]+radiative,'net heat');net=_finite(exchange+applied[i],'net heat')
        delta=_mul(net,dt,'thermal energy change');value=_div(delta,m.capacity[i],'temperature change')
        newt[i]=_finite(temp[i]+value,'end temperature')
        if newt[i]<=0:raise ValueError('end temperature must be greater than zero')
        thermal[i][0]=temp[i];thermal[i][1]=newt[i];thermal[i][2]=conductive[i];thermal[i][3]=radiative
        thermal[i][4]=applied[i];thermal[i][5]=net;thermal[i][6]=delta
    representative=temp[m.battery]+(newt[m.battery]-temp[m.battery])/2
    charge=selected.port[14]*dt/3600;discharge=selected.port[15]*dt/3600;increment=charge+discharge
    _enter(5)
    calendar_acc=_acceleration(representative,m.reference_temperature,m.calendar_activation)
    cycle_acc=_acceleration(representative,m.reference_temperature,m.cycle_activation)
    calendar_damage=_mul(_mul(m.calendar_rate,calendar_acc,'calendar_damage'),dt,'calendar_damage')
    normalized=_div(increment,m.nominal_energy,'normalized_energy_throughput')
    cycle_damage=_mul(_mul(m.cycle_rate,cycle_acc,'cycling_damage'),normalized,'cycling_damage')
    total_damage=_finite(calendar_damage+cycle_damage,'total_damage')
    end_retention=_finite(d.retention-total_damage,'end_usable_capacity_retention')
    if end_retention<=0:raise ValueError('battery degradation candidate retention must be greater than zero')
    end_throughput=_finite(d.throughput+increment,'end_cumulative_energy_throughput_wh')
    end_capacity=_mul(m.nominal_energy,end_retention,'battery usable capacity')
    if selected.port[2]<=end_capacity:unavailable=0.;end_energy=selected.port[2]
    else:unavailable=_finite(selected.port[2]-end_capacity,'unavailable_energy_wh');end_energy=end_capacity
    end_solar=d.solar
    if boundary['solar_loss'] is not None:
        _enter(6);end_solar=_finite(d.solar-_number(boundary['solar_loss'],'solar retention loss'),'end_generation_retention')
        if end_solar<=0:raise ValueError('solar degradation candidate retention must be greater than zero')
    _enter(7);port_work.reserve(ageing=True)
    try:
        _port_real(representative,'ageing K',m.p[11],m.p[12])
        exponent=m.p[10]*(representative-m.p[1])
        if abs(exponent)>32:raise BatteryPortDomainError('BATTERY_PORT_AGEING_EXPONENT_DOMAIN')
        acceleration=exp(exponent)
        damage=d.damage+acceleration*(m.p[8]*dt+m.p[9]*selected.port[13])
        if not c_isfinite(damage)or damage>m.p[6]:raise BatteryPortDomainError('BATTERY_PORT_ACCUMULATED_DAMAGE_DOMAIN')
        next_port=dict(damage=damage,weighted=d.weighted+acceleration*dt,
            chemical=d.chemical+selected.port[13],ohmic=d.ohmic+selected.port[11],converter=d.converter+selected.port[12])
        for key,label in (('damage','resistance_damage'),('weighted','temperature_weighted_seconds'),
                          ('chemical','chemical_throughput_wh'),('ohmic','ohmic_heat_wh'),('converter','converter_loss_wh')):
            _port_real(next_port[key],label)
        if end.denominator.bit_length()>4096:raise BatteryPortDomainError('BATTERY_PORT_STATE_CLOCK')
        if d.exact[1]>=2**40:raise BatteryPortDomainError('BATTERY_PORT_STATE_STEPS')
    except BatteryPortDomainError:port_work.ageing_refused+=1;raise
    except BaseException:port_work.ageing_unknown+=1;raise
    port_work.ageing_returned+=1
    # This is a detached proposal, not an externally mutable alias or commit.
    return dict(full=None if not full_valid else _trial_data(&full),selected=_trial_data(&selected),
        desired=tuple(desired[i] for i in range(7)),commanded=tuple(commanded[i] for i in range(7)),served=tuple(served[i] for i in range(7)),
        served_reuse=tuple(bool(served_reuse[i]) for i in range(7)),source_sunlit=boundary['sunlit'],source_incidence=boundary['incidence'],
        desired_total=sum([desired[i] for i in range(7)]),commanded_total=sum([commanded[i] for i in range(7)]),served_total=sum([served[i] for i in range(7)]),
        shed=fsum([desired[i]-commanded[i] for i in range(7)]),essential_unserved=essential_unserved,
        essential_full=bool(essential_full),full_service=bool(full_service),radio=bool(radio),
        initial_refusal=initial_refusal,trials=service_work.allocation_trials-entry_trials,
        thermal=tuple(tuple(thermal[i][j] for j in range(7)) for i in range(m.n)),flows=tuple(flows[i] for i in range(m.l)),
        routed=tuple(routed[i] for i in range(m.n)),wire=tuple(wire[i] for i in range(m.n)),ledgers=tuple(ledgers),
        capability=(d.retention,usable,d.solar,solar_nominal),
        degradation=(d.retention,end_retention,d.throughput,increment,end_throughput,representative,calendar_acc,cycle_acc,calendar_damage,cycle_damage,total_damage),
        reconciliation=(selected.port[2],end_retention,end_capacity,unavailable,end_energy),
        solar=(d.solar,boundary['solar_loss'],end_solar),next_port=next_port,
        shape=m.shape(),method=METHOD)

class CoupledElectricalRefusal(ElectricalLimitError):
    def __init__(self,reason,full,trials):
        super().__init__(reason);self.full=full;self.trials=trials

class CoupledDomainRefusal(ValueError):
    def __init__(self,reason,data):
        super().__init__(reason);self.data=data

def coupled_cut(IndexedStatic model,TypedDynamic dynamic,boundary,service_work,port_work,wire_work,limits):
    _require_static_ready(model)
    return _coupled_cut(model,dynamic,boundary,service_work,port_work,wire_work,limits)

def prepare_static(configuration,compilation,service_policy,port_policy,protection,routing,limits):
    from .lifecycle_typed_state import indexed_static_data
    return IndexedStatic(indexed_static_data(configuration,compilation,service_policy,port_policy,protection,routing,limits))

def service_port_substep(*args,**kwargs):
    from .lifecycle_typed_state import service_port_substep as materialized_service
    return materialized_service(*args,**kwargs)


include "lifecycle_typed_world.pxi"
include "lifecycle_typed_quiet.pxi"

include "lifecycle_exact_guards.pxi"

# YEAR-V1 exact metadata loops. No physical arithmetic and no numeric-entry charge.
# Full owner signatures and the historical scientific wire remain the oracle.
import dataclasses as _ym_dc
import enum as _ym_enum
import fractions as _ym_frac
import decimal as _ym_dec
_ym_fields = _ym_dc.fields
_ym_is_dataclass = _ym_dc.is_dataclass
_ym_Enum = _ym_enum.Enum
_ym_EnumMeta = _ym_enum.EnumMeta
_ym_Fraction = _ym_frac.Fraction
_ym_Decimal = _ym_dec.Decimal
cdef object _YM_EXPORTS
cdef object _YM_DC=_ym_dc
cdef object _YM_ENUM_MOD=_ym_enum
cdef object _YM_FRAC_MOD=_ym_frac
cdef object _YM_DEC_MOD=_ym_dec
cdef object _YM_FIELDS=_ym_fields
cdef object _YM_IS_DC=_ym_is_dataclass
cdef object _YM_ENUM=_ym_Enum
cdef object _YM_ENUM_META=_ym_EnumMeta
cdef object _YM_FRAC=_ym_Fraction
cdef object _YM_DEC=_ym_Decimal
cdef uint64_t _ym_owner_calls=0
cdef uint64_t _ym_scientific_calls=0

cdef void _ym_guard() except *:
    cdef object name,expected
    for name,expected in _YM_EXPORTS:
        if PyObject_GetAttr(_G_MODULE,name)is not expected:raise ValueError("YEAR-V1 native metadata export drift")
    if (_ym_dc is not _YM_DC or _ym_enum is not _YM_ENUM_MOD or _ym_frac is not _YM_FRAC_MOD or _ym_dec is not _YM_DEC_MOD or _ym_fields is not _YM_FIELDS or _ym_is_dataclass is not _YM_IS_DC or _ym_Enum is not _YM_ENUM or _ym_EnumMeta is not _YM_ENUM_META or _ym_Fraction is not _YM_FRAC or _ym_Decimal is not _YM_DEC or _ym_dc.fields is not _ym_fields or _ym_dc.is_dataclass is not _ym_is_dataclass or
            _ym_enum.Enum is not _ym_Enum or _ym_enum.EnumMeta is not _ym_EnumMeta or
            _ym_frac.Fraction is not _ym_Fraction or _ym_dec.Decimal is not _ym_Decimal):
        raise ValueError('YEAR-V1 metadata primitive binding drift')

cdef object _ym_function_signature(object value):
    cdef object defaults=getattr(value,'__defaults__',None)
    cdef object keywords=getattr(value,'__kwdefaults__',None)
    cdef object code=getattr(value,'__code__',None)
    cdef list ds=[], ks=[]
    cdef object x,n
    if type(defaults)is tuple:
        for x in defaults:ds.append(id(x))
    if type(keywords)is dict:
        for n,x in keywords.items():ks.append((n,id(x)))
    return (id(value),id(code),id(defaults),tuple(ds),id(keywords),tuple(ks))

def input_owner_signature_v1(owner):
    global _ym_owner_calls
    cdef object name,member,f,n,k,v,params
    cdef list constructors=[],mro=[],members=[],field_data=[],mapping=[],flags=[],metadata=[]
    _ym_guard()
    if _ym_owner_calls>=2**48:raise ValueError('YEAR-V1 metadata owner control bound')
    _ym_owner_calls+=1
    for name in ('__init__','__new__','__post_init__','__setattr__','__getattribute__'):
        constructors.append((name,_ym_function_signature(getattr(owner,name,None))))
    for member in owner.__mro__:mro.append(id(member))
    common=(id(owner),owner.__module__,owner.__name__,tuple(mro),tuple(constructors))
    if isinstance(owner,_ym_EnumMeta):
        for n,member in owner.__members__.items():members.append((n,id(member)))
        return common+(tuple(members),)
    for f in _yc_fields_fast(owner):
        metadata=[]
        for k,v in f.metadata.items():metadata.append((id(k),id(v)))
        field_data.append((id(f),f.name,id(f.type),id(f.default),id(f.default_factory),
            id(f.init),id(f.repr),id(f.hash),id(f.compare),id(f.kw_only),id(f.metadata),
            tuple(metadata),id(getattr(f,'_field_type',None))))
    params=getattr(owner,'__dataclass_params__',None)
    for n in ('init','repr','eq','order','unsafe_hash','frozen','match_args','kw_only','slots','weakref_slot'):
        flags.append((n,id(getattr(params,n,None))))
    for n,f in owner.__dataclass_fields__.items():mapping.append((n,id(f)))
    return common+(id(owner.__dataclass_fields__),tuple(mapping),tuple(field_data),id(params),tuple(flags))

cdef object _ym_encode(object value,int depth,object visits):
    cdef object t,f,k,x
    cdef list rows=[]
    cdef dict result={}
    visits[0]+=1
    if depth>64 or visits[0]>8*2**20:raise ValueError('YEAR-V1 finite scientific tree exceeded')
    if isinstance(value,_ym_Enum):return dict(enum_type=type(value).__module__+'.'+type(value).__qualname__,member=value.name)
    if type(value)is _ym_Decimal:
        t=value.as_tuple();return dict(decimal_tuple=dict(sign=t.sign,digits=list(t.digits),exponent=t.exponent))
    if type(value)is _ym_Fraction:return dict(numerator_hex=hex(value.numerator),denominator_hex=hex(value.denominator))
    if type(value)is float:return dict(float_hex=value.hex())
    if _ym_is_dataclass(value):
        for f in _yc_fields_fast(value):result[f.name]=_ym_encode(getattr(value,f.name),depth+1,visits)
        return dict(record_type=type(value).__module__+'.'+type(value).__qualname__,fields=result)
    if type(value)in (tuple,list):
        for x in value:rows.append(_ym_encode(x,depth+1,visits))
        return {'tuple'if type(value)is tuple else'list':rows}
    if type(value)is dict:
        for k,x in value.items():result[k]=_ym_encode(x,depth+1,visits)
        return result
    if value is None or type(value)in (str,int,bool):return value
    raise TypeError('unsupported scientific output')

def scientific_output_v1(value):
    global _ym_scientific_calls
    _ym_guard()
    if _ym_scientific_calls>=2**48:raise ValueError('YEAR-V1 scientific metadata control bound')
    _ym_scientific_calls+=1
    return _ym_encode(value,0,[0])

def metadata_codec_counts_v1():
    return dict(method='YEAR_V1_EXACT_METADATA_LOOPS',owner_signatures=int(_ym_owner_calls),
        scientific_encodings=int(_ym_scientific_calls),limit=2**48,reset_available=False,
        physical_arithmetic=False,result_cache=False,scope='PROCESS_OPERATIONAL_METADATA_NOT_SCIENTIFIC_WORK')


_YM_EXPORTS=tuple((n,globals()[n])for n in ('input_owner_signature_v1','scientific_output_v1','metadata_codec_counts_v1'))

# YEAR-V2 exact canonical wire loops; all original roundtrip checks retained.
cdef uint64_t _yc_encode_calls=0
cdef uint64_t _yc_decode_calls=0
cdef uint64_t _yc_schema_calls=0

cdef object _yc_encode(object value, object codec, int depth):
    if depth>900:raise RecursionError("YEAR-V2 finite canonical recursion")
    owner = type(value)
    if value is None:
        return {'kind': 'none'}
    if owner is bool:
        return {'kind': 'bool', 'value': value}
    if owner is int:
        return {'kind': 'int', 'value': str(value)}
    if owner is float:
        if not codec['isfinite'](value):
            raise ValueError('non-finite canonical number')
        return {'kind': 'float', 'value': value.hex()}
    if owner is codec['Fraction']:
        return {'kind': 'fraction', 'numerator': str(value.numerator), 'denominator': str(value.denominator)}
    if owner is str:
        return {'kind': 'str', 'value': codec['_text'](value)}
    if owner in (tuple, list):
        return {'kind': 'tuple' if owner is tuple else 'list', 'items': [_yc_encode(x, codec, depth + 1) for x in value]}
    if owner is dict:
        for key in value:
            codec['_text'](key)
        return {'kind': 'map', 'items': [[key, _yc_encode(value[key], codec, depth + 1)] for key in sorted(value)]}
    name = owner.__module__ + '.' + owner.__name__
    if owner in codec['ENUM_TYPES']:
        if value is not owner.__members__.get(value.name):
            raise ValueError('invalid enum member')
        return {'kind': 'enum', 'type': name, 'member': value.name}
    if owner in codec['RECORD_FIELDS']:
        return {'kind': 'record', 'type': name, 'fields': {field: _yc_encode(getattr(value, field), codec, depth + 1) for field in codec['RECORD_FIELDS'][owner]}}
    raise TypeError(f'unsupported canonical type: {name}')

cdef object _yc_decode(object value, object codec, int depth):
    if depth>900:raise RecursionError("YEAR-V2 finite canonical recursion")
    if type(value) is not dict or type(value.get('kind')) is not str:
        raise TypeError('expected tagged canonical object')
    kind = value['kind']
    if kind == 'none':
        codec['object_fields'](value, ('kind',))
        return None
    if kind in ('bool', 'str', 'int', 'float'):
        codec['object_fields'](value, ('kind', 'value'))
        x = value['value']
        if kind == 'bool':
            if type(x) is not bool:
                raise TypeError('expected exact bool')
            return x
        if kind == 'str':
            return codec['_text'](x)
        if kind == 'int':
            return codec['_integer'](x)
        result = float.fromhex(codec['_text'](x))
        if not codec['isfinite'](result) or result.hex() != x:
            raise ValueError('noncanonical or non-finite float')
        return result
    if kind == 'fraction':
        codec['object_fields'](value, ('kind', 'numerator', 'denominator'))
        numerator, denominator = (codec['_integer'](value['numerator']), codec['_integer'](value['denominator']))
        if denominator <= 0:
            raise ValueError('fraction denominator must be positive')
        result = codec['Fraction'](numerator, denominator)
        if result.numerator != numerator or result.denominator != denominator:
            raise ValueError('fraction must be reduced')
        return result
    if kind in ('tuple', 'list', 'map'):
        codec['object_fields'](value, ('kind', 'items'))
        items = value['items']
        if type(items) is not list:
            raise TypeError('canonical items must be a list')
        if kind == 'map':
            result = {}
            for item in items:
                if type(item) is not list or len(item) != 2:
                    raise ValueError('invalid map item')
                key = codec['_text'](item[0])
                if key in result:
                    raise ValueError('duplicate map key')
                result[key] = _yc_decode(item[1], codec, depth + 1)
            if list(result) != sorted(result):
                raise ValueError('noncanonical map key order')
            return result
        result = [_yc_decode(x, codec, depth + 1) for x in items]
        return tuple(result) if kind == 'tuple' else result
    if kind == 'enum':
        codec['object_fields'](value, ('kind', 'type', 'member'))
        owner = codec['_ENUMS'].get(codec['_text'](value['type']))
        member = codec['_text'](value['member'])
        if owner is None or member not in owner.__members__:
            raise ValueError('unknown enum type/member')
        return owner[member]
    if kind == 'record':
        codec['object_fields'](value, ('kind', 'type', 'fields'))
        owner = codec['_RECORDS'].get(codec['_text'](value['type']))
        if owner is None:
            raise ValueError('unknown record type')
        content = codec['object_fields'](value['fields'], codec['RECORD_FIELDS'][owner])
        return owner(**{name: _yc_decode(content[name], codec, depth + 1) for name in codec['RECORD_FIELDS'][owner]})
    raise ValueError('unknown canonical kind')

def canonical_encode_v2(value,codec):
    global _yc_encode_calls
    _ym_guard()
    if _yc_encode_calls>=2**48:raise ValueError("YEAR-V2 canonical control bound")
    _yc_encode_calls+=1
    return _yc_encode(value,codec,0)

def canonical_decode_v2(value,codec):
    global _yc_decode_calls
    _ym_guard()
    if _yc_decode_calls>=2**48:raise ValueError("YEAR-V2 canonical control bound")
    _yc_decode_calls+=1
    return _yc_decode(value,codec,0)

def schema_coverage_v2(records,field_function):
    global _yc_schema_calls
    cdef object owner,names,actual,f
    cdef list observed
    _ym_guard()
    if _yc_schema_calls>=2**48:raise ValueError('YEAR-V2 schema control bound')
    _yc_schema_calls+=1
    for owner,names in records.items():
        actual=_yc_fields_fast(owner)if field_function is _ym_fields else field_function(owner)
        observed=[]
        for f in actual:observed.append(f.name)
        if tuple(observed)!=names:raise ValueError(f"unreviewed canonical field schema: {owner.__name__}")
        for f in actual:
            if not f.init:raise ValueError(f"unreviewed canonical field schema: {owner.__name__}")

def canonical_codec_counts_v2():
    return dict(method='YEAR_V2_EXACT_WIRE_SCOPE_FIELDS_LOOPS_V2',encodings=int(_yc_encode_calls),decodings=int(_yc_decode_calls),schema_checks=int(_yc_schema_calls),scope_checks=int(_yc_scope_checks),fast_field_reads=int(_yc_fields_reads),field_fallback_reads=int(_yc_fields_fallback),recognized_stdlib_fields=bool(_YC_FAST_FIELDS_KNOWN),limit=2**48,reset_available=False,result_cache=False,physical_arithmetic=False)

_YM_EXPORTS+=tuple((n,globals()[n])for n in ('canonical_encode_v2','canonical_decode_v2','schema_coverage_v2','canonical_codec_counts_v2'))

def _yc_field_code_shape(code):
    from types import CodeType
    return (code.co_code.hex(),code.co_exceptiontable.hex(),code.co_argcount,code.co_posonlyargcount,code.co_kwonlyargcount,code.co_nlocals,code.co_stacksize,code.co_flags,code.co_names,code.co_varnames,code.co_freevars,code.co_cellvars,tuple(_yc_field_code_shape(v)if type(v)is CodeType else v for v in code.co_consts))

cdef object _YC_EXPECTED_FIELDS_SHAPE=('80001b005c01000000000000000056005c020000000000000000340200000000000070015c0800000000000000003b0151024a00642200001c001f002e00520317005401500b000000000000000000000000000000000000340000000000000010003400000000000000460300004e024b05000009001e00350623002100520317005401500b0000000000000000000000000000000000003400000000000000100034000000000000003401000000000000230020005c0400000000000000000600640e00001c001f005c070000000000000000520134010000000000005202680269003b031d006901', '8210411a00c11a18413203', 1, 0, 0, 2, 5, 67108867, ('getattr', '_FIELDS', 'AttributeError', 'TypeError', 'tuple', 'values'), ('class_or_instance', 'fields'), (), (), ('Return a tuple describing the fields of this dataclass.\n\nAccepts a dataclass or an instance of one. Tuple elements are of\ntype Field.\n', 'must be called with a dataclass type or instance', None, ('22001f0080005400461c0000711150000000000000000000000000000000000000005c0200000000000000004a00670300001c004b1800005601780080051f004b1e000009001e005200230035036901', '821526019c0a2601', 1, 0, 0, 2, 3, 51, ('_field_type', '_FIELD'), ('.0', 'f'), (), (), (None,))))
cdef bint _YC_FAST_FIELDS_KNOWN=_yc_field_code_shape(_ym_fields.__code__)==_YC_EXPECTED_FIELDS_SHAPE
cdef object _YC_FIELD_CODE=_ym_fields.__code__
cdef object _YC_FIELD_GLOBALS=_ym_fields.__globals__
cdef object _YC_FIELDS_KEY=_ym_dc._FIELDS
cdef object _YC_FIELD_KIND=_ym_dc._FIELD
cdef object _YC_FIELD_BUILTINS=_ym_fields.__builtins__
cdef object _YC_FIELD_LOOKUPS=(('getattr',getattr),('tuple',tuple),('AttributeError',AttributeError),('TypeError',TypeError))
cdef uint64_t _yc_scope_checks=0
cdef uint64_t _yc_fields_reads=0
cdef uint64_t _yc_fields_fallback=0

cdef object _yc_fields_fast(object owner):
    global _yc_fields_reads,_yc_fields_fallback
    cdef object mapping,f,n,expected
    cdef list values=[]
    if (_ym_fields.__code__ is not _YC_FIELD_CODE or _ym_fields.__globals__ is not _YC_FIELD_GLOBALS or
            _ym_dc.fields is not _ym_fields or _ym_dc._FIELDS is not _YC_FIELDS_KEY or _ym_dc._FIELD is not _YC_FIELD_KIND):
        raise ValueError('YEAR-V2 dataclass fields implementation drift')
    if _ym_fields.__builtins__ is not _YC_FIELD_BUILTINS:raise ValueError('YEAR-V2 fields builtins binding')
    for n,expected in _YC_FIELD_LOOKUPS:
        if _YC_FIELD_GLOBALS.get(n,_YC_FIELD_BUILTINS.get(n))is not expected:raise ValueError('YEAR-V2 fields global binding')
    if not _YC_FAST_FIELDS_KNOWN:
        if _yc_fields_fallback>=2**48:raise ValueError('YEAR-V2 field fallback bound')
        _yc_fields_fallback+=1;return _ym_fields(owner)
    if _yc_fields_reads>=2**48:raise ValueError('YEAR-V2 fields control bound')
    _yc_fields_reads+=1
    try:mapping=getattr(owner,_YC_FIELDS_KEY)
    except AttributeError:raise TypeError('must be called with a dataclass type or instance')from None
    for f in mapping.values():
        if f._field_type is _YC_FIELD_KIND:values.append(f)
    return tuple(values)

# Complete previous Python scope check, same live reads; no result caching.
def metadata_scope_check_v2(scope,process,thread):
    global _yc_scope_checks
    cdef object p,n,f,t
    _ym_guard()
    if _yc_scope_checks>=2**48:raise ValueError('YEAR-V2 scope control bound')
    _yc_scope_checks+=1
    p=scope.pins
    if (scope.closed or scope.native is not p[0]or scope.calls is not p[1]or scope.pid!=p[2]or
            scope.thread!=p[3]or process!=p[2]or thread!=p[3]or scope.gate_code is not p[4]):
        raise ValueError('YEAR-V1 stale/process/thread metadata scope')
    for n,f in scope.calls:
        t=type(f)
        if (getattr(scope.native,n)is not f or t.__module__!='_cython_3_2_4'or
                t.__name__!='cython_function_or_method'or t.__flags__&384!=384 or
                getattr(f,'__module__',None)!='ops_sim.v5._lifecycle_typed65'or getattr(f,'__name__',None)!=n):
            raise ValueError('YEAR-V1 exact compiled metadata function drift')

_YM_EXPORTS+=tuple((n,globals()[n])for n in ('metadata_scope_check_v2',))
