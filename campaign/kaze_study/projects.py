"""Versioned DESIGNS V1 data adapter; producer bytes never select executable code."""
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import time

from .data import (canonical, digest, fields, file_digest, identity, inside, integer,
                   no_links, parse, read, read_bytes, relative, sha, text, write_new)
from .errors import Refusal
from .project_owners import registered,verify_implementation
from .project_receipts import authority_body

PRODUCER = 'KAZE_USER_INITIAL_ROOT_MANIFEST_V1'
NORMALIZED = 'KAZE_VERIFIED_PROJECT_CATALOGUE_V1'
EXECUTION = 'KAZE_PROJECT_EXECUTION_CATALOGUE_V1'
ADAPTER = 'DESIGNS_R1_SOURCE824_V1'
COMPILER = 'fbdf5bb7f55c177c59c3524cdaeb714c89402e4560cff7d3133f62983d2687e5'
SOURCE = 'd90243c0725645237a60ab771b6c093de3af38fb08d815a10404adc7d72f8bb1'
COMMON = '06fa05a10b49420b3d7aab6cc7f172977bcfe4d6b6a7f8b04cafdb9a601ca801'
SOURCE_FREEZE = '96a94132e59dd1709ed7f474e767fa55fc6c3fa34edb212e58b5d1715e1311c3'
ASSUMPTIONS = 'd9972c1aada1e8861c0cf99f828fed609db3353dafed9614933b21a8d24d7f4d'
MANIFEST = 'results/user-designs/compiled/projects-manifest.json'
REFERENCE = 'results/b66-reference/'
OWNER_ROOT = Path(__file__).resolve().parents[1] / 'fixtures' / 'b66-packet'


def identifier(value):
    text(value, 'project id', 96)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value):
        raise Refusal('PROJECT_ID')
    relative(value)
    return value


def finite_policy(value):
    fields(value, ('maximum_cases','maximum_files','maximum_total_bytes'), 'explicit import policy')
    integer(value['maximum_cases'],'cases',1,128)
    integer(value['maximum_files'],'files',1,1024)
    integer(value['maximum_total_bytes'],'bytes',1,64*2**20)
    return value


def trusted_owner():
    """No manifest-supplied source path or Python module is used."""
    freeze=read(OWNER_ROOT/'SOURCE824-FREEZE.json')
    entries=freeze['manifest']
    if freeze['source_identity']!=SOURCE or identity(entries)!=SOURCE:
        raise Refusal('PROJECT_CODEC_SOURCE_PIN')
    engine=OWNER_ROOT/'engine-reference'
    actual={p.relative_to(engine).as_posix() for p in engine.rglob('*') if p.is_file()}
    if actual!=set(entries):raise Refusal('PROJECT_CODEC_SOURCE_MEMBERSHIP')
    for name,item in entries.items():
        raw=read_bytes(inside(engine,name))
        if len(raw)!=item['bytes'] or digest(raw)!=item['sha256']:
            raise Refusal('PROJECT_CODEC_SOURCE_DRIFT',name)
    return engine


