"""Candidate finite server supervisor; one original physical root, settled native suffixes.

No server purchase, network transfer, installation, source migration or arbitrary
command execution is performed. Whole-year/15-year execution remains unverified.
"""
from pathlib import Path
from hashlib import sha256
from dataclasses import asdict
import argparse, json, os, shutil, signal, sys, time, uuid
from .lifetime_io_accounting import fsync


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(value):
    return sha256(encoded(value)).hexdigest()


def source_root():
    return Path(__file__).resolve().parents[2]


def derive_input(input_path,output_path,duration_seconds):
    from ops_sim.v5.lifetime_admission import derive_duration
    _,raw,proof=derive_duration(Path(input_path).read_bytes(),duration_seconds)
    out=Path(output_path)
    if out.exists():raise ValueError('new derived input required')
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('xb')as f:f.write(raw);f.flush();fsync(f.fileno())
    return proof


def _read(path, limit=2**20):
    from ops_sim.v5.portable_job import parse
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > limit:
        raise ValueError('bounded regular lifetime metadata required')
    return parse(p.read_bytes())


def _publish(path,value,limit=16384):
    data=encoded(value)
    if len(data)>limit:raise ValueError('lifetime metadata byte admission')
    p=Path(path)
    from .lifetime_physical_storage import register_producer_path,retire_producer_path
    pending=p.with_suffix('.pending')
    register_producer_path(p);register_producer_path(pending,additional_bytes=len(data))
    p.parent.mkdir(parents=True,exist_ok=True)
    with pending.open('xb')as f:f.write(data);f.flush();fsync(f.fileno())
    if p.exists():raise ValueError('immutable lifetime publication exists')
    os.rename(pending,p)
    retire_producer_path(pending)
    if sys.platform.startswith('linux'):
        fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:fsync(fd, directory=True)
        finally:os.close(fd)


def _directory_bytes(path):
    total=0;count=0
    for p in Path(path).rglob('*'):
        if p.is_symlink():raise ValueError('lifetime store link forbidden')
        if p.is_file():
            count+=1;total+=p.stat().st_size
            if count>1000000:raise ValueError('lifetime physical file population')
    return total


def _store(directory):
    from .lifetime_typed_portable import parent_contract_operation,JOB_V3,JOB_V4
    path=Path(directory)/'portable-job.json'
    if path.is_file() and _read(path).get('format')in(JOB_V3,JOB_V4):
        with parent_contract_operation(directory,source_root(),operation='SUPERVISOR_STORE_OPEN')as owner:
            return _open_store(directory,owner)
    return _open_store(directory,None)


def _metadata_control_family(directory):
    from .lifetime_typed_portable import JOB_V3,JOB_V4,FORMAT_V3,FORMAT_V4
    from .portable_job import JOB,LIFETIME_JOB,LIFETIME_JOB_V2,parse
    from .lifetime_execution_authority import _regular
    path=Path(directory)/'portable-job.json'
    if not path.exists():
        contract=Path(directory)/'portable-execution.json'
        if contract.exists()and _read(contract).get('format')in(FORMAT_V3,FORMAT_V4):
            raise ValueError('YEAR-V4 typed public control requires exact package family')
        return False
    job=parse(_regular(path,2**20))
    if type(job)is not dict or type(job.get('format'))is not str:raise ValueError('YEAR-V4 public control package family')
    if job['format']in(JOB_V3,JOB_V4):return True
    if job['format']not in(JOB,LIFETIME_JOB,LIFETIME_JOB_V2):raise ValueError('YEAR-V4 unknown public control package family')
    contract=_read(Path(directory)/'portable-execution.json')
    if type(contract)is not dict or contract.get('format')in(FORMAT_V3,FORMAT_V4):
        raise ValueError('YEAR-V4 public control package/contract family drift')
    return False # Known legacy families retain their original full read path.


def control_status(directory):
    """Public bounded DATA view; full execution/start admission stays in _store."""
    if _metadata_control_family(directory):
        from .lifetime_typed_portable import metadata_control_operation,metadata_control_snapshot
        with metadata_control_operation(directory,source_root())as view:return metadata_control_snapshot(view)
    store,plan=_store(directory)
    try:return _summary(store,plan)
    finally:_close_session(store)


def control_stop(directory):
    """Publish the existing cooperative pause marker, never scientific authority."""
    if not _metadata_control_family(directory):
        store,plan=_store(directory)
        try:
            marker=store.path('operator-pause.json')
            if marker.exists():
                if _read(marker).get('plan_identity')!=plan['plan_identity']:raise ValueError('YEAR-V1 foreign operator pause')
            else:_publish(marker,dict(plan_identity=plan['plan_identity'],token=uuid.uuid4().hex))
            return dict(requested=True,settled=False,scope='EXISTING_SUPERVISOR_COOPERATIVE_STOP_NOT_PROCESS_TERMINATION',status=_summary(store,plan))
        finally:_close_session(store)
    from .lifetime_typed_portable import metadata_control_operation,metadata_control_snapshot
    from .lifetime_execution_authority import _regular
    from .portable_job import parse,fields
    with metadata_control_operation(directory,source_root())as view:
        metadata_control_snapshot(view) # Current request IDs, immutable pins and bounded status heads.
        active=view.path('dispatch-owner.json')
        if active.exists():
            owner=parse(_regular(active,16384));fields(owner,('format','owner','PID','source_identity'))
            if (owner['format']!='B52_EXCLUSIVE_DISPATCH_OWNER_V1'or type(owner['PID'])is not int or owner['PID']<=0 or
                    owner['source_identity']!=view.meta['source_identity']or type(owner['owner'])is not str or
                    len(owner['owner'])!=32 or any(char not in '0123456789abcdef'for char in owner['owner'])):
                raise ValueError('YEAR-V4 metadata Stop dispatch-owner binding')
        marker=view.path('operator-pause.json');metadata_control_snapshot(view)
        if marker.exists():
            saved=parse(_regular(marker,16384));fields(saved,('plan_identity','token'))
            if (saved['plan_identity']!=view.plan['plan_identity']or type(saved['token'])is not str or
                    len(saved['token'])!=32 or any(char not in '0123456789abcdef'for char in saved['token'])):
                raise ValueError('YEAR-V1 foreign operator pause')
        else:_publish(marker,dict(plan_identity=view.plan['plan_identity'],token=uuid.uuid4().hex))
        return dict(requested=True,settled=False,scope='EXISTING_SUPERVISOR_COOPERATIVE_STOP_NOT_PROCESS_TERMINATION',status=metadata_control_snapshot(view))


