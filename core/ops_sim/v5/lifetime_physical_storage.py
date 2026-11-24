"""YEAR-V4 finite physical grants and producer-bound sealed inventories.

One complete serial operation is reserved durably before its first write.
Only a closed, explicitly inventoried producer can settle unused reservation.
An exception, orphan, UNKNOWN, or unlisted file leaves that reservation charged.
The SQLite owner is administrative DATA and supplies no scientific authority.
"""
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import os
import re
import shutil
import sqlite3
import stat
from .lifetime_io_accounting import fsync, sqlite_commit

FORMAT = 'YEAR_V4_PHYSICAL_STORAGE_OWNER_V1'
FORMAT_PACKED = 'YEAR_V5_PACKED_PHYSICAL_STORAGE_OWNER_V2'
CONTRACT_PACKED = 'YEAR_V5_FINITE_PACKED_STORAGE_TERMINAL_CONTRACT_V2'
SETTLEMENT_PACKED = 'YEAR_V5_OWNED_CLOSED_PACKED_PRODUCER_V2'
PACKED_SEGMENT_FILES = 512
PACKED_TERMINAL_FILES = 64
PACKED_TERMINAL_DIRECTORIES = 64
PACKED_TERMINAL_INDEX_ROWS = 128
PACKED_SEGMENT_METADATA_PAGES = 1024
PACKED_MUTABLE_FILES = 3
PACKED_MUTABLE_LEAVES = ('parent-publication-work.bin','parent-codec-work.bin','parent-validation-work.bin')
GLOBAL_NAMESPACE_EXHAUSTED = 'GLOBAL_NAMESPACE_OR_METADATA_BUDGET_EXHAUSTED'
UNKNOWN_UNSETTLED_PRODUCER = 'UNKNOWN_UNSETTLED_PRODUCER'
CONTRACT = 'YEAR_V4_FINITE_PHYSICAL_STORAGE_CONTRACT_V1'
POOL_FORMAT = 'YEAR_V4_SHARED_PHYSICAL_COMMITMENT_POOL_V1'
POOL_FILE = 'LIFETIME-PHYSICAL-POOL-V1.json'
POOL_LIMIT = 4 * 2**20
MAX_OPERATIONS = 16384
MAX_FILES = 32768
MAX_OPERATION_FILES = 4096
MAX_ALLOCATION_UNIT = 4096
DATABASE_PAGE_BYTES = 4096
MAX_DATABASE_PAGES = 4096
MAX_DATABASE_BYTES = DATABASE_PAGE_BYTES * MAX_DATABASE_PAGES
# SQLite3.50.4 pager.c caps effective sectors at64KiB. One initial
# header, at most one initial new-page-only spill, then at most one header
# per newly journaled old page. Include every alignment/header sector.
# See analysis/storage-map/PHYSICAL-CONTRACT.md for the pinned source proof.
MAX_SQLITE_SECTOR_BYTES = 65536
MAX_JOURNAL_HEADERS = MAX_DATABASE_PAGES + 2
MAX_JOURNAL_BYTES = (MAX_DATABASE_PAGES * (DATABASE_PAGE_BYTES + 8) +
    (2 * MAX_JOURNAL_HEADERS - 1) * MAX_SQLITE_SECTOR_BYTES)
METADATA_NAMESPACE_OVERHEAD_BYTES = 32 * MAX_ALLOCATION_UNIT
_METADATA_REQUIRED_BYTES = (MAX_DATABASE_BYTES + MAX_JOURNAL_BYTES +
    2 * POOL_LIMIT + METADATA_NAMESPACE_OVERHEAD_BYTES)
METADATA_BYTES = ((_METADATA_REQUIRED_BYTES + 64 * 2**20 - 1) // (64 * 2**20)) * (64 * 2**20)
SQLITE_VERSION = '3.50.4'
SQLITE_SOURCE_ID = '2025-07-30 19:33:53 4d8adfb30e03f9cf27f800a2c1ba3c48fb4ca1b08b0f5ed59a4d5ecbf45e20a3'
_SQLITE_CONNECT = sqlite3.connect
_SQLITE_RUNTIME = None
GLOBAL_EXHAUSTED = 'GLOBAL_RETAINED_BUDGET_EXHAUSTED'
ROLES = ('RETAINED', 'EXPORT', 'BACKUP')
CAP_KEYS = dict(RETAINED='global_retained_cap_bytes',
                EXPORT='export_allowance_bytes', BACKUP='full_defined_backup_cap_bytes')


def _admit_sqlite_runtime():
    """Pin the bounded pager before opening any on-disk owner/read connection.

    Source ID is queried on a memory-only connection once per process. There
    is no mutation retry or reconstruction of an unsupported saved owner.
    """
    global _SQLITE_RUNTIME
    if sqlite3.sqlite_version != SQLITE_VERSION or sqlite3.connect is not _SQLITE_CONNECT:
        raise ValueError('YEAR-V4 unsupported SQLite runtime; exact3.50.4 bounded pager required')
    if _SQLITE_RUNTIME is None:
        memory = _SQLITE_CONNECT(':memory:', isolation_level=None)
        try:source = memory.execute('SELECT sqlite_source_id()').fetchone()[0]
        finally:memory.close()
        if source != SQLITE_SOURCE_ID:
            raise ValueError('YEAR-V4 unsupported SQLite source identity; no physical qualification')
        _SQLITE_RUNTIME = dict(version=SQLITE_VERSION, source_id=SQLITE_SOURCE_ID)
    return dict(_SQLITE_RUNTIME)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf8')


def digest(value):
    return sha256(value if type(value) is bytes else encoded(value)).hexdigest()


def _integer(value, name, low=0, high=2**40):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('YEAR-V4 exact physical integer: ' + name)
    return value


def _hash(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('YEAR-V4 physical SHA256')
    return value


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError('YEAR-V4 duplicate physical metadata field')
        out[key] = value
    return out


def contract(policy):
    """New method only. Old methods retain their original commitment formula.

    The independent backup is a full allocated copy of the retained cap. The
    active grant includes worst-case RAW payload and bounded file/directory
    overhead. These allowances deliberately overlap conservatively in peak
    admission; already settled bytes are never added to the future retained cap.
    """
    from .lifetime_policy import physical_storage
    if not physical_storage(policy):
        raise TypeError('YEAR-V4 explicit physical policy required')
    policy.__post_init__()
    values = dict(format=CONTRACT,
        global_retained_cap_bytes=3 * 2**30,
        maximum_concurrent_write_reserve_bytes=512 * 2**20,
        terminal_checkpoint_headroom_bytes=128 * 2**20,
        maximum_temporary_overlap_bytes=128 * 2**20,
        export_allowance_bytes=640 * 2**20,
        full_defined_backup_cap_bytes=3 * 2**30,
        bounded_index_metadata_bytes=METADATA_BYTES,
        maximum_allocation_unit_bytes=MAX_ALLOCATION_UNIT,
        maximum_files_per_operation=MAX_OPERATION_FILES,
        maximum_owned_files=MAX_FILES,
        maximum_database_bytes=MAX_DATABASE_BYTES,
        maximum_database_pages=MAX_DATABASE_PAGES,
        database_page_bytes=DATABASE_PAGE_BYTES,
        maximum_rollback_journal_bytes=MAX_JOURNAL_BYTES,
        maximum_rollback_journal_headers=MAX_JOURNAL_HEADERS,
        maximum_sqlite_effective_sector_bytes=MAX_SQLITE_SECTOR_BYTES,
        metadata_namespace_overhead_bytes=METADATA_NAMESPACE_OVERHEAD_BYTES,
        sqlite_runtime=dict(version=SQLITE_VERSION, source_id=SQLITE_SOURCE_ID),
        maximum_segment_auxiliary_bytes=16 * 2**20,
        maximum_export_operation_bytes=128 * 2**20,
        allocation_scope='OWNED_FILE_DATA_PLUS_BOUNDED_FILE_DIRECTORY_METADATA',
        backup_scope='ONE_INDEPENDENT_FULL_COPY_NO_HARDLINK_CREDIT',
        year_capacity='NOT_ESTABLISHED_BY_RESOURCE_CAP')
    from .lifetime_policy import packed_storage
    if packed_storage(policy):
        # A new contract, not a smaller hidden V4 reservation. One bounded
        # packed SQLite index may journal concurrently with the source owner.
        # Its whole-database pinned bound plus the old128MiB temporary overlap
        # fits704MiB. Retained and its independent backup both change explicitly.
        values.update(format=CONTRACT_PACKED,
            global_retained_cap_bytes=2560*2**20,
            full_defined_backup_cap_bytes=2560*2**20,
            maximum_temporary_overlap_bytes=704*2**20,
            maximum_files_per_segment=PACKED_SEGMENT_FILES,
            maximum_mutable_files_per_segment=PACKED_MUTABLE_FILES,
            mutable_namespace_scope='THREE_ORIGINAL_JOB_NAMES_PERSIST_ACROSS_SCIENTIFIC_SEAL; NO_REFUND_OR_GENERATIONS',
            mutable_metadata_scope='ORIGINAL_SEGMENT_PAGE_ESCROW_RETAINED_UNTIL_ALL_THREE_NAMES_ALLOCATED',
            terminal_file_slots=PACKED_TERMINAL_FILES,
            terminal_directory_slots=PACKED_TERMINAL_DIRECTORIES,
            terminal_index_rows=PACKED_TERMINAL_INDEX_ROWS,
            segment_metadata_pages_reserved=PACKED_SEGMENT_METADATA_PAGES,
            maximum_packed_index_bytes=MAX_DATABASE_BYTES,
            maximum_packed_index_journal_bytes=MAX_JOURNAL_BYTES,
            pool_metadata_format='YEAR_V5_INCREMENTAL_PHYSICAL_POOL_V2',
            pool_metadata_scope='BOUNDED_HEADER_AND_PER_STUDY_SLOTS_NOT_PER_FILE_JSON',
            immutable_history_trust='OWNER_CONTROLLED_NAMESPACE; VERIFY_BYTES_AT_SEAL_CONSUME_EXPLICIT_IMPORT; NO_GLOBAL_POLL_TAMPER_CLAIM')
    keys = ('global_retained_cap_bytes', 'maximum_concurrent_write_reserve_bytes',
        'terminal_checkpoint_headroom_bytes', 'maximum_temporary_overlap_bytes',
        'export_allowance_bytes', 'full_defined_backup_cap_bytes', 'bounded_index_metadata_bytes')
    values['whole_study_commitment_bytes'] = sum(values[key] for key in keys)
    if values['whole_study_commitment_bytes'] > 8 * 2**30:
        raise ValueError('YEAR-V4 whole-study physical commitment exceeds8GiB')
    values['identity'] = digest(values)
    return values


def _relative(name):
    if type(name) is not str or not 1 <= len(name) <= 640 or '\\' in name or ':' in name:
        raise ValueError('YEAR-V4 explicit relative owned path')
    value = PurePosixPath(name)
    if not value.parts or value.is_absolute() or any(part in ('', '.', '..') for part in value.parts) or value.as_posix() != name:
        raise ValueError('YEAR-V4 owned path traversal')
    return name


def _node(root, name, *, missing=False):
    path = root.joinpath(*PurePosixPath(_relative(name)).parts)
    for item in (root, *reversed(path.relative_to(root).parents), path):
        # Relative parents above are joined explicitly; never resolve through
        # a symlink/reparse point and then treat the resolved target as owned.
        current = item if item.is_absolute() else root / item
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('YEAR-V4 owned link/reparse forbidden')
    if not missing and not path.exists():
        raise ValueError('YEAR-V4 explicit owned file missing')
    return path


def _root(path):
    root = Path(path).absolute()
    for item in (root, *root.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('YEAR-V4 physical root link/reparse forbidden')
    if not root.is_dir():
        raise ValueError('YEAR-V4 existing local physical root required')
    return root


def _volume(root):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        library = ctypes.WinDLL('kernel32', use_last_error=True)
        sectors = wintypes.DWORD(); sector_bytes = wintypes.DWORD()
        free_clusters = wintypes.DWORD(); clusters = wintypes.DWORD()
        call = library.GetDiskFreeSpaceW
        call.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD))
        call.restype = wintypes.BOOL
        if not call(root.anchor, ctypes.byref(sectors), ctypes.byref(sector_bytes),
                    ctypes.byref(free_clusters), ctypes.byref(clusters)):
            raise OSError(ctypes.get_last_error(), 'YEAR-V4 allocation-unit query')
        unit = sectors.value * sector_bytes.value
    else:
        unit = os.statvfs(root).f_frsize
    _integer(unit, 'allocation unit', 512, MAX_ALLOCATION_UNIT)
    if unit & (unit - 1):
        raise ValueError('YEAR-V4 power-of-two allocation unit required')
    return dict(device=root.stat().st_dev, allocation_unit_bytes=unit,
                platform=os.name)


def _rounded(size, unit):
    return ((size + unit - 1) // unit) * unit


def _windows_allocation(path, info, unit, *, library=None):
    """Read FILE allocation, never the ordinary-file EOF size API.

    The private library seam permits synthetic failure tests. Real handles
    request attributes only and are always closed; no allocation/EOF mutation,
    fallback, ownership or filesystem-metadata measurement is performed.
    """
    import ctypes
    import sys
    expected = _integer(info.st_size, 'allocation expected EOF', 0, 2**63-1)
    _integer(unit, 'allocation unit', 512, MAX_ALLOCATION_UNIT)
    if unit & (unit-1):
        raise ValueError('YEAR-V4 power-of-two allocation unit required')

    class FileStandardInfo(ctypes.Structure):
        _fields_ = (('AllocationSize', ctypes.c_int64), ('EndOfFile', ctypes.c_int64),
            ('NumberOfLinks', ctypes.c_uint32), ('DeletePending', ctypes.c_ubyte),
            ('Directory', ctypes.c_ubyte))
    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = (('FileAttributes', ctypes.c_uint32), ('ReparseTag', ctypes.c_uint32))
    if (ctypes.sizeof(FileStandardInfo) != 24 or ctypes.sizeof(FileAttributeTagInfo) != 8 or
            tuple(getattr(FileStandardInfo, key).offset for key in
                ('AllocationSize', 'EndOfFile', 'NumberOfLinks', 'DeletePending', 'Directory')) != (0,8,16,20,21)):
        raise ValueError('YEAR-V4 exact Windows file-information layout required')
    library = ctypes.WinDLL('kernel32', use_last_error=True) if library is None else library
    create = library.CreateFileW
    create.argtypes = (ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)
    create.restype = ctypes.c_void_p
    query = library.GetFileInformationByHandleEx
    query.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    query.restype = ctypes.c_int
    close = library.CloseHandle
    close.argtypes = (ctypes.c_void_p,)
    close.restype = ctypes.c_int
    # FILE_READ_ATTRIBUTES; SHARE_READ|WRITE|DELETE; OPEN_EXISTING;
    # OPEN_REPARSE_POINT prevents following a raced final symlink.
    handle = create(str(path), 0x80, 7, None, 3, 0x00200000, None)
    if type(handle) is not int or not 0 < handle < ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), 'YEAR-V4 allocated-file open')
    try:
        value = FileStandardInfo(); attributes = FileAttributeTagInfo()
        for kind, data in ((1, value), (9, attributes)):
            result = query(handle, kind, ctypes.byref(data), ctypes.sizeof(data))
            if type(result) is not int or result == 0:
                raise OSError(ctypes.get_last_error(), 'YEAR-V4 allocated-file information query')
        if (value.Directory != 0 or value.DeletePending != 0 or value.NumberOfLinks != 1 or
                attributes.FileAttributes & (0x10 | 0x400)):
            raise ValueError('YEAR-V4 ordinary single-link nonreparse allocated file required')
        eof = _integer(value.EndOfFile, 'native EOF', 0, 2**63-1)
        actual = _integer(value.AllocationSize, 'native allocation size', 0, 2**63-1)
        if eof != expected:
            raise ValueError('YEAR-V4 allocated-file EOF drift')
        if actual > _rounded(eof, unit):
            raise ValueError('YEAR-V4 foreign preallocation exceeds bounded file charge')
        return actual
    finally:
        primary = sys.exception()
        try:
            result = close(handle)
            if type(result) is not int or result == 0:
                raise OSError(ctypes.get_last_error(), 'YEAR-V4 allocated-file handle close')
        except BaseException as error:
            if primary is None:
                raise
            try:
                primary.add_note('Secondary allocated-file handle close failure: ' + repr(error))
            except BaseException:
                pass


