"""One shared filesystem pool; mirrors are one capacity, backups need reserve."""
from pathlib import Path
from dataclasses import asdict
import json,os,shutil,tempfile
from .lifetime_journal import lease,encoded

FORMAT='B62_SHARED_DATA_RESERVATION_POOL_V1'

def measure(path):
    total=count=0
    for p in Path(path).rglob('*'):
        if p.is_symlink():raise ValueError('B62 pool links forbidden')
        if p.is_file():
            count+=1;total+=p.stat().st_size
            if count>2**20:raise ValueError('B62 measured file population')
    return dict(measured_bytes=total,files=count)

def reserve(directory,key,policy,*,pool_bytes=None,windows=False):
    root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=True)
    if type(key)is not str or len(key)!=64 or any(c not in '0123456789abcdef'for c in key):raise ValueError('B62 pool identity')
    with lease(root/'LIFETIME-POOL.lock',windows=windows):
        path=root/'LIFETIME-POOL.json'
        if path.is_symlink():raise ValueError('B62 pool metadata link')
        free=shutil.disk_usage(root).free
        if path.exists():
            if path.stat().st_size>2**20:raise ValueError('B62 pool metadata bytes')
            v=json.loads(path.read_bytes())
        else:
            cap=max(0,free-2**30)if pool_bytes is None else pool_bytes
            if type(cap)is not int or not 0<cap<=free:raise ValueError('B62 finite pool capacity; mirror capacity not added')
            v=dict(format=FORMAT,device=os.stat(root).st_dev,pool_bytes=cap,reservations={})
        if type(v)is not dict or set(v)!={'format','device','pool_bytes','reservations'}or v['format']!=FORMAT or v['device']!=os.stat(root).st_dev or type(v['pool_bytes'])is not int or not 0<v['pool_bytes']<=2**60 or type(v['reservations'])is not dict or len(v['reservations'])>128:raise ValueError('B62 pool binding')
        entry=dict(policy_identity=policy.identity,retained_store_and_initial_bytes=policy.maximum_reserved_job_output_bytes,backup_and_export_reserve_bytes=policy.maximum_reserved_job_output_bytes*policy.backup_copies,total_reserved_bytes=policy.pool_commitment_bytes)
        if key in v['reservations'] and v['reservations'][key]!=entry:raise ValueError('B62 pool policy drift')
        for k,x in v['reservations'].items():
            if type(x)is not dict or set(x)!=set(entry)or any(type(x[n])is not int or x[n]<0 for n in entry if n!='policy_identity')or x['total_reserved_bytes']!=x['retained_store_and_initial_bytes']+x['backup_and_export_reserve_bytes']:raise ValueError('B62 pool record')
        proposed=dict(v['reservations']);proposed[key]=entry
        if len(proposed)>128 or sum(x['total_reserved_bytes']for x in proposed.values())>v['pool_bytes']:raise ValueError('B62 all-design prospective pool exhausted')
        measured=measure(root)
        # Repeated admission doesn't subtract already written data twice.
        if measured['measured_bytes']+free<sum(x['total_reserved_bytes']for x in proposed.values())+2**20:raise ValueError('B62 external disk consumption exhausted reserved pool')
        v['reservations']=proposed
        with tempfile.NamedTemporaryFile('wb',dir=root,prefix='.b62-pool-',delete=False)as f:
            f.write(encoded(v));f.flush();os.fsync(f.fileno());tmp=Path(f.name)
        os.replace(tmp,path)
        return dict(pool=v,measured=measured,free_bytes=free,cap_is_not_measured_use=True,retention='ALL_JOBS_NO_AUTOMATIC_REFUND_OR_DELETION')