def producer_data(producer_root, manifest_name, policy):
    """Read only a contained closure, strict JSON first, before any owner import."""
    finite_policy(policy); producer_root=no_links(producer_root).resolve()
    payload={}; folded=set(); total=0
    def take(name, expected=None, *, json_data=True):
        nonlocal total
        name=relative(name)
        if name not in payload:
            if name.casefold() in folded:raise Refusal('CASE_FOLDED_PRODUCER_PATH_COLLISION')
            raw=read_bytes(inside(producer_root,name),8*2**20)
            total+=len(raw)
            if len(payload)+1>policy['maximum_files'] or total>policy['maximum_total_bytes']:
                raise Refusal('PROJECT_IMPORT_FINITE_BYTES_OR_FILES')
            payload[name]=raw;folded.add(name.casefold())
        raw=payload[name]
        if expected is not None and digest(raw)!=sha(expected):
            raise Refusal('PRODUCER_RAW_HASH_MISMATCH',name)
        return parse(raw,8*2**20) if json_data else raw
    manifest_name=relative(manifest_name); parent=Path(manifest_name).parent.as_posix()
    def member(name, expected=None):
        return take((parent+'/' if parent!='.' else '')+relative(name),expected)
    m=take(manifest_name)
    fields(m,('format','version','projects','source','compiler','freeze_sha256',
        'research_authority_sha256','common_projection_sha256','common_input_sha256','actual','dispatch'),'producer V1')
    if m['format']!=PRODUCER or type(m['version']) is not int or m['version']!=1:
        raise Refusal('UNSUPPORTED_DESIGNS_PRODUCER_VERSION')
    compiler=fields(m['compiler'],('format','files','sha256'),'compiler closure')
    profile=registered(compiler=compiler['sha256'])
    if (compiler['format']!='KAZE_DESIGNS_CODE_V2' or compiler['files']!=profile['files'] or
            identity(compiler['files'])!=profile['compiler']):
        raise Refusal('UNTRUSTED_COMPILER_REVISION_REQUIRES_VERSIONED_ADAPTER')
    if type(compiler['files']) is not dict or not 1<=len(compiler['files'])<=128:
        raise Refusal('COMPILER_CLOSURE_BOUND')
    for name,pin in compiler['files'].items():take(name,pin,json_data=False)
    freeze_source=take(REFERENCE+'SOURCE824-FREEZE.json',SOURCE_FREEZE)
    if identity(freeze_source['manifest'])!=SOURCE or freeze_source['source_identity']!=SOURCE:
        raise Refusal('PRODUCER_SOURCE_CLOSURE_IDENTITY')
    common=take(REFERENCE+'handoff/frozen-r10/COMMON-RESEARCH-INPUT.json',COMMON)
    assumptions=take(REFERENCE+'handoff/frozen-r10/ASSUMPTIONS.json',ASSUMPTIONS)
    expected_source=dict(format='KAZE_B65_REFERENCE_V1',source_identity=SOURCE,files=824,
        freeze_sha256=digest(payload[REFERENCE+'SOURCE824-FREEZE.json']),raw_byte_equality=True,
        common_input_sha256=COMMON,assumptions_sha256=identity(assumptions))
    # ASSUMPTIONS is canonical in this owner revision; raw identity is authoritative.
    expected_source['assumptions_sha256']=digest(payload[REFERENCE+'handoff/frozen-r10/ASSUMPTIONS.json'])
    if m['source']!=expected_source or m['common_input_sha256']!=COMMON:
        raise Refusal('PROJECT_SOURCE_OR_COMMON_TEMPLATE_MISMATCH')
    freeze=member('PROJECT-FREEZE.json',m['freeze_sha256'])
    authority=member('RESEARCH-AUTHORITY.json',m['research_authority_sha256'])
    projection=member('COMMON-PROJECTION.json',m['common_projection_sha256'])
    for key in ('source','compiler','research_authority_sha256','common_projection_sha256'):
        if freeze.get(key)!=m[key]:raise Refusal('PROJECT_FREEZE_AUTHORITY_MISMATCH',key)
    if freeze.get('format')!='KAZE_USER_PROJECT_FREEZE_V1' or freeze.get('mission_outputs_seen') is not False:
        raise Refusal('PROJECT_INITIAL_FREEZE_REQUIRED')
    if (authority.get('source_identity')!=SOURCE or authority.get('common_input_sha256')!=COMMON or
        authority.get('supplied_assumptions_sha256')!=expected_source['assumptions_sha256'] or
        identity(authority.get('coefficients'))!=authority.get('coefficient_digest')):
        raise Refusal('PROJECT_RESEARCH_AUTHORITY_BINDING')
    entries=m['projects']
    if type(entries) is not list or not 1<=len(entries)<=policy['maximum_cases']:
        raise Refusal('PROJECT_POPULATION_BOUND')
    if freeze.get('projects')!=[dict(id=x.get('project_id'),identity=x.get('project_identity')) for x in entries]:
        raise Refusal('PROJECT_FREEZE_POPULATION')
    ids=set(); roots={}; inputs={}; physical={}; cases=[]
    for item in entries:
        fields(item,('project_id','project_identity','status','input_file','input_sha256','root_identity',
            'report_file','report_sha256','project_file','duplicate_physical_root_of'),'admitted producer item')
        name=identifier(item['project_id'])
        if name.casefold() in ids:raise Refusal('DUPLICATE_PROJECT_ID')
        ids.add(name.casefold())
        if item['status']!='ADMITTED_EXECUTABLE_INPUT':raise Refusal('PRODUCER_CASE_NOT_ADMITTED',name)
        spec=member(item['project_file'],item['project_identity'])
        report=member(item['report_file'],item['report_sha256'])
        doc=member(item['input_file'],item['input_sha256'])
        if spec.get('project_id')!=name or identity(spec)!=item['project_identity']:
            raise Refusal('PROJECT_CANONICAL_SPEC_IDENTITY')
        specraw=payload[(parent+'/' if parent!='.' else '')+item['project_file']]
        if canonical(spec)!=specraw:raise Refusal('PROJECT_NONCANONICAL_SPEC')
        for key in ('project_id','project_identity','input_sha256','root_identity','status'):
            if report.get(key)!=item[key]:raise Refusal('PROJECT_REPORT_BINDING',key)
        for key in ('compiler','common_projection_sha256','research_authority_sha256'):
            if report.get(key)!=m[key]:raise Refusal('PROJECT_REPORT_AUTHORITY',key)
        if report.get('source_identity')!=SOURCE or report.get('actual')!='NOT_RUN':
            raise Refusal('PROJECT_REPORT_SOURCE_OR_ACTUAL')
        fields(doc,('format','version','inputs','digest'),'canonical root')
        if (doc['format']!='B61_EXPLICIT_ENVIRONMENT_AGEING_INPUT_V7' or doc['version']!=7 or
            doc['digest']!=identity({k:doc[k] for k in ('format','version','inputs')})):
            raise Refusal('PROJECT_CANONICAL_ROOT_DOCUMENT')
        pin=dict(project_identity=sha(item['project_identity']),spec_sha256=digest(specraw),
            compiler_source_sha256=profile['compiler'],compiler_manifest_sha256=identity(compiler),
            initial_root_identity=sha(item['root_identity']),input_sha256=sha(item['input_sha256']),
            common_scenario_sha256=m['common_projection_sha256'],research_authority_sha256=m['research_authority_sha256'],
            freeze_sha256=m['freeze_sha256'],engine_source_sha256=SOURCE,build_sha256=None)
        prior=roots.get(pin['initial_root_identity'])
        if item['duplicate_physical_root_of']!=prior:raise Refusal('DUPLICATE_PROVENANCE_MISMATCH')
        if prior and inputs.get(pin['input_sha256'])!=prior:raise Refusal('ROOT_INPUT_ALIAS_MISMATCH')
        if not prior and pin['input_sha256'] in inputs:raise Refusal('INPUT_ROOT_ALIAS_MISMATCH')
        phys=sha(report.get('physical_spec_identity'))
        if phys in physical and not prior:raise Refusal('PHYSICAL_SPEC_CONTRADICTORY_ROOT')
        roots[pin['initial_root_identity']]=name; inputs[pin['input_sha256']]=name;physical[phys]=name
        cases.append(dict(project_id=name,pins=pin,case_identity=identity(pin),alias_of=prior,
            physical_spec_identity=phys,producer_item=item,
            input_path=(parent+'/' if parent!='.' else '')+item['input_file'],
            metadata=dict(parts=spec['parts'],instances=spec['instances'],units=spec['units'],
                electrical=spec['electrical'],thermal=report['thermal'],ratings=report['ratings'],
                effective_mass_properties=report['effective_mass_properties'],mass_ownership=report['mass_ownership'],
                routes=report['routes'],provenance=spec['provenance'],material_metadata_status='ONLY_EXPLICIT_PRODUCER_FIELDS',
                science='NOT_RUN')))
    return m,payload,cases