def _allocation(path, info, unit):
    if os.name == 'nt':
        return _windows_allocation(path, info, unit)
    actual = info.st_blocks * 512
    if actual > _rounded(info.st_size, unit):
        raise ValueError('YEAR-V4 foreign preallocation exceeds bounded file charge')
    return actual


def _file(root, entry, volume, *, sync=False):
    if type(entry) is not dict or set(entry) != {'path', 'sha256', 'bytes'}:
        raise ValueError('YEAR-V4 producer inventory exact file fields')
    name = _relative(entry['path']); _hash(entry['sha256'])
    _integer(entry['bytes'], 'owned logical length', 0, 3 * 2**30)
    path = _node(root, name); before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_dev != volume['device']:
        raise ValueError('YEAR-V4 regular single-link same-volume owned file required')
    if before.st_size != entry['bytes']:
        raise ValueError('YEAR-V4 producer length drift')
    content = sha256()
    with path.open('r+b' if sync else 'rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            content.update(block)
        if sync:
            fsync(stream.fileno())
    after = path.stat()
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_nlink')
    if content.hexdigest() != entry['sha256'] or any(getattr(before, key) != getattr(after, key) for key in fields):
        raise ValueError('YEAR-V4 producer current-byte/SHA drift')
    unit = volume['allocation_unit_bytes']
    return dict(entry, allocated_bytes=_allocation(path, after, unit),
        charged_bytes=_rounded(entry['bytes'], unit) + unit)


def _binding(value):
    names = {'root_identity', 'source_identity', 'input_sha256', 'policy_identity', 'store_name'}
    if type(value) is not dict or set(value) != names:
        raise ValueError('YEAR-V4 exact storage binding')
    for name in names - {'store_name'}:
        _hash(value[name])
    if type(value['store_name']) is not str or re.fullmatch('[A-Za-z0-9_.-]{1,160}', value['store_name']) is None:
        raise ValueError('YEAR-V4 bounded store name')
    return dict(value)


class PhysicalStorage:
    """Bounded durable owner; operation exceptions never implicitly refund."""
    def __init__(self, directory, policy, binding, *, create=False):
        from .lifetime_policy import packed_storage
        self.packed=packed_storage(policy)
        self.owner_format=FORMAT_PACKED if self.packed else FORMAT
        self.sqlite_runtime = _admit_sqlite_runtime()
        self.root = _root(directory)
        self.policy = policy
        self.binding = _binding(binding)
        if self.binding['policy_identity'] != policy.identity:
            raise ValueError('YEAR-V4 storage policy binding')
        self.contract = contract(policy)
        self.volume = _volume(self.root)
        self.path = _node(self.root, self.binding['store_name'] + '.physical.sqlite3', missing=True)
        existed = self.path.exists()
        if create and existed or not create and not existed:
            raise ValueError('YEAR-V4 explicit new/existing physical owner required')
        if existed:
            info = self.path.stat()
            if not self.path.is_file() or info.st_nlink != 1 or info.st_size > MAX_DATABASE_BYTES:
                raise ValueError('YEAR-V4 bounded regular physical owner')
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        try:
            if create:
                self.db.execute('PRAGMA page_size=4096')
                self.db.execute('PRAGMA auto_vacuum=NONE')
            if self.db.execute('PRAGMA page_size').fetchone()[0] != 4096:
                raise ValueError('YEAR-V4 pinned physical index page size')
            if self.db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
                raise ValueError('YEAR-V4 exact DELETE rollback journal required')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA temp_store=MEMORY')
            if self.db.execute('PRAGMA temp_store').fetchone()[0] != 2 or self.db.execute('PRAGMA auto_vacuum').fetchone()[0] != 0:
                raise ValueError('YEAR-V4 memory temp storage and no page-moving auto-vacuum required')
            if self.db.execute('PRAGMA max_page_count=4096').fetchone()[0] != MAX_DATABASE_PAGES:
                raise ValueError('YEAR-V4 exact bounded physical page count required')
            if create:
                self.db.executescript('''
                    BEGIN IMMEDIATE;
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL);
                    CREATE TABLE grants (operation TEXT PRIMARY KEY, role TEXT NOT NULL,
                      maximum_bytes INTEGER NOT NULL, maximum_files INTEGER NOT NULL,
                      reserved_bytes INTEGER NOT NULL, producer BLOB NOT NULL,
                      scope TEXT, state TEXT NOT NULL, manifest BLOB,
                      charged_bytes INTEGER NOT NULL DEFAULT 0,
                      logical_bytes INTEGER NOT NULL DEFAULT 0,
                      allocated_bytes INTEGER NOT NULL DEFAULT 0,
                      write_reserved_bytes INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE files (path TEXT PRIMARY KEY, operation TEXT NOT NULL
                      REFERENCES grants(operation), sha256 TEXT NOT NULL,
                      bytes INTEGER NOT NULL, charged_bytes INTEGER NOT NULL,
                      allocated_bytes INTEGER NOT NULL);
                    CREATE TABLE mutable (path TEXT PRIMARY KEY, producer BLOB NOT NULL,
                      reserved_logical_bytes INTEGER NOT NULL, charged_bytes INTEGER NOT NULL);
                    CREATE TABLE claims (path TEXT PRIMARY KEY, operation TEXT NOT NULL
                      REFERENCES grants(operation), kind TEXT NOT NULL, retired INTEGER NOT NULL DEFAULT 0,
                      generation INTEGER NOT NULL DEFAULT 1);
                    CREATE TABLE claim_retirements (path TEXT NOT NULL, generation INTEGER NOT NULL,
                      operation TEXT NOT NULL, PRIMARY KEY(path,generation));
                ''')
                if self.packed:
                    self.db.execute('''CREATE TABLE packed_namespace(operation TEXT PRIMARY KEY REFERENCES grants(operation),
                        file_slots INTEGER NOT NULL,directory_slots INTEGER NOT NULL,index_rows INTEGER NOT NULL,
                        metadata_pages INTEGER NOT NULL,mutable_slots INTEGER NOT NULL,phase TEXT NOT NULL,state TEXT NOT NULL)''')
                    self.db.execute('''CREATE TABLE packed_pool_seals(sequence INTEGER PRIMARY KEY,
                        operation TEXT NOT NULL UNIQUE REFERENCES grants(operation),
                        cumulative_allocated_bytes INTEGER NOT NULL,chain TEXT NOT NULL)''')
                self.db.execute('INSERT INTO metadata VALUES (?,?)', ('authority', encoded(
                    dict(format=self.owner_format, binding=self.binding, policy=asdict(self.policy), contract=self.contract, volume=self.volume, sqlite_runtime=self.sqlite_runtime))))
                self.db.execute('INSERT INTO metadata VALUES (?,?)', ('tip', encoded(None)))
                self._commit()
            saved = self.db.execute('SELECT value FROM metadata WHERE key=?', ('authority',)).fetchone()
            expected = encoded(dict(format=self.owner_format, binding=self.binding, policy=asdict(self.policy),
                contract=self.contract, volume=self.volume, sqlite_runtime=self.sqlite_runtime))
            if saved is None or saved[0] != expected:
                raise ValueError('YEAR-V4 physical owner source/policy/volume drift')
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        self.close()

    def _guard(self):
        if _admit_sqlite_runtime() != self.sqlite_runtime:
            raise ValueError('YEAR-V4 admitted SQLite runtime drift')
        if _volume(_root(self.root)) != self.volume:
            raise ValueError('YEAR-V4 physical volume/allocation-unit change')
        for suffix in ('', '-journal'):
            path = self.path.with_name(self.path.name + suffix)
            if path.exists():
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_dev != self.volume['device'] or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('YEAR-V4 owner/journal file drift')
        if self.path.stat().st_size > MAX_DATABASE_BYTES:
            raise ValueError('YEAR-V4 index metadata allocation cap')
        journal = self.path.with_name(self.path.name + '-journal')
        if journal.exists() and journal.stat().st_size > MAX_JOURNAL_BYTES:
            raise ValueError('YEAR-V4 rollback journal exceeds pinned finite format bound')

    @contextmanager
    def _transaction(self):
        self._guard()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            if self.packed:
                # Ordinary/root-control mutations cannot consume metadata
                # already promised to unsettled terminal families. A source
                # terminal phase spends its own escrow; UNKNOWN retains it.
                held=self._namespace_values()['protected_metadata_pages_for_mutations']
                if self.db.execute('PRAGMA page_count').fetchone()[0]+held>MAX_DATABASE_PAGES:
                    raise ValueError(GLOBAL_NAMESPACE_EXHAUSTED)
            self._commit()
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise

    def _commit(self):
        sqlite_commit(lambda: self.db.execute('COMMIT'))

    @contextmanager
    def _accounting_read(self):
        """One consistent read view, or the caller's existing mutation view.

        A read ends with ROLLBACK, not a durable logical COMMIT. No new cache or
        trust boundary is introduced; every call reads current scalar rows.
        """
        self._guard()
        own=not self.db.in_transaction
        if own:self.db.execute('BEGIN')
        try:
            yield
        except BaseException as primary:
            if own and self.db.in_transaction:
                try:self.db.execute('ROLLBACK')
                except BaseException as secondary:
                    try:primary.add_note('Accounting read rollback failure: '+repr(secondary))
                    except BaseException:pass
            raise
        else:
            if own:self.db.execute('ROLLBACK')

    def _rows(self):
        # Manifest and producer BLOBs are deliberately absent. Their complete
        # bytes remain verified by seal/consume/import/export, not accounting.
        rows = self.db.execute('SELECT operation,role,state,reserved_bytes,charged_bytes,logical_bytes,allocated_bytes,write_reserved_bytes FROM grants ORDER BY operation LIMIT ?', (MAX_OPERATIONS+1,)).fetchall()
        if len(rows) > MAX_OPERATIONS:
            raise ValueError('YEAR-V4 finite physical operation population')
        for operation,role,state,reserved,charged,logical,allocated,static in rows:
            _hash(operation)
            if role not in ROLES or state not in ('RESERVED','UNKNOWN','SEALED'):
                raise ValueError('YEAR-V4 physical grant state')
            for value,name in ((reserved,'saved reserved allocation'),(charged,'saved charged allocation'),
                    (logical,'saved logical allocation'),(allocated,'saved native allocation'),(static,'saved static precharge')):
                _integer(value,name)
            if state=='SEALED' and (logical>charged or allocated>charged):
                raise ValueError('YEAR-V6 sealed scalar allocation exceeds its charge')
            if state!='SEALED' and (charged or logical or allocated):
                raise ValueError('YEAR-V6 unsettled scalar allocation is not a sealed charge')
        return rows

    def _mutable_rows(self):
        rows=self.db.execute('SELECT path,reserved_logical_bytes,charged_bytes FROM mutable ORDER BY path LIMIT ?', (MAX_FILES+1,)).fetchall()
        if len(rows)>MAX_FILES:raise ValueError('YEAR-V4 finite mutable file population')
        for path,reserved,charged in rows:
            _relative(path);_integer(reserved,'mutable logical reservation');_integer(charged,'mutable reservation')
            if reserved>charged:raise ValueError('YEAR-V6 mutable scalar allocation exceeds its charge')
        return rows

    def snapshot(self):
        with self._accounting_read():return self._snapshot_values()

    def _snapshot_values(self):
        rows=self._rows();mutable_rows=self._mutable_rows()
        used = {role: 0 for role in ROLES}; active = unknown = logical = allocated = 0
        sealed=static_bytes=0
        # Bounded validated rows and Python integers avoid SQLite SUM's
        # signed-integer overflow and mixed INTEGER/REAL coercion entirely.
        for operation,role,state,reserved,charged,size,allocation,static in rows:
            static_bytes+=static
            used[role]+=charged if state=='SEALED'else reserved
            if state!='SEALED':
                active+=reserved if role=='RETAINED'else 0
                if state=='UNKNOWN':unknown+=reserved
            else:
                sealed+=charged if role=='RETAINED'else 0
                logical+=size;allocated+=allocation
        mutable=sum(row[2]for row in mutable_rows)
        used['RETAINED']+=mutable
        for role in ROLES:
            if used[role] > self.contract[CAP_KEYS[role]]:
                raise ValueError('YEAR-V4 saved physical role exceeds cap')
        if active > self.contract['maximum_concurrent_write_reserve_bytes']:
            raise ValueError('YEAR-V4 saved active grants exceed finite cap')
        files = self.db.execute('SELECT COUNT(*) FROM files').fetchone()[0]
        if files > MAX_FILES:
            raise ValueError('YEAR-V4 finite owned file population')
        head = self.db.execute('SELECT value FROM metadata WHERE key=?', ('tip',)).fetchone()
        result=dict(format=self.owner_format, binding=dict(self.binding), contract=dict(self.contract),
            retained_owned_bytes=sealed, still_reserved_active_writes=active,
            mutable_reserved_bytes=mutable,
            static_bytes_precharged=static_bytes,
            charged_by_role=used, unknown_reserved_bytes=unknown,
            logical_sealed_bytes=logical, allocated_sealed_file_data_bytes=allocated,
            owned_files=files, operations=len(rows),
            global_retained_headroom_bytes=self.contract['global_retained_cap_bytes'] - used['RETAINED'],
            current_peak_bound_bytes=sealed + active + mutable + self.contract['terminal_checkpoint_headroom_bytes'] +
                self.contract['maximum_temporary_overlap_bytes'] + self.contract['export_allowance_bytes'] +
                self.contract['full_defined_backup_cap_bytes'] + self.contract['bounded_index_metadata_bytes'],
            whole_study_commitment_bytes=self.contract['whole_study_commitment_bytes'],
            tip=None if head is None else json.loads(head[0], object_pairs_hook=_pairs),
            capacity_status='NOT_ESTABLISHED_BY_RESOURCE_CAP')
        if self.packed:result['namespace']=self._namespace_values(grants=rows,mutable_rows=mutable_rows)
        return result

    def reservation_bytes(self, maximum_bytes, maximum_files=MAX_OPERATION_FILES):
        _integer(maximum_bytes, 'prospective payload', 1, 3 * 2**30)
        _integer(maximum_files, 'prospective files', 1, MAX_OPERATION_FILES)
        # One rounding cluster + one file metadata cluster per file, plus one
        # directory cluster per bounded directory. Sixteen ancestors are covered.
        return maximum_bytes + (3 * maximum_files + 16) * self.volume['allocation_unit_bytes']

    def can_admit_segment(self, maximum_bytes, maximum_files=MAX_OPERATION_FILES):
        if self.packed:return self.admission_status(maximum_bytes)['admitted']
        state = self.snapshot()
        amount = self.reservation_bytes(maximum_bytes + self.contract['maximum_segment_auxiliary_bytes'], maximum_files)
        return (amount <= state['global_retained_headroom_bytes'] and
                state['still_reserved_active_writes'] + amount <= self.contract['maximum_concurrent_write_reserve_bytes'])

    def namespace_snapshot(self):
        """Actual cumulative names plus unused unsettled escrow; no ABA reuse."""
        with self._accounting_read():return self._namespace_values()

    def _namespace_values(self,*,grants=None,mutable_rows=None):
        if not self.db.in_transaction:raise ValueError('YEAR-V6 namespace requires a consistent accounting view')
        grants=self._rows()if grants is None else grants
        mutable_rows=self._mutable_rows()if mutable_rows is None else mutable_rows
        states={row[0]:row[2]for row in grants};claims={};files=directories=0
        groups=self.db.execute('SELECT operation,kind,COUNT(*) FROM claims GROUP BY operation,kind LIMIT ?', (2*MAX_OPERATIONS+1,)).fetchall()
        if len(groups)>2*MAX_OPERATIONS:raise ValueError('YEAR-V4 finite producer claim groups')
        for operation,kind,count in groups:
            if operation not in states or kind not in ('FILE','DIRECTORY'):
                raise ValueError('YEAR-V6 invalid/orphan producer claim group')
            _integer(count,'producer claim group',1,2*MAX_FILES+32)
            claims[(operation,kind)]=count
            if kind=='FILE':files+=count
            else:directories+=count
        if files>MAX_FILES or files+directories>2*MAX_FILES+32:
            raise ValueError('YEAR-V4 finite global producer path population')
        mutable_scopes={}
        for path,reserved,charged in mutable_rows:
            leaf=PurePosixPath(path).name
            if leaf not in PACKED_MUTABLE_LEAVES:raise ValueError('YEAR-V6 undeclared packed mutable leaf')
            scope=PurePosixPath(path).parent.as_posix()
            mutable_scopes[scope]=mutable_scopes.get(scope,0)+1
        mutable=len(mutable_rows)
        remaining_files=remaining_dirs=pages=rows=unknown=mutable_future=protected_pages=0
        namespace=self.db.execute('SELECT n.operation,n.file_slots,n.directory_slots,n.index_rows,n.metadata_pages,n.mutable_slots,n.state,n.phase,g.scope FROM packed_namespace n LEFT JOIN grants g ON n.operation=g.operation LIMIT ?', (MAX_OPERATIONS+1,)).fetchall()
        if len(namespace)!=len(grants):raise ValueError('YEAR-V6 missing/extra namespace producer row')
        scopes=set()
        for operation,maximum,dirmax,index_rows,metadata,mutable_slots,state,phase,scope in namespace:
            if operation not in states or state!=states[operation]or phase not in ('ORDINARY','TERMINAL'):
                raise ValueError('YEAR-V6 namespace producer state drift')
            for value,name,low,high in ((maximum,'namespace file slots',1,MAX_OPERATION_FILES),(dirmax,'namespace directory slots',1,MAX_OPERATION_FILES+16),
                    (index_rows,'namespace index rows',1,PACKED_TERMINAL_INDEX_ROWS),(metadata,'namespace page slots',1,MAX_DATABASE_PAGES),
                    (mutable_slots,'namespace mutable slots',0,PACKED_MUTABLE_FILES)):
                _integer(value,name,low,high)
            if dirmax!=maximum+16 or mutable_slots not in (0,PACKED_MUTABLE_FILES):
                raise ValueError('YEAR-V6 namespace reservation shape')
            if scope is not None:_relative(scope);scopes.add(scope)
            used_files=claims.get((operation,'FILE'),0);used_dirs=claims.get((operation,'DIRECTORY'),0)
            used_mutable=mutable_scopes.get(scope,0)
            future=max(0,mutable_slots-used_mutable)
            # Mutable names belong to the original job for its full lifetime,
            # including first validation after scientific producer closure.
            mutable_future+=future;remaining_files+=future
            if state!='SEALED':
                remaining_files+=max(0,maximum-used_files)
                remaining_dirs+=max(0,dirmax-used_dirs)
                pages+=metadata;rows+=index_rows;unknown+=state=='UNKNOWN'
            elif future:
                # Retain the original conservative row/page grant; do not
                # invent a smaller late-insert pager/split bound.
                pages+=metadata;rows+=min(index_rows,future)
            if state=='UNKNOWN' or state!='SEALED'and phase!='TERMINAL' or state=='SEALED'and future:
                protected_pages+=metadata
        if any(scope not in scopes for scope in mutable_scopes):raise ValueError('YEAR-V6 mutable name without producer scope')
        return dict(format='YEAR_V5_PROSPECTIVE_TERMINAL_NAMESPACE_V2',cumulative_file_names=files,
            cumulative_directory_names=directories,mutable_names=mutable,
            unused_unsettled_file_slots=remaining_files,unused_unsettled_directory_slots=remaining_dirs,
            unsettled_metadata_pages=pages,unsettled_terminal_index_rows=rows,unknown_escrows=unknown,
            unused_persistent_mutable_file_slots=mutable_future,
            protected_metadata_pages_for_mutations=protected_pages,
            file_slot_scope='UNSETTLED_SCIENTIFIC_NAMES_PLUS_PERSISTENT_UNUSED_MUTABLE_NAMES_INCLUDING_SEALED_JOBS',
            current_database_pages=self.db.execute('PRAGMA page_count').fetchone()[0],
            maximum_database_pages=MAX_DATABASE_PAGES,maximum_file_names=MAX_FILES,
            terminal_file_slots_per_segment=PACKED_TERMINAL_FILES,
            terminal_directory_slots_per_segment=PACKED_TERMINAL_DIRECTORIES,
            retired_names='CUMULATIVE_NEVER_REUSED_SCIENTIFIC_NAMES')

    def admission_status(self, maximum_bytes):
        state=self.snapshot()
        files=PACKED_SEGMENT_FILES if self.packed else MAX_OPERATION_FILES
        amount=self.reservation_bytes(maximum_bytes+self.contract['maximum_segment_auxiliary_bytes'],files)
        if self.packed and state['namespace']['unknown_escrows']:
            # U covers one whole uncertain packed rollback journal, not a
            # second launch over that suffix. Named read/export stay separate.
            return dict(admitted=False,reason=UNKNOWN_UNSETTLED_PRODUCER,
                        required_bytes=amount,namespace=state['namespace'])
        if amount>state['global_retained_headroom_bytes'] or state['still_reserved_active_writes']+amount>self.contract['maximum_concurrent_write_reserve_bytes']:
            return dict(admitted=False,reason=GLOBAL_EXHAUSTED,required_bytes=amount)
        if self.packed:
            n=state['namespace']
            if (n['cumulative_file_names']+n['mutable_names']+n['unused_unsettled_file_slots']+files+PACKED_MUTABLE_FILES>MAX_FILES or
                    n['cumulative_directory_names']+n['unused_unsettled_directory_slots']+files+16>MAX_FILES+16 or
                    n['current_database_pages']+n['unsettled_metadata_pages']+PACKED_SEGMENT_METADATA_PAGES>MAX_DATABASE_PAGES):
                return dict(admitted=False,reason=GLOBAL_NAMESPACE_EXHAUSTED,required_bytes=amount,namespace=n)
        return dict(admitted=True,reason=None,required_bytes=amount,
                    namespace=None if not self.packed else state['namespace'])

    def reserve(self, operation, role, maximum_bytes, producer, *, scope=None,
                maximum_files=MAX_OPERATION_FILES):
        _hash(operation)
        if role not in ROLES or type(producer) is not dict or len(encoded(producer)) > 16384:
            raise ValueError('YEAR-V4 exact bounded producer reservation')
        if scope is not None:
            _relative(scope)
        charge = self.reservation_bytes(maximum_bytes, maximum_files)
        record = (operation, role, maximum_bytes, maximum_files, charge, encoded(producer), scope)
        with self._transaction():
            old = self.db.execute('SELECT operation,role,maximum_bytes,maximum_files,reserved_bytes,producer,scope FROM grants WHERE operation=?', (operation,)).fetchone()
            if old is not None:
                if old != record:
                    raise ValueError('YEAR-V4 immutable reservation/producer drift')
                return dict(operation=operation, reserved_bytes=charge, existing=True)
            segment=self.packed and producer.get('kind')=='SEGMENT'
            if segment:
                if maximum_files!=PACKED_SEGMENT_FILES:raise ValueError('YEAR-V5 exact packed segment namespace grant')
                # reserve() receives the already augmented payload bound.
                admitted=self.admission_status(max(1,maximum_bytes-self.contract['maximum_segment_auxiliary_bytes']))
                if not admitted['admitted']:raise ValueError(admitted['reason'])
            if self.packed:
                metadata_pages=PACKED_SEGMENT_METADATA_PAGES if segment or role=='BACKUP' else 128 if producer.get('kind')=='STATIC_AND_BOUNDED_ROOT_CONTROL'else 64
                mutable_slots=PACKED_MUTABLE_FILES if segment else 0
                namespace=self.namespace_snapshot()
                if (namespace['cumulative_file_names']+namespace['mutable_names']+namespace['unused_unsettled_file_slots']+maximum_files+mutable_slots>MAX_FILES or
                        namespace['cumulative_directory_names']+namespace['unused_unsettled_directory_slots']+maximum_files+16>MAX_FILES+16 or
                        namespace['current_database_pages']+namespace['unsettled_metadata_pages']+metadata_pages>MAX_DATABASE_PAGES):
                    raise ValueError(GLOBAL_NAMESPACE_EXHAUSTED)
            state = self.snapshot()
            if state['operations'] >= MAX_OPERATIONS:
                raise ValueError('YEAR-V4 finite operation population exhausted')
            if state['charged_by_role'][role] + charge > self.contract[CAP_KEYS[role]]:
                raise ValueError(GLOBAL_EXHAUSTED if role == 'RETAINED' else 'YEAR-V4 physical ' + role + ' allowance exhausted')
            if role == 'RETAINED' and state['still_reserved_active_writes'] + charge > self.contract['maximum_concurrent_write_reserve_bytes']:
                raise ValueError('YEAR-V4 active write reservation exhausted; UNKNOWN remains charged')
            if role != 'RETAINED' and self.db.execute('SELECT 1 FROM grants WHERE role=? AND state<>?', (role, 'SEALED')).fetchone() is not None:
                raise ValueError('YEAR-V4 only one active external-role publication; UNKNOWN remains charged')
            if shutil.disk_usage(self.root).free < charge + self.contract['terminal_checkpoint_headroom_bytes'] + self.contract['maximum_temporary_overlap_bytes']:
                raise ValueError('YEAR-V4 actual free space refuses prospective write')
            self.db.execute('INSERT INTO grants (operation,role,maximum_bytes,maximum_files,reserved_bytes,producer,scope,state) VALUES (?,?,?,?,?,?,?,?)', (*record, 'RESERVED'))
            if self.packed:self.db.execute('INSERT INTO packed_namespace VALUES (?,?,?,?,?,?,?,?)',
                (operation,maximum_files,maximum_files+16,PACKED_TERMINAL_INDEX_ROWS,
                 metadata_pages,mutable_slots,'ORDINARY'if segment or producer.get('kind')=='STATIC_AND_BOUNDED_ROOT_CONTROL'else'TERMINAL','RESERVED'))
        return dict(operation=operation, reserved_bytes=charge, existing=False)

    def mark_unknown(self, operation):
        _hash(operation)
        with self._transaction():
            row = self.db.execute('SELECT state FROM grants WHERE operation=?', (operation,)).fetchone()
            if row is None or row[0] == 'SEALED':
                raise ValueError('YEAR-V4 UNKNOWN requires own unsettled reservation')
            self.db.execute('UPDATE grants SET state=? WHERE operation=?', ('UNKNOWN', operation))
            if self.packed:self.db.execute('UPDATE packed_namespace SET state=? WHERE operation=?',('UNKNOWN',operation))

    def reserve_mutable(self, path, additional_bytes, producer):
        """Precharge append-only administrative bytes; no postwrite refund.

        These paths remain outside immutable pool credit. A failed append still
        consumes the precharge. Existing source owners retain their independent
        exact sequence and per-file index limits.
        """
        _relative(path)
        _integer(additional_bytes, 'mutable append', 1, 2**20)
        if type(producer) is not dict or len(encoded(producer)) > 16384:
            raise ValueError('YEAR-V4 bounded mutable producer')
        with self._transaction():
            if self.packed:
                leaf=PurePosixPath(path).name
                jid=producer.get('job_id')
                expected_scope=self.binding['store_name']+'/jobs/'+str(jid)
                if (leaf not in PACKED_MUTABLE_LEAVES or set(producer)!={'kind','job_id','leaf'} or
                        producer.get('kind')!='PARENT_APPEND_LEDGER' or producer.get('leaf')!=leaf or
                        type(jid)is not str or re.fullmatch('[0-9a-f]{32}',jid)is None or
                        path!=expected_scope+'/'+leaf):
                    raise ValueError('YEAR-V5 only three declared parent mutable names')
                scopes=self.db.execute('SELECT g.producer,g.state,n.state,n.mutable_slots FROM grants g JOIN packed_namespace n ON g.operation=n.operation WHERE g.scope=?',(expected_scope,)).fetchall()
                if len(scopes)!=1:
                    raise ValueError('YEAR-V5 mutable name needs original source namespace escrow')
                declared,state,namespace_state,slots=scopes[0];declared=json.loads(declared,object_pairs_hook=_pairs)
                if (state not in ('RESERVED','SEALED') or namespace_state!=state or slots!=PACKED_MUTABLE_FILES or
                        declared.get('kind')!='SEGMENT' or declared.get('job_id')!=jid):
                    raise ValueError('YEAR-V5 mutable name requires exact RESERVED/SEALED original job; UNKNOWN refuses')
                if self.db.execute('SELECT 1 FROM claims WHERE path=?',(path,)).fetchone()is not None:
                    raise ValueError('YEAR-V5 scientific/retired claim cannot become mutable')
            if self.db.execute('SELECT 1 FROM files WHERE path=?', (path,)).fetchone() is not None:
                raise ValueError('YEAR-V4 immutable file cannot acquire mutable authority')
            row = self.db.execute('SELECT producer,reserved_logical_bytes,charged_bytes FROM mutable WHERE path=?', (path,)).fetchone()
            if row is not None and row[0] != encoded(producer):
                raise ValueError('YEAR-V4 mutable producer drift')
            if self.packed:
                node=_node(self.root,path,missing=True)
                if row is None:
                    if node.exists():raise ValueError('YEAR-V5 unregistered mutable orphan; no adoption')
                    namespace=self.namespace_snapshot()
                    if namespace['cumulative_file_names']+namespace['mutable_names']+namespace['unused_unsettled_file_slots']>MAX_FILES:
                        raise ValueError(GLOBAL_NAMESPACE_EXHAUSTED)
                else:
                    if not node.exists():raise ValueError('YEAR-V5 prior mutable append missing; reservation remains charged')
                    info=node.stat()
                    if (not stat.S_ISREG(info.st_mode)or info.st_nlink!=1 or info.st_dev!=self.volume['device'] or
                            info.st_size!=row[1]):
                        raise ValueError('YEAR-V5 mutable partial/orphan/length drift; no refund or retry')
            old_size, old_charge = (0, 0) if row is None else (row[1], row[2])
            size = old_size + additional_bytes
            charge = _rounded(size, self.volume['allocation_unit_bytes']) + 2 * self.volume['allocation_unit_bytes']
            state = self.snapshot()
            if state['charged_by_role']['RETAINED'] + charge - old_charge > self.contract['global_retained_cap_bytes']:
                raise ValueError(GLOBAL_EXHAUSTED)
            if row is None:
                if self.db.execute("SELECT COUNT(*) FROM claims WHERE kind='FILE'").fetchone()[0] + self.db.execute('SELECT COUNT(*) FROM mutable').fetchone()[0] >= MAX_FILES:
                    raise ValueError('YEAR-V4 finite mutable file population exhausted')
                self.db.execute('INSERT INTO mutable VALUES (?,?,?,?)', (path, encoded(producer), size, charge))
            else:
                self.db.execute('UPDATE mutable SET reserved_logical_bytes=?,charged_bytes=? WHERE path=?', (size, charge, path))
        return dict(path=path, reserved_logical_bytes=size, charged_bytes=charge)

    def register_path(self, path, *, kind='FILE'):
        """Positive producer claim BEFORE creation, including directory bounds."""
        _relative(path)
        if kind not in ('FILE', 'DIRECTORY'):
            raise ValueError('YEAR-V4 producer path kind')
        with self._transaction():
            if self.db.execute('SELECT 1 FROM mutable WHERE path=?', (path,)).fetchone() is not None:
                return False
            old = self.db.execute('SELECT operation,kind,retired FROM claims WHERE path=?', (path,)).fetchone()
            if old is not None:
                if old[1] != kind:
                    raise ValueError('YEAR-V4 producer name cannot change kind or be reused after retirement')
                if old[2]:
                    grant = self.db.execute('SELECT state,producer FROM grants WHERE operation=?', (old[0],)).fetchone()
                    if grant is None or grant[0] != 'RESERVED' or json.loads(grant[1]).get('kind') != 'STATIC_AND_BOUNDED_ROOT_CONTROL':
                        raise ValueError('YEAR-V4 retired scientific producer name cannot be reused')
                    generation = self.db.execute('SELECT generation FROM claims WHERE path=?', (path,)).fetchone()[0]
                    if generation >= 2 * MAX_OPERATIONS + 16:raise ValueError('YEAR-V4 finite control-slot generations exhausted')
                    self.db.execute('UPDATE claims SET retired=0,generation=generation+1 WHERE path=?', (path,))
                return True
            candidates = [(scope, operation, state, maximum_files) for operation, scope, state, maximum_files in
                self.db.execute('SELECT operation,scope,state,maximum_files FROM grants')
                if scope is not None and (path == scope or path.startswith(scope + '/'))]
            if not candidates:
                raise ValueError('YEAR-V4 write has no prospective scoped producer grant')
            scope, operation, state, maximum_files = max(candidates, key=lambda item: (len(item[0]), item[2] == 'RESERVED'))
            if state != 'RESERVED':
                raise ValueError('YEAR-V4 closed/UNKNOWN producer cannot create files')
            escrow=None if not self.packed else self.db.execute(
                'SELECT file_slots,directory_slots,phase,state FROM packed_namespace WHERE operation=?',(operation,)).fetchone()
            critical=(PurePosixPath(path).name=='stop-request.json' or
                '/parent-errors/'in path and re.fullmatch(r'error-[0-9]{2}\.json',PurePosixPath(path).name)is not None)
            if escrow is not None and critical and escrow[2]!='TERMINAL':
                self.db.execute('UPDATE packed_namespace SET phase=? WHERE operation=?',('TERMINAL',operation))
                escrow=(escrow[0],escrow[1],'TERMINAL',escrow[3])
            names = [(path, kind)]
            parent = PurePosixPath(path).parent
            if kind == 'DIRECTORY':
                parent = PurePosixPath(path).parent
            while parent.as_posix() != '.' and (parent.as_posix() == scope or parent.as_posix().startswith(scope + '/')):
                names.append((parent.as_posix(), 'DIRECTORY'))
                parent = parent.parent
            for name, entry_kind in reversed(names):
                previous = self.db.execute('SELECT kind,retired FROM claims WHERE path=?', (name,)).fetchone()
                if previous is not None:
                    if previous[0] != entry_kind or previous[1]:
                        raise ValueError('YEAR-V4 ancestor claim kind/retirement drift')
                    continue
                count = self.db.execute('SELECT COUNT(*) FROM claims WHERE operation=? AND kind=?', (operation, entry_kind)).fetchone()[0]
                if self.packed:
                    namespace=self.namespace_snapshot()
                    if entry_kind=='FILE':
                        occupied=namespace['cumulative_file_names']+namespace['mutable_names']+namespace['unused_unsettled_file_slots']+(0 if escrow is not None else 1)
                        if occupied>MAX_FILES:raise ValueError(GLOBAL_NAMESPACE_EXHAUSTED)
                    else:
                        occupied=namespace['cumulative_directory_names']+namespace['unused_unsettled_directory_slots']+(0 if escrow is not None else 1)
                        if occupied>MAX_FILES+16:raise ValueError(GLOBAL_NAMESPACE_EXHAUSTED)
                if escrow is not None:
                    if escrow[3]!='RESERVED':raise ValueError('YEAR-V5 unknown namespace cannot create names')
                    terminal=escrow[2]=='TERMINAL' or critical
                    allowed=(escrow[0] if terminal else escrow[0]-PACKED_TERMINAL_FILES) if entry_kind=='FILE' else (escrow[1] if terminal else escrow[1]-PACKED_TERMINAL_DIRECTORIES)
                    if count>=allowed:raise ValueError('YEAR-V5 prospective terminal namespace preserved')
                    if not terminal and self.db.execute('PRAGMA page_count').fetchone()[0]>MAX_DATABASE_PAGES-PACKED_SEGMENT_METADATA_PAGES:
                        raise ValueError('YEAR-V5 prospective terminal metadata preserved')
                if count >= (maximum_files if entry_kind == 'FILE' else maximum_files + 16):
                    raise ValueError('YEAR-V4 prospective producer file/directory population exhausted')
                if self.db.execute('SELECT COUNT(*) FROM claims').fetchone()[0] >= 2 * MAX_FILES + 32:
                    raise ValueError('YEAR-V4 prospective global producer path population exhausted')
                if entry_kind == 'FILE' and (self.db.execute("SELECT COUNT(*) FROM claims WHERE kind='FILE'").fetchone()[0] + self.db.execute('SELECT COUNT(*) FROM mutable').fetchone()[0] >= MAX_FILES):
                    raise ValueError('YEAR-V4 prospective global FILE population exhausted')
                self.db.execute('INSERT INTO claims VALUES (?,?,?,0,1)', (name, operation, entry_kind))
        return True

    def precharge_static_bytes(self, path, additional_bytes):
        _relative(path); _integer(additional_bytes, 'prospective static bytes', 0, 128 * 2**20)
        if not additional_bytes:return False
        with self._transaction():
            candidates = [(scope, operation, state, producer, maximum, paid) for operation, scope, state, producer, maximum, paid in
                self.db.execute('SELECT operation,scope,state,producer,maximum_bytes,write_reserved_bytes FROM grants')
                if scope is not None and (path == scope or path.startswith(scope + '/'))]
            if not candidates:raise ValueError('YEAR-V4 bytes have no prospective producer grant')
            scope, operation, state, producer, maximum, paid = max(candidates, key=lambda item: len(item[0]))
            if json.loads(producer).get('kind') != 'STATIC_AND_BOUNDED_ROOT_CONTROL':return False
            if state != 'RESERVED' or paid + additional_bytes > maximum:
                raise ValueError('YEAR-V4 prospective STATIC cumulative byte budget exhausted')
            self.db.execute('UPDATE grants SET write_reserved_bytes=write_reserved_bytes+? WHERE operation=?', (additional_bytes, operation))
        return True

    def retire_path(self, path):
        """Source-owned post-unlink settlement; its operation charge is retained."""
        _relative(path)
        with self._transaction():
            node = _node(self.root, path, missing=True)
            if node.exists() or node.is_symlink():
                raise ValueError('YEAR-V4 retirement requires proven absent owned path')
            old = self.db.execute('SELECT operation,generation,retired FROM claims WHERE path=?', (path,)).fetchone()
            if old is None:
                raise ValueError('YEAR-V4 cannot retire an unclaimed producer path')
            if self.db.execute('SELECT 1 FROM files WHERE path=?', (path,)).fetchone() is not None:
                raise ValueError('YEAR-V4 sealed immutable file cannot be retired implicitly')
            if old[2]:return
            if self.db.execute('SELECT COUNT(*) FROM claim_retirements').fetchone()[0] >= 2 * MAX_FILES:
                raise ValueError('YEAR-V4 finite retirement evidence population exhausted')
            self.db.execute('INSERT INTO claim_retirements VALUES (?,?,?)', (path, old[1], old[0]))
            self.db.execute('UPDATE claims SET retired=1 WHERE path=?', (path,))

    def producer_inventory(self, operation):
        """Read only positively registered producer paths, never discover files."""
        _hash(operation)
        entries = []
        for name, kind, retired in self.db.execute('SELECT path,kind,retired FROM claims WHERE operation=? ORDER BY path', (operation,)):
            if kind != 'FILE' or retired:
                continue
            if self.db.execute('SELECT 1 FROM mutable WHERE path=?', (name,)).fetchone() is not None:
                continue
            path = _node(self.root, name)
            if not path.is_file() or path.stat().st_size > 3 * 2**30:
                raise ValueError('YEAR-V4 registered producer file missing/oversized')
            content = sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(2**20), b''):
                    content.update(block)
            entries.append(dict(path=name, sha256=content.hexdigest(), bytes=path.stat().st_size))
        return entries

    def _complete_scope(self, scope, names, maximum_files):
        if scope is None:
            raise ValueError('YEAR-V4 sealing requires an explicitly bounded producer scope')
        node = _node(self.root, scope)
        if node.is_file():
            if names != {scope}:
                raise ValueError('YEAR-V4 file producer inventory is incomplete')
            return 0
        files = set(); directories = 1
        # Enumeration is a negative completeness test only. It NEVER supplies
        # positive ownership or hashes for a producer inventory.
        for folder, dirs, members in os.walk(node, followlinks=False):
            directories += len(dirs)
            if directories > MAX_FILES + 16:
                raise ValueError('YEAR-V4 bounded producer directory population')
            for name in dirs + members:
                path = Path(folder) / name
                relative = path.relative_to(self.root).as_posix()
                _node(self.root, relative)
                if name in members:
                    files.add(relative)
                    if len(files) > MAX_FILES:
                        raise ValueError('YEAR-V4 bounded producer file population')
        mutable = {name for name, maximum in self.db.execute('SELECT path,reserved_logical_bytes FROM mutable')
            if name == scope or name.startswith(scope + '/')}
        for name in mutable:
            path = _node(self.root, name, missing=True)
            if path.exists():
                maximum = self.db.execute('SELECT reserved_logical_bytes FROM mutable WHERE path=?', (name,)).fetchone()[0]
                if not path.is_file() or path.stat().st_size > maximum:
                    raise ValueError('YEAR-V4 mutable producer exceeds prepaid logical bytes')
        other_owned = {name for name, in self.db.execute('SELECT path FROM files')
            if name == scope or name.startswith(scope + '/')}
        for name in other_owned - names:
            sha, size = self.db.execute('SELECT sha256,bytes FROM files WHERE path=?', (name,)).fetchone()
            _file(self.root, dict(path=name, sha256=sha, bytes=size), self.volume)
        if files != names | (mutable & files) | (other_owned & files):
            raise ValueError('YEAR-V4 unlisted/orphan producer files remain charged')
        return directories

    def seal(self, operation, inventory, *, producer, settlement, tip=None):
        """Fsync exact immutable files, then commit ownership and optional tip.

        `settlement` is made by the existing owned cleanup consumer after its
        live producers close. It cannot grant execution rights. Any validation
        or commit failure preserves the prior full reservation and prior tip.
        """
        _hash(operation)
        if type(inventory) not in (list, tuple) or len(inventory) > MAX_OPERATION_FILES:
            raise ValueError('YEAR-V4 finite explicit producer inventory')
        with self._transaction():
            row = self.db.execute('SELECT role,maximum_bytes,maximum_files,reserved_bytes,producer,scope,state,manifest FROM grants WHERE operation=?', (operation,)).fetchone()
            if row is None or encoded(producer) != row[4]:
                raise ValueError('YEAR-V4 exact reserved producer required')
            expected = dict(format=SETTLEMENT_PACKED if self.packed else 'YEAR_V4_OWNED_CLOSED_PRODUCER_V1', binding=self.binding,
                producer=producer, scope=row[5], closed=True, ownership_valid=True,
                uncertain_suffix=False)
            if type(settlement) is not dict or settlement != expected:
                raise ValueError('YEAR-V4 exact closed owned settlement required')
            names = [entry.get('path') if type(entry) is dict else None for entry in inventory]
            if len(set(names)) != len(names) or len(names) > row[2]:
                raise ValueError('YEAR-V4 duplicate/oversized producer inventory')
            for name in names:
                _relative(name)
                if not (name == row[5] or name.startswith(row[5] + '/')):
                    raise ValueError('YEAR-V4 producer file outside reserved scope')
            expected_names = {name for name, in self.db.execute('SELECT path FROM claims WHERE operation=? AND kind=? AND retired=0', (operation, 'FILE'))
                if self.db.execute('SELECT 1 FROM mutable WHERE path=?', (name,)).fetchone() is None}
            if set(names) != expected_names:
                raise ValueError('YEAR-V4 explicit inventory differs from positive producer claims')
            directories = self._complete_scope(row[5], set(names), row[2])
            files = [_file(self.root, entry, self.volume, sync=True) for entry in sorted(inventory, key=lambda value: value['path'])]
            self._sync_directories(names, row[5])
            logical = sum(entry['bytes'] for entry in files)
            charged = sum(entry['charged_bytes'] for entry in files) + directories * self.volume['allocation_unit_bytes']
            allocated = sum(entry['allocated_bytes'] for entry in files)
            if logical > row[1] or charged > row[3]:
                raise ValueError('YEAR-V4 sealed producer exceeds its prospective reservation')
            manifest = encoded(dict(format=self.owner_format, binding=self.binding, operation=operation,
                producer=producer, settlement=settlement, files=files,
                directories=directories, charged_bytes=charged, logical_bytes=logical,
                allocated_file_data_bytes=allocated, tip=tip))
            if len(manifest) > 2 * 2**20:
                raise ValueError('YEAR-V4 bounded ownership manifest')
            if row[6] == 'SEALED':
                if row[7] != manifest:
                    raise ValueError('YEAR-V4 immutable sealed ownership drift')
                return dict(operation=operation, manifest_sha256=digest(manifest), existing=True)
            if self.db.execute('SELECT COUNT(*) FROM files').fetchone()[0] + len(files) > MAX_FILES:
                raise ValueError('YEAR-V4 finite owned file population exhausted')
            for entry in files:
                self.db.execute('INSERT INTO files VALUES (?,?,?,?,?,?)', (entry['path'], operation,
                    entry['sha256'], entry['bytes'], entry['charged_bytes'], entry['allocated_bytes']))
            self.db.execute('UPDATE grants SET state=?,manifest=?,charged_bytes=?,logical_bytes=?,allocated_bytes=? WHERE operation=?',
                ('SEALED', manifest, charged, logical, allocated, operation))
            if self.packed:
                self.db.execute('UPDATE packed_namespace SET state=? WHERE operation=?',('SEALED',operation))
                previous=self.db.execute('SELECT sequence,cumulative_allocated_bytes,chain FROM packed_pool_seals ORDER BY sequence DESC LIMIT 1').fetchone()
                sequence,cumulative,chain=(0,0,'0'*64)if previous is None else previous
                sequence+=1
                chain=digest(dict(previous=chain,sequence=sequence,operation=operation,
                    manifest_sha256=digest(manifest),allocated_bytes=allocated))
                self.db.execute('INSERT INTO packed_pool_seals VALUES (?,?,?,?)',
                    (sequence,operation,cumulative+allocated,chain))
            if tip is not None:
                if len(encoded(tip)) > 16384:
                    raise ValueError('YEAR-V4 bounded committed tip')
                self.db.execute('UPDATE metadata SET value=? WHERE key=?', (encoded(tip), 'tip'))
        return dict(operation=operation, manifest_sha256=digest(manifest),
            logical_bytes=logical, charged_bytes=charged, allocated_file_data_bytes=allocated,
            files=len(files), existing=False)

    def inventory(self):
        self._guard()
        entries = [dict(path=name, sha256=sha, bytes=size) for name, sha, size in
            self.db.execute('SELECT path,sha256,bytes FROM files ORDER BY path')]
        if len(entries) > MAX_FILES:
            raise ValueError('YEAR-V4 finite inventory population')
        return entries

    def _sync_directories(self, names, scope):
        if os.name == 'nt':
            # The Windows experimental owner retains the established file
            # fsync + atomic-name guarantees. It does not claim independently
            # qualified power-loss durability of directory metadata.
            return
        directories = {self.root}
        for name in (*names, scope):
            node = _node(self.root, name)
            current = node if node.is_dir() else node.parent
            while current.is_relative_to(self.root):
                directories.add(current)
                if current == self.root:break
                current = current.parent
        for directory in sorted(directories, key=lambda value: len(value.parts), reverse=True):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:fsync(fd, directory=True)
            finally:os.close(fd)