# The V1 owner above is preserved for historical stores.  New B63 stores use a
# separate namespace and an explicitly attributed inventory, never measure(root)
# as reservation credit.  A V1 pool cannot silently acquire V2 ownership claims.
FORMAT_V2='B63_BOUND_OWNED_RESERVATION_POOL_V2'
POOL_V2='LIFETIME-POOL-V2.json'
MAX_POOL_V2_BYTES=2**20
MAX_V2_RESERVATIONS=128
MAX_V2_OWNERS=32
MAX_V2_FILES=4096
POOL_SAFETY_BYTES=2**20


def _v2_hash(value,name):
    if type(value)is not str or len(value)!=64 or any(c not in '0123456789abcdef'for c in value):
        raise ValueError('B63 pool exact SHA256: '+name)
    return value


def _v2_integer(value,name,low=0,high=2**60):
    if type(value)is not int or not low<=value<=high:
        raise ValueError('B63 pool exact integer: '+name)
    return value


def _v2_relative(value):
    from pathlib import PurePosixPath
    from .portable_job import safe
    if type(value)is not str or not 0<len(value.encode('utf8'))<=4096 or '\\'in value or ':'in value or '\x00'in value:
        raise ValueError('B63 pool strict relative path')
    parts=PurePosixPath(value).parts
    if value.startswith('/')or not parts or any(x in ('','.','..')for x in parts)or '/'.join(parts)!=value:
        raise ValueError('B63 pool normalized relative path')
    # Use the existing shared portable path rules as well: NFC, Windows device
    # names, trailing dot/space, control characters and the bounded 240-character
    # representation cannot acquire filesystem aliases or overlap exemptions.
    safe(value)
    return value


def _v2_node(root,name,*,allow_missing=False):
    import stat
    name=_v2_relative(name);p=root
    for part in name.split('/'):
        p=p/part
        try:info=p.lstat()
        except FileNotFoundError:
            if allow_missing:continue
            raise ValueError('B63 pool owned path missing')from None
        if stat.S_ISLNK(info.st_mode)or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('B63 pool link/reparse forbidden')
        if info.st_dev!=root.stat().st_dev:raise ValueError('B63 pool one filesystem device only')
    return p


def _v2_owner(value):
    if type(value)is not dict or set(value)!={'owner','role','path','identity','kind'}:
        raise ValueError('B63 pool exact owner fields')
    _v2_hash(value['owner'],'owner');_v2_hash(value['identity'],'owner identity')
    _v2_relative(value['path'])
    if type(value['role'])is not str or value['role']not in ('STORE','INITIAL_PACKAGE','EXPORT','BACKUP'):
        raise ValueError('B63 pool owner role')
    if type(value['kind'])is not str or value['kind']not in ('DIRECTORY','FILE'):
        raise ValueError('B63 pool owner kind')
    return dict(value)


def _v2_overlaps(left,right):
    a=left['path'].casefold();b=right['path'].casefold()
    return a==b or a.startswith(b+'/')or b.startswith(a+'/')


def _v2_file(value,owners):
    if type(value)is not dict or set(value)!={'owner','path','sha256','bytes'}:
        raise ValueError('B63 pool exact inventory fields')
    owner=owners.get(value['owner'])
    if owner is None:raise ValueError('B63 pool foreign inventory owner')
    name=_v2_relative(value['path']);_v2_hash(value['sha256'],'owned file')
    _v2_integer(value['bytes'],'owned logical bytes')
    base=owner['path']
    if not(name==base if owner['kind']=='FILE'else name.startswith(base+'/')):
        raise ValueError('B63 pool file outside declared owner')
    return dict(value)


def _v2_physical_credit(info):
    """Conservative physical credit, never unproved logical sparse allocation.

    POSIX st_blocks is allocated 512-byte blocks; credit no more than logical
    length.  On Windows regular, noncompressed/nonsparse attributes establish
    that logical length is a lower bound on retained allocation.  Unknown
    allocation and sparse/compressed files receive ZERO credit.  Reservations
    remain logical upper bounds and are never returned/deleted here.
    """
    attrs=getattr(info,'st_file_attributes',None)
    if attrs is not None:
        if attrs&(0x200|0x800):return 0
        return info.st_size
    blocks=getattr(info,'st_blocks',None)
    if type(blocks)is int and blocks>=0:return min(info.st_size,blocks*512)
    return 0


