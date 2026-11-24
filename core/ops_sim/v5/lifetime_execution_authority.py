"""B63 execution permission, separate from model admission and process doctor.

Planning an input or reading a result grants no right to execute it.  The new
authority is exact DATA, bound to one input/source/runtime/policy/backend.  A
bounded pilot is available to obtain genuine evidence; LONG rechecks saved
Linux day, direct-restore and ownership evidence, never a manually set flag.
"""
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import os
import stat

FORMAT = 'B63_LIFETIME_EXECUTION_AUTHORITY_V1'
DOMAIN = 'B63_EXACT_HORIZON_INDEPENDENT_INPUT_DOMAIN_V1'
ACCEPTANCE = 'B63_GENUINE_BACKEND_DOMAIN_ACCEPTANCE_V1'
BACKEND_FORMAT = 'B63_BACKEND_EXECUTION_BINDING_V1'
BACKEND_METHOD = 'B63_PREPARED_NATIVE_V1'
TYPED_BACKEND_FORMAT = 'B64_TYPED_BACKEND_EXECUTION_BINDING_V1'
TYPED_CONTRACT_FORMAT = 'B64_TYPED_LIFETIME_EXECUTION_CONTRACT_V3'
TYPED_CONTRACT_FORMAT_V4='B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4'
TYPED_BACKEND_FORMAT_V2='B65_TYPED_BACKEND_EXECUTION_BINDING_V2'
PILOT = 'PILOT'
LONG = 'LONG'
USER_LONG = 'YEAR_V1_AUTHORED_LOCAL_EXPERIMENT_NOT_QUALIFICATION'
PILOT_SECONDS = 86400
PILOT_PRIMARY_SEGMENTS = 8
PILOT_DIAGNOSTIC_SLOTS = 2
PILOT_HARD_SECONDS = 240
MAX_EVIDENCE_BYTES = 2**20


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf8')


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _hash(value, name):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('B63 exact SHA256: ' + name)
    return value


def _fields(value, names, name):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('B63 exact ' + name + ' fields')
    return value


def _text(value, name, maximum=4096):
    if type(value) is not str or not 0 < len(value.encode('utf8')) <= maximum:
        raise ValueError('B63 bounded text: ' + name)
    return value


def _integer(value, name, low=0, high=2**63-1):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('B63 exact finite integer: ' + name)
    return value


def _parse(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_EVIDENCE_BYTES:
        raise ValueError('B63 bounded authority/evidence bytes')
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('B63 duplicate evidence key')
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('B63 nonfinite evidence')))


def _regular(path, maximum=MAX_EVIDENCE_BYTES):
    p = Path(path).absolute()
    for node in (p, *p.parents):
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('B63 evidence link/reparse path')
    info = p.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum or info.st_nlink != 1:
        raise ValueError('B63 bounded regular single-link evidence')
    raw = p.read_bytes()
    after = p.stat()
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('B63 evidence changed while read')
    return raw


def reference(path):
    """Freeze an existing evidence file; this operation grants no permission."""
    p = Path(path).absolute()
    raw = _regular(p)
    return dict(path=str(p), sha256=sha256(raw).hexdigest(), bytes=len(raw))


def _read_reference(value):
    _fields(value, ('path', 'sha256', 'bytes'), 'evidence reference')
    _text(value['path'], 'evidence path')
    _hash(value['sha256'], 'evidence')
    _integer(value['bytes'], 'evidence size', 1, MAX_EVIDENCE_BYTES)
    raw = _regular(value['path'])
    if len(raw) != value['bytes'] or sha256(raw).hexdigest() != value['sha256']:
        raise ValueError('B63 evidence raw binding')
    return _parse(raw)