def _open_store(directory,owner):
    from ops_sim.v5.lifecycle_application import LifecycleStore
    from ops_sim.v5.lifetime_policy import is_lifetime
    from ops_sim.v5.portable_job import worker_contract_for_store,canonical
    store=LifecycleStore(directory,parent_contract_operation=owner)
    if not is_lifetime(store.runner_policy):
        raise ValueError('new lifetime store required; no migration')
    if owner is None:contract=worker_contract_for_store(store,source_root())
    else:
        from .portable_job import worker_contract
        contract=worker_contract(store.directory,source_root(),operation=owner)
    plan=_read(store.path('lifetime-plan.json'))
    expected=_plan(store,contract)
    if canonical(plan)!=canonical(expected):raise ValueError('immutable lifetime plan/source/runtime drift')
    return store,plan


def _plan(store,contract):
    from ops_sim.v5.lifetime_campaign import PLAN,PLAN_V2
    from ops_sim.v5.lifetime_policy import is_v2,physical_storage,packed_storage
    from ops_sim.v5.lifetime_typed_portable import FORMAT_V3,PLAN_V3,FORMAT_V4,PLAN_V4
    typed=contract.get('format')in(FORMAT_V3,FORMAT_V4)
    value=dict(format=PLAN_V4 if contract.get('format')==FORMAT_V4 else PLAN_V3 if typed else PLAN_V2 if is_v2(store.runner_policy)else PLAN,root_identity=store.meta['root_identity'],input_sha256=store.meta['input_sha256'],
        source_identity=store.meta['source_identity'],runtime=store.meta['runtime'],
        policy=asdict(store.runner_policy),policy_identity=store.runner_policy.identity,
        execution_contract_sha256=digest(contract),root_target=store.root_input.end_seconds,
        original_anchor=store.root_input.start_seconds,automatic_resume=['RESOURCE_TIME','RESOURCE_OUTPUT'],
        incomplete_is_not_coverage=True)
    if is_v2(store.runner_policy):
        value.update(execution_authority_sha256=store.meta['execution_authority_sha256'],
            backend_binding=contract['backend_binding'],pool_inventory='B63_VERIFIED_IMMUTABLE_INITIAL_FILES_ONLY_V1')
    provisional=dict(root_identity=store.root_input.identity,input_sha256=store.meta['input_sha256'],contract_sha256=digest(contract),policy_identity=store.runner_policy.identity,store_name=store.directory.name)
    value['pool_key']=digest(provisional)
    if physical_storage(store.runner_policy):
        from .lifetime_physical_storage import contract as physical_contract,binding_for_store,digest as physical_digest
        value.update(format='YEAR_V4_BOUNDED_PHYSICAL_LIFETIME_PLAN_V1',
            pool_inventory='YEAR_V4_PRODUCER_REGISTERED_SEALED_FILES_V1',
            physical_store_name=store.directory.name,
            physical_storage_contract=physical_contract(store.runner_policy))
        if packed_storage(store.runner_policy):
            value.update(format='YEAR_V5_PACKED_TERMINAL_LIFETIME_PLAN_V2',pool_inventory='YEAR_V5_POSITIVE_INCREMENTAL_BLOCK_INVENTORY_V1')
        value['pool_key']=physical_digest(binding_for_store(store))
    return dict(value,plan_identity=digest(value))


def _pool_owners(directory,key,policy):
    """Named reservation owners, not authority inferred from arbitrary files."""
    path=Path(directory).absolute()
    from .lifetime_policy import physical_storage
    if physical_storage(policy):
        from .lifetime_physical_storage import pool_owners
        return pool_owners(path,key)
    declared=[('STORE',path.name,'DIRECTORY'),('INITIAL_PACKAGE',path.name+'.initial.zip','FILE')]
    declared.extend(('EXPORT'if i==0 else'BACKUP',path.name+('.exports'if i==0 else'.backup-'+str(i+1)),'DIRECTORY')for i in range(policy.backup_copies))
    return [dict(owner=digest(dict(pool_key=key,role=role,path=name)),role=role,path=name,kind=kind,
        identity=digest(dict(pool_key=key,role=role,scope='EXPLICIT_RESERVED_OWNER_NOT_DISCOVERED_FILE')))
        for role,name,kind in declared]


