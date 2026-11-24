"""Project dependencies in the existing FULL/WAL pool; execution stays in State/Scheduler."""
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import threading
import os
import shutil
import sqlite3
import uuid

from .data import (canonical,digest,fields,file_digest,identity,inside,integer,no_links,
                   parse,read,read_bytes,reference,sha,slug,write_new)
from .errors import Refusal
from .projects import EXECUTION,SOURCE,load_verified
from .project_receipts import ReceiptAuthority
from .resources import admit_cost,admit_resources,volume_identity
from .state import DDL,State,utc

QUEUE_DDL='''
CREATE TABLE IF NOT EXISTS project_queues(
 key TEXT PRIMARY KEY, directory TEXT UNIQUE NOT NULL, config BLOB NOT NULL,
 generation INTEGER NOT NULL DEFAULT 0, paused INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS project_catalogues(
 queue TEXT NOT NULL, identity TEXT NOT NULL, path TEXT NOT NULL, bytes INTEGER NOT NULL,
 PRIMARY KEY(queue,identity));
CREATE TABLE IF NOT EXISTS project_cases(
 queue TEXT NOT NULL, identity TEXT NOT NULL, causal TEXT NOT NULL,
 catalogue TEXT, project TEXT NOT NULL, request BLOB NOT NULL,
 phase TEXT NOT NULL, classification TEXT NOT NULL, study_directory TEXT,
 design TEXT, binding BLOB, blocker TEXT, PRIMARY KEY(queue,identity),UNIQUE(queue,causal));
CREATE TABLE IF NOT EXISTS project_result_refs(
 queue TEXT NOT NULL, case_identity TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
 PRIMARY KEY(queue,case_identity,path));
CREATE TABLE IF NOT EXISTS project_historical_data(
 queue TEXT NOT NULL, sha256 TEXT NOT NULL, path TEXT NOT NULL, receipt_sha256 TEXT NOT NULL,
 PRIMARY KEY(queue,sha256));
CREATE TABLE IF NOT EXISTS project_imported_state(
 queue TEXT NOT NULL, case_identity TEXT NOT NULL, payload BLOB NOT NULL,
 PRIMARY KEY(queue,case_identity));
'''
TERMINAL={'TARGET','USER','RESOURCE_TIME','RESOURCE_OUTPUT','PHYSICAL','MODEL','UNSUPPORTED','PROCESS_FAILURE'}
UNKNOWN={'SUBMIT_INTENT','ACTIVE','SUBMISSION_UNKNOWN','PLAN_INTENT','PLAN_UNKNOWN'}


def case_request(v):
    if v.get('schema')in ('KAZE_YEAR_PROJECT_CASE_REQUEST_V1','KAZE_YEAR_FINITE_CHAIN_CASE_REQUEST_V2'):
        from .year_study import request
        return request(v)
    fields(v,('schema','horizon_seconds','bucket_seconds','deadline','concurrency','resources',
        'cost','objective','execution_mode','policy_sha256'),'explicit queued case request')
    if v['schema']!='KAZE_PROJECT_CASE_REQUEST_V1':raise Refusal('PROJECT_CASE_REQUEST_SCHEMA')
    integer(v['horizon_seconds'],'horizon',1,86400);integer(v['bucket_seconds'],'bucket',1,31557600)
    integer(v['concurrency'],'concurrency',1,128);sha(v['policy_sha256'])
    if v['execution_mode']!='pilot':raise Refusal('LONG_REQUIRES_CORRECTED_PER_DOMAIN_TARGET_ACCEPTANCE')
    try:
        d=datetime.fromisoformat(v['deadline'])
        if d.tzinfo is None:raise ValueError('offset')
    except (TypeError,ValueError) as e:raise Refusal('DEADLINE_WITH_OFFSET',str(e)) from e
    admit_resources(v['resources'],v['concurrency']);admit_cost(v['cost'])
    if v['objective'] is not None:
        fields(v['objective'],('metric','direction'),'objective')
        if v['objective']['metric'] not in ('credits','useful_bits','priority_score') or v['objective']['direction'] not in ('max','min'):
            raise Refusal('DECLARED_OBJECTIVE')
    return v


def clone_catalogue(source,destination, *, authority):
    value=load_verified(source,authority=authority);destination=no_links(destination).absolute()
    if destination.exists():raise Refusal('NEW_CATALOGUE_SNAPSHOT_REQUIRED')
    for name,pin in value['raw_files'].items():
        raw=read_bytes(inside(Path(source).parent/'raw',name),8*2**20)
        write_new(inside(destination/'raw',name),raw)
    write_new(destination/'catalogue.json',canonical(value))
    if load_verified(destination/'catalogue.json',authority=authority)!=value:raise Refusal('COPIED_CATALOGUE_DRIFT')
    return value


