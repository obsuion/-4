"""Strict bounded data-only result, never a native continuation authority."""
from pathlib import Path
from hashlib import sha256
import stat,zipfile,struct
from .portable_job import canonical,digest,safe,parse,identity

FORMAT='B62_READ_ONLY_LIFETIME_RESULT_V1'
FORMAT_V2='B63_READ_ONLY_PREPARED_LIFETIME_RESULT_V2'
FORMAT_V3='B64_READ_ONLY_TYPED_LIFETIME_RESULT_V3'
FORMAT_V4='B65_READ_ONLY_TYPED_LIFETIME_RESULT_V4'
FORMAT_V5='YEAR_V3_READ_ONLY_NO_LAUNCH_LIFETIME_RESULT_V5'
FORMAT_V6='YEAR_V4_READ_ONLY_BOUNDED_PHYSICAL_LIFETIME_RESULT_V6'
FORMAT_V7='YEAR_V5_READ_ONLY_PACKED_SHORT_CIRCUIT_RESULT_V7'
MAX_BYTES=512*2**20
MAX_FILES=16384
MAX_MANIFEST=8*2**20
FIELDS={'format','root_identity','input_sha256','source_manifest_sha256','execution_contract_sha256','plan_identity','requested_end_seconds','actual_end_seconds','read_only','native_execution_rights','backup_required_for_resume','primary_totals','monthly_environment','monthly_actual','cumulative_work','jobs','scope'}

def _view(v):
    modern=type(v)is dict and v.get('format')in(FORMAT_V2,FORMAT_V3,FORMAT_V4,FORMAT_V5,FORMAT_V6,FORMAT_V7)
    expected=(FIELDS|({'administrative_dispositions'}if type(v)is dict and v.get('format')in(FORMAT_V5,FORMAT_V6,FORMAT_V7) else set()))|({'execution_authority_sha256','backend_binding'}if modern else set())
    if type(v)is not dict or set(v)!=expected or v['format']not in(FORMAT,FORMAT_V2,FORMAT_V3,FORMAT_V4,FORMAT_V5,FORMAT_V6,FORMAT_V7) or v['read_only']is not True or v['native_execution_rights']is not False or v['backup_required_for_resume']is not True:raise ValueError('B62/B63/B64 exact read-only result schema')
    if modern:
        from .lifetime_execution_authority import _admit_backend_binding,BACKEND_FORMAT,TYPED_BACKEND_FORMAT,TYPED_BACKEND_FORMAT_V2
        identity(v['execution_authority_sha256']);_admit_backend_binding(v['backend_binding'])
        if v['format']not in(FORMAT_V6,FORMAT_V7) and v['backend_binding']['format']!=(TYPED_BACKEND_FORMAT_V2 if v['format']in(FORMAT_V4,FORMAT_V5) else TYPED_BACKEND_FORMAT if v['format']==FORMAT_V3 else BACKEND_FORMAT):raise ValueError('read-only result/backend format family mismatch')
    for k in ('root_identity','input_sha256','source_manifest_sha256','execution_contract_sha256','plan_identity'):identity(v[k])
    if type(v['jobs'])is not list or len(v['jobs'])>8200 or type(v['monthly_environment'])is not list or len(v['monthly_environment'])>185 or type(v['monthly_actual'])is not list or len(v['monthly_actual'])>185:raise ValueError('B62 result population')
    if type(v['requested_end_seconds'])is not int or type(v['actual_end_seconds'])is not int or not 0<=v['actual_end_seconds']<=v['requested_end_seconds']:raise ValueError('B62 actual prefix')
    from .lifecycle_report import ROW_FIELDS,COUNTS
    previous=None
    for row in v['monthly_actual']:
        expected=ROW_FIELDS|{'power_service','solar_attitude','battery_port','lifetime_environment'}
        if type(row)is not dict or set(row)!=expected:raise ValueError('B62 monthly actual exact fields')
        a=row['start_seconds'];b=row['end_seconds']
        if type(a)is not int or type(b)is not int or not 0<=a<=b<=v['actual_end_seconds']or previous is not None and a!=previous:raise ValueError('B62 monthly actual support')
        if any(type(row[k])is not int or row[k]<0 for k in COUNTS):raise ValueError('B62 actual monthly counts')
        if row['lifetime_environment']is not None:
            e=row['lifetime_environment']
            if type(e)is not dict or set(e)!={'start_seconds','end_seconds','environment','paid_work_start','paid_work_end'}or e['start_seconds']!=a or e['end_seconds']!=b:raise ValueError('B62 monthly selected environment support')
        previous=b
    if [r['lifetime_environment']for r in v['monthly_actual']if r['lifetime_environment']is not None]!=v['monthly_environment']:raise ValueError('B62 environment/actual monthly binding')
    seen=set()
    for j in v['jobs']:
        if type(j)is not dict or set(j)!={'job_id','role','status','terminal','clock','scientific_file','scientific_sha256'}or j['role']not in('PRIMARY','DIAGNOSTIC'):raise ValueError('B62 result job schema')
        jid=j['job_id']
        if type(jid)is not str or len(jid)!=32 or any(c not in '0123456789abcdef'for c in jid)or jid in seen:raise ValueError('B62 result job identity')
        seen.add(jid)
        if j['status']not in('COMPLETED','INCOMPLETE','CANCELLED','REFUSED','PROCESS_FAILED','UNKNOWN'):raise ValueError('B62 result unsettled job')
        from .battery_terminal import admit_terminal
        terminal=None if j['terminal']is None else admit_terminal(j['terminal'])
        if j['scientific_file']is not None:
            if safe(j['scientific_file'])!='scientific/'+jid+'.json':raise ValueError('B62 scientific path')
            identity(j['scientific_sha256'])
            if type(j['clock'])is not int or not 0<=j['clock']<=v['actual_end_seconds']or terminal is None or terminal['clock']!=j['clock']:raise ValueError('B62 scientific/terminal clock binding')
            if j['role']=='PRIMARY'and terminal['kind']=='TARGET'and j['clock']!=v['requested_end_seconds']:raise ValueError('B62 primary target binding')
        elif j['scientific_sha256']is not None:raise ValueError('B62 absent scientific hash')
        elif j['clock']is not None or terminal is not None and terminal['kind']not in('UNKNOWN','PROCESS_FAILURE'):raise ValueError('B62 missing scientific prefix cannot claim coverage')
    if v['format']in(FORMAT_V5,FORMAT_V6,FORMAT_V7):
        _admit_administrative_view(v)
    if v['scope']!='LATEST_FORWARD_PRIMARY_ACTUAL_PREFIX_DIAGNOSTICS_NEVER_ADDED':raise ValueError('B62 credit scope')
    return v

