"""KazEOSat offline server preparation/control candidate. Standard library only.

No provider API, SSH, purchase, upload or installation occurs
in this module. Planning uses the installed B61 strict input owners. Actual model commands are fixed local child entrypoints and
require a coherent Linux runtime with the pinned dependencies and source.
"""
from __future__ import annotations
import argparse,datetime,hashlib,importlib.metadata,json,math,os,platform,re,shutil,subprocess,sys,tempfile,time
from decimal import Decimal,InvalidOperation
from pathlib import Path
from contextlib import contextmanager

YEAR=31557600
MONTH=2592000
FORMAT='B62_B61_SERVER_PLAN_V1'
FORMAT_V2='B63_PREPARED_SERVER_PLAN_V2'
FORMAT_V3='B65_TYPED_SERVER_PLAN_V3'
LIFETIME_METADATA_RESERVE=16384*16384+16*2**20
HERE=Path(__file__).resolve().parent
DEFAULT_ENGINE=HERE.parent
CAP=16*2**20

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')

def digest(data):return hashlib.sha256(data).hexdigest()

def parse(data):
    def unique(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('DUPLICATE_JSON_KEY: '+key)
            out[key]=value
        return out
    return json.loads(data.decode('utf-8-sig'),object_pairs_hook=unique,
        parse_constant=lambda x:(_ for _ in ()).throw(ValueError('NONFINITE_JSON: '+x)))

def read(path,cap=CAP):
    p=Path(path)
    if p.is_symlink() or p.stat().st_size>cap:raise ValueError('FILE_ADMISSION: '+str(p))
    return parse(p.read_bytes())

def write_new(path,value):
    p=Path(path);data=canonical(value)+b'\n'
    if len(data)>CAP:raise ValueError('METADATA_BYTES')
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb')as f:f.write(data);f.flush();os.fsync(f.fileno())

def natural(v,name,low=1,high=2**50):
    if type(v)is not int or not low<=v<=high:raise ValueError('EXACT_INTEGER: '+name)
    return v

def decimal(v,name,zero=False):
    try:d=Decimal(str(v))
    except InvalidOperation as e:raise ValueError(name)from e
    if not d.is_finite() or d<0 or not zero and d==0:raise ValueError('POSITIVE_DECIMAL: '+name)
    return d

def source_manifest(engine):
    root=Path(engine).resolve();out={}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():raise ValueError('SOURCE_SYMLINK')
        if not p.is_file():continue
        relative=p.relative_to(root).as_posix()
        if '.git' in p.relative_to(root).parts or '__pycache__' in p.relative_to(root).parts:
            raise ValueError('SOURCE_UNDECLARED_CACHE_OR_GIT')
        if len(out)>=2000 or p.stat().st_size>16*2**20:raise ValueError('SOURCE_QUOTA')
        b=p.read_bytes();out[relative]={'bytes':len(b),'sha256':digest(b)}
    if not out or 'm8_lifetime_campaign_cli.py'not in out:raise ValueError('LIFETIME_ENGINE_NOT_PRESENT')
    return out

def requirement_pins(engine):
    b=(Path(engine)/'requirements.txt').read_bytes()
    text=b.decode('utf-16')if b.startswith((b'\xff\xfe',b'\xfe\xff'))else b.decode('utf-8-sig')
    pins={}
    for row in text.splitlines():
        row=row.strip()
        if not row or row.startswith('#'):continue
        m=re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)',row)
        if not m or m[1].lower()in pins:raise ValueError('EXACT_REQUIREMENT_PIN_REQUIRED')
        pins[m[1].lower()]=m[2]
    if not pins or len(pins)>128:raise ValueError('REQUIREMENT_COUNT')
    return pins

def proc_identity():
    if not sys.platform.startswith('linux'):return {'available':False,'coherent':False,'reason':'LINUX_REQUIRED'}
    try:
        text=Path('/proc/self/stat').read_text('ascii');end=text.rfind(')')
        pid=int(text[:text.index(' ')]);fields=text[end+2:].split()
        current={'pid':os.getpid(),'ppid':os.getppid(),'pgrp':os.getpgrp(),'session':os.getsid(0)}
        proc={'pid':pid,'ppid':int(fields[1]),'pgrp':int(fields[2]),'session':int(fields[3])}
        return {'available':True,'coherent':current==proc,'runtime':current,'proc':proc}
    except (OSError,ValueError,IndexError)as e:return {'available':False,'coherent':False,'reason':repr(e)}

