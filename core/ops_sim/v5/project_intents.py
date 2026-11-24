"""Strict durable submission content; delivery uncertainty never changes the key."""
from hashlib import sha256
from .experiment_codec import object_fields
from .long_mission_document import canonical_json

FORMAT='M8_DURABLE_JOB_INTENT_V1'
INITIAL='INITIAL'
CAUSAL='B48_CAUSAL'
DIRECT='B51_DIRECT'
FIELDS=('format','action_id','idempotency_key','project_id','revision','parent_job_id','snapshot_sha256','method','mode','window_end_seconds')
def _hex(v,n):
    if type(v) is not str or len(v)!=n or any(c not in '0123456789abcdef' for c in v):raise ValueError('exact intent identifier')
    return v
def validate_intent(value):
    d=object_fields(value,FIELDS)
    if d['format']!=FORMAT or type(d['method']) is not str or d['method'] not in (INITIAL,CAUSAL,DIRECT):raise ValueError('intent method')
    for n in ('action_id','idempotency_key','project_id'):_hex(d[n],32)
    _hex(d['revision'],64)
    if type(d['mode']) is not str or d['mode'] not in ('MAIN','DIAGNOSTIC_NORMAL','DIAGNOSTIC_VERBOSE'):raise ValueError('intent mode')
    if d['method']==INITIAL:
        if d['parent_job_id'] is not None or d['snapshot_sha256'] is not None or d['window_end_seconds'] is not None or d['mode']!='MAIN':raise ValueError('initial intent cannot claim continuation')
    else:
        _hex(d['parent_job_id'],32);_hex(d['snapshot_sha256'],64)
        if d['method']==CAUSAL:
            if d['window_end_seconds'] is not None or d['mode']!='MAIN':raise ValueError('causal continuation mode')
        elif type(d['window_end_seconds']) is not int or not 128<d['window_end_seconds']<=728:raise ValueError('bounded direct window')
    return dict(d)
def intent_identity(value):return sha256(canonical_json(validate_intent(value)).encode()).hexdigest()
def make_intent(pid,revision,key,*,parent=None,snapshot_sha=None,method=INITIAL,mode='MAIN',window_end=None):
    return validate_intent(dict(format=FORMAT,action_id=key,idempotency_key=key,project_id=pid,revision=revision,parent_job_id=parent,snapshot_sha256=snapshot_sha,method=method,mode=mode,window_end_seconds=window_end))