def import_projects(producer_root, manifest_name, output, *, policy, label, authority=None, receipt_directory=None, runner=None,expected_authority=None):
    """Immutable snapshot -> authoritative codec proof -> deterministic catalogue."""
    text(label,'explicit display label',256);finite_policy(policy)
    if authority is None or receipt_directory is None:raise Refusal('OWNED_IMPORT_AUTHORITY_REQUIRED')
    output=no_links(output).absolute()
    if output.exists():raise Refusal('NEW_PROJECT_IMPORT_DIRECTORY_REQUIRED')
    started=time.monotonic();m,payload,cases=producer_data(producer_root,manifest_name,policy)
    profile=registered(compiler=m['compiler']['sha256'])
    verify_implementation(profile);trusted_owner()
    read_wall=time.monotonic()-started
    snapshot_start=time.monotonic()
    for name,raw in sorted(payload.items()):write_new(inside(output/'raw',name),raw)
    inventory={n:dict(bytes=len(raw),sha256=digest(raw)) for n,raw in sorted(payload.items())}
    if len(canonical(cases))+len(canonical(m))+len(canonical(inventory))>2*2**20-65536:
        raise Refusal('NORMALIZED_CATALOGUE_FINITE_METADATA_BYTES')
    seed=dict(schema=NORMALIZED,adapter=profile['adapter'],producer=dict(format=PRODUCER,manifest=manifest_name,
        sha256=digest(payload[manifest_name])),raw_files=inventory)
    cached=authority.lookup(seed)
    snapshot_wall=time.monotonic()-snapshot_start
    compile_start=time.monotonic()
    if cached is not None:
        proof=cached['verified']['codec_proof']
    else:
        from .process import ProcessRunner
        from .validation_budget import reserve_validation,finish_validation
        if runner is not None and type(runner) is not ProcessRunner:raise Refusal('EXACT_OWNED_PROCESS_RUNNER_REQUIRED')
        authority.check_attempt(seed)
        reservation=reserve_validation([c['project_id'] for c in cases])
        authority.begin(seed,output)
        result=(runner or ProcessRunner(maximum_children=1)).run(
            [sys.executable,'-B','-m','kaze_study.project_codec','--root',str(output/'raw'),
             '--manifest',manifest_name,'--metrics',str(output/'validation-metrics.json')],cwd=str(Path(__file__).resolve().parents[1]),timeout=reservation['seconds'],
            stdout_cap=4*2**20,stderr_cap=2**20,rss_cap=768*2**20)
        finish_validation(reservation,result)
        write_new(output/'codec-process.json',canonical(result.evidence()))
        write_new(output/'codec-stderr.txt',result.stderr)
        if result.returncode!=0 or result.reason is not None or not result.reaped:
            authority.settled_failure(seed,result.evidence())
            raise Refusal('TRUSTED_PROJECT_CODEC_REFUSED',result.stderr.decode('utf-8','replace')[-2000:])
        proof=parse(result.stdout)
    compile_wall=time.monotonic()-compile_start
    receipt_start=time.monotonic()
    fields(proof,('format','adapter','compiler_source_sha256','cases','science_entries','native_import'),'trusted codec proof')
    if (proof['format']!='KAZE_PROJECT_CODEC_PROOF_V1' or proof['adapter']!=profile['adapter'] or
        proof['compiler_source_sha256']!=profile['compiler'] or type(proof['science_entries']) is not int or
        proof['science_entries']!=0 or proof['native_import'] is not False or
        set(proof['cases'])!={c['project_id'] for c in cases}):
        raise Refusal('PROJECT_CODEC_PROOF_POPULATION')
    for c in cases:
        p=proof['cases'][c['project_id']]
        fields(p,('root_identity','input_sha256','anchor_seconds','root_duration_seconds','canonical_roundtrip',
            'original_empty_custody','common_projection_verified','constructor_metadata_verified','science_entries'),'initial proof')
        integer(p['anchor_seconds'],'trusted initial anchor',0,2**63-1)
        integer(p['root_duration_seconds'],'trusted initial duration',1,473364000)
        if any(p[k] is not True for k in ('canonical_roundtrip','original_empty_custody','common_projection_verified','constructor_metadata_verified')) or type(p['science_entries']) is not int or p['science_entries']!=0:
            raise Refusal('PROJECT_CODEC_INITIAL_FLAGS')
        if p['root_identity']!=c['pins']['initial_root_identity'] or p['input_sha256']!=c['pins']['input_sha256']:
            raise Refusal('PROJECT_CODEC_PROOF_IDENTITY')
        c['initial']=p
    value=dict(schema=NORMALIZED,adapter=profile['adapter'],label=label,policy=policy,
        producer=dict(format=PRODUCER,manifest=manifest_name,sha256=digest(payload[manifest_name])),
        source=m['source'],compiler=m['compiler'],freeze_sha256=m['freeze_sha256'],
        common_projection_sha256=m['common_projection_sha256'],research_authority_sha256=m['research_authority_sha256'],
        common_input_sha256=COMMON,raw_files=inventory,codec_proof=proof,cases=cases,
        state='PENDING_CORE_BINDING',dispatch=False,science='NOT_RUN')
    value['catalogue_identity']=identity(value)
    if expected_authority is not None and authority_body(value)!=expected_authority:
        raise Refusal('INDEPENDENT_INITIAL_PROOF_MISMATCH')
    if cached is not None:
        authority.require(value)
    else:
        # Recheck copied bytes and registered implementation after the child.
        check_m,check_payload,_=producer_data(output/'raw',manifest_name,policy)
        if check_m!=m or check_payload!=payload:raise Refusal('PROJECT_CHANGED_DURING_VERIFICATION')
        verify_implementation(profile);trusted_owner()
        authority.publish(value,receipt_directory)
    write_new(output/'catalogue.json',canonical(value))
    write_new(output/'admission-timing.json',canonical(dict(read_hash_seconds=read_wall,snapshot_seconds=snapshot_wall,
        compile_codec_seconds=compile_wall,receipt_seconds=time.monotonic()-receipt_start,cache_hit=cached is not None,
        validation_transactions=0 if cached else len(cases)+1,science_entries=0)))
    return value