def doctor(engine,expected=None):
    engine=Path(engine).resolve();actual=source_manifest(engine);identity=proc_identity();pins=requirement_pins(engine)
    distributions={};dependencies=True
    for name,version in pins.items():
        try:observed=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:observed=None
        distributions[name]={'expected':version,'observed':observed,'match':observed==version};dependencies&=observed==version
    checks={'linux':sys.platform.startswith('linux'),'coherent_procfs':identity['coherent'],
        'python_major_minor':sys.version_info[:2]==(3,14),'exact_dependencies':dependencies,
        'source_matches':expected is None or actual==expected}
    return {'format':'KAZEOSAT_SERVER_DOCTOR_V1','ready_for_engine_attempt':all(checks.values()),
        'checks':checks,'runtime':{'python':sys.version,'platform':sys.platform,'executable':sys.executable},
        'proc_identity':identity,'dependencies':distributions,'source_manifest_sha256':digest(canonical(actual)),
        'science_executed':False,'long_horizon_qualification':False}

def estimate(*,years,designs,parallel,rate,setup='0',sample_sim_seconds=MONTH,sample_wall_seconds='7304.2479725',speedup='1'):
    natural(years,'years',1,15);natural(designs,'designs',1,128);natural(parallel,'parallel',1,128)
    natural(sample_sim_seconds,'sample simulation seconds')
    factor=decimal(speedup,'scenario speedup');hourly=decimal(rate,'hourly rate');initial=decimal(setup,'setup',True)
    per=decimal(sample_wall_seconds,'positive measured wall seconds')*Decimal(years*YEAR)/Decimal(sample_sim_seconds)/factor/Decimal(3600)
    waves=math.ceil(designs/parallel);wall=per*waves
    return {'format':'KAZEOSAT_CONDITIONAL_COST_SCENARIO_V1','years':years,'designs':designs,'parallel':parallel,
        'assumed_speedup':str(factor),'process_hours_per_design':str(per),'total_process_hours':str(per*designs),
        'ideal_wave_count':waves,'ideal_wall_hours':str(wall),'linear_hourly_machine_cost':str(wall*hourly+initial),
        'assumptions':['Linear work density and no ageing/controller cost growth are unverified.',
            'Equal per-process throughput at requested concurrency is unverified.',
            'Price excludes tax, storage/IP/backup/network, idle/setup elapsed, and monthly caps.',
            'This is not a completion forecast, quote, lifetime simulation or provider charge limit.']}


def owners(engine):
    engine=Path(engine).resolve()
    if engine!=HERE.parent:raise ValueError('B62 installed engine/kit must be one immutable package')
    if str(engine)not in sys.path:sys.path.insert(0,str(engine))
    from ops_sim.v5 import lifetime_supervisor as supervisor
    return supervisor


def _execution_contract(root,engine,strategy,*,backend,build):
    from ops_sim.v5.lifecycle_backend import TYPED_SELECTIONS,ALL_SELECTIONS
    if type(backend)is not str or backend not in ALL_SELECTIONS:raise ValueError('B65 exact server backend')
    if backend in TYPED_SELECTIONS:
        from ops_sim.v5.lifetime_typed_portable import execution_contract_v3
        return execution_contract_v3(root,engine,strategy,backend=backend,build=build)
    from ops_sim.v5.lifetime_portable import execution_contract_v2
    return execution_contract_v2(root,engine,strategy,backend=backend,build=build)

def _accounted_input(raw):
    from ops_sim.v5.lifetime_admission import _initial,derive_accounting,ACCOUNTING,resource_plan
    root,document,canonical_raw=_initial(raw)
    if root.policy.method==ACCOUNTING:
        return root,canonical_raw,dict(format='B65_ALREADY_BOUND_ACCOUNTING_INPUT_V1',input_sha256=digest(canonical_raw),
            changed_fields=[],physical_fields='UNCHANGED',resource_plan=resource_plan(root))
    return derive_accounting(raw)