def binding_for_store(store):
    return dict(root_identity=store.meta['root_identity'], source_identity=store.meta['source_identity'],
        input_sha256=store.meta['input_sha256'], policy_identity=store.runner_policy.identity,
        store_name=store.directory.name)


def open_for_store(store, *, create=False):
    return PhysicalStorage(store.directory.parent, store.runner_policy,
                           binding_for_store(store), create=create)


def reserve_for_intent(store, intent, *, job_id=None, request_sha256=None):
    """Called by prepare_job BEFORE request publication, including direct callers."""
    operation = digest(dict(kind='SEGMENT', intent=intent))
    if type(job_id) is not str or re.fullmatch('[0-9a-f]{32}', job_id) is None:
        raise ValueError('YEAR-V4 request-bound producer job id required')
    _hash(request_sha256)
    producer = dict(kind='SEGMENT', intent_sha256=digest(intent),
        job_id=job_id, request_sha256=request_sha256)
    scope = store.directory.name + '/jobs/' + job_id
    with open_for_store(store) as owner:
        # The supervisor only checks headroom; the complete request-bound grant
        # is created by prepare_job once the final job id exists.
        return owner.reserve(operation, 'RETAINED', intent['maximum_output_bytes'] + owner.contract['maximum_segment_auxiliary_bytes'],
            producer, scope=scope,maximum_files=PACKED_SEGMENT_FILES if owner.packed else MAX_OPERATION_FILES)