def _load_header(path):
    path=no_links(path).absolute();v=read(path)
    fields(v,('schema','adapter','label','policy','producer','source','compiler','freeze_sha256',
        'common_projection_sha256','research_authority_sha256','common_input_sha256','raw_files',
        'codec_proof','cases','state','dispatch','science','catalogue_identity'),'normalized catalogue')
    if v.get('schema')!=NORMALIZED:
        raise Refusal('NORMALIZED_PROJECT_SCHEMA')
    registered(adapter=v.get('adapter'));finite_policy(v['policy'])
    if v['state']!='PENDING_CORE_BINDING' or v['dispatch'] is not False or v['science']!='NOT_RUN':
        raise Refusal('NORMALIZED_DATA_NEVER_DISPATCH_AUTHORITY')
    claimed=v.get('catalogue_identity');body={k:x for k,x in v.items() if k!='catalogue_identity'}
    if identity(body)!=claimed:raise Refusal('NORMALIZED_CATALOGUE_IDENTITY')
    return v


def _load_lineage(path):
    path=no_links(path).absolute();v=_load_header(path)
    profile=registered(adapter=v['adapter'])
    m,payload,cases=producer_data(path.parent/'raw',v['producer']['manifest'],v['policy'])
    if profile['compiler']!=m['compiler']['sha256']:raise Refusal('NORMALIZED_OWNER_MISMATCH')
    inventory={n:dict(bytes=len(raw),sha256=digest(raw)) for n,raw in sorted(payload.items())}
    if inventory!=v['raw_files'] or digest(payload[v['producer']['manifest']])!=v['producer']['sha256']:
        raise Refusal('NORMALIZED_RAW_LINEAGE_DRIFT')
    for expected,actual in zip(cases,v['cases'],strict=True):
        if expected!={k:x for k,x in actual.items() if k!='initial'}:
            raise Refusal('NORMALIZED_DERIVED_MAPPING_DRIFT')
        if actual['initial']!=v['codec_proof']['cases'][actual['project_id']]:raise Refusal('CODEC_PROOF_MAPPING')
    return v


