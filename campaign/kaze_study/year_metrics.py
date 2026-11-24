"""Typed actual metrics only. Forecast and missing counters never become refusals."""
from .data import identity

UNKNOWN='UNKNOWN'
# Exact producer keys, deliberately no inference from credits or success ratios.
FIELDS={
 'offered':('offered','offered_actions'),
 'geometry_eligible':('geometry_eligible','geometry_eligible_actions'),
 'acquired':('acquired','acquired_actions'),
 'delivered_on_time':('delivered_on_time','delivered_on_time_actions','credits'),
 'on_time_credits':('credits',), 'delivered_useful_bits':('useful_bits',),
 'energy_min_wh':('minimum_energy_wh',),'energy_end_wh':('end_energy_wh',),
 'voltage_min_v':('minimum_voltage_v',),'voltage_max_v':('maximum_voltage_v',),
 'temperature_min_k':('minimum_temperature_k',),'temperature_max_k':('maximum_temperature_k',),
 'model_mass_kg':('model_mass_kg',),
}

def actual(science,*,start,end,target,role,declared_mass=None):
    totals=(science.get('report')or{}).get('totals')or{}
    answer={}
    for field,keys in FIELDS.items():
        found=[totals[k]for k in keys if k in totals and totals[k]is not None]
        answer[field]=UNKNOWN if not found else found[0]
        if len(found)>1 and len({identity(x)for x in found})>1:answer[field]=UNKNOWN
    refusals=totals.get('actual_refusals_by_reason')
    if refusals is None and totals.get('refusal_scope')=='ACTUAL':refusals=totals.get('refusals_by_reason')
    answer['actual_refusals_by_reason']=refusals if isinstance(refusals,dict) else UNKNOWN
    answer['refusal_total']=totals.get('refused_actions')if totals.get('refused_actions')is not None else UNKNOWN
    if answer['model_mass_kg']==UNKNOWN and declared_mass is not None:
        answer['model_mass_kg']=declared_mass
        answer['model_mass_basis']='MODEL_DECLARED_NOT_MEASURED_FLIGHT_MASS'
    port=totals.get('battery_port')or{}
    if port.get('method')=='B58_SELECTED_SAMPLED_PORT_REPORT_V1'and port.get('scope')=='SELECTED_START_HELD_SAMPLES_NOT_CONTINUOUS_BOUNDS':
        for field,key in (('voltage_min_v','minimum_voltage_v'),('voltage_max_v','maximum_voltage_v')):
            if port.get(key)is not None:answer[field]=port[key]
        answer['voltage_extrema_scope']=port['scope']
    answer['temperature_extrema_scope']=(science.get('report')or{}).get('extrema_scope',UNKNOWN)
    answer.update(covered_interval=dict(start_seconds=start,end_seconds=end),
        requested_end_seconds=target,completeness='COMPLETE'if end==target else 'PARTIAL',
        role=role,primary_counted=role=='PRIMARY',forecast_refusals_included=False,
        diagnostic_credits_added=False)
    return answer

def cumulative_tips(rows):
    """One latest PRIMARY tip per causal run, including benchmark aliases."""
    tips={};diagnostics=[]
    for row in rows:
        if row['role']!='PRIMARY':diagnostics.append(row);continue
        key=row['causal_identity'];old=tips.get(key)
        if old is None or row['actual_end_seconds']>old['actual_end_seconds']:tips[key]=row
    return dict(primary_tips=list(tips.values()),diagnostic=diagnostics,
        duplicate_or_older_tips=len(rows)-len(diagnostics)-len(tips),
        rule='ONE_CUMULATIVE_PRIMARY_CAUSAL_TIP_MAIN_LOUPE_ADD_ZERO')
