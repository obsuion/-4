# Included after lifecycle_typed_world.pxi in the same numerical extension.
# No arbitrary callback is accepted by this interface. Exact clocks and work
# remain Python integers/Fractions; physical scratch is private binary64.

cdef class _TypedQuietPlan:
    cdef IndexedStatic model
    cdef object static,physical,hardware,pending,policy,service_policy,env_policy,origin
    cdef TypedWorldPlan world
    cdef double operating_min[64]
    cdef double operating_max[64]
    cdef double survival_min[64]
    cdef double survival_max[64]
    cdef bint required[64]
    cdef object node_laws,link_laws
    cdef object metric_names,integral_names,temperature_order,reason_role
    cdef bint short_circuit

cdef class _TypedQuietState:
    cdef TypedDynamic dynamic
    cdef object service,service_work,environment,history
    cdef double last_voltage,last_current,last_resistance,last_ocv
    cdef bint measured
    cdef object port_clock,port_steps

cdef _TypedQuietState _quiet_clone(_TypedQuietState q):
    cdef _TypedQuietState result=_TypedQuietState.__new__(_TypedQuietState)
    cdef TypedDynamic d=TypedDynamic.__new__(TypedDynamic)
    cdef IndexedStatic m=q.dynamic.owner
    cdef int i
    d.owner=m;d.energy=q.dynamic.energy;d.retention=q.dynamic.retention
    d.throughput=q.dynamic.throughput;d.solar=q.dynamic.solar
    d.damage=q.dynamic.damage;d.weighted=q.dynamic.weighted;d.chemical=q.dynamic.chemical
    d.ohmic=q.dynamic.ohmic;d.converter=q.dynamic.converter;d.exact=q.dynamic.exact
    for i in range(m.n):d.t[i]=q.dynamic.t[i]
    result.dynamic=d;result.service=dict(q.service);result.service_work=dict(q.service_work)
    result.environment=None if q.environment is None else dict(q.environment)
    result.history=q.history
    result.last_voltage=q.last_voltage;result.last_current=q.last_current
    result.last_resistance=q.last_resistance;result.last_ocv=q.last_ocv;result.measured=q.measured
    result.port_clock=q.port_clock;result.port_steps=q.port_steps
    return result

cdef double _quiet_saturate(double initial,double asymptote,object calendar,double exposure,double kc,double kx) except *:
    cdef double x=kc*float(calendar)+kx*exposure
    return initial+(asymptote-initial)*(x/(1.+x))

cdef double _quiet_retention(_TypedQuietPlan p,object environment) except *:
    cdef double initial=environment['reference_solar_retention']
    return _quiet_saturate(initial,initial*p.env_policy.pv_floor_fraction,
        environment['calendar_seconds'],environment['pv_exposure_seconds'],
        p.env_policy.pv_calendar_rate_per_second,p.env_policy.pv_exposure_rate_per_second)

cdef object _quiet_effective(_TypedQuietPlan p,object environment):
    cdef int i
    cdef double value,exposure
    cdef IndexedStatic m=p.model
    cdef object epsilon=[],conductance=[],law
    for i in range(m.n):
        law=p.node_laws[i]
        value=m.emissivity[i]
        if law is not None:
            exposure=environment['thermal_exposure_seconds']*law.exposure_factor
            value=_quiet_saturate(value,law.asymptote,environment['calendar_seconds'],exposure,
                law.calendar_rate_per_second,law.exposure_rate_per_second)
        epsilon.append(value)
    for i in range(m.l):
        law=p.link_laws[i]
        value=m.conductance[i]
        if law is not None:
            exposure=environment['thermal_exposure_seconds']*law.exposure_factor
            value=_quiet_saturate(value,law.asymptote_w_per_k,environment['calendar_seconds'],exposure,
                law.calendar_rate_per_second,law.exposure_rate_per_second)
        conductance.append(value)
    return tuple(epsilon),tuple(conductance)

cdef object _quiet_environment_propose(_TypedQuietPlan p,_TypedQuietState q,object left,object right,object forcing):
    cdef object history=q.environment,result
    cdef double dt=float(right-left),weight,incidence
    cdef object work=p.physical.environment_ageing_work
    if p.env_policy is None:return None
    if q.dynamic.solar!=_quiet_retention(p,history):raise ValueError('B61 physical PV state/provenance mismatch')
    work.reserve(p.env_policy)
    try:
        if history['clock_seconds']!=left or not 0<right-left<=120:raise ValueError('B61 bounded exact physical cut')
        if type(forcing['sunlit'])is not bool:raise TypeError('B61 actual admitted lighting boolean')
        incidence=_number(forcing['incidence'],'incidence degrees')
        if not 0<=incidence<=180:raise ValueError('B61_DOMAIN:incidence degrees')
        weight=max(0.,cos(radians(incidence))) if forcing['sunlit'] else 0.
        result=dict(history)
        result.update(clock_seconds=right,calendar_seconds=history['calendar_seconds']+(right-left),
            pv_exposure_seconds=history['pv_exposure_seconds']+dt*weight,
            thermal_exposure_seconds=history['thermal_exposure_seconds']+(dt if forcing['sunlit'] else 0.),
            selected_cuts=history['selected_cuts']+1)
        for name in ('clock_seconds','calendar_seconds'):
            value=result[name]
            if (type(value)is not Fraction or not 0<=value<=10**12 or
                    value.numerator.bit_length()>128 or value.denominator.bit_length()>128):
                raise ValueError('B61 exact bounded clock')
        for name in ('pv_exposure_seconds','thermal_exposure_seconds'):
            value=result[name]
            if type(value)not in(int,float)or not c_isfinite(float(value))or not 0<=value<=10**12:
                raise ValueError('B61_DOMAIN:'+name)
        if type(result['selected_cuts'])is not int or not 0<=result['selected_cuts']<=2**36:
            raise ValueError('B61_DOMAIN:selected cuts')
        work.returned+=1
        return result
    except BaseException:work.failed+=1;raise