def load_verified(path, *, authority=None):
    if read(path).get('schema')=='KAZE_VERIFIED_NAMED_PROJECT_CATALOGUE_V1':
        from .current_projects import load_verified as current
        return current(path,authority=authority)
    if authority is None:raise Refusal('OWNED_IMPORT_AUTHORITY_REQUIRED')
    path=no_links(path).absolute();v=_load_header(path)
    # The independent owned receipt pins the complete derived mapping. Re-read
    # and hash its exact raw closure; do not reparse/reconstruct the same roots.
    authority.require(v)
    inventory=v['raw_files'];policy=v['policy']
    if (not 1<=len(v['cases'])<=policy['maximum_cases'] or len(inventory)>policy['maximum_files'] or
        sum(x['bytes'] for x in inventory.values())>policy['maximum_total_bytes']):
        raise Refusal('PROJECT_IMPORT_FINITE_BYTES_OR_FILES')
    for name,pin in inventory.items():
        raw=read_bytes(inside(path.parent/'raw',name),8*2**20)
        if len(raw)!=pin['bytes'] or digest(raw)!=pin['sha256']:raise Refusal('NORMALIZED_RAW_LINEAGE_DRIFT',name)
    verify_implementation(registered(adapter=v['adapter']));trusted_owner()
    return v


