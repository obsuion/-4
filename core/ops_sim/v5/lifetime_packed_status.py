"""YEAR-V5 bounded status-object blocks and range-verified SQLite index.

This is administrative DATA, never execution or scientific authority. A block
append is fsynced before its index transaction commits; the existing status
head is published only afterwards. Unknown append/index failures quarantine the
writer and leave all source-owner reservations charged. Legacy status objects
are neither rewritten nor imported by this owner.
"""
from pathlib import Path, PurePosixPath
from hashlib import sha256
from functools import wraps
import json
import os
import re
import sqlite3
import stat
import struct
import zlib
from threading import RLock
from .lifetime_io_accounting import fsync, sqlite_commit

METHOD = 'YEAR_V5_PACKED_STATUS_OBJECTS_V1'
FRAME = 'YEAR_V5_CANONICAL_STATUS_OBJECT_FRAME_V1'
BLOCK_BYTES = 2**20
MAX_BLOCKS = 128
MAX_BYTES = BLOCK_BYTES * MAX_BLOCKS
MAX_OBJECT_BYTES = 256 * 1024
MAX_HEADER_BYTES = 2048
MAX_OBJECTS = 65536
TERMINAL_OBJECTS = 128
TERMINAL_BLOCKS = 2
TERMINAL_BYTES = TERMINAL_BLOCKS * BLOCK_BYTES
TERMINAL_INDEX_PAGES = 128
INDEX_PAGE_BYTES = 4096
INDEX_PAGES = 4096
INDEX_BYTES = INDEX_PAGE_BYTES * INDEX_PAGES
# Same pinned pager whole-database journal bound used by the V4 owner; the new
# contract independently reserves this concurrent temporary overlap.
INDEX_JOURNAL_BYTES = INDEX_PAGES * (4096 + 8) + (2 * (INDEX_PAGES + 2) - 1) * 65536
PREFIX = struct.Struct('>I')
ROLES = ('FIELD', 'DETAILS')


def _serialized(method):
    """Serialize this process's administrative owner, never adopt a handle.

    Check PID before acquiring a possibly inherited lock as well as inside it.
    Reentrant calls (put -> contains -> read) retain one writer critical section.
    """
    @wraps(method)
    def invoke(self,*args,**kwargs):
        self._check_process()
        with self._lock:
            self._check_process()
            return method(self,*args,**kwargs)
    return invoke


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf8')