cdef object _quiet_decision(_TypedQuietPlan p,_TypedQuietState q,object clock):
    cdef object state=q.service,policy=p.service_policy
    cdef object mode=state['mode'],reason=state['last_reason']
    cdef double capacity=_mul(p.model.nominal_energy,q.dynamic.retention,'battery usable capacity')
    if state['clock_seconds']!=clock:raise ValueError('stale service decision clock')
    if q.dynamic.energy>capacity:raise ValueError('battery energy exceeds current usable capacity')
    low=Fraction(policy.low_usable_capacity_fraction)*Fraction(capacity)
    high=Fraction(policy.high_usable_capacity_fraction)*Fraction(capacity)
    dwell=clock-state['entered_at_seconds']
    if mode=='NORMAL':
        if not state['essential_serviceable']:mode='POWER_OFF';reason='ESSENTIAL_SERVICE_UNAVAILABLE'
        elif Fraction(q.dynamic.energy)<=low:mode='SAFE';reason='NORMAL_LOW_ENERGY'
    elif mode in ('SAFE','POWER_OFF'):
        if not state['essential_serviceable']:mode='POWER_OFF';reason='ESSENTIAL_SERVICE_UNAVAILABLE'
        elif Fraction(q.dynamic.energy)>=high and dwell>=policy.minimum_dwell_seconds:
            mode='RECOVERY';reason='RECOVERY_RESERVE_READY'
    else:
        if not state['essential_serviceable']:mode='POWER_OFF';reason='ESSENTIAL_SERVICE_UNAVAILABLE'
        elif Fraction(q.dynamic.energy)<=low:mode='SAFE';reason='BOOT_RESERVE_LOST'
        elif state['boot_progress_seconds']>=policy.boot_duration_seconds and dwell>=policy.minimum_dwell_seconds:
            mode='NORMAL';reason='BOOT_COMPLETED'
    changed=mode!=state['mode']
    chosen=dict(state)
    if changed:
        chosen.update(mode=mode,entered_at_seconds=clock,last_reason=reason,boot_progress_seconds=Fraction(),
            transition_count=state['transition_count']+1,
            communications_serviceable=(mode=='NORMAL' and state['essential_serviceable']),tx_fully_served=False)
    return chosen,bool(changed)

cdef void _quiet_commit_service(_TypedQuietPlan p,_TypedQuietState q,object decision,bint changed,object dt,object data) except *:
    cdef object work=q.service_work,state=decision,values=[],new_state,updated,names
    cdef int i
    for name in ('desired','commanded','served'):
        values.append(sum((Fraction(x) for x in data[name]),Fraction()))
    desired,commanded,served=values
    unmet=sum((Fraction(data['commanded'][i])-Fraction(data['served'][i]) for i in (0,1)),Fraction())
    if work['through_seconds']is not None and work['through_seconds']!=state['clock_seconds']:
        raise ValueError('stale service decision/work frontier')
    if commanded<=0 or not served<=commanded<=desired or unmet>commanded-served:
        raise ValueError('selected receiving load/service balance')
    if data['essential_full']!=(unmet==0):raise ValueError('functional service differs from essential deficit')
    if state['transition_count']!=work['initial_transition_count']+work['transitions']+int(changed):
        raise ValueError('service decision/work transition frontier')
    boot=dt if state['mode']=='RECOVERY' and data['essential_full'] else Fraction()
    new_state=dict(state)
    new_state.update(clock_seconds=state['clock_seconds']+dt,
        boot_progress_seconds=state['boot_progress_seconds']+boot if state['mode']=='RECOVERY' else Fraction(),
        essential_serviceable=data['essential_full'],communications_serviceable=state['mode']=='NORMAL' and data['essential_full'],tx_fully_served=False)
    names=dict(work['transition_reasons'])
    if changed:names[state['last_reason']]=names.get(state['last_reason'],0)+1
    time_field={'NORMAL':'normal_seconds','SAFE':'safe_seconds','POWER_OFF':'power_off_seconds','RECOVERY':'recovery_seconds'}[state['mode']]
    updated=dict(work)
    updated[time_field]=work[time_field]+dt
    updated.update(desired_normal_load_wh=work['desired_normal_load_wh']+desired*dt/3600,
        commanded_load_wh=work['commanded_load_wh']+commanded*dt/3600,
        served_receiving_load_wh=work['served_receiving_load_wh']+served*dt/3600,
        commanded_shed_demand_wh=work['commanded_shed_demand_wh']+(desired-commanded)*dt/3600,
        essential_unserved_wh=work['essential_unserved_wh']+unmet*dt/3600,
        boot_work_seconds=work['boot_work_seconds']+boot,selected_steps=work['selected_steps']+1,
        transitions=work['transitions']+int(changed),
        service_interruptions=work['service_interruptions']+int(state['essential_serviceable'] and not data['essential_full']),
        transition_reasons=tuple(sorted(names.items())),
        initial_clock_seconds=state['clock_seconds'] if work['initial_clock_seconds']is None else work['initial_clock_seconds'],
        through_seconds=new_state['clock_seconds'])
    _quiet_check_service_data(new_state,updated)
    q.service=new_state;q.service_work=updated