def admit_external(path, *, authority, receipt_directory):
    if read(path).get('schema')=='KAZE_VERIFIED_NAMED_PROJECT_CATALOGUE_V1':
        from .current_projects import admit_external as current
        return current(path,authority=authority,receipt_directory=receipt_directory)
    """Explicit revalidation; external proof and external receipts are claims."""
    v=_load_header(path)
    try:return load_verified(path,authority=authority)
    except Refusal as e:
        if e.code!='OWNED_IMPORT_RECEIPT_REQUIRED_REVERIFY_EXPLICITLY':raise
    v=_load_lineage(path)
    import uuid
    check=Path(receipt_directory)/('verify-'+uuid.uuid4().hex)
    actual=import_projects(Path(path).parent/'raw',v['producer']['manifest'],check,
        policy=v['policy'],label=v['label'],authority=authority,receipt_directory=receipt_directory,
        expected_authority=authority_body(v))
    if authority_body(actual)!=authority_body(v):
        raise Refusal('INDEPENDENT_INITIAL_PROOF_MISMATCH')
    return load_verified(path,authority=authority)


def cohort(catalogues, *, authority=None):
    if not isinstance(catalogues,(list,tuple)) or not 1<=len(catalogues)<=128:raise Refusal('FINITE_COHORT_SELECTION_REQUIRED')
    values=[load_verified(p,authority=authority) for p in catalogues]
    common=('source','compiler','common_input_sha256','common_projection_sha256','research_authority_sha256')
    if any(any(v[k]!=values[0][k] for k in common) for v in values[1:]):
        raise Refusal('INCOMPATIBLE_PROJECT_COHORT')
    unique={}; aliases=[]
    for v in values:
        for c in v['cases']:
            causal=(c['pins']['initial_root_identity'],c['pins']['input_sha256'])
            if causal in unique:aliases.append(dict(project_id=c['project_id'],alias_of=unique[causal]['project_id']))
            else:unique[causal]=c
    return dict(schema='KAZE_PROJECT_COHORT_V1',cases=list(unique.values()),aliases=aliases,
        unique_physical_roots=len(unique),actual_results='NOT_RUN',primary_credits=None,dispatch=False)


