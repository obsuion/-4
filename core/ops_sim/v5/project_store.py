"""Bounded local M8 store. Client identifiers never become arbitrary paths.

Trusted local filesystem: reparse/symlink paths reject at every access. The
standard-library check/open sequence is not advertised as hostile-FS race proof.
"""
from .lifetime_io_accounting import fsync as _io_fsync
from dataclasses import asdict,replace
from hashlib import sha256
from pathlib import Path
from functools import wraps
import csv,io,json,os,re,secrets,sys,threading,uuid,zipfile
from .spacecraft_project import (SpacecraftProject,ProjectLimits,project_source_identity,
    preview_project,edit_project)
from .spacecraft_project_document import dumps_project,loads_project,MAX_BYTES
from .design_repair import ConstructorLedger,MissionRequirements
from .design_repair_study import ceiling_for
from .command_document import inputs_to_json as root_to_json
from .long_mission_document import canonical_json
from .experiment_codec import parse_json,object_fields
from .rolling_physics import digest
from .project_intents import validate_intent, intent_identity, make_intent, INITIAL, CAUSAL, DIRECT

STORE='M8_LOCAL_PROJECT_STORE_V2'
RESULT='M8_PINNED_ACTUAL_PROJECT_RESULT_V1'
JOB='M8_OWNED_PROJECT_JOB_V1'
TERMINAL=('COMPLETED','REFUSED','INCOMPLETE','CANCELLED','PROCESS_FAILED','UNKNOWN')
ID=re.compile(r'^[0-9a-f]{32}$');REV=re.compile(r'^[0-9a-f]{64}$')

def identifier(v,*,revision=False):
    if type(v) is not str or not (REV if revision else ID).fullmatch(v):raise ValueError('exact generated identifier')
    return v

def runtime_identity():
    return dict(python=sys.version,platform=sys.platform,executable=sys.executable,
        interpreter_sha256=sha256(Path(sys.executable).read_bytes()).hexdigest())

def file_sha(p):return sha256(Path(p).read_bytes()).hexdigest()

def synchronized(method):
    @wraps(method)
    def protected(self,*args,**kwargs):
        # Owned server threads close read handles before mutable replacement.
        with self.lock:return method(self,*args,**kwargs)
    return protected

