"""Finite, serial, durable consumer of settled chronological native states.

Opening a chain is read-only and never dispatches. A claimed writer is never
stolen on PID guesses. UNKNOWN suffixes are not continuation authorities.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json, os, threading, time, uuid
from .experiment_codec import object_fields
from .lifecycle_contract import integer, identity, canonical
from .project_store import identifier, file_sha
from .lifecycle_execution_budget import ExecutionBudget, admit_budget

PLAN='B55R2_FINITE_SERIAL_CHAIN_PLAN_V1'
STATE='B55R2_HASH_LINKED_CHAIN_STATE_V1'
FIELDS=('format','chain_id','root_identity','input_sha256','source_identity','runtime',
        'maximum_primary_segments','reserved_diagnostic_slots','maximum_output_bytes',
        'maximum_observed_seconds','execution_budget','execution_budget_identity',
        'late_predecessor_rule','plan_identity')
STATES=('READY','DISPATCHING','RUNNING','BUDGET_CONTINUING','USER_PAUSED',
        'COMPLETED','PLAN_EXHAUSTED','ADMISSION_STOP','BLOCKED')
STATE_FIELDS=('format','plan_identity','sequence','previous_sha256','state','segments',
              'pending_intent','command_keys','reason','observed_seconds','estimate','failed_attempt')

def encoded(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return sha256(encoded(v)).hexdigest()

def make_plan(store, *, chain_id, execution_budget, maximum_primary_segments=6,
              maximum_output_bytes=128*2**20, maximum_observed_seconds=9600):
    identifier(chain_id)
    if type(execution_budget) is not ExecutionBudget:raise TypeError('immutable execution budget')
    p=dict(format=PLAN,chain_id=chain_id,root_identity=store.meta['root_identity'],
        input_sha256=store.meta['input_sha256'],source_identity=store.meta['source_identity'],
        runtime=store.meta['runtime'],maximum_primary_segments=maximum_primary_segments,
        reserved_diagnostic_slots=2,maximum_output_bytes=maximum_output_bytes,
        maximum_observed_seconds=maximum_observed_seconds,execution_budget=asdict(execution_budget),
        execution_budget_identity=execution_budget.identity,
        late_predecessor_rule='LATEST_RETAINED_WORKING_STRICTLY_BEFORE_TARGET_WITH_SUFFIX_AT_MOST_256_TRANSITIONS')
    p['plan_identity']=digest(p)
    return admit_plan(p,store)

def admit_plan(value,store):
    p=object_fields(value,FIELDS);identifier(p['chain_id'])
    if p['format']!=PLAN or p['plan_identity']!=digest({k:v for k,v in p.items() if k!='plan_identity'}):raise ValueError('immutable chain plan identity')
    for key in ('root_identity','input_sha256','source_identity','runtime'):
        if p[key]!=store.meta[key]:raise ValueError('chain '+key+' binding')
    integer(p['maximum_primary_segments'],'finite primary segments',1,6)
    integer(p['maximum_output_bytes'],'finite segment output',2**20,128*2**20)
    integer(p['maximum_observed_seconds'],'finite chain allowance',1,10800)
    if type(p['reserved_diagnostic_slots']) is not int or p['reserved_diagnostic_slots']!=2:raise ValueError('reserve MAIN and loupe slots')
    if p['late_predecessor_rule']!='LATEST_RETAINED_WORKING_STRICTLY_BEFORE_TARGET_WITH_SUFFIX_AT_MOST_256_TRANSITIONS':raise ValueError('declared late predecessor selection')
    b=admit_budget(p['execution_budget'],execution_seconds=p['execution_budget']['hard_execution_seconds'])
    if p['execution_budget_identity']!=b.identity:raise ValueError('chain budget identity')
    if store.runner_policy is None or p['maximum_primary_segments']+2>store.maximum_jobs:raise ValueError('finite V2 store required')
    if (p['maximum_primary_segments']+2)*p['maximum_output_bytes']>store.maximum_reserved_job_output_bytes:raise ValueError('chain/diagnostics output reservations')
    if p['maximum_output_bytes']>store.root_input.policy.max_task_output_bytes:raise ValueError('root output allowance')
    if store.root_input.output_policy is not None:
        q=store.root_input.output_policy
        worker=p['maximum_output_bytes']-q.status_total_bytes-4*q.max_index_bytes-256*2**10
        if worker<=store.root_input.policy.max_checkpoint_bytes+327680:raise ValueError('chain output allowance after parent/checkpoint reserve')
    # 128 immutable metadata records of at most 256 KiB, plus small plan/owner.
    if (p['maximum_primary_segments']+2)*p['maximum_output_bytes']+33*2**20>store.maximum_reserved_job_output_bytes:raise ValueError('chain metadata plus job reservation')
    return deepcopy(p)

class LifecycleChain:
    def __init__(self,store,chain_id,*,plan=None,runner=None):
        from .lifecycle_application import _write_new,LifecycleRunner
        self.store=store;self.chain_id=identifier(chain_id);self.lock=threading.RLock()
        self.folder=store.path('chains',chain_id);self.runner=runner or LifecycleRunner(store)
        if plan is not None:
            plan=admit_plan(plan,store)
            if plan['chain_id']!=chain_id:raise ValueError('chain name binding')
            if self.folder.exists():
                if self._read(self.folder/'plan.json')!=plan:raise ValueError('chain plan drift')
            else:
                if store.jobs():raise ValueError('new chain requires new empty store; no implicit original retry')
                _write_new(self.folder/'plan.json',plan)
                self.plan=plan
                self._append(dict(state='READY',segments=[],pending_intent=None,command_keys=[],reason=None,observed_seconds=0.,estimate=None,failed_attempt=None),initial=True)
        self.plan=admit_plan(self._read(self.folder/'plan.json'),store)
        self.plan_sha=file_sha(self.folder/'plan.json')
        self.snapshot() # strict saved metadata admission, with no dispatch.

    @staticmethod
    def _read(p):
        from .lifecycle_application import _read
        return _read(p)

    def _states(self):
        paths=sorted((self.folder/'states').glob('*.json'))
        if not 1<=len(paths)<=128:raise ValueError('finite chain journal population')
        previous='0'*64;last=None
        for n,p in enumerate(paths,1):
            if p.name!=f'{n:04}.json':raise ValueError('chain sequence filename')
            raw=p.read_bytes()
            if len(raw)>256*2**10:raise ValueError('chain journal record cap')
            v=json.loads(raw);object_fields(v,STATE_FIELDS)
            if raw!=encoded(v) or v['format']!=STATE or type(v['sequence']) is not int or v['sequence']!=n or v['previous_sha256']!=previous or v['plan_identity']!=self.plan['plan_identity'] or v['state'] not in STATES:raise ValueError('chain journal binding/sequence')
            if type(v['segments']) is not list or len(v['segments'])>self.plan['maximum_primary_segments']:raise ValueError('chain segment population')
            for segment in v['segments']:
                object_fields(segment,('ordinal','job_id','intent_sha256','checkpoint_sha256','clock','observed_seconds'))
                integer(segment['ordinal'],'segment ordinal',1,6);identifier(segment['job_id']);identity(segment['intent_sha256']);identity(segment['checkpoint_sha256'])
                integer(segment['clock'],'committed segment clock')
                if type(segment['observed_seconds']) not in (int,float) or not 0<=segment['observed_seconds']<float('inf'):raise ValueError('finite settled envelope')
            if [x['ordinal'] for x in v['segments']]!=list(range(1,len(v['segments'])+1)):raise ValueError('chain ordinal sequence')
            if type(v['command_keys']) is not list or len(v['command_keys'])>32 or len(set(v['command_keys']))!=len(v['command_keys']):raise ValueError('finite command keys')
            for k in v['command_keys']:identifier(k)
            failed_seconds=0.
            if v['failed_attempt'] is not None:
                f=object_fields(v['failed_attempt'],('job_id','intent_sha256','status','reason','observed_seconds','launch'))
                identifier(f['job_id']);identity(f['intent_sha256'])
                if v['state']!='BLOCKED':raise ValueError('failed attempt blocks continuation')
                if f['observed_seconds'] is not None:
                    if type(f['observed_seconds']) not in (int,float) or not 0<=f['observed_seconds']<float('inf'):raise ValueError('failed attempt envelope')
                    failed_seconds=f['observed_seconds']
            if type(v['observed_seconds']) not in (int,float) or not 0<=v['observed_seconds']<float('inf') or v['observed_seconds']!=sum(x['observed_seconds'] for x in v['segments'])+failed_seconds:raise ValueError('chain cumulative observed envelopes')
            if v['pending_intent'] is not None:
                from .lifecycle_application import validate_intent
                validate_intent(v['pending_intent'])
                expected=self._intent(len(v['segments'])+1,v['segments'][-1] if v['segments'] else None)
                if v['pending_intent']!=expected:raise ValueError('durable chain intent drift')
            if last is not None:
                if v['segments'][:len(last['segments'])]!=last['segments'] or not set(last['command_keys'])<=set(v['command_keys']):raise ValueError('chain cannot refund settled lineage')
            previous=sha256(raw).hexdigest();last=v
        return last,previous

    def snapshot(self):
        if hasattr(self,'plan_sha') and file_sha(self.folder/'plan.json')!=self.plan_sha:raise ValueError('immutable chain plan changed')
        admit_plan(self.plan,self.store);self.store._pinned()
        state,_=self._states()
        # No saved status, graph or checkpoint summary is a native authority.
        return dict(plan=deepcopy(self.plan),state=deepcopy(state),active_job_id=self.runner.active)

    def _append(self,value,*,initial=False):
        from .lifecycle_application import _write_new
        if initial:n=1;previous='0'*64
        else:old,previous=self._states();n=old['sequence']+1
        if n>128:raise ValueError('chain journal exhausted')
        v=dict(value,format=STATE,plan_identity=self.plan['plan_identity'],sequence=n,previous_sha256=previous)
        target=self.folder/'states'/f'{n:04}.json'
        pending=target.with_suffix('.pending')
        _write_new(pending,encoded(v))
        # Publish a NEW immutable filename only after flush/close. Readers
        # never open this private pending file, and no held target is replaced.
        if target.exists():raise ValueError('chain sequence already published')
        os.rename(pending,target)
        return v

    def _save(self,previous_state,**updates):
        v={k:deepcopy(v) for k,v in previous_state.items() if k not in ('format','plan_identity','sequence','previous_sha256')};v.update(updates)
        return self._append(v)

    def _intent(self,ordinal,parent):
        from .lifecycle_application import make_intent
        p=self.plan;b=admit_budget(p['execution_budget'],execution_seconds=p['execution_budget']['hard_execution_seconds'])
        key=sha256((p['plan_identity']+':'+str(ordinal)).encode()).hexdigest()[:32]
        return make_intent(p['root_identity'],key=key,parent_job_id=None if parent is None else parent['job_id'],
            snapshot_sha256=None if parent is None else parent['checkpoint_sha256'],execution_seconds=b.hard_execution_seconds,
            maximum_output_bytes=p['maximum_output_bytes'],execution_budget=b,publication_profile=self.store.publication_profile,profile_bound=self.store.publication_profile is not None)

    def stop(self):
        """User pause is durable before a marker; it never means budget Continue."""
        from .lifecycle_application import _write_new
        with self.lock:
            state=self.snapshot()['state'];seq=state['sequence']
            path=self.folder/f'user-pause-{seq:04}.json'
            if not path.exists():
                stage=path.with_suffix('.pending')
                _write_new(stage,dict(plan_identity=self.plan['plan_identity'],sequence=seq));os.rename(stage,path)
            if self.runner.active is not None:self.runner.stop(self.runner.active)
            elif state['pending_intent'] is not None:
                # CLI in a separate process has no owned handle. It may publish
                # the same strict cooperative request; it never controls a PID.
                job=self.store.reconcile(state['pending_intent'])
                if job is not None and job['status'] in ('QUEUED','ADMITTED','RUNNING','STOP_REQUESTED'):
                    from .lifecycle_application import _utc
                    marker=self.store.path('jobs',job['job_id'],'stop-request.json')
                    if not marker.exists():
                        from .lifecycle_application import _write_stop_request
                        _write_stop_request(marker,job)
                    else:
                        m=self._read(marker)
                        if m.get('format')!='B52_COOPERATIVE_STOP_REQUEST_V1' or m.get('job_id')!=job['job_id'] or m.get('root_identity')!=job['root_identity']:raise ValueError('foreign stop marker')
            return self.snapshot()

    def _paused(self,state):
        # A Continue state explicitly consumes every older pause record.
        consumed=0
        for p in sorted((self.folder/'states').glob('*.json')):
            v=self._read(p)
            if v['reason']=='EXPLICIT_CONTINUE':consumed=max(consumed,v['sequence']-1)
        paths=list(self.folder.glob('user-pause-*.json'))
        for path in paths:
            v=self._read(path);object_fields(v,('plan_identity','sequence'))
            if v['plan_identity']!=self.plan['plan_identity'] or path.name!=f"user-pause-{v['sequence']:04}.json":raise ValueError('pause binding')
            if v['sequence']>consumed:return True
        return False

    def _settled_segment(self,job,ordinal):
        from .lifecycle_application import TERMINAL,_admit_execution_terminal,_settled_publication_work,_admit_publication,_verify_checkpoint_streams
        from .lifecycle_checkpoint import admit_checkpoint,make_bindings
        if job['status'] not in TERMINAL or job['ownership_valid'] is not True or job['launch'] is None or job['launch'].get('forced_interruption') is not False or job['launch'].get('unexpected') is not None or job['launch'].get('timeout') is not False:
            raise ValueError('chain refuses unknown/forced/unsettled parent')
        result=job['result']
        if result is None or result['application_status'] not in ('COMPLETED_WINDOW','INCOMPLETE_STOP','INCOMPLETE_BUDGET_STOP'):raise ValueError('chain refuses failed/admission/model terminal')
        _admit_execution_terminal(job,result)
        folder=self.store.path('jobs',job['job_id']);cp=result['checkpoint']
        if cp['kind']!='FINAL' or cp not in job['checkpoints']:raise ValueError('chain final native publication')
        if result['clock']!=cp['clock'] or result['status']!='ACTIVE' and result['clock']<self.store.root_input.end_seconds:raise ValueError('chain native must remain active')
        if cp['bindings']!=make_bindings(self.store.root_input,cp['clock']):raise ValueError('chain native exact source/runtime/policy')
        _settled_publication_work(folder,self.store.root_input,job,result)
        _admit_publication(folder,cp,self.store.root_input,settled=True)
        from .lifecycle_checkpoint import checkpoint_file_bytes
        from .lifetime_policy import physical_storage
        raw=checkpoint_file_bytes(folder/cp['file'],cp,self.store.root_input,require_transport=physical_storage(self.store.runner_policy))
        admit_checkpoint(raw,self.store.root_input,expected_sha256=cp['sha256'],expected_bindings=cp['bindings'])
        _verify_checkpoint_streams(folder,cp,self.store.root_input,reserve=lambda n:self.store._reserve_saved_read(job['job_id'],n))
        seconds=job['launch']['observed_envelope_seconds']
        if type(seconds) not in (int,float) or not 0<=seconds<float('inf'):raise ValueError('chain observed envelope')
        return dict(ordinal=ordinal,job_id=job['job_id'],intent_sha256=digest(job['intent']),checkpoint_sha256=cp['sha256'],clock=cp['clock'],observed_seconds=seconds)

    def run(self,command_key):
        """Explicit bounded command, automatically continues only budget cuts."""
        from .lifecycle_application import _write_new
        identifier(command_key)
        with self.lock:
            state=self.snapshot()['state']
            if command_key in state['command_keys']:return self.snapshot()
            if state['state'] in ('COMPLETED','PLAN_EXHAUSTED','ADMISSION_STOP','BLOCKED'):return self.snapshot()
            if list((self.folder/'states').glob('*.pending')):raise ValueError('unpublished chain state requires reconciliation; no dispatch')
            owner=self.folder/'writer-owner.json';token=dict(token=uuid.uuid4().hex,PID=os.getpid(),plan_identity=self.plan['plan_identity'])
            try:_write_new(owner,token)
            except FileExistsError:raise ValueError('chain writer already claimed; reopen never steals ownership') from None
            state=self._save(state,command_keys=[*state['command_keys'],command_key],reason='EXPLICIT_CONTINUE')
        try:
            while True:
                self.snapshot()
                if self._paused(state):state=self._save(state,state='USER_PAUSED',reason='USER_STOP_REQUIRES_EXPLICIT_CONTINUE');break
                if len(state['segments'])>=self.plan['maximum_primary_segments']:state=self._save(state,state='PLAN_EXHAUSTED',reason='FINITE_PRIMARY_SEGMENT_LIMIT');break
                b=self.plan['execution_budget'];remaining=self.plan['maximum_observed_seconds']-state['observed_seconds']
                if remaining<b['hard_execution_seconds']+2:state=self._save(state,state='ADMISSION_STOP',reason='REMAINING_ALLOWANCE_CANNOT_RESERVE_FULL_SEGMENT');break
                previous=state['segments'][-1] if state['segments'] else None
                if previous is not None:
                    # Revalidate parent on every continuation, including restart.
                    checked=self._settled_segment(self.store.job(previous['job_id']),previous['ordinal'])
                    if checked!=previous:raise ValueError('stale/tampered chain parent')
                ordinal=len(state['segments'])+1
                intent=self._intent(ordinal,previous)
                if state['pending_intent'] is not None and state['pending_intent']!=intent:raise ValueError('pending chain intent mismatch')
                with self.lock:
                    # A User Stop cannot land between the last pause check and
                    # acquiring the runner's owned handle. stop() shares this lock.
                    if self._paused(state):
                        state=self._save(state,state='USER_PAUSED',reason='USER_STOP_REQUIRES_EXPLICIT_CONTINUE');break
                    state=self._save(state,state='DISPATCHING',pending_intent=intent,reason=None)
                    job=self.runner.submit(intent) # reconcile identity; never retry unknown work.
                    state=self._save(state,state='RUNNING')
                thread=self.runner.thread
                if thread is not None:thread.join(b['hard_execution_seconds']+3)
                if thread is not None and thread.is_alive():raise RuntimeError('owned segment did not settle')
                job=self.store.job(job['job_id']);segment=self._settled_segment(job,ordinal)
                segments=[*state['segments'],segment];observed=sum(x['observed_seconds'] for x in segments)
                estimate=None
                if segment['clock']>self.store.root_input.start_seconds:
                    estimate=dict(method='MEASURED_CUMULATIVE_RATE_ENGINEERING_ESTIMATE_NOT_RUNTIME_BOUND',
                        remaining_seconds_estimate=observed*(self.store.root_input.end_seconds-segment['clock'])/(segment['clock']-self.store.root_input.start_seconds))
                state=self._save(state,segments=segments,pending_intent=None,observed_seconds=observed,estimate=estimate)
                if segment['clock']>=self.store.root_input.end_seconds:state=self._save(state,state='COMPLETED',reason='IMMUTABLE_TARGET_REACHED');break
                if self._paused(state) or job['result']['application_status']=='INCOMPLETE_STOP':state=self._save(state,state='USER_PAUSED',reason='USER_STOP_REQUIRES_EXPLICIT_CONTINUE');break
                if job['result']['application_status']!='INCOMPLETE_BUDGET_STOP':raise ValueError('only budget stop automatically continues')
                if segment['clock']<=(previous['clock'] if previous is not None else self.store.root_input.start_seconds):raise ValueError('no scientific progress; no blind retry')
                if estimate is not None and estimate['remaining_seconds_estimate']>self.plan['maximum_observed_seconds']-observed:
                    state=self._save(state,state='ADMISSION_STOP',reason='MEASURED_RATE_CANNOT_FIT_REMAINING_PLAN');break
                state=self._save(state,state='BUDGET_CONTINUING',reason='SETTLED_BUDGET_PREFIX')
        except BaseException as error:
            failed=None
            pending=state['pending_intent']
            if pending is not None:
                job=self.store.reconcile(pending)
                if job is not None:
                    launch=deepcopy(job['launch']);seconds=None if launch is None else launch.get('observed_envelope_seconds')
                    failed=dict(job_id=job['job_id'],intent_sha256=digest(job['intent']),status=job['status'],reason=job['reason'],observed_seconds=seconds,launch=launch)
            observed=sum(x['observed_seconds'] for x in state['segments'])+(0. if failed is None or failed['observed_seconds'] is None else failed['observed_seconds'])
            state=self._save(state,state='BLOCKED',reason=type(error).__name__+': '+str(error),failed_attempt=failed,observed_seconds=observed);raise
        finally:
            if self._read(owner)!=token:raise RuntimeError('foreign chain writer token; preserve')
            owner.unlink()
        return self.snapshot()