def _pool_inventory(store,plan,owners):
    """Credit only admitted immutable producer metadata, never rglob(root).

    Dynamic checkpoints, append streams, initial ZIP, exports and foreign files
    deliberately receive ZERO credit. Their bytes still reduce actual free
    space; a conservative refusal is preferable to inventing materialization.
    """
    store._pinned()
    from ops_sim.v5.portable_job import worker_contract_for_store
    contract=worker_contract_for_store(store,source_root())
    if digest(contract)!=plan['execution_contract_sha256']:raise ValueError('B63 pool exact immutable execution contract')
    owner=next(x for x in owners if x['role']=='STORE')
    names=('input.json','store.json','portable-execution.json','portable-job.json',
           'execution-authority.json','lifetime-plan.json','lifetime-native-build.json')
    inventory=[]
    for name in names:
        path=store.path(name)
        if name=='lifetime-native-build.json'and contract.get('native_build')is None:
            if path.exists():raise ValueError('B63 unexpected native receipt has no owned inventory authority')
            continue
        if not path.exists():
            raise ValueError('B63 declared immutable store file missing: '+name)
        if path.stat().st_size>16*2**20:raise ValueError('B63 immutable pool metadata bound')
        content=path.read_bytes()
        if content!=encoded(_read(path,16*2**20)):raise ValueError('B63 pool credited metadata must be exact canonical producer bytes')
        if name=='input.json'and sha256(content).hexdigest()!=store.meta['input_sha256']:raise ValueError('B63 pool input authority drift')
        if name=='lifetime-plan.json'and encoded(_read(path))!=encoded(plan):raise ValueError('B63 pool immutable plan drift')
        if name=='lifetime-native-build.json'and content!=encoded(contract['native_build']):raise ValueError('B63 pool native build canonical authority drift')
        inventory.append(dict(owner=owner['owner'],path=store.directory.name+'/'+name,
            sha256=sha256(content).hexdigest(),bytes=len(content)))
    return inventory


def _reserve_pool(store,plan):
    from ops_sim.v5.lifetime_execution_authority import admit_store_execution
    from ops_sim.v5.lifetime_policy import is_v2,QUALIFICATION,windows_policy,physical_storage,packed_storage
    admit_store_execution(store)
    p=store.runner_policy
    if physical_storage(p):
        from .lifetime_physical_storage import reserve_pool as physical_pool,open_for_store
        owners=_pool_owners(store.directory,plan['pool_key'],p)
        if packed_storage(p):
            # New producer-owned incremental index consumes only added/sealed
            # blocks. No V4 full prefix content inventory or JSON is rebuilt.
            return physical_pool(store.directory.parent,plan['pool_key'],p,owners=owners,inventory=(),windows=windows_policy(p))
        inventory=_pool_inventory(store,plan,owners)
        with open_for_store(store) as physical:
            explicit=physical.inventory()
        by_path={value['path']:value for value in inventory}
        for entry in explicit:
            bound=next((value for value in owners if entry['path']==value['path'] or value['kind']=='DIRECTORY' and entry['path'].startswith(value['path']+'/')),None)
            if bound is None:raise ValueError('YEAR-V4 sealed inventory has no declared physical pool owner')
            by_path[entry['path']]=dict(owner=bound['owner'],**entry)
        return physical_pool(store.directory.parent,plan['pool_key'],p,owners=owners,
            inventory=list(by_path.values()),windows=windows_policy(p))
    if is_v2(p):
        from ops_sim.v5.lifetime_pool import reserve_v2
        owners=_pool_owners(store.directory,plan['pool_key'],p)
        return reserve_v2(store.directory.parent,plan['pool_key'],p,owners=owners,
            inventory=_pool_inventory(store,plan,owners),windows=windows_policy(p))
    from ops_sim.v5.lifetime_pool import reserve
    return reserve(store.directory.parent,plan['pool_key'],p,windows=windows_policy(p))


from ops_sim.v5.lifetime_journal import Journal


def _summary(store,plan):
    from ops_sim.v5.finite_campaign import intent_role
    from .lifetime_no_launch import administrative_ids
    administrative=administrative_ids(store)
    jobs=store.jobs();index={j['job_id']:j for j in jobs};primary=[];observed={'PRIMARY':0.,'DIAGNOSTIC':0.};unknown={'PRIMARY':0,'DIAGNOSTIC':0}
    for j in jobs:
        role=intent_role(j['intent'],index.get(j['intent']['parent_job_id']),None if j['resume']is None else j['resume']['checkpoint'],store.root_input.end_seconds)
        if role=='PRIMARY':primary.append(j)
        launch=j.get('launch');v=None if launch is None else launch.get('observed_envelope_seconds')
        if type(v)in(int,float)and 0<=v<float('inf'):observed[role]+=v
        else:unknown[role]+=store.runner_policy.hard_seconds+2
    scientific=[j for j in primary if j['job_id']not in administrative]
    parents={j['intent']['parent_job_id']for j in scientific};tips=[j for j in scientific if j['job_id']not in parents]
    if scientific and len(tips)!=1:raise ValueError('B62 sole forward primary tip')
    tip=None if not tips else tips[0]
    value=dict(plan_identity=plan['plan_identity'],root_identity=store.root_input.identity,
        target_seconds=store.root_input.end_seconds,source_identity=store.meta['source_identity'],runtime=store.meta['runtime'],
        jobs=len(jobs),primary_jobs=len(primary),diagnostic_jobs=len(jobs)-len(primary),observed_seconds=observed['PRIMARY'],
        diagnostic_observed_seconds=observed['DIAGNOSTIC'],reserved_unknown_seconds=unknown['PRIMARY'],
        clock=store.root_input.start_seconds if tip is None or tip['result']is None else tip['result']['clock'],
        parent_job_id=None if tip is None else tip['job_id'],typed_terminal=None if tip is None else tip.get('typed_stop'),
        operator_pause=store.path('operator-pause.json').exists(),mode=store.runner_policy.mode,
        qualification='FINITE_ACTUAL_PREFIX_ONLY_SERVER_ACCEPTANCE_PENDING')
    if 'execution_authority_sha256'in plan:value.update(execution_authority_sha256=plan['execution_authority_sha256'],backend_binding=plan['backend_binding'],runner_store_format=store.meta['format'])
    from .lifetime_no_launch import enabled
    if enabled(store.runner_policy):value.update(no_launch_jobs=len(administrative),scientific_primary_jobs=len(scientific))
    return value


