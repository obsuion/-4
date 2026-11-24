"""Loopback-only M8 application/API; no browser/plugin or remote control API."""
from dataclasses import asdict
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import html,json,os,secrets,threading
from hashlib import sha256
from .project_store import ProjectStore,identifier
from .project_runner import ProjectRunner
from .spacecraft_project import SpacecraftProject,project_source_identity
from .spacecraft_project_document import dumps_project,loads_project,MAX_BYTES
from .design_repair import MissionRequirements
from .experiment_codec import object_fields,parse_json

ASSETS=Path(__file__).with_name('workbench_assets')

def edited_design_document(text,*,rebuild_outer_digest=False):
    """Explicit editor operation: rebuild only the outer edited-input checksum.

    Nested common-root/owner digests remain strict and are never regenerated.
    This grants neither model admission nor execution; the codec follows it.
    """
    from .long_mission_document import canonical_json
    if type(text)is not str or len(text.encode('utf8'))>MAX_BYTES or type(rebuild_outer_digest)is not bool:
        raise ValueError('bounded explicit design editor input')
    document=object_fields(parse_json(text),('format','version','inputs','digest'))
    if type(document['format'])is not str or type(document['version'])is not int or (document['format'],document['version'])not in (('B66_IMMUTABLE_SPACECRAFT_DESIGN_PROJECT_V2',2),('KAZEOSAT_SPACECRAFT_PROJECT_V3',3)):
        raise ValueError('explicit V2 design document required')
    if rebuild_outer_digest:
        document['digest']=sha256(canonical_json({key:document[key]for key in ('format','version','inputs')}).encode('utf8')).hexdigest()
    return canonical_json(document)

