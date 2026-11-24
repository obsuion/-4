"""YEAR-V3 runner-issued no-start proof; administrative, never scientific DATA.

An attempt marker precedes Thread.start. A missing marker alone proves nothing:
recovery additionally needs the exact owner-issued refusal receipt and committed
REFUSED status. Any publication error or unreleased owner remains fail-closed.
"""
from copy import deepcopy
from hashlib import sha256
from .lifetime_journal import encoded,publish

BOUNDARY='YEAR_V3_RUNNER_PRE_THREAD_BOUNDARY_V1'
PROOF='YEAR_V3_RUNNER_NO_LAUNCH_PROOF_V1'
DISPOSITION='YEAR_V3_NO_LAUNCH_ADMIN_DISPOSITION_V1'
RECOVERY='YEAR_V3_EXPLICIT_NO_LAUNCH_RECOVERY_V1'
CAP=8192
RESERVE=3*CAP

def enabled(policy):
    from .lifetime_policy import no_launch
    return no_launch(policy)

def digest(v):return sha256(encoded(v)).hexdigest()

def _read(store,jid,name):
    from .lifecycle_application import _read
    p=store.path('jobs',jid,name)
    value=_read(p,CAP)
    if encoded(value)!=p.read_bytes():raise ValueError('YEAR-V3 exact no-launch bytes')
    return value

def begin(runner,job):
    if not enabled(runner.store.runner_policy):return
    store=runner.store;jid=job['job_id'];a=runner.owned_authority
    if runner.thread is not None or runner.active is not None or a['launch_attempted']is not False:
        raise ValueError('YEAR-V3 unstarted runner boundary required')
    from .lifetime_journal import Journal
    from .lifetime_supervisor import _read as read_plan
    plan=read_plan(store.path('lifetime-plan.json'))
    records=list(Journal(store,plan).records())
    dispatch=[x for x in records if x['action']in('DISPATCH','DIAGNOSTIC') and x['data']['intent']==job['intent']]
    if len(dispatch)!=1:raise ValueError('YEAR-V3 exact durable dispatch required')
    value=dict(format=BOUNDARY,job_id=jid,request_sha256=sha256(store.path('jobs',jid,'request.json').read_bytes()).hexdigest(),
        root_identity=job['root_identity'],source_identity=job['source_identity'],runtime=job['runtime'],
        input_sha256=job['input_sha256'],intent=job['intent'],dispatch_sha256=digest(dispatch[0]),
        owner=deepcopy(runner.lease),reserved_bytes=RESERVE)
    if len(encoded(value))>CAP:raise ValueError('YEAR-V3 boundary byte admission')
    store._parent_charge(jid,RESERVE) # irrevocable prepayment, even on later I/O failure
    publish(store.path('jobs',jid,'no-launch-boundary.json'),value,CAP)
    a['pre_thread_boundary']=deepcopy(value)

def attempt(runner,job):
    if not enabled(runner.store.runner_policy):return
    boundary=runner.owned_authority.get('pre_thread_boundary')
    if boundary is None:raise ValueError('YEAR-V3 missing owned boundary')
    publish(runner.store.path('jobs',job['job_id'],'thread-attempt.json'),
        dict(format='YEAR_V3_THREAD_START_ATTEMPT_V1',boundary_sha256=digest(boundary)),CAP)
    runner.owned_authority['thread_start_attempted']=True

