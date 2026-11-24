"""B65 per-design Linux qualification producer from genuine saved evidence.

No PASS booleans accepted. Three real day histories, a substantive native
continuation, original-call restore watch and process receipts are re-admitted.
The historical ``native_uninterrupted_store`` key denotes an independent
complete serial baseline: legitimate resource-bounded resumes are permitted.
The continuation must have a separate terminal execution, not a copied store.
This module launches no campaign and never promotes a short Windows pilot.
"""
from pathlib import Path
import sys,json
from .portable_job import canonical,digest,parse,source_manifest
from .lifetime_execution_authority import reference,_read_reference,_qualification_binding,ACCEPTANCE
from .lifecycle_typed_platform import METHOD,LINUX,admit_build_data,admit_typed_build
FORMAT='B65_GENUINE_TYPED_TARGET_EVIDENCE_V2'

def requirements(root,build,source):
    from .lifetime_execution_authority import domain_identity,typed_backend_binding
    build=admit_build_data(build);manifest=source_manifest(source)
    return dict(format='B65_PER_DESIGN_ACCEPTANCE_REQUIREMENTS_V1',backend=typed_backend_binding(METHOD,build),
        source_manifest_sha256=digest(canonical(manifest)),domain_identity=domain_identity(root),
        runtime=build['runtime'],native_profile=build['profile'],hardware_caps=build['capabilities']['limits'],
        required=['coherent Linux doctor and exact dependencies','strict ELF/build/runtime admission',
            'all owned process protocol fixtures and cleanup','same-runtime full reference/native scientific equality',
            'complete independent 86400-second actual serial native baseline; resource-bounded resumes allowed',
            'separately launched substantive fresh-process MAIN continuation with exact endpoint equality',
            'zero-prefix original Python-call watch and native entry monitor'],
        dispatch_granted=False,physical_qualification=False,cross_abi_migration=False)

def _hex_token(value,name):
    if type(value)is not str or len(value)!=32 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('B66 genuine execution '+name)
    return value

def _execution_history(store,job):
    """Re-read durable launch authorities along the actual causal parent chain.

    Paths are never execution identities.  A copied directory retains these
    identities.  Shared authentic checkpoint prefixes are allowed; terminal
    continuation ownership must be new with respect to the complete baseline.
    This is admission of declared saved provenance, not hardware attestation.
    """
    from .lifetime_execution_authority import _regular
    from .lifetime_campaign import validate_settled_parent
    from .lifecycle_application import _valid_owned_cleanup
    history=[];seen=set();current=job
    while True:
        jid=_hex_token(current['job_id'],'job identity')
        if jid in seen or len(history)>=store.runner_policy.maximum_jobs:
            raise ValueError('B66 bounded acyclic causal execution history')
        seen.add(jid)
        validate_settled_parent(store,current)
        request_raw=_regular(store.path('jobs',jid,'request.json'))
        request=parse(request_raw)
        names=('format','job_id','intent','root_identity','source_identity','runtime','input_sha256','resume')
        if type(request)is not dict or set(request)!=set(names) or canonical(request)!=canonical({k:current[k]for k in names}):
            raise ValueError('B66 causal immutable request binding')
        authority=parse(_regular(store.path('jobs',jid,'parent-launch-authority.json')))
        fields={'format','job_id','root_identity','source_identity','runtime','request_sha256','dispatch_token','command','started_utc'}
        if (type(authority)is not dict or set(authority)!=fields or authority['format']!='B63_IMMUTABLE_PARENT_LAUNCH_AUTHORITY_V1' or
                any(authority[k]!=current[k]for k in ('job_id','root_identity','source_identity','runtime')) or
                authority['request_sha256']!=digest(request_raw)):
            raise ValueError('B66 causal parent launch authority binding')
        dispatch=authority['dispatch_token']
        if (type(dispatch)is not dict or set(dispatch)!={'format','owner','PID','source_identity'} or
                dispatch['format']!='B52_EXCLUSIVE_DISPATCH_OWNER_V1' or dispatch['source_identity']!=current['source_identity'] or
                type(dispatch['PID'])is not int or dispatch['PID']<=0):
            raise ValueError('B66 causal dispatch ownership')
        dispatch_owner=_hex_token(dispatch['owner'],'dispatch owner')
        launch=current['launch'];cleanup=launch['cleanup'];worker=launch['worker_identity']
        if (not _valid_owned_cleanup(cleanup,strict=True) or cleanup.get('backend')!='B60_COOPERATIVE_LINUX_SESSION_V1' or
                type(worker)is not dict or set(worker)!={'worker_PID','worker_PPID','runtime'} or
                any(type(worker[k])is not int or worker[k]<=0 for k in ('worker_PID','worker_PPID')) or
                worker['worker_PID']==worker['worker_PPID'] or worker['worker_PPID']!=dispatch['PID'] or
                worker['runtime']!=current['runtime'] or launch.get('root_PID')!=worker['worker_PID'] or
                worker['worker_PID']not in launch.get('owned_seen_PIDs',[]) or launch.get('command')!=authority['command']):
            raise ValueError('B66 genuine causal worker/cleanup binding')
        owner=_hex_token(cleanup.get('owner_token'),'private process owner')
        settlement=parse(_regular(store.path('jobs',jid,'backend-settlement.json')))
        fields={'format','job_id','root_identity','source_identity','launch_command','root_launch_PID','worker_identity',
            'owned_seen_PIDs','execution_start_monotonic','envelope_to_completed_cleanup_seconds','scope','cleanup'}
        if (type(settlement)is not dict or set(settlement)!=fields or settlement['format']!='B60_DURABLE_BACKEND_SETTLEMENT_V1' or
                any(settlement[k]!=current[k]for k in ('job_id','root_identity','source_identity')) or
                settlement['launch_command']!=authority['command'] or settlement['root_launch_PID']!=worker['worker_PID'] or
                settlement['worker_identity']!=worker or settlement['cleanup']!=cleanup or
                settlement['owned_seen_PIDs']!=launch['owned_seen_PIDs'] or
                settlement['scope']!='LAUNCH_TO_COMPLETED_OWNED_CLEANUP_NOT_LATER_PARENT_REPORTING'):
            raise ValueError('B66 causal backend settlement binding')
        record=dict(job_id=jid,dispatch_owner=dispatch_owner,process_owner=owner,
            worker_identity=worker,parent_launch_sha256=digest(canonical(authority)),
            backend_settlement_sha256=digest(canonical(settlement)))
        if any(record[key]in {v[key]for v in history}for key in ('dispatch_owner','process_owner')):
            raise ValueError('B66 resumed segment requires a fresh execution owner')
        history.append(record)
        resume=current['resume']
        if resume is None:break
        parent=store.job(resume['parent_job_id']);cp=resume['checkpoint']
        if (current['intent']['mode']!='MAIN' or current['intent']['parent_job_id']!=parent['job_id'] or
                current['intent']['snapshot_sha256']!=cp['sha256'] or cp not in parent['checkpoints'] or
                not store.root_input.start_seconds<=cp['clock']<current['result']['clock']):
            raise ValueError('B66 causal checkpoint ancestry binding')
        current=parent
    return history