class ProjectStore:
    def __init__(self,directory,reference,*,create=False,recover=False):
        self.lock=threading.RLock();self._inputs={};self._historical=[];self.root=Path(directory).absolute();self.reference=reference
        self.reference_identity=digest(reference);self.source_identity=project_source_identity()
        self._reject_links(self.root)
        # Never write any repository tree, including a worktree .git file.
        if any((p/'.git').exists() for p in (self.root,*self.root.parents)):
            raise ValueError('project directory must be outside repository trees')
        if create:
            if self.root.exists():raise ValueError('new project store must not already exist')
            self.root.mkdir(parents=True)
            self.meta=dict(format=STORE,version=2,reference_identity=self.reference_identity,
                source_identity=self.source_identity,projects=[],reserved_bytes=0,published_metadata_bytes=0,
                constructor=dict(maximum_compiles=32,compiles=0,control_reserved=0),exports=0,
                snapshot_control=dict(admission_attempts=0,reserved_units=0,scope='SEPARATE_WRAPPER_CONTROL_NOT_SCIENTIFIC_CREDIT'))
            self._write(('store.json',),self.meta,mutable=True)
        else:
            self.meta=self.read_json('store.json')
            object_fields(self.meta,('format','version','reference_identity','source_identity','projects','reserved_bytes','published_metadata_bytes','constructor','exports','snapshot_control'))
            if self.meta['format']!=STORE or type(self.meta['version']) is not int or self.meta['version']!=2:
                raise ValueError('store version')
            if self.meta['reference_identity']!=self.reference_identity or self.meta['source_identity']!=self.source_identity:
                raise ValueError('store source/template mismatch; no automatic migration')
            if type(self.meta['projects']) is not list or len(self.meta['projects'])>16 or len(set(self.meta['projects']))!=len(self.meta['projects']):raise ValueError('project population')
            for p in self.meta['projects']:identifier(p)
            if type(self.meta['reserved_bytes']) is not int or not 0<=self.meta['reserved_bytes']<=2**31:raise ValueError('store retention admission')
            ConstructorLedger(**self.meta['constructor']).validate()
            c=object_fields(self.meta['snapshot_control'],('admission_attempts','reserved_units','scope'))
            if type(c['admission_attempts']) is not int or not 0<=c['admission_attempts']<=512 or type(c['reserved_units']) is not int or not 0<=c['reserved_units']<=2**34 or c['scope']!='SEPARATE_WRAPPER_CONTROL_NOT_SCIENTIFIC_CREDIT':raise ValueError('snapshot control ledger')
            for pid in self.meta['projects'] if recover else ():
                for job in self.jobs(pid):
                    # Dead handles are not reconstituted from a PID or assumed killed.
                    if job['status'] in ('QUEUED','ADMITTED','RUNNING','STOP_REQUESTED'):
                        job['status']='UNKNOWN';job['reason']='REOPEN_REQUIRES_OWNERSHIP_RECONCILIATION'
                        self.update_job(job)
    @staticmethod
    def _reject_links(path):
        for p in (path,*path.parents):
            if p.exists() or p.is_symlink():
                st=p.lstat()
                if p.is_symlink() or getattr(st,'st_file_attributes',0)&0x400:
                    raise ValueError('symlink/junction/reparse path rejected')
    def path(self,*parts):
        if not parts or any(type(p) is not str or p in ('','.','..') or '/' in p or '\\' in p or ':' in p for p in parts):
            raise ValueError('only fixed basenames and generated IDs')
        p=self.root.joinpath(*parts);self._reject_links(p)
        if not p.resolve().is_relative_to(self.root.resolve()):raise ValueError('store containment')
        return p
    @synchronized
    def read_json(self,*parts,cap=16*2**20):
        p=self.path(*parts)
        if p.stat().st_size>cap:raise ValueError('stored document cap')
        return parse_json(p.read_text(encoding='utf-8'))
    @synchronized
    def _write(self,parts,value,*,mutable=False,cap=16*2**20):
        raw=canonical_json(value).encode()
        if len(raw)>cap:raise ValueError('metadata publication bytes')
        p=self.path(*parts);p.parent.mkdir(parents=True,exist_ok=True);self._reject_links(p.parent)
        if p.exists() and not mutable:raise ValueError('immutable stored artifact already exists')
        temp=self.path(*parts[:-1],'tmp-'+uuid.uuid4().hex+'.json')
        with temp.open('xb') as f:f.write(raw);f.flush();_io_fsync(f.fileno())
        os.replace(temp,p)
        return sha256(raw).hexdigest()
    def charge(self,amount):
        if type(amount) is not int or amount<0 or self.meta['reserved_bytes']+amount>2**31:
            raise ValueError('M8_STORE_RETENTION_ADMISSION')
        self.meta['reserved_bytes']+=amount;self._write(('store.json',),self.meta,mutable=True)
    def _project_record(self,pid):
        identifier(pid)
        if pid not in self.meta['projects']:raise ValueError('foreign project')
        p=self.read_json('projects',pid,'project.json')
        object_fields(p,('project_id','current_revision','revisions','jobs','preview_hashes'))
        if p['project_id']!=pid:raise ValueError('project binding')
        identifier(p['current_revision'],revision=True)
        if type(p['revisions']) is not list or not 1<=len(p['revisions'])<=32 or type(p['jobs']) is not list or len(p['jobs'])>4:raise ValueError('bounded project history')
        return p
    def load(self,pid,revision=None):
        p=self._project_record(pid);revision=p['current_revision'] if revision is None else identifier(revision,revision=True)
        if revision not in p['revisions']:raise ValueError('foreign revision')
        raw=self.path('projects',pid,'revisions',revision,'input.json').read_bytes();h=sha256(raw).hexdigest()
        cached=self._inputs.get((pid,revision))
        if cached is not None:
            if cached[0]!=h:raise ValueError('altered immutable revision bytes')
            return cached[1]
        project=loads_project(raw.decode('utf-8'),expected_identity=revision,expected_source_identity=self.source_identity,
            expected_reference_identity=self.reference_identity)
        self._inputs[(pid,revision)]=(h,project)
        return project
    def create(self,project):
        with self.lock:
            if len(self.meta['projects'])>=16:raise ValueError('project population limit')
            text=dumps_project(project)
            project=loads_project(text,expected_source_identity=self.source_identity,expected_reference_identity=self.reference_identity)
            pid=uuid.uuid4().hex;rev=project.identity;self.charge(len(text.encode())+4096)
            self._write(('projects',pid,'revisions',rev,'input.json'),parse_json(text))
            self._write(('projects',pid,'project.json'),dict(project_id=pid,current_revision=rev,revisions=[rev],jobs=[],preview_hashes={}))
            self.meta['projects'].append(pid);self._write(('store.json',),self.meta,mutable=True)
            return dict(project_id=pid,revision=rev,input=parse_json(text))
    def load_document(self,text):
        """Explicit input load reselects a known immutable revision and its history."""
        with self.lock:
            project=loads_project(text,expected_source_identity=self.source_identity,
                expected_reference_identity=self.reference_identity)
            for pid in self.meta['projects']:
                record=self._project_record(pid)
                if project.identity in record['revisions']:
                    self.load(pid,project.identity)  # Check existing bytes before reselection.
                    record['current_revision']=project.identity
                    self._write(('projects',pid,'project.json'),record,mutable=True)
                    return dict(project_id=pid,revision=project.identity,input=parse_json(dumps_project(project)),
                        history_preserved=True,new_actual_submission=False)
            return self.create(project)
    def edit(self,pid,expected_revision,**changes):
        with self.lock:
            record=self._project_record(pid)
            if record['current_revision']!=identifier(expected_revision,revision=True):raise ValueError('stale edit revision')
            project=edit_project(self.load(pid),**changes);rev=project.identity
            if rev not in record['revisions']:
                if len(record['revisions'])==32:raise ValueError('revision history cap')
                text=dumps_project(project);self.charge(len(text.encode())+4096)
                self._write(('projects',pid,'revisions',rev,'input.json'),parse_json(text));record['revisions'].append(rev)
            record['current_revision']=rev;self._write(('projects',pid,'project.json'),record,mutable=True)
            return dict(project_id=pid,revision=rev,input=parse_json(dumps_project(project)),derived_current=None)
    def edit_document(self,pid,expected_revision,text):
        """Strict authored input edit; preserve history and invalidate old preview."""
        with self.lock:
            record=self._project_record(pid)
            if record['current_revision']!=identifier(expected_revision,revision=True):raise ValueError('stale design edit revision')
            project=loads_project(text,expected_source_identity=self.source_identity,
                expected_reference_identity=self.reference_identity)
            prior=self.load(pid,expected_revision)
            if type(project)is not type(prior):raise ValueError('project family is immutable; import as a new project')
            rev=project.identity
            if rev not in record['revisions']:
                if len(record['revisions'])>=32:raise ValueError('revision history cap')
                encoded=dumps_project(project);self.charge(len(encoded.encode())+4096)
                self._write(('projects',pid,'revisions',rev,'input.json'),parse_json(encoded));record['revisions'].append(rev)
            record['current_revision']=rev;self._write(('projects',pid,'project.json'),record,mutable=True)
            return dict(project_id=pid,revision=rev,input=parse_json(dumps_project(project)),derived_current=None)
    def preview(self,pid,revision):
        with self.lock:
            project=self.load(pid,revision);record=self._project_record(pid)
            if record['current_revision']!=revision:raise ValueError('preview current revision required')
            ledger=ConstructorLedger(**self.meta['constructor'])
            # Spend before compilation. A failed compilation remains paid.
            before=asdict(ledger)
            from .spacecraft_project import constructor_compile_bound
            for _ in range(constructor_compile_bound(project)):ledger.reserve()
            self.meta['constructor']=asdict(ledger)
            self.charge(2**20)
            actual=ConstructorLedger(**before)
            preview=preview_project(project,actual)
            if asdict(actual)!=asdict(ledger):raise ValueError('constructor accounting disagreement')
            h=self._write(('projects',pid,'revisions',revision,'preview.json'),preview,mutable=True)
            record['preview_hashes'][revision]=h;self._write(('projects',pid,'project.json'),record,mutable=True)
            return parse_json(canonical_json(preview))
    def current_preview(self,pid,revision):
        project=self.load(pid,revision);p=self.path('projects',pid,'revisions',revision,'preview.json')
        if not p.exists():return None
        if file_sha(p)!=self._project_record(pid)['preview_hashes'].get(revision):raise ValueError('altered preview manifest')
        preview=self.read_json('projects',pid,'revisions',revision,'preview.json')
        if preview['project_identity']!=project.identity or preview['source_identity']!=self.source_identity:
            raise ValueError('stale preview binding')
        return preview
    def jobs(self,pid):
        p=self._project_record(pid)
        return [self.job(jid) for jid in p['jobs']]
    def job(self,jid):
        identifier(jid);d=self.read_json('jobs',jid,'job.json')
        if d.get('format')!=JOB or d.get('job_id')!=jid:raise ValueError('job identity/format')
        identifier(d['project_id']);identifier(d['revision'],revision=True)
        if jid not in self._project_record(d['project_id'])['jobs']:raise ValueError('job project ownership')
        if d['source_identity']!=self.source_identity:raise ValueError('job source mismatch')
        self.load(d['project_id'],d['revision'])
        return d
    def update_job(self,job):
        identifier(job['job_id']);self._write(('jobs',job['job_id'],'job.json'),job,mutable=True)
    def reconcile_intent(self,body):
        body=validate_intent(body)
        for job in self.jobs(body['project_id']):
            if job['idempotency_key']==body['idempotency_key']:
                if job.get('intent')!=body:raise ValueError('idempotency key reused for different intent')
                return job
        return None
    def admit_parent(self,project,prior,preview,*,method,snapshot_sha256=None):
        # Read-only, before compilation, reservations, job creation or dispatch.
        if prior['runtime']!=runtime_identity():raise ValueError('parent runtime/interpreter mismatch before work')
        if prior['source_identity']!=self.source_identity or prior['revision']!=project.identity or prior['root_identity']!=preview['root_identity']:
            raise ValueError('parent source/root/revision mismatch before work')
        if prior['status'] not in TERMINAL or prior.get('ownership_valid') is not True:raise ValueError('resume requires settled owned launch')
        old_request=self.read_json('jobs',prior['job_id'],'request.json')
        input_sha=file_sha(self.path('projects',prior['project_id'],'revisions',project.identity,'input.json'))
        if old_request['format']!='M8_ALLOWLISTED_PROJECT_WORKER_REQUEST_V2' or old_request['source_identity']!=self.source_identity or old_request['root_identity']!=preview['root_identity']:
            raise ValueError('parent source/method/root request mismatch before work')
        if old_request['runtime']!=runtime_identity() or old_request['project_input_sha256']!=input_sha:raise ValueError('parent input/runtime mismatch before work')
        if method==DIRECT:
            from .rolling_snapshot import admit_snapshot,METHOD
            candidates=[x for x in prior.get('snapshots',[]) if x['sha256']==snapshot_sha256]
            if len(candidates)!=1:raise ValueError('generated pinned snapshot required')
            cp=candidates[0];bindings=cp['bindings']
            expected=dict(root_identity=preview['root_identity'],revision=project.identity,source_identity=self.source_identity,
                runtime=runtime_identity(),project_input_sha256=input_sha,method=METHOD,clock=cp['clock'])
            if bindings!=expected or cp['file'] not in ('snapshot-136.json','snapshot-200.json'):raise ValueError('parent snapshot authority mismatch')
            raw=self.path('jobs',prior['job_id'],cp['file']).read_bytes()
            if len(raw)!=cp['bytes']:raise ValueError('snapshot length drift')
            from .rolling_snapshot_document import CONTROL_ALLOWANCE
            c=self.meta['snapshot_control']
            if c['admission_attempts']>=512 or c['reserved_units']+CONTROL_ALLOWANCE>2**34:raise ValueError('snapshot admission control quota')
            c['admission_attempts']+=1;c['reserved_units']+=CONTROL_ALLOWANCE
            self._write(('store.json',),self.meta,mutable=True)
            admit_snapshot(raw,expected_sha256=snapshot_sha256,expected_bindings=expected)
            return dict(kind=DIRECT,job_id=prior['job_id'],snapshot=cp,
                expected_complete_science=None if prior['result'] is None else prior['result']['scientific_sha256'])
        if method!=CAUSAL or prior['checkpoint'] is None:raise ValueError('same-version causal packet required')
        cp=prior['checkpoint'];packet=self.path('jobs',prior['job_id'],cp['file'])
        if cp['file']!='checkpoint.rolling.json' or file_sha(packet)!=cp['sha256'] or packet.stat().st_size!=cp['bytes']:raise ValueError('altered causal packet')
        data=self.read_json('jobs',prior['job_id'],cp['file'],cap=project.limits.maximum_packet_bytes)
        object_fields(data,('format','version','inputs','root_identity','completed_decisions','scientific','paid_work'))
        from .command_document import PACKET
        if data['format']!=PACKET or type(data['version']) is not int or data['version']!=1:raise ValueError('parent causal method/version before work')
        from .command_document import inputs_from_json,admit_command_reconstruction
        parent_root=inputs_from_json(canonical_json(data['inputs']))
        if digest(parent_root)!=preview['root_identity']:raise ValueError('parent immutable input/age/model mismatch before work')
        admit_command_reconstruction(parent_root,data['completed_decisions'],data['paid_work']['aggregate'])
        if data['root_identity']!=preview['root_identity'] or data['completed_decisions']!=cp['completed_decisions'] or data['scientific']['checkpoint']['simulation_time_seconds']!=cp['clock']:
            raise ValueError('parent causal clock/root/count mismatch before work')
        if type(cp['clock']) not in (int,float) or not 128<=cp['clock']<=728 or not 0<=cp['completed_decisions']<=64:raise ValueError('parent causal age/domain')
        return dict(kind=CAUSAL,job_id=prior['job_id'],checkpoint=cp,
            expected_complete_science=None if prior['result'] is None else prior['result']['scientific_sha256'],
            report_snapshot=next((s for s in prior.get('snapshots',[]) if s['clock']==cp['clock']),None))
    def prepare_job(self,pid,revision,key,*,resume_job=None,intent=None):
        with self.lock:
            from .spacecraft_project import require_short_project
            project=require_short_project(self.load(pid,revision))
            identifier(key)
            p=self._project_record(pid)
            if p['current_revision']!=revision:raise ValueError('run current revision required')
            if intent is None:
                old=None if resume_job is None else self.job(resume_job)
                intent=make_intent(pid,revision,key,parent=resume_job,
                    snapshot_sha=None if old is None or old['checkpoint'] is None else old['checkpoint']['sha256'],
                    method=INITIAL if old is None else CAUSAL)
            intent=validate_intent(intent)
            if (intent['project_id'],intent['revision'],intent['idempotency_key'],intent['parent_job_id'])!=(pid,revision,key,resume_job):raise ValueError('submission/intent binding')
            submission=intent_identity(intent)
            for jid in p['jobs']:
                j=self.job(jid)
                if j['idempotency_key']==key:
                    if j['submission_identity']!=submission:raise ValueError('idempotency key reused for different request')
                    return j,False
            if len(p['jobs'])>=project.limits.maximum_jobs:raise ValueError('M8_PROJECT_JOB_ADMISSION')
            if any(j['status'] in ('QUEUED','ADMITTED','RUNNING','STOP_REQUESTED','UNKNOWN') for j in self.jobs(pid)):
                raise ValueError('active or uncertain job must be reconciled first')
            preview=self.current_preview(pid,revision)
            if preview is None:raise ValueError('real constructor preview required before run')
            prior=None;resume=None
            if resume_job is not None:
                prior=self.job(resume_job)
                if prior['project_id']!=pid or prior['revision']!=revision:
                    raise ValueError('same immutable revision and valid causal packet required')
                if prior['project_id']!=pid or prior['revision']!=revision:raise ValueError('foreign parent')
                resume=self.admit_parent(project,prior,preview,method=intent['method'],snapshot_sha256=intent['snapshot_sha256'])
                if intent['method']==DIRECT and intent['window_end_seconds']<=resume['snapshot']['clock']:raise ValueError('direct window must follow snapshot clock')
            intent_path=self.path('intents',key,'intent.json')
            if intent_path.exists():
                if self.read_json('intents',key,'intent.json')!=intent:raise ValueError('durable intent drift')
            else:
                existing=self.path('intents')
                if existing.exists() and len(list(existing.iterdir()))>=64:raise ValueError('durable intent population')
                self._write(('intents',key,'intent.json'),intent)
            # Complete fresh root/causal reconstruction ceiling, never a C5 estimate.
            ceiling=ceiling_for(project.reference)
            paid=ConstructorLedger(**self.meta['constructor']);before=asdict(paid);paid.reserve()
            reservation=project.limits.maximum_science_bytes+project.limits.maximum_progress_bytes+2**20
            if prior is None:reservation+=project.limits.maximum_packet_bytes
            reservation+=2*128*2**20+32*2**20  # two explicit snapshot allowances and separate report/detail cap
            self.charge(reservation)
            self.meta['constructor']=asdict(paid);self._write(('store.json',),self.meta,mutable=True)
            jid=sha256(submission.encode()).hexdigest()[:32]
            job=dict(format=JOB,job_id=jid,project_id=pid,revision=revision,source_identity=self.source_identity,
                reference_identity=self.reference_identity,root_identity=preview['root_identity'],
                comparison_identity=project.comparison_identity,idempotency_key=key,submission_identity=submission,
                status='QUEUED',reason=None,progress=None,checkpoint=None,result=None,ownership_valid=None,
                resume_from=resume_job,reserved_retention_bytes=reservation,root_ceiling=ceiling,
                constructor_before=before,constructor_reserved=asdict(paid),runtime=runtime_identity(),launch=None,
                intent=intent,snapshots=[],report=None,direct_restore=None)
            request=dict(format='M8_ALLOWLISTED_PROJECT_WORKER_REQUEST_V2',job_id=jid,project_id=pid,revision=revision,
                source_identity=self.source_identity,root_identity=preview['root_identity'],
                project_input_sha256=file_sha(self.path('projects',pid,'revisions',revision,'input.json')),
                preview_sha256=file_sha(self.path('projects',pid,'revisions',revision,'preview.json')),
                constructor_before=before,constructor_reserved=asdict(paid),runtime=runtime_identity(),
                resume=resume,intent=intent)
            self._write(('jobs',jid,'request.json'),request)
            # Worker reads only immutable job-bound inputs, never live mutable UI metadata.
            self._write(('jobs',jid,'project-input.json'),parse_json(dumps_project(project)))
            self._write(('jobs',jid,'preview.json'),preview)
            p['jobs'].append(jid);self._write(('projects',pid,'project.json'),p,mutable=True);self.update_job(job)
            return job,True
    def seal_result(self,job,record):
        project=self.load(job['project_id'],job['revision'])
        object_fields(record,('format','job_id','revision','source_identity','root_identity','comparison_identity','scientific_sha256',
            'scientific_bytes','metrics','checkpoint','runtime','same_environment_resume_equal','qualification','work_sha256',
            'snapshots','report','window_report','continuation_method','diagnostic_scope','requirements_evaluation'))
        if job['result'] is not None and canonical_json(job['result'])!=canonical_json(record):raise ValueError('altered terminal metadata')
        if record.get('format')!=RESULT or any(record.get(n)!=job[n] for n in ('job_id','revision','source_identity','root_identity')):
            raise ValueError('foreign terminal result')
        science=self.path('jobs',job['job_id'],'science.json')
        if science.stat().st_size>project.limits.maximum_science_bytes or file_sha(science)!=record['scientific_sha256']:
            raise ValueError('full scientific result binding')
        direct=job['intent']['method']==DIRECT
        expected_clock=job['intent']['window_end_seconds'] if direct else 728
        if record['metrics']['clock']!=expected_clock or record['metrics']['status']!=('COMPLETE' if expected_clock==728 else 'ACTIVE'):raise ValueError('result is neither complete mission nor exact committed direct window')
        if record['runtime']!=job['runtime'] or record['comparison_identity']!=job['comparison_identity'] or record['continuation_method']!=job['intent']['method'] or record['diagnostic_scope']!=job['intent']['mode']:raise ValueError('result runtime/intent/comparison binding')
        if record['scientific_bytes']!=science.stat().st_size:raise ValueError('science length binding')
        for name in ('report','window_report'):
            meta=record[name]
            if meta is None:continue
            if meta['file']!=name.replace('_','-')+'.json':raise ValueError('fixed report file')
            path=self.path('jobs',job['job_id'],meta['file'])
            if path.stat().st_size!=meta['bytes'] or path.stat().st_size>2**20 or file_sha(path)!=meta['sha256']:raise ValueError('report result manifest binding')
            from .mission_report_document import loads_report
            if meta['totals'] is not None and loads_report(path.read_bytes())['totals']!=meta['totals']:raise ValueError('compact report totals binding')
        job['result']=record;self.update_job(job)
    def snapshot(self):
        from .spacecraft_project_v3 import SpacecraftProjectV3
        # Only bounded stored metadata. No model calls/whole-history science reads.
        with self.lock:
            result=[]
            for pid in self.meta['projects']:
                rec=self._project_record(pid);project=self.load(pid);rev=rec['current_revision']
                jobs=self.jobs(pid)
                result.append(dict(project_id=pid,revision=rev,title=project.title,placement=project.placement,
                    payload_area_m2=project.payload_area_m2,requirements=asdict(project.requirements),
                    project_format=('M8_IMMUTABLE_SPACECRAFT_PROJECT_INPUT_V1'if type(project)is SpacecraftProject else 'KAZEOSAT_SPACECRAFT_PROJECT_V3'if type(project)is SpacecraftProjectV3 else 'B66_IMMUTABLE_SPACECRAFT_DESIGN_PROJECT_V2'),general_design=type(project)is not SpacecraftProject,
                    preview=self.current_preview(pid,rev),jobs=[dict(j, is_current_revision=j['revision']==rev) for j in jobs]))
            return dict(format=STORE,source_identity=self.source_identity,projects=result,historical=self._historical,
                constructor_work=self.meta['constructor'],retention_reserved_bytes=self.meta['reserved_bytes'],
                snapshot_control=self.meta['snapshot_control'],
                workflow='ACTUAL_RESULTS_FORECASTS_AND_HISTORICAL_EVIDENCE_ARE_DISTINCT')
    def register_historical(self,hid,*,expected_science_sha256,expected_root_document_sha256,
        actual_source_identity,archive_sha256):
        """Trusted local import from exact externally bound files INSIDE this store.

        No HTTP route exposes this operator. It cannot seed a current job/state.
        Full science is checked once at admission; UI polling reads this bounded
        labelled metadata cache, never reruns or scans the scientific history.
        """
        from .design_repair import hash_identity
        from .command_document import inputs_from_json
        from .design_repair_study import metrics_from_science
        identifier(hid,revision=True)
        for h in (expected_science_sha256,expected_root_document_sha256,actual_source_identity,archive_sha256):hash_identity(h)
        science=self.path('historical',hid,'science.json');rootfile=self.path('historical',hid,'root.json')
        if science.stat().st_size>128*2**20 or file_sha(science)!=expected_science_sha256 or file_sha(rootfile)!=expected_root_document_sha256:
            raise ValueError('historical external full-output binding')
        root=inputs_from_json(rootfile.read_text(encoding='utf-8'))
        metrics=metrics_from_science(science.read_bytes(),root,expected_scientific_sha256=expected_science_sha256)
        record=dict(id=hid,scope='HISTORICAL_ACTUAL_B49_METRIC_REDERIVATION_NOT_CURRENT_RUN',
            actual_source_identity=actual_source_identity,archive_sha256=archive_sha256,
            scientific_sha256=expected_science_sha256,root_document_sha256=expected_root_document_sha256,
            reporting_source_identity=self.source_identity,root_identity=digest(root),metrics=metrics,
            grant='NONE_FOR_CURRENT_EXECUTION_OR_CONTINUATION')
        self.charge(science.stat().st_size+rootfile.stat().st_size+2**20)
        self._write(('historical',hid,'report.json'),record)
        self._historical.append(record)
        return record
    def export(self,jid):
        with self.lock:
            job=self.job(jid);project=self.load(job['project_id'],job['revision'])
            if job['status']!='COMPLETED' or job['result'] is None:raise ValueError('export completed actual result only')
            record=self.read_json('jobs',jid,'terminal.json')
            self.seal_result(job,record)
            if self.meta['exports']>=project.limits.maximum_exports:raise ValueError('export population cap')
            self.charge(project.limits.maximum_science_bytes+project.limits.maximum_packet_bytes+2*128*2**20+48*2**20)
            eid=uuid.uuid4().hex;folder=self.path('exports',eid);folder.mkdir(parents=True)
            mapping={'project.json':self.path('projects',job['project_id'],'revisions',job['revision'],'input.json'),
                'preview.json':self.path('projects',job['project_id'],'revisions',job['revision'],'preview.json'),
                'science.json':self.path('jobs',jid,'science.json'),'result.json':self.path('jobs',jid,'terminal.json'),
                'root.json':self.path('jobs',jid,'root.json'),'work.json':self.path('jobs',jid,'work.json'),
                'progress.jsonl':self.path('jobs',jid,'progress.jsonl')}
            if job['checkpoint'] is not None:mapping['causal-packet.json']=self.path('jobs',jid,job['checkpoint']['file'])
            for name in ('report.json','window-report.json','report-state.json','snapshots.json','snapshot-work.json','direct-restore.json','details.jsonl'):
                path=self.path('jobs',jid,name)
                if path.exists():mapping[name]=path
            for snap in job.get('snapshots',[]):mapping[snap['file']]=self.path('jobs',jid,snap['file'])
            request=self.read_json('jobs',jid,'request.json')
            if request['resume'] is not None and request['resume']['kind']==DIRECT:
                cp=request['resume']['snapshot'];path=self.path('jobs',request['resume']['job_id'],cp['file'])
                if file_sha(path)!=cp['sha256']:raise ValueError('parent snapshot export binding')
                mapping['parent-snapshot.json']=path
                self._write(('exports',eid,'parent-snapshot-manifest.json'),cp)
            manifest={}
            if (folder/'parent-snapshot-manifest.json').exists():manifest['parent-snapshot-manifest.json']=file_sha(folder/'parent-snapshot-manifest.json')
            for name,p in mapping.items():
                raw=p.read_bytes();(folder/name).write_bytes(raw);manifest[name]=sha256(raw).hexdigest()
            self._write(('exports',eid,'job.json'),job);manifest['job.json']=file_sha(folder/'job.json')
            m=record['metrics'];csvfile=io.StringIO(newline='');writer=csv.writer(csvfile)
            writer.writerow(['metric','value','unit','scope'])
            for n,u in (('credited_products','count'),('priority_weighted_delivery_score','1'),('minimum_energy_wh','Wh'),('final_energy_wh','Wh'),('unmet_load_wh','Wh'),('actual_slew_seconds','s'),('actuator_energy_wh','Wh'),('wire_loss_wh','Wh')):
                writer.writerow([n,m[n],u,'ACTUAL_RETURNED'])
            (folder/'metrics.csv').write_text(csvfile.getvalue(),encoding='utf-8');manifest['metrics.csv']=file_sha(folder/'metrics.csv')
            (folder/'SUMMARY.md').write_text(f"# Результат проекта\n\nФактических кредитов: {m['credited_products']}; score {m['priority_weighted_delivery_score']}. Энергия {m['minimum_energy_wh']} → {m['final_energy_wh']} Wh; выполненный поворот {m['actual_slew_seconds']} s.\n\nASSUMED synthetic600s model; не flight qualification. Project revision {job['revision']}. Исторические данные и прогнозы не дают actual receipt.\n",encoding='utf-8')
            manifest['SUMMARY.md']=file_sha(folder/'SUMMARY.md')
            (folder/'verify_saved_only.py').write_text(EXPORT_VERIFIER,encoding='utf-8');manifest['verify_saved_only.py']=file_sha(folder/'verify_saved_only.py')
            self._write(('exports',eid,'MANIFEST-SHA256.json'),manifest)
            archive=self.path('exports',eid+'.zip')
            with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
                for p in sorted(folder.iterdir()):z.write(p,p.name)
            self.meta['exports']+=1;self._write(('store.json',),self.meta,mutable=True)
            return dict(export_id=eid,sha256=file_sha(archive),bytes=archive.stat().st_size,url='/api/export/'+eid)