class Workbench:
    def __init__(self,store,*,runner=None,fixture_mode=False,lifecycle_workspace=None,design_common=None):
        self.store=store;self.runner=ProjectRunner(store) if runner is None else runner
        self.lifecycle=lifecycle_workspace;self.dispatch_lock=threading.RLock()
        self.design_common=design_common
        self.token=secrets.token_hex(32);self.session=secrets.token_hex(32);self.server=None;self.fixture_mode=fixture_mode
        self.owner=secrets.token_hex(32);self.owner_file=store.path('workbench-owner.json')
        # An existing token is never treated as permission to control its PID.
        with self.owner_file.open('x',encoding='utf-8') as f:json.dump(dict(owner=self.owner,PID=os.getpid()),f)
        for pid in store.meta['projects']:
            for job in store.jobs(pid):
                if job['status'] in ('QUEUED','ADMITTED','RUNNING','STOP_REQUESTED'):
                    job['status']='UNKNOWN';job['reason']='NO_RECONSTRUCTIBLE_OWNERSHIP_HANDLE_ON_REOPEN';store.update_job(job)
    def release_owner(self):
        d=json.loads(self.owner_file.read_bytes())
        if d!={'owner':self.owner,'PID':os.getpid()}:raise RuntimeError('foreign application token; preserve it')
        self.owner_file.unlink()
    def handler(self):
        app=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.0'
            def log_message(self,*args):pass
            def respond(self,status,raw,content='application/json; charset=utf-8',cookie=False):
                if type(raw) is not bytes:raw=json.dumps(raw,ensure_ascii=False,allow_nan=False).encode()
                self.send_response(status);self.send_header('Content-Type',content);self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
                if cookie:self.send_header('Set-Cookie','kaz-session='+app.session+'; HttpOnly; SameSite=Strict; Path=/')
                self.end_headers();self.wfile.write(raw)
            def respond_file(self,path,maximum_bytes):
                ProjectStore._reject_links(path);count=path.stat().st_size
                if count>maximum_bytes:raise ValueError('lifecycle streamed download cap')
                self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Length',str(count))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
                with path.open('rb') as stream:
                    remaining=count
                    while remaining:
                        chunk=stream.read(min(2**20,remaining))
                        if not chunk:raise ValueError('lifecycle export changed while streaming')
                        self.wfile.write(chunk);remaining-=len(chunk)
                    if stream.read(1):raise ValueError('lifecycle export grew while streaming')
            def guard(self,mutating=False):
                expected='127.0.0.1:'+str(app.server.server_port)
                if self.headers.get_all('Host')!=[expected]:raise ValueError('loopback Host mismatch')
                origin=self.headers.get_all('Origin')
                if origin is not None and origin!=['http://'+expected]:raise ValueError('same-origin request required')
                if mutating:
                    if origin!=['http://'+expected] or self.headers.get_all('X-CSRF-Token')!=[app.token]:raise ValueError('same-origin CSRF admission')
                    c=SimpleCookie();c.load(self.headers.get('Cookie',''))
                    if 'kaz-session' not in c or c['kaz-session'].value!=app.session:raise ValueError('application session required')
                    if self.headers.get_all('Content-Type')!=['application/json']:raise ValueError('exact JSON content type')
            def do_GET(self):
                try:
                    self.guard();u=urlsplit(self.path)
                    if u.netloc or u.scheme:raise ValueError('relative application route')
                    path=u.path
                    if path=='/':
                        raw=(ASSETS/'index.html').read_text(encoding='utf-8').replace('CSRF_TOKEN',app.token)
                        if app.fixture_mode:raw=raw.replace('</body>','<script src="/test-fixture.js"></script></body>')
                        self.respond(200,raw.encode(),'text/html; charset=utf-8',True)
                    elif path in ('/workbench.js','/control.js','/lifecycle.js','/workbench.css'):
                        self.respond(200,(ASSETS/path[1:]).read_bytes(),'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
                    elif path=='/test-fixture.js' and app.fixture_mode:
                        self.respond(200,app.store.path('fixtures','driver.js').read_bytes(),'text/javascript; charset=utf-8')
                    elif path=='/api/state':self.respond(200,app.store.snapshot())
                    elif path=='/api/lifecycle/state':
                        self.respond(200,dict(enabled=False,roots=[],active_job_id=None) if app.lifecycle is None else dict(enabled=True,**app.lifecycle.snapshot()))
                    elif path.startswith('/api/lifecycle/checkpoints/'):
                        if app.lifecycle is None:raise ValueError('lifecycle workspace is not attached')
                        parts=path.removeprefix('/api/lifecycle/checkpoints/').split('/')
                        if len(parts)!=2:raise ValueError('lifecycle checkpoints route')
                        query=parse_qs(u.query,strict_parsing=True)
                        if set(query)-{'before','limit'} or any(len(v)!=1 or not v[0].isdigit() for v in query.values()):raise ValueError('bounded checkpoint page query')
                        self.respond(200,app.lifecycle.store(parts[0]).checkpoint_history(parts[1],before=None if 'before' not in query else int(query['before'][0]),limit=int(query.get('limit',['16'])[0])))
                    elif path.startswith('/api/lifecycle/intent/'):
                        if app.lifecycle is None:raise ValueError('lifecycle workspace is not attached')
                        parts=path.removeprefix('/api/lifecycle/intent/').split('/')
                        if len(parts)!=2:raise ValueError('lifecycle intent route')
                        store=app.lifecycle.store(parts[0]);identifier(parts[1]);found=None
                        for job in store.jobs():
                            if job['intent']['idempotency_key']==parts[1]:found=job;break
                        self.respond(200,dict(intent=None if found is None else found['intent'],job=found))
                    elif path.startswith('/api/lifecycle/records/'):
                        if app.lifecycle is None:raise ValueError('lifecycle workspace is not attached')
                        parts=path.removeprefix('/api/lifecycle/records/').split('/')
                        if len(parts)!=3:raise ValueError('lifecycle scientific page route')
                        query=parse_qs(u.query,strict_parsing=True)
                        if set(query)-{'after','limit'} or any(len(v)!=1 or not v[0].isdigit() for v in query.values()):raise ValueError('bounded scientific page query')
                        self.respond(200,app.lifecycle.store(parts[0]).stream_page(parts[1],parts[2],after=int(query.get('after',['0'])[0]),limit=int(query.get('limit',['16'])[0])))
                    elif path.startswith('/api/lifecycle/report/'):
                        if app.lifecycle is None:raise ValueError('lifecycle workspace is not attached')
                        parts=path.removeprefix('/api/lifecycle/report/').split('/')
                        if len(parts)!=2:raise ValueError('lifecycle report route')
                        store=app.lifecycle.store(parts[0]);job=store.job(parts[1])
                        if job['result'] is None:raise ValueError('no settled lifecycle report')
                        self.respond(200,dict(cumulative=job['result']['report'],window=job['result']['window_report']))
                    elif path.startswith('/api/lifecycle/export/'):
                        if app.lifecycle is None:raise ValueError('lifecycle workspace is not attached')
                        parts=path.removeprefix('/api/lifecycle/export/').split('/')
                        if len(parts)!=2:raise ValueError('lifecycle export route')
                        store=app.lifecycle.store(parts[0]);identifier(parts[1]);p=store.path('exports',parts[1]+'.zip')
                        self.respond_file(p,128*2**20)
                    elif path.startswith('/api/report/'):
                        jid=identifier(path.removeprefix('/api/report/'));job=app.store.job(jid)
                        if job['result'] is None:raise ValueError('no sealed actual report')
                        self.respond(200,app.store.read_json('jobs',jid,'report.json',cap=2**20))
                    elif path.startswith('/api/details/'):
                        jid=identifier(path.removeprefix('/api/details/'));job=app.store.job(jid)
                        if job['result'] is None:raise ValueError('no sealed detail result')
                        p=app.store.path('jobs',jid,'details.jsonl')
                        if p.stat().st_size>32*2**20:raise ValueError('detail byte cap')
                        self.respond(200,p.read_bytes(),'application/x-ndjson; charset=utf-8')
                    elif path.startswith('/api/intent/'):
                        key=identifier(path.removeprefix('/api/intent/'))
                        body=app.store.read_json('intents',key,'intent.json') if app.store.path('intents',key,'intent.json').exists() else None
                        self.respond(200,dict(intent=body,job=None if body is None else app.store.reconcile_intent(body)))
                    elif path.startswith('/api/wait/'):
                        jid=identifier(path.removeprefix('/api/wait/'))
                        c=SimpleCookie();c.load(self.headers.get('Cookie',''))
                        if self.headers.get('X-CSRF-Token')!=app.token or 'kaz-session' not in c or c['kaz-session'].value!=app.session:
                            raise ValueError('application session required for bounded wait')
                        with app.runner.lock:
                            thread=app.runner.thread if app.runner.active==jid else None
                        if thread is not None:thread.join(timeout=30.)
                        self.respond(200,app.store.job(jid))
                    elif path.startswith('/api/export/'):
                        eid=identifier(path.removeprefix('/api/export/'));p=app.store.path('exports',eid+'.zip')
                        if p.stat().st_size>256*2**20:raise ValueError('export download cap')
                        self.respond(200,p.read_bytes(),'application/zip')
                    else:self.respond(404,dict(error='Неизвестный локальный маршрут'))
                except (ValueError,TypeError,KeyError,OSError) as e:self.respond(403,dict(error=str(e)))
            def do_POST(self):
                try:
                    self.guard(True)
                    lengths=self.headers.get_all('Content-Length')
                    if lengths is None or len(lengths)!=1 or not lengths[0].isdigit():raise ValueError('exact bounded body length')
                    count=int(lengths[0])
                    if count>MAX_BYTES:raise ValueError('request byte cap')
                    body=parse_json(self.rfile.read(count).decode('utf-8'));path=self.path
                    if path.startswith('/api/lifecycle/'):
                        if app.lifecycle is None:raise ValueError('lifecycle workspace is not attached')
                        with app.dispatch_lock:
                            if path=='/api/lifecycle/create':result=app.lifecycle.create_project(body)
                            elif path=='/api/lifecycle/submit':
                                if app.runner.active is not None:raise ValueError('short owned worker already active')
                                result=app.lifecycle.submit(body)
                            elif path=='/api/lifecycle/chain/create':result=app.lifecycle.create_chain(body)
                            elif path=='/api/lifecycle/chain/continue':
                                if app.runner.active is not None:raise ValueError('short owned worker already active')
                                result=app.lifecycle.continue_chain(body)
                            elif path=='/api/lifecycle/chain/stop':result=app.lifecycle.stop_chain(body)
                            elif path=='/api/lifecycle/stop':
                                object_fields(body,('root_identity','job_id'));result=app.lifecycle.stop(body['root_identity'],body['job_id'])
                            elif path=='/api/lifecycle/portable/prepare':
                                object_fields(body,('root_identity','strategy','idempotency_key','execution_seconds'))
                                import uuid
                                store=app.lifecycle.store(body['root_identity']);eid=uuid.uuid4().hex
                                result=app.lifecycle.prepare_portable(body['root_identity'],store.path('exports',eid+'.zip'),strategy=body['strategy'],key=body['idempotency_key'],execution_seconds=body['execution_seconds'])
                                result.update(export_id=eid,url='/api/lifecycle/export/'+body['root_identity']+'/'+eid,dispatch=False)
                            elif path=='/api/lifecycle/export':
                                object_fields(body,('root_identity','job_id'));result=app.lifecycle.store(body['root_identity']).export(body['job_id'])
                            else:raise ValueError('unknown lifecycle mutating route')
                    elif path=='/api/project':
                        object_fields(body,('title','placement','payload_area_m2'))
                        p=SpacecraftProject(app.store.reference,project_source_identity(),body['title'],body['placement'],body['payload_area_m2'])
                        result=app.store.create(p)
                    elif path=='/api/design/template':
                        object_fields(body,('title',))
                        from .lifecycle_contract import LifecycleRoot
                        from .spacecraft_project_v2 import project_from_root
                        common=app.design_common if app.design_common is not None else LifecycleRoot(app.store.reference,600)
                        project=project_from_root(common,title=body['title'],source_identity=project_source_identity())
                        result=dict(document=parse_json(dumps_project(project)),dispatch=False,
                            mission_origin='EXPLICIT_SUPPLIED_COMMON'if app.design_common is not None else'LEGACY_ASSUMED_600_SECOND_TEMPLATE')
                    elif path=='/api/design/create':
                        object_fields(body,('document','rebuild_outer_digest'))
                        text=edited_design_document(body['document'],rebuild_outer_digest=body['rebuild_outer_digest'])
                        result=app.store.create(loads_project(text,expected_source_identity=app.store.source_identity,
                            expected_reference_identity=app.store.reference_identity))
                    elif path=='/api/design/apply':
                        object_fields(body,('project_id','revision','document','rebuild_outer_digest'))
                        text=edited_design_document(body['document'],rebuild_outer_digest=body['rebuild_outer_digest'])
                        result=app.store.edit_document(body['project_id'],body['revision'],text)
                    elif path=='/api/design/lifecycle':
                        if app.lifecycle is None:raise ValueError('lifecycle workspace is not attached')
                        with app.dispatch_lock:result=app.lifecycle.create_design_project(body)
                    elif path=='/api/edit':
                        object_fields(body,('project_id','revision','placement','payload_area_m2','requirements','title'))
                        req=object_fields(body['requirements'],('minimum_credited_products','minimum_priority_score','maximum_unmet_load_wh','maximum_actual_refusals'))
                        result=app.store.edit(body['project_id'],body['revision'],placement=body['placement'],payload_area_m2=body['payload_area_m2'],requirements=MissionRequirements(**req),title=body['title'])
                    elif path=='/api/preview':
                        object_fields(body,('project_id','revision'));result=app.store.preview(body['project_id'],body['revision'])
                    elif path=='/api/save':
                        object_fields(body,('project_id','revision'));result=dict(document=parse_json(dumps_project(app.store.load(body['project_id'],body['revision']))))
                    elif path=='/api/load':
                        object_fields(body,('document',));result=app.store.load_document(body['document'])
                    elif path=='/api/run':
                        object_fields(body,('project_id','revision','idempotency_key'))
                        with app.dispatch_lock:
                            if app.lifecycle is not None and app.lifecycle.active is not None:raise ValueError('lifecycle owned worker already active')
                            result=app.runner.submit(body['project_id'],body['revision'],body['idempotency_key'])
                    elif path=='/api/submit':
                        from .project_intents import validate_intent
                        body=validate_intent(body)
                        with app.dispatch_lock:
                            if app.lifecycle is not None and app.lifecycle.active is not None:raise ValueError('lifecycle owned worker already active')
                            result=app.runner.submit(body['project_id'],body['revision'],body['idempotency_key'],resume_job=body['parent_job_id'],intent=body)
                    elif path=='/api/stop':
                        object_fields(body,('job_id',));result=app.runner.stop(body['job_id'])
                    elif path=='/api/resume':
                        object_fields(body,('job_id','idempotency_key'));old=app.store.job(body['job_id'])
                        with app.dispatch_lock:
                            if app.lifecycle is not None and app.lifecycle.active is not None:raise ValueError('lifecycle owned worker already active')
                            result=app.runner.submit(old['project_id'],old['revision'],body['idempotency_key'],resume_job=old['job_id'])
                    elif path=='/api/export':
                        object_fields(body,('job_id',));result=app.store.export(body['job_id'])
                    elif path=='/api/shutdown':
                        object_fields(body,());app.runner.close()
                        if app.lifecycle is not None:app.lifecycle.close()
                        result=dict(status='OWNED_DISPATCH_CLOSED')
                        threading.Thread(target=app.server.shutdown,daemon=True).start()
                    else:raise ValueError('unknown mutating route')
                    self.respond(200,result)
                except (ValueError,TypeError,KeyError,OSError,RuntimeError) as e:self.respond(400,dict(error=str(e)))
        return Handler
    def bind(self,port=8765):
        if type(port) is not int or not 0<=port<=65535:raise ValueError('local TCP port')
        self.server=ThreadingHTTPServer(('127.0.0.1',port),self.handler());return self.server
    def serve(self,port=8765):
        try:
            self.bind(port)
            print('KazEOSat: http://127.0.0.1:'+str(self.server.server_port),flush=True)
            self.server.serve_forever(poll_interval=.1)
        finally:
            self.runner.close()
            if self.lifecycle is not None:self.lifecycle.close()
            if self.server is not None:self.server.server_close()
            self.release_owner()
