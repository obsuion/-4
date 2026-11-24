"""Target evidence admission. A boolean attestation cannot grant long execution."""
from pathlib import Path
import sys
from .portable_job import parse,digest,canonical

def admit_acceptance(path,source_manifest_sha256):
    from .project_store import runtime_identity
    from .lifetime_supervisor import _store,_summary
    from .lifetime_campaign import validate_settled_parent
    from .lifecycle_process import FIXTURES
    if not sys.platform.startswith('linux'):raise ValueError('B62 genuine Linux acceptance required')
    p=Path(path)
    if p.is_symlink()or p.stat().st_size>2**20:raise ValueError('B62 acceptance record bytes/link')
    v=parse(p.read_bytes())
    if type(v)is not dict or set(v)!={'format','source_manifest_sha256','runtime','reference_store','continuation_store','protocol_receipts'}or v['format']!='B62_GENUINE_TARGET_EVIDENCE_REFERENCES_V1' or v['source_manifest_sha256']!=source_manifest_sha256 or v['runtime']!=runtime_identity():raise ValueError('B62 target evidence references, not manually set PASS flags')
    endpoints=[];roots=[]
    for key in ('reference_store','continuation_store'):
        store,plan=_store(v[key])
        try:
            c=parse(store.path('portable-execution.json').read_bytes())
            if c['source_manifest_sha256']!=source_manifest_sha256 or store.root_input.duration_seconds!=86400 or store.runner_policy.mode!='LINUX_PRODUCTION':raise ValueError('B62 genuine source-bound Linux scientific day')
            summary=_summary(store,plan);job=store.job(summary['parent_job_id']);t,cp,elapsed=validate_settled_parent(store,job)
            if t['kind']!='TARGET' or cp['clock']!=store.root_input.end_seconds:raise ValueError('B62 complete day required')
            endpoints.append(store.path('jobs',job['job_id'],job['result']['endpoint']['file']).read_bytes());roots.append(store.root_input.identity)
            if key=='continuation_store':
                if job['resume']is None or job['resume']['checkpoint']['clock']<=store.root_input.start_seconds:raise ValueError('B62 substantive fresh native day resume required')
                proof=parse(store.path('jobs',job['job_id'],'direct-restore.json').read_bytes())
                if proof.get('prefix_numerical_calls')not in (0,None):raise ValueError('B62 numerical prefix replay forbidden')
                # The separately bound original-call watch must establish zero;
                # absence of a counter in a restore receipt is not evidence.
                watch=store.path('server-restore-watch.json')
                w=parse(watch.read_bytes())
                if set(w)!={'source_manifest_sha256','job_id','proof','proof_sha256'}or w['source_manifest_sha256']!=source_manifest_sha256 or w['job_id']!=job['job_id']or digest(canonical(w['proof']))!=w['proof_sha256']or w['proof'].get('validity')!='PASS'or w['proof'].get('prefix_numerical_calls_zero')is not True or w['proof'].get('restore_entries')!=1:raise ValueError('B62 genuine saved restore watch required')
        finally:store.close_publications()
    if roots[0]!=roots[1]or endpoints[0]!=endpoints[1]:raise ValueError('B62 whole scientific day/reference/native equality')
    records=v['protocol_receipts']
    if type(records)is not dict or set(records)!=set(FIXTURES):raise ValueError('B62 all genuine process protocol groups required')
    for name,item in records.items():
        if type(item)is not dict or set(item)!={'path','sha256'}:raise ValueError('B62 protocol receipt binding')
        raw=Path(item['path']).read_bytes()
        if len(raw)>2**20 or digest(raw)!=item['sha256']:raise ValueError('B62 protocol receipt raw hash')
        r=parse(raw)
        fields={'format','fixture','source_manifest_sha256','runtime','backend','creator_pid','worker_pid','owner_token','cleanup','observed_seconds','execution_limit_seconds','outcome'}
        if type(r)is not dict or set(r)!=fields or r['format']!='B62_GENUINE_LINUX_PROTOCOL_RECEIPT_V1' or r['fixture']!=name or r['source_manifest_sha256']!=source_manifest_sha256 or r['runtime']!=runtime_identity()or r['backend']!='B60_COOPERATIVE_LINUX_SESSION_V1':raise ValueError('B62 actual protocol source/runtime identity')
        if any(type(r[k])is not int or r[k]<=0 for k in ('creator_pid','worker_pid'))or r['creator_pid']==r['worker_pid']or type(r['owner_token'])is not str or len(r['owner_token'])!=32:raise ValueError('B62 retained creator/root identity')
        cleanup=r['cleanup']
        if cleanup.get('owner_token')!=r['owner_token']or cleanup.get('root_reaped')is not True or cleanup.get('owned_job_empty')is not True or cleanup.get('handles_closed')is not True or cleanup.get('cleanup_within_deadline')is not True or cleanup.get('errors'):raise ValueError('B62 unsettled protocol cleanup')
        if type(r['observed_seconds'])not in(int,float)or type(r['execution_limit_seconds'])not in(int,float)or not 0<r['observed_seconds']<=r['execution_limit_seconds']+2:raise ValueError('B62 protocol envelope')
        if r['outcome']!=('EXPECTED_TIMEOUT'if name=='timeout'else'EXPECTED_EXCEPTION'if name in('exception','parent_report_exception')else'COMPLETED'):raise ValueError('B62 protocol outcome')
    return dict(computed_acceptance='PASS',source_manifest_sha256=source_manifest_sha256,runtime=runtime_identity(),day_scientific_sha256=digest(endpoints[0]),physical_qualification=False)


