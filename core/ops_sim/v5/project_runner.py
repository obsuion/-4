"""Owned finite Windows project jobs; polling never invokes the model."""
from pathlib import Path
import datetime,json,math,os,sys,threading,time,traceback
from .project_store import file_sha,identifier,TERMINAL
from .project_worker import PROGRESS
from .experiment_codec import object_fields,parse_json

def validate_progress(record,identity,expected_sequence):
    object_fields(record,('format','sequence','kind','identity','data'))
    if record['format']!=PROGRESS or type(record['sequence']) is not int or record['sequence']!=expected_sequence or record['identity']!=identity:
        raise ValueError('journal schema/sequence/identity')
    fields={
        'identity':('worker_PID','worker_PPID','runtime'),
        'boundary':('validated','clock','clock_exact','completed_decisions','status','pending','partial_bits','received_at','received_credit_scope','forecast_scope','work'),
        'checkpoint':('file','sha256','bytes','clock','pending','partial_bits','completed_decisions'),
        'reconstruction':('method','replay_completed_decisions','scientific_equal','prior_work_retained','additional_work_charged'),
        'snapshot':('file','sha256','bytes','clock','bindings','pending','partial_bits','queued_packet_ids','completed_decisions'),
        'direct_restore':('method','restored_clock','prefix_actual_calls','prefix_forecast_calls','prefix_force_calls','validation_control_units','prior_work_retained'),
        'completed':('terminal_sha256','scientific_sha256','clock'),
        'failure':('type','reason','final_physics')}
    if type(record['kind']) is not str or record['kind'] not in fields:raise ValueError('journal kind')
    object_fields(record['data'],fields[record['kind']])
    d=record['data'];kind=record['kind']
    if kind=='identity':
        if any(type(d[n]) is not int or d[n]<=0 for n in ('worker_PID','worker_PPID')):raise ValueError('exact actual worker identity')
        object_fields(d['runtime'],('python','platform','executable','interpreter_sha256'))
    if kind in ('boundary','checkpoint','completed'):
        if type(d['clock']) not in (int,float) or not math.isfinite(d['clock']) or not 128<=d['clock']<=728:raise ValueError('finite bounded display clock')
    if kind in ('boundary','checkpoint'):
        if type(d['completed_decisions']) is not int or not 0<=d['completed_decisions']<=64:raise ValueError('strict decision counter')
        if type(d['pending']) is not list or len(d['pending'])>8 or any(type(n) is not str or n not in ('POINT','CAPTURE','CONTACT','HOLD_UNTIL') for n in d['pending']):raise ValueError('pending command schema')
        if type(d['partial_bits']) is not list or len(d['partial_bits'])>16 or any(type(n) not in (int,float) or not math.isfinite(n) or n<0 for n in d['partial_bits']):raise ValueError('returned partial bits')
    if kind=='boundary':
        if d['validated'] is not True or d['status'] not in ('ACTIVE','COMPLETE'):raise ValueError('validated actual boundary status')
        if type(d['received_at']) not in (int,float) or not math.isfinite(d['received_at']) or not 128<=d['received_at']<=d['clock']:raise ValueError('received observation time')
        object_fields(d['work'],('decisions','forecast_invocations','actual_physical_reserved','control_reserved','reconstructions'))
        if any(type(v) is not int or not 0<=v<=2**48 for v in d['work'].values()):raise ValueError('strict paid work counters')
        if d['received_credit_scope']!='RECEIVED_OBSERVATION_ONLY' or d['forecast_scope']!='PRIVATE_UNCONFIRMED_COMMAND_ESTIMATE':raise ValueError('knowledge scope')
    if kind=='checkpoint':
        if d['file']!='checkpoint.rolling.json' or type(d['bytes']) is not int or not 0<d['bytes']<=64*2**20:raise ValueError('causal packet publication')
    if kind=='snapshot':
        from .rolling_snapshot import checked_bindings
        checked_bindings(d['bindings'])
        if d['file'] not in ('snapshot-136.json','snapshot-200.json') or type(d['bytes']) is not int or not 0<d['bytes']<=128*2**20 or d['clock']!=d['bindings']['clock']:raise ValueError('generated snapshot journal')
    if kind=='direct_restore':
        from .rolling_snapshot import METHOD
        if d['method']!=METHOD or any(type(d[n]) is not int or d[n]!=0 for n in ('prefix_actual_calls','prefix_forecast_calls','prefix_force_calls')) or d['prior_work_retained'] is not True:raise ValueError('direct proof journal')
    for n in ('sha256','terminal_sha256','scientific_sha256'):
        if n in d:
            from .design_repair import hash_identity
            hash_identity(d[n])
    return record

