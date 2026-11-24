"""YEAR-V5 bounded per-study pool slots, not a growing per-file JSON.

Only the changed study slot is durably replaced. Credit consumes a monotone
source-owner seal sequence, validating the newly added producer bytes and real
allocation. Untouched sealed blocks are owner-controlled immutable history;
their bytes are checked on consume or explicit verify_import, not every poll.
This changed trust boundary supplies no scientific execution permission.
"""
from pathlib import Path
from dataclasses import asdict
from hashlib import sha256
import json
import os
import shutil
import sqlite3
import stat

FORMAT = 'YEAR_V5_INCREMENTAL_PHYSICAL_POOL_V2'
HEADER = 'LIFETIME-PHYSICAL-POOL-V2.json'
FOLDER = 'LIFETIME-PHYSICAL-POOL-V2'
LOCK = 'LIFETIME-PHYSICAL-POOL-V2.lock'
SLOT_BYTES = 16384
MAX_STUDIES = 128
HEADER_BYTES = 16384
POOL_METADATA_BYTES = 2 * MAX_STUDIES * SLOT_BYTES + 2 * HEADER_BYTES


def _api():
    from . import lifetime_physical_storage as p
    return p


def _namespace(root):
    meta = root.stat()
    return dict(device=meta.st_dev, directory_inode=meta.st_ino)


def _read(path, maximum):
    p = _api(); path = p._node(path.parent, path.name)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
        raise ValueError('YEAR-V5 bounded regular pool metadata')
    content = path.read_bytes(); value = json.loads(content, object_pairs_hook=p._pairs)
    if p.encoded(value) != content: raise ValueError('YEAR-V5 canonical pool metadata')
    return value


def _publish(path, value, maximum):
    p = _api(); data = p.encoded(value)
    if len(data) > maximum: raise ValueError('YEAR-V5 fixed pool slot/header byte cap')
    pending = path.with_name(path.name + '.pending')
    if pending.exists(): raise ValueError('YEAR-V5 unknown pool publication remains charged; no repair')
    with pending.open('xb') as stream:
        if stream.write(data) != len(data): raise OSError('YEAR-V5 incomplete pool slot write')
        stream.flush(); p.fsync(stream.fileno())
    os.replace(pending, path)
    if os.name != 'nt':
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: p.fsync(fd, directory=True)
        finally: os.close(fd)


def _header(root, *, create=False, pool_bytes=None):
    p = _api(); path = p._node(root, HEADER, missing=True)
    if any((root / n).exists() for n in (p.POOL_FILE, 'LIFETIME-POOL.json', 'LIFETIME-POOL-V2.json')):
        raise ValueError('YEAR-V5 separate new pool namespace; no V4 migration')
    if (root / (HEADER + '.pending')).exists():
        raise ValueError('YEAR-V5 incomplete pool header remains charged')
    volume = p._volume(root)
    if path.exists():
        value = _read(path, HEADER_BYTES)
        if (type(value) is not dict or set(value) != {'format','volume','namespace','pool_bytes','keys'} or
                value['format'] != FORMAT or value['volume'] != volume or value['namespace'] != _namespace(root)):
            raise ValueError('YEAR-V5 pool source namespace/volume drift; explicit verified import required')
        if pool_bytes is not None and pool_bytes != value['pool_bytes']:
            raise ValueError('YEAR-V5 immutable pool capacity')
        p._integer(value['pool_bytes'], 'pool bytes', 1, 2**60)
        if type(value['keys']) is not list or len(value['keys']) > MAX_STUDIES or value['keys'] != sorted(set(value['keys'])):
            raise ValueError('YEAR-V5 bounded unique study keys')
        for key in value['keys']: p._hash(key)
        return value
    if not create: return None
    if (root/FOLDER).exists():
        raise ValueError('YEAR-V5 orphan slot namespace without header; no implicit repair')
    free = shutil.disk_usage(root).free
    capacity = max(0, free - 2**30) if pool_bytes is None else pool_bytes
    p._integer(capacity, 'pool bytes', 1, 2**60)
    if capacity > free: raise ValueError('YEAR-V5 pool exceeds actual free space')
    value = dict(format=FORMAT, volume=volume, namespace=_namespace(root), pool_bytes=capacity, keys=[])
    _publish(path, value, HEADER_BYTES)
    return value