def run_protocol(directory):
    """Explicit target-only fixed nonnumerical fixtures, never called by doctor."""
    import os,time
    from .lifecycle_process import OwnedPosixGroup,FIXTURES
    from .project_store import runtime_identity
    from .lifetime_journal import publish
    from .lifetime_portable import source_manifest
    source=Path(__file__).resolve().parents[2]
    from kit.serverctl import doctor
    if not doctor(source)['ready_for_engine_attempt']:raise ValueError('B62 actual coherent target Linux required before fixtures')
    root=Path(directory).absolute()
    if root.exists()or root.resolve().is_relative_to(source):raise ValueError('B62 fresh external protocol directory')
    root.mkdir(parents=True);source_sha=digest(canonical(source_manifest(source)));receipts={}
    sequence=time.perf_counter()
    for name in FIXTURES:
        if time.perf_counter()-sequence+6>40:raise ValueError('B62 protocol total envelope exhausted')
        folder=root/name;folder.mkdir();job=None;failure=None;cleanup=None;start=time.perf_counter();timeout=False
        with (folder/'stdout.txt').open('xb')as out,(folder/'stderr.txt').open('xb')as err:
            try:
                job=OwnedPosixGroup([sys.executable,'-B','-m','ops_sim.v5.lifecycle_application','fixture',name],source,dict(os.environ,TMP=str(folder),TEMP=str(folder),PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),out,err,_fixture=True)
                deadline=start+(1 if name=='timeout'else 4)
                while time.perf_counter()<deadline:
                    state=job.state();code=job.poll()
                    if code is not None and not state['job_active_PIDs']:break
                    time.sleep(min(.01,max(0.,deadline-time.perf_counter())))
                timeout=job.poll()is None
                if name=='parent_report_exception':raise RuntimeError('EXPECTED_PARENT_REPORT_EXCEPTION')
            except BaseException as error:failure=repr(error)
            finally:
                if job is not None:
                    end=time.perf_counter()+2
                    cleanup=job.reap(kill=timeout or failure is not None,max_seconds=2,cleanup_deadline=end)
        if job is None:raise ValueError('B62 fixture launch failed: '+str(failure))
        outcome='EXPECTED_TIMEOUT'if name=='timeout'and timeout else'EXPECTED_EXCEPTION'if name=='exception'and cleanup['root_exit_code']not in(None,0)or name=='parent_report_exception'and failure==repr(RuntimeError('EXPECTED_PARENT_REPORT_EXCEPTION'))else'COMPLETED'
        value=dict(format='B62_GENUINE_LINUX_PROTOCOL_RECEIPT_V1',fixture=name,source_manifest_sha256=source_sha,runtime=runtime_identity(),backend='B60_COOPERATIVE_LINUX_SESSION_V1',creator_pid=os.getpid(),worker_pid=job.pid,owner_token=job.token,cleanup=cleanup,observed_seconds=time.perf_counter()-start,execution_limit_seconds=1 if name=='timeout'else 4,outcome=outcome)
        publish(folder/'receipt.json',value,2**20)
        receipts[name]=dict(path=str(folder/'receipt.json'),sha256=digest(canonical(value)))
        if cleanup['errors']or not cleanup['root_reaped']or not cleanup['owned_job_empty']or not cleanup['cleanup_within_deadline']:raise ValueError('B62 genuine fixture invalid; no later fixtures')
    publish(root/'protocol-references.json',receipts,2**20)
    return receipts
