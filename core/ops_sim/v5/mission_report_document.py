"""Strict bounded data-only report publication; never a physics seed.

The rows are the authority for summary aggregates.  Admission establishes
internal consistency, not independent physical truth.  Offered/expired events
have no timestamps in this V1 format; root-bound restoration separately checks
their declared request metadata without evaluating the physical model.
"""
from fractions import Fraction
import math
from .experiment_codec import object_fields, parse_json
from .rolling_snapshot_document import canonical
from .rolling_cache import canonical_size
from .mission_report import METHOD, SUMS

STATE_FIELDS=('method','root_identity','offset_seconds','period_seconds','start_seconds','end_seconds','cursor','base_cursor',
    'seen_actions','seen_receipts','seen_offered','seen_expired','sealed','current','control_units','control_reserved_units','detail_bytes','status')
ROW_FIELDS=('bucket','start_seconds','end_seconds','seal','offered','credits','expired','actions','refused_actions',
    'executed_point_seconds','minimum_energy_wh','end_energy_wh','maximum_temperature_k','sums','wear_start','wear_end','soc',
    'delivered_useful_bits','credits_count','priority_numerator','priority_denominator')
SUMMARY_FIELDS=('method','root_identity','status','start_seconds','end_seconds','month_semantics','epoch_offset_seconds',
    'period_seconds','coverage','rows','totals','extrema_scope','control_units','control_reserved_units','coordinator_history')
TOTAL_FIELDS=('offered','credits','useful_bits','priority_numerator','priority_denominator','priority_score','refused_actions',
    'expired_requests','executed_point_seconds','minimum_energy_wh','end_energy_wh','maximum_temperature_k','sums')
MAX_BYTES=2**20


def whole(v,lo=0,hi=2**40):
    if type(v) is not int or not lo<=v<=hi:raise ValueError('report exact bounded integer')
    return v


def finite(v,nonnegative=True):
    if type(v) not in (int,float):raise ValueError('report finite scalar')
    try:valid=math.isfinite(v)
    except OverflowError:valid=False
    if not valid or nonnegative and v<0:raise ValueError('report finite scalar')
    return v


def identifier(v):
    if type(v) is not str or not 1<=len(v)<=1024:raise ValueError('report exact identity')
    v.encode('utf-8',errors='strict')
    return v


def rational(value):
    if type(value) is not list or len(value)!=2 or any(type(x) is not str or len(x)>1024 for x in value):raise ValueError('report exact sum')
    try:q=Fraction(int(value[0]),int(value[1]))
    except (ValueError,ZeroDivisionError):raise ValueError('report exact sum') from None
    if [str(q.numerator),str(q.denominator)]!=value:raise ValueError('report canonical sum')
    return q


def _nonnegative_rational(value):
    q=rational(value)
    if q<0:raise ValueError('report negative exact quantity')
    return q


def _thermal(values):
    if type(values) is not dict or not 1<=len(values)<=16:raise ValueError('report thermal nodes')
    for key,value in values.items():identifier(key);finite(value)


def _wear(wear):
    object_fields(wear,('battery','solar'))
    object_fields(wear['battery'],('usable_capacity_retention','cumulative_energy_throughput_wh'))
    object_fields(wear['solar'],('generation_retention',))
    for value in (*wear['battery'].values(),*wear['solar'].values()):finite(value)
    if wear['battery']['usable_capacity_retention']>1 or wear['solar']['generation_retention']>1:raise ValueError('report retention domain')