def _v2_verify_files(root,entry):
    import hashlib,stat
    owners={x['owner']:x for x in entry['owners']}
    for owner in owners.values():
        p=_v2_node(root,owner['path'],allow_missing=True)
        if p.exists()and (not p.is_dir()if owner['kind']=='DIRECTORY'else not p.is_file()):
            raise ValueError('B63 pool owned path kind drift')
    logical=physical=0;inodes=set();logical_by_role={'RETAINED':0,'BACKUP_EXPORT':0}
    for value in entry['inventory']:
        _v2_file(value,owners)
        p=_v2_node(root,value['path']);before=p.stat()
        if not stat.S_ISREG(before.st_mode)or before.st_nlink!=1:
            raise ValueError('B63 pool regular single-link owned file required')
        inode=(before.st_dev,before.st_ino)
        if inode in inodes:raise ValueError('B63 pool duplicate physical file claim')
        inodes.add(inode)
        if before.st_size!=value['bytes']:raise ValueError('B63 pool inventory size drift')
        content=hashlib.sha256()
        with p.open('rb')as stream:
            while True:
                block=stream.read(2**20)
                if not block:break
                content.update(block)
        after=p.stat()
        if content.hexdigest()!=value['sha256']or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
            raise ValueError('B63 pool inventory hash/current-byte drift')
        logical+=before.st_size;physical+=_v2_physical_credit(before)
        group='RETAINED'if owners[value['owner']]['role']in('STORE','INITIAL_PACKAGE')else'BACKUP_EXPORT'
        logical_by_role[group]+=before.st_size
    if logical>entry['total_reserved_bytes']or physical>logical:
        raise ValueError('B63 pool materialization exceeds declared reservation')
    if logical_by_role['RETAINED']>entry['retained_store_and_initial_bytes']or logical_by_role['BACKUP_EXPORT']>entry['backup_and_export_reserve_bytes']:
        raise ValueError('B63 pool materialized role exceeds its distinct reservation')
    return dict(logical_materialized_bytes=logical,credited_physical_bytes=physical,
                owned_files=len(entry['inventory']),logical_by_role=logical_by_role)


def _v2_parse(raw):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('B63 pool duplicate key')
            out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=pairs,
        parse_constant=lambda x:(_ for _ in ()).throw(ValueError('B63 pool nonfinite DATA')))


def _v2_entry(key,policy,owners,inventory):
    from . import lifetime_policy
    policy_types=tuple(getattr(lifetime_policy,name)for name in ('LifetimeCampaignPolicy','LifetimeCampaignPolicyV2')if hasattr(lifetime_policy,name))
    if type(policy)not in policy_types:raise TypeError('B63 pool exact lifetime policy')
    _v2_hash(key,'reservation');policy.__post_init__()
    if type(owners)not in(list,tuple)or not 1<=len(owners)<=MAX_V2_OWNERS:
        raise ValueError('B63 pool bounded explicit ownership required')
    owners=sorted((_v2_owner(x)for x in owners),key=lambda x:x['owner'])
    index={x['owner']:x for x in owners}
    if len(index)!=len(owners):raise ValueError('B63 pool duplicate owner')
    counts={role:sum(x['role']==role for x in owners)for role in ('STORE','INITIAL_PACKAGE','EXPORT','BACKUP')}
    if counts['STORE']!=1 or counts['INITIAL_PACKAGE']>1 or counts['EXPORT']+counts['BACKUP']>policy.backup_copies:
        raise ValueError('B63 pool full prospective owner/copy population')
    if type(inventory)not in(list,tuple)or len(inventory)>MAX_V2_FILES:
        raise ValueError('B63 pool inventory population')
    inventory=sorted((_v2_file(x,index)for x in inventory),key=lambda x:x['path'])
    if len({x['path'].casefold()for x in inventory})!=len(inventory):
        raise ValueError('B63 pool duplicate inventory path')
    return dict(policy_identity=policy.identity,
        retained_store_and_initial_bytes=policy.maximum_reserved_job_output_bytes,
        backup_and_export_reserve_bytes=policy.maximum_reserved_job_output_bytes*policy.backup_copies,
        total_reserved_bytes=policy.pool_commitment_bytes,owners=owners,inventory=inventory)