def export_result(store,plan,path,*,sink_factory=None,maximum_bytes=MAX_BYTES):
    from .lifetime_supervisor import _summary
    from .finite_campaign import intent_role
    from .lifetime_reporting import rows
    from .lifetime_policy import is_v2,physical_storage,packed_storage
    modern=is_v2(store.runner_policy)
    out=Path(path).absolute()
    if type(maximum_bytes)is not int or not 22<=maximum_bytes<=MAX_BYTES:raise ValueError('finite result export byte allowance')
    if out.exists()or out.resolve().is_relative_to(store.directory)or out.resolve().is_relative_to(Path(__file__).resolve().parents[2]):raise ValueError('B62 new external export required')
    monthly=[]
    index=store.jobs();byid={j['job_id']:j for j in index};summary=_summary(store,plan);tip=summary['parent_job_id'];latest=None
    c=parse(store.path('portable-execution.json').read_bytes())
    from .lifetime_typed_portable import FORMAT_V3 as TYPED_CONTRACT,FORMAT_V4 as TYPED_CONTRACT_V4
    typed=c.get('format')in(TYPED_CONTRACT,TYPED_CONTRACT_V4)
    if typed and not modern:raise ValueError('B64 typed result requires explicit new lifetime store policy')
    payload={'input.json':store.path('input.json').read_bytes(),'execution-contract.json':canonical(c),'plan.json':canonical(plan)};records=[]
    if sum(map(len,payload.values()))+MAX_MANIFEST>maximum_bytes:raise ValueError('prospective result initial payload cap')
    for item in index:
        j=store.job(item['job_id'])
        if j['status']not in('COMPLETED','INCOMPLETE','CANCELLED','REFUSED','PROCESS_FAILED','UNKNOWN'):raise ValueError('B62 export requires settled store')
        role=intent_role(j['intent'],byid.get(j['intent']['parent_job_id']),None if j['resume']is None else j['resume']['checkpoint'],store.root_input.end_seconds)
        name=h=clock=None
        if j['result']is not None:
            e=j['result']['endpoint'];raw=store.path('jobs',j['job_id'],e['file']).read_bytes()
            if digest(raw)!=e['sha256']:raise ValueError('B62 actual scientific hash')
            if sum(map(len,payload.values()))+len(raw)+MAX_MANIFEST>maximum_bytes:raise ValueError('prospective result scientific payload cap')
            name='scientific/'+j['job_id']+'.json';payload[name]=raw;h=digest(raw);clock=j['result']['clock']
            if j['job_id']==tip:latest=j['result']
        if role=='PRIMARY' and j['result']is not None:
            from .lifecycle_stream import iter_stream_records
            monthly.extend(iter_stream_records(store.path('jobs',j['job_id'],'months53'),policy=store.root_input.output_policy))
        records.append(dict(job_id=j['job_id'],role=role,status=j['status'],terminal=j.get('typed_stop'),clock=clock,scientific_file=name,scientific_sha256=h))
        store._cache.pop(j['job_id'],None)
    report=None if latest is None else latest['report']
    scientific_work=None
    if latest is not None:
        from .design_repair_study import _plain_output
        scientific_work=_plain_output(parse(payload['scientific/'+tip+'.json']))['work']
    monthly.sort(key=lambda row:(row['start_seconds'],row['end_seconds']))
    if latest is not None and latest.get('partial_terminal_report')is not None:
        binding=latest['partial_terminal_report'];partial=parse(store.path('jobs',tip,binding['file']).read_bytes())
        if digest(store.path('jobs',tip,binding['file']).read_bytes())!=binding['sha256']:raise ValueError('B62 partial report raw binding')
        if partial['row']is not None:monthly.append(partial['row'])
    if len(monthly)>185:raise ValueError('B62 bounded monthly actual rows')
    from .lifetime_no_launch import enabled,dispositions,validate
    from .lifetime_journal import Journal
    administrative=[]
    if enabled(store.runner_policy):
        for jid,data in dispositions(store,list(Journal(store,plan).records())).items():
            administrative.append(dict(disposition=data,proof=validate(store,store.job(jid))))
    v=dict(format=FORMAT_V7 if packed_storage(store.runner_policy)else FORMAT_V6 if physical_storage(store.runner_policy)else FORMAT_V5 if enabled(store.runner_policy)else FORMAT_V4 if c.get('format')==TYPED_CONTRACT_V4 else FORMAT_V3 if typed else FORMAT_V2 if modern else FORMAT,root_identity=store.root_input.identity,input_sha256=store.meta['input_sha256'],source_manifest_sha256=c['source_manifest_sha256'],execution_contract_sha256=digest(canonical(c)),plan_identity=plan['plan_identity'],requested_end_seconds=store.root_input.end_seconds,actual_end_seconds=summary['clock'],read_only=True,native_execution_rights=False,backup_required_for_resume=True,primary_totals=None if report is None else report['totals'],monthly_environment=[x['lifetime_environment']for x in monthly if x.get('lifetime_environment')is not None],monthly_actual=monthly,cumulative_work=scientific_work,jobs=records,scope='LATEST_FORWARD_PRIMARY_ACTUAL_PREFIX_DIAGNOSTICS_NEVER_ADDED')
    if modern:
        authority=store.path('execution-authority.json');raw=authority.read_bytes()
        if authority.is_symlink()or len(raw)>16384 or digest(raw)!=store.meta['execution_authority_sha256']:
            raise ValueError('B63 read-only export authority pin')
        payload['execution-authority.json']=raw
        v.update(execution_authority_sha256=digest(raw),backend_binding=c['backend_binding'])
    if enabled(store.runner_policy):v['administrative_dispositions']=administrative
    _view(v);payload['view.json']=canonical(v)
    if len(payload)+1>MAX_FILES or sum(map(len,payload.values()))+MAX_MANIFEST>maximum_bytes:raise ValueError('B62 finite result cap; retain store without deletion')
    m={n:dict(bytes=len(b),sha256=digest(b))for n,b in payload.items()};manifest=canonical(dict(format=v['format'],files=m))
    if len(manifest)>MAX_MANIFEST:raise ValueError('B62 manifest bytes')
    with (out.open('xb')if sink_factory is None else sink_factory(out))as f:
        with zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED)as z:
            z.writestr('MANIFEST.json',manifest)
            for n,b in sorted(payload.items()):z.writestr(n,b)
    inspect_result(out)
    return dict(path=str(out),sha256=digest(out.read_bytes()),native_execution_rights=False,measured_bytes=out.stat().st_size,actual_end_seconds=summary['clock'])