def activate_terminal_for_job_directory(directory):
    """Source checkpoint owner enters its reserved terminal namespace, once.

    Called only for existing terminal checkpoint kinds, before publication;
    this administrative flag creates no execution/checkpoint authority.
    """
    owner=_owner_for_path(Path(directory)/'terminal.json')
    if owner is None:return False
    with owner:
        if not owner.packed:return False
        scope=Path(directory).absolute().relative_to(owner.root).as_posix()
        with owner._transaction():
            rows=owner.db.execute('SELECT n.operation,n.state FROM packed_namespace n JOIN grants g ON n.operation=g.operation WHERE g.scope=?',(scope,)).fetchall()
            if len(rows)!=1 or rows[0][1]!='RESERVED':raise ValueError('YEAR-V5 terminal namespace requires own active reserved producer')
            owner.db.execute('UPDATE packed_namespace SET phase=? WHERE operation=?',('TERMINAL',rows[0][0]))
    return True


def reserve_parent_metadata(store, job_id, leaf, additional_bytes):
    if leaf not in ('parent-publication-work.bin', 'parent-codec-work.bin', 'parent-validation-work.bin'):
        raise ValueError('YEAR-V4 named mutable parent ledger')
    if type(job_id) is not str or re.fullmatch('[0-9a-f]{32}', job_id) is None:
        raise ValueError('YEAR-V4 exact mutable parent job')
    with open_for_store(store) as owner:
        return owner.reserve_mutable(store.directory.name + '/jobs/' + job_id + '/' + leaf,
            additional_bytes, dict(kind='PARENT_APPEND_LEDGER', job_id=job_id, leaf=leaf))