cdef void _quiet_check_service_data(object state,object work) except *:
    # Exact bounded state/work invariants of the immutable public records.
    # Private trials do not manufacture those records, but keep their guards.
    for name in ('clock_seconds','entered_at_seconds','boot_progress_seconds'):
        value=state[name]
        if type(value)is not Fraction or value<0 or max(abs(value.numerator).bit_length(),value.denominator.bit_length())>4096:
            raise ValueError('exact nonnegative service seconds/energy: '+name)
    if state['entered_at_seconds']>state['clock_seconds']:raise ValueError('future service mode entry')
    if type(state['transition_count'])is not int or not 0<=state['transition_count']<=2**48:
        raise ValueError('exact bounded service integer: mode transitions')
    if state['mode']!='RECOVERY' and state['boot_progress_seconds']:
        raise ValueError('boot work belongs only to RECOVERY')
    if state['boot_progress_seconds']>state['clock_seconds']-state['entered_at_seconds']:
        raise ValueError('boot progress exceeds actual recovery support')
    for name in ('normal_seconds','safe_seconds','power_off_seconds','recovery_seconds',
                 'desired_normal_load_wh','commanded_load_wh','served_receiving_load_wh',
                 'commanded_shed_demand_wh','essential_unserved_wh','boot_work_seconds'):
        value=work[name]
        if type(value)is not Fraction or value<0 or max(abs(value.numerator).bit_length(),value.denominator.bit_length())>4096:
            raise ValueError('exact nonnegative service seconds/energy: '+name)
    for name in ('selected_steps','transitions','service_interruptions'):
        if type(work[name])is not int or not 0<=work[name]<=2**48:
            raise ValueError('exact bounded service integer: '+name)
    if work['served_receiving_load_wh']>work['commanded_load_wh'] or work['commanded_load_wh']>work['desired_normal_load_wh']:
        raise ValueError('desired/commanded/served receiving-power scopes')
    if work['commanded_shed_demand_wh']!=work['desired_normal_load_wh']-work['commanded_load_wh']:
        raise ValueError('exact commanded shed accounting')
    if work['essential_unserved_wh']>work['commanded_load_wh']-work['served_receiving_load_wh']:
        raise ValueError('essential deficit exceeds receiving load deficit')
    if work['boot_work_seconds']>work['recovery_seconds']:raise ValueError('boot work exceeds selected recovery support')
    reasons=work['transition_reasons']
    if (type(reasons)is not tuple or len(reasons)>6 or
            any(type(n)is not str or type(v)is not int or not 1<=v<=2**48 for n,v in reasons)or
            tuple(n for n,v in reasons)!=tuple(sorted(set(n for n,v in reasons)))or
            sum(v for n,v in reasons)!=work['transitions']):
        raise ValueError('canonical transition reason/count balance')
    covered=work['normal_seconds']+work['safe_seconds']+work['power_off_seconds']+work['recovery_seconds']
    if work['through_seconds']-work['initial_clock_seconds']!=covered or (work['selected_steps']==0)!=(covered==0):
        raise ValueError('service ledger support/frontier balance')

cdef object _quiet_temperature_reason(_TypedQuietPlan p,_TypedQuietState q,bint at_start,object data=None):
    cdef int i
    cdef bint normal=q.service['mode']=='NORMAL'
    cdef double value
    for i in range(p.model.n):
        value=q.dynamic.t[i] if at_start else data['thermal'][i][1]
        if not p.survival_min[i]<=value<=p.survival_max[i]:
            return 'B55_SURVIVAL_TEMPERATURE_AT_START' if at_start else 'B55_SURVIVAL_TEMPERATURE_AT_ENDPOINT'
    if normal:
        for i in range(p.model.n):
            value=q.dynamic.t[i] if at_start else data['thermal'][i][1]
            if p.required[i] and not p.operating_min[i]<=value<=p.operating_max[i]:
                return 'OPERATING_TEMPERATURE_AT_START' if at_start else 'OPERATING_TEMPERATURE_AT_ENDPOINT'
    return None

cdef object _quiet_ocv(_TypedQuietPlan p,_TypedQuietState q):
    cdef IndexedStatic m=p.model
    cdef TypedDynamic d=q.dynamic
    cdef double capacity=_mul(m.nominal_energy,d.retention,'battery usable capacity')
    cdef double s=d.energy/capacity,t=d.t[m.battery],voc=0.,exponent,resistance,square,acceleration
    cdef int i
    _port_real(capacity,'usable Wh',1.e-12);_port_real(d.energy,'stored Wh',0.,capacity)
    _port_real(t,'temperature K',m.p[11],m.p[12])
    if d.damage>m.p[6]:raise BatteryPortDomainError('BATTERY_PORT_DAMAGE_DOMAIN')
    for i in range(m.ocv_n-1):
        if s<=m.ocv_s[i+1]:
            voc=m.ocv_v[i]+(m.ocv_v[i+1]-m.ocv_v[i])*((s-m.ocv_s[i])/(m.ocv_s[i+1]-m.ocv_s[i]));break
    voc+=m.p[0]*(t-m.p[1]);exponent=m.p[3]*(m.p[1]-t)
    if abs(exponent)>32:raise BatteryPortDomainError('BATTERY_PORT_EXPONENT_DOMAIN')
    v=float(1-s);v=v**2;square=v;acceleration=exp(exponent)
    resistance=m.p[2]*(1+d.damage)*(1+m.p[4]*square)*acceleration
    _port_real(voc,'derived Voc',1.e-12,100.);_port_real(resistance,'derived R',0.,100.)
    return voc,resistance

cdef object _quiet_values(_TypedQuietPlan p,_TypedQuietState q):
    cdef IndexedStatic m=p.model
    cdef TypedDynamic d=q.dynamic
    cdef int i
    voc,resistance=_quiet_ocv(p,q)
    values=[('port_voltage_v',q.last_voltage if q.measured else voc),('port_ocv_v',voc),
        ('port_current_a',q.last_current if q.measured else 0.),('port_resistance_ohm',resistance),
        ('port_resistance_damage',d.damage),('port_weighted_seconds',d.weighted),
        ('port_ohmic_heat_wh',d.ohmic),('port_converter_loss_wh',d.converter),
        ('energy_wh',d.energy),('throughput_wh',d.throughput),('battery_retention',d.retention),('solar_retention',d.solar)]
    for i in p.temperature_order:values.append(('temperature:'+p.static.ids[i].value,d.t[i]))
    if q.environment is not None:
        epsilon,conductance=_quiet_effective(p,q.environment)
        values.extend((('environment_calendar_seconds',float(q.environment['calendar_seconds'])),
            ('environment_pv_exposure_seconds',q.environment['pv_exposure_seconds']),
            ('environment_thermal_exposure_seconds',q.environment['thermal_exposure_seconds']),
            ('environment_pv_retention',_quiet_retention(p,q.environment))))
        for i in range(m.n):values.append(('environment_epsilon:'+p.static.ids[i].value,epsilon[i]))
        for i in range(m.l):values.append(('environment_conductance:'+p.static.links[i].value,conductance[i]))
    return tuple(values)