def validate_row(row):
    object_fields(row,ROW_FIELDS);object_fields(row['sums'],SUMS)
    for value in row['sums'].values():_nonnegative_rational(value)
    whole(row['bucket'],-2**40)
    for name in ('start_seconds','end_seconds','actions','refused_actions','executed_point_seconds','credits_count'):whole(row[name])
    if row['start_seconds']>row['end_seconds'] or row['refused_actions']>row['actions'] or row['executed_point_seconds']>row['end_seconds']-row['start_seconds']:raise ValueError('report interval/actions')
    if row['seal'] is not None and (type(row['seal']) is not str or row['seal'] not in ('MONTH_BOUNDARY','PARTIAL_TERMINAL')):raise ValueError('report seal')
    for name in ('minimum_energy_wh','end_energy_wh','delivered_useful_bits','priority_numerator','priority_denominator'):finite(row[name])
    if row['minimum_energy_wh']>row['end_energy_wh']:raise ValueError('report energy extrema')
    if row['priority_denominator']<=0 or row['priority_numerator']>row['priority_denominator']:raise ValueError('report priority weights')
    _thermal(row['maximum_temperature_k'])
    object_fields(row['soc'],('minimum_returned','end_returned','scope'))
    if type(row['soc']['scope']) is not str or row['soc']['scope']!='DERIVED_RETURNED_ENERGY_OVER_RETURNED_CAPACITY_NOT_CONTINUOUS':raise ValueError('report SOC scope')
    low,end=row['soc']['minimum_returned'],row['soc']['end_returned']
    if (low is None)!=(end is None):raise ValueError('report SOC presence')
    if low is not None:
        finite(low);finite(end)
        if not low<=end<=1:raise ValueError('report SOC extrema')
    for name in ('offered','credits','expired'):
        if type(row[name]) is not list or len(row[name])>64:raise ValueError('report event population')
    offered=[];receipts=[];records=[]
    for event in row['offered']:
        object_fields(event,('id','priority'));offered.append(identifier(event['id']));finite(event['priority'])
        if event['priority']<=0:raise ValueError('report positive request priority')
    for event in row['credits']:
        object_fields(event,('request_id','record_ids','completion_time','priority','useful_bits'))
        receipts.append(identifier(event['request_id']))
        if type(event['record_ids']) is not list or not 1<=len(event['record_ids'])<=16:raise ValueError('report custody IDs')
        records.extend(identifier(value) for value in event['record_ids'])
        completion=_nonnegative_rational(event['completion_time'])
        if not row['start_seconds']<=completion<=row['end_seconds']:raise ValueError('report receipt coverage')
        finite(event['priority']);finite(event['useful_bits'])
        if event['priority']<=0 or event['useful_bits']<=0:raise ValueError('report positive credit quantities')
    expired=[identifier(value) for value in row['expired']]
    if any(len(ids)!=len(set(ids)) for ids in (offered,receipts,records,expired)):raise ValueError('duplicate report event/custody')
    if set(receipts)&set(expired):raise ValueError('report credited and expired request')
    if row['credits_count']!=len(row['credits']) or row['delivered_useful_bits']!=sum(x['useful_bits'] for x in row['credits']) or row['priority_numerator']!=sum(x['priority'] for x in row['credits']):raise ValueError('report credit aggregates')
    _wear(row['wear_start']);_wear(row['wear_end'])
    if row['wear_end']['battery']['cumulative_energy_throughput_wh']<row['wear_start']['battery']['cumulative_energy_throughput_wh']:raise ValueError('report throughput direction')
    if row['wear_end']['battery']['usable_capacity_retention']>row['wear_start']['battery']['usable_capacity_retention'] or row['wear_end']['solar']['generation_retention']>row['wear_start']['solar']['generation_retention']:raise ValueError('report retention direction')
    if row['actions']==0 and (row['start_seconds']!=row['end_seconds'] or any(_nonnegative_rational(q) for q in row['sums'].values()) or row['minimum_energy_wh']!=row['end_energy_wh'] or row['wear_start']!=row['wear_end'] or low is not None):raise ValueError('report unexecuted row resources')
    return row


def _header(value,offset_name):
    if type(value['method']) is not str or value['method']!=METHOD or type(value['status']) is not str or value['status'] not in ('ACTIVE','COMPLETE'):raise ValueError('report method/status')
    root=value['root_identity']
    if type(root) is not str or len(root)!=64 or any(c not in '0123456789abcdef' for c in root):raise ValueError('report root hash')
    for name in ('start_seconds','end_seconds','period_seconds'):whole(value[name])
    whole(value[offset_name],-2**40)
    if not 1<=value['period_seconds']<=2592000 or value['start_seconds']>value['end_seconds']:raise ValueError('report calendar domain')