def seal_for_job(store, job, inventory=None):
    from .lifetime_campaign import validate_settled_parent
    validate_settled_parent(store, job)
    operation = digest(dict(kind='SEGMENT', intent=job['intent']))
    request = store.path('jobs', job['job_id'], 'request.json')
    producer = dict(kind='SEGMENT', intent_sha256=digest(job['intent']),
        job_id=job['job_id'], request_sha256=sha256(request.read_bytes()).hexdigest())
    with open_for_store(store) as owner:
        if owner.packed:
            # Source-owned closure validates this newly completed job's blocks
            # and ranges once before positive physical ownership is committed.
            # An unindexed append tail cannot receive credit from its filename.
            from .lifetime_packed_status import PackedStatus
            with PackedStatus(store.path('jobs',job['job_id'],'status63'),store._status_binding(job['job_id']))as packed:
                packed.verify_import()
        if inventory is None:
            inventory = owner.producer_inventory(operation)
        settlement = dict(format=SETTLEMENT_PACKED if owner.packed else 'YEAR_V4_OWNED_CLOSED_PRODUCER_V1', binding=owner.binding,
            producer=producer, scope=store.directory.name + '/jobs/' + job['job_id'],
            closed=True, ownership_valid=True, uncertain_suffix=False)
        return owner.seal(operation, inventory, producer=producer, settlement=settlement,
            tip=dict(job_id=job['job_id'], checkpoint_sha256=job['result']['checkpoint']['sha256'],
                     clock=job['result']['clock']))