def _slot(root, key, *, create=False):
    p = _api(); p._hash(key)
    folder = p._node(root, FOLDER, missing=True)
    if not folder.exists():
        if not create:raise ValueError('YEAR-V5 declared pool slot directory missing; no repair')
        folder.mkdir()
    return p._node(root, FOLDER + '/' + key + '.json', missing=True)


def _owners(root, key, owners):
    p = _api()
    if type(owners) not in (list, tuple) or len(owners) != 4:
        raise ValueError('YEAR-V5 four explicit independent pool owners')
    stores = [x for x in owners if type(x) is dict and x.get('role') == 'STORE']
    if len(stores) != 1: raise ValueError('YEAR-V5 one STORE pool owner')
    name = stores[0].get('path'); p._hash(name)
    expected = sorted(p.pool_owners(root / name, key), key=lambda x:x['owner'])
    if sorted(owners, key=lambda x:x['owner']) != expected:
        raise ValueError('YEAR-V5 exact independent owner identities')
    return expected


def _delta(root, key, slot):
    p = _api(); store_name = next(x['path'] for x in slot['owners'] if x['role'] == 'STORE')
    database = root / (store_name + '.physical.sqlite3')
    if not database.exists():
        if (slot['credit_cursor'] or slot['credit_bytes'] or slot['owner_initialized'] or
                any((root/owner['path']).exists()for owner in slot['owners'])):
            raise ValueError('YEAR-V5 credited physical owner disappeared')
        return dict(slot), 0, 0
    p._admit_sqlite_runtime()
    meta=p._node(root,database.name).stat()
    if not stat.S_ISREG(meta.st_mode)or meta.st_nlink!=1 or meta.st_size>p.MAX_DATABASE_BYTES:
        raise ValueError('YEAR-V5 bounded own credit ledger required')
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)
    read_bytes = verified_files = 0
    try:
        authority = db.execute('SELECT value FROM metadata WHERE key=?', ('authority',)).fetchone()
        if authority is None or len(authority[0]) > 65536: raise ValueError('YEAR-V5 pool owner authority missing')
        value = json.loads(authority[0], object_pairs_hook=p._pairs)
        binding = p._binding(value['binding'])
        from .lifetime_policy import admit_policy,packed_storage
        policy=admit_policy(value['policy'])
        if (value.get('format') != p.FORMAT_PACKED or p.digest(binding) != key or
                not packed_storage(policy)or policy.identity!=slot['policy_identity']or
                value['contract']!=p.contract(policy)or value['sqlite_runtime']!=p._admit_sqlite_runtime()or
                value['contract'] != slot['contract'] or binding['policy_identity'] != slot['policy_identity'] or
                value['volume'] != p._volume(root) or p.encoded(value) != authority[0]):
            raise ValueError('YEAR-V5 incremental owner authority binding')
        if slot['credit_cursor']:
            cached=db.execute('SELECT cumulative_allocated_bytes,chain FROM packed_pool_seals WHERE sequence=?',(slot['credit_cursor'],)).fetchone()
            if cached!=(slot['credit_bytes'],slot['credit_chain']):
                raise ValueError('YEAR-V5 cached credit lacks positive committed owner ledger binding')
        elif slot['credit_bytes']!=0 or slot['credit_chain']!='0'*64:
            raise ValueError('YEAR-V5 zero cursor has no physical credit')
        rows = db.execute('SELECT sequence,operation,cumulative_allocated_bytes,chain FROM packed_pool_seals WHERE sequence>? ORDER BY sequence',
                          (slot['credit_cursor'],)).fetchall()
        if len(rows) > p.MAX_OPERATIONS: raise ValueError('YEAR-V5 finite added seal population')
        result = dict(slot)
        for sequence, operation, cumulative, committed_chain in rows:
            if type(sequence) is not int or sequence != result['credit_cursor'] + 1:
                raise ValueError('YEAR-V5 exact monotone seal cursor')
            grant = db.execute('SELECT state,manifest,allocated_bytes FROM grants WHERE operation=?', (operation,)).fetchone()
            if grant is None or grant[0] != 'SEALED': raise ValueError('YEAR-V5 cursor refers only to closed producer')
            manifest = json.loads(grant[1], object_pairs_hook=p._pairs)
            if (p.encoded(manifest) != grant[1] or manifest['format'] != p.FORMAT_PACKED or
                    manifest['binding'] != binding or manifest['operation'] != operation or
                    len(manifest['files']) > p.MAX_OPERATION_FILES):
                raise ValueError('YEAR-V5 added seal manifest binding')
            allocated = 0
            for entry in manifest['files']:
                # Reverify ONLY the newly credited closed producer bytes. A
                # name, size/mtime or saved JSON does not establish this credit.
                actual = p._file(root, {k:entry[k] for k in ('path','sha256','bytes')}, value['volume'])
                if actual != entry: raise ValueError('YEAR-V5 added allocation/producer drift')
                allocated += actual['allocated_bytes']; read_bytes += actual['bytes']; verified_files += 1
            if allocated != grant[2]: raise ValueError('YEAR-V5 positive allocation credit sum')
            result['credit_bytes'] += allocated; result['credit_cursor'] = sequence
            result['credit_chain'] = p.digest(dict(previous=result['credit_chain'], sequence=sequence,
                operation=operation, manifest_sha256=p.digest(grant[1]), allocated_bytes=allocated))
            if cumulative!=result['credit_bytes']or committed_chain!=result['credit_chain']:
                raise ValueError('YEAR-V5 added positive owner credit chain drift')
        return result, read_bytes, verified_files
    finally: db.close()


