"""V6 actual metrics: retain producer scope and exact rational sums.

Missing counters stay UNKNOWN. Credits never stand in for acquired/delivered
action counts, refusal causes, thermal ageing or a spatial thermal model.
The older YEAR metric protocol remains byte-compatible with saved receipts.
"""
from .year_metrics import actual as year_actual,UNKNOWN
from .data import read_bytes,parse,digest
from .errors import Refusal

def engineering(preparation,*,source_identity,physical_spec_identity):
    answer=dict(recorded=preparation.get('engineering_evidence',UNKNOWN),
        source=preparation.get('CORE_flat_job',preparation.get('CORE_job',UNKNOWN)),
        mass_properties=UNKNOWN,functional_composition=UNKNOWN,routes=UNKNOWN,thermal_plant=UNKNOWN,
        qualification='Only genuine compiled/paid records; source600s mechanical reference is not pilot or mission science')
    reference=preparation.get('source_engineering_report');evidence=preparation.get('source_engineering_evidence')
    if not isinstance(reference,dict)or not isinstance(evidence,dict):return answer
    raw=read_bytes(reference['path'],2*2**20)
    if (digest(raw)!=reference['sha256']or len(raw)!=reference['bytes']or parse(raw,2*2**20)!=evidence or
        evidence.get('source_identity')!=source_identity or evidence.get('specification_identity')!=physical_spec_identity or
        evidence.get('project_identity')!=preparation['authored_project_sha256']):raise Refusal('NINETY_MECHANICAL_REPORT_SOURCE_AUTHORED_PHYSICAL_BINDING')
    mass=evidence.get('mass',{})
    if preparation.get('model_mass_kg')is not None and mass.get('total_mass_kg')!=preparation['model_mass_kg']:raise Refusal('NINETY_ACTUAL_JOB_AND_SAME_SPEC_MASS_JOIN')
    answer.update(mass_properties=mass or UNKNOWN,routes=evidence.get('routes',UNKNOWN),thermal_plant=evidence.get('thermal_plant',UNKNOWN),
        functional_composition={k:evidence.get(k,UNKNOWN)for k in('nominal_battery_wh','nominal_pv_w','initial_energy_wh')},
        mechanical_reference=reference,mechanical_reference_basis=preparation.get('engineering_basis',UNKNOWN),
        authoring_assumptions=evidence.get('authoring',UNKNOWN),seed_support_duration_seconds=600,own_admitted_root_not_relabelled=True)
    return answer

def _value(mapping,key):
    value=mapping.get(key)
    return UNKNOWN if value is None else value

def actual(science,*,start,end,target,role,declared_mass=None):
    value=year_actual(science,start=start,end=end,target=target,role=role,declared_mass=declared_mass)
    totals=(science.get('report')or{}).get('totals')or{}
    # Counts must be independently recorded as counts, not inferred from score.
    value['delivered_on_time']=_value(totals,'delivered_on_time_actions')
    if value['delivered_on_time']==UNKNOWN:value['delivered_on_time']=_value(totals,'delivered_on_time')
    for out,key in (('expired','expired'),('completed_actions','completed_actions'),
                    ('delivered','delivered_actions'),('score','credits'),
                    ('start_energy_wh','start_energy_wh'),('SOC_start','start_soc'),
                    ('SOC_minimum','minimum_soc'),('SOC_end','end_soc')):
        value[out]=_value(totals,key)
    sums=totals.get('sums')or{}
    for key in ('unmet_load_wh','wire_loss_wh','calendar_damage','cycling_damage','throughput_wh','capacity_clip_wh'):
        value[key]=_value(sums,key)
    value['sums_representation']='EXACT_PRODUCER_VALUES_RATIONAL_PAIRS_PRESERVED'
    value['temperatures_minimum_by_node_k']=_value(totals,'minimum_temperature_k')
    value['temperatures_maximum_by_node_k']=_value(totals,'maximum_temperature_k')
    port=totals.get('battery_port')or{}
    qualified=port.get('method')=='B58_SELECTED_SAMPLED_PORT_REPORT_V1'and port.get('scope')=='SELECTED_START_HELD_SAMPLES_NOT_CONTINUOUS_BOUNDS'
    for out,key in (('maximum_abs_current_a','maximum_abs_current_a'),
                    ('minimum_resistance_ohm','minimum_resistance_ohm'),('maximum_resistance_ohm','maximum_resistance_ohm')):
        value[out]=_value(port,key)if qualified else UNKNOWN
    value['electrical_extrema_scope']=port.get('scope',UNKNOWN)if qualified else UNKNOWN
    value['battery_port_last']=_value(port,'last')if qualified else UNKNOWN
    wear_start=totals.get('wear_start')or{};wear_end=totals.get('wear_end')or{}
    value['battery_capacity_retention']=dict(start=_value(wear_start,'battery_retention'),end=_value(wear_end,'battery_retention'))
    value['PV_retention']=dict(start=_value(wear_start,'solar_retention'),end=_value(wear_end,'solar_retention'))
    value['wear_start']=wear_start or UNKNOWN;value['wear_end']=wear_end or UNKNOWN
    value['thermal_ageing']=_value(totals,'thermal_ageing')
    report=science.get('report')or{}
    value['environment_ageing']=_value(report,'environment_ageing')
    value['lifetime_environment']=_value(report,'lifetime_environment')
    value['metrics_protocol']='KAZE_NINETY_ACTUAL_METRICS_V1'
    return value

def thirty_day_summaries(scientific_observations,*,anchor=128):
    """Use genuine interval reports only; a cumulative tip cannot give extrema
    of a later month. No resimulation or subtraction of cumulative minima.
    """
    result=[]
    for index in range(3):
        left=anchor+index*30*86400;right=left+30*86400;matches=[]
        for observation in scientific_observations:
            for item in observation.get('monthly_actual',(observation.get('science',{}).get('report')or{}).get('interval_summaries',[])):
                if item.get('start_seconds')==left and item.get('end_seconds')==right:
                    matches.append(dict(recorded=item,source=observation['source']))
        result.append(dict(requested_interval=dict(start_seconds=left,end_seconds=right),
            state='RECORDED'if len(matches)==1 else'UNKNOWN',
            evidence=matches[0]if len(matches)==1 else UNKNOWN,
            qualification='Exact source-owned interval summary only; cumulative extrema are not monthly extrema'))
    return result