def pool_owners(directory, key):
    path = Path(directory).absolute()
    names = (('STORE', path.name, 'DIRECTORY'), ('INITIAL_PACKAGE', path.name + '.initial.zip', 'FILE'),
             ('EXPORT', path.name + '.exports', 'DIRECTORY'), ('BACKUP', path.name + '.backup', 'DIRECTORY'))
    return [dict(owner=digest(dict(key=key, role=role, path=name)), role=role, path=name, kind=kind,
                 identity=digest(dict(key=key, role=role, method=FORMAT))) for role, name, kind in names]


def prepare_owner(directory, policy, binding, *, initial_package=False):
    """Whole-study pool and static grant BEFORE the new store's first output."""
    from .lifetime_policy import windows_policy
    path = Path(directory).absolute()
    if binding['store_name'] != path.name:
        raise ValueError('YEAR-V4 physical owner path binding')
    key = digest(_binding(binding))
    reserve_pool(path.parent, key, policy, owners=pool_owners(path, key), windows=windows_policy(policy))
    database = path.parent / (path.name + '.physical.sqlite3')
    with PhysicalStorage(path.parent, policy, binding, create=not database.exists()) as owner:
        producer = dict(kind='STATIC_AND_BOUNDED_ROOT_CONTROL', binding=owner.binding)
        owner.reserve(digest(producer), 'RETAINED', 128 * 2**20, producer, scope=path.name)
        if initial_package:
            producer = dict(kind='INITIAL_PACKAGE', binding=owner.binding)
            owner.reserve(digest(producer), 'RETAINED', 128 * 2**20, producer,
                scope=path.name + '.initial.zip', maximum_files=1)
        result=owner.snapshot()
        if owner.packed:
            from .lifetime_incremental_pool import mark_owner_initialized
            mark_owner_initialized(path.parent,key,windows=windows_policy(policy))
        return result


def initialize_store(store):
    """Validate completed static bindings; root control reserve stays charged."""
    store._pinned()
    with open_for_store(store) as owner:
        return owner.snapshot()


def _owner_for_path(path):
    """Locate a bounded explicit owner without importing a scientific model."""
    path = Path(path).absolute()
    candidates = []
    for candidate in (path, *tuple(path.parents)[:12]):
        candidates.append((candidate, candidate.name))
        for suffix in ('.exports', '.backup', '.initial.zip'):
            if candidate.name.endswith(suffix):
                candidates.append((candidate, candidate.name[:-len(suffix)]))
    for candidate, store_name in candidates:
        database = candidate.parent / (store_name + '.physical.sqlite3')
        if not database.exists():
            _refuse_missing_declared_owner(candidate.parent, store_name)
            continue
        _root(candidate.parent)
        _volume(candidate.parent)
        if database.is_symlink() or not database.is_file() or database.stat().st_size > MAX_DATABASE_BYTES:
            raise ValueError('YEAR-V4 producer owner path drift')
        _admit_sqlite_runtime()
        db=sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        try:
            row = db.execute('SELECT value FROM metadata WHERE key=?', ('authority',)).fetchone()
        finally:
            db.close()
        if row is None or len(row[0]) > 65536:
            raise ValueError('YEAR-V4 producer owner authority missing')
        value = json.loads(row[0], object_pairs_hook=_pairs)
        if value.get('format') not in (FORMAT,FORMAT_PACKED) or value.get('binding', {}).get('store_name') != store_name:
            raise ValueError('YEAR-V4 producer owner binding drift')
        from .lifetime_policy import admit_policy
        policy = admit_policy(value['policy'])
        return PhysicalStorage(candidate.parent, policy, value['binding'])
    return None


