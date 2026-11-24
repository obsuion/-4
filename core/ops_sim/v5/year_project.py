"""Authored V3 -> original-anchor finite day/year -> existing serial lifetime.

No separate executor, launcher, numerical method, environment ephemeris or CAD.
The long scenario explicitly retains the already selected ASSUMED annual Sun
and stationary declared lumped forcing. A short Sun table is never extended.
"""
from dataclasses import replace,asdict
from hashlib import sha256
from pathlib import Path
import json

FORMAT='YEAR_V1_AUTHORED_SERIAL_JOB'
WORLD='YEAR_V1_EXPLICIT_EXISTING_ASSUMED_ANNUAL_WORLD'
DAY=86400
YEAR=31557600
MAX_BYTES=16*2**20
FORMAT_V5='YEAR_V5_EXPLICIT_SHORT_CIRCUIT_PACKED_JOB_V2'
DERIVATION_V5='YEAR_V5_QUIET_METHOD_ONLY_AND_DURATION_DERIVATION_V1'


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')


def _fields(value,names):
    if type(value)is not dict or any(type(k)is not str for k in value)or set(value)!=set(names):
        raise ValueError('YEAR-V1 exact declared fields')


def _world(root):
    from .lifecycle_contract import LifecycleRoot
    from .lifetime_admission import ACCOUNTING
    from .lifecycle_execution import build_model
    if type(root)is not LifecycleRoot:raise TypeError('YEAR-V1 full original LifecycleRoot')
    if (root.sun_mode!='REDUCED_ASSUMED_ANNUAL_V1' or root.policy.method!=ACCOUNTING or
            root.study is None or root.environment_ageing_policy is None or
            root.battery_port_policy is None or root.energy_attitude_policy is None or root.output_policy is None):
        raise ValueError('YEAR-V1 explicit annual/lumped study, accounting, ageing, battery, Sun policy and streams required')
    anchor=root.base.model.environment.trajectory.initial_state.position.instant.elapsed_seconds
    if root.start_seconds!=anchor:raise ValueError('YEAR-V1 original anchor; no reanchoring')
    old=root.base.model.environment
    # This producer supports only a genuinely stationary baseline declaration.
    # It does not discard profile discontinuities or reuse a table periodically.
    from .lifecycle_study import validate_study_base
    from .lifecycle_orbit import _identity
    validate_study_base(root.base,root.study)
    payloads=tuple(_identity((e.nodes,e.loads,e.incidence_angle_deg,e.internal_includes_eps_losses,e.non_overlap_assumption))for e in old.profile)
    if len(set(payloads))!=1:raise ValueError('YEAR-V1 profile is not a declared stationary study law; no discarded discontinuities')
    world=build_model(root).environment
    if world.sun_table is not None or world.start_seconds!=anchor or world.end_seconds!=root.end_seconds:
        raise ValueError('YEAR-V1 complete declared world domain')
    from .lifecycle_orbit import _identity
    return dict(method=WORLD,start_seconds=root.start_seconds,end_seconds=root.end_seconds,
        sun_mode=root.sun_mode,sun=asdict(world.sun),sun_table_used=False,
        original_short_table_domain=[str(t)for t in old.table.domain_seconds],
        orbit='EXISTING_ORIGINAL_ANCHOR_J2_FIXED_GRID_RK4',lighting_step_seconds=world.lighting_step_seconds,
        stationary_forcing_identity=_identity((old.profile[0].nodes,old.profile[0].loads)),
        original_profile_pieces=len(old.profile),stationary_profile_payloads=list(payloads),
        stationary_forcing='EXPLICIT_EXISTING_ASSUMED_LUMPED_STUDY_CONSTANT_LAW_OVER_DECLARED_DOMAIN_NOT_EXTENDED_EPHEMERIS',
        world_identity=_identity((world,)),qualification='NOMINAL_SAMPLED_ASSUMED_MODEL_NO_EVENT_TIME_OR_FLIGHT_ACCURACY_CERTIFICATE')


