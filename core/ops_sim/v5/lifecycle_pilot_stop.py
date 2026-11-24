"""B63 immutable PILOT wrapper stop, after an actual committed step only.

This sidecar never inserts a model cut, changes a clock/input, evaluates a
forecast or grants execution permission. The normal dispatch/worker gates own
permission. It only requests the existing cooperative checkpoint/settlement
path after a returned actual CONTACT has a retained partial record at or above
the declared threshold. Separate records are never summed to reach it.
"""
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
import json
import stat


FORMAT = 'B63_IMMUTABLE_PILOT_STOP_RULE_V1'
KIND = 'PENDING_CONTACT_MINIMUM_PARTIAL_BITS_V1'
SCOPE = 'WRAPPER_STOP_AFTER_COMMITTED_ACTUAL_STEP_NOT_NUMERICAL_POLICY'
FILENAME = 'pilot-stop-rule.json'
MAX_BYTES = 4096
MAX_TRIGGER_BYTES = 16384
MAX_BITS = 2**53 - 1
FIELDS = ('format', 'kind', 'job_id', 'root_identity', 'input_sha256',
          'request_sha256', 'execution_contract_sha256', 'source_manifest_sha256',
          'minimum_partial_bits', 'scope', 'identity')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf8')


def _hash(value, name):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('B63 pilot stop exact SHA256: ' + name)
    return value


def _jid(value):
    if type(value) is not str or len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('B63 pilot stop exact job ID')
    return value


def _integer(value, name, low=0, high=2**40):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('B63 pilot stop exact bounded integer: ' + name)
    return value