def _refuse_missing_declared_owner(directory, store_name):
    """Never let loss of a declared owner turn a physical writer into legacy.

    These are bounded read-only probes, not reconstruction or repair. Other
    families retain the no-op path when no physical marker is present.
    """
    from .lifetime_incremental_pool import refuse_missing
    refuse_missing(directory,store_name)
    metadata = Path(directory) / store_name / 'store.json'
    if metadata.exists() or metadata.is_symlink():
        node = _node(Path(directory), store_name + '/store.json')
        if not node.is_file() or node.stat().st_size > 256 * 1024:
            raise ValueError('YEAR-V4 bounded existing store marker required')
        with node.open('rb') as stream:raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:raise ValueError('YEAR-V4 bounded existing store marker required')
        value = json.loads(raw, object_pairs_hook=_pairs)
        if type(value) is not dict:raise ValueError('YEAR-V4 exact existing store marker')
        from .lifetime_policy import STORE_PHYSICAL, METHOD_PHYSICAL, STORE_PACKED, METHOD_PACKED
        physical = (value.get('format') in (STORE_PHYSICAL,STORE_PACKED) or
            value.get('base_store_format') in (STORE_PHYSICAL,STORE_PACKED) or
            type(value.get('runner_policy')) is dict and value['runner_policy'].get('method') in (METHOD_PHYSICAL,METHOD_PACKED))
        if physical:
            if encoded(value) != raw:raise ValueError('YEAR-V4 strict canonical physical store marker')
            from .lifecycle_runner_policy import admit_runner_store_metadata
            admit_runner_store_metadata(value)
            raise ValueError('YEAR-V4 declared physical SQLite owner missing; no legacy fallback')
    # A new store's pool declaration precedes store.json. Owner loss in that
    # initial interval must fail closed as well, without creating a replacement.
    pool = Path(directory) / POOL_FILE
    if pool.exists() or pool.is_symlink():
        node = _node(Path(directory), POOL_FILE)
        if not node.is_file() or node.stat().st_size > POOL_LIMIT:
            raise ValueError('YEAR-V4 bounded declared physical pool marker')
        with node.open('rb') as stream:raw = stream.read(POOL_LIMIT + 1)
        if len(raw) > POOL_LIMIT:raise ValueError('YEAR-V4 bounded declared physical pool marker')
        value = json.loads(raw, object_pairs_hook=_pairs)
        if type(value) is not dict or set(value) != {'format', 'volume', 'pool_bytes', 'reservations'} or value.get('format') != POOL_FORMAT or encoded(value) != raw or type(value.get('reservations')) is not dict or len(value['reservations']) > 128:
            raise ValueError('YEAR-V4 strict existing physical pool marker')
        for entry in value['reservations'].values():
            if type(entry) is not dict or type(entry.get('owners')) is not list or len(entry['owners']) > 16:
                raise ValueError('YEAR-V4 bounded declared physical owner marker')
            if any(type(owner) is dict and owner.get('role') == 'STORE' and owner.get('path') == store_name for owner in entry['owners']):
                raise ValueError('YEAR-V4 declared physical SQLite owner missing; no legacy fallback')


def register_producer_path(path, *, kind='FILE', additional_bytes=0):
    owner = _owner_for_path(path)
    if owner is None:
        return False
    with owner:
        relative=Path(path).absolute().relative_to(owner.root).as_posix()
        owner.precharge_static_bytes(relative,additional_bytes)
        return owner.register_path(relative, kind=kind)


def retire_producer_path(path):
    owner = _owner_for_path(path)
    if owner is None:
        return False
    with owner:
        owner.retire_path(Path(path).absolute().relative_to(owner.root).as_posix())
    return True


def workspace_physical_entries(directory):
    """Admit only explicit physical-pool siblings for workspace reopening.

    No suffix-only ignore rule and no discovered ownership. Pool declarations,
    the read-only owner authority and positive producer records bind every
    administrative sibling. Unfinished external publications refuse reopening.
    Actual store source/input/policy binding is checked by the caller after its
    ordinary LifecycleStore constructor has independently admitted that store.
    """
    root = _root(directory)
    from .lifetime_incremental_pool import HEADER,workspace_entries
    if (root/HEADER).exists():return workspace_entries(root)
    pool = _node(root, POOL_FILE, missing=True)
    if not pool.exists():return set(), {}
    volume = _volume(root)
    sqlite_runtime = _admit_sqlite_runtime()

    def regular(path, maximum):
        node = _node(root, path.relative_to(root).as_posix())
        info = node.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_dev != volume['device'] or info.st_size > maximum:
            raise ValueError('YEAR-V4 bounded workspace physical metadata')
        return node

    regular(pool, POOL_LIMIT)
    if (root / (POOL_FILE + '.pending')).exists():
        raise ValueError('YEAR-V4 unfinished physical pool publication remains charged')
    if any((root / name).exists() for name in ('LIFETIME-POOL.json', 'LIFETIME-POOL-V2.json')):
        raise ValueError('YEAR-V4 workspace cannot mix historical physical pool namespaces')
    raw = pool.read_bytes(); value = json.loads(raw, object_pairs_hook=_pairs)
    if type(value) is not dict or set(value) != {'format', 'volume', 'pool_bytes', 'reservations'} or value['format'] != POOL_FORMAT or value['volume'] != volume or encoded(value) != raw:
        raise ValueError('YEAR-V4 workspace physical pool format/volume drift')
    _integer(value['pool_bytes'], 'workspace pool capacity', 1, 2**60)
    if type(value['reservations']) is not dict or not 1 <= len(value['reservations']) <= 128:
        raise ValueError('YEAR-V4 bounded workspace physical reservations')
    skipped = {POOL_FILE}; bindings = {}; total = 0
    lock = root / 'LIFETIME-PHYSICAL-POOL-V1.lock'
    if lock.exists():regular(lock, 1); skipped.add(lock.name)
    from .lifetime_policy import admit_policy
    for key, record in value['reservations'].items():
        _hash(key)
        if type(record) is not dict or set(record) != {'policy_identity', 'contract', 'owners', 'inventory'} or type(record['owners']) is not list:
            raise ValueError('YEAR-V4 exact workspace physical reservation')
        stores = [owner for owner in record['owners'] if type(owner) is dict and owner.get('role') == 'STORE']
        if len(stores) != 1:raise ValueError('YEAR-V4 workspace sole physical STORE owner')
        name = stores[0].get('path'); _hash(name)
        if name in bindings:raise ValueError('YEAR-V4 duplicate workspace STORE owner')
        expected_owners = sorted(pool_owners(root / name, key), key=lambda item: item['owner'])
        if record['owners'] != expected_owners:
            raise ValueError('YEAR-V4 workspace explicit independent owner identities')
        database = regular(root / (name + '.physical.sqlite3'), MAX_DATABASE_BYTES)
        db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            saved = db.execute('SELECT value FROM metadata WHERE key=?', ('authority',)).fetchone()
            if saved is None or len(saved[0]) > 65536:
                raise ValueError('YEAR-V4 workspace physical authority missing')
            authority = json.loads(saved[0], object_pairs_hook=_pairs)
            if type(authority) is not dict or set(authority) != {'format', 'binding', 'policy', 'contract', 'volume', 'sqlite_runtime'}:
                raise ValueError('YEAR-V4 exact workspace physical authority')
            binding = _binding(authority['binding']); policy = admit_policy(authority['policy'])
            limits = contract(policy)
            if (binding['store_name'] != name or digest(binding) != key or
                binding['policy_identity'] != policy.identity or record['policy_identity'] != policy.identity or
                record['contract'] != limits or authority != dict(format=FORMAT,
                    binding=binding, policy=asdict(policy), contract=limits, volume=volume, sqlite_runtime=sqlite_runtime) or encoded(authority) != saved[0]):
                raise ValueError('YEAR-V4 workspace physical source/policy/owner drift')
            store = _node(root, name)
            if not store.is_dir():raise ValueError('YEAR-V4 workspace physical store missing')
            bindings[name] = binding; total += limits['whole_study_commitment_bytes']
            skipped.add(database.name)
            journal = root / (database.name + '-journal')
            if journal.exists():
                regular(journal, MAX_JOURNAL_BYTES)
                skipped.add(journal.name)
            for owner in expected_owners:
                if owner['role'] == 'STORE':continue
                scope = owner['path']; node = _node(root, scope, missing=True)
                grants = db.execute('SELECT operation,role,maximum_bytes,state FROM grants WHERE scope=?', (scope,)).fetchall()
                if any(state != 'SEALED' for operation, role, maximum, state in grants) and owner['role'] != 'INITIAL_PACKAGE':
                    raise ValueError('YEAR-V4 unfinished external producer remains charged')
                if not node.exists():
                    if grants and owner['role'] != 'INITIAL_PACKAGE':
                        raise ValueError('YEAR-V4 sealed external producer missing')
                    continue
                if owner['role'] == 'INITIAL_PACKAGE':
                    claim = db.execute('SELECT kind,retired FROM claims WHERE path=?', (scope,)).fetchone()
                    if len(grants) != 1 or grants[0][1] != 'RETAINED' or claim != ('FILE', 0):
                        raise ValueError('YEAR-V4 initial package has no positive bounded owner')
                    regular(node, grants[0][2])
                else:
                    if not node.is_dir() or not grants:
                        raise ValueError('YEAR-V4 external directory has no sealed producer')
                    entries = [dict(path=path, sha256=sha, bytes=size) for path, sha, size in
                        db.execute('SELECT path,sha256,bytes FROM files WHERE path LIKE ?', (scope + '/%',))]
                    names = {entry['path'] for entry in entries}
                    if len(names) > MAX_FILES:raise ValueError('YEAR-V4 bounded workspace external inventory')
                    for entry in entries:_file(root, entry, volume)
                    found = set(); directories = 0
                    for folder, dirs, members in os.walk(node, followlinks=False):
                        directories += 1
                        if directories > MAX_FILES + 16:raise ValueError('YEAR-V4 bounded workspace external directories')
                        for leaf in dirs + members:
                            path = Path(folder) / leaf; relative = path.relative_to(root).as_posix()
                            _node(root, relative)
                            if leaf in members:
                                found.add(relative)
                                if len(found) > MAX_FILES:raise ValueError('YEAR-V4 bounded workspace external files')
                            elif db.execute('SELECT kind,retired FROM claims WHERE path=?', (relative,)).fetchone() != ('DIRECTORY', 0):
                                raise ValueError('YEAR-V4 unclaimed external directory')
                    if found != names:raise ValueError('YEAR-V4 orphan external files remain charged')
                skipped.add(scope)
        finally:db.close()
    if total > value['pool_bytes']:
        raise ValueError('YEAR-V4 workspace future commitments exceed pool')
    return skipped, bindings


class BoundedExportFile:
    """Seekable ZIP sink that refuses a prospective write before disk growth."""
    def __init__(self, path, maximum_bytes):
        self.maximum_bytes = _integer(maximum_bytes, 'export file cap', 1, 512 * 2**20)
        self.path = Path(path)
        register_producer_path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('xb')

    def write(self, data):
        if self.file.tell() + len(data) > self.maximum_bytes:
            raise ValueError('YEAR-V4 prospective export byte cap')
        return self.file.write(data)

    def tell(self):return self.file.tell()
    def flush(self):return self.file.flush()
    def fileno(self):return self.file.fileno()
    def seekable(self):return True

    def seek(self, offset, whence=0):
        old = self.file.tell()
        position = self.file.seek(offset, whence)
        if not 0 <= position <= self.maximum_bytes:
            self.file.seek(old)
            raise ValueError('YEAR-V4 bounded export seek')
        return position

    def close(self):
        if not self.file.closed:
            try:
                self.file.flush(); fsync(self.file.fileno())
            finally:
                self.file.close()

    def __enter__(self):return self
    def __exit__(self, *ignored):self.close()


