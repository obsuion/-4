"""B63 bounded status envelopes for explicitly versioned new lifetime stores.

The old job wire is the immutable details DATA, never a compressed logical
status record. A status head commits last. This is not a multi-file atomic
transaction: a failed details/head write leaves a charged orphan and quarantines
that publisher. No saved status or worker exit reconstructs OS ownership.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from .lifetime_io_accounting import fsync as _io_fsync
import json
import os
import re
import stat

STORAGE = 'B63_BOUNDED_STATUS_ENVELOPE_V1'
STORAGE_OBJECTS='YEAR_V2_OBJECT_STATUS_ENVELOPE_V1'
DETAILS_OBJECTS='YEAR_V2_CANONICAL_JOB_FIELD_REFS_V1'
STORAGE_PACKED='YEAR_V5_PACKED_STATUS_ENVELOPE_V1'
DETAILS_PACKED='YEAR_V5_PACKED_CANONICAL_JOB_FIELD_REFS_V1'
DETAILS = 'B63_IMMUTABLE_JOB_DETAILS_V1'
INDEX = 'B63_COMPACT_JOB_INDEX_V1'
ERROR = 'B63_INDEPENDENT_PARENT_ERROR_V1'
ERROR_RESERVATION = 'B63_PARENT_ERROR_RESERVATION_V1'
MAX_RECORD_BYTES = 65536
MAX_DETAILS_BYTES = 256 * 1024
MAX_ERROR_BYTES = 16384
MAX_ERRORS = 4
ERROR_RESERVED_BYTES = MAX_ERRORS * MAX_ERROR_BYTES + 4096
TERMINAL_RESERVE_BYTES = 2 * MAX_DETAILS_BYTES + ERROR_RESERVED_BYTES
BINDING_KEYS = ('job_id', 'root_identity', 'source_identity', 'runtime',
                'request_sha256', 'profile_identity', 'runner_policy_identity')
TERMINAL = ('COMPLETED', 'INCOMPLETE', 'CANCELLED', 'PROCESS_FAILED', 'REFUSED', 'UNKNOWN')
JOB_REQUIRED = ('format', 'job_id', 'intent', 'root_identity', 'source_identity',
                'runtime', 'input_sha256', 'resume', 'publication_sequence',
                'status', 'reason', 'progress', 'checkpoints', 'result', 'launch',
                'ownership_valid', 'created_utc', 'worker_artifact_bytes')
JOB_OPTIONAL = ('parent_failure', 'terminal_failure', 'typed_stop', 'last_actual_refusal')


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _same(left, right):
    return type(left) is type(right) and raw(left) == raw(right)


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('B63 exact status schema')


def _integer(value, low=0, high=2 ** 48):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('B63 exact bounded status integer')
    return value


def _digest(value, *, nullable=False):
    if nullable and value is None:
        return value
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('B63 status digest')
    return value


def _jobid(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{32}', value) is None:
        raise ValueError('B63 status job identity')
    return value


def admit_binding(value):
    _fields(value, BINDING_KEYS)
    _jobid(value['job_id'])
    for name in ('root_identity', 'source_identity', 'request_sha256', 'runner_policy_identity'):
        _digest(value[name])
    _digest(value['profile_identity'], nullable=True)
    if type(value['runtime']) is not dict or not value['runtime'] or len(raw(value['runtime'])) > 4096:
        raise ValueError('B63 bounded runtime identity')
    return deepcopy(value)


def make_binding(job, request_sha256, profile_identity, runner_policy_identity):
    return admit_binding(dict(job_id=job['job_id'], root_identity=job['root_identity'],
        source_identity=job['source_identity'], runtime=job['runtime'],
        request_sha256=request_sha256, profile_identity=profile_identity,
        runner_policy_identity=runner_policy_identity))


def _job(value, binding):
    if (type(value) is not dict or not set(JOB_REQUIRED) <= set(value)
            or set(value) - set(JOB_REQUIRED) - set(JOB_OPTIONAL)):
        raise ValueError('B63 details exact legacy job fields')
    for name in ('job_id', 'root_identity', 'source_identity', 'runtime'):
        if not _same(value[name], binding[name]):
            raise ValueError('B63 details job authority binding')
    _digest(value['input_sha256'])
    _integer(value['publication_sequence'])
    if (type(value['format']) is not str or not 1 <= len(value['format']) <= 128
            or type(value['intent']) is not dict or type(value['checkpoints']) is not list
            or len(value['checkpoints']) > 8
            or type(value['status']) is not str
            or value['status'] not in (*TERMINAL, 'QUEUED', 'ADMITTED', 'RUNNING', 'STOP_REQUESTED')
            or value['ownership_valid'] is not None and type(value['ownership_valid']) is not bool):
        raise ValueError('B63 details bounded job view')
    if value['intent'].get('root_identity') != binding['root_identity']:
        raise ValueError('B63 details intent root')
    if value['reason'] is not None and type(value['reason']) is not str:
        raise ValueError('B63 details reason type')
    return value


def _short(value, maximum=512):
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError('B63 bounded status text')
    return value[:maximum]


def _cliptext(value, maximum):
    return str(value).encode('utf-8')[:maximum].decode('utf-8', errors='ignore')


def _index_job(job):
    value = {name: deepcopy(job[name]) for name in JOB_REQUIRED}
    value.update(storage_view=INDEX, progress=None, checkpoints=[],
                 reason=_short(job['reason']))
    for name in ('typed_stop', 'last_actual_refusal'):
        if name in job:
            value[name] = deepcopy(job[name])
    if job['result'] is not None:
        names = ('typed_terminal', 'checkpoint', 'clock', 'actual_end_seconds',
                 'target_seconds', 'application_status', 'status', 'reason')
        value['result'] = {name: deepcopy(job['result'][name]) for name in names}
        value['result']['reason'] = _short(value['result']['reason'])
    if job['launch'] is not None:
        value['launch'] = {name: deepcopy(job['launch'].get(name)) for name in
                          ('observed_envelope_seconds', 'forced_interruption', 'timeout')}
        unexpected = job['launch'].get('unexpected')
        value['launch']['unexpected'] = None if unexpected is None else dict(
            type=_short(unexpected.get('type'), 128), reason=_short(unexpected.get('reason')))
    return value


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    """Only immutable canonical bytes cross the pure-admission/I/O boundary."""
    binding_raw: bytes
    details_raw: bytes
    envelope_raw: bytes
    sequence: int
    terminal: bool
    objects: tuple = ()

    @property
    def job(self):
        value=json.loads(self.details_raw)
        if value['format'] in (DETAILS_OBJECTS,DETAILS_PACKED):
            from .lifetime_status_objects import restore
            objects=dict(self.objects)
            return restore(value['fields'],lambda ref:objects[ref['path']])
        return value['job']

    @property
    def envelope(self):
        return json.loads(self.envelope_raw)


def preflight(fulljob, binding, *, object_store=False, packed_store=False):
    """Pure schema/size admission; never mutates a caller, sequence or writer."""
    if type(object_store)is not bool or type(packed_store)is not bool:raise ValueError('explicit status object policy')
    if packed_store:object_store=True
    binding = admit_binding(binding)
    value = deepcopy(fulljob)
    _job(value, binding)
    value['publication_sequence'] += 1
    details = dict(format=DETAILS, binding=binding, job=value)
    objects=()
    if object_store:
        from .lifetime_status_objects import prepare
        fields,objects=prepare(value)
        details=dict(format=DETAILS_PACKED if packed_store else DETAILS_OBJECTS,binding=binding,fields=fields)
    details_raw = raw(details)
    if len(details_raw) > MAX_DETAILS_BYTES:
        raise ValueError('B63 prospective details byte cap')
    reference = dict(path='details/' + str(value['publication_sequence']).zfill(8) +
                     '-' + sha256(details_raw).hexdigest() + '.json',
                     sha256=sha256(details_raw).hexdigest(), bytes=len(details_raw),
                     format=DETAILS_PACKED if packed_store else DETAILS_OBJECTS if object_store else DETAILS, binding=binding)
    envelope = dict(format=STORAGE_PACKED if packed_store else STORAGE_OBJECTS if object_store else STORAGE, binding=binding,
        publication_sequence=value['publication_sequence'],
        index=dict(format=INDEX, job=_index_job(value)), details=reference)
    envelope_raw = raw(envelope)
    if len(envelope_raw) + 1 > MAX_RECORD_BYTES:
        raise ValueError('B63 prospective status decoded byte cap')
    admit_envelope(envelope, binding)
    return PublicationPlan(raw(binding), details_raw, envelope_raw,
                           value['publication_sequence'], value['status'] in TERMINAL,objects)


def _reject_links(path):
    """Reject all existing parent/leaf links, including Windows reparse points."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            meta = part.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(meta.st_mode)
                or getattr(meta, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
            raise ValueError('B63 status link/reparse target')
    return path


def _relative(directory, relative):
    if (type(relative) is not str or re.fullmatch(
            r'details/[0-9]{8,15}-[0-9a-f]{64}\.json', relative) is None):
        raise ValueError('B63 allowlisted details relative path')
    directory = _reject_links(directory)
    path = _reject_links(directory.joinpath(*relative.split('/')))
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError('B63 details containment')
    return path


def admit_envelope(value, binding):
    binding = admit_binding(binding)
    _fields(value, ('format', 'binding', 'publication_sequence', 'index', 'details'))
    if value['format'] not in (STORAGE,STORAGE_OBJECTS,STORAGE_PACKED) or not _same(value['binding'], binding):
        raise ValueError('B63 status envelope binding/version')
    sequence = _integer(value['publication_sequence'], 1)
    _fields(value['index'], ('format', 'job'))
    if value['index']['format'] != INDEX:
        raise ValueError('B63 explicit compact index version')
    summary = value['index']['job']
    if type(summary) is not dict or summary.get('storage_view') != INDEX:
        raise ValueError('B63 compact index storage view')
    restored = dict(summary)
    restored.pop('storage_view')
    _job(restored, binding)
    if restored['publication_sequence'] != sequence or restored['progress'] is not None or restored['checkpoints'] != []:
        raise ValueError('B63 compact index publication shape')
    reference = value['details']
    _fields(reference, ('path', 'sha256', 'bytes', 'format', 'binding'))
    _digest(reference['sha256'])
    _integer(reference['bytes'], 1, MAX_DETAILS_BYTES)
    expected_details=DETAILS_PACKED if value['format']==STORAGE_PACKED else DETAILS_OBJECTS if value['format']==STORAGE_OBJECTS else DETAILS
    if (reference['format'] != expected_details or not _same(reference['binding'], binding)
            or reference['path'] != 'details/' + str(sequence).zfill(8) + '-' + reference['sha256'] + '.json'):
        raise ValueError('B63 details reference binding/path')
    if len(raw(value)) + 1 > MAX_RECORD_BYTES:
        raise ValueError('B63 status decoded byte cap')
    return value


def index(envelope, binding):
    """Validate the compact head only; do not touch a details file."""
    admit_envelope(envelope, binding)
    return deepcopy(envelope['index']['job'])


def hydrate(directory, envelope, binding, *, read_charge=None):
    admit_envelope(envelope, binding)
    reference = envelope['details']
    if reference['format']==DETAILS_PACKED:
        # The logical details/field names remain canonical DATA; only their
        # explicitly versioned physical reader changes. Every referenced range
        # is re-hashed before decode, never accepted from an index name alone.
        from .lifetime_packed_status import PackedStatus
        from .lifetime_status_objects import restore
        if read_charge is not None:read_charge(16*MAX_DETAILS_BYTES+65536)
        with PackedStatus(directory,binding)as packed:
            content=packed.read(reference['path'],expected_sha256=reference['sha256'],expected_bytes=reference['bytes'])
            data=json.loads(content);_fields(data,('format','binding','fields'))
            if data['format']!=DETAILS_PACKED or not _same(data['binding'],binding) or raw(data)!=content:
                raise ValueError('YEAR-V5 packed details canonical/binding')
            job=restore(data['fields'],lambda ref:packed.read(ref['path'],expected_sha256=ref['sha256'],expected_bytes=ref['bytes']))
        _job(job,binding)
        if job['publication_sequence']!=envelope['publication_sequence']or not _same(_index_job(job),envelope['index']['job']):
            raise ValueError('YEAR-V5 packed hydrated index disagreement')
        return deepcopy(job)
    path = _relative(directory, reference['path'])
    if path.stat().st_size != reference['bytes']:
        raise ValueError('B63 details exact size')
    # Paid once before bounded file read/hash/decode/validation/copy. A read-only
    # caller may supply an in-memory finite reservation, never a model ledger.
    if read_charge is not None:
        read_charge(16 * (MAX_DETAILS_BYTES if reference['format']==DETAILS_OBJECTS else reference['bytes']) + 65536)
    with path.open('rb') as stream:
        content = stream.read(reference['bytes'] + 1)
    if len(content) != reference['bytes'] or sha256(content).hexdigest() != reference['sha256']:
        raise ValueError('B63 details exact hash/size')
    data = json.loads(content)
    if reference['format']==DETAILS_OBJECTS:
        _fields(data,('format','binding','fields'))
        if data['format']!=DETAILS_OBJECTS or not _same(data['binding'],binding) or raw(data)!=content:raise ValueError('YEAR-V2 details binding/canonical')
        from .lifetime_status_objects import restore
        def read_object(ref):
            path=_reject_links(Path(directory).joinpath(*ref['path'].split('/')))
            if path.stat().st_size!=ref['bytes']:raise ValueError('field object exact size')
            with path.open('rb')as f:return f.read(ref['bytes']+1)
        job=restore(data['fields'],read_object);_job(job,binding)
        if job['publication_sequence']!=envelope['publication_sequence']or not _same(_index_job(job),envelope['index']['job']):raise ValueError('object hydrated index disagreement')
        return deepcopy(job)
    _fields(data, ('format', 'binding', 'job'))
    if data['format'] != DETAILS or not _same(data['binding'], binding) or raw(data) != content:
        raise ValueError('B63 details canonical schema/binding')
    _job(data['job'], binding)
    if data['job']['publication_sequence'] != envelope['publication_sequence'] or not _same(_index_job(data['job']), envelope['index']['job']):
        raise ValueError('B63 hydrated index disagreement')
    return deepcopy(data['job'])


def read_envelope(directory, binding, output_policy, *, profile=None):
    from .lifecycle_stream import read_latest_status
    directory = _reject_links(directory)
    value, proof = read_latest_status(directory / 'head', output_policy, profile=profile)
    if proof['incomplete_head_tail_bytes'] or proof['sequence'] != value.get('publication_sequence'):
        raise ValueError('B63 incomplete/uncertain status head; quarantined, no repair')
    admit_envelope(value, binding)
    return value, proof


def _write_new(path, data):
    path = _reject_links(path)
    # Details, field objects and independent error evidence share this leaf.
    # Claim the future FILE and bounded parent DIRs before either is created;
    # a failed/UNKNOWN owner must never become an untracked status writer.
    from .lifetime_physical_storage import register_producer_path
    register_producer_path(path, additional_bytes=len(data))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        if stream.write(data) != len(data):
            raise OSError('B63 incomplete immutable details write')
        stream.flush()
        _io_fsync(stream.fileno())


class ParentErrorChannel:
    """Independent finite pre-reserved evidence, never a terminal/resume right."""
    def __init__(self, directory, binding, *, charge=None):
        self.directory = Path(directory)
        self.binding = admit_binding(binding)
        self.charge = charge
        self.attempts = 0

    def reserve(self, *, precharged=False):
        path = _reject_links(self.directory / 'parent-errors' / 'reservation.json')
        expected = dict(format=ERROR_RESERVATION, binding=self.binding,
                        maximum_records=MAX_ERRORS, maximum_record_bytes=MAX_ERROR_BYTES,
                        reserved_bytes=ERROR_RESERVED_BYTES)
        content = raw(expected)
        if path.exists():
            if path.stat().st_size != len(content):
                raise ValueError('B63 parent error reservation binding')
            with path.open('rb') as stream:
                if stream.read(len(content) + 1) != content:
                    raise ValueError('B63 parent error reservation binding')
            return
        if self.charge is not None and not precharged:
            self.charge(ERROR_RESERVED_BYTES)
        _write_new(path, content)

    def record(self, stage, primary, *, traceback_text='', secondary=()):
        if type(stage) is not str or not 1 <= len(stage) <= 128:
            raise ValueError('B63 bounded parent error stage')
        reservation = self.directory / 'parent-errors' / 'reservation.json'
        if not reservation.exists():
            raise ValueError('B63 independent parent error channel was not reserved')
        self.reserve()
        folder = _reject_links(reservation.parent)
        files = []
        for path in folder.glob('error-*.json'):
            if len(files) >= MAX_ERRORS or re.fullmatch(r'error-[0-9]{2}\.json', path.name) is None:
                raise ValueError('B63 parent error channel population')
            _reject_links(path)
            files.append(path)
        self.attempts = max(self.attempts, *(int(p.stem[-2:]) for p in files), 0) + 1
        if self.attempts > MAX_ERRORS:
            raise ValueError('B63 parent error channel exhausted; preserve original failure')
        if type(traceback_text) is not str or type(secondary) not in (tuple, list) or len(secondary) > 8:
            raise ValueError('B63 parent error payload')
        trace = traceback_text.encode('utf-8')
        kept = trace[:8192].decode('utf-8', errors='ignore')
        message = str(primary)
        payload = dict(format=ERROR, binding=self.binding, sequence=self.attempts,
            stage=stage, primary_type=_cliptext(type(primary).__name__, 128),
            primary_message=_cliptext(message, 1024), primary_message_sha256=sha256(message.encode('utf-8')).hexdigest(),
            traceback=kept, traceback_original_bytes=len(trace), traceback_sha256=sha256(trace).hexdigest(),
            traceback_truncated=len(kept.encode('utf-8')) != len(trace),
            secondary=[dict(type=_cliptext(type(error).__name__, 128), message=_cliptext(error, 384)) for error in secondary],
            scientific_authority=False, application_terminal=False)
        content = raw(payload)
        if len(content) > MAX_ERROR_BYTES:
            raise ValueError('B63 parent error record cap')
        target = folder / ('error-' + str(self.attempts).zfill(2) + '.json')
        _write_new(target, content)
        return dict(path=target.relative_to(self.directory).as_posix(), bytes=len(content),
                    sha256=sha256(content).hexdigest(), format=ERROR)


class Publisher:
    """Lazy one-writer details -> last durable head publication.

    Byte reservations include immutable details and independent emergency files.
    Codec units conservatively cover encode/hash/read/validate/copy, separate
    from the existing stream codec/head charges. No attempted cost is refunded.
    """
    def __init__(self, directory, binding, output_policy, *, profile=None,
                 charge=None, codec_charge=None, writer_factory=None, object_store=False, packed_store=False):
        if type(object_store)is not bool or type(packed_store)is not bool:raise ValueError('explicit object storage policy')
        self.object_store=object_store or packed_store
        self.packed_store=packed_store
        self.packed=None
        self.directory = Path(directory)
        self.binding = admit_binding(binding)
        self.policy = output_policy
        from .lifecycle_stream import LifecycleStreamPolicy
        if type(output_policy) is not LifecycleStreamPolicy:
            raise TypeError('B63 exact immutable status output policy')
        self.head_policy = replace(output_policy, status_total_bytes=output_policy.status_total_bytes // 2)
        self.profile = profile
        actual_profile_identity = None if profile is None else profile.identity
        if actual_profile_identity != self.binding['profile_identity']:
            raise ValueError('B63 immutable publication profile binding')
        self.charge = charge
        self.codec_charge = codec_charge
        self.writer_factory = writer_factory
        self.writer = None
        self.sequence = 0
        self.details_bytes = 0
        self.failed = False
        self.closed = False
        self.errors = ParentErrorChannel(self.directory, self.binding, charge=charge)
        if type(output_policy.max_record_bytes) is not int or output_policy.max_record_bytes < MAX_RECORD_BYTES:
            raise ValueError('B63 unchanged 65536 decoded status domain')

    @property
    def head(self):
        return self.writer.head if self.writer is not None else self

    def publish(self, plan):
        if self.closed or self.failed:
            raise ValueError('B63 closed/quarantined status publisher')
        if (type(plan) is not PublicationPlan
                or any(type(getattr(plan, name)) is not bytes for name in
                       ('binding_raw', 'details_raw', 'envelope_raw'))
                or type(plan.sequence) is not int or type(plan.terminal) is not bool
                or plan.binding_raw != raw(self.binding)):
            raise ValueError('B63 exact admitted publication plan')
        # Re-admit immutable plan bytes before costs or I/O; forged plans do not
        # bypass size/schema checks or alter caller/cache/sequence.
        envelope = plan.envelope
        admitted = preflight(dict(plan.job, publication_sequence=plan.sequence - 1), self.binding,object_store=self.object_store,packed_store=self.packed_store)
        if plan != admitted or plan.sequence != self.sequence + 1:
            raise ValueError('B63 publication immutable plan/sequence')
        # Existing immutable objects are verified, never overwritten or deleted.
        new_objects=[]
        if plan.objects:
            from .lifetime_status_objects import decode
            refs={v['object']['path']:v['object']for v in json.loads(plan.details_raw)['fields'].values()if 'object'in v}
            if self.codec_charge is not None:self.codec_charge(32*MAX_DETAILS_BYTES+65536)
            for relative,content in plan.objects:
                if self.packed_store:
                    if self.packed is None or not self.packed.contains(relative,content):new_objects.append((relative,content))
                    continue
                target=_reject_links(self.directory.joinpath(*relative.split('/')))
                if target.exists():
                    if target.stat().st_size!=len(content):raise ValueError('existing immutable object size')
                    with target.open('rb')as f:saved=f.read(len(content)+1)
                    if saved!=content:raise ValueError('existing immutable object bytes')
                    decode(refs[relative],saved)
                else:new_objects.append((target,content))
        publication_bytes=len(plan.details_raw)+sum(len(v)for _,v in new_objects)
        if self.packed_store:
            from .lifetime_packed_status import MAX_HEADER_BYTES
            # Frame headers and bounded index rows are prospective charges;
            # they are not invented payload bytes or a measured IO count.
            publication_bytes+=(1+len(new_objects))*(4+MAX_HEADER_BYTES+512)
        limit = self.policy.status_total_bytes // 2
        reserve = 0 if plan.terminal else TERMINAL_RESERVE_BYTES
        if self.details_bytes + publication_bytes + reserve > limit:
            raise ValueError('B63 prospective details/terminal reservation')
        path = _relative(self.directory, envelope['details']['path'])
        if not self.packed_store and path.exists():
            raise ValueError('B63 existing details orphan; no replay/repair')
        if self.codec_charge is not None:
            self.codec_charge(16 * len(plan.details_raw) + 16 * MAX_RECORD_BYTES + 65536)
        if self.charge is not None:
            self.charge(publication_bytes)
            if not (self.directory / 'parent-errors' / 'reservation.json').exists():
                self.charge(ERROR_RESERVED_BYTES)
        try:
            if self.packed_store:
                critical=plan.terminal or plan.job['status']=='STOP_REQUESTED'
                if critical:
                    from .lifetime_physical_storage import activate_terminal_for_job_directory
                    activate_terminal_for_job_directory(self.directory.parent)
            self.errors.reserve(precharged=True)
            if self.packed_store:
                from .lifetime_packed_status import PackedStatus
                if self.packed is None:self.packed=PackedStatus(self.directory,self.binding,create=True)
                for relative,content in new_objects:self.packed.put(relative,content,role='FIELD',terminal=critical)
                self.packed.put(envelope['details']['path'],plan.details_raw,role='DETAILS',terminal=critical)
            else:
                for target,content in new_objects:_write_new(target,content)
                _write_new(path, plan.details_raw)
            if self.writer is None:
                if self.writer_factory is None:
                    from .lifecycle_stream import StatusStream
                    factory = StatusStream
                else:
                    factory = self.writer_factory
                self.writer = factory(self.directory / 'head', self.head_policy,
                    charge=self.charge, profile=self.profile, codec_charge=self.codec_charge)
            committed = self.writer.publish(envelope, terminal=plan.terminal)
            if committed != plan.sequence:
                raise ValueError('B63 committed head sequence mismatch')
        except BaseException:
            self.failed = True
            raise
        self.details_bytes += publication_bytes
        self.sequence = committed
        return committed

    def close(self):
        if self.closed:
            return
        self.closed = True
        failures=[]
        for resource in (self.writer,self.packed):
            if resource is not None:
                try:resource.close()
                except BaseException as error:failures.append(error)
        if failures:
            for error in failures[1:]:
                try:failures[0].add_note('Secondary status close failure: '+repr(error))
                except BaseException:pass
            raise failures[0]


def close_all(resources):
    """Best-effort close of every resource; returns ordered separate failures."""
    errors = []
    for name, resource in resources:
        try:
            resource.close()
        except BaseException as error:
            errors.append((name, error))
    return errors
