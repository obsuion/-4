"""Named general-project seam into the existing owned typed lifecycle runner.

No short-root conversion, new physics, launcher, or advanced-store migration.
The complete existing PILOT permission, runtime, build and package admission
owners still run. This module only retains the named project at that boundary.
"""
from dataclasses import dataclass,asdict
from hashlib import sha256
from pathlib import Path
import json

from .lifetime_policy import LifetimeCampaignPolicyV2
from .lifecycle_typed_platform import METHOD as NATIVE_DOMAIN

OPTIONS='B67_NAMED_GENERAL_NATIVE_EXECUTION_V1'
ENVELOPE='B67_NAMED_GENERAL_PROJECT_ENVELOPE_V1'
ENVELOPE_V3='B68_NAMED_ROUTE_THERMAL_PROJECT_ENVELOPE_V1'
ENVELOPE_LONG='YEAR_V1_NAMED_AUTHORED_SERIAL_EXPERIMENT'
MAX_BYTES=16*2**20


@dataclass(frozen=True,slots=True)
class GeneralProjectExecution:
    policy: LifetimeCampaignPolicyV2
    build_bytes: bytes
    method: str=OPTIONS
    execution_mode: str='PILOT'

    def __post_init__(self):
        if type(self.policy)is not LifetimeCampaignPolicyV2:
            raise TypeError('exact finite V2 execution policy')
        self.policy.__post_init__()
        from .lifetime_policy import WINDOWS_USER
        from .lifetime_execution_authority import USER_LONG,PILOT
        if (type(self.execution_mode)is not str or self.execution_mode not in (PILOT,USER_LONG) or
                (self.execution_mode==USER_LONG) != (self.policy.mode==WINDOWS_USER)):
            raise ValueError('YEAR-V1 explicit experimental execution permission/policy')
        if type(self.method)is not str or self.method!=OPTIONS:
            raise ValueError('explicit named general execution method')
        if type(self.build_bytes)is not bytes or not 0<len(self.build_bytes)<=65536:
            raise ValueError('bounded immutable successor native receipt bytes')
        from .portable_job import parse,canonical
        from .lifecycle_typed_platform import admit_build_data
        build=admit_build_data(parse(self.build_bytes))
        if canonical(build)!=self.build_bytes:
            raise ValueError('canonical successor receipt required')

    @property
    def backend(self):return NATIVE_DOMAIN


def dumps_named_project(project,execution):
    """Portable initial DATA only; receipt DATA alone grants no execution."""
    from .spacecraft_project_v2 import SpacecraftProjectV2
    from .spacecraft_project_v3 import SpacecraftProjectV3
    from .spacecraft_project_document import dumps_project
    from .portable_job import canonical,parse
    if type(project)not in (SpacecraftProjectV2,SpacecraftProjectV3) or type(execution)is not GeneralProjectExecution:
        raise TypeError('exact initial general project and execution selection')
    execution.__post_init__();project.__post_init__()
    doc=dumps_project(project)
    value=dict(format=ENVELOPE_V3 if type(project)is SpacecraftProjectV3 else ENVELOPE,version=1,project_document=doc,
        project_sha256=sha256(doc.encode('utf8')).hexdigest(),
        execution=dict(method=execution.method,backend=execution.backend,
            policy=asdict(execution.policy),build=parse(execution.build_bytes)),
        scope='INITIAL_INPUT_ONLY_NO_CHECKPOINT_OR_REMOTE_LAUNCH_RIGHTS')
    if execution.execution_mode!='PILOT':
        if type(project)is not SpacecraftProjectV3:raise ValueError('YEAR-V1 authored V3 project required')
        value['format']=ENVELOPE_LONG;value['execution']['execution_mode']=execution.execution_mode
    raw=canonical(value)
    if len(raw)>MAX_BYTES:raise ValueError('named project envelope byte cap')
    return raw