def refuse(runner,job,error):
    store=runner.store;a=runner.owned_authority;jid=job['job_id']
    if (not enabled(store.runner_policy) or runner.thread is not None or runner.active is not None or
            a['launch_attempted']is not False or a.get('thread_start_attempted')is not None or
            a['dispatch_token']!=runner.lease or a.get('pre_thread_boundary')is None):
        raise ValueError('YEAR-V3 runner cannot prove no-start')
    boundary=a['pre_thread_boundary']
    if _read(store,jid,'no-launch-boundary.json')!=boundary or store.path('jobs',jid,'thread-attempt.json').exists():
        raise ValueError('YEAR-V3 attempted/foreign boundary')
    if store.job(jid)['intent']!=job['intent']:raise ValueError('YEAR-V3 callback changed intent')
    reason='BEFORE_OWNED_LAUNCH:'+str(error)[:1024]
    proof=dict(format=PROOF,boundary=boundary,reason=reason,thread_start_attempted=False,
        scientific_launch_attempted=False,scientific_authority=False)
    publish(store.path('jobs',jid,'no-launch-proof.json'),proof,CAP)
    job.update(status='REFUSED',reason=reason,ownership_valid=True)
    store.update_job(job) # if this fails, receipt is insufficient for recovery
    runner._release_dispatch()
    return proof

def validate(store,job):
    if not enabled(store.runner_policy):raise ValueError('YEAR-V3 prospective store only; no migration')
    store._pinned();jid=job['job_id'];proof=_read(store,jid,'no-launch-proof.json')
    if set(proof)!={'format','boundary','reason','thread_start_attempted','scientific_launch_attempted','scientific_authority'} or proof['format']!=PROOF or any(proof[k]is not False for k in('thread_start_attempted','scientific_launch_attempted','scientific_authority')):
        raise ValueError('YEAR-V3 strict no-launch proof')
    b=proof['boundary'];expected=_read(store,jid,'no-launch-boundary.json')
    names={'format','job_id','request_sha256','root_identity','source_identity','runtime','input_sha256','intent','dispatch_sha256','owner','reserved_bytes'}
    if type(b)is not dict or set(b)!=names or b!=expected or b['format']!=BOUNDARY or type(b['reserved_bytes'])is not int or b['reserved_bytes']!=RESERVE:
        raise ValueError('YEAR-V3 boundary schema/binding')
    if (job['status']!='REFUSED' or job['ownership_valid']is not True or job['result']is not None or job['launch']is not None or job['checkpoints'] or job['progress']is not None or job['reason']!=proof['reason']):
        raise ValueError('YEAR-V3 proof requires committed non-scientific refusal')
    if any(b[n]!=job[n]for n in('job_id','root_identity','source_identity','runtime','input_sha256','intent')):
        raise ValueError('YEAR-V3 foreign proof authority')
    if sha256(store.path('jobs',jid,'request.json').read_bytes()).hexdigest()!=b['request_sha256']:
        raise ValueError('YEAR-V3 request proof hash')
    owner=b['owner']
    from .project_store import identifier
    if type(owner)is not dict or set(owner)!={'format','owner','PID','source_identity'} or owner['format']!='B52_EXCLUSIVE_DISPATCH_OWNER_V1' or type(owner['PID'])is not int or owner['PID']<=0 or owner['source_identity']!=job['source_identity']:
        raise ValueError('YEAR-V3 exact runner owner')
    identifier(owner['owner'])
    active=store.path('dispatch-owner.json')
    current=getattr(store,'_year_v3_dispatch_owner',None)
    authorized_current=(current is not None and current!=owner and active.exists()and __import__(__package__+'.lifecycle_application',fromlist=['_read'])._read(active)==current)
    if (active.exists()and not authorized_current) or store.path('dispatch-quarantine.json').exists() or store.path('jobs',jid,'thread-attempt.json').exists():
        raise ValueError('YEAR-V3 live/unknown/attempted owner remains fail-closed')
    from .lifetime_supervisor import _read as read_plan
    from .lifetime_journal import Journal
    records=list(Journal(store,read_plan(store.path('lifetime-plan.json'))).records())
    matches=[x for x in records if x['action']in('DISPATCH','DIAGNOSTIC')and x['data']['intent']==job['intent']]
    if len(matches)!=1 or digest(matches[0])!=b['dispatch_sha256']:raise ValueError('YEAR-V3 dispatch proof binding')
    return proof