def derive_project(project,duration_seconds):
    """Immutable mission-duration derivation, preserving every authored part.

    The caller must explicitly upgrade source DATA before this boundary when
    importing a project authored under another implementation. No checkpoint
    or advanced physical state is admitted as an initial project.
    """
    from .spacecraft_project_v3 import SpacecraftProjectV3
    from .spacecraft_project import project_source_identity
    from .lifecycle_contract import integer
    if type(project)is not SpacecraftProjectV3:raise TypeError('YEAR-V1 authored general V3 required')
    project.__post_init__();integer(duration_seconds,'YEAR-V1 duration',1,YEAR)
    if project.source_identity!=project_source_identity():raise ValueError('YEAR-V1 source mismatch; explicit source upgrade required')
    result=replace(project,common=replace(project.common,duration_seconds=duration_seconds))
    _world(result.common)
    return result


def compile_job(project,duration_seconds,ledger,policy,build_bytes):
    from .metadata_codec import admitted_metadata_scope
    from .portable_job import parse
    with admitted_metadata_scope(parse(build_bytes)):
        return _compile_job(project,duration_seconds,ledger,policy,build_bytes)


def _compile_job(project,duration_seconds,ledger,policy,build_bytes):
    """Paid actual design compilation; DATA preparation grants no launch."""
    from .spacecraft_project_document import dumps_project
    from .spacecraft_project import materialize_design_project
    from .lifetime_admission import resource_plan
    from .lifetime_campaign import horizon_preflight
    from .lifetime_policy import QUALIFICATION,WINDOWS_USER,is_v2
    from .general_project_job import GeneralProjectExecution
    from .lifetime_execution_authority import USER_LONG,PILOT
    from .lifecycle_document import dumps_root
    from .portable_job import parse
    if not is_v2(policy):raise TypeError('YEAR-V1 existing finite V2 lifetime policy')
    if duration_seconds>DAY and policy.mode!=WINDOWS_USER:raise ValueError('YEAR-V1 long Windows job requires explicit experimental policy')
    if duration_seconds<=DAY and policy.mode not in (QUALIFICATION,WINDOWS_USER):raise ValueError('YEAR-V1 local job policy')
    original=dumps_project(project).encode('utf8');derived=derive_project(project,duration_seconds)
    root,construction,hardware=materialize_design_project(derived,ledger)
    world=_world(root);horizon=horizon_preflight(root,policy)
    mode=USER_LONG if policy.mode==WINDOWS_USER else PILOT
    execution=GeneralProjectExecution(policy,build_bytes,execution_mode=mode)
    body=dict(format=FORMAT,version=1,project_document=dumps_project(derived),root_document=dumps_root(root).decode('utf8'),
        original_project_document=original.decode('utf8'),original_project_sha256=sha256(original).hexdigest(),
        project_identity=derived.identity,root_identity=root.identity,source_identity=derived.source_identity,
        duration_seconds=duration_seconds,world=world,resource_plan=resource_plan(root),horizon=horizon,
        execution=dict(policy=asdict(policy),mode=mode,backend=execution.backend,build=parse(build_bytes)),
        evidence=dict(constructor_work=asdict(ledger),assembly_mass_kg=hardware.mass_properties.total_mass_kg),
        qualification='PREPARED_ONLY_NO_YEAR_EXECUTION_OR_PHYSICAL_QUALIFICATION')
    raw=canonical(dict(body,digest=sha256(canonical(body)).hexdigest()))
    if len(raw)>MAX_BYTES:raise ValueError('YEAR-V1 finite job bytes')
    return raw


