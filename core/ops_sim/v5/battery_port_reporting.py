"""Selected support battery-port summaries; no ground access or resume authority."""
from copy import deepcopy
from math import isfinite
from .battery_port import BatteryPortPolicy,BatteryPortState

METHOD='B58_SELECTED_SAMPLED_PORT_REPORT_V1'
EXTREMA=('minimum_voltage_v','maximum_voltage_v','maximum_abs_current_a',
         'minimum_resistance_ohm','maximum_resistance_ohm')
SUMS=('ohmic_heat_wh','converter_loss_wh','chemical_throughput_wh')
FIELDS={'method','policy_identity','scope','selected_steps','limits','last',*EXTREMA,*SUMS}

def port_report_blank(policy):
    if type(policy)is not BatteryPortPolicy:raise TypeError('port report policy')
    return dict(method=METHOD,policy_identity=policy.identity,
        scope='SELECTED_START_HELD_SAMPLES_NOT_CONTINUOUS_BOUNDS',selected_steps=0,
        limits=dict(minimum_terminal_voltage_v=policy.minimum_terminal_voltage_v,
            maximum_terminal_voltage_v=policy.maximum_terminal_voltage_v,
            maximum_charge_current_a=policy.maximum_charge_current_a,
            maximum_discharge_current_a=policy.maximum_discharge_current_a),
        last=None,**{n:None for n in EXTREMA},**{n:0. for n in SUMS})

def port_report_part(target,battery,state_after):
    """One committed physical cut only, never proposed allocation/quiet work."""
    if battery['method']!='B58_ASSUMED_ENERGY_SOC_RINT_PACK_V1':raise ValueError('port transition method')
    v=battery['terminal_voltage_v'];r=battery['resistance_ohm'];i=abs(battery['current_a'])
    values=(v,v,i,r,r)
    for n,value in zip(EXTREMA,values):
        if target[n]is None:target[n]=value
        else:target[n]=(min if n.startswith('minimum')else max)(target[n],value)
    for n in SUMS:target[n]+=battery[n]
    target['selected_steps']+=1
    target['last']=deepcopy(state_after)
    from fractions import Fraction as Q
    for name in ('clock_seconds','last_support_start_seconds'):
        value=target['last'][name]
        if type(value)is Q:target['last'][name]=dict(numerator=value.numerator,denominator=value.denominator)

def port_report_combine(rows):
    out=deepcopy(rows[0]);out['selected_steps']=sum(r['selected_steps']for r in rows)
    for name in SUMS:out[name]=sum(r[name]for r in rows)
    for name in EXTREMA:
        values=[r[name]for r in rows if r[name]is not None]
        out[name]=None if not values else (min if name.startswith('minimum')else max)(values)
    out['last']=next((deepcopy(r['last'])for r in reversed(rows)if r['last']is not None),None)
    return out

def validate_port_report(data,policy):
    if type(data)is not dict or set(data)!=FIELDS:raise ValueError('strict port report fields')
    blank=port_report_blank(policy)
    if any(data[n]!=blank[n]for n in ('method','policy_identity','scope','limits')):raise ValueError('port report binding')
    if type(data['selected_steps'])is not int or not 0<=data['selected_steps']<=2**48:raise ValueError('port report count')
    for n in SUMS:
        if type(data[n])not in(int,float)or not isfinite(data[n])or data[n]<0:raise ValueError('finite port heat/throughput')
    for n in EXTREMA:
        value=data[n]
        if value is not None and(type(value)not in(int,float)or not isfinite(value)or value<0):raise ValueError('finite port extrema')
        if (value is None)!=(data['selected_steps']==0):raise ValueError('port samples/extrema')
    if data['selected_steps']:
        if data['minimum_voltage_v']>data['maximum_voltage_v']or data['minimum_resistance_ohm']>data['maximum_resistance_ohm']:raise ValueError('ordered port extrema')
        if type(data['last'])is not dict or set(data['last'])!=set(BatteryPortState.__dataclass_fields__):raise ValueError('strict selected port endpoint')
        from fractions import Fraction as Q
        state=dict(data['last'])
        for name in ('clock_seconds','last_support_start_seconds'):
            if state[name]is not None:
                q=state[name]
                if type(q)is not dict or set(q)!={'numerator','denominator'}or any(type(x)is not int for x in q.values()):raise ValueError('strict report port time')
                state[name]=Q(q['numerator'],q['denominator'])
                if state[name].numerator!=q['numerator']or state[name].denominator!=q['denominator']:raise ValueError('canonical report port time')
        selected=BatteryPortState(**state)
        if selected.resistance_damage>policy.maximum_resistance_damage:raise ValueError('report port damage domain')
    elif data['last']is not None:raise ValueError('empty port report cannot hold endpoint')
    return data

def port_projection(policy,state):
    if policy is None:return dict(status='UNAVAILABLE',reason='LEGACY_WH_ONLY_NO_PACK_VOLTAGE_MODEL')
    if state is None:return None
    from dataclasses import asdict
    from fractions import Fraction
    if type(state)is not BatteryPortState:raise TypeError('port projection state')
    data=asdict(state)
    for key,value in data.items():
        if type(value)is Fraction:data[key]=dict(numerator=value.numerator,denominator=value.denominator)
    return dict(status='AVAILABLE_SAMPLED_MODEL',policy_identity=policy.identity,
        sensor_assumption=policy.bms_sensor,pack_measurements=data,regulated_bus_voltage='SEPARATE_CONSTRUCTION_AUTHORITY')


def validate_port_progress(data,root,clock):
    """Strict saved-data admission; no physics or present-state ground query."""
    from fractions import Fraction as Q
    policy=root.battery_port_policy
    expected={'actual','received','estimated','observed_at_seconds','received_at_seconds','sampled_report','knowledge_scope'}
    if type(data)is not dict or set(data)!=expected or policy is None:raise ValueError('port progress fields/root')
    if data['knowledge_scope']!='RECEIVED_PACKETS_AND_PAID_CATCHUP_ONLY':raise ValueError('port knowledge scope')
    observed=data['observed_at_seconds'];received=data['received_at_seconds']
    if type(observed)is not int or type(received)is not int or not root.start_seconds<=observed<=received<=clock:raise ValueError('received port time')
    def measurement(value,at,optional=False):
        if value is None and optional:return
        template=port_projection(policy,BatteryPortState(Q(at)))
        if type(value)is not dict or set(value)!=set(template)or any(value[k]!=template[k]for k in template if k!='pack_measurements'):raise ValueError('strict port measurement binding')
        raw=value['pack_measurements']
        if type(raw)is not dict or set(raw)!=set(BatteryPortState.__dataclass_fields__):raise ValueError('strict port measurement fields')
        raw=dict(raw)
        for key in ('clock_seconds','last_support_start_seconds'):
            if raw[key]is not None:
                q=raw[key]
                if type(q)is not dict or set(q)!={'numerator','denominator'}or any(type(x)is not int for x in q.values()):raise ValueError('strict sampled port rational')
                raw[key]=Q(q['numerator'],q['denominator'])
                if raw[key].numerator!=q['numerator']or raw[key].denominator!=q['denominator']:raise ValueError('canonical sampled port time')
        state=BatteryPortState(**raw)
        if not root.start_seconds<=state.clock_seconds<=clock or not optional and state.clock_seconds!=at:raise ValueError('sampled port clock')
        if state.resistance_damage>policy.maximum_resistance_damage:raise ValueError('port damage domain')
    measurement(data['actual'],clock);measurement(data['received'],observed);measurement(data['estimated'],clock,True)
    validate_port_report(data['sampled_report'],policy)
    return data
