"""Bounded monthly selected exposure/property history, separate from forecasts."""
from copy import deepcopy
from hashlib import sha256
from .lifecycle_contract import canonical
from .environment_reporting import initial as environment_initial,advance as environment_advance,validate as environment_validate
from .lifecycle_report import pack,unpack

METHOD='B62_ACTUAL_BUCKET_ENVIRONMENT_V1'

def enabled(root):return root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'

def initial(root,history,*,prepared_runtime=None):
    t=int(history.clock_seconds)
    from dataclasses import asdict
    from .environment_ageing import EnvironmentAgeingWork
    zero=dict(actual_environment=asdict(EnvironmentAgeingWork()),forecast_environment=asdict(EnvironmentAgeingWork()))if t==root.start_seconds else None
    return dict(method=METHOD,start_seconds=t,end_seconds=t,rows=[],sealed_count=0,sealed_chain='0'*64,current=environment_initial(root,history,prepared_runtime=prepared_runtime),work_start=deepcopy(zero),work_end=deepcopy(zero))

def advance(data,root,before,after,work=None,*,prepared_runtime=None):
    d=deepcopy(data);a=int(before.clock_seconds);b=int(after.clock_seconds)
    if a!=d['end_seconds'] or not a<=b<=root.end_seconds:raise ValueError('B62 actual environment support gap')
    p=root.policy;bucket=(a+p.month_epoch_offset_seconds)//p.month_period_seconds
    boundary=(bucket+1)*p.month_period_seconds-p.month_epoch_offset_seconds
    if b>boundary:raise ValueError('B62 environmental cut crosses reporting bucket')
    if work is not None:d['work_end']=deepcopy(work)
    d['current']=environment_advance(d['current'],root,before,after,prepared_runtime=prepared_runtime);d['end_seconds']=b
    if b==boundary and b>a:
        row=dict(start_seconds=d['start_seconds'],end_seconds=b,environment=d['current'],paid_work_start=d['work_start'],paid_work_end=d['work_end'])
        d['sealed_chain']=sha256((d['sealed_chain']+canonical(row)).encode()).hexdigest();d['sealed_count']+=1
        d['rows']=[row] # Prior raw buckets are in the retained months stream, not the native state.
        d['start_seconds']=b;d['work_start']=deepcopy(d['work_end']);d['current']=environment_initial(root,after,prepared_runtime=prepared_runtime)
    validate(d,root,b,prepared_runtime=prepared_runtime)
    return d

def validate(data,root,end,*,prepared_runtime=None):
    from .environment_reporting import _runtime
    prepared_runtime=_runtime(root,prepared_runtime)
    if type(data)is not dict or set(data)!={'method','start_seconds','end_seconds','rows','current','sealed_count','sealed_chain','work_start','work_end'}or data['method']!=METHOD:raise ValueError('B62 strict selected environment report')
    if type(data['rows'])is not list or len(data['rows'])>1 or type(data['sealed_count'])is not int or not 0<=data['sealed_count']<=root.month_rows+1 or (data['sealed_count']==0)!=(len(data['rows'])==0)or type(data['sealed_chain'])is not str or len(data['sealed_chain'])!=64:raise ValueError('B62 bounded environment buckets')
    previous=None
    for row in data['rows']:
        if type(row)is not dict or set(row)!={'start_seconds','end_seconds','environment','paid_work_start','paid_work_end'}:raise ValueError('B62 environment row schema')
        a=row['start_seconds'];b=row['end_seconds']
        if type(a)is not int or type(b)is not int or not root.start_seconds<=a<b<=end or previous is not None and a!=previous:raise ValueError('B62 bucket support')
        environment_validate(row['environment'],root,a,b,prepared_runtime=prepared_runtime);previous=b
    a=data['start_seconds']
    if type(a)is not int or type(data['end_seconds'])is not int or data['end_seconds']!=end or not root.start_seconds<=a<=end or previous is not None and previous!=a:raise ValueError('B62 terminal environment support')
    environment_validate(data['current'],root,a,end,prepared_runtime=prepared_runtime)
    for work in (data['work_start'],data['work_end'],*(x['paid_work_start']for x in data['rows']),*(x['paid_work_end']for x in data['rows'])):
        validate_work(work)
    return data

def validate_work(work):
    if work is None:return # Explicitly unavailable initial/window counter origin.
    from dataclasses import fields
    from .environment_ageing import EnvironmentAgeingWork
    if type(work)is not dict or set(work)!={'actual_environment','forecast_environment'}:raise ValueError('B62 paid work groups')
    for name,owner in (('actual_environment',EnvironmentAgeingWork),('forecast_environment',EnvironmentAgeingWork)):
        group=work[name]
        if type(group)is not dict or set(group)!={f.name for f in fields(owner)}or any(type(v)is not int or not 0<=v<=2**64 for v in group.values()):raise ValueError('B62 paid finite counter snapshot')

def rows(data):
    result=deepcopy(data['rows'])
    if data['end_seconds']>data['start_seconds']:
        result.append(dict(start_seconds=data['start_seconds'],end_seconds=data['end_seconds'],environment=deepcopy(data['current']),paid_work_start=deepcopy(data['work_start']),paid_work_end=deepcopy(data['work_end'])))
    return result
