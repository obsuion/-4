"""B53 bounded append-only chunks, prefix authority and constant-size status heads.

No physics imports. Every raw scientific record is retained; chunk rotation does
not downsample events. Working memory holds one hash/frontier, not the history.
Append-only heads never replace a Windows reader-held file. Saved-data readers
validate exact prefixes and expose incomplete tails, not invented raw history.
"""
from .lifetime_io_accounting import fsync as _io_fsync
from dataclasses import dataclass,asdict
from hashlib import sha256
from pathlib import Path
import json,math,os,re,struct
from .lifecycle_contract import METHOD55

METHOD='B53_CHUNKED_SCIENTIFIC_STREAMS_V1'
FRONTIER='B53_EXACT_STREAM_PREFIX_V1'
INDEX='B53_IMMUTABLE_CHUNK_INDEX_V1'
HEAD=struct.Struct('>8sQQQQ32s')
MAGIC=b'B53STAT1'
ZERO='0'*64


def _int(v,n,lo=0,hi=2**48):
    if type(v) is not int or not lo<=v<=hi:raise ValueError('bounded exact stream integer: '+n)
    return v
def _digest(v):
    if type(v) is not str or not re.fullmatch('[0-9a-f]{64}',v):raise ValueError('stream SHA256')
    return v
def _fields(v,names):
    if type(v) is not dict or set(v)!=set(names):raise ValueError('exact stream fields')
    return v