def _independent_histories(histories):
    """Require independently executed reference/baseline/continuation tips.

    Continuation may reuse an authentic earlier prefix, but its terminal job,
    dispatch and private process owners must occur in neither comparison run.
    """
    for index,history in enumerate(histories):
        tip=history[0]
        for other_index,other in enumerate(histories):
            if index==other_index:continue
            if any(tip[key]in {row[key]for row in other}for key in ('job_id','dispatch_owner','process_owner')):
                raise ValueError('B66 independent causal histories required; copied execution is not comparison')

def _settled(store_path,source_sha,backend,expected_domain):
    from .lifetime_supervisor import _store,_summary
    from .lifetime_campaign import validate_settled_parent
    from .lifecycle_backend import admit_backend_receipt
    from .lifetime_execution_authority import domain_identity
    store,plan=_store(store_path)
    try:
        c=parse(store.path('portable-execution.json').read_bytes());summary=_summary(store,plan)
        if c['source_manifest_sha256']!=source_sha or c['backend_binding']['selection']!=backend or store.runner_policy.mode!='LINUX_PRODUCTION' or store.root_input.duration_seconds!=86400:
            raise ValueError('B65 genuine same-source/Linux/backend/day required')
        if domain_identity(store.root_input)!=expected_domain:
            raise ValueError('B66 actual tested root domain differs from requested qualification domain')
        job=store.job(summary['parent_job_id']);terminal,checkpoint,elapsed=validate_settled_parent(store,job)
        if terminal['kind']!='TARGET' or checkpoint['clock']!=store.root_input.end_seconds:raise ValueError('B65 incomplete day not qualification')
        admit_backend_receipt(job['result']['backend_execution'],c)
        endpoint=job['result']['endpoint'];raw=store.path('jobs',job['job_id'],endpoint['file']).read_bytes()
        if digest(raw)!=endpoint['sha256']:raise ValueError('B65 complete scientific endpoint binding')
        return raw,store.root_input.identity,c,job,_execution_history(store,job)
    finally:store.close_publications()