def _lock(store):
    from ops_sim.v5.lifetime_journal import lease
    from ops_sim.v5.lifetime_policy import PRODUCTION,QUALIFICATION,windows_policy
    p=store.runner_policy
    if p.mode==PRODUCTION:
        from kit.serverctl import doctor
        d=doctor(source_root())
        if not d['ready_for_engine_attempt']:raise RuntimeError('B62 production Linux doctor required: '+repr(d['checks']))
    from ops_sim.v5.lifetime_execution_authority import admit_store_execution
    admit_store_execution(store)
    return lease(store.path('lifetime-supervisor.lock'),windows=windows_policy(p))


def run(directory,*,explicit_continue=False,on_launch=None,on_finish=None,stop_when=None,job_factory=None,pilot_stop_minimum_partial_bits=None,maximum_segments=None,no_launch_authority=None):
    # Validate the complete DATA contract before selecting a native metadata
    # implementation. _run_original still performs full store/plan/source/
    # runtime/project/permission admission before ANY launch.
    from contextlib import nullcontext
    scope=nullcontext();path=Path(directory)/'portable-execution.json'
    if path.is_file():
        contract=_read(path)
        if type(contract)is dict and contract.get('format')=='B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4':
            from .lifetime_typed_portable import admit_execution_contract_data_v3
            from .metadata_codec import admitted_metadata_scope
            admit_execution_contract_data_v3(contract)
            scope=admitted_metadata_scope(contract['native_build'])
    with scope:
        return _run_original(directory,explicit_continue=explicit_continue,on_launch=on_launch,on_finish=on_finish,stop_when=stop_when,job_factory=job_factory,pilot_stop_minimum_partial_bits=pilot_stop_minimum_partial_bits,maximum_segments=maximum_segments,no_launch_authority=no_launch_authority)


def _run_original(directory,*,explicit_continue=False,on_launch=None,on_finish=None,stop_when=None,job_factory=None,pilot_stop_minimum_partial_bits=None,maximum_segments=None,no_launch_authority=None):
    if maximum_segments is not None and (type(maximum_segments)is not int or not 1<=maximum_segments<=1024):raise ValueError("YEAR-V1 exact finite invocation segment count")
    if pilot_stop_minimum_partial_bits is not None:
        from ops_sim.v5.lifecycle_pilot_stop import _integer,MAX_BITS
        _integer(pilot_stop_minimum_partial_bits,'supervisor pilot stop minimum partial bits',1,MAX_BITS)
    store,plan=_store(directory)
    try:
        if pilot_stop_minimum_partial_bits is not None:
            from ops_sim.v5.lifetime_policy import is_v2
            if not is_v2(store.runner_policy):raise ValueError('B63 supervisor pilot stop requires explicit V2 store')
        with _lock(store):
            return _run_locked(store,plan,explicit_continue=explicit_continue,on_launch=on_launch,on_finish=on_finish,stop_when=stop_when,job_factory=job_factory,pilot_stop_minimum_partial_bits=pilot_stop_minimum_partial_bits,maximum_segments=maximum_segments,no_launch_authority=no_launch_authority)
    finally:_close_session(store)


def _close_session(store,runner=None):
    """Close both owners best-effort without replacing an active primary error."""
    primary=sys.exception();errors=[]
    if runner is not None:
        try:runner.close()
        except BaseException as error:errors.append(error)
    try:store.close_publications()
    except BaseException as error:errors.append(error)
    if not errors:return
    if primary is not None:
        primary.supervisor_close_failures=[*getattr(primary,'supervisor_close_failures',()),*errors]
        if runner is not None and runner._last_job_id is not None:
            runner._parent_error(runner._last_job_id,'SUPERVISOR_BEST_EFFORT_CLOSE',primary,secondary=errors[:8])
        return
    failure=RuntimeError('lifetime supervisor close failures: '+'; '.join(repr(e)for e in errors));failure.close_failures=errors
    raise failure from errors[0]