def _build_receipt(value):
    _fields(value, ('format', 'artifact', 'runtime', 'engine_source_sha256',
                    'compiler', 'capabilities', 'capability_sha256'), 'native build receipt')
    if value['format'] != 'B63_NATIVE_BUILD_RECEIPT_V1':
        raise ValueError('B63 native build receipt version')
    artifact = _fields(value['artifact'], ('path', 'sha256', 'bytes'), 'build artifact')
    name = _text(artifact['path'], 'build artifact path')
    parts = PurePosixPath(name).parts
    if '\\' in name or ':' in name or name.startswith('/') or any(p in ('', '.', '..') for p in parts) or '/'.join(parts) != name:
        raise ValueError('B63 build artifact relative path')
    _hash(artifact['sha256'], 'build binary')
    _integer(artifact['bytes'], 'build binary bytes', 1, 128*2**20)
    runtime = _fields(value['runtime'], ('implementation', 'python', 'cache_tag',
                                        'ext_suffix', 'platform', 'machine'), 'build runtime')
    for key, item in runtime.items():
        _text(item, 'build runtime ' + key)
    _hash(value['engine_source_sha256'], 'build engine source')
    compiler = _fields(value['compiler'], ('name', 'version', 'flags'), 'compiler')
    _text(compiler['name'], 'compiler name')
    _text(compiler['version'], 'compiler version')
    if type(compiler['flags']) is not list or len(compiler['flags']) > 128:
        raise ValueError('B63 compiler flags')
    for flag in compiler['flags']:
        _text(flag, 'compiler flag', 1024)
    if type(value['capabilities']) is not dict or not value['capabilities']:
        raise ValueError('B63 actual native capability DATA required')
    _hash(value['capability_sha256'], 'build capabilities')
    if digest(value['capabilities']) != value['capability_sha256']:
        raise ValueError('B63 native capability content binding')
    if len(canonical(value)) > 65536:
        raise ValueError('B63 native build receipt bytes')
    return value


def backend_binding(selection='REFERENCE', build=None):
    """Bind backend DATA; its owner separately checks the actual binary/FP probe."""
    if type(selection) is not str or selection not in ('REFERENCE', 'PREPARED_PYTHON', 'PREPARED_NATIVE'):
        raise ValueError('B63 explicit numerical backend')
    if selection == 'PREPARED_NATIVE':
        build = _build_receipt(build)
        build_sha, capability_sha = digest(build), build['capability_sha256']
    else:
        if build is not None:
            raise ValueError('B63 nonnative execution cannot claim native build')
        build_sha = capability_sha = None
    return dict(format=BACKEND_FORMAT, method=BACKEND_METHOD, selection=selection,
                build_sha256=build_sha, capability_sha256=capability_sha)


def typed_backend_binding(selection,build):
    """New exact typed DATA identity; never an option on the B63 container."""
    from .lifecycle_typed_backend import admit_build_data,FULL_DOMAIN,SUPPORT_DOMAIN,METHOD,NEW_DOMAIN
    if type(selection)is not str or selection not in (FULL_DOMAIN,SUPPORT_DOMAIN,NEW_DOMAIN):
        raise ValueError('B64 explicit typed backend domain')
    build=admit_build_data(build)
    if build['execution_domain']!=selection:raise ValueError('B64 typed selection/build domain mismatch')
    return dict(format=TYPED_BACKEND_FORMAT_V2 if selection==NEW_DOMAIN else TYPED_BACKEND_FORMAT,method=NEW_DOMAIN if selection==NEW_DOMAIN else METHOD,selection=selection,
        build_sha256=digest(build),capability_sha256=build['capability_sha256'])


def _admit_backend_binding(value):
    _fields(value, ('format', 'method', 'selection', 'build_sha256', 'capability_sha256'), 'backend binding')
    if value['format']in(TYPED_BACKEND_FORMAT,TYPED_BACKEND_FORMAT_V2):
        from .lifecycle_typed_backend import FULL_DOMAIN,SUPPORT_DOMAIN,METHOD,NEW_DOMAIN
        if (type(value['format'])is not str or type(value['method'])is not str or value['method']!=(NEW_DOMAIN if value['format']==TYPED_BACKEND_FORMAT_V2 else METHOD) or
                type(value['selection'])is not str or value['selection']not in ((NEW_DOMAIN,)if value['format']==TYPED_BACKEND_FORMAT_V2 else(FULL_DOMAIN,SUPPORT_DOMAIN))):
            raise ValueError('B64 exact typed backend binding')
        _hash(value['build_sha256'],'typed native build receipt');_hash(value['capability_sha256'],'typed native capabilities')
        return value
    if value['format'] != BACKEND_FORMAT or value['method'] != BACKEND_METHOD or type(value['selection']) is not str or value['selection'] not in ('REFERENCE', 'PREPARED_PYTHON', 'PREPARED_NATIVE'):
        raise ValueError('B63 exact named backend binding')
    if value['selection'] == 'PREPARED_NATIVE':
        _hash(value['build_sha256'], 'native build receipt')
        _hash(value['capability_sha256'], 'native capabilities')
    elif value['build_sha256'] is not None or value['capability_sha256'] is not None:
        raise ValueError('B63 nonnative backend cannot claim a native build')
    return value