cdef double _quiet_energy(double power,double seconds) except *:
    return _div(_mul(power,seconds,'action energy J'),3600.,'action energy Wh')

cdef object _quiet_integrals(object data):
    cdef object b=data['selected']['port'],dg=data['degradation'],rc=data['reconciliation']
    cdef double dt=b[0]
    cdef object names=('generation_wh','requested_load_wh','served_load_wh','unmet_load_wh',
        'charge_input_wh','discharge_output_wh','curtailed_generation_wh','conversion_loss_wh',
        'throughput_wh','unavailable_energy_wh','calendar_damage','cycling_damage','solar_retention_loss',
        'routed_internal_heat_wh','external_heat_wh','wire_loss_wh','source_generation_wh','receiving_load_wh',
        'port_ohmic_heat_wh','port_converter_loss_wh')
    values=[fsum([_quiet_energy(b[i],dt)]) for i in (3,4,5,6,7,8,9)]
    values.extend((fsum([b[10]]),fsum([dg[3]]),fsum([rc[3]]),fsum([dg[8]]),fsum([dg[9]]),
        fsum([] if data['solar'][1]is None else [data['solar'][1]]),
        fsum(_quiet_energy(row[0],dt) for row in data['ledgers']),
        fsum(_quiet_energy(fsum((row[1],row[2],row[3])),dt) for row in data['ledgers']),
        (data['selected']['pv_wire_loss_w']+data['selected']['receiving_wire_loss_w'])*(dt/3600.),
        data['selected']['source_generation_w']*(dt/3600.),
        data['selected']['receiving_load_w']*(dt/3600.),b[11],b[12]))
    return tuple(zip(names,values))

cdef object _quiet_sample_data(_TypedQuietPlan p,_TypedQuietState q,object data):
    cdef IndexedStatic m=p.model
    cdef object b=data['selected']['port'],capacity=data['capability'][1],energy=q.dynamic.energy
    cdef object policy=p.policy,service=q.service,mode=data['mode']
    cdef int i
    cdef bint near,near_energy,crossed_low,thermal_near,was_near
    cdef object reasons=[]
    regime=(b[7]>0,b[8]>0,b[9]>0,data['reconciliation'][3]>0,b[6]>0,b[1]==capacity,
        mode,service['essential_serviceable'],service['boot_progress_seconds']>=p.service_policy.boot_duration_seconds)
    fractions=(p.service_policy.high_usable_capacity_fraction,) if mode in('SAFE','POWER_OFF') else (
        p.service_policy.low_usable_capacity_fraction,p.service_policy.high_usable_capacity_fraction)
    near_energy=any(abs(energy-capacity*f)<=policy.guard_energy_margin_wh for f in fractions)
    start_capacity_q=Fraction(capacity);end_capacity_q=Fraction(data['reconciliation'][2])
    start_energy_q=Fraction(b[1]);end_energy_q=Fraction(data['reconciliation'][4])
    low_q=Fraction(p.service_policy.low_usable_capacity_fraction);high_q=Fraction(p.service_policy.high_usable_capacity_fraction)
    low_start=start_energy_q-start_capacity_q*low_q;low_end=end_energy_q-end_capacity_q*low_q
    high_start=start_energy_q-start_capacity_q*high_q;high_end=end_energy_q-end_capacity_q*high_q
    if mode=='NORMAL':near_energy=near_energy or energy<=policy.guard_energy_margin_wh or (low_start>0 and low_end<=0) or low_end<=0
    elif mode=='RECOVERY':near_energy=near_energy or (low_start>0 and low_end<=0) or low_end<=0
    else:near_energy=near_energy or high_start<0<=high_end
    near=near_energy;thermal_near=False
    if near_energy:reasons.append('ENERGY_NEAR_COMPOSITE')
    for i in range(m.n):
        if mode!='NORMAL' or p.required[i]:
            if min(q.dynamic.t[i]-(p.operating_min[i] if mode=='NORMAL' else p.survival_min[i]),
                   (p.operating_max[i] if mode=='NORMAL' else p.survival_max[i])-q.dynamic.t[i])<=policy.guard_temperature_margin_k:
                near=True;thermal_near=True
    if thermal_near:reasons.append('THERMAL_MARGIN')
    if mode in('SAFE','POWER_OFF') and service['essential_serviceable'] and high_end>=0:
        remaining=p.service_policy.minimum_dwell_seconds-(service['clock_seconds']-service['entered_at_seconds'])
        was_near=near;near=near or remaining<=policy.maximum_macro_seconds
        if near and not was_near:reasons.append('DWELL_GUARD_ADDED')
    if service['mode']=='RECOVERY' and service['boot_progress_seconds']<p.service_policy.boot_duration_seconds:
        was_near=near;near=near or p.service_policy.boot_duration_seconds-service['boot_progress_seconds']<=policy.maximum_macro_seconds
        if near and not was_near:reasons.append('BOOT_GUARD_ADDED')
    regime+=(data['selected']['reason'],b[18]>0,b[18]<0)
    if data['selected']['near']:reasons.append('SELECTED_ALLOCATION_NEAR')
    near=near or data['selected']['near']
    return dict(state_values=_quiet_values(p,q),integrals=_quiet_integrals(data),regime=regime,near_guard=bool(near),near_reasons=tuple(reasons))