def _rows(rows,*,start,end,offset,period,status):
    if type(rows) is not list or not 1<=len(rows)<=180:raise ValueError('report finite nonempty rows')
    offered={};receipts={};record_ids=set();expired=set();previous=None
    for index,row in enumerate(rows):
        validate_row(row)
        if row['start_seconds']!=(start if previous is None else previous['end_seconds']):raise ValueError('report chronological contiguous coverage')
        if row['bucket']!=(row['start_seconds']+offset)//period:raise ValueError('report bucket identity')
        boundary=(row['bucket']+1)*period-offset
        if row['end_seconds']>boundary:raise ValueError('report row crosses bucket')
        last=index==len(rows)-1
        expected='MONTH_BOUNDARY' if row['end_seconds']==boundary else ('PARTIAL_TERMINAL' if status=='COMPLETE' and last else None)
        if row['seal']!=expected or not last and expected!='MONTH_BOUNDARY' or status=='ACTIVE' and last and row['seal'] is not None:raise ValueError('report calendar seal/active row')
        if row['seal']=='MONTH_BOUNDARY' and row['start_seconds']==row['end_seconds']:raise ValueError('report empty month seal')
        if previous is not None:
            if set(row['maximum_temperature_k'])!=set(previous['maximum_temperature_k']):raise ValueError('report mixed thermal sets')
            if row['priority_denominator']!=previous['priority_denominator']:raise ValueError('report denominator scope')
            if row['wear_start']!=previous['wear_end'] or row['minimum_energy_wh']>previous['end_energy_wh']:raise ValueError('report returned boundary continuity')
        for event in row['offered']:
            if event['id'] in offered:raise ValueError('duplicate report offered request')
            offered[event['id']]=event['priority']
        for event in row['credits']:
            if event['request_id'] in receipts:raise ValueError('duplicate report receipt')
            if (rational(event['completion_time'])+offset)//period!=row['bucket']:raise ValueError('report receipt calendar membership')
            if record_ids.intersection(event['record_ids']):raise ValueError('report reused receipt custody')
            record_ids.update(event['record_ids']);receipts[event['request_id']]=event['priority']
        if expired.intersection(row['expired']):raise ValueError('duplicate report expired request')
        expired.update(row['expired']);previous=row
    if rows[-1]['end_seconds']!=end:raise ValueError('report outer coverage')
    if set(receipts)&expired:raise ValueError('report credited and expired request')
    if any(offered[key]!=weight for key,weight in receipts.items() if key in offered):raise ValueError('report request weight disagreement')
    denominator=rows[0]['priority_denominator']
    if sum(offered.values())>denominator or sum(receipts.values())>denominator:raise ValueError('report mission denominator scope')
    actions=sum(row['actions'] for row in rows)
    if actions>64 or len(offered)>64 or len(receipts)>64 or len(expired)>64:raise ValueError('report short population quota')
    return dict(offered=set(offered),receipts=set(receipts),expired=expired,actions=actions)


def _control(value,actions):
    for name in ('control_units','control_reserved_units'):whole(value[name],hi=2**30)
    if value['control_reserved_units']!=actions*2**20 or value['control_units']>value['control_reserved_units']:raise ValueError('report control reservation/cursor')