def typed_capability(engine,build):
    owners(engine)
    from ops_sim.v5.lifecycle_typed_platform import admit_build_data,admit_typed_build,LINUX,METHOD
    receipt=admit_build_data(build);module=admit_typed_build(receipt,source=engine)
    baseline=doctor(engine)
    return dict(format='B65_TYPED_SERVER_CAPABILITY_V1',backend=METHOD,profile=receipt['profile'],
        source_manifest_sha256=baseline['source_manifest_sha256'],runtime=receipt['runtime'],
        build_sha256=digest(canonical(receipt)),artifact=receipt['artifact'],caps=receipt['capabilities']['limits'],
        current_native_entry_counts=module.native_entry_counts(),doctor=baseline,
        ready_for_pilot=baseline['ready_for_engine_attempt']and receipt['profile']==LINUX,
        long_dispatch=False,long_requires='PER_DESIGN_GENUINE_TARGET_DAY_REFERENCE_AND_NATIVE_CONTINUATION_EVIDENCE',
        checkpoint_migration=False,physical_qualification=False)

def make_plan(engine,input_path,plan_path,*,seconds,policy,rate,currency,max_cost,setup='0',mode='pilot',backend='REFERENCE',build=None,acceptance=None):
    from dataclasses import asdict
    owners(engine)
    from ops_sim.v5.lifetime_admission import derive_duration,derive_accounting
    from ops_sim.v5.lifetime_policy import admit_policy,is_v2
    policy=admit_policy(policy);engine=Path(engine).resolve();p=Path(plan_path).absolute()
    if p.exists()or p.resolve().is_relative_to(engine):raise ValueError('B62 new external plan required')
    if mode not in('pilot','long')or seconds>MONTH and mode!='long':raise ValueError('B62 explicit long mode required')
    hourly=decimal(rate,'hourly rate');budget=decimal(max_cost,'estimate budget');initial=decimal(setup,'setup',True)
    if not re.fullmatch('[A-Z]{3}',currency):raise ValueError('B62 currency')
    wall=policy.maximum_observed_primary_seconds+policy.maximum_diagnostic_seconds
    if Decimal(wall)/3600*hourly+initial>budget:raise ValueError('B62 declared compute scenario exceeds operator estimate')
    raw=Path(input_path).read_bytes();_,duration,derivation=derive_duration(raw,seconds)
    root,actual,accounting=_accounted_input(duration)
    execution=None;contract=None
    if is_v2(policy):
        from ops_sim.v5.lifetime_portable import execution_contract_v2
        from ops_sim.v5.lifetime_execution_authority import make_authority
        contract=_execution_contract(root,engine,'B60_SEALED_STATIC_V1',backend=backend,build=build)
        # Complete permission admission precedes any plan/input/store/pool write.
        execution=make_authority(root,actual,contract,policy,mode=mode.upper(),backend=backend,build=build,acceptance=acceptance)
    elif backend!='REFERENCE'or build is not None or acceptance is not None:
        raise ValueError('B63 backend/acceptance requires explicit new policy and plan')
    source=source_manifest(engine)
    if contract is not None and canonical(source)!=canonical(contract['source_manifest']):raise ValueError('B63 source changed during immutable plan admission')
    p.parent.mkdir(parents=True,exist_ok=True)
    names={'original':p.stem+'.original.json','duration':p.stem+'.duration.json','initial':p.stem+'.initial.json'}
    for name,data in ((names['original'],raw),(names['duration'],duration),(names['initial'],actual)):
        with (p.parent/name).open('xb')as f:f.write(data);f.flush();os.fsync(f.fileno())
    value=dict(format=FORMAT_V3 if backend in('B64_TYPED_EXECUTION_V1','B64_TYPED_COUPLED_LEGACY_QUIET_CONTROL_V1','B65_TYPED_EXECUTION_V2')else FORMAT_V2 if is_v2(policy)else FORMAT,mode=mode,duration_seconds=seconds,root_identity=root.identity,
        original_input=names['original'],duration_input=names['duration'],input_file=names['initial'],
        original_sha256=digest(raw),duration_sha256=digest(duration),input_sha256=digest(actual),
        duration_derivation=derivation,accounting_derivation=accounting,policy=asdict(policy),policy_identity=policy.identity,
        source_manifest=source,source_manifest_sha256=digest(canonical(source)),
        preparation_runtime=dict(python=sys.version,platform=sys.platform),
        prospective_store_reservation_bytes=policy.maximum_reserved_job_output_bytes,
        shared_pool_reservation_including_backup_bytes=policy.pool_commitment_bytes,
        cost_scenario=dict(currency=currency,rate_per_machine_hour=str(hourly),setup=str(initial),maximum_estimated_compute_cost=str(budget),
            maximum_declared_seconds=wall,billing_warning='NOT_A_PROVIDER_CAP; Stop does not cancel rental. Disk, backups, idle, tax and transfer are extra.'),
        native_import=False,qualification='SERVER_ACCEPTANCE_PENDING',engine_entrypoint='m8_lifetime_campaign_cli.py')
    if is_v2(policy):value.update(backend=backend,native_build=build,execution_mode=mode.upper(),
        execution_authority=execution,execution_contract_sha256=digest(canonical(contract)))
    value['plan_identity']=digest(canonical(value));write_new(p,value);return value