def _pilot_stop_on_launch(store,minimum_partial_bits,on_launch):
    """Arm on the Runner's SAME store/parent-ledger owner before its thread.

    An external second store instance must not append to a parent publication
    ledger cached by the active Runner.  The public hook receives ordinary job
    DATA only; this adapter preserves that older callback contract unchanged.
    """
    if minimum_partial_bits is None:return on_launch
    from ops_sim.v5.lifecycle_pilot_stop import _integer,MAX_BITS
    from ops_sim.v5.lifetime_policy import is_v2
    _integer(minimum_partial_bits,'supervisor pilot stop minimum partial bits',1,MAX_BITS)
    if not is_v2(store.runner_policy):raise ValueError('B63 supervisor pilot stop requires explicit V2 store')
    def before(job):
        store.arm_pilot_stop(job['job_id'],minimum_partial_bits)
        if on_launch is not None:on_launch(job)
    return before


def _run_locked(store,plan,*,explicit_continue,on_launch,on_finish,stop_when,job_factory,pilot_stop_minimum_partial_bits=None,maximum_segments=None,no_launch_authority=None):
    from ops_sim.v5.lifecycle_application import LifecycleRunner,make_intent
    from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget
    from ops_sim.v5.lifetime_campaign import validate_settled_parent
    from ops_sim.v5.lifetime_execution_authority import admit_store_execution
    admit_store_execution(store)
    on_launch=_pilot_stop_on_launch(store,pilot_stop_minimum_partial_bits,on_launch)
    p=store.runner_policy;journal=Journal(store,plan)
    runner=LifecycleRunner(store,job_factory=job_factory,on_launch=on_launch,on_finish=on_finish);previous_handlers={};stop_requested=False
    def request_stop(signum=None,frame=None):
        nonlocal stop_requested
        stop_requested=True
        marker=store.path('operator-pause.json')
        if not marker.exists():_publish(marker,dict(plan_identity=plan['plan_identity'],token=uuid.uuid4().hex))
        if runner.active is not None:runner.stop(runner.active)
    try:
        # Outer signals do NOT promise a scientific checkpoint. Use serverctl stop.
        # Reconcile only exact durable intents; uncertain submissions never retry.
        from .lifetime_no_launch import dispositions,enabled,admit_recovery
        records=list(journal.records());administrative=dispositions(store,records)if enabled(p)else {}
        settled={x['data']['job_id']for x in records if x['action']in ('SETTLED','RECOVER_SETTLED','DIAGNOSTIC_SETTLED')}
        for record in records:
            if record['action'] not in ('DISPATCH','DIAGNOSTIC'):continue
            job=store.reconcile(record['data']['intent'])
            if job is None:raise ValueError('B62 uncertain dispatched intent; no blind retry')
            if job['job_id']in administrative:continue
            if job['job_id']not in settled:
                terminal,checkpoint,elapsed=validate_settled_parent(store,job)
                journal.append('RECOVER_SETTLED',dict(job_id=job['job_id'],clock=checkpoint['clock'],checkpoint_sha256=checkpoint['sha256'],terminal=terminal,observed_seconds=elapsed))
        recovery=admit_recovery(store,records,no_launch_authority)if enabled(p)else None
        if no_launch_authority is not None and not enabled(p):raise ValueError('YEAR-V3 prospective recovery policy required')
        if explicit_continue:
            # This action is explicit; read-only open never clears a pause.
            marker=store.path('operator-pause.json')
            proof=None if not marker.exists()else _read(marker)
            if proof is not None and proof.get('plan_identity')!=plan['plan_identity']:raise ValueError('foreign operator pause')
            journal.append('EXPLICIT_CONTINUE',dict(pause=proof))
            if marker.exists():marker.unlink()
        invocation_start_primary=_summary(store,plan)["primary_jobs"]
        while True:
            summary=_summary(store,plan)
            if maximum_segments is not None and summary["primary_jobs"]-invocation_start_primary>=maximum_segments:
                journal.append("HALT",dict(reason="INVOCATION_SEGMENT_LIMIT_NO_REWIND"));break
            parent=None if summary['parent_job_id']is None else store.job(summary['parent_job_id'])
            if store.path('operator-pause.json').exists() or stop_requested:
                journal.append('HALT',dict(reason='USER_PAUSED'));break
            if parent is not None:
                terminal,cp,elapsed=validate_settled_parent(store,parent)
                if terminal['kind']=='TARGET':
                    journal.append('HALT',dict(reason='ORIGINAL_TARGET_REACHED',clock=cp['clock']));break
                if terminal['kind']=='USER' and not explicit_continue:
                    journal.append('HALT',dict(reason='USER_REQUIRES_EXPLICIT_CONTINUE'));break
                if terminal['kind']not in ('RESOURCE_TIME','RESOURCE_OUTPUT','USER'):
                    journal.append('HALT',dict(reason='MODEL_OR_PHYSICAL_TERMINAL',terminal=terminal));break
                if cp['clock']<=store.root_input.start_seconds:raise ValueError('resource prefix has no scientific progress')
            jobs=store.jobs()
            if summary['primary_jobs']>=p.maximum_primary_segments:
                journal.append('HALT',dict(reason='FINITE_PRIMARY_LIMIT'));break
            remaining=p.maximum_observed_primary_seconds-summary['observed_seconds']-summary['reserved_unknown_seconds']
            if remaining<p.hard_seconds+p.cleanup_seconds:
                journal.append('HALT',dict(reason='FINITE_WALL_ADMISSION'));break
            # The full declared output population was reserved before initial work.
            # Recheck actual bytes/free-space before every job; no automatic cleanup.
            _reserve_pool(store,plan)
            from .lifetime_policy import physical_storage,packed_storage
            if physical_storage(p):
                from .lifetime_physical_storage import open_for_store,GLOBAL_EXHAUSTED
                with open_for_store(store) as physical:
                    admission=(physical.admission_status(p.maximum_output_bytes) if packed_storage(p) else
                        dict(admitted=physical.can_admit_segment(p.maximum_output_bytes),reason=GLOBAL_EXHAUSTED))
                    storage=physical.snapshot();fits=admission['admitted']
                if not fits:
                    journal.append('HALT',dict(reason=admission['reason'],
                        retained_headroom_bytes=storage['global_retained_headroom_bytes'],
                        next_payload_bytes=p.maximum_output_bytes,automatic_retry=False));break
            else:
                size=_directory_bytes(store.directory)
                if size+p.maximum_output_bytes+16*2**20>p.disk_limit_bytes or shutil.disk_usage(store.directory).free<p.maximum_output_bytes+32*2**20:
                    journal.append('HALT',dict(reason='FINITE_DISK_ADMISSION'));break
            if journal.sequence+3>p.maximum_journal_records:
                if journal.sequence<p.maximum_journal_records:journal.append('HALT',dict(reason='FINITE_JOURNAL_RESERVE'))
                break
            ordinal=summary['primary_jobs']+1
            key=sha256((plan['plan_identity']+':'+str(ordinal)+':'+('INITIAL'if parent is None else cp['sha256'])).encode()).hexdigest()[:32]
            if recovery is not None:key=recovery['next_key']
            intent=make_intent(store.root_input.identity,key=key,
                parent_job_id=None if parent is None else parent['job_id'],
                snapshot_sha256=None if parent is None else cp['sha256'],
                execution_seconds=p.hard_seconds,maximum_output_bytes=p.maximum_output_bytes,
                execution_budget=ExecutionBudget(p.hard_seconds,p.soft_seconds,p.finalization_seconds),
                publication_profile=store.publication_profile,profile_bound=True)
            dispatch=dict(ordinal=ordinal,intent=intent)
            if recovery is not None:
                admit_recovery(store,records,no_launch_authority,intent)
                dispatch.update(recovery_job_id=recovery['job_id'],recovery_authority=no_launch_authority)
            journal.append('DISPATCH',dispatch)
            recovery=None;no_launch_authority=None
            job=runner.submit(intent)
            while runner.thread is not None and runner.thread.is_alive():
                runner.thread.join(.25)
                if stop_when is not None and stop_when(store,runner):request_stop()
                if store.path('operator-pause.json').exists() and runner.active is not None:runner.stop(runner.active)
            job=store.job(job['job_id']);terminal,newcp,elapsed=validate_settled_parent(store,job)
            if physical_storage(p):
                from .lifetime_physical_storage import seal_for_job
                seal_for_job(store,job)
            oldclock=store.root_input.start_seconds if parent is None else cp['clock']
            if newcp['clock']<=oldclock and terminal['kind']in ('RESOURCE_TIME','RESOURCE_OUTPUT'):
                raise ValueError('resource no progress; no blind retry')
            journal.append('SETTLED',dict(ordinal=ordinal,job_id=job['job_id'],clock=newcp['clock'],
                checkpoint_sha256=newcp['sha256'],terminal=terminal,observed_seconds=elapsed))
            explicit_continue=False
        return _summary(store,plan)
    finally:
        try:_close_session(store,runner)
        finally:
            for sig,handler in previous_handlers.items():signal.signal(sig,handler)
            pass