cdef double _quiet_absolute(object name,object policy) except *:
    if name in('environment_calendar_seconds','environment_pv_exposure_seconds','environment_thermal_exposure_seconds'):return policy.absolute_exposure_seconds
    if name=='environment_pv_retention':return policy.absolute_retention
    if name.startswith('environment_epsilon:'):return policy.absolute_emissivity
    if name.startswith('environment_conductance:'):return policy.absolute_conductance_w_per_k
    if name in('port_voltage_v','port_ocv_v'):return policy.absolute_voltage_v
    if name=='port_current_a':return policy.absolute_current_a
    if name=='port_resistance_ohm':return policy.absolute_resistance_ohm
    if name=='port_resistance_damage':return policy.absolute_resistance_damage
    if name=='port_weighted_seconds':return policy.absolute_weighted_seconds
    if name.startswith('temperature:'):return policy.absolute_temperature_k
    if 'retention' in name or name in('calendar_damage','cycling_damage'):return policy.absolute_retention
    return policy.absolute_energy_wh

cdef double _quiet_error(object initial,object full,object first,object second,object policy,object role) except *:
    cdef double result=0.,coarse,fine,scale,value
    cdef object dominant=None
    from .lifecycle_quiet import _reason_v5,_reason_named_v5
    cdef int i
    _enter(9)
    if (tuple(k for k,v in initial)!=tuple(k for k,v in full['state_values']) or
            tuple(k for k,v in initial)!=tuple(k for k,v in first['state_values']) or
            tuple(k for k,v in initial)!=tuple(k for k,v in second['state_values']) or
            tuple(k for k,v in full['integrals'])!=tuple(k for k,v in first['integrals']) or
            tuple(k for k,v in full['integrals'])!=tuple(k for k,v in second['integrals'])):
        raise ValueError('quiet metric authority/order changed')
    for i in range(len(initial)):
        name,coarse=full['state_values'][i];fine=second['state_values'][i][1]
        scale=_quiet_absolute(name,policy)+policy.relative_tolerance*max(abs(initial[i][1]),abs(coarse),abs(fine))
        value=abs(fine-coarse)/scale
        if value>result:dominant='STATE:'+name
        result=max(result,value)
    for i in range(len(full['integrals'])):
        name,coarse=full['integrals'][i];fine=first['integrals'][i][1]+second['integrals'][i][1]
        scale=_quiet_absolute(name,policy)+policy.relative_tolerance*max(abs(coarse),abs(fine))
        value=abs(fine-coarse)/scale
        if value>result:dominant='INTEGRAL:'+name
        result=max(result,value)
    if not c_isfinite(result):raise ValueError('quiet nonfinite error norm')
    _reason_v5(role,'norm_evaluations')
    if result>1:
        _reason_v5(role,'error_norm_above_one')
        if dominant is not None:_reason_named_v5(role,'dominant_components',dominant)
    return result

cdef object _quiet_trial(_TypedQuietPlan p,_TypedQuietState q,object left,object right):
    cdef IndexedStatic m=p.model
    cdef TypedDynamic d=q.dynamic
    cdef int i
    cdef object chosen,changed,forcing,boundary,data,next_environment,environment_before,reason,part,record
    cdef object physical=p.physical
    cdef double start_solar,end_solar
    from .integration_time import RationalSeconds
    from .lifecycle_physics import _Refusal
    chosen,changed=_quiet_decision(p,q,left)
    q.service=chosen
    reason=_quiet_temperature_reason(p,q,True)
    if reason is not None:raise _Refusal(reason)
    forcing=_typed_forcing_at(p.world,left,right)
    environment_before=None if q.environment is None else dict(q.environment)
    next_environment=_quiet_environment_propose(p,q,left,right,forcing)
    epsilon,conductance=_quiet_effective(p,q.environment)
    if p.env_policy is not None:physical.environment_ageing_work.effective_networks+=1
    legacy_loss=(physical.inputs.solar_retention_loss_per_second*float(right-left)
                 if p.env_policy is None else 0.)
    boundary=dict(start=left,end=right,duration=RationalSeconds.from_fraction(right-left),
        mode=chosen['mode'],loads=forcing['loads'],essential_indices=(0,1),communications_index=4,
        incidence=forcing['incidence'],sunlit=forcing['sunlit'],emissivity=epsilon,conductance=conductance,
        adjustments=tuple(0. for i in range(m.n)),external_heat=forcing['external_heat'],
        sink_values=forcing['sink_values'],start_temperature_values=tuple(d.t[i] for i in range(m.n)),
        solar_loss=None if legacy_loss==0 else legacy_loss)
    physical.runtime_work.charge('physical_reserved_calls',1,physical.inputs.limits)
    try:
        data=_coupled_cut(m,d,boundary,physical.service_allocation_work,physical.battery_port_work,
            physical.construction.work,physical.inputs.construction_limits)
    except BatteryPortDomainError as error:
        raise _Refusal('BATTERY_PORT_DOMAIN_REFUSED:'+str(error)) from error
    except CoupledDomainRefusal as error:
        from .lifecycle_typed_state import materialize_quiet_service_refusal
        diagnostic=materialize_quiet_service_refusal(p.static,p.world,forcing,error.data,left,right,
            chosen['mode'],d.solar,domain=True)
        raise _Refusal('UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY',
            diagnostic=('PAID_PRIVATE_SERVICE_PROPOSAL_NOT_PUBLISHED',diagnostic)) from error
    except CoupledElectricalRefusal as error:
        from .lifecycle_typed_state import materialize_quiet_service_refusal
        diagnostic=materialize_quiet_service_refusal(p.static,p.world,forcing,error,left,right,
            chosen['mode'],d.solar,domain=False)
        raise _Refusal('CONSTRUCTION_ELECTRICAL_REFUSED:'+str(error),
            diagnostic=('PAID_PRIVATE_ELECTRICAL_REFUSAL',diagnostic)) from error
    except ElectricalLimitError as error:
        raise _Refusal('CONSTRUCTION_ELECTRICAL_REFUSED:'+str(error)) from error
    except BaseException:
        physical.runtime_work.physical_work_unknown_events+=1
        raise
    physical.runtime_work.physical_completed_calls+=1
    physical.service_allocation_work.selected_coupled_calls+=1
    data['mode']=chosen['mode']
    if p.env_policy is not None:
        start_solar=_quiet_retention(p,q.environment);end_solar=_quiet_retention(p,next_environment)
        data['solar']=(start_solar,start_solar-end_solar,end_solar)
        data['environment_before']=environment_before;data['environment_after']=dict(next_environment)
        q.environment=next_environment
    else:
        data['environment_before']=None;data['environment_after']=None
    reason=_quiet_temperature_reason(p,q,False,data)
    if reason is not None:
        # Reconstruct only an actual refused proposal's original complete
        # diagnostic from retained arithmetic. No forcing or physics replay.
        from .lifecycle_typed_state import materialize_quiet_failure_part
        record=(left,right,forcing,data,None,None,q.port_steps+1)
        part=materialize_quiet_failure_part(p.static,physical,p.origin,p.hardware,p.pending,p.world,
            q.history+(record,))
        raise _Refusal(reason,diagnostic=('PAID_PRIVATE_ENDPOINT_NOT_PUBLISHED',right,part))
    # Transfer the detached successful candidate into private scratch. No
    # actual SimulationContext or selected history has been published yet.
    d.energy=data['reconciliation'][4];d.retention=data['degradation'][1]
    d.throughput=data['degradation'][4];d.solar=data['solar'][2]
    for i in range(m.n):d.t[i]=data['thermal'][i][1]
    d.damage=data['next_port']['damage'];d.weighted=data['next_port']['weighted']
    d.chemical=data['next_port']['chemical'];d.ohmic=data['next_port']['ohmic'];d.converter=data['next_port']['converter']
    d.exact=(right,q.port_steps+1);q.port_clock=right;q.port_steps+=1
    q.measured=True;q.last_voltage=data['selected']['port'][19];q.last_current=data['selected']['port'][18]
    q.last_resistance=data['selected']['port'][17];q.last_ocv=data['selected']['port'][16]
    _quiet_commit_service(p,q,chosen,bool(changed),right-left,data)
    record=(left,right,forcing,data,dict(q.service),dict(q.service_work),q.port_steps)
    q.history=q.history+(record,)
    return dict(state=q,sample=_quiet_sample_data(p,q,data),selected=record)