def admit(path,binding):
    from .lifetime_server_acceptance import admit_acceptance
    from .project_store import runtime_identity
    from .lifetime_execution_authority import _regular,MAX_EVIDENCE_BYTES
    value=parse(_regular(path,MAX_EVIDENCE_BYTES))
    expected={'format','qualification_binding','legacy_day_evidence','python_reference_store','native_uninterrupted_store','native_continuation_store'}
    if type(value)is not dict or set(value)!=expected or value['format']!=FORMAT or canonical(value['qualification_binding'])!=canonical(_qualification_binding(binding)):
        raise ValueError('B65 exact genuine typed acceptance binding')
    if sys.platform!='linux':raise ValueError('B65 actual Linux acceptance only')
    legacy_ref=value['legacy_day_evidence'];legacy=_read_reference(legacy_ref)
    if legacy['reference_store']!=value['native_uninterrupted_store']or legacy['continuation_store']!=value['native_continuation_store']:
        raise ValueError('B65 genuine native day references disagree')
    old=admit_acceptance(legacy_ref['path'],binding['source_manifest_sha256'])
    histories=[];provenance=[];native_contract=None
    for key,backend in(('python_reference_store','REFERENCE'),('native_uninterrupted_store',METHOD),('native_continuation_store',METHOD)):
        science,root,c,job,history=_settled(value[key],binding['source_manifest_sha256'],backend,binding['domain_identity'])
        histories.append((root,science));provenance.append(history)
        if backend==METHOD:
            if canonical(c['backend_binding'])!=canonical(binding['backend_binding']):raise ValueError('B65 genuine typed build/domain mismatch')
            native_contract=c
        if key=='native_continuation_store':
            if job['resume']is None or job['resume']['checkpoint']['clock']<=binding['original_anchor_seconds']:raise ValueError('B65 substantive native resume required')
            proof=parse(_regular(Path(value[key])/'jobs'/job['job_id']/'direct-restore.json',MAX_EVIDENCE_BYTES))
            if proof.get('restored_clock')!=job['resume']['checkpoint']['clock']:raise ValueError('B66 direct restore clock binding')
            monitor=proof.get('native_entry_monitor',{})
            if monitor.get('total_delta')!=0 or not monitor.get('delta')or any(type(x)is not int or x!=0 for x in monitor['delta'].values()):raise ValueError('B65 native restore must prove exact zero entries')
    _independent_histories(provenance)
    if any(v!=histories[0]for v in histories[1:]):raise ValueError('B65 full same-runtime reference/native/day continuation science differs')
    build=admit_build_data(native_contract['native_build'])
    if build['profile']!=LINUX:raise ValueError('B65 genuine ELF Linux profile required')
    admit_typed_build(build)
    return dict(computed_acceptance='PASS',source_manifest_sha256=binding['source_manifest_sha256'],
        runtime=runtime_identity(),day_scientific_sha256=digest(histories[0][1]),physical_qualification=False,
        domain_identity=binding['domain_identity'],legacy_process_and_restore=old,
        causal_provenance=dict(format='B66_INDEPENDENT_SERIAL_BASELINE_AND_FRESH_CONTINUATION_V1',
            histories=provenance,shared_authentic_prefix_permitted=True))

def produce(output,*,legacy_day_evidence,python_reference_store,qualification_binding,binding):
    """Write only after real evidence admission. No caller-approved flag exists."""
    output=Path(output).absolute()
    if output.exists()or output.resolve().is_relative_to(Path(__file__).resolve().parents[2]):raise ValueError('B65 new external acceptance directory')
    legacy_ref=reference(legacy_day_evidence);legacy=_read_reference(legacy_ref)
    value=dict(format=FORMAT,qualification_binding=qualification_binding,legacy_day_evidence=legacy_ref,
        python_reference_store=str(Path(python_reference_store).absolute()),native_uninterrupted_store=legacy['reference_store'],native_continuation_store=legacy['continuation_store'])
    # Use a new external directory, retain a failed validation as evidence.
    output.mkdir(parents=True);genuine=output/'genuine.json';genuine.write_bytes(canonical(value))
    try:
        result=admit(genuine,binding)
        wrapper=dict(format=ACCEPTANCE,qualification_binding=qualification_binding,genuine_evidence=reference(genuine))
        (output/'acceptance.json').write_bytes(canonical(wrapper));(output/'COMPUTED.json').write_bytes(canonical(result))
        return dict(acceptance=reference(output/'acceptance.json'),computed=result)
    except BaseException:
        import traceback
        (output/'FAILURE.txt').write_text(traceback.format_exc(),encoding='utf8');raise
