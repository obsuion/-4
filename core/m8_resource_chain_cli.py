"""B55-R2 separately bound production resource-chain CLI/Workbench adapter.

The frozen scientific worker is NOT edited. This controller has its own hash
and strict versioned plan, in addition to the worker's native source identity.
It can adopt a fully settled output-admission prefix; it never adopts force,
unknown suffixes, changes a job status, raises a cap or migrates the V1 journal.
"""
from pathlib import Path
from dataclasses import asdict
from copy import deepcopy
from hashlib import sha256
import argparse,datetime,json,os,threading,time,uuid
from ops_sim.v5.experiment_codec import object_fields
from ops_sim.v5.lifecycle_contract import integer,identity
from ops_sim.v5.project_store import identifier,file_sha,runtime_identity
from ops_sim.v5.spacecraft_project import project_source_identity
from ops_sim.v5.lifecycle_application import (LifecycleStore,LifecycleRunner,make_intent,
    _read,_write_new,_admit_execution_terminal,_settled_publication_work,
    _admit_publication,_verify_checkpoint_streams,_write_stop_request,TERMINAL)
from ops_sim.v5.lifecycle_execution_budget import admit_budget
from ops_sim.v5.lifecycle_checkpoint import admit_checkpoint,make_bindings

PLAN='B55R2_SETTLED_RESOURCE_CHAIN_V2'
STATE='B55R2_RESOURCE_CHAIN_STATE_V2'
POLICY='TIME_OR_PROSPECTIVE_OUTPUT_PAID_PREFIX_V2'
OUTPUT_REASON='PROSPECTIVE_OUTPUT_ADMISSION_BEFORE_NEXT_MODEL_TRANSITION'
PLAN_FIELDS=('format','policy','chain_id','controller_sha256','worker_source_identity',
    'worker_manifest_sha256','root_identity','input_sha256','runtime','original_plan_sha256',
    'original_chain_id','adopted_parent_job_id','adopted_snapshot_sha256',
    'maximum_primary_segments','maximum_observed_seconds','maximum_output_bytes',
    'reserved_diagnostic_slots','execution_budget','execution_budget_identity','plan_identity')
STATE_FIELDS=('format','plan_identity','sequence','previous_sha256','state','command_keys',
    'segments','pending_intent','reason','failed_attempt','observed_seconds','estimate')
SEGMENT_FIELDS=('ordinal','job_id','intent_sha256','checkpoint_sha256','terminal_sha256',
                'clock','observed_seconds','resource_cause')
STATES=('READY_INITIAL','READY_ADOPTED_OUTPUT','RUNNING','DISPATCHING','TIME_BUDGET_CONTINUING',
    'OUTPUT_BUDGET_CONTINUING','USER_PAUSED','COMPLETED','PLAN_EXHAUSTED','ADMISSION_STOP','BLOCKED')