def load_plan(path,engine):
    owners(engine);path=Path(path).absolute();v=read(path)
    expected={'format','mode','duration_seconds','root_identity','original_input','duration_input','input_file','original_sha256','duration_sha256','input_sha256','duration_derivation','accounting_derivation','policy','policy_identity','source_manifest','source_manifest_sha256','preparation_runtime','prospective_store_reservation_bytes','shared_pool_reservation_including_backup_bytes','cost_scenario','native_import','qualification','engine_entrypoint','plan_identity'}
    new=type(v)is dict and v.get('format')in(FORMAT_V2,FORMAT_V3)
    if new:expected|={'backend','native_build','execution_mode','execution_authority','execution_contract_sha256'}
    if type(v)is not dict or set(v)!=expected or v['format']not in(FORMAT,FORMAT_V2,FORMAT_V3) or v['native_import']is not False or v['engine_entrypoint']!='m8_lifetime_campaign_cli.py':raise ValueError('B62/B63 strict versioned server plan')
    if type(v['mode'])is not str or v['mode']not in('pilot','long'):raise ValueError('B63 exact server planning mode')
    natural(v['duration_seconds'],'plan duration',1,15*YEAR)
    if path.resolve().is_relative_to(Path(engine).resolve()):raise ValueError('B62 plan inside source')
    if v['plan_identity']!=digest(canonical({k:x for k,x in v.items()if k!='plan_identity'})):raise ValueError('B62 plan digest')
    if source_manifest(engine)!=v['source_manifest']or digest(canonical(v['source_manifest']))!=v['source_manifest_sha256']:raise ValueError('B62 frozen source drift')
    from ops_sim.v5.lifetime_policy import admit_policy,is_v2
    from ops_sim.v5.lifetime_admission import derive_duration,derive_accounting
    p=admit_policy(v['policy'])
    for name,key in (('original_input','original_sha256'),('duration_input','duration_sha256'),('input_file','input_sha256')):
        if type(v[name])is not str or Path(v[name]).name!=v[name]or any(c in v[name]for c in ('\\',':'))or v[name]in('.','..'):raise ValueError('B62 plan input path')
        if digest((path.parent/v[name]).read_bytes())!=v[key]:raise ValueError('B62 plan input raw drift')
    _,duration,proof=derive_duration((path.parent/v['original_input']).read_bytes(),v['duration_seconds'])
    root,actual,accounting=_accounted_input(duration)
    if duration!=(path.parent/v['duration_input']).read_bytes()or actual!=(path.parent/v['input_file']).read_bytes()or proof!=v['duration_derivation']or accounting!=v['accounting_derivation']or root.identity!=v['root_identity']:raise ValueError('B62 owner derivation binding')
    if p.identity!=v['policy_identity']or p.maximum_reserved_job_output_bytes!=v['prospective_store_reservation_bytes']or p.pool_commitment_bytes!=v['shared_pool_reservation_including_backup_bytes']:raise ValueError('B62 prospective policy drift')
    if new!=is_v2(p):raise ValueError('B63 explicit plan/policy version binding')
    if new:
        from ops_sim.v5.lifecycle_backend import TYPED_SELECTIONS
        if (v['format']==FORMAT_V3)!=(v['backend']in TYPED_SELECTIONS):raise ValueError('B65 server plan/backend family mismatch')
        from ops_sim.v5.lifetime_portable import execution_contract_v2
        from ops_sim.v5.lifetime_execution_authority import admit_authority_data,_binding
        contract=_execution_contract(root,engine,'B60_SEALED_STATIC_V1',backend=v['backend'],build=v['native_build'])
        authority=admit_authority_data(v['execution_authority'])
        expected_binding=_binding(root,actual,contract,p,v['backend'],v['native_build'])
        if (v['execution_mode']!=v['mode'].upper()or authority['mode']!=v['execution_mode']
                or canonical(authority['binding'])!=canonical(expected_binding)
                or v['execution_contract_sha256']!=digest(canonical(contract))):raise ValueError('B63 strict planning authority/context binding')
    if v['preparation_runtime']!=dict(python=sys.version,platform=sys.platform):raise ValueError('B62 prepare plan on target runtime; native migration forbidden')
    cost=v['cost_scenario']
    if type(cost)is not dict or set(cost)!={'currency','rate_per_machine_hour','setup','maximum_estimated_compute_cost','maximum_declared_seconds','billing_warning'}:raise ValueError('B62 cost scenario schema')
    wall=p.maximum_observed_primary_seconds+p.maximum_diagnostic_seconds
    if type(cost['maximum_declared_seconds'])is not int or cost['maximum_declared_seconds']!=wall or Decimal(wall)/3600*decimal(cost['rate_per_machine_hour'],'rate')+decimal(cost['setup'],'setup',True)>decimal(cost['maximum_estimated_compute_cost'],'cost'):raise ValueError('B62 cost/time binding')
    return v