def load_execution_catalogue(raw,root,*,mode,source_sha256,horizon_seconds,build_sha256,authority=None):
    """Derived dispatch selection. This format is CAMPAIGN-owned, never producer V1."""
    from .data import reference
    from .catalogue import Catalogue,Design
    v=fields(parse(raw),('schema','label','verified_catalogue','projects','bucket_seconds','build_sha256'),'execution selection')
    if v['schema']!=EXECUTION or v['label']!=mode or mode!='PRODUCTION':raise Refusal('EXECUTION_CATALOGUE_MODE')
    path,_=reference(root,v['verified_catalogue']);cat=load_verified(path,authority=authority)
    if source_sha256!=cat['source']['source_identity'] or v['build_sha256']!=build_sha256:
        raise Refusal('PROJECT_FRESH_SOURCE_BUILD_BINDING_REQUIRED')
    integer(v['bucket_seconds'],'requested report bucket',1,31557600)
    if type(v['projects']) is not list or not v['projects'] or len(set(v['projects']))!=len(v['projects']):
        raise Refusal('EXPLICIT_PROJECT_SELECTION')
    byid={c['project_id']:c for c in cat['cases']};designs=[];seen=set();anchors=set()
    for name in v['projects']:
        if name not in byid:raise Refusal('UNKNOWN_VERIFIED_PROJECT',name)
        c=byid[name];p=c['pins'];causal=(p['initial_root_identity'],p['input_sha256'])
        if causal in seen:raise Refusal('DUPLICATE_CAUSAL_EXECUTION_CASE')
        seen.add(causal);anchors.add(c['initial']['anchor_seconds'])
        if horizon_seconds>c['initial']['root_duration_seconds']:raise Refusal('REQUEST_EXCEEDS_INITIAL_ROOT_DOMAIN')
        pins=dict(p,build_sha256=build_sha256,project_metadata=c['metadata'])
        pins['case_identity']=identity({k:x for k,x in pins.items() if k!='project_metadata'})
        data=read_bytes(inside(path.parent/'raw',c['input_path']),8*2**20)
        mass=dict(value_kg=str(c['metadata']['effective_mass_properties']['total_mass_kg']),
            status='ASSUMED_RESEARCH',source=c['producer_item']['report_sha256'])
        assumptions=[dict(name='research authority',value=cat['research_authority_sha256'],units='identity',
            source=cat['producer']['sha256'],consumer='CORE',status='SUPPLIED')]
        designs.append(Design(name,p['initial_root_identity'],p['input_sha256'],str(inside(path.parent/'raw',c['input_path'])),
            data,canonical(assumptions),canonical(mass),canonical(pins)))
    if len(anchors)!=1:raise Refusal('PROJECT_COMMON_ANCHOR')
    return Catalogue(tuple(designs),cat['common_projection_sha256'],source_sha256,raw,anchors.pop(),v['bucket_seconds'])


def execution_references(root,catref, *, authority=None):
    """Copy closure for State.create, retaining original producer paths/bytes."""
    from .data import reference
    _,raw=reference(root,catref);wrapper=parse(raw)
    nref=wrapper['verified_catalogue'];path,nraw=reference(root,nref);v=load_verified(path,authority=authority)
    result={nref['path']:nraw}
    parent=Path(nref['path']).parent
    for name,item in v['raw_files'].items():
        raw=read_bytes(inside(path.parent/'raw',name),8*2**20)
        result[(parent/'raw'/name).as_posix()]=raw
    return result