cdef void _quiet_validate_sample(object sample) except *:
    # Original QuietSample validation without constructing discarded records.
    for values in (sample['state_values'],sample['integrals']):
        if type(values)is not tuple or not values or len(values)>128:
            raise ValueError('bounded quiet metric vector required')
        keys=[]
        for key,value in values:
            if (type(key)is not str or not key or len(key)>200 or
                    type(value)not in(int,float)or not c_isfinite(float(value))):
                raise ValueError('finite named quiet metric required')
            keys.append(key)
        if len(set(keys))!=len(keys):raise ValueError('duplicate quiet metric')
    if (type(sample['regime'])is not tuple or len(sample['regime'])>32 or
            any(type(x)not in(str,int,bool)for x in sample['regime'])or type(sample['near_guard'])is not bool):
        raise ValueError('bounded exact quiet regime required')

cdef void _quiet_complete_v5(object initial,object sample,object policy,object integrals=None) except *:
    cdef object name,value,scale
    _quiet_validate_sample(sample)
    if (tuple(k for k,v in initial)!=tuple(k for k,v in sample['state_values']) or
            integrals is not None and tuple(k for k,v in sample['integrals'])!=integrals):
        raise ValueError('quiet metric authority/order changed before short-circuit')
    for name,value in (*initial,*sample['state_values'],*sample['integrals']):
        scale=_quiet_absolute(name,policy)
        if not c_isfinite(scale) or scale<=0:raise ValueError('quiet invalid metric units before short-circuit')


cdef object _quiet_call(_TypedQuietPlan p,_TypedQuietState q,object left,object right,object kind,object stage):
    cdef object work=p.physical.quiet_work,before,outcome='unexpected_error'
    from .lifecycle_physics import _Refusal
    from .lifecycle_quiet import QuietTrialRefusal,_reason_begin_v5,_reason_end_v5,_reason_named_v5
    work.reserve(kind,p.policy)
    if p.short_circuit:work.performed(stage)
    before=_reason_begin_v5(p.reason_role,kind)
    try:
        try:result=_quiet_trial(p,q,left,right)
        except _Refusal as error:
            work.refused_leaf_calls+=1;outcome='known_refusal'
            _reason_named_v5(p.reason_role,'known_refusals',getattr(error,'reason',type(error).__name__))
            raise QuietTrialRefusal(error) from error
        except BaseException:
            work.unknown_leaf_calls+=1
            raise
        work.returned_leaf_calls+=1
        _quiet_validate_sample(result['sample']);outcome='returned'
        return result
    finally:_reason_end_v5(p.reason_role,kind,before,outcome)