def _admit_reference_data(value):
    _fields(value, ('path', 'sha256', 'bytes'), 'evidence reference')
    _text(value['path'], 'evidence path')
    _hash(value['sha256'], 'evidence')
    _integer(value['bytes'], 'evidence size', 1, MAX_EVIDENCE_BYTES)
    return value


def admit_authority_data(value):
    """Pure strict DATA admission for a new store; not execution permission.

    The complete contextual/genuine-evidence gate remains admit_authority and
    admit_store_execution.  This pure reader does not access files or runtime.
    """
    _fields(value, ('format', 'mode', 'binding', 'acceptance', 'pilot_limits', 'identity'), 'execution authority')
    if value['format'] != FORMAT or type(value['mode']) is not str or value['mode'] not in (PILOT, LONG, USER_LONG):
        raise ValueError('B63 named execution authority')
    body = _fields(value['binding'], ('root_identity', 'input_sha256', 'source_manifest_sha256',
        'runtime', 'execution_contract_sha256', 'policy_identity', 'backend_binding',
        'domain_identity', 'original_anchor_seconds', 'duration_seconds'), 'authority binding')
    for key in ('root_identity', 'input_sha256', 'source_manifest_sha256',
                'execution_contract_sha256', 'policy_identity', 'domain_identity'):
        _hash(body[key], 'authority ' + key)
    runtime = _fields(body['runtime'], ('python', 'platform', 'executable', 'interpreter_sha256'), 'authority runtime')
    for key in ('python', 'platform', 'executable'):
        _text(runtime[key], 'authority runtime ' + key)
    _hash(runtime['interpreter_sha256'], 'runtime interpreter')
    _admit_backend_binding(body['backend_binding'])
    _integer(body['original_anchor_seconds'], 'original anchor', 0, 2**40)
    _integer(body['duration_seconds'], 'duration', 1, 15*31557600)
    limits = dict(duration_seconds=PILOT_SECONDS, primary_segments=PILOT_PRIMARY_SEGMENTS,
                  diagnostic_slots=PILOT_DIAGNOSTIC_SLOTS, hard_seconds=PILOT_HARD_SECONDS)
    if canonical(value['pilot_limits']) != canonical(limits):
        raise ValueError('B63 exact declared pilot bounds')
    if value['mode'] == PILOT:
        if value['acceptance'] is not None or body['duration_seconds'] > PILOT_SECONDS:
            raise ValueError('B63 bounded pilot authority DATA')
    elif value['mode']==USER_LONG:
        if value['acceptance'] is not None or body['duration_seconds']>31557600:
            raise ValueError('YEAR-V1 local experiment is not accepted LONG qualification')
    else:
        _admit_reference_data(value['acceptance'])
    _hash(value['identity'], 'authority identity')
    if value['identity'] != digest({k: v for k, v in value.items() if k != 'identity'}) or len(canonical(value)) > 16384:
        raise ValueError('B63 immutable authority content/byte limit')
    return json.loads(canonical(value))


def domain_identity(root):
    """All physical/numerical/control/anchor data retained; ONLY duration removed.

    B62 accounting caps are fixed across horizons.  No quota, accuracy, nested
    digest or declared physical value is removed from this stricter domain.
    """
    from .lifecycle_document import dumps_root
    document = json.loads(dumps_root(root))
    return domain_from_document(document,root.start_seconds)


def domain_from_document(document,original_anchor_seconds):
    """Pure DATA counterpart for result inspection; grants no model admission."""
    _fields(document,('format','version','inputs','digest'),'domain input envelope')
    _integer(original_anchor_seconds,'domain original anchor',0,2**40)
    if type(document['format'])is not str or type(document['version'])is not int or type(document['inputs'])is not dict:
        raise ValueError('B63 domain input envelope DATA types')
    _hash(document['digest'],'domain input digest')
    _integer(document['inputs'].get('duration_seconds'),'domain duration',1,15*31557600)
    if digest({k:document[k]for k in ('format','version','inputs')})!=document['digest']:
        raise ValueError('B63 domain input content digest')
    document=json.loads(canonical(document))
    document.pop('digest')
    document['inputs'].pop('duration_seconds')
    return digest(dict(format=DOMAIN, exclusions=['digest', 'inputs.duration_seconds'],
                       input=document, original_anchor_seconds=original_anchor_seconds))