def reserve_pool(directory, key, policy, *, owners, inventory=(), pool_bytes=None, windows=False):
    p = _api(); root = p._root(directory); p._hash(key)
    from .lifetime_journal import lease
    if inventory: raise ValueError('YEAR-V5 incremental pool takes source seal deltas, not caller prefix inventory')
    clean = _owners(root,key,owners); limits = p.contract(policy)
    lock = p._node(root, LOCK, missing=True)
    with lease(lock, windows=windows):
        header = _header(root,create=True,pool_bytes=pool_bytes)
        folder=p._node(root,FOLDER,missing=True);expected_names={x+'.json'for x in header['keys']}
        found=set()
        if folder.exists():
            if not folder.is_dir():raise ValueError('YEAR-V5 pool metadata directory required')
            for path in folder.iterdir():
                if len(found)>=MAX_STUDIES or path.name not in expected_names:
                    raise ValueError('YEAR-V5 unindexed/orphan pool metadata; UNKNOWN remains reserved')
                found.add(path.name)
        if found!=expected_names:raise ValueError('YEAR-V5 indexed pool metadata missing; no repair')
        slots = {}; scopes = []; added_read_bytes=added_files=0
        for saved_key in header['keys']:
            path = _slot(root,saved_key)
            if path.with_name(path.name+'.pending').exists(): raise ValueError('YEAR-V5 unfinished slot remains charged')
            slot = _read(path,SLOT_BYTES)
            if (set(slot) != {'format','key','policy_identity','contract','owners','credit_cursor','credit_bytes','credit_chain','owner_initialized'} or
                    slot['format'] != FORMAT or slot['key'] != saved_key):
                raise ValueError('YEAR-V5 exact bounded pool slot')
            _owners(root,saved_key,slot['owners']); p._hash(slot['policy_identity']); p._hash(slot['credit_chain'])
            p._integer(slot['credit_cursor'],'seal cursor',0,p.MAX_OPERATIONS)
            p._integer(slot['credit_bytes'],'positive credit',0,8*2**30)
            if type(slot['owner_initialized'])is not bool:raise ValueError('YEAR-V5 exact initialized-owner marker')
            # Validate cached credit against the source-owned positive seal
            # ledger, then inspect only any newly added closed producer bytes.
            slots[saved_key],read_count,file_count = _delta(root,saved_key,slot)
            added_read_bytes+=read_count;added_files+=file_count
            for owner in slot['owners']:
                scope=owner['path'].casefold()
                if any(scope==old or scope.startswith(old+'/') or old.startswith(scope+'/') for old in scopes):
                    raise ValueError('YEAR-V5 distinct physical pool scopes')
                scopes.append(scope)
        fresh = dict(format=FORMAT,key=key,policy_identity=policy.identity,contract=limits,
            owners=clean,credit_cursor=0,credit_bytes=0,credit_chain='0'*64,owner_initialized=False)
        previous=slots.get(key)
        if previous is not None:
            if any(previous[n] != fresh[n] for n in ('format','key','policy_identity','contract','owners')):
                raise ValueError('YEAR-V5 immutable pool policy/source/owner')
            fresh=previous
        elif len(slots)>=MAX_STUDIES:raise ValueError('YEAR-V5 finite study population')
        else:
            for owner in clean:
                scope=owner['path'].casefold()
                if any(scope==old or scope.startswith(old+'/')or old.startswith(scope+'/')for old in scopes):
                    raise ValueError('YEAR-V5 new reservation overlaps an existing physical owner')
        fresh,read_bytes,verified_files=_delta(root,key,fresh)
        added_read_bytes+=read_bytes;added_files+=verified_files
        slots[key]=fresh
        total=sum(x['contract']['whole_study_commitment_bytes'] for x in slots.values())
        credit=sum(x['credit_bytes'] for x in slots.values())
        if total>header['pool_bytes']:raise ValueError('YEAR-V5 finite all-study commitment exhausted')
        outstanding=max(0,total-credit);free=shutil.disk_usage(root).free
        if free<outstanding+2**20:raise ValueError('YEAR-V5 external/unattributed bytes exhausted pool')
        for saved_key,updated in slots.items():
            path=_slot(root,saved_key,create=True)
            old_slot=_read(path,SLOT_BYTES)if path.exists()else None
            if old_slot!=updated:_publish(path,updated,SLOT_BYTES)
        if key not in header['keys']:
            header=dict(header,keys=sorted([*header['keys'],key]));_publish(root/HEADER,header,HEADER_BYTES)
        return dict(format=FORMAT,total_reserved_bytes=total,outstanding_reserved_bytes=outstanding,
            credited_physical_bytes=credit,unregistered_files_credit_bytes=0,free_bytes=free,
            new_sealed_file_bytes_verified=added_read_bytes,new_sealed_files_verified=added_files,
            historical_file_bytes_read=0,slot_bytes=len(p.encoded(fresh)),
            trust_scope='OWNER_CONTROLLED_IMMUTABLE_CLOSED_BLOCKS; STRICT_RANGE_CONSUME_AND_EXPLICIT_IMPORT; NOT_GLOBAL_POLL_TAMPER_DETECTION')