def export_result(directory,output):
    from ops_sim.v5.lifetime_result import export_result as export
    store,plan=_store(directory)
    try:
        from ops_sim.v5.lifetime_policy import is_v2,physical_storage
        if physical_storage(store.runner_policy):
            from .lifetime_physical_storage import publish_data_export
            _reserve_pool(store,plan)
            return publish_data_export(store,plan,output,export)
        if is_v2(store.runner_policy):
            from ops_sim.v5.project_store import ProjectStore
            target=Path(output).absolute();allowed=store.directory.parent/(store.directory.name+'.exports')
            ProjectStore._reject_links(target)
            if target.parent!=allowed or target.suffix.lower()!='.zip' or target.exists():raise ValueError('B63 export requires new file in its reserved exports directory')
            used=0;count=0
            for i in range(store.runner_policy.backup_copies):
                path=store.directory.parent/(store.directory.name+('.exports'if i==0 else'.backup-'+str(i+1)))
                if path.exists():
                    used+=_directory_bytes(path)
                    count+=sum(p.is_file()for p in path.rglob('*'))
            # Every export is charged prospectively at its existing finite cap;
            # foreign data consumes this reserve but never earns pool credit.
            from ops_sim.v5.lifetime_result import MAX_BYTES
            if (count>=4096 or used+MAX_BYTES>store.runner_policy.maximum_reserved_job_output_bytes*store.runner_policy.backup_copies
                    or shutil.disk_usage(store.directory.parent).free<MAX_BYTES+2**20):raise ValueError('B63 prospective export/backup allocation exhausted')
            allowed.mkdir(parents=True,exist_ok=True)
        return export(store,plan,output)
    finally:_close_session(store)