def _binding(root, raw, contract, policy, backend, build):
    from .lifecycle_document import dumps_root
    from . import lifetime_policy
    from .project_store import runtime_identity
    policy_types = tuple(getattr(lifetime_policy, name) for name in ('LifetimeCampaignPolicy', 'LifetimeCampaignPolicyV2') if hasattr(lifetime_policy, name))
    if type(policy) not in policy_types:
        raise TypeError('B63 exact lifetime policy')
    policy.__post_init__()
    if type(raw) is not bytes or raw != dumps_root(root):
        raise ValueError('B63 exact original owner input bytes')
    if type(contract) is not dict:
        raise TypeError('B63 exact execution contract')
    expected_backend = (typed_backend_binding(backend,build) if contract.get('format')in(TYPED_CONTRACT_FORMAT,TYPED_CONTRACT_FORMAT_V4) else backend_binding(backend, build))
    if canonical(contract.get('backend_binding')) != canonical(expected_backend):
        raise ValueError('B63 contract/backend/build drift')
    source_hash = _hash(contract.get('source_manifest_sha256'), 'execution source')
    if type(contract.get('source_manifest')) is not dict or digest(contract['source_manifest']) != source_hash:
        raise ValueError('B63 execution source manifest binding')
    current = runtime_identity()
    if canonical(contract.get('runtime')) != canonical(current):
        raise ValueError('B63 actual execution runtime binding')
    if contract.get('root_identity') != root.identity or contract.get('input_sha256') != sha256(raw).hexdigest():
        raise ValueError('B63 exact execution input binding')
    return dict(root_identity=root.identity, input_sha256=sha256(raw).hexdigest(),
                source_manifest_sha256=source_hash, runtime=current,
                execution_contract_sha256=digest(contract), policy_identity=policy.identity,
                backend_binding=expected_backend, domain_identity=domain_identity(root),
                original_anchor_seconds=root.start_seconds, duration_seconds=root.duration_seconds)


def _qualification_binding(binding):
    return {key: binding[key] for key in ('source_manifest_sha256', 'runtime',
                                         'backend_binding', 'domain_identity')}


def admit_long_evidence(ref, binding):
    """Recompute genuine saved evidence; no boolean or caller verifier hook."""
    wrapper = _read_reference(ref)
    _fields(wrapper, ('format', 'qualification_binding', 'genuine_evidence'), 'genuine acceptance')
    if wrapper['format'] != ACCEPTANCE or canonical(wrapper['qualification_binding']) != canonical(_qualification_binding(binding)):
        raise ValueError('B63 acceptance source/runtime/backend/build/domain mismatch')
    genuine = _read_reference(wrapper['genuine_evidence'])
    if genuine.get('format')=='B65_GENUINE_TYPED_TARGET_EVIDENCE_V2':
        if binding['backend_binding']['selection']!='B65_TYPED_EXECUTION_V2':raise ValueError('B65 acceptance cannot grant another backend')
        from .lifetime_typed_acceptance import admit
        return dict(format=ACCEPTANCE,evidence_sha256=ref['sha256'],qualification_binding=_qualification_binding(binding),
            computed=admit(wrapper['genuine_evidence']['path'],binding),physical_qualification=False)
    from .lifetime_server_acceptance import admit_acceptance
    result = admit_acceptance(wrapper['genuine_evidence']['path'], binding['source_manifest_sha256'])
    # The legacy verifier proves actual day/equality/ownership, but did not know
    # a numerical backend.  Both actual day stores must supply the NEW binding.
    from .lifetime_supervisor import _store
    for key in ('reference_store', 'continuation_store'):
        store, _ = _store(genuine[key])
        try:
            contract = _parse(_regular(store.path('portable-execution.json')))
            if canonical(contract.get('backend_binding')) != canonical(binding['backend_binding']) or domain_identity(store.root_input) != binding['domain_identity']:
                raise ValueError('B63 genuine day backend/build/domain mismatch')
        finally:
            store.close_publications()
    return dict(format=ACCEPTANCE, evidence_sha256=ref['sha256'],
                qualification_binding=_qualification_binding(binding),
                computed=result, physical_qualification=False)