def _admit_job_legacy(raw,ledger):
    """Strict portable data + paid independent compiled-root reconstruction."""
    from .portable_job import parse
    from .spacecraft_project_document import loads_project,dumps_project
    from .spacecraft_project import project_source_identity,materialize_design_project
    from .lifecycle_document import dumps_root,loads_root
    from .lifetime_policy import admit_policy
    from .lifetime_campaign import horizon_preflight
    from .lifetime_admission import resource_plan
    from .general_project_job import GeneralProjectExecution
    if type(raw)is not bytes or not 0<len(raw)<=MAX_BYTES:raise ValueError('YEAR-V1 bounded job bytes')
    d=parse(raw)
    _fields(d,('format','version','project_document','root_document','original_project_document','original_project_sha256',
        'project_identity','root_identity','source_identity','duration_seconds','world','resource_plan','horizon','execution','evidence','qualification','digest'))
    body={k:v for k,v in d.items()if k!='digest'}
    if d['format']!=FORMAT or type(d['version'])is not int or d['version']!=1 or canonical(d)!=raw or d['digest']!=sha256(canonical(body)).hexdigest():raise ValueError('YEAR-V1 exact canonical job identity')
    if d['qualification']!='PREPARED_ONLY_NO_YEAR_EXECUTION_OR_PHYSICAL_QUALIFICATION':raise ValueError('YEAR-V1 preparation is not qualification')
    original=d['original_project_document']
    if type(original)is not str or sha256(original.encode('utf8')).hexdigest()!=d['original_project_sha256']:raise ValueError('YEAR-V1 original project binding')
    source=project_source_identity()
    p=loads_project(d['project_document'],expected_source_identity=source,expected_identity=d['project_identity'])
    initial=loads_project(original,expected_source_identity=source)
    if dumps_project(derive_project(initial,d['duration_seconds']))!=d['project_document']:raise ValueError('YEAR-V1 only declared duration may change')
    root,_,hardware=materialize_design_project(p,ledger)
    if dumps_root(root).decode('utf8')!=d['root_document']or root.identity!=d['root_identity']or d['source_identity']!=source:raise ValueError('YEAR-V1 actual compiled full root binding')
    _fields(d['evidence'],('constructor_work','assembly_mass_kg'))
    from .design_repair import ConstructorLedger
    work=d['evidence']['constructor_work'];_fields(work,('maximum_compiles','compiles','control_reserved'))
    ConstructorLedger(**work).validate() # declaration only, never execution credit
    mass=d['evidence']['assembly_mass_kg']
    if type(mass)is not float or mass.hex()!=hardware.mass_properties.total_mass_kg.hex():raise ValueError('YEAR-V1 compiled mass declaration')
    # Fresh root decoding tests the existing V7 codec; it is not a prefix restore.
    if dumps_root(loads_root(d['root_document'].encode()))!=d['root_document'].encode():raise ValueError('YEAR-V1 root codec')
    _fields(d['execution'],('policy','mode','backend','build'))
    e=d['execution'];policy=admit_policy(e['policy']);execution=GeneralProjectExecution(policy,canonical(e['build']),execution_mode=e['mode'])
    if e['backend']!=execution.backend:raise ValueError('YEAR-V1 backend mismatch')
    if canonical(_world(root))!=canonical(d['world'])or canonical(resource_plan(root))!=canonical(d['resource_plan'])or canonical(horizon_preflight(root,policy))!=canonical(d['horizon']):raise ValueError('YEAR-V1 environment/resource derivation drift')
    return p,root,execution