class ProjectQueue:
    def __init__(self,directory):
        self.directory=no_links(directory).resolve()
        marker=fields(read(self.directory/'queue.json'),('schema','key','pool','config_sha256'),'queue marker')
        if marker['schema']!='KAZE_PROJECT_QUEUE_V1':raise Refusal('PROJECT_QUEUE_SCHEMA')
        self.key=marker['key'];self.pool=no_links(marker['pool']).resolve()
        if not self.pool.is_file() or volume_identity(self.directory)!=volume_identity(self.pool.parent):
            raise Refusal('SHARED_POOL_SAME_VOLUME_REQUIRED')
        with self.connection() as c:
            row=c.execute('SELECT * FROM project_queues WHERE key=?',(self.key,)).fetchone()
            if row is None or row['directory']!=str(self.directory) or digest(bytes(row['config']))!=marker['config_sha256']:
                raise Refusal('PROJECT_QUEUE_DATABASE_BINDING')
            self.config=parse(bytes(row['config']))
        self.authority=ReceiptAuthority(self.pool)

    @classmethod
    def create(cls,directory,pool,config):
        fields(config,('queue_id','maximum_cases','maximum_catalogues','maximum_metadata_bytes'),'queue limits')
        slug(config['queue_id']);integer(config['maximum_cases'],'queue cases',1,128)
        integer(config['maximum_catalogues'],'queue catalogues',1,16)
        integer(config['maximum_metadata_bytes'],'queue metadata bytes',8*2**20,128*2**20)
        directory=no_links(directory).absolute();pool=no_links(pool).absolute()
        if directory.exists() or pool.is_relative_to(directory):raise Refusal('NEW_QUEUE_SHARED_POOL_REQUIRED')
        pool.parent.mkdir(parents=True,exist_ok=True);directory.mkdir(parents=True)
        if volume_identity(directory)!=volume_identity(pool.parent):raise Refusal('SHARED_POOL_SAME_VOLUME_REQUIRED')
        key=uuid.uuid4().hex
        c=sqlite3.connect(pool,timeout=5,isolation_level=None)
        try:
            c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL');c.executescript(DDL+QUEUE_DDL)
            ReceiptAuthority.initialize(c)
            c.execute('BEGIN IMMEDIATE')
            promises=c.execute('SELECT coalesce(sum(bytes),0) FROM disk_reservations').fetchone()[0]+config['maximum_metadata_bytes']
            limits=c.execute("SELECT value FROM meta WHERE key='pool_config'").fetchone()
            if promises>shutil.disk_usage(directory).free or limits and promises>parse(bytes(limits[0]))['disk_bytes']:
                raise Refusal('RESOURCE_QUEUE_DISK')
            c.execute('INSERT INTO project_queues(key,directory,config) VALUES(?,?,?)',(key,str(directory.resolve()),canonical(config)))
            c.execute("INSERT INTO disk_reservations VALUES(?,'__queue__',?)",(key,config['maximum_metadata_bytes']))
            write_new(directory/'queue.json',canonical(dict(schema='KAZE_PROJECT_QUEUE_V1',key=key,pool=str(pool),config_sha256=identity(config))))
            c.commit()
        except BaseException:c.rollback();raise
        finally:c.close()
        return cls(directory)

    @contextmanager
    def connection(self,writable=False):
        no_links(self.pool)
        c=sqlite3.connect(self.pool if writable else self.pool.as_uri()+'?mode=ro',uri=not writable,timeout=5,isolation_level=None)
        c.row_factory=sqlite3.Row
        try:
            if writable:
                c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA wal_autocheckpoint=64');c.execute('PRAGMA journal_size_limit=262144')
                budget=c.execute("SELECT coalesce(sum(bytes),0) FROM disk_reservations WHERE design IN ('__queue__','__wrapper__')").fetchone()[0]
                from .ninety_metadata_repair import validate_extension_for_connection
                budget+=validate_extension_for_connection(c,self.pool)
                c.execute('PRAGMA max_page_count='+str(max(64,budget//3//c.execute('PRAGMA page_size').fetchone()[0])))
            yield c
        finally:c.close()

    @contextmanager
    def transaction(self):
        with self.connection(True) as c:
            c.execute('BEGIN IMMEDIATE')
            try:yield c;c.commit()
            except BaseException:c.rollback();raise

    def _event(self,c,kind,payload):
        count,used=c.execute('SELECT count(*),coalesce(sum(length(payload)),0) FROM events WHERE study=?',(self.key,)).fetchone()
        raw=canonical(payload)
        if count>=8192 or used+len(raw)>self.config['maximum_metadata_bytes']//6 or len(raw)>128*2**10:
            raise Refusal('QUEUE_JOURNAL_LIMIT')
        c.execute('INSERT INTO events(study,kind,at,payload) VALUES(?,?,?,?)',(self.key,kind,utc(),raw))

    def _capacity(self,extra=0):
        total=0;count=0
        for directory,dirs,files in os.walk(self.directory,followlinks=False):
            base=Path(directory)
            # Existing State owns/reserves stores, backups and publications.
            if base==self.directory:dirs[:]=[d for d in dirs if d!='executions']
            for name in dirs:no_links(base/name)
            for name in files:
                p=no_links(base/name);total+=p.stat().st_size;count+=1
                if total+extra>self.config['maximum_metadata_bytes']*2//3 or count>8192:raise Refusal('QUEUE_METADATA_LIMIT')

    def _result_coverage(self,qid,state):
        """Read previously verified, independently DB-pinned cumulative tips.

        Arbitrary receipts still use authoritative reinspection on import/export;
        status itself cannot invoke a capability or inspector subprocess.
        """
        from .report import reduce_result
        with self.connection() as c:
            refs=list(c.execute('SELECT path,sha256 FROM project_result_refs WHERE queue=? AND case_identity=?',(self.key,qid)))
        latest=None
        for ref in refs:
            path=Path(ref['path']);raw=read_bytes(path)
            if digest(raw)!=ref['sha256']:raise Refusal('QUEUED_RESULT_RECEIPT_DRIFT')
            value=parse(raw)
            design=next(d for d in state.study.catalogue.designs if d.design_id==value['design_id'])
            if value['study_manifest_sha256']!=state.study.manifest_sha256 or value['case_identity']!=design.pins:
                raise Refusal('QUEUED_RESULT_CASE_LINEAGE')
            if file_digest(inside(path.parent,value['result']['path']))!=value['result']['sha256']:
                raise Refusal('QUEUED_RESULT_DATA_DRIFT')
            row=reduce_result(value)
            if latest is None or row['actual_end_seconds']>latest['actual_end_seconds']:latest=row
        return latest

    def add_catalogue(self,path):
        value=load_verified(path,authority=self.authority);cid=value['catalogue_identity']
        extra=sum(x['bytes'] for x in value['raw_files'].values())+len(canonical(value))
        with self.transaction() as c:
            old=c.execute('SELECT path FROM project_catalogues WHERE queue=? AND identity=?',(self.key,cid)).fetchone()
            if old:return cid
            if c.execute('SELECT count(*) FROM project_catalogues WHERE queue=?',(self.key,)).fetchone()[0]>=self.config['maximum_catalogues']:
                raise Refusal('QUEUE_CATALOGUE_LIMIT')
            self._capacity(extra)
            destination=self.directory/'catalogues'/cid
            clone_catalogue(path,destination,authority=self.authority)
            c.execute('INSERT INTO project_catalogues VALUES(?,?,?,?)',(self.key,cid,str(destination/'catalogue.json'),extra))
            self._event(c,'PROJECT_CATALOGUE_IMPORTED',dict(catalogue_identity=cid,producer=value['producer'],dispatch=False))
        return cid

    def catalogue(self,cid):
        with self.connection() as c:
            row=c.execute('SELECT path FROM project_catalogues WHERE queue=? AND identity=?',(self.key,cid)).fetchone()
        if row is None:raise Refusal('QUEUE_CATALOGUE_NOT_FOUND')
        path=Path(row[0]);v=load_verified(path,authority=self.authority)
        if v['catalogue_identity']!=cid:raise Refusal('QUEUE_CATALOGUE_PIN')
        return path,v

    def enqueue(self,cid,project_id,request):
        case_request(request);path,cat=self.catalogue(cid)
        item=next((x for x in cat['cases'] if x['project_id']==project_id),None)
        if item is None:raise Refusal('UNKNOWN_VERIFIED_PROJECT')
        if request['horizon_seconds']>item['initial']['root_duration_seconds']:raise Refusal('REQUEST_EXCEEDS_INITIAL_ROOT_DOMAIN')
        from .project_identity import causal as causal_identity
        causal=causal_identity(item['pins'])
        qid=identity(dict(project_case_identity=item['case_identity'],request=request))
        with self.transaction() as c:
            prior=c.execute('SELECT identity,request,project FROM project_cases WHERE queue=? AND causal=?',(self.key,causal)).fetchone()
            if prior:
                if bytes(prior['request'])!=canonical(request):raise Refusal('EXISTING_CAUSAL_HISTORY_REQUEST_IMMUTABLE_USE_EXPLICIT_RESUME')
                self._event(c,'CAUSAL_ALIAS_IGNORED',dict(project=project_id,existing=prior['identity']))
                return dict(case_identity=prior['identity'],alias=True,dispatch=False)
            if c.execute('SELECT count(*) FROM project_cases WHERE queue=?',(self.key,)).fetchone()[0]>=self.config['maximum_cases']:
                raise Refusal('QUEUE_CASE_LIMIT')
            c.execute('INSERT INTO project_cases(queue,identity,causal,catalogue,project,request,phase,classification,blocker) VALUES(?,?,?,?,?,?,?,?,?)',
                (self.key,qid,causal,cid,project_id,canonical(request),'WAITING_CORE_BINDING','VERIFIED_PRODUCER_DATA','FINAL_CORE_BINDING_REQUIRED'))
            self._event(c,'PROJECT_ENQUEUED',dict(case_identity=qid,project=project_id,request_sha256=identity(request),dispatch=False))
        return dict(case_identity=qid,alias=False,dispatch=False)

    def row(self,qid):
        with self.connection() as c:row=c.execute('SELECT * FROM project_cases WHERE queue=? AND identity=?',(self.key,qid)).fetchone()
        if row is None:raise Refusal('QUEUE_CASE_NOT_FOUND')
        return dict(row)

    def explicit_bind(self,qid,path):
        try:return self._explicit_bind(qid,path)
        except (Refusal,OSError,ValueError,KeyError,TypeError) as e:
            with self.transaction() as c:
                c.execute('UPDATE project_cases SET blocker=? WHERE queue=? AND identity=?',(str(e)[:4000],self.key,qid))
                self._event(c,'PROJECT_BIND_REFUSED_PRESERVED',dict(case_identity=qid,error=str(e)[:4000],dispatch=False))
            raise

    def _explicit_bind(self,qid,path):
        """Explicit immutable final binding, metadata only; no capability/native load."""
        from .contract import acceptance_references,load_study
        from .engine_adapter import EngineAdapter
        request_path=no_links(path).absolute();binding_request=read(request_path)
        row=self.row(qid)
        if row['catalogue']:
            _,current=self.catalogue(row['catalogue'])
            if current.get('schema')=='KAZE_VERIFIED_NAMED_PROJECT_CATALOGUE_V1':
                from .named_execution import bind
                return bind(self,qid,path)
        fields(binding_request,('schema','binding','policy','engine','interpreter'),'CORE bind request')
        if binding_request['schema']!='KAZE_PROJECT_CORE_BIND_REQUEST_V1':raise Refusal('PROJECT_CORE_BIND_REQUEST_SCHEMA')
        if row['classification']!='VERIFIED_PRODUCER_DATA' or row['phase'] in UNKNOWN|TERMINAL|{'CANCELLED','REMOVED'} or row['study_directory']:
            raise Refusal('QUEUE_BIND_NEW_PENDING_CASE_ONLY')
        req=parse(bytes(row['request']));catpath,cat=self.catalogue(row['catalogue'])
        b=binding_request['binding'];bid=identity(binding_request)
        if b.get('source_sha256')!=cat['source']['source_identity']:
            raise Refusal('WAITING_CORE_BINDING_SOURCE_DOMAIN',canonical(dict(
                catalogue_source=cat['source']['source_identity'],requested_source=b.get('source_sha256'),
                compiler=cat['compiler']['sha256'],fresh_roots_required=True,source_retag_allowed=False)).decode())
        if b.get('source_sha256')==SOURCE:
            raise Refusal('SOURCE824_REVIEW_REFERENCE_CANNOT_BE_RETAGGED_FINAL')
        destination=self.directory/'admissions'/qid/bid
        if destination.exists():raise Refusal('BIND_ATTEMPT_PRESERVED_NO_AUTOMATIC_RETRY')
        refs=(b['source_manifest'],b['build'],b['repair_evidence'],b.get('core_handoff'),binding_request['policy'],*acceptance_references(b['acceptance']))
        declared_bytes=0
        for ref in refs:
            if ref is not None:
                fields(ref,('path','sha256','bytes'),'binding snapshot reference')
                declared_bytes+=integer(ref['bytes'],'binding snapshot bytes',1,16*2**20)
        # Failed attempts remain as evidence, so every new attempt must reserve
        # its complete raw closure before the first materialized byte.
        self._capacity(sum(p['bytes'] for p in cat['raw_files'].values())+len(canonical(cat))+declared_bytes+65536)
        clone_catalogue(catpath,destination/'projects',authority=self.authority)
        for ref in refs:
            if ref is None:continue
            _,raw=reference(request_path.parent,ref)
            if ref['path'] in ('study-input.json','queue-execution.json') or ref['path'].startswith('projects/'):
                raise Refusal('BIND_SNAPSHOT_PATH_COLLISION')
            target=inside(destination,ref['path'])
            if target.exists():
                if read_bytes(target)!=raw:raise Refusal('BIND_SNAPSHOT_PATH_COLLISION')
            else:write_new(target,raw)
        if binding_request['policy']['sha256']!=req['policy_sha256']:raise Refusal('QUEUED_POLICY_IDENTITY_IMMUTABLE')
        _,buildraw=reference(destination,b['build'])
        nraw=read_bytes(destination/'projects/catalogue.json')
        wrapper=dict(schema=EXECUTION,label='PRODUCTION',verified_catalogue=dict(path='projects/catalogue.json',bytes=len(nraw),sha256=digest(nraw)),
            projects=[row['project']],bucket_seconds=req['bucket_seconds'],build_sha256=identity(parse(buildraw)))
        raw=canonical(wrapper);write_new(destination/'queue-execution.json',raw)
        spec=dict(schema='KAZE_STUDY_V1',study_id='q'+qid[:20]+'-'+bid[:16],mode='PRODUCTION',binding=b,
            catalogue=dict(path='queue-execution.json',bytes=len(raw),sha256=digest(raw)),policy=binding_request['policy'],
            **{k:req[k] for k in ('horizon_seconds','deadline','concurrency','resources','cost','objective','execution_mode')},failure_policy='CONTINUE_INDEPENDENT')
        write_new(destination/'study-input.json',canonical(spec))
        error=None;state=None
        try:
            study=load_study(destination/'study-input.json',authority=self.authority)
            adapter=EngineAdapter(study,binding_request['engine'],binding_request['interpreter'])
            adapter.check_source()
            api=parse(reference(destination,b['repair_evidence'])[1])
            if b['source_sha256']==SOURCE:
                raise Refusal('SOURCE824_REVIEW_REFERENCE_CANNOT_BE_RETAGGED_FINAL')
            if api.get('per_domain_target_acceptance')!='CORRECTED_GENUINE_EVIDENCE_REQUIRED':
                raise Refusal('FINAL_CORRECTED_CORE_HANDOFF_REQUIRED')
            state=State.create(study,self.directory/'executions'/qid,self.pool,engine=binding_request['engine'],interpreter=binding_request['interpreter'])
        except (Refusal,OSError,ValueError,KeyError,TypeError) as e:error=str(e)[:4000]
        with self.transaction() as c:
            current=c.execute('SELECT phase,study_directory FROM project_cases WHERE queue=? AND identity=?',(self.key,qid)).fetchone()
            if current['phase']!='WAITING_CORE_BINDING' or current['study_directory']:
                if state:c.execute("UPDATE studies SET paused=1,generation=generation+1 WHERE key=?",(state.key,))
                raise Refusal('QUEUE_BIND_CONCURRENT_STATE_CHANGE')
            if state and c.execute('SELECT paused FROM project_queues WHERE key=?',(self.key,)).fetchone()[0]:
                c.execute("UPDATE studies SET paused=1,generation=generation+1,halt_reason='QUEUE_STOP' WHERE key=?",(state.key,))
            c.execute('UPDATE project_cases SET binding=?,study_directory=?,design=?,phase=?,blocker=? WHERE queue=? AND identity=?',
                (canonical(dict(request=binding_request,request_sha256=bid,admission=str(destination))),None if state is None else str(state.directory),row['project'],
                 'WAITING_CORE_BINDING' if error else 'WAITING_CAPABILITY',error or 'EXPLICIT_CURRENT_CAPABILITY_CHECK_REQUIRED',self.key,qid))
            self._event(c,'PROJECT_CORE_BINDING_CHECKED',dict(case_identity=qid,binding_sha256=bid,error=error,dispatch=False))
        return self.case_status(qid)

    def attach_protocol_fixture(self,state,*,explicit_fixture=False):
        """Control tests only. No real project row may adopt synthetic evidence."""
        if not explicit_fixture or state.study.spec['mode']!='PROTOCOL_FIXTURE_NO_SCIENCE' or state.pool!=self.pool:
            raise Refusal('SEPARATE_PROTOCOL_FIXTURE_STATE_REQUIRED')
        result=[]
        with self.transaction() as c:
            for d in state.study.catalogue.designs:
                qid=identity(dict(protocol_fixture=state.study.manifest_sha256,design=d.design_id))
                c.execute('INSERT INTO project_cases(queue,identity,causal,project,request,phase,classification,study_directory,design) VALUES(?,?,?,?,?,?,?,?,?)',
                    (self.key,qid,qid,d.design_id,canonical(dict(protocol_fixture=True)),'WAITING_CAPABILITY','PROTOCOL_FIXTURE_NO_SCIENCE',str(state.directory),d.design_id))
                result.append(qid)
            self._event(c,'SEPARATE_PROTOCOL_FIXTURE_ATTACHED',dict(cases=result,science=False))
        return result

    def _state(self,row):
        if row['study_directory'] is None:raise Refusal('FINAL_CORE_BINDING_REQUIRED')
        state=State(row['study_directory'])
        if state.pool!=self.pool:raise Refusal('QUEUE_EXECUTION_POOL_MISMATCH')
        return state

    def case_status(self,qid,*,catalogue_cache=None):
        row=self.row(qid);req=parse(bytes(row['request']));phase=row['phase'];blockers=[];engine=None
        item=None;state=None
        if row['catalogue']:
            if catalogue_cache is not None and row['catalogue'] in catalogue_cache:cat=catalogue_cache[row['catalogue']]
            else:
                _,cat=self.catalogue(row['catalogue'])
                if catalogue_cache is not None:catalogue_cache[row['catalogue']]=cat
            item=next(x for x in cat['cases'] if x['project_id']==row['project'])
        if row['blocker']:blockers.append(row['blocker'])
        if row['study_directory']:
            try:
                state=self._state(row);engine=state.design(row['design'])
                from .engine_adapter import EngineAdapter
                if state.study.spec['schema']=='KAZE_NAMED_PROJECT_STUDY_V1':
                    from .named_execution import NamedEngineAdapter
                    adapter=NamedEngineAdapter(state)
                else:adapter=EngineAdapter(state.study,state.marker['engine'],state.marker['interpreter'],
                    state=state,protocol_fixture=row['classification']=='PROTOCOL_FIXTURE_NO_SCIENCE')
                adapter.check_source()  # Read-only, no capability/native/dispatch.
                if engine['phase'] in UNKNOWN|TERMINAL:phase=engine['phase']
                elif phase not in ('CANCELLED','REMOVED'):
                    phase='WAITING_CAPABILITY';blockers.append('FRESH_EXPLICIT_CAPABILITY_CHECK_REQUIRED')
            except (Refusal,OSError,ValueError) as e:
                phase='WAITING_CORE_BINDING';blockers.append(str(e))
        if row['phase'] in ('CANCELLED','REMOVED','STALE_PROJECT_BINDING'):phase=row['phase']
        initial=None if item is None else item['initial']
        plan=None if engine is None else engine['plan_data']
        receipt=None if engine is None else engine.get('last_receipt')
        if type(receipt) in (bytes,bytearray):receipt=parse(bytes(receipt))
        summary=None
        if receipt and receipt.get('result',{}).get('parent_settled') is True:
            with state.connection() as c:
                pin=c.execute('SELECT result_sha FROM completions WHERE intent=?',(receipt['intent']['intent_id'],)).fetchone()
            if pin is not None and pin[0]==identity(receipt['result']):summary=receipt['result']['summary']
        actual_end=None if not summary else summary.get('clock');coverage=None
        if row['study_directory'] and state is not None:
            try:
                if state.study.spec['schema']=='KAZE_NAMED_PROJECT_STUDY_V1':
                    from .project_comparison import result as current_result
                    actual=current_result(self,row,item)
                    coverage=None if actual is None or actual.get('metrics')is None else dict(
                        on_time_credits=actual['metrics']['on_time_credits'],complete_horizon=actual['state']=='COMPLETE',actual_end_seconds=actual['actual_end_seconds'])
                else:coverage=self._result_coverage(qid,state)
                if coverage:actual_end=coverage['actual_end_seconds']
            except (Refusal,OSError,ValueError,KeyError,StopIteration) as e:blockers.append(str(e));coverage=None
        bound=None
        if state is not None:
            design=next(d for d in state.study.catalogue.designs if d.design_id==row['design'])
            binding=state.study.spec['binding']
            bound=dict(case_identity=identity(dict(queue_case=qid,project_pins=design.pins,binding=binding)),
                source_sha256=binding['source_sha256'],runtime=binding['runtime'],backend=binding.get('backend',binding['protocol']),
                build=binding.get('build',binding.get('build_sha256')),capability_sha256=binding['capability_sha256'],project_pins=design.pins)
        with self.connection() as c:
            imported=c.execute('SELECT payload FROM project_imported_state WHERE queue=? AND case_identity=?',(self.key,qid)).fetchone()
        return dict(case_identity=qid,project_id=row['project'],classification=row['classification'],phase=phase,
            recorded_phase=row['phase'],blockers=sorted(set(blockers)),
            required_bindings=['final_CORE_source/API/build/runtime/root-domain','current public capability','explicit run or resume'],
            project_pins=None if item is None else item['pins'],
            core_binding=bound,
            imported_history=None if imported is None else parse(bytes(imported[0])),
            execution_case_identity=None if plan is None else identity(dict(case=qid,plan_sha256=engine['plan_sha'])),
            requested_horizon_seconds=req.get('horizon_seconds'),
            actual_prefix=dict(start_seconds=None if initial is None else initial['anchor_seconds'],end_seconds=actual_end,
                state='NOT_RUN' if actual_end is None else 'VERIFIED_SETTLED_PREFIX'),
            resources=req.get('resources'),cost=req.get('cost'),conditional_eta=dict(state='NO_BOUND_MEASUREMENTS',seconds=None),
            coverage=dict(primary_credits=None if not coverage else coverage['on_time_credits'],diagnostic_credits_added=False,
                actual='NOT_RUN' if actual_end is None else 'SETTLED_PREFIX',
                complete_requested_horizon=False if not coverage else coverage['complete_horizon']),
            hardware=None if item is None else item['metadata'],dispatch=False)

    def status(self):
        with self.connection() as c:
            header=dict(c.execute('SELECT generation,paused FROM project_queues WHERE key=?',(self.key,)).fetchone())
            ids=[x[0] for x in c.execute('SELECT identity FROM project_cases WHERE queue=? ORDER BY identity',(self.key,))]
        cache={};cases=[self.case_status(qid,catalogue_cache=cache) for qid in ids]
        return dict(schema='KAZE_PROJECT_QUEUE_STATUS_V1',queue_id=self.config['queue_id'],**header,cases=cases,
            queued=[r['case_identity'] for r in cases if r['phase'].startswith('WAITING')],
            active=[r['case_identity'] for r in cases if r['phase'] in UNKNOWN],
            completed=[r['case_identity'] for r in cases if r['phase'] in TERMINAL],dispatch=False,
            readiness='READY_EXISTS_ONLY_DURING_FRESH_EXPLICIT_CORE_VALIDATION',
            science_new_projects='VERIFIED_SETTLED_PREFIX' if any(r['classification']=='VERIFIED_PRODUCER_DATA' and
                r['actual_prefix']['end_seconds'] is not None for r in cases) else 'NOT_RUN')

    def explicit_validate(self,qid):
        from .engine_adapter import EngineAdapter
        row=self.row(qid);state=self._state(row)
        if row['phase']=='STALE_PROJECT_BINDING':raise Refusal('PHYSICAL_EDIT_REQUIRES_FRESH_PROJECT_CASE')
        if state.study.spec['schema']=='KAZE_NAMED_PROJECT_STUDY_V1':
            from .named_execution import NamedEngineAdapter
            adapter=NamedEngineAdapter(state)
        else:adapter=EngineAdapter(state.study,state.marker['engine'],state.marker['interpreter'],state=state,
            protocol_fixture=row['classification']=='PROTOCOL_FIXTURE_NO_SCIENCE')
        try:adapter.check_execution()
        except (Refusal,OSError,ValueError) as e:
            with self.transaction() as c:
                c.execute('UPDATE project_cases SET blocker=? WHERE queue=? AND identity=?',(str(e)[:4000],self.key,qid))
                self._event(c,'CURRENT_CAPABILITY_REFUSED_NO_RETRY',dict(case_identity=qid,error=str(e)[:4000],dispatch=False))
            raise
        result=self.case_status(qid)
        if result['phase'] in {'CANCELLED','REMOVED'}|UNKNOWN:raise Refusal('CASE_NOT_READY',result['phase'])
        with self.transaction() as c:
            if c.execute('SELECT paused FROM project_queues WHERE key=?',(self.key,)).fetchone()[0]:raise Refusal('QUEUE_STOPPED_EXPLICIT_RESUME_REQUIRED')
            if c.execute('SELECT paused FROM studies WHERE key=?',(state.key,)).fetchone()[0]:raise Refusal('EXPLICIT_STATE_RESUME_REQUIRED')
            if c.execute('SELECT phase FROM project_cases WHERE queue=? AND identity=?',(self.key,qid)).fetchone()[0] in ('CANCELLED','REMOVED'):
                raise Refusal('CASE_CANCELLED_OR_REMOVED')
            c.execute("UPDATE project_cases SET phase='READY',blocker=NULL WHERE queue=? AND identity=?",(self.key,qid))
            self._event(c,'CURRENT_CORE_CAPABILITY_READY',dict(case_identity=qid,study_manifest=state.study.manifest_sha256,
                classification=row['classification'],dispatch=False))
        result['phase']='READY';result['blockers']=[];result['dispatch']=False
        return result

    def explicit_run(self,qid,*,resume_generation=None):
        """Only an explicit call reaches the existing Scheduler. No pending poller."""
        from .scheduler import Scheduler
        row=self.row(qid);state=self._state(row)
        if row['phase'] in ('CANCELLED','REMOVED','STALE_PROJECT_BINDING'):raise Refusal('CASE_CANCELLED_REMOVED_OR_PHYSICALLY_STALE')
        with self.transaction() as c:
            current=c.execute('SELECT phase FROM project_cases WHERE queue=? AND identity=?',(self.key,qid)).fetchone()
            if current['phase'] in ('CANCELLED','REMOVED','STALE_PROJECT_BINDING'):raise Refusal('CASE_CANCELLED_REMOVED_OR_PHYSICALLY_STALE')
            header=c.execute('SELECT paused,generation FROM project_queues WHERE key=?',(self.key,)).fetchone()
            if header['paused']:
                if resume_generation!=header['generation']:raise Refusal('EXPLICIT_QUEUE_GENERATION_REQUIRED')
                c.execute('UPDATE project_queues SET paused=0 WHERE key=?',(self.key,))
            elif resume_generation is not None and resume_generation!=header['generation']:
                raise Refusal('STALE_QUEUE_RESUME_GENERATION')
            # Capture the exact State generation under the same pool lock. A
            # later Stop must make this generation stale, never be reopened by
            # looking up a newer generation after the operator's resume request.
            captured_generation=c.execute('SELECT generation FROM studies WHERE key=?',(state.key,)).fetchone()[0]
            self._event(c,'EXPLICIT_PROJECT_RUN_REQUEST',dict(case_identity=qid,resume_generation=resume_generation))
        scheduler=Scheduler(state,protocol_fixture=row['classification']=='PROTOCOL_FIXTURE_NO_SCIENCE')
        studygen=captured_generation if resume_generation is not None else None
        live_key=(str(self.pool.resolve()),str(state.directory.resolve()))
        with _LIVE_SCHEDULERS_LOCK:
            if live_key in _LIVE_SCHEDULERS:raise Refusal('PROJECT_SCHEDULER_ALREADY_ACTIVE')
            _LIVE_SCHEDULERS[live_key]=scheduler
        # Scheduler revalidates capability, source, runtime, plan, envelope and
        # owner; its spawn_guard and Stop transaction remain the sole launch gate.
        try:scheduler.run(explicit_resume_generation=studygen)
        except (Refusal,OSError,ValueError) as e:
            with self.transaction() as c:
                c.execute('UPDATE project_cases SET blocker=? WHERE queue=? AND identity=?',(str(e)[:4000],self.key,qid))
                self._event(c,'EXPLICIT_RUN_REFUSED_NO_AUTOMATIC_RETRY',dict(case_identity=qid,error=str(e)[:4000]))
            raise
        finally:
            with _LIVE_SCHEDULERS_LOCK:
                if _LIVE_SCHEDULERS.get(live_key)is scheduler:_LIVE_SCHEDULERS.pop(live_key)
        return self.status()

    def stop(self):
        from .operational_r8 import stop
        return stop(self)

    def cancel(self,qid,*,remove=False):
        row=self.row(qid);state=None if not row['study_directory'] else self._state(row)
        if state:
            record=state.design(row['design'])
            if record['phase'] in TERMINAL and not remove:return self.case_status(qid)
            if remove and (record['phase']!='READY' or record['last_intent'] is not None):
                raise Refusal('REMOVE_ONLY_BEFORE_DISPATCH_OR_PLAN')
            if record['phase'] in UNKNOWN:raise Refusal('ACTIVE_OWNER_RETAINS_LEASE_USE_STOP')
        with self.transaction() as c:
            if state:
                current=c.execute('SELECT phase,last_intent FROM designs WHERE study=? AND design=?',(state.key,row['design'])).fetchone()
                if current['phase'] in UNKNOWN or remove and (current['phase']!='READY' or current['last_intent'] is not None):
                    raise Refusal('ACTIVE_OWNER_RETAINS_LEASE_USE_STOP')
            phase='REMOVED' if remove else 'CANCELLED'
            c.execute('UPDATE project_cases SET phase=?,blocker=? WHERE queue=? AND identity=?',(phase,'OPERATOR_'+phase,self.key,qid))
            if state:c.execute("UPDATE studies SET paused=1,generation=generation+1,halt_reason='QUEUE_CANCEL' WHERE key=?",(state.key,))
            self._event(c,'PROJECT_'+phase,dict(case_identity=qid,retained_evidence=True))
        return self.case_status(qid)
_LIVE_SCHEDULERS={}
_LIVE_SCHEDULERS_LOCK=threading.Lock()

def live_scheduler(pool,directory):
    with _LIVE_SCHEDULERS_LOCK:
        return _LIVE_SCHEDULERS.get((str(Path(pool).resolve()),str(Path(directory).resolve())))