def _v2_admit_entry(value):
    expected={'policy_identity','retained_store_and_initial_bytes','backup_and_export_reserve_bytes','total_reserved_bytes','owners','inventory'}
    if type(value)is not dict or set(value)!=expected:raise ValueError('B63 pool exact reservation fields')
    _v2_hash(value['policy_identity'],'policy')
    for key in ('retained_store_and_initial_bytes','backup_and_export_reserve_bytes','total_reserved_bytes'):
        _v2_integer(value[key],key)
    if value['total_reserved_bytes']!=value['retained_store_and_initial_bytes']+value['backup_and_export_reserve_bytes']:
        raise ValueError('B63 pool exact complete reservation sum')
    if type(value['owners'])is not list or not 1<=len(value['owners'])<=MAX_V2_OWNERS:
        raise ValueError('B63 pool saved owner population')
    index={}
    for owner in value['owners']:
        _v2_owner(owner)
        if owner['owner']in index:raise ValueError('B63 pool duplicate saved owner')
        index[owner['owner']]=owner
    retained=value['retained_store_and_initial_bytes'];backup=value['backup_and_export_reserve_bytes']
    counts={role:sum(x['role']==role for x in value['owners'])for role in ('STORE','INITIAL_PACKAGE','EXPORT','BACKUP')}
    if retained<=0 or backup%retained or counts['STORE']!=1 or counts['INITIAL_PACKAGE']>1 or counts['EXPORT']+counts['BACKUP']>backup//retained:
        raise ValueError('B63 pool saved owner/copy population')
    if type(value['inventory'])is not list or len(value['inventory'])>MAX_V2_FILES:
        raise ValueError('B63 pool saved inventory population')
    names=set()
    for item in value['inventory']:
        _v2_file(item,index)
        if item['path'].casefold()in names:raise ValueError('B63 pool duplicate saved file')
        names.add(item['path'].casefold())
    return value