EXPORT_VERIFIER='''"""Saved project evidence only; no owner imports/calculation."""
import hashlib,json,pathlib,sys
r=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else pathlib.Path(__file__).parent
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
m=json.loads((r/'MANIFEST-SHA256.json').read_bytes())
assert set(p.name for p in r.iterdir() if p.is_file())==set(m)|{'MANIFEST-SHA256.json'}
for n,v in m.items():
 p=pathlib.PurePosixPath(n);assert len(p.parts)==1 and p.name not in ('.','..');assert h(r/n)==v
project=json.loads((r/'project.json').read_bytes());result=json.loads((r/'result.json').read_bytes());job=json.loads((r/'job.json').read_bytes())
assert (project['format'],project['version']) in (('M8_IMMUTABLE_SPACECRAFT_PROJECT_INPUT_V1',1),('B66_IMMUTABLE_SPACECRAFT_DESIGN_PROJECT_V2',2))
body={n:project[n] for n in ('format','version','inputs')}
assert hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()==project['digest']
assert result['source_identity']==project['inputs']['source_identity']==job['source_identity']
assert result['root_identity']==job['root_identity'] and result['revision']==job['revision']
assert result['scientific_sha256']==h(r/'science.json') and job['status']=='COMPLETED'
science=json.loads((r/'science.json').read_bytes());assert science['root_identity']==result['root_identity']
assert science['status']=='COMPLETE' or (job['intent']['method']=='B51_DIRECT' and science['status']=='ACTIVE' and result['metrics']['clock']==job['intent']['window_end_seconds'])
assert result['metrics']['reporting_method']=='M7_EXECUTED_POINT_BOUNDARY_METRICS_V2'
print('PASS: exact saved project/full science/manifest bindings; no physical continuation performed')
'''