def inspect_result(path):
    p=Path(path)
    if p.is_symlink()or not p.is_file()or not 22<=p.stat().st_size<=MAX_BYTES:raise ValueError('B62 result bytes/link')
    with p.open('rb')as f:
        f.seek(-22,2);sig,disk,sd,n1,n,cd,off,comment=struct.unpack('<4s4H2LH',f.read(22))
        if sig!=b'PK\x05\x06'or disk or sd or n1!=n or comment or not 2<=n<=MAX_FILES or cd>16*2**20 or off+cd!=p.stat().st_size-22:raise ValueError('B62 bounded classic result ZIP')
        # Count and bound real directory records before ZipFile allocates them;
        # an untrusted EOCD count alone is not a population proof.
        f.seek(off)
        for _ in range(n):
            header=f.read(46)
            if len(header)!=46 or header[:4]!=b'PK\x01\x02':raise ValueError('B62 result directory record')
            name,extra,note=struct.unpack_from('<3H',header,28)
            if not 1<=name<=960 or f.tell()+name+extra+note>off+cd:raise ValueError('B62 result directory member bound')
            f.seek(name+extra+note,1)
        if f.tell()!=off+cd:raise ValueError('B62 result actual directory count')
    with zipfile.ZipFile(p)as z:
        names=set();total=0
        for i in z.infolist():
            safe(i.filename)
            if i.filename.casefold()in names or i.is_dir()or stat.S_ISLNK(i.external_attr>>16)or i.flag_bits&1 or i.file_size>64*2**20:raise ValueError('B62 result member')
            names.add(i.filename.casefold());total+=i.file_size
            if total>MAX_BYTES:raise ValueError('B62 expanded result bytes')
        if z.getinfo('MANIFEST.json').file_size>MAX_MANIFEST:raise ValueError('B62 result manifest cap')
        m=parse(z.read('MANIFEST.json'))
        if type(m)is not dict or set(m)!={'format','files'}or m['format']not in(FORMAT,FORMAT_V2,FORMAT_V3,FORMAT_V4,FORMAT_V5,FORMAT_V6,FORMAT_V7)or type(m['files'])is not dict or set(m['files'])|{'MANIFEST.json'}!=set(z.namelist()):raise ValueError('B62/B63/B64 manifest schema/membership')
        for n,x in m['files'].items():
            if type(x)is not dict or set(x)!={'bytes','sha256'}or type(x['bytes'])is not int or z.getinfo(n).file_size!=x['bytes']:raise ValueError('B62 manifest size')
            identity(x['sha256']);h=sha256()
            with z.open(n)as f:
                for b in iter(lambda:f.read(2**20),b''):h.update(b)
            if h.hexdigest()!=x['sha256']:raise ValueError('B62 result hash')
        if not {'view.json','input.json','execution-contract.json','plan.json'}<=set(m['files']):raise ValueError('B62 result authorities')
        if m['format']in(FORMAT_V2,FORMAT_V3,FORMAT_V4,FORMAT_V5,FORMAT_V6,FORMAT_V7):
            caps={'input.json':8*2**20,'execution-contract.json':2**20,'plan.json':65536,'execution-authority.json':16384}
            if any(name not in m['files']or z.getinfo(name).file_size>cap for name,cap in caps.items()):
                raise ValueError('B63 read-only authority metadata before decoding')
        v=_view(parse(z.read('view.json')));c=parse(z.read('execution-contract.json'));plan=parse(z.read('plan.json'))
        modern=v['format']in(FORMAT_V2,FORMAT_V3,FORMAT_V4,FORMAT_V5,FORMAT_V6,FORMAT_V7);typed=v['format']in(FORMAT_V3,FORMAT_V4,FORMAT_V5)
        physical=v['format']in(FORMAT_V6,FORMAT_V7);packed=v['format']==FORMAT_V7
        if physical:typed=c.get('format')in('B64_TYPED_LIFETIME_EXECUTION_CONTRACT_V3','B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4')
        if m['format']!=v['format']:raise ValueError('B63 result manifest/view format binding')
        if type(c)is not dict or type(plan)is not dict:raise ValueError('B62/B63 result typed authorities')
        if modern:
            if typed:
                from .lifetime_typed_portable import admit_execution_contract_data_v3
                admit_execution_contract_data_v3(c)
            else:
                from .lifetime_portable import admit_execution_contract_data_v2
                admit_execution_contract_data_v2(c)
            if z.getinfo('input.json').file_size>8*2**20:raise ValueError('B63 result bounded original input DATA')
        if digest(z.read('input.json'))!=v['input_sha256']or c['input_sha256']!=v['input_sha256']or c['root_identity']!=v['root_identity']or digest(canonical(c))!=v['execution_contract_sha256']or c['source_manifest_sha256']!=v['source_manifest_sha256']or plan['plan_identity']!=v['plan_identity']:raise ValueError('B62 result authority binding')
        required={'format','root_identity','input_sha256','source_identity','runtime','policy','policy_identity','execution_contract_sha256','root_target','original_anchor','automatic_resume','incomplete_is_not_coverage','pool_key','plan_identity'}
        if modern:required|={'execution_authority_sha256','backend_binding','pool_inventory'}
        if physical:required|={'physical_storage_contract','physical_store_name'}
        plan_format='B65_ORIGINAL_ROOT_TYPED_SERIAL_PLAN_V4'if v['format']in(FORMAT_V4,FORMAT_V5) else'B64_ORIGINAL_ROOT_TYPED_SERIAL_PLAN_V3'if typed else'B63_ORIGINAL_ROOT_PREPARED_SERIAL_PLAN_V2'if modern else'B62_ORIGINAL_ROOT_SERIAL_PLAN_V1'
        if physical:plan_format='YEAR_V5_PACKED_TERMINAL_LIFETIME_PLAN_V2'if packed else'YEAR_V4_BOUNDED_PHYSICAL_LIFETIME_PLAN_V1'
        if type(plan)is not dict or set(plan)!=required or plan['format']!=plan_format or plan['plan_identity']!=digest(canonical({k:x for k,x in plan.items()if k!='plan_identity'})):raise ValueError('B62/B63 result exact plan/digest')
        contract_format='B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4'if v['format']in(FORMAT_V4,FORMAT_V5) else'B64_TYPED_LIFETIME_EXECUTION_CONTRACT_V3'if typed else'B63_PREPARED_LIFETIME_EXECUTION_CONTRACT_V2'if modern else'B62_B61_LIFETIME_EXECUTION_CONTRACT_V1'
        if physical:contract_format=('B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4'if c.get('format')=='B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4'else'B64_TYPED_LIFETIME_EXECUTION_CONTRACT_V3'if typed else'B63_PREPARED_LIFETIME_EXECUTION_CONTRACT_V2')
        if c.get('format')!=contract_format or digest(canonical(c['source_manifest']))!=c['source_manifest_sha256']:raise ValueError('B62/B63 result source manifest binding')
        from .portable_job import _admit_manifest
        _admit_manifest(c['source_manifest'])
        if len(c['source_manifest'])>1024 or sum(x['bytes']for x in c['source_manifest'].values())>64*2**20:raise ValueError('B62 result source manifest finite allowance')
        if plan['execution_contract_sha256']!=v['execution_contract_sha256']or plan['root_identity']!=v['root_identity']or plan['input_sha256']!=v['input_sha256']or plan['runtime']!=c['runtime']or type(plan['original_anchor'])is not int or type(plan['root_target'])is not int or plan['root_target']!=v['requested_end_seconds']or not plan['original_anchor']<=v['actual_end_seconds']<=plan['root_target']:raise ValueError('B62 result plan/runtime/horizon binding')
        from .lifetime_policy import admit_policy,is_v2,physical_storage,packed_storage
        policy=admit_policy(plan['policy'])
        if physical_storage(policy)!=physical or packed_storage(policy)!=packed:raise ValueError('YEAR-V4/V5 result/physical policy version binding')
        if physical:
            from .lifetime_physical_storage import contract as physical_contract,digest as physical_digest
            if plan['physical_storage_contract']!=physical_contract(policy):raise ValueError('YEAR-V4 result physical commitment binding')
            expected_key=physical_digest(dict(root_identity=plan['root_identity'],source_identity=plan['source_identity'],input_sha256=plan['input_sha256'],policy_identity=policy.identity,store_name=plan['physical_store_name']))
            if expected_key!=plan['pool_key']:raise ValueError('YEAR-V4 result physical pool owner binding')
        if is_v2(policy)!=modern or policy.identity!=plan['policy_identity']or plan['automatic_resume']!=['RESOURCE_TIME','RESOURCE_OUTPUT']or plan['incomplete_is_not_coverage']is not True:raise ValueError('B62/B63 result finite continuation policy')
        document=parse(z.read('input.json'))
        if type(document)is not dict or set(document)!={'format','version','inputs','digest'}or document['format']!='B61_EXPLICIT_ENVIRONMENT_AGEING_INPUT_V7'or type(document['version'])is not int or document['version']!=7 or document['digest']!=digest(canonical({k:document[k]for k in('format','version','inputs')}))or type(document['inputs'])is not dict or type(document['inputs'].get('duration_seconds'))is not int or document['inputs']['duration_seconds']!=plan['root_target']-plan['original_anchor']:raise ValueError('B62 result original V7 duration/digest')
        expected={'view.json','input.json','execution-contract.json','plan.json'}
        if modern:
            from .lifetime_execution_authority import (admit_authority_data,domain_from_document,backend_binding,typed_backend_binding)
            if z.getinfo('input.json').file_size>8*2**20 or 'execution-authority.json'not in m['files']or z.getinfo('execution-authority.json').file_size>16384:
                raise ValueError('B63 bounded read-only authority/input DATA')
            authority_raw=z.read('execution-authority.json');authority=admit_authority_data(parse(authority_raw))
            body=authority['binding'];authority_sha=digest(authority_raw)
            if canonical(authority)!=authority_raw or authority_sha!=v['execution_authority_sha256']or authority_sha!=plan['execution_authority_sha256']:
                raise ValueError('B63 read-only authority raw/view/plan pin')
            expected_backend=(typed_backend_binding if typed else backend_binding)(c['backend_binding']['selection'],c['native_build'])
            if canonical(expected_backend)!=canonical(c['backend_binding'])or canonical(expected_backend)!=canonical(v['backend_binding'])or canonical(expected_backend)!=canonical(plan['backend_binding']):
                raise ValueError('B63 read-only backend/build binding')
            expected_binding=dict(root_identity=v['root_identity'],input_sha256=v['input_sha256'],
                source_manifest_sha256=v['source_manifest_sha256'],runtime=c['runtime'],
                execution_contract_sha256=v['execution_contract_sha256'],policy_identity=policy.identity,
                backend_binding=expected_backend,domain_identity=domain_from_document(document,plan['original_anchor']),
                original_anchor_seconds=plan['original_anchor'],duration_seconds=document['inputs']['duration_seconds'])
            if canonical(body)!=canonical(expected_binding)or plan['pool_inventory']!=('YEAR_V5_POSITIVE_INCREMENTAL_BLOCK_INVENTORY_V1'if packed else'YEAR_V4_PRODUCER_REGISTERED_SEALED_FILES_V1'if physical else'B63_VERIFIED_IMMUTABLE_INITIAL_FILES_ONLY_V1'):
                raise ValueError('B63 read-only source/runtime/domain/authority binding')
            expected.add('execution-authority.json')
        for j in v['jobs']:
            if j['scientific_file']is not None:
                expected.add(j['scientific_file'])
                if j['scientific_file']not in m['files']or m['files'][j['scientific_file']]['sha256']!=j['scientific_sha256']:raise ValueError('B62 result endpoint binding')
        if expected!=set(m['files']):raise ValueError('B62 unexpected executable/native member')
        primary=[j for j in v['jobs']if j['role']=='PRIMARY'and j['scientific_file']is not None]
        if primary:
            latest=max(primary,key=lambda j:j['clock'])
            from .design_repair_study import _plain_output
            from .lifecycle_report import combine,unpack
            science=_plain_output(parse(z.read(latest['scientific_file'])))
            report=science['report'];totals=combine([x for x in(report['sealed_totals'],report['current'])if x is not None])
            den=unpack(totals['priority_denominator']);num=unpack(totals['priority_numerator'])
            totals.update(priority_score=float(num/den)if den else None,priority_score_status='AVAILABLE'if den else'UNAVAILABLE_NO_OFFERS')
            if science['root_identity']!=v['root_identity']or science['clock']!=v['actual_end_seconds']or canonical(totals)!=canonical(v['primary_totals'])or science['work']!=v['cumulative_work']:raise ValueError('B62 read-only totals/work must match actual scientific prefix')
            # Monthly presentation is bound to the scientific state's original
            # row chain. A copied incomplete terminal row is not a native seal.
            monthly=v['monthly_actual'];sealed=monthly if report['current']is None else monthly[:-1]
            if len(sealed)!=report['sealed_count']:raise ValueError('B62 monthly/native seal count')
            chain='0'*64
            for row in sealed:
                native={k:x for k,x in row.items()if k!='lifetime_environment'}
                chain=digest((chain+canonical(native).decode('utf8')).encode('utf8'))
            if chain!=report['row_chain']:raise ValueError('B62 monthly rows must match scientific row chain')
            if report['current']is not None and report['current']['end_seconds']>report['current']['start_seconds']:
                if not monthly:raise ValueError('B62 missing actual partial row')
                copied={k:x for k,x in monthly[-1].items()if k not in('lifetime_environment','seal')}
                current={k:x for k,x in report['current'].items()if k!='seal'}
                if canonical(copied)!=canonical(current):raise ValueError('B62 copied partial row differs from scientific current row')
            from .lifetime_reporting import validate_work
            policy=document['inputs']['policy'];period=policy['month_period_seconds'];offset=policy['month_epoch_offset_seconds'];chain='0'*64;count=0
            for e in v['monthly_environment']:
                validate_work(e['paid_work_start']);validate_work(e['paid_work_end'])
                if e['end_seconds']>e['start_seconds']and (e['end_seconds']+offset)%period==0:
                    chain=digest((chain+canonical(e).decode('utf8')).encode('utf8'));count+=1
            native=report['lifetime_environment']
            if chain!=native['sealed_chain']or count!=native['sealed_count']:raise ValueError('B62 monthly environment must match scientific selected chain')
            from .lifetime_reporting import rows as retained_environment_rows
            for retained in retained_environment_rows(native):
                matching=[e for e in v['monthly_environment']if e['start_seconds']==retained['start_seconds']and e['end_seconds']==retained['end_seconds']]
                if len(matching)!=1 or canonical(matching[0])!=canonical(retained):raise ValueError('B62 retained/partial environment must match actual scientific properties/work')
        elif v['primary_totals']is not None or v['cumulative_work']is not None or v['actual_end_seconds']!=plan['original_anchor']:raise ValueError('B62 uncomputed primary has no totals/coverage')
        return v