cdef object _quiet_interval(_TypedQuietPlan p,_TypedQuietState origin,object start,object end,object controller):
    cdef object work=p.physical.quiet_work,policy=p.policy,current=origin,clock=start
    cdef object selected=[],proposal=controller.next_step_seconds,last_step=Fraction(0),phase=controller.phase
    cdef object remaining,h,trial,full,first,second,initial,integrals,why
    cdef int attempts=0
    cdef double max_error=0.,last_error=controller.last_error_norm,error
    cdef bint admissible,mismatch
    from .lifecycle_quiet import (QuietControllerState,QuietTrialRefusal,_reason_v5,
        _reason_sample_v5,_reason_regime_v5,_quiet_initial_metrics_v5)
    controller.validate(policy,clock=start);work.validate(policy)
    if end<=start or end-start>120:raise ValueError('bounded advancing quiet interval required')
    while clock<end:
        remaining=end-clock;h=min(Fraction(proposal),remaining)
        if h<proposal:
            _reason_v5(p.reason_role,'shortened_boundary_proposals')
            if p.short_circuit:work.shortened_boundary_proposals+=1
        if h<policy.minimum_macro_seconds:
            _reason_v5(p.reason_role,'below_minimum_fallbacks')
            if p.short_circuit:work.below_minimum_fallbacks+=1
            h=min(remaining,Fraction(policy.detailed_seconds))
            trial=_quiet_call(p,_quiet_clone(current),clock,clock+h,'detailed_fallback','detailed')
            selected.append(trial['selected']);work.select(h)
            current=trial['state'];clock+=h;last_step=h;phase='DETAILED_FALLBACK'
        else:
            attempts+=1
            if attempts>policy.max_trials_per_interval:raise ValueError('QUIET_LOCAL_TRIAL_QUOTA')
            work.proposed_macros+=1;initial=_quiet_values(p,current)
            if p.short_circuit:_quiet_initial_metrics_v5(initial,policy)
            if h==policy.minimum_macro_seconds:
                _reason_v5(p.reason_role,'minimum_macro_proposals')
                if p.short_circuit:work.minimum_macro_proposals+=1
            try:
                full=_quiet_call(p,_quiet_clone(current),clock,clock+h,'full_trial','full')
                _reason_sample_v5(p.reason_role,'full',full['sample'],work)
                if p.short_circuit:
                    _quiet_complete_v5(initial,full['sample'],policy)
                    integrals=tuple(k for k,v in full['sample']['integrals'])
                if p.short_circuit and full['sample']['near_guard']:
                    work.early('full_near');_reason_v5(p.reason_role,'early_full_near');_reason_v5(p.reason_role,'skipped_half_trials',2)
                    admissible=False
                else:
                    first=_quiet_call(p,_quiet_clone(current),clock,clock+h/2,'half_trial','first')
                    if p.short_circuit:_quiet_complete_v5(initial,first['sample'],policy,integrals)
                    _reason_sample_v5(p.reason_role,'first',first['sample'],work)
                    mismatch=_reason_regime_v5(p.reason_role,'full','first',full['sample'],first['sample'],work)
                    if p.short_circuit and(first['sample']['near_guard'] or mismatch):
                        why='first_near'if first['sample']['near_guard']else'first_regime'
                        work.early(why);_reason_v5(p.reason_role,'early_'+why);_reason_v5(p.reason_role,'skipped_half_trials')
                        admissible=False
                    else:
                        second=_quiet_call(p,first['state'],clock+h/2,clock+h,'half_trial','second')
                        if p.short_circuit:_quiet_complete_v5(initial,second['sample'],policy,integrals)
                        _reason_sample_v5(p.reason_role,'second',second['sample'],work)
                        _reason_regime_v5(p.reason_role,'full','second',full['sample'],second['sample'],work)
                        _reason_regime_v5(p.reason_role,'first','second',first['sample'],second['sample'],work)
                        error=_quiet_error(initial,full['sample'],first['sample'],second['sample'],policy,p.reason_role)
                        if p.short_circuit:work.norm_evaluations+=1;work.norm_rejections+=int(error>1.)
                        admissible=(full['sample']['regime']==first['sample']['regime']==second['sample']['regime'] and
                            not any(x['sample']['near_guard'] for x in(full,first,second)) and error<=1.)
            except QuietTrialRefusal:
                work.rejected_macros+=1
                if h<=policy.minimum_macro_seconds:
                    proposal=policy.minimum_macro_seconds;h=min(remaining,Fraction(policy.detailed_seconds))
                    _reason_v5(p.reason_role,'minimum_macro_fallbacks')
                    if p.short_circuit:work.minimum_macro_fallbacks+=1
                    trial=_quiet_call(p,_quiet_clone(current),clock,clock+h,'detailed_fallback','detailed')
                    selected.append(trial['selected']);work.select(h)
                    current=trial['state'];clock+=h;last_step=h;phase='DETAILED_FALLBACK'
                else:proposal=max(policy.minimum_macro_seconds,int(h)//2)
                if len(selected)>policy.max_selected_parts:raise ValueError('QUIET_SELECTED_EVIDENCE_QUOTA')
                continue
            if not admissible:
                work.rejected_macros+=1
                if h>policy.minimum_macro_seconds:
                    proposal=max(policy.minimum_macro_seconds,int(h)//2);continue
                _reason_v5(p.reason_role,'minimum_macro_fallbacks')
                if p.short_circuit:work.minimum_macro_fallbacks+=1
                h=min(remaining,Fraction(policy.detailed_seconds))
                trial=_quiet_call(p,_quiet_clone(current),clock,clock+h,'detailed_fallback','detailed')
                selected.append(trial['selected']);work.select(h)
                current=trial['state'];clock+=h;last_step=h;phase='DETAILED_FALLBACK';proposal=policy.minimum_macro_seconds
            else:
                work.accepted_macros+=1;selected.extend((first['selected'],second['selected']))
                work.select(h/2);work.select(h/2)
                current=second['state'];clock+=h;last_step=h;last_error=error;max_error=max(max_error,error);phase='ACCEPTED'
                work.maximum_accepted_error_norm=max(work.maximum_accepted_error_norm,error)
                if error<=.25:proposal=min(policy.maximum_macro_seconds,max(proposal,int(h)*2))
        if len(selected)>policy.max_selected_parts:raise ValueError('QUIET_SELECTED_EVIDENCE_QUOTA')
    next_controller=QuietControllerState(end,proposal,last_step,last_error,phase,policy.method)
    next_controller.validate(policy,clock=end);work.validate(policy)
    return current,selected,next_controller,max_error


cdef _TypedQuietPlan _quiet_plan(object physical,object hardware,object pending,object static,object world):
    cdef _TypedQuietPlan p=_TypedQuietPlan.__new__(_TypedQuietPlan)
    cdef int i
    from .lifecycle_typed_state import TypedStatic
    from .lifecycle_quiet import BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy
    from .lifecycle_physics import LifecyclePhysicalState,PendingLifecycleAction
    from .lifecycle_typed_context import TypedBackendContext
    from .harness_hardware import EffectiveAssemblyHardware
    if type(static)is not TypedStatic:raise TypeError('B64 exact typed quiet static authority')
    static._check_identity()
    if (type(physical)is not LifecyclePhysicalState or type(hardware)is not EffectiveAssemblyHardware or
            type(pending)is not PendingLifecycleAction or type(physical.backend_context)is not TypedBackendContext):
        raise TypeError('B64 exact typed quiet physical/hardware/pending authority')
    context=physical.backend_context
    context._guard_activation();context._role(physical)
    if context._typed is not static or physical.harness.hardware is not hardware:
        raise ValueError('B64 foreign quiet static/hardware authority')
    if pending.kind not in('HOLD_UNTIL','SOLAR_HOLD')or pending.slew is not None or pending.payload_w!=0:
        raise ValueError('quiet integration requires a stationary, unloaded HOLD')
    if type(physical.inputs.quiet_policy)not in(BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy):
        raise ValueError('B64 port/environment typed quiet domain')
    p.model=static.compiled;p.static=static;p.physical=physical;p.hardware=hardware;p.pending=pending
    p.policy=physical.inputs.quiet_policy;p.service_policy=physical.inputs.service_policy;p.env_policy=physical.inputs.environment_ageing_policy
    from .lifecycle_quiet import is_short_circuit_policy,quiet_work_type
    p.short_circuit=is_short_circuit_policy(p.policy)
    if type(physical.quiet_work)is not quiet_work_type(p.policy):raise TypeError('matching versioned quiet work required')
    p.reason_role=physical.prepared_runtime.role if physical.prepared_runtime is not None else 'REFERENCE'
    if p.reason_role not in('ACTUAL','FORECAST','REFERENCE'):raise ValueError('exact quiet diagnostic role')
    if world is None:p.world=_typed_prepare_world(physical,hardware,pending)
    else:
        if type(world)is not TypedWorldPlan:raise TypeError('B64 exact compiled quiet world authority')
        p.world=world
        if p.world.data['physical'] is not physical or p.world.data['pending'] is not pending:
            raise ValueError('B64 foreign quiet world physical/pending authority')
    p.world.validate()
    required=set(physical.inputs.protection.standby_node_ids)
    for i in range(p.model.n):
        n=static.configuration.thermal_network.nodes[i]
        p.operating_min[i]=_number(n.operating_min_temperature_k.value,'operating min')
        p.operating_max[i]=_number(n.operating_max_temperature_k.value,'operating max')
        p.survival_min[i]=_number(n.survival_min_temperature_k.value,'survival min')
        p.survival_max[i]=_number(n.survival_max_temperature_k.value,'survival max')
        p.required[i]=n.node_id in required
    if p.env_policy is None:
        p.node_laws=tuple(None for i in range(p.model.n));p.link_laws=tuple(None for i in range(p.model.l))
    else:
        node_by={x.node_id:x for x in p.env_policy.emissivity};link_by={x.link_id:x for x in p.env_policy.conductance}
        p.node_laws=tuple(node_by.get(n.value) for n in static.ids)
        p.link_laws=tuple(link_by.get(n.value) for n in static.links)
    return p

cdef _TypedQuietState _quiet_initial(_TypedQuietPlan p,object candidate):
    cdef _TypedQuietState q=_TypedQuietState.__new__(_TypedQuietState)
    from .lifecycle_typed_state import _dynamic
    physical=p.physical;port=physical.battery_port_state
    q.dynamic=_dynamic(p.static,candidate,port)
    q.service={n:getattr(physical.service_state,n)for n in physical.service_state.__dataclass_fields__}
    q.service_work={n:getattr(physical.service_work,n)for n in physical.service_work.__dataclass_fields__}
    history=physical.environment_ageing_state
    q.environment=None if history is None else {n:getattr(history,n)for n in history.__dataclass_fields__}
    physical.service_state.__post_init__();physical.service_work.__post_init__()
    physical.inputs.service_policy.__post_init__()
    if history is not None:history.__post_init__()
    q.history=()
    q.measured=port.last_voltage_v is not None
    q.last_voltage=0. if not q.measured else port.last_voltage_v;q.last_current=0. if not q.measured else port.last_current_a
    q.last_resistance=0. if not q.measured else port.last_resistance_ohm;q.last_ocv=0. if not q.measured else port.last_ocv_v
    q.port_clock=port.clock_seconds;q.port_steps=port.selected_steps
    return q

def integrate_quiet_hold(physical,candidate,hardware,start,end,pending,*,compiled_static,world_plan=None):
    """Closed, callback-free bounded HOLD engine over current private arrays."""
    cdef _TypedQuietPlan p
    cdef _TypedQuietState current
    cdef object selected=[],controller=physical.quiet_controller,points,left,right,parts
    from .lifecycle_quiet import QuietTrialRefusal
    from .context import SimulationContext
    _enter(8)
    if type(start)is not Fraction or type(end)is not Fraction:raise ValueError('B64 exact quiet support')
    p=_quiet_plan(physical,hardware,pending,compiled_static,world_plan)
    if type(candidate)is not SimulationContext or candidate.inputs is not physical.inputs.simulation_inputs:
        raise ValueError('B64 foreign quiet candidate context authority')
    p.origin=candidate
    p.temperature_order=tuple(compiled_static.ids.index(n.node_id)for n in candidate.spacecraft_state.thermal.node_states)
    current=_quiet_initial(p,candidate)
    points=_typed_support_points(p.world,start,end)
    try:
        for left,right in zip(points,points[1:]):
            current,parts,controller,maximum=_quiet_interval(p,current,left,right,controller)
            selected.extend(parts)
            if len(selected)>physical.inputs.limits.max_retained_cuts:
                from .lifecycle_physics import _Refusal
                raise _Refusal('LIFECYCLE_LOCAL_ACTION_PARTITION_LIMIT')
    except QuietTrialRefusal as error:raise error.original from error
    from .lifecycle_typed_state import materialize_quiet_result
    return materialize_quiet_result(compiled_static,physical,candidate,hardware,pending,p.world,
        selected,current.service,current.service_work,current.environment,controller)


def quiet_reason_counts_v5():
    """Nonnumerical read of bounded process aggregates; no execution authority."""
    from .lifecycle_quiet import quiet_reason_counts_v5 as snapshot
    return snapshot()