def _parse(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('B63 pilot stop bounded raw bytes')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('B63 pilot stop duplicate key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('B63 pilot stop nonfinite DATA')))


def _read(path, maximum=MAX_BYTES):
    from .project_store import ProjectStore
    path = Path(path)
    ProjectStore._reject_links(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
        raise ValueError('B63 pilot stop bounded single-link regular file')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    after = path.stat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or len(raw) != before.st_size):
        raise ValueError('B63 pilot stop file changed while read')
    return raw


@dataclass(frozen=True, slots=True)
class PilotStopRule:
    format: str
    kind: str
    job_id: str
    root_identity: str
    input_sha256: str
    request_sha256: str
    execution_contract_sha256: str
    source_manifest_sha256: str
    minimum_partial_bits: int
    scope: str
    identity: str

    def __post_init__(self):
        for name, expected in (('format', FORMAT), ('kind', KIND), ('scope', SCOPE)):
            if type(getattr(self, name)) is not str or getattr(self, name) != expected:
                raise ValueError('B63 pilot stop named enum: ' + name)
        _jid(self.job_id)
        for name in ('root_identity', 'input_sha256', 'request_sha256',
                     'execution_contract_sha256', 'source_manifest_sha256', 'identity'):
            _hash(getattr(self, name), name)
        _integer(self.minimum_partial_bits, 'minimum partial bits', 1, MAX_BITS)
        value = asdict(self)
        identity = value.pop('identity')
        if sha256(_canonical(value)).hexdigest() != identity or len(_canonical(asdict(self))) > MAX_BYTES:
            raise ValueError('B63 pilot stop immutable content binding')


def _rule(value):
    if type(value) is not dict or set(value) != set(FIELDS):
        raise ValueError('B63 pilot stop exact schema')
    return PilotStopRule(**value)


def _contract_binding(contract, root):
    from .lifetime_portable import admit_execution_contract_data_v2
    from .lifetime_typed_portable import FORMAT_V3,FORMAT_V4,admit_execution_contract_data_v3
    from .lifecycle_contract import LifecycleRoot
    if type(root) is not LifecycleRoot:
        raise TypeError('B63 pilot stop exact lifecycle root')
    if type(contract)is dict and contract.get('format')in(FORMAT_V3,FORMAT_V4):admit_execution_contract_data_v3(contract)
    else:admit_execution_contract_data_v2(contract)
    if contract['root_identity'] != root.identity:
        raise ValueError('B63 pilot stop foreign root/contract')
    return dict(root_identity=root.identity, input_sha256=contract['input_sha256'],
                execution_contract_sha256=sha256(_canonical(contract)).hexdigest(),
                source_manifest_sha256=contract['source_manifest_sha256'])


def arm(store, jid, minimum_partial_bits):
    """Exclusive pre-launch publication, after the complete common gate.

    Called by LifecycleStore.arm_pilot_stop from the runner's on_launch hook,
    before the owned thread/child starts. Failed reservations remain paid;
    neither an existing rule nor an already admitted/running job is repaired.
    """
    from .lifecycle_application import LifecycleStore, _write_new, _read as application_read
    from .lifetime_policy import is_v2
    from .lifetime_execution_authority import admit_store_execution, PILOT
    from .portable_job import worker_contract
    if type(store) is not LifecycleStore:
        raise TypeError('B63 pilot stop exact lifecycle store')
    _jid(jid)
    _integer(minimum_partial_bits, 'minimum partial bits', 1, MAX_BITS)
    with store.lock:
        if not is_v2(store.runner_policy):
            raise ValueError('B63 pilot stop requires V2 store')
        authority = admit_store_execution(store)  # BEFORE any publication.
        if type(authority) is not dict or authority.get('mode') != PILOT:
            raise ValueError('B63 pilot stop requires fully admitted PILOT authority')
        store._pinned()
        job = store.job(jid)
        if (job['job_id'] != jid or type(job['status']) is not str or job['status'] != 'QUEUED' or
                job['launch'] is not None or job['result'] is not None or job['ownership_valid'] is not None or
                store.path('jobs', jid, 'parent-launch-authority.json').exists()):
            raise ValueError('B63 pilot stop requires QUEUED job before owned launch')
        path = store.path('jobs', jid, FILENAME)
        if path.exists():
            raise FileExistsError('B63 immutable pilot stop rule already exists')
        request_path = store.path('jobs', jid, 'request.json')
        raw_request = _read(request_path, 256 * 1024)
        request_sha = sha256(raw_request).hexdigest()
        contract = worker_contract(store.directory, Path(__file__).resolve().parents[2],
                                   job_id=jid, request_sha256=request_sha)
        binding = _contract_binding(contract, store.root_input)
        request = application_read(request_path)
        if (request.get('job_id') != jid or request.get('root_identity') != binding['root_identity'] or
                request.get('input_sha256') != binding['input_sha256'] or
                any(request.get(name) != job.get(name) for name in
                    ('format', 'intent', 'root_identity', 'source_identity', 'runtime', 'input_sha256', 'resume')) or
                authority.get('binding', {}).get('execution_contract_sha256') != binding['execution_contract_sha256']):
            raise ValueError('B63 pilot stop request/common authority binding')
        value = dict(format=FORMAT, kind=KIND, job_id=jid, request_sha256=request_sha,
                     minimum_partial_bits=minimum_partial_bits, scope=SCOPE, **binding)
        value['identity'] = sha256(_canonical(value)).hexdigest()
        rule = _rule(value)
        raw = _canonical(asdict(rule))
        store._parent_codec_charge(jid, 16 * len(raw) + 65536)
        store._parent_charge(jid, len(raw))
        receipt = _write_new(path, raw, MAX_BYTES)
        return dict(**receipt, rule=asdict(rule), numerical_policy_changed=False,
                    scope=SCOPE)


def admit_rule(directory, jid, expected_request_sha, contract, root):
    """Read immutable saved DATA after normal worker execution admission.

    Absence means no special wrapper stop. This function itself never grants
    permission to execute, and never creates/migrates a legacy sidecar.
    """
    _jid(jid)
    _hash(expected_request_sha, 'expected request')
    directory = Path(directory)
    path = directory / 'jobs' / jid / FILENAME
    from .project_store import ProjectStore
    ProjectStore._reject_links(path)
    if not path.exists():
        return None
    binding = _contract_binding(contract, root)
    raw = _read(path)
    rule = _rule(_parse(raw))
    if raw != _canonical(asdict(rule)):
        raise ValueError('B63 pilot stop canonical raw binding')
    if (rule.job_id != jid or rule.request_sha256 != expected_request_sha or
            any(getattr(rule, name) != value for name, value in binding.items()) or
            sha256(_read(directory / 'jobs' / jid / 'request.json', 256 * 1024)).hexdigest() != expected_request_sha):
        raise ValueError('B63 pilot stop stale/foreign request/source/input/contract')
    from .lifetime_execution_authority import admit_authority_data, PILOT, _parse as parse_authority
    authority_raw = _read(directory / 'execution-authority.json', 16384)
    authority = admit_authority_data(parse_authority(authority_raw))
    if (authority['mode'] != PILOT or
            any(authority['binding'][name] != value for name, value in binding.items())):
        raise ValueError('B63 pilot stop requires same PILOT execution authority')
    return rule


def _selected_data(rule, state):
    from .lifecycle_state import LifecycleState
    from .lifecycle_physics import LifecyclePhysicalState, PendingLifecycleAction, LifecycleActionOutcome
    from .lifecycle_contract import LifecycleRoot
    from .lifecycle_backend import BackendContext
    from .lifecycle_typed_context import TypedBackendContext
    from .lifecycle_orbit import LifecycleOrbitProvider
    from .context import SimulationContext
    from .data_delivery import GroundDataDeliveryState, DownlinkTransferProgress
    from .ids import AcquisitionDataRecordId
    from .long_mission import LongMissionAction
    if type(rule) is not PilotStopRule:
        raise TypeError('B63 exact admitted immutable pilot stop rule')
    rule.__post_init__()
    if type(state) is not LifecycleState or type(state.root) is not LifecycleRoot:
        raise TypeError('B63 pilot stop exact committed lifecycle state')
    if (type(state.root_identity) is not str or type(state.root.identity) is not str or
            state.root_identity != rule.root_identity or state.root.identity != rule.root_identity):
        raise ValueError('B63 pilot stop selected root drift')
    physical, backend = state.physical, state.backend_context
    if (type(physical) is not LifecyclePhysicalState or type(backend) not in (BackendContext,TypedBackendContext) or
            backend is not physical.backend_context or backend.root is not state.root or
            backend.model is not state.model or type(backend.source_binding) is not str or
            backend.source_binding != rule.source_manifest_sha256 or
            type(state.actual_provider) is not LifecycleOrbitProvider or
            physical.nominal_provider is not state.actual_provider or
            type(state.actual_provider.role) is not str or state.actual_provider.role != 'ACTUAL' or
            type(physical.context) is not SimulationContext):
        raise ValueError('B63 pilot stop selected actual/source ownership')
    _integer(state.transition_count, 'committed transitions')
    clock = _integer(state.clock, 'committed clock')
    if type(state.status) is not str:
        raise TypeError('B63 pilot stop exact lifecycle status')
    if state.status != 'ACTIVE' or state.transition_count == 0 or physical.pending is None:
        return None
    if type(physical.pending) is not PendingLifecycleAction or type(physical.pending.action) is not LongMissionAction:
        raise TypeError('B63 pilot stop exact pending action')
    pending, outcome = physical.pending, state.last_outcome
    if type(pending.kind) is not str:
        raise TypeError('B63 pilot stop exact pending kind')
    if pending.kind != 'CONTACT':
        return None
    if (type(outcome) is not LifecycleActionOutcome or type(outcome.kind) is not str or
            outcome.kind != 'CONTACT' or type(outcome.status) is not str or outcome.status != 'partial' or
            type(outcome.action_id) is not str or type(pending.action.action_id) is not str or
            outcome.action_id != pending.action.action_id):
        raise ValueError('B63 pilot stop requires returned partial CONTACT outcome')
    for name, value in (('outcome start', outcome.start_seconds), ('outcome end', outcome.end_seconds),
                        ('pending origin', pending.origin_seconds), ('pending end', pending.end_seconds)):
        _integer(value, name)
    if not pending.origin_seconds <= outcome.start_seconds < outcome.end_seconds == clock < pending.end_seconds:
        raise ValueError('B63 pilot stop requires positive already committed CONTACT step')
    delivery = physical.context.ground_data_delivery_state
    if type(delivery) is not GroundDataDeliveryState or type(delivery.partial_transfers) is not tuple or len(delivery.partial_transfers) > 16:
        raise TypeError('B63 pilot stop bounded actual partial records')
    records = []
    for progress in delivery.partial_transfers:
        if type(progress) is not DownlinkTransferProgress or type(progress.record_id) is not AcquisitionDataRecordId:
            raise TypeError('B63 pilot stop exact actual partial progress')
        bits = progress.transmitted_equivalent_bits
        if type(bits) is not float or not isfinite(bits) or not 0 < bits <= MAX_BITS or not bits.is_integer():
            raise ValueError('B63 pilot stop actual integer-valued partial bits')
        name = progress.record_id.value
        if type(name) is not str or not 0 < len(name.encode('utf8')) <= 256:
            raise ValueError('B63 pilot stop actual record ID')
        records.append(dict(record_id=name, partial_bits=int(bits), partial_bits_hex=bits.hex()))
    if len({r['record_id'] for r in records}) != len(records):
        raise ValueError('B63 pilot stop duplicate actual record')
    return dict(clock_seconds=clock, transition_count=state.transition_count,
                pending_action_id=pending.action.action_id,
                actual_partial_records=records)


def matches(rule, state):
    """Pure post-step predicate; no forecast/trial, summation or model call."""
    data = _selected_data(rule, state)
    return data is not None and any(r['partial_bits'] >= rule.minimum_partial_bits
                                    for r in data['actual_partial_records'])


def trigger_receipt(rule, state):
    """Bound actual DATA for the existing wrapper Stop/checkpoint publication."""
    data = _selected_data(rule, state)
    if data is None or not any(r['partial_bits'] >= rule.minimum_partial_bits for r in data['actual_partial_records']):
        raise ValueError('B63 pilot stop rule has not matched actual selected state')
    value = dict(format='B63_ACTUAL_COMMITTED_PILOT_STOP_TRIGGER_V1',
                 rule=asdict(rule), rule_sha256=sha256(_canonical(asdict(rule))).hexdigest(),
                 scope=SCOPE, numerical_policy_changed=False, **data)
    if len(_canonical(value)) > MAX_TRIGGER_BYTES:
        raise ValueError('B63 pilot stop bounded trigger receipt')
    return value