def _admit_administrative_view(v):
    from .lifetime_no_launch import PROOF,DISPOSITION,digest
    rows=v['administrative_dispositions'];seen=set();jobs={j['job_id']:j for j in v['jobs']}
    if type(rows)is not list or len(rows)>len(jobs):raise ValueError('YEAR-V3 bounded administrative view')
    for row in rows:
        if type(row)is not dict or set(row)!={'disposition','proof'}:raise ValueError('YEAR-V3 administrative view schema')
        d=row['disposition'];p=row['proof'];jid=d.get('job_id')
        if (type(d)is not dict or set(d)!={'format','job_id','proof_sha256','scientific_authority'} or d['format']!=DISPOSITION or d['scientific_authority']is not False or
                type(p)is not dict or p.get('format')!=PROOF or digest(p)!=d['proof_sha256'] or jid in seen or jid not in jobs):
            raise ValueError('YEAR-V3 exported administrative proof binding')
        j=jobs[jid];b=p.get('boundary',{})
        if (j['status']!='REFUSED' or any(j[n]is not None for n in('clock','scientific_file','scientific_sha256','terminal')) or
                b.get('job_id')!=jid or b.get('root_identity')!=v['root_identity'] or
                b.get('input_sha256')!=v['input_sha256'] or any(p.get(k)is not False for k in('thread_start_attempted','scientific_launch_attempted','scientific_authority'))):
            raise ValueError('YEAR-V3 administrative job is not scientific credit')
        seen.add(jid)