def raw(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def digest(v):return sha256(raw(v)).hexdigest()
def controller_sha():return file_sha(Path(__file__))
def publish(path,value):
    pending=path.with_suffix('.pending');_write_new(pending,raw(value))
    if path.exists():raise ValueError('immutable resource publication already exists')
    os.rename(pending,path) # publish NEW filename; do not replace a reader-held file.

def admit_plan(plan,store,binding,original):
    object_fields(plan,PLAN_FIELDS)
    if plan['format']!=PLAN or plan['policy']!=POLICY or plan['plan_identity']!=digest({k:v for k,v in plan.items() if k!='plan_identity'}):raise ValueError('resource plan version/hash')
    identifier(plan['chain_id']);identifier(plan['original_chain_id'])
    if plan['adopted_parent_job_id'] is None:
        if plan['adopted_snapshot_sha256'] is not None:raise ValueError('initial resource plan cannot borrow state')
    else:identifier(plan['adopted_parent_job_id']);identity(plan['adopted_snapshot_sha256'])
    if plan['controller_sha256']!=controller_sha():raise ValueError('resource controller source drift')
    if plan['worker_source_identity']!=store.source_identity or plan['worker_source_identity']!=project_source_identity() or plan['runtime']!=store.runtime or plan['runtime']!=runtime_identity():raise ValueError('frozen worker source/runtime drift')
    if plan['root_identity']!=store.meta['root_identity'] or plan['input_sha256']!=store.meta['input_sha256']:raise ValueError('resource immutable root/input')
    if plan['worker_manifest_sha256']!=digest(binding):raise ValueError('frozen worker manifest binding')
    if type(binding) is not dict or set(binding)!=set(('revision','source_root','source_sha256','runtime','frozen_utc')) or type(binding['source_sha256']) is not dict or len(binding['source_sha256'])!=659:raise ValueError('explicit frozen worker659 manifest')
    if any(type(binding[k]) is not str for k in ('revision','source_root','frozen_utc')):raise ValueError('worker binding text types')
    for name,h in binding['source_sha256'].items():
        if type(name) is not str:raise ValueError('worker manifest path type')
        identity(h)
    from ops_sim.v5.lifecycle_chain import admit_plan as admit_original
    admit_original(original,store)
    if plan['original_plan_sha256']!=digest(original):raise ValueError('original finite plan binding')
    for key in ('maximum_primary_segments','maximum_observed_seconds','maximum_output_bytes','reserved_diagnostic_slots','execution_budget','execution_budget_identity'):
        if type(plan[key]) is not type(original[key]) or plan[key]!=original[key]:raise ValueError('cannot raise or change original reservation: '+key)
    integer(plan['maximum_primary_segments'],'resource primary maximum',1,6)
    integer(plan['maximum_observed_seconds'],'resource elapsed allowance',1,10800)
    integer(plan['maximum_output_bytes'],'resource job output',2**20,128*2**20)
    if type(plan['reserved_diagnostic_slots']) is not int or plan['reserved_diagnostic_slots']!=2:raise ValueError('reserve MAIN/loupe')
    b=admit_budget(plan['execution_budget'],execution_seconds=plan['execution_budget']['hard_execution_seconds'])
    if b.identity!=plan['execution_budget_identity']:raise ValueError('resource budget hash')
    if store.runner_policy is None or plan['maximum_primary_segments']+2>store.maximum_jobs or (plan['maximum_primary_segments']+2)*plan['maximum_output_bytes']+33*2**20>store.maximum_reserved_job_output_bytes:raise ValueError('unchanged finite store reservations')
    return deepcopy(plan)

class ResourceChain:
    def __init__(self,store,chain_id,*,runner=None):
        self.store=store;self.chain_id=identifier(chain_id);self.folder=store.path('resource-chains',chain_id)
        self.lock=threading.RLock();self.runner=runner or LifecycleRunner(store)
        self.binding=_read(self.folder/'frozen-worker.json',2**20)
        self.original=_read(self.folder/'original-plan.json')
        self.plan=admit_plan(_read(self.folder/'plan.json'),store,self.binding,self.original)
        self._source_admit();self._states()

    @classmethod
    def create_initial(cls,store,chain_id,binding,original_chain_id,*,runner=None):
        """New original experiment: automatic resource chain from its initial authority."""
        identifier(chain_id);identifier(original_chain_id)
        if store.jobs():raise ValueError('initial resource plan requires empty store')
        folder=store.path('resource-chains',chain_id)
        if folder.exists():raise ValueError('new explicit resource plan required')
        original=_read(store.path('chains',original_chain_id,'plan.json'))
        p=dict(format=PLAN,policy=POLICY,chain_id=chain_id,controller_sha256=controller_sha(),
            worker_source_identity=store.source_identity,worker_manifest_sha256=digest(binding),
            root_identity=store.meta['root_identity'],input_sha256=store.meta['input_sha256'],runtime=store.runtime,
            original_plan_sha256=digest(original),original_chain_id=original_chain_id,
            adopted_parent_job_id=None,adopted_snapshot_sha256=None,
            **{k:deepcopy(original[k]) for k in ('maximum_primary_segments','maximum_observed_seconds','maximum_output_bytes','reserved_diagnostic_slots','execution_budget','execution_budget_identity')})
        p['plan_identity']=digest(p);admit_plan(p,store,binding,original)
        source=Path(binding['source_root']).resolve()
        if source!=Path(__file__).resolve().parent or any(file_sha(source/n)!=h for n,h in binding['source_sha256'].items()):raise ValueError('frozen worker admission before publication')
        _write_new(folder/'frozen-worker.json',binding,2**20);_write_new(folder/'original-plan.json',original);_write_new(folder/'plan.json',p)
        temporary=object.__new__(cls);temporary.folder=folder;temporary.plan=p
        temporary._append(dict(state='READY_INITIAL',command_keys=[],segments=[],pending_intent=None,
            reason='NEW_INITIAL_AUTHORITY_NO_BORROWED_STATE',failed_attempt=None,observed_seconds=0.,estimate=None),initial=True)
        return cls(store,chain_id,runner=runner)

    @classmethod
    def adopt(cls,store,chain_id,binding,original_chain_id,parent_job_id,snapshot_sha256,*,runner=None):
        identifier(chain_id);identifier(original_chain_id);identifier(parent_job_id);identity(snapshot_sha256)
        folder=store.path('resource-chains',chain_id)
        if folder.exists():raise ValueError('new explicit resource plan required; no rewrite')
        if len(store.jobs())!=1 or store.jobs()[0]['job_id']!=parent_job_id:raise ValueError('adoption requires the sole existing settled first primary')
        original=_read(store.path('chains',original_chain_id,'plan.json'))
        from ops_sim.v5.lifecycle_chain import admit_plan as admit_original
        admit_original(original,store)
        p=dict(format=PLAN,policy=POLICY,chain_id=chain_id,controller_sha256=controller_sha(),
            worker_source_identity=store.source_identity,worker_manifest_sha256=digest(binding),
            root_identity=store.meta['root_identity'],input_sha256=store.meta['input_sha256'],runtime=store.runtime,
            original_plan_sha256=digest(original),original_chain_id=original_chain_id,
            adopted_parent_job_id=parent_job_id,adopted_snapshot_sha256=snapshot_sha256,
            **{k:deepcopy(original[k]) for k in ('maximum_primary_segments','maximum_observed_seconds','maximum_output_bytes','reserved_diagnostic_slots','execution_budget','execution_budget_identity')})
        p['plan_identity']=digest(p);admit_plan(p,store,binding,original)
        temporary=object.__new__(cls);temporary.store=store;temporary.plan=p
        source=Path(binding['source_root']).resolve()
        if source!=Path(__file__).resolve().parent or any(file_sha(source/n)!=h for n,h in binding['source_sha256'].items()):raise ValueError('frozen worker admission before publication')
        segment=temporary.validate_job(store.job(parent_job_id),1)
        if segment['checkpoint_sha256']!=snapshot_sha256 or segment['resource_cause']!='OUTPUT':raise ValueError('only exact settled first output prefix is adopted')
        _write_new(folder/'frozen-worker.json',binding,2**20);_write_new(folder/'original-plan.json',original);_write_new(folder/'plan.json',p)
        value=dict(state='READY_ADOPTED_OUTPUT',command_keys=[],segments=[segment],pending_intent=None,reason='EXPLICIT_V2_ADOPTION_OF_SETTLED_OUTPUT_PREFIX_NO_REFUND',failed_attempt=None,observed_seconds=segment['observed_seconds'],estimate=None)
        temporary.folder=folder;temporary._append(value,initial=True)
        return cls(store,chain_id,runner=runner)

    def _source_admit(self):
        admit_plan(self.plan,self.store,self.binding,self.original);self.store._pinned()
        source=Path(self.binding['source_root']).resolve()
        if source!=Path(__file__).resolve().parent:raise ValueError('explicit original worker source directory')
        for name,h in self.binding['source_sha256'].items():
            p=Path(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or file_sha(source/p)!=h:raise ValueError('frozen worker byte drift: '+name)
        if _read(self.folder/'plan.json')!=self.plan or _read(self.folder/'frozen-worker.json',2**20)!=self.binding or _read(self.folder/'original-plan.json')!=self.original:raise ValueError('resource saved authority drift')

    def _states(self):
        paths=sorted((self.folder/'states').glob('*.json'))
        if not 1<=len(paths)<=128:raise ValueError('finite resource journal')
        last=None;previous='0'*64
        for n,path in enumerate(paths,1):
            data=path.read_bytes();v=json.loads(data);object_fields(v,STATE_FIELDS)
            if len(data)>256*2**10 or raw(v)!=data or path.name!=f'{n:04}.json' or v['format']!=STATE or type(v['sequence']) is not int or v['sequence']!=n or v['previous_sha256']!=previous or v['plan_identity']!=self.plan['plan_identity'] or type(v['state']) is not str or v['state'] not in STATES:raise ValueError('resource journal binding')
            if type(v['segments']) is not list or not 0<=len(v['segments'])<=self.plan['maximum_primary_segments']:raise ValueError('resource primary population')
            for ordinal,segment in enumerate(v['segments'],1):
                object_fields(segment,SEGMENT_FIELDS)
                if type(segment['ordinal']) is not int or segment['ordinal']!=ordinal:raise ValueError('resource ordinal')
                identifier(segment['job_id']);identity(segment['intent_sha256']);identity(segment['checkpoint_sha256']);identity(segment['terminal_sha256']);integer(segment['clock'],'resource clock')
                if segment['resource_cause'] not in ('OUTPUT','TIME','USER','TARGET') or type(segment['observed_seconds']) not in (int,float) or not 0<=segment['observed_seconds']<float('inf'):raise ValueError('resource segment fields')
            if type(v['command_keys']) is not list or len(v['command_keys'])>32 or len(set(v['command_keys']))!=len(v['command_keys']):raise ValueError('resource command keys')
            for k in v['command_keys']:identifier(k)
            if v['reason'] is not None and (type(v['reason']) is not str or len(v['reason'])>4096):raise ValueError('resource diagnostic reason')
            if v['observed_seconds']!=sum(x['observed_seconds'] for x in v['segments']):raise ValueError('resource settled elapsed no refund')
            if last is not None and (v['segments'][:len(last['segments'])]!=last['segments'] or not set(last['command_keys'])<=set(v['command_keys'])):raise ValueError('resource lineage cannot rewind')
            if v['pending_intent'] is not None and v['pending_intent']!=self._intent(len(v['segments'])+1,v['segments'][-1] if v['segments'] else None):raise ValueError('resource pending intent drift')
            previous=sha256(data).hexdigest();last=v
        return last,previous

    def _append(self,value,*,initial=False):
        if initial:n=1;previous='0'*64
        else:old,previous=self._states();n=old['sequence']+1
        if n>128:raise ValueError('resource journal exhausted')
        v=dict(value,format=STATE,plan_identity=self.plan['plan_identity'],sequence=n,previous_sha256=previous)
        publish(self.folder/'states'/f'{n:04}.json',v);return v
    def _save(self,prior,**updates):
        v={k:deepcopy(v) for k,v in prior.items() if k not in ('format','plan_identity','sequence','previous_sha256')};v.update(updates);return self._append(v)
    def _intent(self,ordinal,parent):
        p=self.plan;b=admit_budget(p['execution_budget'],execution_seconds=p['execution_budget']['hard_execution_seconds'])
        key=sha256((p['plan_identity']+':'+str(ordinal)+':'+('INITIAL' if parent is None else parent['checkpoint_sha256'])).encode()).hexdigest()[:32]
        return make_intent(p['root_identity'],key=key,parent_job_id=None if parent is None else parent['job_id'],snapshot_sha256=None if parent is None else parent['checkpoint_sha256'],execution_seconds=b.hard_execution_seconds,maximum_output_bytes=p['maximum_output_bytes'],execution_budget=b)

    def validate_job(self,job,ordinal):
        if job['status'] not in TERMINAL or job['ownership_valid'] is not True or job['launch'] is None or job['launch'].get('forced_interruption') is not False or job['launch'].get('timeout') is not False or job['launch'].get('unexpected') is not None:raise ValueError('resource refuses unknown/forced/failure authority')
        r=job['result']
        if r is None:raise ValueError('resource needs terminal and settled receipt')
        _admit_execution_terminal(job,r)
        app=r['application_status']
        if app=='COMPLETED_WINDOW' and r['clock']==self.store.root_input.end_seconds:cause='TARGET'
        elif app=='INCOMPLETE_BUDGET_STOP' and r['reason']=='WORKER_LOCAL_SOFT_BUDGET_PAID_PREFIX':cause='TIME'
        elif app=='INCOMPLETE_APPLICATION_ADMISSION' and r['reason']==OUTPUT_REASON:cause='OUTPUT'
        elif app=='INCOMPLETE_STOP' and r['reason']=='USER_COOPERATIVE_STOP_BEFORE_NEXT_MODEL_TRANSITION':cause='USER'
        else:raise ValueError('resource terminal reason is not an approved settled resource cut')
        if cause!='TARGET' and r['status']!='ACTIVE':raise ValueError('resource native must remain ACTIVE')
        if job['source_identity']!=self.store.meta['source_identity'] or job['runtime']!=self.store.meta['runtime'] or job['root_identity']!=self.store.meta['root_identity']:raise ValueError('resource worker/root/runtime binding')
        cp=r['checkpoint'];folder=self.store.path('jobs',job['job_id'])
        if cp['kind']!='FINAL' or cp not in job['checkpoints'] or cp['clock']!=r['clock'] or cp['bindings']!=make_bindings(self.store.root_input,cp['clock']):raise ValueError('resource exact final native')
        _settled_publication_work(folder,self.store.root_input,job,r);_admit_publication(folder,cp,self.store.root_input,settled=True)
        data=(folder/cp['file']).read_bytes();admit_checkpoint(data,self.store.root_input,expected_sha256=cp['sha256'],expected_bindings=cp['bindings'])
        _verify_checkpoint_streams(folder,cp,self.store.root_input,reserve=lambda n:self.store._reserve_saved_read(job['job_id'],n))
        if file_sha(folder/'terminal.json')!=sha256(raw(r)).hexdigest():raise ValueError('resource exact terminal bytes')
        elapsed=job['launch']['observed_envelope_seconds']
        if type(elapsed) not in (int,float) or not 0<=elapsed<float('inf'):raise ValueError('resource finite envelope')
        return dict(ordinal=ordinal,job_id=job['job_id'],intent_sha256=digest(job['intent']),checkpoint_sha256=cp['sha256'],terminal_sha256=file_sha(folder/'terminal.json'),clock=r['clock'],observed_seconds=elapsed,resource_cause=cause)

    def _paused(self,state):
        consumed=0
        for path in sorted((self.folder/'states').glob('*.json')):
            v=_read(path)
            if v['reason']=='EXPLICIT_CONTINUE':consumed=max(consumed,v['sequence']-1)
        for path in self.folder.glob('pause-*.json'):
            v=_read(path);object_fields(v,('plan_identity','sequence'))
            if v['plan_identity']!=self.plan['plan_identity'] or path.name!=f"pause-{v['sequence']:04}.json":raise ValueError('resource pause binding')
            if v['sequence']>consumed:return True
        return False
    def snapshot(self):
        self._source_admit();state,_=self._states();job=None
        if self.runner.active is not None:job=self.store.job(self.runner.active)
        return dict(plan=deepcopy(self.plan),state=state,active_job_id=self.runner.active,
            live_progress=None if job is None else job['progress'],active_job_created_utc=None if job is None else job['created_utc'])
    def stop(self):
        with self.lock:
            state=self.snapshot()['state'];path=self.folder/f"pause-{state['sequence']:04}.json"
            if not path.exists():publish(path,dict(plan_identity=self.plan['plan_identity'],sequence=state['sequence']))
            if self.runner.active is not None:self.runner.stop(self.runner.active)
            elif state['pending_intent'] is not None:
                job=self.store.reconcile(state['pending_intent'])
                if job is not None and job['status'] not in TERMINAL:
                    marker=self.store.path('jobs',job['job_id'],'stop-request.json')
                    if not marker.exists():_write_stop_request(marker,job)
            return self.snapshot()

    def run(self,key):
        identifier(key)
        with self.lock:
            state=self.snapshot()['state']
            if key in state['command_keys'] or state['state'] in ('COMPLETED','BLOCKED','PLAN_EXHAUSTED','ADMISSION_STOP'):return self.snapshot()
            if list((self.folder/'states').glob('*.pending')):raise ValueError('unpublished resource state; no retry')
            owner=self.folder/'owner.json';token=dict(token=uuid.uuid4().hex,PID=os.getpid(),plan_identity=self.plan['plan_identity'])
            _write_new(owner,token)
            state=self._save(state,command_keys=[*state['command_keys'],key],reason='EXPLICIT_CONTINUE')
        try:
            while True:
                self.snapshot()
                if self._paused(state):state=self._save(state,state='USER_PAUSED',reason='USER_STOP');break
                if len(state['segments'])>=self.plan['maximum_primary_segments']:state=self._save(state,state='PLAN_EXHAUSTED',reason='ORIGINAL_FINITE_PRIMARY_LIMIT');break
                b=self.plan['execution_budget'];remaining=self.plan['maximum_observed_seconds']-state['observed_seconds']
                if remaining<b['hard_execution_seconds']+2:state=self._save(state,state='ADMISSION_STOP',reason='CANNOT_RESERVE_FULL_NEXT_SLOT');break
                parent=state['segments'][-1] if state['segments'] else None
                if parent is not None and self.validate_job(self.store.job(parent['job_id']),parent['ordinal'])!=parent:raise ValueError('resource stale/tampered parent')
                ordinal=len(state['segments'])+1;intent=self._intent(ordinal,parent)
                with self.lock:
                    if self._paused(state):state=self._save(state,state='USER_PAUSED',reason='USER_STOP');break
                    state=self._save(state,state='DISPATCHING',pending_intent=intent,reason=None)
                    job=self.runner.submit(intent);state=self._save(state,state='RUNNING')
                thread=self.runner.thread
                if thread is not None:thread.join(b['hard_execution_seconds']+3)
                if thread is not None and thread.is_alive():raise RuntimeError('resource owned worker did not settle')
                job=self.store.job(job['job_id']);segment=self.validate_job(job,ordinal)
                if segment['clock']<=(parent['clock'] if parent is not None else self.store.root_input.start_seconds):raise ValueError('resource no progress; no blind retry')
                segments=[*state['segments'],segment];elapsed=sum(x['observed_seconds'] for x in segments)
                estimate=dict(method='OBSERVED_CUMULATIVE_RATE_NOT_RUNTIME_BOUND',remaining_seconds=elapsed*(self.store.root_input.end_seconds-segment['clock'])/(segment['clock']-self.store.root_input.start_seconds))
                state=self._save(state,segments=segments,observed_seconds=elapsed,pending_intent=None,estimate=estimate)
                if segment['clock']==self.store.root_input.end_seconds:state=self._save(state,state='COMPLETED',reason='IMMUTABLE_TARGET');break
                if segment['resource_cause']=='USER' or self._paused(state):state=self._save(state,state='USER_PAUSED',reason='USER_STOP');break
                if estimate['remaining_seconds']>self.plan['maximum_observed_seconds']-elapsed:state=self._save(state,state='ADMISSION_STOP',reason='MEASURED_RATE_CANNOT_FIT');break
                state=self._save(state,state='OUTPUT_BUDGET_CONTINUING' if segment['resource_cause']=='OUTPUT' else 'TIME_BUDGET_CONTINUING',reason=segment['resource_cause'])
        except BaseException as error:
            failed=None
            if state['pending_intent'] is not None:
                failed=self.store.reconcile(state['pending_intent'])
            state=self._save(state,state='BLOCKED',reason=type(error).__name__+': '+str(error),failed_attempt=failed)
            raise
        finally:
            if _read(owner)!=token:raise RuntimeError('foreign resource owner; preserve')
            owner.unlink()
        return self.snapshot()


class ResourceWorkbench:
    """Explicit same-origin adapter around the existing Workbench application.

    Does not replace its scientific owners, old routes, assets or store metadata.
    The additional page/JS are bound by this controller's plan hash, separately
    from the unmodified worker source hash. Reopen never starts its run thread.
    """
    def __init__(self,app,chain):
        self.app=app;self.chain=chain;self.thread=None;self.error=None
        rid=chain.store.meta['root_identity'];key=(rid,chain.chain_id)
        app.lifecycle.stores[rid]=chain.store
        app.lifecycle.runners[rid]=chain.runner
        self.key=key
    def continue_command(self,body):
        object_fields(body,('command_key',));identifier(body['command_key'])
        with self.app.dispatch_lock:
            state=self.chain.snapshot()['state']
            if body['command_key'] in state['command_keys']:return self.chain.snapshot()
            if self.thread is not None and self.thread.is_alive():return self.chain.snapshot()
            if self.app.runner.active is not None or self.app.lifecycle.active is not None:raise ValueError('another owned worker active')
            def execute():
                try:self.chain.run(body['command_key'])
                except BaseException as error:
                    import traceback
                    self.error=dict(type=type(error).__name__,reason=str(error),traceback=traceback.format_exc())
            self.thread=threading.Thread(target=execute,name='B55R2-resource-chain',daemon=False)
            # Existing application shutdown/active-owner checks include this
            # adapter between segments too. No second scientific worker can fit.
            self.app.lifecycle.chains[self.key]=self.chain
            self.app.lifecycle.chain_threads[self.key]=self.thread
            self.thread.start();return self.chain.snapshot()
    def handler(self):
        adapter=self;base=self.app.handler()
        class Handler(base):
            def do_GET(self):
                if self.path not in ('/resource-chain','/resource-chain.js','/api/resource-chain/state'):return super().do_GET()
                try:
                    self.guard()
                    if self.path=='/resource-chain':
                        page=('<!doctype html><meta charset="utf-8"><title>Resource chain</title>'
                            '<meta name="csrf" content="'+adapter.app.token+'"><link rel="stylesheet" href="/workbench.css">'
                            '<h1>Bounded resource chain V2</h1><p>Time/output budget: automatic continuation. User Stop: pause.</p>'
                            '<button id="continue">Run / Continue</button><button id="stop">User Stop</button>'
                            '<p id="elapsed"></p><pre id="status"></pre><script src="/resource-chain.js"></script>')
                        self.respond(200,page.encode(),'text/html; charset=utf-8',True)
                    elif self.path=='/resource-chain.js':self.respond(200,RESOURCE_JS.encode(),'text/javascript; charset=utf-8')
                    else:self.respond(200,adapter.chain.snapshot())
                except (ValueError,TypeError,KeyError,OSError) as e:self.respond(400,dict(error=str(e)))
            def do_POST(self):
                if self.path not in ('/api/resource-chain/continue','/api/resource-chain/stop'):return super().do_POST()
                try:
                    self.guard(True);lengths=self.headers.get_all('Content-Length')
                    if lengths is None or len(lengths)!=1 or not lengths[0].isdigit() or not 0<int(lengths[0])<=4096:raise ValueError('bounded exact resource request length')
                    from ops_sim.v5.experiment_codec import parse_json
                    body=parse_json(self.rfile.read(int(lengths[0])).decode())
                    if self.path.endswith('/continue'):result=adapter.continue_command(body)
                    else:object_fields(body,());result=adapter.chain.stop()
                    self.respond(200,result)
                except (ValueError,TypeError,KeyError,OSError,RuntimeError) as e:self.respond(400,dict(error=str(e)))
        return Handler
    def close(self):
        if self.thread is not None and self.thread.is_alive():self.chain.stop()
        self.chain.runner.close()
        if self.thread is not None:self.thread.join(3)
        if self.thread is not None and self.thread.is_alive():raise RuntimeError('resource adapter thread not settled')


RESOURCE_JS=r"""'use strict';
const token=document.querySelector('meta[name=csrf]').content;
let latest=null;
async function api(path,body){const r=await fetch('/api/resource-chain/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':token},body:body===undefined?undefined:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error);return v;}
async function refresh(){latest=await api('state');const key='resource-command-'+latest.plan.plan_identity,pending=localStorage.getItem(key);if(pending&&latest.state.command_keys.includes(pending))localStorage.removeItem(key);document.getElementById('status').textContent=JSON.stringify({state:latest.state.state,reason:latest.state.reason,segments:latest.state.segments,settled_envelope_seconds:latest.state.observed_seconds,model_progress:latest.live_progress,estimate:latest.state.estimate},null,2);document.getElementById('elapsed').textContent=latest.active_job_created_utc?'Current job UTC age (not worker CPU/monotonic): '+Math.max(0,(Date.now()-Date.parse(latest.active_job_created_utc))/1000).toFixed(1)+' s':'No active owned worker';}
document.getElementById('continue').onclick=async()=>{try{await refresh();const key='resource-command-'+latest.plan.plan_identity;let command=localStorage.getItem(key);if(!command){command=crypto.randomUUID().replaceAll('-','');localStorage.setItem(key,command);}await api('continue',{command_key:command});await refresh();}catch(e){document.getElementById('status').textContent=String(e);}};
document.getElementById('stop').onclick=async()=>{try{await api('stop',{});await refresh();}catch(e){document.getElementById('status').textContent=String(e);}};
refresh().catch(e=>document.getElementById('status').textContent=String(e));setInterval(()=>refresh().catch(e=>document.getElementById('status').textContent=String(e)),1500);
"""

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--store',type=Path,required=True);p.add_argument('--chain-id',required=True)
    sub=p.add_subparsers(dest='action',required=True)
    c=sub.add_parser('adopt');c.add_argument('--worker-binding',type=Path,required=True);c.add_argument('--original-chain-id',required=True);c.add_argument('--parent-job',required=True);c.add_argument('--snapshot-sha256',required=True)
    c=sub.add_parser('create');c.add_argument('--worker-binding',type=Path,required=True);c.add_argument('--original-chain-id',required=True)
    c=sub.add_parser('serve');c.add_argument('--app-store',type=Path,required=True);c.add_argument('--port',type=int,default=8765)
    c=sub.add_parser('run');c.add_argument('--command-key',required=True)
    sub.add_parser('status');sub.add_parser('stop');a=p.parse_args(argv);store=LifecycleStore(a.store)
    if a.action=='adopt':chain=ResourceChain.adopt(store,a.chain_id,_read(a.worker_binding,2**20),a.original_chain_id,a.parent_job,a.snapshot_sha256)
    elif a.action=='create':chain=ResourceChain.create_initial(store,a.chain_id,_read(a.worker_binding,2**20),a.original_chain_id)
    else:chain=ResourceChain(store,a.chain_id)
    if a.action=='serve':
        from http.server import ThreadingHTTPServer
        from ops_sim.v5.project_store import ProjectStore
        from ops_sim.v5.lifecycle_application import LifecycleWorkspace
        from ops_sim.v5.project_workbench import Workbench
        integer(a.port,'loopback port',0,65535)
        projects=ProjectStore(a.app_store,store.root_input.base,create=not a.app_store.exists())
        workspace=LifecycleWorkspace(projects.path('lifecycle'),project_store=projects)
        app=Workbench(projects,lifecycle_workspace=workspace);adapter=ResourceWorkbench(app,chain)
        server=ThreadingHTTPServer(('127.0.0.1',a.port),adapter.handler());app.server=server
        try:
            print('http://127.0.0.1:'+str(server.server_port)+'/resource-chain',flush=True)
            server.serve_forever(poll_interval=.1)
        finally:adapter.close();workspace.close();app.runner.close();server.server_close();app.release_owner()
        return
    try:result=chain.run(a.command_key) if a.action=='run' else chain.stop() if a.action=='stop' else chain.snapshot();print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except KeyboardInterrupt:chain.stop();raise
    finally:chain.runner.close()

if __name__=='__main__':main()