def bound_store(path,plan,engine):
    supervisor=owners(engine);path=Path(path).absolute();directory=path.parent/(path.stem+'.store')
    store,lifetime=supervisor._store(directory)
    from dataclasses import asdict
    if store.meta['input_sha256']!=plan['input_sha256']or store.root_input.identity!=plan['root_identity']or asdict(store.runner_policy)!=plan['policy']:raise ValueError('B62 foreign store/input/policy')
    contract=read(store.path('portable-execution.json'))
    if contract['source_manifest_sha256']!=plan['source_manifest_sha256']:raise ValueError('B62 foreign store/source')
    if plan['format']in(FORMAT_V2,FORMAT_V3):
        if (digest(canonical(contract))!=plan['execution_contract_sha256']
                or store.meta.get('execution_authority_sha256')!=digest(canonical(plan['execution_authority']))):raise ValueError('B63 foreign store/backend/authority')
    store.close_publications();return directory

def run_plan(path,engine,*,resume=False):
    supervisor=owners(engine);v=load_plan(path,engine)
    from ops_sim.v5.lifetime_policy import admit_policy,PRODUCTION,is_v2
    policy=admit_policy(v['policy'])
    if is_v2(policy):
        from ops_sim.v5.lifecycle_document import loads_root
        from ops_sim.v5.lifetime_portable import execution_contract_v2
        from ops_sim.v5.lifetime_execution_authority import admit_authority
        raw=(Path(path).absolute().parent/v['input_file']).read_bytes();root=loads_root(raw)
        contract=_execution_contract(root,engine,'B60_SEALED_STATIC_V1',backend=v['backend'],build=v['native_build'])
        admit_authority(v['execution_authority'],root,raw,contract,policy,backend=v['backend'],build=v['native_build'])
    else:
        from ops_sim.v5.lifetime_execution_authority import PILOT_SECONDS,PILOT_PRIMARY_SEGMENTS,PILOT_DIAGNOSTIC_SLOTS,PILOT_HARD_SECONDS
        if (v['duration_seconds']>PILOT_SECONDS or policy.maximum_primary_segments>PILOT_PRIMARY_SEGMENTS
                or policy.reserved_diagnostic_slots>PILOT_DIAGNOSTIC_SLOTS or policy.hard_seconds>PILOT_HARD_SECONDS):raise ValueError('B63 historical server plan has no qualified long execution authority')
    d=doctor(engine,v['source_manifest'])
    if not d['ready_for_engine_attempt']:raise ValueError('B62 actual Linux doctor failed: '+json.dumps(d['checks']))
    from ops_sim.v5.lifetime_journal import lease
    if policy.mode!=PRODUCTION:raise ValueError('B62 serverctl production does not promote local qualification')
    if v['mode']=='long'and not is_v2(policy):
        from ops_sim.v5.lifetime_server_acceptance import admit_acceptance
        admit_acceptance(Path(path).parent/'SERVER-PILOT-PASS.json',v['source_manifest_sha256'])
    path=Path(path).absolute();directory=path.parent/(path.stem+'.store')
    with lease(path.with_suffix('.run.lock')):
        if not directory.exists():
            if resume:raise ValueError('B62 no store to resume')
            supervisor.prepare(path.parent/v['input_file'],directory,policy,
                backend=v.get('backend','REFERENCE'),build=v.get('native_build'),
                execution_mode=v.get('execution_mode','PILOT'),acceptance=None if not is_v2(policy)else v['execution_authority']['acceptance'])
        bound_store(path,v,engine)
        result=supervisor.run(directory,explicit_continue=resume)
        return dict(store=str(directory),result=result,billing_still_active=True)