def dispositions(store,records):
    values={}
    for record in records:
        if record['action']!='NO_LAUNCH_DISPOSITION':continue
        d=record['data']
        if type(d)is not dict or set(d)!={'format','job_id','proof_sha256','scientific_authority'} or d['format']!=DISPOSITION or d['scientific_authority']is not False or d['job_id']in values:
            raise ValueError('YEAR-V3 exact distinct administrative disposition')
        proof=validate(store,store.job(d['job_id']))
        if digest(proof)!=d['proof_sha256']:raise ValueError('YEAR-V3 disposed proof drift')
        values[d['job_id']]=d
    return values

def pending_recovery(store,records):
    disposed=dispositions(store,records)
    consumed=set()
    grants={digest(x):x for x in records if x['action']=='NO_LAUNCH_RECOVERY'}
    for x in records:
        if x['action']not in('DISPATCH','DIAGNOSTIC') or 'recovery_job_id'not in x['data']:continue
        d=x['data'];jid=d['recovery_job_id'];g=grants.get(d.get('recovery_authority'))
        if (jid not in disposed or jid in consumed or g is None or g['sequence']>=x['sequence'] or
                g['data'].get('format')!=RECOVERY or g['data'].get('job_id')!=jid or
                g['data'].get('proof_sha256')!=disposed[jid]['proof_sha256'] or
                g['data'].get('maximum_new_intents')!=1 or
                d['intent']['idempotency_key']!=g['data'].get('next_key') or digest(d['intent'])!=g['data'].get('intent_sha256')):
            raise ValueError('YEAR-V3 recovery dispatch binding')
        consumed.add(jid)
    return {k:v for k,v in disposed.items()if k not in consumed}

def admit_recovery(store,records,token,intent=None):
    pending=pending_recovery(store,records)
    if not pending:
        if token is not None:raise ValueError('YEAR-V3 no pending refusal for authority')
        return None
    from .project_store import identifier
    if token is None:raise ValueError('YEAR-V3 explicit finite recovery authority required')
    identifier(token,revision=True)
    if len(pending)!=1:raise ValueError('YEAR-V3 ambiguous pending recovery')
    jid=next(iter(pending));grants=[x for x in records if x['action']=='NO_LAUNCH_RECOVERY'and x['data'].get('job_id')==jid]
    if len(grants)!=1 or token!=digest(grants[0]):raise ValueError('YEAR-V3 explicit finite recovery authority required')
    grant=grants[0]['data']
    if set(grant)!={'format','job_id','proof_sha256','next_key','intent_sha256','maximum_new_intents'} or grant['format']!=RECOVERY or grant['maximum_new_intents']!=1 or type(grant['maximum_new_intents'])is not int or grant['proof_sha256']!=pending[jid]['proof_sha256']:
        raise ValueError('YEAR-V3 recovery authority schema')
    from .project_store import identifier
    identifier(grant['next_key'])
    if intent is not None and (intent['idempotency_key']!=grant['next_key'] or digest(intent)!=grant['intent_sha256']):raise ValueError('YEAR-V3 different recovery intent')
    return grant

def administrative_ids(store):
    if not enabled(store.runner_policy):return set()
    from .lifetime_supervisor import _read
    from .lifetime_journal import Journal
    return set(dispositions(store,list(Journal(store,_read(store.path('lifetime-plan.json'))).records())))


def validate_next_dispatch(store,intent):
    if not enabled(store.runner_policy):return
    from .lifetime_supervisor import _read
    from .lifetime_journal import Journal
    records=list(Journal(store,_read(store.path('lifetime-plan.json'))).records())
    matching=[x for x in records if x['action']in('DISPATCH','DIAGNOSTIC')and x['data']['intent']==intent]
    if len(matching)!=1:raise ValueError('YEAR-V3 new job requires exact durable dispatch')
    current=matching[0]
    pending=pending_recovery(store,[x for x in records if x is not current])
    if pending:
        grant=admit_recovery(store,[x for x in records if x is not current],current['data'].get('recovery_authority'),intent)
        if current['data'].get('recovery_job_id')!=grant['job_id']:raise ValueError('YEAR-V3 missing recovery job binding')