def make_authority(root, raw, contract, policy, *, mode=PILOT, backend='REFERENCE',
                   build=None, acceptance=None):
    binding = _binding(root, raw, contract, policy, backend, build)
    value = dict(format=FORMAT, mode=mode, binding=binding, acceptance=acceptance,
                 pilot_limits=dict(duration_seconds=PILOT_SECONDS,
                     primary_segments=PILOT_PRIMARY_SEGMENTS,
                     diagnostic_slots=PILOT_DIAGNOSTIC_SLOTS, hard_seconds=PILOT_HARD_SECONDS))
    value['identity'] = digest(value)
    return admit_authority(value, root, raw, contract, policy, backend=backend, build=build)


def admit_authority(value, root, raw, contract, policy, *, backend='REFERENCE', build=None):
    admit_authority_data(value)
    expected = _binding(root, raw, contract, policy, backend, build)
    if canonical(value['binding']) != canonical(expected) or value['identity'] != digest({k: v for k, v in value.items() if k != 'identity'}):
        raise ValueError('B63 immutable execution authority drift')
    limits = dict(duration_seconds=PILOT_SECONDS, primary_segments=PILOT_PRIMARY_SEGMENTS,
                  diagnostic_slots=PILOT_DIAGNOSTIC_SLOTS, hard_seconds=PILOT_HARD_SECONDS)
    if canonical(value['pilot_limits']) != canonical(limits):
        raise ValueError('B63 exact declared pilot bounds')
    if value['mode'] == PILOT:
        if value['acceptance'] is not None:
            raise ValueError('B63 pilot does not claim long acceptance')
        if (root.duration_seconds > PILOT_SECONDS or policy.maximum_primary_segments > PILOT_PRIMARY_SEGMENTS or
                policy.reserved_diagnostic_slots > PILOT_DIAGNOSTIC_SLOTS or policy.hard_seconds > PILOT_HARD_SECONDS):
            raise ValueError('B63 bounded pilot duration/population/deadline')
    elif value['mode']==USER_LONG:
        from .lifetime_policy import WINDOWS_USER,is_v2
        from .lifetime_admission import ACCOUNTING
        if (not is_v2(policy) or policy.mode!=WINDOWS_USER or value['acceptance'] is not None or
                backend!='B65_TYPED_EXECUTION_V2' or root.duration_seconds>31557600 or
                root.policy.method!=ACCOUNTING or root.sun_mode!='REDUCED_ASSUMED_ANNUAL_V1' or
                root.environment_ageing_policy is None or root.battery_port_policy is None or
                root.energy_attitude_policy is None or root.output_policy is None):
            raise ValueError('YEAR-V1 exact authored serial experimental domain')
        from .year_project import _world
        _world(root) # complete stationary declared study; no discarded forcing discontinuity
        from .lifecycle_execution import build_model
        world=build_model(root).environment
        if world.sun_table is not None or world.start_seconds!=root.start_seconds or world.end_seconds!=root.end_seconds:
            raise ValueError('YEAR-V1 full-domain declared annual world; no table extension')
    else:
        admit_long_evidence(value['acceptance'], expected)
    return json.loads(canonical(value))