def derive_project_v5(project,duration_seconds):
    """Explicit method selection, never a mutation of an old stored run.

    The authored specification and every numerical/physical policy field are
    retained. Only duration and the declared quiet method identity differ.
    """
    from .spacecraft_project_v3 import SpacecraftProjectV3
    from .spacecraft_project import project_source_identity
    from .lifecycle_contract import integer
    from .lifecycle_quiet import short_circuit_policy
    if type(project)is not SpacecraftProjectV3:raise TypeError('YEAR-V5 authored general V3 required')
    project.__post_init__();integer(duration_seconds,'YEAR-V5 duration',1,YEAR)
    if project.source_identity!=project_source_identity():raise ValueError('YEAR-V5 source mismatch; explicit initial DATA upgrade required')
    old=project.common.policy.quiet_solver
    if old is None:raise ValueError('YEAR-V5 requires an explicit supported quiet solver')
    selected=short_circuit_policy(old)
    before=asdict(old);after=asdict(selected)
    if {k:v for k,v in before.items()if k!='method'}!={k:v for k,v in after.items()if k!='method'}:
        raise ValueError('YEAR-V5 physical/numerical quiet fields changed')
    result=replace(project,common=replace(project.common,duration_seconds=duration_seconds,
        policy=replace(project.common.policy,quiet_solver=selected)))
    _world(result.common)
    return result


def _derivation_v5(original,derived):
    old=original.common.policy.quiet_solver;new=derived.common.policy.quiet_solver
    if old is None or new is None:raise ValueError('YEAR-V5 explicit quiet authority')
    values=asdict(old);values.pop('method')
    return dict(method=DERIVATION_V5,original_quiet_method=old.method,
        selected_quiet_method=new.method,physical_parameter_sha256=sha256(canonical(values)).hexdigest())


def compile_job_v5(project,duration_seconds,ledger,policy,build_bytes):
    """Opt-in Q1 + packed-store job; old compile_job stays unchanged."""
    from .lifetime_policy import packed_storage
    from .spacecraft_project_document import dumps_project
    from .metadata_codec import admitted_metadata_scope
    from .portable_job import parse
    if not packed_storage(policy):raise ValueError('YEAR-V5 requires the explicit packed terminal storage policy')
    with admitted_metadata_scope(parse(build_bytes)):
        derived=derive_project_v5(project,duration_seconds)
        body=parse(_compile_job(derived,duration_seconds,ledger,policy,build_bytes))
        body.pop('digest')
        original=dumps_project(project)
        body.update(format=FORMAT_V5,version=2,original_project_document=original,
            original_project_sha256=sha256(original.encode('utf8')).hexdigest(),
            derivation=_derivation_v5(project,derived))
        raw=canonical(dict(body,digest=sha256(canonical(body)).hexdigest()))
        if len(raw)>MAX_BYTES:raise ValueError('YEAR-V5 finite job bytes')
        return raw


def admit_job(raw,ledger):
    """Dispatch exact versioned DATA; legacy job bytes are never upgraded."""
    from .portable_job import parse
    if type(raw)is not bytes or not 0<len(raw)<=MAX_BYTES:raise ValueError('YEAR-V5 bounded job bytes')
    data=parse(raw)
    if type(data)is not dict or data.get('format')!=FORMAT_V5:
        return _admit_job_legacy(raw,ledger)
    from .spacecraft_project import project_source_identity
    from .spacecraft_project_document import loads_project,dumps_project
    from .lifetime_policy import admit_policy,packed_storage
    _fields(data,('format','version','project_document','root_document','original_project_document','original_project_sha256',
        'project_identity','root_identity','source_identity','duration_seconds','world','resource_plan','horizon','execution','evidence','qualification','derivation','digest'))
    body={k:v for k,v in data.items()if k!='digest'}
    if type(data['version'])is not int or data['version']!=2 or canonical(data)!=raw or data['digest']!=sha256(canonical(body)).hexdigest():
        raise ValueError('YEAR-V5 exact canonical versioned job identity')
    original=data['original_project_document']
    if type(original)is not str or sha256(original.encode('utf8')).hexdigest()!=data['original_project_sha256']:
        raise ValueError('YEAR-V5 original authored project binding')
    initial=loads_project(original,expected_source_identity=project_source_identity())
    derived=derive_project_v5(initial,data['duration_seconds'])
    if dumps_project(derived)!=data['project_document']or data['derivation']!=_derivation_v5(initial,derived):
        raise ValueError('YEAR-V5 only declared method and duration may change')
    execution=data['execution']
    if type(execution)is not dict or not packed_storage(admit_policy(execution.get('policy'))):
        raise ValueError('YEAR-V5 exact packed storage execution identity')
    # Reuse the complete independent compiled-root/world/build admission. Its
    # initial DATA is the already declared derived project, not a checkpoint.
    legacy={k:v for k,v in body.items()if k!='derivation'}
    legacy.update(format=FORMAT,version=1,original_project_document=data['project_document'],
        original_project_sha256=sha256(data['project_document'].encode('utf8')).hexdigest())
    legacy_raw=canonical(dict(legacy,digest=sha256(canonical(legacy)).hexdigest()))
    return _admit_job_legacy(legacy_raw,ledger)