def validate_state(value):
    object_fields(value,STATE_FIELDS);_header(value,'offset_seconds')
    for name in ('cursor','base_cursor'):whole(value[name],hi=64)
    if value['cursor']+value['base_cursor']>64:raise ValueError('report physical cursor quota')
    whole(value['detail_bytes'],hi=2**30)
    for name in ('seen_actions','seen_receipts','seen_offered','seen_expired'):
        ids=value[name]
        if type(ids) is not list or len(ids)>64:raise ValueError('report finite dedup population')
        for item in ids:identifier(item)
        if len(set(ids))!=len(ids):raise ValueError('report dedup identity')
    if type(value['sealed']) is not list or len(value['sealed'])>180:raise ValueError('report finite sealed rows')
    if value['status']=='ACTIVE' and value['current'] is None or value['status']=='COMPLETE' and value['current'] is not None:raise ValueError('report active/sealed shape')
    if any(type(row) is not dict or row.get('seal') is None for row in value['sealed']):raise ValueError('report unsealed historical row')
    rows=value['sealed']+([] if value['current'] is None else [value['current']])
    data=_rows(rows,start=value['start_seconds'],end=value['end_seconds'],offset=value['offset_seconds'],period=value['period_seconds'],status=value['status'])
    if data['actions']!=value['cursor'] or len(value['seen_actions'])!=value['cursor']:raise ValueError('report action cursor')
    for field,key in (('seen_receipts','receipts'),('seen_offered','offered'),('seen_expired','expired')):
        if set(value[field])!=data[key]:raise ValueError('report event dedup ledger')
    _control(value,data['actions']);canonical_size(value,MAX_BYTES)
    return value


def validate_summary(value):
    object_fields(value,SUMMARY_FIELDS);_header(value,'epoch_offset_seconds')
    scopes=dict(month_semantics='FIXED_30_DAY_BUCKET_NOT_GREGORIAN',extrema_scope='RETURNED_STATES_NOT_CONTINUOUS_EXTREMA',coverage='SHORT_SYNTHETIC_DEMO_NOT_MONTH_PHYSICAL_SIMULATION',coordinator_history='FULL_SHORT_PREFIX_RETAINED_SEPARATELY')
    if any(type(value[key]) is not str or value[key]!=expected for key,expected in scopes.items()):raise ValueError('report summary scope')
    rows=value['rows'];data=_rows(rows,start=value['start_seconds'],end=value['end_seconds'],offset=value['epoch_offset_seconds'],period=value['period_seconds'],status=value['status'])
    _control(value,data['actions'])
    totals=value['totals'];object_fields(totals,TOTAL_FIELDS);object_fields(totals['sums'],SUMS)
    for name in ('offered','credits','refused_actions','expired_requests','executed_point_seconds'):whole(totals[name])
    for name in ('useful_bits','priority_numerator','priority_denominator','priority_score','minimum_energy_wh','end_energy_wh'):finite(totals[name])
    for q in totals['sums'].values():_nonnegative_rational(q)
    _thermal(totals['maximum_temperature_k'])
    denominator=rows[0]['priority_denominator'];numerator=sum(c['priority'] for row in rows for c in row['credits'])
    expected=dict(offered=sum(len(row['offered']) for row in rows),credits=sum(len(row['credits']) for row in rows),
        useful_bits=sum(c['useful_bits'] for row in rows for c in row['credits']),priority_numerator=numerator,
        priority_denominator=denominator,priority_score=numerator/denominator,
        refused_actions=sum(row['refused_actions'] for row in rows),expired_requests=sum(len(row['expired']) for row in rows),
        executed_point_seconds=sum(row['executed_point_seconds'] for row in rows),minimum_energy_wh=min(row['minimum_energy_wh'] for row in rows),
        end_energy_wh=rows[-1]['end_energy_wh'],maximum_temperature_k={key:max(row['maximum_temperature_k'][key] for row in rows) for key in rows[0]['maximum_temperature_k']},
        sums={key:[str(q.numerator),str(q.denominator)] for key in SUMS for q in [sum((rational(row['sums'][key]) for row in rows),Fraction())]})
    if totals!=expected:raise ValueError('report summary derived totals')
    canonical_size(value,MAX_BYTES)
    return value


def dumps_report(value):
    canonical_size(value,MAX_BYTES)
    raw=canonical(value).encode()
    if len(raw)>MAX_BYTES:raise ValueError('report byte quota')
    return raw


def loads_report(raw):
    if type(raw) is not bytes or len(raw)>MAX_BYTES:raise ValueError('report byte quota')
    value=parse_json(raw.decode());canonical_size(value,MAX_BYTES)
    if dumps_report(value)!=raw:raise ValueError('report canonical data')
    if type(value) is not dict:raise ValueError('report object required')
    return validate_state(value) if 'cursor' in value else validate_summary(value)