def prepare(input_path,directory,policy,*,strategy='B60_SEALED_STATIC_V1',backend='REFERENCE',build=None,execution_mode='PILOT',acceptance=None):
    from ops_sim.v5.lifecycle_document import loads_root
    from ops_sim.v5.portable_job import worker_contract_for_store
    from ops_sim.v5.lifetime_policy import is_v2,is_lifetime,QUALIFICATION,windows_policy
    if not is_lifetime(policy):raise TypeError('exact named lifetime policy required')
    from ops_sim.v5.lifetime_policy import PRODUCTION
    if policy.mode==PRODUCTION:
        from kit.serverctl import doctor
        d=doctor(source_root())
        if not d['ready_for_engine_attempt']:raise ValueError('B63 production Linux doctor prerequisite before pool/store writes')
    raw=Path(input_path).read_bytes();root=loads_root(raw);path=Path(directory).absolute();package=path.with_name(path.name+'.initial.zip')
    if path.exists()or package.exists():raise ValueError('B62 fresh store/package required')
    # A complete source-bound reservation precedes the package/store write.
    if is_v2(policy):
        from ops_sim.v5.lifetime_portable import execution_contract_v2,prepare_lifetime_v2,create_lifetime_store_v2
        from ops_sim.v5.lifecycle_backend import TYPED_SELECTIONS
        if backend in TYPED_SELECTIONS:
            from ops_sim.v5.lifetime_typed_portable import (execution_contract_v3 as execution_contract_v2,
                prepare_lifetime_v3 as prepare_lifetime_v2,create_lifetime_store_v3 as create_lifetime_store_v2)
        from ops_sim.v5.lifetime_execution_authority import make_authority
        from ops_sim.v5.lifetime_pool import reserve_v2
        c=execution_contract_v2(root,source_root(),strategy,backend=backend,build=build)
        make_authority(root,raw,c,policy,mode=execution_mode,backend=backend,build=build,acceptance=acceptance)
    else:
        if backend!='REFERENCE'or build is not None or acceptance is not None or execution_mode!='PILOT':raise ValueError('B63 backend/long execution requires explicitly new store policy')
        from ops_sim.v5.lifetime_portable import execution_contract
        from ops_sim.v5.portable_job import prepare_lifetime,create_lifetime_store
        c=execution_contract(root,source_root(),strategy)
        from ops_sim.v5.lifetime_execution_authority import PILOT_SECONDS,PILOT_PRIMARY_SEGMENTS,PILOT_DIAGNOSTIC_SLOTS,PILOT_HARD_SECONDS
        if (root.duration_seconds>PILOT_SECONDS or policy.maximum_primary_segments>PILOT_PRIMARY_SEGMENTS
                or policy.reserved_diagnostic_slots>PILOT_DIAGNOSTIC_SLOTS or policy.hard_seconds>PILOT_HARD_SECONDS):raise ValueError('B63 legacy prepare has no long execution authority')
    provisional=dict(root_identity=root.identity,input_sha256=sha256(raw).hexdigest(),contract_sha256=digest(c),policy_identity=policy.identity,store_name=path.name)
    key=digest(provisional)
    from .lifetime_policy import physical_storage
    if physical_storage(policy):
        from .lifetime_physical_storage import prepare_owner,digest as physical_digest
        from .spacecraft_project import project_source_identity
        binding=dict(root_identity=root.identity,source_identity=project_source_identity(),
            input_sha256=sha256(raw).hexdigest(),policy_identity=policy.identity,store_name=path.name)
        key=physical_digest(binding)
        prepare_owner(path,policy,binding,initial_package=True)
    if is_v2(policy):
        if not physical_storage(policy):reserve_v2(path.parent,key,policy,owners=_pool_owners(path,key,policy),inventory=(),windows=windows_policy(policy))
        if physical_storage(policy):
            from .lifetime_physical_storage import register_producer_path
            register_producer_path(package)
        prepare_lifetime_v2(package,root,source_root(),policy,strategy=strategy,key=uuid.uuid4().hex,
            backend=backend,build=build,execution_mode=execution_mode,acceptance=acceptance)
        store,intent=create_lifetime_store_v2(package,path,source_root())
    else:
        from ops_sim.v5.lifetime_pool import reserve
        reserve(path.parent,key,policy,windows=windows_policy(policy))
        prepare_lifetime(package,root,source_root(),policy,strategy=strategy,key=uuid.uuid4().hex)
        store,intent=create_lifetime_store(package,path,source_root())
    plan=_plan(store,worker_contract_for_store(store,source_root()))
    plan['pool_key']=key
    # pool_key is part of the plan identity; _plan computes the same deterministic key.
    if plan!=_plan(store,c):raise ValueError('B62 plan/pool binding')
    _publish(store.path('lifetime-plan.json'),plan)
    if physical_storage(policy):
        from .lifetime_physical_storage import initialize_store
        initialize_store(store)
    store.close_publications();return dict(prepared=True,store=str(path),package=str(package),plan=plan,dispatch=False)