class IncrementalJournal:
    def __init__(self,path,identity,limit):self.path=path;self.identity=identity;self.limit=limit;self.offset=0;self.tail=b'';self.sequence=0;self.records=[]
    def read(self):
        if not self.path.exists():return []
        if self.path.stat().st_size>self.limit:raise ValueError('progress byte cap')
        with self.path.open('rb') as f:f.seek(self.offset);new=f.read(self.limit-self.offset+1)
        self.offset+=len(new);data=self.tail+new;lines=data.split(b'\n');self.tail=lines.pop();fresh=[]
        if len(self.tail)>16384:raise ValueError('incomplete record cap')
        for line in lines:
            if not line or len(line)>16384:raise ValueError('complete progress record cap')
            record=validate_progress(parse_json(line.decode()),self.identity,self.sequence+1)
            self.sequence+=1;self.records.append(record);fresh.append(record)
        if self.sequence>256:raise ValueError('progress record count')
        return fresh

class ProjectRunner:
    def __init__(self,store,*,job_factory=None,on_launch=None,on_finish=None):
        self.store=store;self.factory=job_factory;self.on_launch=on_launch;self.on_finish=on_finish
        self.lock=threading.RLock();self.active=None;self.thread=None;self.stop_event=threading.Event();self.closing=False
    def submit(self,pid,revision,key,*,resume_job=None,intent=None):
        with self.lock:
            from .spacecraft_project import require_short_project
            require_short_project(self.store.load(pid,revision))
            if self.closing:raise ValueError('dispatch closed')
            # Exact known duplicate returns current identity without another child.
            for j in self.store.jobs(pid):
                if j['idempotency_key']==key:
                    if j['revision']!=revision or j['resume_from']!=resume_job or intent is not None and j.get('intent')!=intent:raise ValueError('idempotency key drift')
                    return j
            if self.active is not None:raise ValueError('one owned job at a time in this bounded workbench')
            job,new=self.store.prepare_job(pid,revision,key,resume_job=resume_job,intent=intent)
            if not new:return job
            if self.on_launch is not None:
                try:self.on_launch(job)
                except BaseException as error:
                    job['status']='REFUSED';job['reason']='BEFORE_OWNED_LAUNCH_ADMISSION:'+str(error)
                    job['ownership_valid']=True;self.store.update_job(job);raise
            self.active=job['job_id'];self.stop_event.clear()
            self.thread=threading.Thread(target=self._run,args=(job,),name='M8-owned-job-'+job['job_id'],daemon=False)
            self.thread.start();return self.store.job(job['job_id'])
    def stop(self,jid):
        identifier(jid)
        with self.lock:
            if jid!=self.active:
                job=self.store.job(jid)
                if job['status'] in TERMINAL:return job
                raise ValueError('no owned current handle for this job')
            self.stop_event.set();job=self.store.job(jid);job['status']='STOP_REQUESTED';self.store.update_job(job);return job
    def _run(self,job):
        try:self._execute_job(job)
        except BaseException as error:
            job['status']='UNKNOWN' if job['launch'] is not None and job['ownership_valid'] is not True else 'PROCESS_FAILED'
            job['reason']='PARENT_SETUP_OR_REPORTING:'+str(error)
            job['parent_failure']=traceback.format_exc();self.store.update_job(job)
            with self.lock:
                if job['launch'] is None or job['ownership_valid'] is True:self.active=None
    def _execute_job(self,job):
        project=self.store.load(job['project_id'],job['revision']);directory=self.store.path('jobs',job['job_id'])
        cmd=[sys.executable,'-B','-m','ops_sim.v5.project_worker','--store',str(self.store.root),
            '--job',job['job_id'],'--request-sha256',file_sha(directory/'request.json')]
        reader=IncrementalJournal(directory/'progress.jsonl',{n:job[n] for n in ('job_id','revision','source_identity','root_identity')},project.limits.maximum_progress_bytes)
        child=None;cleanup=None;seen=set();timed_out=False;stopped=False;unexpected=None;completed=None;identity=None
        start=time.perf_counter();launch=dict(command=cmd,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            execution_seconds=project.limits.execution_seconds,cleanup_seconds=2,source_identity=job['source_identity'],owned_seen_PIDs=[])
        def accept(fresh):
            nonlocal completed,identity
            for rec in fresh:
                if rec['kind']=='identity':identity=rec['data']
                elif rec['kind']=='boundary':job['progress']=rec['data']
                elif rec['kind']=='checkpoint':
                    cp=rec['data'];p=self.store.path('jobs',job['job_id'],cp['file'])
                    if cp['file']!='checkpoint.rolling.json' or p.stat().st_size!=cp['bytes'] or file_sha(p)!=cp['sha256']:raise ValueError('validated checkpoint publication SHA')
                    job['checkpoint']=cp
                elif rec['kind']=='snapshot':
                    cp=rec['data'];p=self.store.path('jobs',job['job_id'],cp['file'])
                    if p.stat().st_size!=cp['bytes'] or file_sha(p)!=cp['sha256']:raise ValueError('snapshot publication binding')
                    if any(s['clock']==cp['clock'] for s in job['snapshots']):raise ValueError('duplicate snapshot publication')
                    job['snapshots'].append(cp)
                elif rec['kind']=='direct_restore':job['direct_restore']=rec['data']
                elif rec['kind']=='completed':completed=rec['data']
            if fresh:
                with self.lock:
                    if self.stop_event.is_set():job['status']='STOP_REQUESTED'
                    self.store.update_job(job)
        try:
            job['status']='ADMITTED';self.store.update_job(job)
            factory=self.factory
            if factory is None:
                if os.name!='nt':raise RuntimeError('owned actual runner is Windows-only; preview/codec remain portable')
                from .project_windows_job import OwnedJob
                factory=OwnedJob
            temp=directory/'tmp';temp.mkdir(exist_ok=False)
            with (directory/'stdout.log').open('xb') as out,(directory/'stderr.log').open('xb') as err:
                if self.stop_event.is_set():stopped=True
                else:
                    child=factory(cmd,Path(__file__).resolve().parents[2],dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',
                        PYTHONPATH=str(Path(__file__).resolve().parents[2]),TEMP=str(temp),TMP=str(temp),GIT_OPTIONAL_LOCKS='0'),out,err)
                    launch['root_PID']=child.pid;launch['assigned_before_execution']=child.assigned_before_resume
                    job['status']='RUNNING';self.store.update_job(job)
                    while True:
                        state=child.state();seen.update(state['job_active_PIDs']);code=child.poll()
                        accept(reader.read())
                        if out.tell()+err.tell()>2**20:raise ValueError('bounded worker log output')
                        elapsed=time.perf_counter()-start
                        if self.stop_event.is_set():stopped=True;break
                        if elapsed>=project.limits.execution_seconds:timed_out=True;break
                        if code is not None and state['job_active_count']==0:break
                        time.sleep(min(.1,max(0.,project.limits.execution_seconds-elapsed)))
                    cleanup=child.reap(kill=stopped or timed_out,max_seconds=2.,cleanup_deadline=time.perf_counter()+2.)
        except BaseException as error:
            unexpected=dict(type=type(error).__name__,reason=str(error),traceback=traceback.format_exc())
            if child is not None and not child.closed:
                cleanup=child.reap(kill=True,max_seconds=2.,cleanup_deadline=time.perf_counter()+2.)
        finally:
            try:accept(reader.read())
            except BaseException as error:unexpected=unexpected or dict(type=type(error).__name__,reason=str(error),scope='final journal read')
            valid=cleanup is not None and cleanup['owned_job_empty'] and cleanup['root_signaled'] and cleanup['root_status_captured'] and cleanup['handles_closed'] and not cleanup['errors'] and cleanup['cleanup_within_two_seconds']
            if stopped and child is None:valid=True
            if identity is not None and identity['worker_PID'] not in seen:valid=False
            launch.update(cleanup=cleanup,owned_seen_PIDs=sorted(seen),worker_identity=identity,
                ownership_valid=valid,stopped=stopped,timeout=timed_out,reader_sequence=reader.sequence,
                incomplete_tail_bytes=len(reader.tail),unexpected=unexpected,observed_envelope_seconds=time.perf_counter()-start,
                ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            job['launch']=launch;job['ownership_valid']=valid
            if not valid:job['status']='UNKNOWN';job['reason']='OWNERSHIP_CLEANUP_UNRESOLVED'
            elif stopped:job['status']='CANCELLED';job['reason']='USER_STOP_OWNED_ONLY'
            elif timed_out:job['status']='INCOMPLETE';job['reason']='EXECUTION_DEADLINE_NO_ENDPOINT'
            elif unexpected:job['status']='PROCESS_FAILED';job['reason']=unexpected['reason']
            elif cleanup['root_exit_code']!=0:job['status']='PROCESS_FAILED';job['reason']='OWNED_WORKER_EXIT_'+str(cleanup['root_exit_code'])
            elif completed is None or reader.tail:job['status']='INCOMPLETE';job['reason']='NO_VALID_TERMINAL_PUBLICATION'
            else:
                try:
                    terminal=self.store.path('jobs',job['job_id'],'terminal.json')
                    if file_sha(terminal)!=completed['terminal_sha256']:raise ValueError('terminal publication hash')
                    record=self.store.read_json('jobs',job['job_id'],'terminal.json')
                    if record['scientific_sha256']!=completed['scientific_sha256']:raise ValueError('science terminal link')
                    self.store.seal_result(job,record);job['status']='COMPLETED'
                except BaseException as error:job['status']='PROCESS_FAILED';job['reason']=str(error)
            with self.lock:
                self.store.update_job(job)
                if valid:self.active=None
            if self.on_finish is not None:self.on_finish(job)
    def close(self):
        with self.lock:
            self.closing=True
            if self.active is not None:self.stop_event.set()
            thread=self.thread
        if thread is not None:thread.join(timeout=5.)
        if thread is not None and thread.is_alive():raise RuntimeError('owned runner shutdown did not settle')
        if self.active is not None:raise RuntimeError('owned cleanup unresolved; no dispatch restart')