def _int(value, name, minimum=0, maximum=2**63-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('YEAR-V5 packed exact integer: ' + name)
    return value


def _hash(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('YEAR-V5 packed exact digest')
    return value


def _key(value):
    if (type(value) is not str or len(value) > 160 or
            re.fullmatch(r'(?:objects/[0-9a-f]{64}\.zjson|details/[0-9]{8,15}-[0-9a-f]{64}\.json)', value) is None):
        raise ValueError('YEAR-V5 packed logical path')
    return value


def _safe(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        try: info = node.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('YEAR-V5 packed link/reparse path')
    return path


def _claim(path):
    from .lifetime_physical_storage import register_producer_path
    register_producer_path(path)


def _decoded_metadata(key, data, role):
    """Guard the actual codec, canonical bytes and decoded identity before I/O."""
    if role=='FIELD':
        decoder=zlib.decompressobj()
        decoded=decoder.decompress(data,MAX_OBJECT_BYTES+1)
        if (not 1<=len(decoded)<=MAX_OBJECT_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
            raise ValueError('YEAR-V5 bounded canonical field codec/tail')
        decoded_sha=sha256(decoded).hexdigest()
        if key!='objects/'+decoded_sha+'.zjson':raise ValueError('YEAR-V5 decoded field key binding')
        codec='ZLIB_CANONICAL_FIELD_V1'
    else:
        decoded=data;decoded_sha=sha256(data).hexdigest();codec='RAW_CANONICAL_DETAILS_V1'
        if not key.endswith('-'+decoded_sha+'.json'):raise ValueError('YEAR-V5 decoded details key binding')
    parsed=json.loads(decoded)
    if raw(parsed)!=decoded:raise ValueError('YEAR-V5 exact decoded canonical object')
    return dict(codec=codec,decoded_bytes=len(decoded),decoded_sha256=decoded_sha)


class PackedStatus:
    """One bounded job-local writer or strict range reader.

    The index is bounded to 16MiB and does not store payloads. Ordinary put()
    reads only the indexed duplicate, current block frontier and bounded root
    metadata; it never hashes completed blocks. Explicit verify_import() reads
    every indexed range/sealed block and is intentionally separately charged.
    """
    def __init__(self, directory, binding, *, create=False):
        from .lifetime_status import admit_binding
        from .lifetime_physical_storage import _admit_sqlite_runtime
        _admit_sqlite_runtime()
        if type(sqlite3.threadsafety)is not int or sqlite3.threadsafety not in (1,3):
            raise ValueError('YEAR-V5 thread-capable pinned SQLite required')
        if type(create) is not bool: raise TypeError('YEAR-V5 exact packed create flag')
        self._pid=os.getpid()
        self._lock=RLock()
        self.directory = _safe(Path(directory) / 'packed-v1')
        self.binding = admit_binding(binding)
        self.context_sha256 = sha256(raw(self.binding)).hexdigest()
        self.path = _safe(self.directory / 'index.sqlite3')
        self.failed = False
        self.closed = False
        self.writable = create
        self.active = None
        self.read_bytes = 0
        self.written_bytes = 0
        self.index_transactions = 0
        self.old_prefix_bytes_read_on_put = 0
        if create:
            if self.directory.exists(): raise ValueError('YEAR-V5 new packed directory required')
            _claim(self.path)
            _claim(self.path.with_name(self.path.name + '-journal'))
            self.directory.mkdir(parents=True)
            self.db = sqlite3.connect(self.path, isolation_level=None, timeout=5,check_same_thread=False)
        else:
            if not self.path.is_file() or self.path.stat().st_size > INDEX_BYTES:
                raise ValueError('YEAR-V5 bounded packed index required')
            self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=0,check_same_thread=False)
        try:
            if create:
                self.db.execute('PRAGMA page_size=4096')
                self.db.execute('PRAGMA auto_vacuum=NONE')
                if self.db.execute('PRAGMA journal_mode=PERSIST').fetchone()[0] != 'persist':
                    raise ValueError('YEAR-V5 packed PERSIST journal required')
                self.db.execute('PRAGMA synchronous=FULL')
                self.db.execute('PRAGMA temp_store=MEMORY')
                self.db.execute('PRAGMA cache_size=-2048')
                self.db.execute('PRAGMA journal_size_limit=0')
                if self.db.execute('PRAGMA max_page_count=4096').fetchone()[0] != INDEX_PAGES:
                    raise ValueError('YEAR-V5 bounded packed index pages required')
                self.db.executescript('''BEGIN IMMEDIATE;
                    CREATE TABLE metadata(key TEXT PRIMARY KEY,value BLOB NOT NULL);
                    CREATE TABLE blocks(number INTEGER PRIMARY KEY,bytes INTEGER NOT NULL,
                      sealed INTEGER NOT NULL DEFAULT 0,sha256 TEXT);
                    CREATE TABLE objects(key BLOB PRIMARY KEY,block INTEGER NOT NULL,
                      offset INTEGER NOT NULL,length INTEGER NOT NULL,payload INTEGER NOT NULL,
                      sha BLOB NOT NULL,role INTEGER NOT NULL,sequence INTEGER NOT NULL UNIQUE)
                      WITHOUT ROWID;
                ''')
                self.db.execute('INSERT INTO metadata VALUES (?,?)', ('authority', raw(dict(
                    format=METHOD, binding=self.binding, block_bytes=BLOCK_BYTES,
                    maximum_blocks=MAX_BLOCKS, maximum_objects=MAX_OBJECTS,
                    maximum_index_bytes=INDEX_BYTES, journal_mode='PERSIST_FULL_LIMIT0'))))
                self.db.execute('INSERT INTO metadata VALUES (?,?)', ('counts', raw(dict(objects=0, bytes=0))))
                self._commit()
                # PERSIST keeps the same name, including when truncated to zero.
                # Ensure its producer claim corresponds to an actual regular file.
                journal = self.path.with_name(self.path.name + '-journal')
                if not journal.exists():
                    with journal.open('xb') as stream: stream.flush(); fsync(stream.fileno())
            else:
                self.db.execute('PRAGMA cache_size=-2048')
                self.db.execute('PRAGMA query_only=ON')
            if self.db.execute('PRAGMA page_size').fetchone()[0] != INDEX_PAGE_BYTES:
                raise ValueError('YEAR-V5 packed page size drift')
            saved = self.db.execute('SELECT value FROM metadata WHERE key=?', ('authority',)).fetchone()
            expected = raw(dict(format=METHOD, binding=self.binding, block_bytes=BLOCK_BYTES,
                maximum_blocks=MAX_BLOCKS, maximum_objects=MAX_OBJECTS,
                maximum_index_bytes=INDEX_BYTES, journal_mode='PERSIST_FULL_LIMIT0'))
            if saved is None or saved[0] != expected:
                raise ValueError('YEAR-V5 packed source/context/schema binding')
        except BaseException:
            self.db.close()
            raise

    def _check_process(self):
        if os.getpid()!=self._pid:
            raise ValueError('YEAR-V5 packed foreign-process handle; no adoption')

    def _commit(self):
        self._check_process()
        sqlite_commit(lambda: self.db.execute('COMMIT'))
        self.index_transactions += 1

    def _guard(self):
        self._check_process()
        if self.closed or self.failed: raise ValueError('YEAR-V5 closed/quarantined packed owner')
        for path, maximum in ((self.path, INDEX_BYTES),
                (self.path.with_name(self.path.name + '-journal'), INDEX_JOURNAL_BYTES)):
            _safe(path)
            if path.exists():
                meta = path.stat()
                if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > maximum:
                    raise ValueError('YEAR-V5 packed index/journal bound or kind')

    def _block_path(self, number):
        self._check_process()
        _int(number, 'block', 1, MAX_BLOCKS)
        path = _safe(self.directory / ('block-' + str(number).zfill(8) + '.bin'))
        if path.exists():
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > BLOCK_BYTES:
                raise ValueError('YEAR-V5 bounded single-link regular block required')
        return path

    def _row(self, key):
        self._check_process()
        return self.db.execute('SELECT block,offset,length,payload,sha,role,sequence FROM objects WHERE key=?',
                               (sha256(_key(key).encode('ascii')).digest(),)).fetchone()

    @_serialized
    def read(self, key, *, expected_sha256=None, expected_bytes=None):
        self._guard(); key = _key(key)
        row = self._row(key)
        if row is None: raise ValueError('YEAR-V5 packed object not committed')
        block, offset, length, payload_size, digest, role, sequence = row
        _int(offset, 'offset', 0, BLOCK_BYTES); _int(length, 'frame', 5, BLOCK_BYTES)
        _int(payload_size, 'payload', 1, MAX_OBJECT_BYTES); _int(sequence, 'sequence', 1, MAX_OBJECTS)
        if type(digest) is not bytes or len(digest) != 32 or type(role) is not int or role not in (0, 1):
            raise ValueError('YEAR-V5 packed index row schema')
        path = self._block_path(block); size = path.stat().st_size
        if size > BLOCK_BYTES or offset + length > size:
            raise ValueError('YEAR-V5 packed range truncated')
        with path.open('rb') as stream:
            stream.seek(offset); frame = stream.read(length)
        self.read_bytes += len(frame)
        if len(frame) != length: raise ValueError('YEAR-V5 packed short range')
        header_size = PREFIX.unpack(frame[:PREFIX.size])[0]
        if not 1 <= header_size <= MAX_HEADER_BYTES or PREFIX.size + header_size + payload_size != length:
            raise ValueError('YEAR-V5 packed frame lengths')
        header_raw = frame[PREFIX.size:PREFIX.size + header_size]
        header = json.loads(header_raw)
        fields = ('format', 'key', 'sequence', 'role', 'context_sha256', 'encoded_bytes', 'encoded_sha256',
                  'codec','decoded_bytes','decoded_sha256')
        if type(header) is not dict or set(header) != set(fields) or raw(header) != header_raw:
            raise ValueError('YEAR-V5 packed header canonical schema')
        _int(header['sequence'],'header sequence',1,MAX_OBJECTS)
        _hash(header['context_sha256']);_hash(header['encoded_sha256'])
        if (header['format'] != FRAME or header['key'] != key or header['sequence'] != sequence or
                header['role'] != ROLES[role] or header['context_sha256'] != self.context_sha256 or
                type(header['encoded_bytes']) is not int or header['encoded_bytes'] != payload_size or
                header['encoded_sha256'] != digest.hex()):
            raise ValueError('YEAR-V5 packed header/index/context disagreement')
        if (role == 0) != key.startswith('objects/'):
            raise ValueError('YEAR-V5 packed key/role disagreement')
        payload = frame[PREFIX.size + header_size:]
        if sha256(payload).digest() != digest:
            raise ValueError('YEAR-V5 packed payload hash')
        decoded=_decoded_metadata(key,payload,ROLES[role])
        if any(header[name]!=decoded[name]or type(header[name])is not type(decoded[name])for name in decoded):
            raise ValueError('YEAR-V5 packed decoded length/hash/codec binding')
        if expected_sha256 is not None and _hash(expected_sha256) != digest.hex():
            raise ValueError('YEAR-V5 packed expected payload binding')
        if expected_bytes is not None and _int(expected_bytes, 'expected bytes', 1, MAX_OBJECT_BYTES) != len(payload):
            raise ValueError('YEAR-V5 packed expected payload size')
        return payload

    @_serialized
    def contains(self, key, data):
        self._guard()
        if self._row(key) is None: return False
        if self.read(key, expected_sha256=sha256(data).hexdigest(), expected_bytes=len(data)) != data:
            raise ValueError('YEAR-V5 packed duplicate content drift')
        return True

    @_serialized
    def put(self, key, data, *, role, terminal=False):
        self._guard(); key = _key(key)
        if not self.writable: raise ValueError('YEAR-V5 packed read-only owner')
        if type(data) is not bytes or not 1 <= len(data) <= MAX_OBJECT_BYTES or type(role)is not str or role not in ROLES or type(terminal)is not bool:
            raise ValueError('YEAR-V5 bounded packed payload/role')
        if (role=='FIELD') != key.startswith('objects/'):raise ValueError('YEAR-V5 packed key/role mismatch')
        decoded=_decoded_metadata(key,data,role)
        if self.contains(key, data): return dict(existing=True, published_bytes=0)
        count = self.db.execute('SELECT value FROM metadata WHERE key=?', ('counts',)).fetchone()
        counters = json.loads(count[0])
        if type(counters)is not dict or set(counters)!={'objects','bytes'}or raw(counters)!=count[0]:
            raise ValueError('YEAR-V5 packed exact counter schema')
        _int(counters['objects'],'object counter',0,MAX_OBJECTS);_int(counters['bytes'],'byte counter',0,MAX_BYTES)
        latest=self.db.execute('SELECT MAX(sequence) FROM objects').fetchone()[0]
        if counters['objects']!=(latest or 0):raise ValueError('YEAR-V5 packed monotone sequence/counter drift')
        if counters['bytes']!=self.db.execute('SELECT COALESCE(SUM(bytes),0) FROM blocks').fetchone()[0]:
            raise ValueError('YEAR-V5 packed indexed byte frontier drift')
        sequence = counters['objects'] + 1
        if sequence > (MAX_OBJECTS if terminal else MAX_OBJECTS-TERMINAL_OBJECTS):
            raise ValueError('YEAR-V5 packed terminal logical-object reserve')
        header = raw(dict(format=FRAME, key=key, sequence=sequence, role=role,
            context_sha256=self.context_sha256, encoded_bytes=len(data), encoded_sha256=sha256(data).hexdigest(),**decoded))
        if len(header) > MAX_HEADER_BYTES: raise ValueError('YEAR-V5 packed header cap')
        frame = PREFIX.pack(len(header)) + header + data
        if len(frame) > BLOCK_BYTES or counters['bytes'] + len(frame) > (MAX_BYTES if terminal else MAX_BYTES-TERMINAL_BYTES):
            raise ValueError('YEAR-V5 packed byte cap')
        # Prospectively retain a bounded number of empty index pages for the
        # next terminal object set. No body write occurs after metadata refusal.
        if self.db.execute('PRAGMA page_count').fetchone()[0] > (INDEX_PAGES if terminal else INDEX_PAGES-TERMINAL_INDEX_PAGES):
            raise ValueError('YEAR-V5 packed terminal metadata headroom exhausted')
        row = self.db.execute('SELECT number,bytes,sealed FROM blocks ORDER BY number DESC LIMIT 1').fetchone()
        if row is None or row[2] or row[1] + len(frame) > BLOCK_BYTES:
            if row is not None and not row[2]: self._seal_block(row[0], row[1])
            block = 1 if row is None else row[0] + 1
            if block > (MAX_BLOCKS if terminal else MAX_BLOCKS-TERMINAL_BLOCKS):
                raise ValueError('YEAR-V5 packed terminal block reserve')
            path = self._block_path(block); _claim(path)
            with path.open('xb') as stream: stream.flush(); fsync(stream.fileno())
            self.db.execute('BEGIN IMMEDIATE')
            try:
                self.db.execute('INSERT INTO blocks(number,bytes,sealed) VALUES (?,0,0)', (block,))
                self._commit()
            except BaseException:
                if self.db.in_transaction: self.db.execute('ROLLBACK')
                self.failed = True; raise
            offset = 0
        else: block, offset = row[0], row[1]; path = self._block_path(block)
        if path.stat().st_size != offset:
            self.failed = True; raise ValueError('YEAR-V5 packed unindexed append/orphan; no repair')
        try:
            with path.open('ab') as stream:
                if stream.write(frame) != len(frame): raise OSError('YEAR-V5 packed incomplete append')
                stream.flush(); fsync(stream.fileno())
            self.written_bytes += len(frame)
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('INSERT INTO objects VALUES (?,?,?,?,?,?,?,?)',
                (sha256(key.encode('ascii')).digest(), block, offset, len(frame), len(data),
                 sha256(data).digest(), ROLES.index(role), sequence))
            self.db.execute('UPDATE blocks SET bytes=bytes+? WHERE number=?', (len(frame), block))
            self.db.execute('UPDATE metadata SET value=? WHERE key=?',
                (raw(dict(objects=sequence, bytes=counters['bytes'] + len(frame))), 'counts'))
            self._commit()
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            self.failed = True; raise
        return dict(existing=False, published_bytes=len(frame), sequence=sequence)

    def _seal_block(self, block, size):
        self._check_process()
        path = self._block_path(block)
        if path.stat().st_size != size: raise ValueError('YEAR-V5 packed seal frontier drift')
        h = sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''): h.update(chunk)
        self.read_bytes += size
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('UPDATE blocks SET sealed=1,sha256=? WHERE number=? AND sealed=0', (h.hexdigest(), block))
            self._commit()
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            self.failed = True; raise

    @_serialized
    def verify_import(self):
        """Explicit complete sealed-block check, not an ordinary append cost."""
        self._guard(); rows = self.db.execute('SELECT number,bytes,sealed,sha256 FROM blocks ORDER BY number').fetchall()
        if len(rows) > MAX_BLOCKS: raise ValueError('YEAR-V5 bounded imported blocks')
        total = 0
        for number, size, sealed, expected in rows:
            path = self._block_path(number)
            if type(size) is not int or not 0 <= size <= BLOCK_BYTES or path.stat().st_size != size:
                raise ValueError('YEAR-V5 imported block size')
            if not sealed or type(expected) is not str: raise ValueError('YEAR-V5 import requires independently sealed blocks')
            content = path.read_bytes(); self.read_bytes += len(content); total += len(content)
            if sha256(content).hexdigest() != _hash(expected): raise ValueError('YEAR-V5 imported block hash')
        count = self.db.execute('SELECT COUNT(*) FROM objects').fetchone()[0]
        if count > MAX_OBJECTS: raise ValueError('YEAR-V5 imported logical population')
        expected_sequence=0
        for keyhash,number,offset,length,payload,digest,role,sequence in self.db.execute(
                'SELECT key,block,offset,length,payload,sha,role,sequence FROM objects ORDER BY sequence'):
            expected_sequence+=1
            if sequence!=expected_sequence:raise ValueError('YEAR-V5 imported sequence gap/duplicate')
            path=self._block_path(number)
            with path.open('rb')as stream:
                stream.seek(offset);prefix=stream.read(PREFIX.size)
                if len(prefix)!=PREFIX.size:raise ValueError('YEAR-V5 imported short header')
                header_size=PREFIX.unpack(prefix)[0]
                if not 1<=header_size<=MAX_HEADER_BYTES:raise ValueError('YEAR-V5 imported header bound')
                header=json.loads(stream.read(header_size))
            key=_key(header['key'])
            if sha256(key.encode('ascii')).digest()!=keyhash:raise ValueError('YEAR-V5 imported key binding')
            self.read(key,expected_sha256=digest.hex(),expected_bytes=payload)
        if expected_sequence!=count:raise ValueError('YEAR-V5 imported index population drift')
        counters=json.loads(self.db.execute('SELECT value FROM metadata WHERE key=?',('counts',)).fetchone()[0])
        if counters!=dict(objects=count,bytes=total):raise ValueError('YEAR-V5 imported complete frontier drift')
        return dict(format=METHOD, blocks=len(rows), objects=count, verified_bytes=total,
                    qualification='EXPLICIT_DATA_IMPORT_NOT_EXECUTION_AUTHORITY')

    @_serialized
    def snapshot(self):
        self._guard(); counts = json.loads(self.db.execute('SELECT value FROM metadata WHERE key=?', ('counts',)).fetchone()[0])
        return dict(format=METHOD, logical_objects=counts['objects'], block_bytes=counts['bytes'],
            blocks=self.db.execute('SELECT COUNT(*) FROM blocks').fetchone()[0],
            index_bytes=self.path.stat().st_size, index_page_limit=INDEX_PAGES,
            bytes_read=self.read_bytes, bytes_written=self.written_bytes,
            index_transactions=self.index_transactions, old_prefix_bytes_read_on_put=self.old_prefix_bytes_read_on_put,
            old_prefix_counter_scope='PREVIOUSLY_SEALED_BLOCKS_ONLY_EXCLUDES_CURRENT_ACTIVE_BLOCK_SEAL_AND_NAMED_OBJECT_CONSUME',
            maximum_objects=MAX_OBJECTS, maximum_blocks=MAX_BLOCKS,
            terminal_object_slots=TERMINAL_OBJECTS,terminal_block_slots=TERMINAL_BLOCKS,
            terminal_index_pages=TERMINAL_INDEX_PAGES,terminal_payload_bytes=TERMINAL_BYTES,
            integrity='RANGE_ON_CONSUME_SEAL_AND_EXPLICIT_VERIFIED_IMPORT_NOT_ALL_HISTORY_EACH_POLL')

    @_serialized
    def close(self):
        if self.closed: return
        try:
            if self.writable and not self.failed:
                row = self.db.execute('SELECT number,bytes FROM blocks WHERE sealed=0 ORDER BY number DESC LIMIT 1').fetchone()
                if row is not None: self._seal_block(*row)
        finally:
            self.closed = True; self.db.close()

    @_serialized
    def __enter__(self): return self

    def __exit__(self, *args): self.close()