def _raw(v):return json.dumps(v,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def _parse(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('duplicate stream JSON key')
            result[k]=v
        return result
    return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
def _folder(path):
    path=Path(path).absolute()
    if any(p.is_symlink() or p.exists() and getattr(p,'is_junction',lambda:False)() for p in (path,*path.parents)):raise ValueError('stream links/junctions forbidden')
    if any((p/'.git').exists() for p in (path,*path.parents)):raise ValueError('stream must remain outside repository')
    return path
def _chunk(n):return 'chunk-'+str(_int(n,'chunk',1,99999999)).zfill(8)+'.jsonl'


def _register_producer_file(path):
    """Prospective physical FILE/DIR charge; historical stores are a no-op."""
    from .lifetime_physical_storage import register_producer_path
    register_producer_path(path)


@dataclass(frozen=True,slots=True)
class LifecycleStreamPolicy:
    method:str=METHOD
    chunk_bytes:int=262144
    max_record_bytes:int=65536
    events_total_bytes:int=128*2**20
    details_total_bytes:int=32*2**20
    progress_total_bytes:int=16*2**20
    status_total_bytes:int=16*2**20
    max_index_bytes:int=2*2**20
    working_checkpoint_every_events:int=1024
    named_checkpoint_every_seconds:int=86400
    publication_minimum_wall_seconds:float=1.0
    def __post_init__(self):
        if type(self.method) is not str or self.method!=METHOD:raise ValueError('stream policy method')
        for name,lo,hi in (('chunk_bytes',4096,2**20),('max_record_bytes',1024,2**20),
            ('events_total_bytes',2**20,512*2**20),('details_total_bytes',65536,128*2**20),
            ('progress_total_bytes',65536,64*2**20),('status_total_bytes',65536,64*2**20),
            ('max_index_bytes',4096,16*2**20),('working_checkpoint_every_events',64,65536),
            ('named_checkpoint_every_seconds',60,2592000)):_int(getattr(self,name),name,lo,hi)
        if self.max_record_bytes>self.chunk_bytes:raise ValueError('stream record must fit one chunk')
        if type(self.publication_minimum_wall_seconds) is not float or not math.isfinite(self.publication_minimum_wall_seconds) or not .1<=self.publication_minimum_wall_seconds<=60:raise ValueError('finite stream publication cadence')
    @property
    def identity(self):return sha256(_raw(asdict(self))).hexdigest()
    @property
    def declared_stream_bytes(self):
        # Four streams/indexes, status heads, checkpoint metadata catalog and
        # parent paid-publication journal. Native checkpoint occupancy/encoding,
        # month rows and terminal reserve remain separate.
        return sum((self.events_total_bytes,self.details_total_bytes,self.progress_total_bytes,self.status_total_bytes))+7*self.max_index_bytes


class ChunkedStreamWriter:
    """Single writer. charge(bytes) reserves global publication BEFORE writes.

    maximum_bytes includes raw records and sealed index bytes. Reservations and
    attempted records do not rewind on failure. A checkpoint snapshot pins the
    existing current chunk PREFIX; later appends do not alter that prefix.
    """
    def __init__(self,directory,policy,maximum_bytes,*,start_record=0,charge=None):
        if type(policy) is not LifecycleStreamPolicy:raise TypeError('exact stream policy')
        policy.__post_init__();_int(maximum_bytes,'stream byte allowance',1024,2**30);_int(start_record,'start record')
        self.directory=_folder(directory)
        if self.directory.exists():raise ValueError('new immutable stream directory required')
        _register_producer_file(self.directory/'index.jsonl')
        self.directory.mkdir(parents=True);self.policy=policy;self.maximum_bytes=maximum_bytes;self.start_record=start_record;self.charge=charge
        self.index=(self.directory/'index.jsonl').open('xb');self.index_hash=sha256();self.index_bytes=0;self.index_chain=ZERO
        self.file=None;self.chunk_hash=None;self.chunk_bytes=0;self.chunk_records=0;self.sealed_chunks=0;self.sealed_bytes=0;self.records=0
        self.closed=False;self.failed=False;self.final=None
        self.work=dict(record_attempts=0,records_completed=0,encoded_bytes_reserved=0,bytes_published=0,index_records=0)
    def _reserve(self,n):
        self.work['encoded_bytes_reserved']+=n
        if self.charge is not None:self.charge(n)
    def _index_entry(self):
        first=self.start_record+self.records-self.chunk_records+1
        e=dict(format=INDEX,chunk=self.sealed_chunks+1,file=_chunk(self.sealed_chunks+1),bytes=self.chunk_bytes,records=self.chunk_records,
            first_sequence=first,last_sequence=self.start_record+self.records,sha256=self.chunk_hash.hexdigest(),previous_index_chain=self.index_chain)
        e['index_chain']=sha256((self.index_chain+_raw(e).decode('utf-8')).encode('utf-8')).hexdigest()
        return e
    def _seal(self):
        if self.file is None:return
        e=self._index_entry();raw=_raw(e)+b'\n'
        if len(raw)>4096 or self.index_bytes+len(raw)>self.policy.max_index_bytes or self.work['bytes_published']+len(raw)>self.maximum_bytes:raise ValueError('prospective sealed index quota')
        self._reserve(len(raw));self.file.flush();_io_fsync(self.file.fileno());self.file.close();self.file=None
        self.index.write(raw);self.index.flush();_io_fsync(self.index.fileno())
        self.index_hash.update(raw);self.index_bytes+=len(raw);self.index_chain=e['index_chain'];self.sealed_chunks+=1;self.sealed_bytes+=self.chunk_bytes
        self.work['bytes_published']+=len(raw);self.work['index_records']+=1;self.chunk_bytes=self.chunk_records=0
    def append(self,payload):
        if self.closed or self.failed:raise ValueError('closed/failed stream cannot append')
        self.work['record_attempts']+=1
        try:
            raw=_raw(payload)+b'\n'
            if len(raw)>self.policy.max_record_bytes:raise ValueError('stream record prospective byte cap')
            # Reserve future seal metadata before accepting a record. Its exact
            # entry is smaller than4096 bytes; final seal never borrows terminal
            # capacity that was already spent on raw records.
            if self.work['bytes_published']+len(raw)+4096>self.maximum_bytes:raise ValueError('stream prospective total byte cap')
            if self.file is not None and self.chunk_bytes+len(raw)>self.policy.chunk_bytes:self._seal()
            if self.file is None:
                _register_producer_file(self.directory/_chunk(self.sealed_chunks+1))
                self.file=(self.directory/_chunk(self.sealed_chunks+1)).open('xb');self.chunk_hash=sha256();self.chunk_bytes=self.chunk_records=0
            self._reserve(len(raw));offset=self.chunk_bytes;self.file.write(raw);self.file.flush()
            self.chunk_hash.update(raw);self.chunk_bytes+=len(raw);self.chunk_records+=1;self.records+=1
            self.work['records_completed']+=1;self.work['bytes_published']+=len(raw)
            return dict(file=_chunk(self.sealed_chunks+1),chunk=self.sealed_chunks+1,offset=offset,bytes=len(raw),sha256=sha256(raw).hexdigest(),sequence=self.start_record+self.records)
        except BaseException:self.failed=True;raise
    def snapshot(self):
        if self.file is not None:self.file.flush();_io_fsync(self.file.fileno())
        self.index.flush();_io_fsync(self.index.fileno())
        current=None if self.file is None else dict(chunk=self.sealed_chunks+1,file=_chunk(self.sealed_chunks+1),bytes=self.chunk_bytes,records=self.chunk_records,
            first_sequence=self.start_record+self.records-self.chunk_records+1,last_sequence=self.start_record+self.records,sha256=self.chunk_hash.hexdigest())
        return dict(format=FRONTIER,policy=asdict(self.policy),policy_identity=self.policy.identity,maximum_bytes=self.maximum_bytes,
            start_record=self.start_record,end_record=self.start_record+self.records,records=self.records,sealed_chunks=self.sealed_chunks,sealed_bytes=self.sealed_bytes,
            index_bytes=self.index_bytes,index_sha256=self.index_hash.hexdigest(),index_chain=self.index_chain,current=current,writer_failed=self.failed,work=dict(self.work))
    def finish(self):
        if self.final is not None:return self.final
        if self.closed:raise ValueError('stream closed without manifest')
        try:
            self._seal();self.final=self.snapshot();raw=_raw(self.final)
            self._reserve(len(raw))
            _register_producer_file(self.directory/'manifest.json')
            with (self.directory/'manifest.json').open('xb') as stream:stream.write(raw);stream.flush();_io_fsync(stream.fileno())
            return self.final
        except BaseException:self.failed=True;raise
        finally:self.close()
    def close(self):
        if self.file is not None:self.file.close();self.file=None
        if not self.index.closed:self.index.close()
        self.closed=True


def _admit_inventory_counts(value, policy):
    """Every accepted index entry contains two 64-character chain digests.

    Hence 128 bytes/entry is a conservative LOWER bound, not an estimated
    average. Each sealed chunk is nonempty and contains at least one record.
    This admission applies to pinned prefixes too; it allocates no population.
    """
    for name in ('sealed_chunks','index_bytes','sealed_bytes','records','maximum_bytes'):
        _int(value[name],name)
    _int(value['maximum_bytes'],'maximum_bytes',1024,2**30)
    n=value['sealed_chunks']
    if (value['index_bytes']>policy.max_index_bytes or
            n>value['index_bytes']//128 or n>value['records'] or n>value['sealed_bytes'] or
            value['sealed_bytes']+value['index_bytes']>value['maximum_bytes'] or
            (n==0 and (value['index_bytes']!=0 or value['sealed_bytes']!=0))):
        raise ValueError('stream source/index/output population bound')


def _whole_inventory(directory, frontier):
    """O(1) auxiliary memory; no range/set built from an untrusted count.

    Canonical filename -> integer is injective. Filesystem names are unique;
    a complete admitted population of in-range canonical names proves exactly
    one file per ordinal without storing or enumerating an expected range.
    """
    from .lifecycle_compact import FRONTIER as COMPACT_FORMAT,chunk as compact_chunk
    if frontier['current'] is not None:raise ValueError('final stream cannot retain an unsealed current chunk')
    n=frontier['sealed_chunks'];seen=0
    compact=frontier['format']==COMPACT_FORMAT
    pattern=r'chunk-([0-9]{8})\.zframes' if compact else r'chunk-([0-9]{8})\.jsonl'
    for path in directory.iterdir():
        if path.name in ('manifest.json','index.jsonl'):continue
        seen+=1
        if seen>n:raise ValueError('unexpected final stream files/offsets')
        match=re.fullmatch(pattern,path.name)
        if match is None:raise ValueError('unexpected final stream files/offsets')
        ordinal=int(match.group(1))
        if not 1<=ordinal<=n or path.name!=(compact_chunk(ordinal)if compact else _chunk(ordinal)):
            raise ValueError('unexpected final stream files/offsets')
        _folder(path)
        if not path.is_file():raise ValueError('unexpected final stream file type')
    if seen!=n:raise ValueError('unexpected final stream files/offsets')


def admit_frontier(value,policy=None):
    from .lifecycle_compact import FRONTIER as COMPACT,admit_frontier as admit_compact
    if type(value) is dict and value.get('format')==COMPACT:return admit_compact(value,policy)
    _fields(value,('format','policy','policy_identity','maximum_bytes','start_record','end_record','records','sealed_chunks','sealed_bytes','index_bytes','index_sha256','index_chain','current','writer_failed','work'))
    p=LifecycleStreamPolicy(**value['policy'])
    if value['format']!=FRONTIER or value['policy_identity']!=p.identity or policy is not None and p!=policy:raise ValueError('stream frontier policy binding')
    for n in ('maximum_bytes','start_record','end_record','records','sealed_chunks','sealed_bytes','index_bytes'):_int(value[n],n)
    for n in ('index_sha256','index_chain'):_digest(value[n])
    if type(value['writer_failed']) is not bool or value['end_record']!=value['start_record']+value['records'] or value['index_bytes']>p.max_index_bytes:raise ValueError('stream frontier balance')
    _fields(value['work'],('record_attempts','records_completed','encoded_bytes_reserved','bytes_published','index_records'))
    for n,v in value['work'].items():_int(v,n)
    if value['work']['records_completed']!=value['records'] or value['work']['record_attempts']<value['records'] or value['work']['index_records']!=value['sealed_chunks']:raise ValueError('stream paid record balance')
    if value['work']['bytes_published']>value['maximum_bytes'] or value['work']['encoded_bytes_reserved']<value['work']['bytes_published']:raise ValueError('stream paid byte balance')
    _admit_inventory_counts(value,p)
    if value['current'] is not None:
        c=_fields(value['current'],('chunk','file','bytes','records','first_sequence','last_sequence','sha256'))
        for n in ('chunk','bytes','records','first_sequence','last_sequence'):_int(c[n],n,1)
        if c['file']!=_chunk(c['chunk']) or c['chunk']!=value['sealed_chunks']+1 or c['last_sequence']!=value['end_record'] or c['last_sequence']-c['first_sequence']+1!=c['records'] or c['bytes']>p.chunk_bytes:raise ValueError('stream current prefix balance')
        _digest(c['sha256'])
    return p


def _read_chunk(directory,entry,p,*,prefix=False):
    path=directory/entry['file'];_folder(path)
    if path.stat().st_size<entry['bytes'] or not prefix and path.stat().st_size!=entry['bytes']:raise ValueError('stream chunk raw size')
    if not 0<entry['bytes']<=p.chunk_bytes:raise ValueError('stream chunk byte bound')
    digest=sha256();remaining=entry['bytes'];count=0
    with path.open('rb') as stream:
        while remaining:
            raw=stream.readline(min(remaining,p.max_record_bytes)+1)
            if not raw or not raw.endswith(b'\n') or len(raw)>remaining or len(raw)>p.max_record_bytes:raise ValueError('incomplete/oversize stream record')
            remaining-=len(raw);digest.update(raw);count+=1;payload=_parse(raw[:-1])
            if _raw(payload)+b'\n'!=raw:raise ValueError('noncanonical stream record')
            yield payload
    if count!=entry['records'] or digest.hexdigest()!=entry['sha256']:raise ValueError('stream chunk record/hash binding')


def iter_stream_records(directory,frontier=None,policy=None):
    """One-pass bounded saved-data reader. Consume fully to verify all hashes."""
    directory=_folder(directory)
    if frontier is None:
        if (directory/'manifest.json').stat().st_size>65536:raise ValueError('stream manifest byte cap')
        raw=(directory/'manifest.json').read_bytes()
        if len(raw)>65536:raise ValueError('stream manifest byte cap')
        frontier=_parse(raw)
        # Strict type/schema and source/index/output bounds precede all
        # filesystem population work, including compact dispatch.
        admit_frontier(frontier,policy)
        if (directory/'index.jsonl').stat().st_size!=frontier['index_bytes']:raise ValueError('stream final index trailing bytes')
        _whole_inventory(directory,frontier)
    from .lifecycle_compact import FRONTIER as COMPACT,iter_records
    if type(frontier) is dict and frontier.get('format')==COMPACT:
        yield from iter_records(directory,frontier,policy);return
    p=admit_frontier(frontier,policy);index=directory/'index.jsonl'
    if index.stat().st_size<frontier['index_bytes']:raise ValueError('stream index prefix size')
    remaining=frontier['index_bytes'];index_hash=sha256();chain=ZERO;ordinal=0;count=0;payload_bytes=0;next_sequence=frontier['start_record']+1
    with index.open('rb') as stream:
        while remaining:
            raw=stream.readline(min(remaining,4096)+1)
            if not raw.endswith(b'\n') or len(raw)>remaining or len(raw)>4096:raise ValueError('stream index incomplete tail')
            remaining-=len(raw);index_hash.update(raw);e=_parse(raw[:-1])
            _fields(e,('format','chunk','file','bytes','records','first_sequence','last_sequence','sha256','previous_index_chain','index_chain'))
            for n in ('chunk','bytes','records','first_sequence','last_sequence'):_int(e[n],n,1)
            _digest(e['sha256']);_digest(e['index_chain']);ordinal+=1
            content={n:v for n,v in e.items() if n!='index_chain'}
            if e['format']!=INDEX or e['chunk']!=ordinal or e['file']!=_chunk(ordinal) or e['previous_index_chain']!=chain or e['first_sequence']!=next_sequence or e['last_sequence']-e['first_sequence']+1!=e['records'] or sha256((chain+_raw(content).decode()).encode()).hexdigest()!=e['index_chain'] or _raw(e)+b'\n'!=raw:raise ValueError('stream index hash/sequence')
            yield from _read_chunk(directory,e,p);chain=e['index_chain'];next_sequence=e['last_sequence']+1;count+=e['records'];payload_bytes+=e['bytes']
    if ordinal!=frontier['sealed_chunks'] or payload_bytes!=frontier['sealed_bytes'] or index_hash.hexdigest()!=frontier['index_sha256'] or chain!=frontier['index_chain']:raise ValueError('stream index frontier binding')
    if frontier['current'] is not None:
        c=frontier['current']
        if c['first_sequence']!=next_sequence:raise ValueError('current stream sequence gap')
        yield from _read_chunk(directory,c,p,prefix=True);count+=c['records'];payload_bytes+=c['bytes']
    if count!=frontier['records'] or payload_bytes+frontier['index_bytes']!=frontier['work']['bytes_published']:raise ValueError('stream record/byte conservation')


def verify_stream(directory,frontier=None,policy=None):
    count=sum(1 for _ in iter_stream_records(directory,frontier,policy))
    return dict(status='PASS',records=count,scope='RETAINED_RAW_RECORDS_AND_EXACT_BOUND_FRONTIER_NOT_PHYSICAL_REACHABILITY')


class IncrementalStreamReader:
    """Live complete records only; no index rescan and explicit bounded tail.

    Final sealed/index hashes must ALSO pass verify_stream after owned cleanup.
    Live records alone never imply final artifact integrity or full coverage.
    """
    def __new__(cls,directory,policy,maximum_bytes,*,profile=None,read_charge=None):
        if profile is not None:
            from .lifecycle_compact import IncrementalCompactReader
            return IncrementalCompactReader(directory,policy,maximum_bytes,profile,read_charge)
        return super().__new__(cls)
    def __init__(self,directory,policy,maximum_bytes,*,profile=None,read_charge=None):
        self.directory=_folder(directory);self.policy=policy;self.maximum_bytes=maximum_bytes
        self.chunk=1;self.offset=0;self.bytes=0;self.tail=b'';self.records=0
    def read(self):
        result=[]
        read_chunks=0
        while True:
            path=self.directory/_chunk(self.chunk)
            if not path.exists():break
            if path.stat().st_size>self.policy.chunk_bytes:raise ValueError('live chunk exceeds policy')
            with path.open('rb') as stream:stream.seek(self.offset);raw=stream.read(self.policy.chunk_bytes-self.offset+1)
            self.offset+=len(raw);self.bytes+=len(raw)
            read_chunks+=1
            if self.bytes>self.maximum_bytes:raise ValueError('live stream byte cap')
            lines=(self.tail+raw).split(b'\n');self.tail=lines.pop()
            if len(self.tail)>self.policy.max_record_bytes:raise ValueError('live incomplete tail cap')
            for line in lines:
                if not line or len(line)+1>self.policy.max_record_bytes:raise ValueError('live record byte cap')
                payload=_parse(line)
                if _raw(payload)!=line:raise ValueError('live canonical record')
                result.append(payload);self.records+=1
            if not (self.directory/_chunk(self.chunk+1)).exists():break
            if self.tail:raise ValueError('incomplete tail before next chunk')
            self.chunk+=1;self.offset=0
            if read_chunks>=4:break # finite live batch; later calls continue, no history array.
        return result


class StatusStream:
    """One parent writer; immutable raw status chunks plus72-byte append heads."""
    def __new__(cls,directory,policy,*,charge=None,profile=None,codec_charge=None):
        if profile is not None:
            from .lifecycle_compact import CompactStatus
            return CompactStatus(directory,policy,charge=charge,profile=profile,codec_charge=codec_charge)
        return super().__new__(cls)
    def __init__(self,directory,policy,*,charge=None,profile=None,codec_charge=None):
        self.directory=_folder(directory);self.policy=policy;self.charge=charge
        self.writer=ChunkedStreamWriter(self.directory/'records',policy,policy.status_total_bytes,charge=charge)
        _register_producer_file(self.directory/'heads.bin')
        self.head=(self.directory/'heads.bin').open('xb');self.head_bytes=0
    def publish(self,status,*,terminal=False):
        if type(terminal) is not bool:raise TypeError('exact terminal status flag')
        if not terminal and (self.head_bytes+9*HEAD.size>self.policy.max_index_bytes or
                self.writer.work['bytes_published']+len(_raw(status))+1+2*self.policy.max_record_bytes+4096>self.policy.status_total_bytes):
            raise ValueError('prospective status terminal reserve')
        if self.head_bytes+HEAD.size>self.policy.max_index_bytes:raise ValueError('prospective status head cap')
        if self.charge is not None:self.charge(HEAD.size)
        receipt=self.writer.append(status);self.writer.snapshot()
        raw=HEAD.pack(MAGIC,receipt['sequence'],receipt['chunk'],receipt['offset'],receipt['bytes'],bytes.fromhex(receipt['sha256']))
        self.head.write(raw);self.head.flush();_io_fsync(self.head.fileno());self.head_bytes+=len(raw)
        return receipt['sequence']
    def close(self):
        try:
            if not self.writer.closed:self.writer.finish()
        finally:self.head.close()


def read_latest_status(directory,policy,*,profile=None):
    """O(1) last complete head; incomplete tail is explicit, never auto repaired."""
    if profile is not None:
        from .lifecycle_compact import read_status
        return read_status(directory,policy,profile)
    directory=_folder(directory);path=directory/'heads.bin';size=path.stat().st_size
    if size>policy.max_index_bytes or size<HEAD.size:raise ValueError('status head byte bound')
    complete=size//HEAD.size;tail=size%HEAD.size
    with path.open('rb') as stream:stream.seek((complete-1)*HEAD.size);magic,seq,chunk,offset,length,expected=HEAD.unpack(stream.read(HEAD.size))
    if magic!=MAGIC or seq!=complete or not 0<length<=policy.max_record_bytes or offset+length>policy.chunk_bytes:raise ValueError('status exact head')
    target=directory/'records'/_chunk(chunk);_folder(target)
    if target.stat().st_size<offset+length:raise ValueError('status publication incomplete')
    with target.open('rb') as stream:stream.seek(offset);raw=stream.read(length)
    if not raw.endswith(b'\n') or sha256(raw).digest()!=expected:raise ValueError('status publication SHA')
    value=_parse(raw[:-1])
    if _raw(value)+b'\n'!=raw:raise ValueError('status canonical bytes')
    return value,dict(sequence=seq,incomplete_head_tail_bytes=tail,scope='LAST_COMPLETE_STATUS_HEAD_NOT_RECONSTRUCTED_PROCESS_OWNERSHIP')


CATALOG_HEAD=struct.Struct('>Q32s')
CATALOG_LOOKUP=struct.Struct('>Q')


class CheckpointCatalog:
    """Bounded disk index: O(1) SHA lookup and bounded backwards pages.

    A compact job status need retain only recent/selected checkpoint metadata.
    Older monthly metadata remains addressable without loading the whole index.
    Raw retirement is explicit and never deletes its index/tombstone evidence.
    """
    def __init__(self,directory,maximum_bytes,*,charge=None):
        self.directory=_folder(directory);_int(maximum_bytes,'checkpoint index cap',4096,64*2**20)
        if self.directory.exists():raise ValueError('new checkpoint catalog required')
        _register_producer_file(self.directory/'heads.bin')
        self.directory.mkdir(parents=True);self.maximum_bytes=maximum_bytes;self.charge=charge;self.sequence=0;self.published=0;self.reserved=0;self.chain=ZERO
        _register_producer_file(self.directory/'heads.bin')
        self.head=(self.directory/'heads.bin').open('xb');self.closed=False
    def _put(self,path,raw):
        if self.published+len(raw)>self.maximum_bytes:raise ValueError('checkpoint index prospective bytes')
        self.reserved+=len(raw)
        if self.charge is not None:self.charge(len(raw))
        _register_producer_file(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw);stream.flush();_io_fsync(stream.fileno())
        self.published+=len(raw)
    def append(self,checkpoint):
        if self.closed:raise ValueError('closed checkpoint catalog')
        _digest(checkpoint['sha256'])
        if not re.fullmatch(r'checkpoint-[0-9]{8}\.json',checkpoint['file']):raise ValueError('checkpoint catalog file')
        n=self.sequence+1;row=dict(format='B53_CHECKPOINT_CATALOG_ENTRY_V1',sequence=n,checkpoint=checkpoint,previous_chain=self.chain)
        row['chain']=sha256((self.chain+_raw(row).decode()).encode()).hexdigest();raw=_raw(row)
        if len(raw)>65536:raise ValueError('checkpoint metadata cap')
        # Admit all three publications together before writing any of them.
        needed=len(raw)+CATALOG_HEAD.size+CATALOG_LOOKUP.size
        if self.published+needed>self.maximum_bytes:raise ValueError('checkpoint catalog atomic prospective admission')
        self._put(self.directory/('entry-'+str(n).zfill(8)+'.json'),raw)
        self.reserved+=CATALOG_HEAD.size+CATALOG_LOOKUP.size
        if self.charge is not None:self.charge(CATALOG_HEAD.size+CATALOG_LOOKUP.size)
        folder=self.directory/'by-sha'/checkpoint['sha256']
        _register_producer_file(folder/'heads.bin')
        folder.mkdir(parents=True,exist_ok=True)
        with (folder/'heads.bin').open('ab') as stream:stream.write(CATALOG_LOOKUP.pack(n));stream.flush();_io_fsync(stream.fileno())
        self.head.write(CATALOG_HEAD.pack(n,sha256(raw).digest()));self.head.flush();_io_fsync(self.head.fileno())
        self.published+=CATALOG_HEAD.size+CATALOG_LOOKUP.size;self.sequence=n;self.chain=row['chain']
        return n
    def retire(self,sequence,reason):
        _int(sequence,'checkpoint retired sequence',1,self.sequence)
        row=_catalog_entry(self.directory,sequence)
        legacy=type(reason)is str and reason in ('DECLARED_LAST_TWO_WORKING_RETENTION','DECLARED_LAST_TWO_AUDIT_PREDECESSORS')
        if not legacy:
            checkpoint=row['checkpoint'];bindings=checkpoint.get('bindings')
            if (type(reason)is not str or reason!='DECLARED_LAST_TWO_B55_NAMED_PREDECESSORS'
                    or type(bindings)is not dict or type(bindings.get('method'))is not str or bindings['method']!=METHOD55
                    or type(checkpoint.get('kind'))is not str
                    or checkpoint['kind']not in('AUDIT_NAMED','SERVICE_SAFE','SERVICE_POWER_OFF','SERVICE_RECOVERY')):
                raise ValueError('checkpoint retirement scope')
        value=dict(format='B53_DECLARED_RAW_CHECKPOINT_RETIREMENT_V1',sequence=sequence,checkpoint_sha256=row['checkpoint']['sha256'],
            entry_sha256=sha256(_raw(row)).hexdigest(),reason=reason,raw_revalidation='NOT_AVAILABLE_AFTER_DECLARED_RETIREMENT')
        self._put(self.directory/'retired'/('entry-'+str(sequence).zfill(8)+'.json'),_raw(value))
        return value
    def close(self):
        if not self.closed:self.head.close();self.closed=True


def _catalog_count(directory):
    path=directory/'heads.bin';size=path.stat().st_size
    if size%CATALOG_HEAD.size:raise ValueError('checkpoint catalog incomplete head tail')
    if size==0:return 0
    with path.open('rb') as stream:stream.seek(size-CATALOG_HEAD.size);seq,digest=CATALOG_HEAD.unpack(stream.read(CATALOG_HEAD.size))
    if seq!=size//CATALOG_HEAD.size:raise ValueError('checkpoint catalog head sequence')
    if sha256((directory/('entry-'+str(seq).zfill(8)+'.json')).read_bytes()).digest()!=digest:raise ValueError('checkpoint catalog last entry hash')
    return seq


def _catalog_entry(directory,sequence):
    _int(sequence,'checkpoint index sequence',1,99999999)
    raw=(directory/('entry-'+str(sequence).zfill(8)+'.json')).read_bytes()
    if len(raw)>65536:raise ValueError('checkpoint metadata byte cap')
    row=_parse(raw);_fields(row,('format','sequence','checkpoint','previous_chain','chain'))
    _digest(row['previous_chain']);_digest(row['chain']);content={k:v for k,v in row.items() if k!='chain'}
    if row['format']!='B53_CHECKPOINT_CATALOG_ENTRY_V1' or row['sequence']!=sequence or _raw(row)!=raw or sha256((row['previous_chain']+_raw(content).decode()).encode()).hexdigest()!=row['chain']:raise ValueError('checkpoint metadata canonical/chain')
    return row


def checkpoint_page(directory,*,before=None,limit=16):
    directory=_folder(directory);_int(limit,'checkpoint page count',1,32);count=_catalog_count(directory)
    if before is None:before=count+1
    _int(before,'checkpoint page before',1,count+1)
    result=[]
    for seq in range(before-1,max(0,before-1-limit),-1):
        row=_catalog_entry(directory,seq);retired=directory/'retired'/('entry-'+str(seq).zfill(8)+'.json')
        result.append(dict(sequence=seq,checkpoint=row['checkpoint'],raw_available=not retired.exists()))
    return dict(entries=result,next_before=None if not result or result[-1]['sequence']==1 else result[-1]['sequence'],total_publications=count)


def lookup_checkpoint(directory,checkpoint_sha256):
    directory=_folder(directory);_digest(checkpoint_sha256);count=_catalog_count(directory)
    path=directory/'by-sha'/checkpoint_sha256/'heads.bin';size=path.stat().st_size
    if not size or size%CATALOG_LOOKUP.size:raise ValueError('checkpoint SHA lookup incomplete head')
    with path.open('rb') as stream:stream.seek(size-CATALOG_LOOKUP.size);seq=CATALOG_LOOKUP.unpack(stream.read(CATALOG_LOOKUP.size))[0]
    if not 1<=seq<=count:raise ValueError('checkpoint SHA lookup past committed catalog')
    row=_catalog_entry(directory,seq)
    if row['checkpoint']['sha256']!=checkpoint_sha256:raise ValueError('checkpoint SHA lookup binding')
    retired=directory/'retired'/('entry-'+str(seq).zfill(8)+'.json')
    return row['checkpoint'],dict(sequence=seq,raw_available=not retired.exists(),raw_revalidation='NOT_AVAILABLE_DECLARED_RETIREMENT' if retired.exists() else 'REQUIRED_BEFORE_CONTINUATION')


def iter_checkpoint_catalog(directory):
    """Full saved-data chain verification; no array of historical metadata."""
    directory=_folder(directory);count=_catalog_count(directory);chain=ZERO
    with (directory/'heads.bin').open('rb') as heads:
        for seq in range(1,count+1):
            raw=heads.read(CATALOG_HEAD.size);n,expected=CATALOG_HEAD.unpack(raw);row=_catalog_entry(directory,seq)
            if n!=seq or expected!=sha256(_raw(row)).digest() or row['previous_chain']!=chain:raise ValueError('checkpoint catalog global chain/head')
            chain=row['chain'];yield row