def create_store(raw,project_directory,workspace_directory,ledger):
    from .metadata_codec import admitted_metadata_scope
    from .portable_job import parse
    # Full strict DATA fields/typed build are rechecked by admit_job below.
    data=parse(raw)
    if type(data)is not dict or type(data.get('execution'))is not dict:raise ValueError('YEAR-V1 job execution DATA')
    with admitted_metadata_scope(data['execution']['build']):
        return _create_store(raw,project_directory,workspace_directory,ledger)


def _create_store(raw,project_directory,workspace_directory,ledger):
    """Use ProjectStore -> paid preview -> actual Workspace creation unchanged."""
    from .project_store import ProjectStore
    from .lifecycle_application import LifecycleWorkspace
    from .lifetime_supervisor import _plan,_publish
    from .portable_job import worker_contract
    p,root,execution=admit_job(raw,ledger)
    projects=ProjectStore(project_directory,p.reference,create=True)
    workspace=None
    try:
        created=projects.create(p);projects.preview(created['project_id'],p.identity)
        workspace=LifecycleWorkspace(workspace_directory,project_store=projects)
        snap=workspace.create_design_project(dict(project_id=created['project_id'],revision=p.identity),execution=execution)
        if snap['root_identity']!=root.identity:raise ValueError('YEAR-V1 consumer full-root equality')
        store=workspace.store(root.identity)
        plan=_plan(store,worker_contract(store.directory,Path(__file__).resolve().parents[2]))
        _publish(store.path('lifetime-plan.json'),plan)
        return dict(store=str(store.directory),root_identity=root.identity,project_identity=p.identity,
            job_sha256=sha256(raw).hexdigest(),plan_identity=plan['plan_identity'],dispatch=False)
    finally:
        if workspace is not None:workspace.close()


def status(directory):
    from .lifetime_supervisor import control_status
    return control_status(directory)


def stop(directory):
    from .lifetime_supervisor import control_stop
    return control_stop(directory)


def main(argv=None):
    import argparse
    from .design_repair import ConstructorLedger
    from .lifetime_supervisor import run,export_result
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('create');c.add_argument('job',type=Path);c.add_argument('projects',type=Path);c.add_argument('workspace',type=Path)
    for name in ('run','resume','status','stop'):
        c=sub.add_parser(name);c.add_argument('store',type=Path)
        if name in ('run','resume'):c.add_argument('--maximum-segments',type=int,default=1)
    c=sub.add_parser('export');c.add_argument('store',type=Path);c.add_argument('output',type=Path)
    a=p.parse_args(argv)
    if a.command=='create':value=create_store(a.job.read_bytes(),a.projects,a.workspace,ConstructorLedger())
    elif a.command in ('run','resume'):value=run(a.store,explicit_continue=a.command=='resume',maximum_segments=a.maximum_segments)
    elif a.command=='status':value=status(a.store)
    elif a.command=='stop':value=stop(a.store)
    else:value=export_result(a.store,a.output)
    print(canonical(value).decode('utf8'));return 0

if __name__=='__main__':raise SystemExit(main())