def mark_owner_initialized(directory,key,*,windows=False):
    p=_api();root=p._root(directory)
    from .lifetime_journal import lease
    with lease(p._node(root,LOCK,missing=True),windows=windows):
        header=_header(root)
        if header is None or key not in header['keys']:raise ValueError('YEAR-V5 declared slot before owner initialization')
        path=_slot(root,key);slot=_read(path,SLOT_BYTES)
        store=next(x['path']for x in slot['owners']if x['role']=='STORE')
        if not (root/(store+'.physical.sqlite3')).exists():raise ValueError('YEAR-V5 positive owner must exist before initialized marker')
        updated,_,_=_delta(root,key,slot)
        updated=dict(updated,owner_initialized=True)
        if updated!=slot:_publish(path,updated,SLOT_BYTES)


def workspace_entries(directory):
    p=_api();root=p._root(directory);header=_header(root)
    if header is None:return set(),{}
    skipped={HEADER,FOLDER};bindings={};total=0
    if (root/LOCK).exists():
        node=p._node(root,LOCK);info=node.stat()
        if not stat.S_ISREG(info.st_mode)or info.st_nlink!=1 or info.st_size>65536:
            raise ValueError('YEAR-V5 bounded regular pool lock')
        skipped.add(LOCK)
    folder=p._node(root,FOLDER)
    expected={key+'.json' for key in header['keys']}
    observed=set()
    for node in folder.iterdir():
        if len(observed)>=MAX_STUDIES or node.name not in expected:
            raise ValueError('YEAR-V5 unindexed/pending pool metadata; no repair')
        observed.add(node.name)
    if observed != expected:
        raise ValueError('YEAR-V5 unindexed/pending pool metadata; no repair')
    from .lifetime_policy import admit_policy
    for key in header['keys']:
        slot=_read(_slot(root,key),SLOT_BYTES);owners=_owners(root,key,slot['owners'])
        name=next(x['path'] for x in owners if x['role']=='STORE')
        database=p._node(root,name+'.physical.sqlite3')
        info=database.stat()
        if not stat.S_ISREG(info.st_mode)or info.st_nlink!=1 or info.st_size>p.MAX_DATABASE_BYTES:
            raise ValueError('YEAR-V5 bounded single-link owner ledger')
        db=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=5)
        try:
            row=db.execute('SELECT value FROM metadata WHERE key=?',('authority',)).fetchone()
            if row is None or len(row[0])>65536:raise ValueError('YEAR-V5 owner authority missing')
            a=json.loads(row[0],object_pairs_hook=p._pairs);b=p._binding(a['binding']);policy=admit_policy(a['policy'])
            if (a['format']!=p.FORMAT_PACKED or p.digest(b)!=key or b['store_name']!=name or
                    a['contract']!=p.contract(policy) or slot['contract']!=a['contract'] or
                    slot['policy_identity']!=policy.identity or p.encoded(a)!=row[0]):
                raise ValueError('YEAR-V5 explicit source/owner/policy workspace binding')
            bindings[name]=b;total+=slot['contract']['whole_study_commitment_bytes'];skipped.add(database.name)
            journal=root/(database.name+'-journal')
            if journal.exists():
                meta=p._node(root,journal.name).stat()
                if not stat.S_ISREG(meta.st_mode)or meta.st_nlink!=1 or meta.st_size>p.MAX_JOURNAL_BYTES:
                    raise ValueError('YEAR-V5 bounded single-link owner journal')
                skipped.add(journal.name)
            for owner in owners:
                if owner['role']=='STORE':continue
                node=p._node(root,owner['path'],missing=True)
                if not node.exists():continue
                grants=db.execute('SELECT operation,role,maximum_bytes,state FROM grants WHERE scope=?',(owner['path'],)).fetchall()
                if not grants or owner['role']!='INITIAL_PACKAGE' and any(x[3]!='SEALED'for x in grants):
                    raise ValueError('YEAR-V5 unclosed external producer remains charged')
                if owner['role']=='INITIAL_PACKAGE':
                    claim=db.execute('SELECT kind,retired FROM claims WHERE path=?',(owner['path'],)).fetchone()
                    info=node.stat()
                    if (len(grants)!=1 or grants[0][1]!='RETAINED' or claim!=('FILE',0) or
                            not stat.S_ISREG(info.st_mode)or info.st_nlink!=1 or info.st_size>grants[0][2]):
                        raise ValueError('YEAR-V5 initial package lacks positive bounded owner')
                elif not node.is_dir():
                    raise ValueError('YEAR-V5 sealed external directory required')
                skipped.add(owner['path'])
        finally:db.close()
    if total>header['pool_bytes']:raise ValueError('YEAR-V5 workspace future commitment exceeds pool')
    return skipped,bindings


def refuse_missing(directory, store_name):
    p=_api();root=Path(directory)
    if not (root/HEADER).exists():return
    header=_header(root)
    for key in header['keys']:
        slot=_read(_slot(root,key),SLOT_BYTES)
        if any(x['role']=='STORE'and x['path']==store_name for x in slot['owners']):
            raise ValueError('YEAR-V5 declared physical owner missing; no legacy fallback')