def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--engine',type=Path,default=DEFAULT_ENGINE);sub=a.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    p=sub.add_parser('typed-capability');p.add_argument('--build',required=True,type=Path)
    p=sub.add_parser('qualify-protocol');p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('estimate');p.add_argument('--years',type=int,default=15);p.add_argument('--designs',type=int,default=1);p.add_argument('--parallel',type=int,default=1);p.add_argument('--rate',required=True);p.add_argument('--setup',default='0');p.add_argument('--speedup',default='1')
    p=sub.add_parser('plan');p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=int,required=True);p.add_argument('--policy',type=Path,required=True);p.add_argument('--rate',required=True);p.add_argument('--currency',default='USD');p.add_argument('--max-cost',required=True);p.add_argument('--setup',default='0');p.add_argument('--mode',choices=('pilot','long'),default='pilot')
    p.add_argument('--backend',choices=('REFERENCE','PREPARED_PYTHON','PREPARED_NATIVE','B64_TYPED_EXECUTION_V1','B64_TYPED_COUPLED_LEGACY_QUIET_CONTROL_V1','B65_TYPED_EXECUTION_V2'),default='REFERENCE');p.add_argument('--build',type=Path);p.add_argument('--acceptance',type=Path)
    for name in ('run','resume','status','stop','export-result','diagnostic'):
        p=sub.add_parser(name);p.add_argument('--plan',type=Path,required=True)
        if name=='export-result':p.add_argument('--output',type=Path,required=True)
        if name=='diagnostic':p.add_argument('--parent-job-id',required=True);p.add_argument('--checkpoint-sha256',required=True);p.add_argument('--verbose',action='store_true')
    p=sub.add_parser('inspect-result');p.add_argument('--input',type=Path,required=True)
    v=a.parse_args(argv)
    if v.command=='doctor':result=doctor(v.engine)
    elif v.command=='typed-capability':result=typed_capability(v.engine,read(v.build,65536))
    elif v.command=='qualify-protocol':
        owners(v.engine)
        from ops_sim.v5.lifetime_server_acceptance import run_protocol
        result=run_protocol(v.output)
    elif v.command=='estimate':result=estimate(years=v.years,designs=v.designs,parallel=v.parallel,rate=v.rate,setup=v.setup,speedup=v.speedup)
    elif v.command=='plan':
        owners(v.engine)
        from ops_sim.v5.lifetime_execution_authority import reference
        result=make_plan(v.engine,v.input,v.output,seconds=v.seconds,policy=read(v.policy),rate=v.rate,currency=v.currency,max_cost=v.max_cost,setup=v.setup,mode=v.mode,
            backend=v.backend,build=None if v.build is None else read(v.build,65536),acceptance=None if v.acceptance is None else reference(v.acceptance))
    elif v.command in('run','resume'):result=run_plan(v.plan,v.engine,resume=v.command=='resume')
    elif v.command=='inspect-result':
        owners(v.engine)
        from ops_sim.v5.lifetime_result import inspect_result
        result=inspect_result(v.input)
    else:
        plan=load_plan(v.plan,v.engine);directory=bound_store(v.plan,plan,v.engine);supervisor=owners(v.engine)
        if v.command=='export-result':result=supervisor.export_result(directory,v.output)
        elif v.command=='diagnostic':result=supervisor.diagnostic(directory,v.parent_job_id,v.checkpoint_sha256,verbose=v.verbose)
        else:
            store,p=supervisor._store(directory)
            try:
                if v.command=='stop':
                    from ops_sim.v5.lifetime_journal import publish
                    marker=store.path('operator-pause.json')
                    if not marker.exists():publish(marker,dict(plan_identity=p['plan_identity']),16384)
                    elif read(marker).get('plan_identity')!=p['plan_identity']:raise ValueError('B62 foreign pause')
                result=supervisor._summary(store,p)
            finally:store.close_publications()
    print(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2));return result

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,RuntimeError)as error:
        print(json.dumps(dict(status='REFUSED_OR_FAILED',reason=str(error),completion_not_established=True),ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