def diagnostic(directory,parent_job_id,checkpoint_sha256,*,verbose=False,on_launch=None,on_finish=None,job_factory=None,no_launch_authority=None):
    from ops_sim.v5.lifecycle_application import LifecycleRunner,make_intent
    from ops_sim.v5.lifecycle_execution_budget import ExecutionBudget
    from ops_sim.v5.lifetime_campaign import validate_settled_parent
    store,plan=_store(directory);p=store.runner_policy
    with _lock(store):
        parent=store.job(parent_job_id);validate_settled_parent(store,parent)
        cp=store.find_checkpoint(parent_job_id,checkpoint_sha256)
        from .lifetime_no_launch import enabled,admit_recovery
        recovery=None;records=[]
        if enabled(p):
            journal=Journal(store,plan);records=list(journal.records())
            recovery=admit_recovery(store,records,no_launch_authority)
        if no_launch_authority is not None and not enabled(p):raise ValueError('YEAR-V3 recovery policy required')
        key=sha256((plan['plan_identity']+':diagnostic:'+parent_job_id+':'+checkpoint_sha256+':'+str(verbose)).encode()).hexdigest()[:32]
        if recovery is not None:key=recovery['next_key']
        intent=make_intent(store.root_input.identity,key=key,parent_job_id=parent_job_id,snapshot_sha256=checkpoint_sha256,
            mode='DIAGNOSTIC_VERBOSE'if verbose else'DIAGNOSTIC_NORMAL',window_end_seconds=store.root_input.end_seconds,execution_seconds=p.hard_seconds,
            maximum_output_bytes=p.maximum_output_bytes,execution_budget=ExecutionBudget(p.hard_seconds,p.soft_seconds,p.finalization_seconds),publication_profile=store.publication_profile,profile_bound=True)
        _reserve_pool(store,plan)
        from .lifetime_policy import physical_storage,packed_storage
        if physical_storage(p):
            from .lifetime_physical_storage import open_for_store,GLOBAL_EXHAUSTED
            with open_for_store(store) as physical:
                admission=(physical.admission_status(p.maximum_output_bytes) if packed_storage(p) else
                    dict(admitted=physical.can_admit_segment(p.maximum_output_bytes),reason=GLOBAL_EXHAUSTED))
                if not admission['admitted']:raise ValueError(admission['reason'])
        elif _directory_bytes(store.directory)+p.maximum_output_bytes+16*2**20>p.disk_limit_bytes or shutil.disk_usage(store.directory).free<p.maximum_output_bytes+32*2**20:raise ValueError('B62 full diagnostic disk reservation unavailable')
        journal=Journal(store,plan)
        if journal.sequence+3>p.maximum_journal_records:raise ValueError('B62 full diagnostic journal reservation unavailable')
        dispatch=dict(intent=intent)
        if recovery is not None:
            admit_recovery(store,records,no_launch_authority,intent)
            dispatch.update(recovery_job_id=recovery['job_id'],recovery_authority=no_launch_authority)
        journal.append('DIAGNOSTIC',dispatch)
        runner=LifecycleRunner(store,job_factory=job_factory,on_launch=on_launch,on_finish=on_finish)
        try:
            job=runner.submit(intent)
            if runner.thread is not None:runner.thread.join(p.hard_seconds+p.cleanup_seconds+5)
            job=store.job(job['job_id']);terminal,cp,elapsed=validate_settled_parent(store,job)
            if physical_storage(p):
                from .lifetime_physical_storage import seal_for_job
                seal_for_job(store,job)
            journal.append('DIAGNOSTIC_SETTLED',dict(job_id=job['job_id'],clock=cp['clock'],terminal=terminal,checkpoint_sha256=cp['sha256'],observed_seconds=elapsed))
            return job
        finally:_close_session(store,runner)


def reconcile_no_launch(directory,job_id,proof_sha256):
    """Explicitly close one proved no-start DISPATCH; return no science/credit."""
    from .lifetime_no_launch import validate,digest,dispositions,DISPOSITION
    from .project_store import identifier
    identifier(job_id);identifier(proof_sha256,revision=True)
    store,plan=_store(directory)
    try:
        with _lock(store):
            job=store.job(job_id);proof=validate(store,job)
            if digest(proof)!=proof_sha256:raise ValueError('YEAR-V3 expected proof SHA mismatch')
            journal=Journal(store,plan);old=dispositions(store,list(journal.records()))
            if job_id in old:return old[job_id]
            data=dict(format=DISPOSITION,job_id=job_id,proof_sha256=proof_sha256,scientific_authority=False)
            journal.append('NO_LAUNCH_DISPOSITION',data)
            return data
    finally:_close_session(store)


def authorize_no_launch_recovery(directory,job_id,proof_sha256,*,new_key):
    """One explicit prepaid new intent, never reuse/refund a refused job."""
    from .project_store import identifier
    from .lifetime_no_launch import pending_recovery,digest,RECOVERY
    identifier(new_key);identifier(job_id);identifier(proof_sha256,revision=True)
    store,plan=_store(directory)
    try:
        with _lock(store):
            journal=Journal(store,plan);records=list(journal.records());pending=pending_recovery(store,records)
            if set(pending)!={job_id} or pending[job_id]['proof_sha256']!=proof_sha256:
                raise ValueError('YEAR-V3 exact disposed pending refusal required')
            if any(j['intent']['idempotency_key']==new_key for j in store.jobs()):raise ValueError('YEAR-V3 recovery key must be new')
            new_intent=dict(store.job(job_id)['intent'],idempotency_key=new_key)
            from .lifetime_no_launch import digest as intent_digest
            data=dict(format=RECOVERY,job_id=job_id,proof_sha256=proof_sha256,next_key=new_key,intent_sha256=intent_digest(new_intent),maximum_new_intents=1)
            previous=[x for x in records if x['action']=='NO_LAUNCH_RECOVERY'and x['data'].get('job_id')==job_id]
            if previous:
                if len(previous)!=1 or previous[0]['data']!=data:raise ValueError('YEAR-V3 different recovery already authorized')
                return digest(previous[0])
            return digest(journal.append('NO_LAUNCH_RECOVERY',data))
    finally:_close_session(store)