def reserve_v2(directory,key,policy,*,owners,inventory=(),pool_bytes=None,windows=False):
    """Reserve all prospective stores/backups once; credit only bound own files.

    The caller supplies its exact current owned inventory, not a recursive
    directory measurement.  Unlisted/foreign files are preserved and supply
    ZERO credit.  Same-device mirrors never add capacity.  Existing V1 pools
    lack ownership authority and are not silently imported or rewritten.
    """
    import stat
    root=Path(directory).absolute()
    for p in (root,*root.parents):
        if p.exists()or p.is_symlink():
            info=p.lstat()
            if stat.S_ISLNK(info.st_mode)or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('B63 pool root link/reparse forbidden')
    root.mkdir(parents=True,exist_ok=True)
    fresh=_v2_entry(key,policy,owners,inventory)
    lock=_v2_node(root,'LIFETIME-POOL-V2.lock',allow_missing=True)
    if lock.exists()and (not lock.is_file()or lock.stat().st_nlink!=1):
        raise ValueError('B63 pool regular single-link lease required')
    with lease(root/'LIFETIME-POOL-V2.lock',windows=windows):
        if (root/'LIFETIME-POOL.json').exists()or (root/'LIFETIME-POOL.json').is_symlink():
            raise ValueError('B63 pool cannot silently import V1 unowned commitments')
        path=root/POOL_V2
        if path.exists()or path.is_symlink():
            _v2_node(root,POOL_V2)
            if not path.is_file()or path.stat().st_nlink!=1 or path.stat().st_size>MAX_POOL_V2_BYTES:
                raise ValueError('B63 pool bounded metadata')
            value=_v2_parse(path.read_bytes())
            if type(value)is not dict or set(value)!={'format','device','pool_bytes','reservations'}or value['format']!=FORMAT_V2 or type(value['device'])is not int or value['device']!=root.stat().st_dev:
                raise ValueError('B63 pool exact device/format binding')
            _v2_integer(value['pool_bytes'],'capacity',1)
            if pool_bytes is not None and (type(pool_bytes)is not int or pool_bytes!=value['pool_bytes']):
                raise ValueError('B63 pool capacity drift')
        else:
            free=shutil.disk_usage(root).free
            cap=max(0,free-2**30)if pool_bytes is None else pool_bytes
            _v2_integer(cap,'capacity',1)
            if cap>free:raise ValueError('B63 initial pool capacity exceeds one-device free space')
            value=dict(format=FORMAT_V2,device=root.stat().st_dev,pool_bytes=cap,reservations={})
        if type(value['reservations'])is not dict or len(value['reservations'])>MAX_V2_RESERVATIONS:
            raise ValueError('B63 pool reservation population')
        for saved_key,entry in value['reservations'].items():
            _v2_hash(saved_key,'saved reservation');_v2_admit_entry(entry)
        old=value['reservations'].get(key)
        if old is not None:
            if {k:v for k,v in old.items()if k!='inventory'}!={k:v for k,v in fresh.items()if k!='inventory'}:
                raise ValueError('B63 pool policy/ownership drift')
            current={x['path']:x for x in fresh['inventory']}
            if any(x['path']not in current or current[x['path']]['owner']!=x['owner']for x in old['inventory']):
                raise ValueError('B63 pool no dropped ownership or quota refund')
        proposed=dict(value['reservations']);proposed[key]=fresh
        if len(proposed)>MAX_V2_RESERVATIONS:raise ValueError('B63 pool reservation population')
        claims=[]
        for entry in proposed.values():
            claims.extend(entry['owners'])
        for i,owner in enumerate(claims):
            if any(_v2_overlaps(owner,other)or owner['owner']==other['owner']for other in claims[:i]):
                raise ValueError('B63 pool overlapping/duplicate physical ownership claims')
        total=sum(x['total_reserved_bytes']for x in proposed.values())
        if total>value['pool_bytes']:raise ValueError('B63 all-design prospective pool exhausted')
        measurements={k:_v2_verify_files(root,x)for k,x in proposed.items()}
        credits={k:min(proposed[k]['total_reserved_bytes'],x['credited_physical_bytes'])for k,x in measurements.items()}
        outstanding=sum(proposed[k]['total_reserved_bytes']-credits[k]for k in proposed)
        free=shutil.disk_usage(root).free
        if free<outstanding+POOL_SAFETY_BYTES:
            raise ValueError('B63 external/unattributed disk consumption exhausted reserved pool')
        prospective=dict(value,reservations=proposed);raw=encoded(prospective)
        if len(raw)>MAX_POOL_V2_BYTES:raise ValueError('B63 pool metadata byte reservation')
        with tempfile.NamedTemporaryFile('wb',dir=root,prefix='.b63-pool-',delete=False)as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno());pending=Path(stream.name)
        os.replace(pending,path)
        if os.name!='nt':
            fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        return dict(pool=prospective,owned=measurements,free_bytes=free,
            total_reserved_bytes=total,outstanding_reserved_bytes=outstanding,
            credited_physical_bytes=sum(credits.values()),
            unregistered_files_credit_bytes=0,capacity_devices=1,
            allocation_semantics='LOGICAL_UPPER_RESERVATION_CONSERVATIVE_VERIFIED_PHYSICAL_CREDIT',
            retention='ALL_JOBS_NO_AUTOMATIC_REFUND_OR_DELETION')