def publish_data_export(store, plan, output, exporter):
    """Reserve -> bounded staging ZIP -> CRC/schema -> durable name -> seal.

    Failure leaves the pending object and full EXPORT grant charged. Public
    final names appear only after a closed complete independently verified ZIP.
    """
    target = Path(output).absolute()
    allowed = store.directory.parent / (store.directory.name + '.exports')
    if target.parent != allowed or target.suffix.lower() != '.zip' or target.exists() or target.is_symlink():
        raise ValueError('YEAR-V4 new file in explicitly reserved exports directory required')
    with open_for_store(store) as owner:
        _node(owner.root, target.relative_to(owner.root).as_posix(), missing=True)
        producer = dict(kind='READ_ONLY_RESULT_EXPORT', plan_identity=plan['plan_identity'],
            target=target.relative_to(owner.root).as_posix(), tip=owner.snapshot()['tip'])
        operation = digest(producer)
        maximum = owner.contract['maximum_export_operation_bytes']
        owner.reserve(operation, 'EXPORT', maximum, producer,
            scope=allowed.relative_to(owner.root).as_posix(), maximum_files=2)
        register_producer_path(allowed, kind='DIRECTORY')
        allowed.mkdir(parents=True, exist_ok=True)
        stage = allowed / ('.' + target.name + '.' + operation[:16] + '.pending.zip')
        register_producer_path(stage)
        exporter(store, plan, stage, sink_factory=lambda path: BoundedExportFile(path, maximum),
                 maximum_bytes=maximum)
        from .lifetime_result import inspect_result
        inspect_result(stage)
        register_producer_path(target)
        # Same-volume exclusive publication; an existing final never gets
        # replaced. The staging link is removed before inventory settlement.
        os.link(stage, target)
        stage.unlink(); retire_producer_path(stage)
        if os.name != 'nt':
            fd = os.open(allowed, os.O_RDONLY | os.O_DIRECTORY)
            try:fsync(fd, directory=True)
            finally:os.close(fd)
        inventory = owner.producer_inventory(operation)
        settlement = dict(format=SETTLEMENT_PACKED if owner.packed else 'YEAR_V4_OWNED_CLOSED_PRODUCER_V1', binding=owner.binding,
            producer=producer, scope=allowed.relative_to(owner.root).as_posix(),
            closed=True, ownership_valid=True, uncertain_suffix=False)
        sealed = owner.seal(operation, inventory, producer=producer, settlement=settlement)
        return dict(path=str(target), sha256=sha256(target.read_bytes()).hexdigest(),
            measured_bytes=target.stat().st_size, native_execution_rights=False,
            actual_end_seconds=inspect_result(target)['actual_end_seconds'],
            physical_manifest_sha256=sealed['manifest_sha256'])


def reserve_pool(directory, key, policy, *, owners, inventory=(), pool_bytes=None, windows=False):
    """One-device future commitment, separately versioned from historical pools.

    Old namespaces are refused, never migrated or rewritten. Explicit sealed
    inventory earns only measured allocated file-data credit. Unlisted bytes
    consume actual free space and earn zero credit.
    """
    from .lifetime_policy import packed_storage
    if packed_storage(policy):
        from .lifetime_incremental_pool import reserve_pool as incremental
        return incremental(directory,key,policy,owners=owners,inventory=inventory,pool_bytes=pool_bytes,windows=windows)
    from .lifetime_journal import lease
    _admit_sqlite_runtime()
    root = _root(directory); _hash(key)
    limits = contract(policy); volume = _volume(root)
    if type(owners) not in (list, tuple) or not 1 <= len(owners) <= 16:
        raise ValueError('YEAR-V4 finite explicit pool owners')
    clean = []
    for owner in owners:
        if type(owner) is not dict or set(owner) != {'owner', 'role', 'path', 'identity', 'kind'}:
            raise ValueError('YEAR-V4 exact pool owner fields')
        _hash(owner['owner']); _hash(owner['identity']); _relative(owner['path'])
        if owner['role'] not in ('STORE', 'INITIAL_PACKAGE', 'EXPORT', 'BACKUP') or owner['kind'] not in ('DIRECTORY', 'FILE'):
            raise ValueError('YEAR-V4 explicit physical owner role/kind')
        if (owner['role']=='INITIAL_PACKAGE') != (owner['kind']=='FILE'):
            raise ValueError('YEAR-V4 physical owner role/path kind binding')
        clean.append(dict(owner))
    counts={role:sum(owner['role']==role for owner in clean)for role in ('STORE','INITIAL_PACKAGE','EXPORT','BACKUP')}
    if counts!={'STORE':1,'INITIAL_PACKAGE':1,'EXPORT':1,'BACKUP':1}:
        raise ValueError('YEAR-V4 distinct complete retained/export/independent-backup owners required')
    if type(inventory) not in (list, tuple) or len(inventory) > MAX_FILES:
        raise ValueError('YEAR-V4 finite pool file inventory')
    entries = []
    for entry in inventory:
        if type(entry) is not dict or set(entry) != {'owner', 'path', 'sha256', 'bytes'}:
            raise ValueError('YEAR-V4 exact attributed pool inventory')
        bound = [owner for owner in clean if owner['owner'] == entry['owner']]
        if len(bound) != 1:
            raise ValueError('YEAR-V4 foreign pool file owner')
        scope = bound[0]['path']; name = _relative(entry['path'])
        if not (name == scope if bound[0]['kind'] == 'FILE' else name.startswith(scope + '/')):
            raise ValueError('YEAR-V4 pool file outside owner scope')
        entries.append(dict(entry))
    if len({entry['path'].casefold() for entry in entries}) != len(entries):
        raise ValueError('YEAR-V4 duplicate pool file claim')
    fresh = dict(policy_identity=policy.identity, contract=limits,
        owners=sorted(clean, key=lambda value: value['owner']),
        inventory=sorted(entries, key=lambda value: value['path']))
    lock = _node(root, 'LIFETIME-PHYSICAL-POOL-V1.lock', missing=True)
    with lease(lock, windows=windows):
        if any((root / name).exists() for name in ('LIFETIME-POOL.json', 'LIFETIME-POOL-V2.json')):
            raise ValueError('YEAR-V4 isolated physical pool required; historical pools are not migrated')
        path = _node(root, POOL_FILE, missing=True)
        if path.exists():
            if path.stat().st_size > POOL_LIMIT or path.stat().st_nlink != 1:
                raise ValueError('YEAR-V4 bounded pool metadata')
            raw = path.read_bytes(); value = json.loads(raw, object_pairs_hook=_pairs)
            if type(value) is not dict or set(value) != {'format', 'volume', 'pool_bytes', 'reservations'} or value['format'] != POOL_FORMAT or value['volume'] != volume or encoded(value) != raw:
                raise ValueError('YEAR-V4 pool volume/format/canonical drift')
            if pool_bytes is not None and pool_bytes != value['pool_bytes']:
                raise ValueError('YEAR-V4 immutable shared pool capacity')
        else:
            free = shutil.disk_usage(root).free
            capacity = max(0, free - 2**30) if pool_bytes is None else pool_bytes
            _integer(capacity, 'shared pool capacity', 1, 2**60)
            if capacity > free:
                raise ValueError('YEAR-V4 shared commitment exceeds actual device free space')
            value = dict(format=POOL_FORMAT, volume=volume, pool_bytes=capacity, reservations={})
        if type(value['reservations']) is not dict or len(value['reservations']) > 128:
            raise ValueError('YEAR-V4 finite shared pool reservation population')
        old = value['reservations'].get(key)
        if old is not None and {name: item for name, item in old.items() if name != 'inventory'} != {name: item for name, item in fresh.items() if name != 'inventory'}:
            raise ValueError('YEAR-V4 immutable pool policy/owner commitment')
        if old is not None:
            previous = {entry['path']: entry for entry in old['inventory']}
            current = {entry['path']: entry for entry in fresh['inventory']}
            if any(current.get(name) != entry for name, entry in previous.items()):
                raise ValueError('YEAR-V4 sealed pool inventory cannot disappear or drift')
        proposed = dict(value['reservations']); proposed[key] = fresh
        if len(proposed) > 128:
            raise ValueError('YEAR-V4 finite shared pool population')
        claims = []; credit = 0; total = 0; inodes = set()
        for saved_key, entry in proposed.items():
            _hash(saved_key)
            if type(entry) is not dict or set(entry) != {'policy_identity', 'contract', 'owners', 'inventory'}:
                raise ValueError('YEAR-V4 exact saved pool reservation')
            _hash(entry['policy_identity'])
            if entry['contract'] != limits:
                raise ValueError('YEAR-V4 source-owned physical contract drift')
            if type(entry['owners']) is not list or not 1 <= len(entry['owners']) <= 16 or type(entry['inventory']) is not list or len(entry['inventory']) > MAX_FILES:
                raise ValueError('YEAR-V4 saved bounded owner/inventory populations')
            total += entry['contract']['whole_study_commitment_bytes']
            owner_index = {}
            for owner in entry['owners']:
                if type(owner) is not dict or set(owner) != {'owner', 'role', 'path', 'identity', 'kind'}:
                    raise ValueError('YEAR-V4 saved exact pool owner fields')
                _hash(owner['owner']); _hash(owner['identity'])
                if owner['role'] not in ('STORE', 'INITIAL_PACKAGE', 'EXPORT', 'BACKUP') or owner['kind'] not in ('DIRECTORY', 'FILE'):
                    raise ValueError('YEAR-V4 saved pool owner role/kind')
                if (owner['role']=='INITIAL_PACKAGE') != (owner['kind']=='FILE'):
                    raise ValueError('YEAR-V4 saved pool role/path kind binding')
                owner_index[owner['owner']] = owner
                scope = _relative(owner['path']).casefold()
                if any(scope == old_scope or scope.startswith(old_scope + '/') or old_scope.startswith(scope + '/') or owner['owner'] == old_owner for old_scope, old_owner in claims):
                    raise ValueError('YEAR-V4 overlapping physical pool owners')
                claims.append((scope, owner['owner']))
            if {role:sum(owner['role']==role for owner in entry['owners']) for role in ('STORE','INITIAL_PACKAGE','EXPORT','BACKUP')} != {'STORE':1,'INITIAL_PACKAGE':1,'EXPORT':1,'BACKUP':1}:
                raise ValueError('YEAR-V4 saved pool incomplete independent physical owners')
            role_bytes = {'STORE': 0, 'INITIAL_PACKAGE': 0, 'EXPORT': 0, 'BACKUP': 0}
            names = set()
            for item in entry['inventory']:
                if type(item) is not dict or set(item) != {'owner', 'path', 'sha256', 'bytes'} or item['owner'] not in owner_index:
                    raise ValueError('YEAR-V4 saved exact producer inventory attribution')
                owner = owner_index[item['owner']]; name = _relative(item['path'])
                if name.casefold() in names or not (name == owner['path'] if owner['kind'] == 'FILE' else name.startswith(owner['path'] + '/')):
                    raise ValueError('YEAR-V4 duplicate/foreign saved file attribution')
                names.add(name.casefold())
                plain = {name: item[name] for name in ('path', 'sha256', 'bytes')}
                measured = _file(root, plain, volume)
                info = _node(root, item['path']).stat(); inode = (info.st_dev, info.st_ino)
                if inode in inodes:raise ValueError('YEAR-V4 duplicate physical file credit')
                inodes.add(inode)
                credit += measured['allocated_bytes']
                role_bytes[owner['role']] += measured['charged_bytes']
            if (role_bytes['STORE'] + role_bytes['INITIAL_PACKAGE'] > limits['global_retained_cap_bytes'] or
                role_bytes['EXPORT'] > limits['export_allowance_bytes'] or role_bytes['BACKUP'] > limits['full_defined_backup_cap_bytes']):
                raise ValueError('YEAR-V4 materialized inventory exceeds distinct physical role')
        if total > value['pool_bytes']:
            raise ValueError('YEAR-V4 all-design whole-study commitment exhausted')
        outstanding = max(0, total - credit)
        free = shutil.disk_usage(root).free
        if free < outstanding + 2**20:
            raise ValueError('YEAR-V4 external/unattributed disk consumption exhausted pool')
        prospective = dict(value, reservations=proposed); raw = encoded(prospective)
        if len(raw) > POOL_LIMIT:
            raise ValueError('YEAR-V4 bounded physical pool metadata')
        pending = _node(root, POOL_FILE + '.pending', missing=True)
        # A failed previous publication keeps one bounded charged orphan and
        # blocks replay. Do not grow unbounded fresh temporary names on retry.
        with pending.open('xb') as stream:
            stream.write(raw); stream.flush(); fsync(stream.fileno())
        os.replace(pending, path)
        if os.name != 'nt':
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                fsync(fd, directory=True)
            finally:
                os.close(fd)
        return dict(pool=prospective, total_reserved_bytes=total,
            outstanding_reserved_bytes=outstanding, credited_physical_bytes=credit,
            unregistered_files_credit_bytes=0, free_bytes=free, capacity_devices=1)