def loads_named_project(raw):
    from .portable_job import parse,fields,canonical
    from .spacecraft_project_v2 import SpacecraftProjectV2
    from .spacecraft_project_v3 import SpacecraftProjectV3
    from .spacecraft_project_document import loads_project
    from .spacecraft_project import project_source_identity
    from .lifetime_policy import admit_policy
    if type(raw)is not bytes or not 0<len(raw)<=MAX_BYTES:
        raise ValueError('bounded named project DATA')
    value=parse(raw)
    fields(value,('format','version','project_document','project_sha256','execution','scope'))
    if (type(value['format'])is not str or value['format']not in (ENVELOPE,ENVELOPE_V3,ENVELOPE_LONG) or type(value['version'])is not int or value['version']!=1 or
            value['scope']!='INITIAL_INPUT_ONLY_NO_CHECKPOINT_OR_REMOTE_LAUNCH_RIGHTS'):
        raise ValueError('named project envelope version/scope')
    doc=value['project_document']
    if type(doc)is not str or sha256(doc.encode('utf8')).hexdigest()!=value['project_sha256']:
        raise ValueError('named project document binding')
    project=loads_project(doc,expected_source_identity=project_source_identity())
    if type(project)is not (SpacecraftProjectV3 if value['format']in (ENVELOPE_V3,ENVELOPE_LONG) else SpacecraftProjectV2):raise ValueError('named envelope/project family mismatch')
    data=value['execution'];fields(data,('method','backend','policy','build',*(('execution_mode',)if value['format']==ENVELOPE_LONG else())))
    if data['backend']!=NATIVE_DOMAIN:raise ValueError('named project exact native domain')
    execution=GeneralProjectExecution(admit_policy(data['policy']),canonical(data['build']),data['method'],data.get('execution_mode','PILOT'))
    if dumps_named_project(project,execution)!=raw:raise ValueError('canonical named project roundtrip')
    return project,execution


def create_native_store(directory,root,lineage,document,execution):
    """Paid composed root -> full existing v4 execution/authority -> local store.

    Called only by LifecycleWorkspace after its paid constructor. Store creation
    independently validates project->root equality, without cached-id shortcuts.
    """
    from .portable_job import canonical,parse,runtime_requirements
    from .lifetime_typed_portable import execution_contract_v3,_job_metadata,JOB_V4
    from .lifetime_execution_authority import make_authority
    from .lifecycle_document import dumps_root
    from .lifecycle_application import LifecycleStore,make_intent,_write_new
    from .lifecycle_execution_budget import ExecutionBudget
    from .lifecycle_compact import PublicationProfile
    from .lifecycle_fast import FAST
    from .lifetime_campaign import horizon_preflight
    if type(execution)is not GeneralProjectExecution:raise TypeError('exact general execution option')
    execution.__post_init__();policy=execution.policy
    source=Path(__file__).resolve().parents[2]
    build=parse(execution.build_bytes);raw=dumps_root(root)
    contract=execution_contract_v3(root,source,FAST,backend=NATIVE_DOMAIN,build=build)
    authority=make_authority(root,raw,contract,policy,mode=execution.execution_mode,backend=NATIVE_DOMAIN,build=build,acceptance=None)
    profile=PublicationProfile()
    intent=make_intent(root.identity,key='0'*32,execution_seconds=policy.hard_seconds,
        maximum_output_bytes=policy.maximum_output_bytes,
        execution_budget=ExecutionBudget(policy.hard_seconds,policy.soft_seconds,policy.finalization_seconds),
        publication_profile=profile)
    job=dict(format=JOB_V4,contract=contract,intent=intent,horizon=horizon_preflight(root,policy),
        requirements=runtime_requirements(source),lifetime_policy=asdict(policy),
        limits=dict(rss_bytes=policy.maximum_rss_bytes,native_bytes=policy.maximum_native_bytes,
            job_bytes=policy.maximum_output_bytes,slots=policy.maximum_jobs),
        entrypoint='ops_sim.v5.lifecycle_application:worker',native_import=False,execution_authority=authority)
    _job_metadata(job,root,source,raw)
    store=LifecycleStore(directory,root,create=True,project=lineage,project_document=document,
        runner_policy=policy,publication_profile=profile,execution_authority=authority)
    try:
        _write_new(store.path('portable-execution.json'),contract)
        _write_new(store.path('portable-job.json'),job)
        _write_new(store.path('lifetime-native-build.json'),build,65536)
    except BaseException as primary:
        try:store.close_publications()
        except BaseException as secondary:primary.add_note('B67 secondary store close: '+repr(secondary))
        raise
    return store