def admit_store_execution(store):
    """One common owner gate, called before dispatch/reservation/intent writes.

    Older stores are not upgraded by this helper.  Read/export are independent.
    The integration owner must persist this authority at NEW store creation.
    """
    from .portable_job import worker_contract_for_store
    from .lifetime_policy import LifetimeCampaignPolicy, PRODUCTION
    p = store.runner_policy
    from .lifetime_policy import WINDOWS_USER,LifetimeCampaignPolicyV2
    if type(p)is LifetimeCampaignPolicyV2 and p.mode==WINDOWS_USER:
        lineage=store.meta.get('project')
        if type(lineage)is not dict or lineage.get('format')!='B68_BOUND_ROUTE_THERMAL_PROJECT_LINEAGE_V1':
            raise ValueError('YEAR-V1 experimental dispatch requires actual bound authored V3 lineage')
    # Historical stores remain readable.  Their only execution permission is a
    # bounded legacy pilot; the absence of new authority never grants LONG.
    if type(p) is LifetimeCampaignPolicy:
        if (store.root_input.duration_seconds > PILOT_SECONDS or p.maximum_primary_segments > PILOT_PRIMARY_SEGMENTS or
                p.reserved_diagnostic_slots > PILOT_DIAGNOSTIC_SLOTS or p.hard_seconds > PILOT_HARD_SECONDS):
            raise ValueError('B63 legacy store has no qualified long execution authority')
        admitted = dict(format='B63_BOUNDED_LEGACY_PILOT_DISPATCH_ONLY_V1', mode=PILOT,
                        root_identity=store.root_input.identity, policy_identity=p.identity)
        if p.mode == PRODUCTION:
            from kit.serverctl import doctor
            if not doctor(Path(__file__).resolve().parents[2])['ready_for_engine_attempt']:
                raise ValueError('B63 production Linux doctor prerequisite')
        return admitted
    value = _parse(_regular(store.path('execution-authority.json')))
    admit_authority_data(value)
    if store.meta.get('execution_authority_sha256') != digest(value):
        raise ValueError('B63 store/authority raw canonical SHA256 binding')
    contract = worker_contract_for_store(store, Path(__file__).resolve().parents[2])
    backend = contract.get('backend_binding', {}).get('selection')
    build = None
    if backend in ('PREPARED_NATIVE','B64_TYPED_EXECUTION_V1','B64_TYPED_COUPLED_LEGACY_QUIET_CONTROL_V1','B65_TYPED_EXECUTION_V2'):
        build = _parse(_regular(store.path('lifetime-native-build.json'), 65536))
    raw = _regular(store.path('input.json'), 8*2**20)
    admitted = admit_authority(value, store.root_input, raw, contract, store.runner_policy,
                               backend=backend, build=build)
    if p.mode == PRODUCTION:
        from kit.serverctl import doctor
        if not doctor(Path(__file__).resolve().parents[2])['ready_for_engine_attempt']:
            raise ValueError('B63 production Linux doctor prerequisite')
    return admitted


def admit_public_execution(store):
    """Admit every public execution route, including nonportable legacy stores.

    Generic finite/legacy stores remain usable for short roots; their policy
    names and accounting caps are never a substitute for qualified LONG
    authority.  This gate is read-only and must precede ownership, reservation,
    job-intent and dispatch writes.  Planning/read/export do not call it.
    """
    from .lifecycle_contract import LifecycleRoot
    from .lifecycle_runner_policy import LifecycleRunnerStorePolicy
    from .finite_campaign import FiniteCampaignPolicy
    from .lifetime_policy import LifetimeCampaignPolicy, LifetimeCampaignPolicyV2
    root = store.root_input
    policy = store.runner_policy
    if type(root) is not LifecycleRoot:
        raise TypeError('B63 exact real LifecycleRoot execution authority')
    if policy is not None and type(policy) not in (LifecycleRunnerStorePolicy,
            FiniteCampaignPolicy, LifetimeCampaignPolicy, LifetimeCampaignPolicyV2):
        raise TypeError('B63 exact public execution store policy')
    root.__post_init__()
    if policy is not None:
        policy.__post_init__()
    if type(policy) in (LifetimeCampaignPolicy, LifetimeCampaignPolicyV2):
        return admit_store_execution(store)
    if root.duration_seconds > PILOT_SECONDS:
        raise ValueError('B63 generic legacy/finite store has no qualified long execution authority')
    return dict(format='B63_BOUNDED_GENERIC_LEGACY_PILOT_DISPATCH_ONLY_V1',
                mode=PILOT, root_identity=root.identity,
                policy_identity=None if policy is None else policy.identity,
                maximum_duration_seconds=PILOT_SECONDS,
                qualified_long_execution=False)


def admit_worker_execution(directory):
    """Read and pin a real store BEFORE any worker fallback or output write.

    ``LifecycleStore(create=False)`` performs strict typed root/metadata/source
    admission without claiming ownership, creating jobs or opening publication
    writers.  This deliberately does not depend on portable files being present;
    a V2 authority omission and a legacy long root both fail before fallback.
    """
    from .lifecycle_application import LifecycleStore
    directory = Path(directory).absolute()
    _parse(_regular(directory / 'store.json'))
    _regular(directory / 'input.json', 16*2**20)
    store = LifecycleStore(directory)
    try:
        store._pinned()
        admitted = admit_public_execution(store)
        store._pinned()
        return admitted
    finally:
        store.close_publications()
