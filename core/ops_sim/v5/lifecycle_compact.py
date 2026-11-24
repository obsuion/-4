"""B57 bounded lossless transport. This module has no simulator imports.

Independent zlib members, not a growing compression dictionary. A frontier pins
complete frames only. Decoded canonical records retain the original science
chain; encoded transport hashes have a different, explicit scope.
"""
from .lifetime_io_accounting import fsync as _io_fsync
from .lifecycle_stream import _register_producer_file
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import json, os, re, struct, zlib

METHOD = 'B57_LOSSLESS_ZLIB_BLOCKS_V1'
FRONTIER = 'B57_DUAL_HASH_COMPLETE_FRAME_PREFIX_V1'
INDEX = 'B57_DUAL_HASH_CHUNK_INDEX_V1'
STORE = 'B57_PROFILE_BOUND_LIFECYCLE_STORE_V3'
INTENT = 'B57_PROFILE_BOUND_LIFECYCLE_INTENT_V3'
MAGIC = b'B57ZLIB1'
STATUS_MAGIC = b'B57STAT1'
FRAME = struct.Struct('>8sQQQQQ32s32s')
HEAD = struct.Struct('>8sQQQQ32s')
ZERO = '0' * 64

def raw(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def parse(data):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out: raise ValueError('duplicate compact JSON key')
            out[k] = v
        return out
    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite compact JSON')))

def fields(value, names):
    if type(value) is not dict or set(value) != set(names): raise ValueError('exact compact fields')
    return value

def integer(value, lo=0, hi=2**56):
    if type(value) is not int or not lo <= value <= hi: raise ValueError('exact bounded compact integer')
    return value

def digest(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value): raise ValueError('compact SHA256')
    return value

@dataclass(frozen=True, slots=True)
class PublicationProfile:
    method: str = METHOD
    compression_level: int = 6
    maximum_decoded_frame_bytes: int = 65536
    maximum_encoded_frame_bytes: int = 131072
    maximum_frame_records: int = 256
    maximum_expansion_ratio: int = 1024

    def __post_init__(self):
        expected = (METHOD, 6, 65536, 131072, 256, 1024)
        for name, wanted in zip(self.__dataclass_fields__, expected):
            if type(getattr(self, name)) is not type(wanted) or getattr(self, name) != wanted:
                raise ValueError('fixed source-owned publication profile: ' + name)

    @property
    def identity(self):
        self.__post_init__()
        return sha256(raw(asdict(self))).hexdigest()

def admit_profile(value, expected_identity=None):
    fields(value, PublicationProfile.__dataclass_fields__)
    p = PublicationProfile(**value)
    if expected_identity is not None and p.identity != expected_identity: raise ValueError('publication profile identity')
    return p

def requested_profile(name):
    if type(name) is not str: raise TypeError('explicit publication profile')
    if name == 'LEGACY_RAW': return None
    if name == METHOD: return PublicationProfile()
    raise ValueError('unknown publication profile')

def chunk(n):
    return 'chunk-' + str(integer(n, 1, 99999999)).zfill(8) + '.zframes'

def folder(path):
    path = Path(path).absolute()
    if any(p.is_symlink() or p.exists() and getattr(p, 'is_junction', lambda: False)() for p in (path, *path.parents)):
        raise ValueError('compact links/junctions')
    if any((p / '.git').exists() for p in (path, *path.parents)): raise ValueError('compact store inside repository')
    return path

def decode_frame(data, profile, *, expected_frame=None, expected_sequence=None):
    """Bound both compressed input and decompressor output BEFORE allocation."""
    if len(data) < FRAME.size: raise ValueError('incomplete compact header')
    magic, number, first, count, decoded, encoded, dh, eh = FRAME.unpack(data[:FRAME.size])
    for value in (number, first): integer(value, 1)
    integer(count, 1, profile.maximum_frame_records)
    integer(decoded, 1, profile.maximum_decoded_frame_bytes)
    integer(encoded, 1, profile.maximum_encoded_frame_bytes)
    if (magic != MAGIC or len(data) != FRAME.size + encoded or
        expected_frame is not None and number != expected_frame or
        expected_sequence is not None and first != expected_sequence or
        decoded > encoded * profile.maximum_expansion_ratio): raise ValueError('compact frame authority/size/sequence/expansion')
    payload = data[FRAME.size:]
    if sha256(payload).digest() != eh: raise ValueError('compact encoded hash')
    decoder = zlib.decompressobj()
    decoded_raw = decoder.decompress(payload, decoded + 1)
    if (len(decoded_raw) != decoded or not decoder.eof or decoder.unconsumed_tail or
        decoder.unused_data or sha256(decoded_raw).digest() != dh): raise ValueError('compact decoded size/hash/trailing bytes')
    lines = decoded_raw.split(b'\n')
    if lines[-1] != b'' or len(lines) - 1 != count: raise ValueError('compact record population')
    records = []
    for line in lines[:-1]:
        if not line or len(line) + 1 > profile.maximum_decoded_frame_bytes: raise ValueError('compact record bound')
        value = parse(line)
        if raw(value) != line: raise ValueError('compact canonical record')
        records.append(value)
    return records, decoded_raw

WORK = ('record_attempts', 'records_completed', 'encoded_bytes_reserved', 'bytes_published', 'index_records')
CODEC = ('encode_attempts', 'frames_completed', 'decoded_bytes_reserved', 'decoded_bytes_completed', 'codec_reserved_units')

class CompactStreamWriter:
    """Bounded block buffer. snapshot/finish commit every accepted record.

    Codec units are deterministic wrapper reservations, not physical leaf calls
    or measured CPU: 2*maximum_record_bytes before encoding, then 8*decoded+8192 before
    each compression/hash/validation attempt. No reservation is refunded.
    """
    def __init__(self, directory, policy, maximum_bytes, *, start_record=0, charge=None,
                 profile=None, codec_charge=None, buffered=False):
        if profile is None: profile = PublicationProfile()
        if type(profile) is not PublicationProfile: raise TypeError('exact publication profile')
        profile.__post_init__(); policy.__post_init__()
        if policy.max_record_bytes>profile.maximum_decoded_frame_bytes or policy.chunk_bytes<profile.maximum_encoded_frame_bytes+FRAME.size:
            raise ValueError('compact policy/frame compatibility')
        integer(maximum_bytes, 1024, 2**30); integer(start_record)
        self.directory = folder(directory)
        if self.directory.exists(): raise ValueError('new compact stream directory required')
        _register_producer_file(self.directory/'index.jsonl')
        self.directory.mkdir(parents=True)
        self.policy = policy; self.profile = profile; self.maximum_bytes = maximum_bytes
        self.start_record = start_record; self.charge = charge; self.codec_charge = codec_charge; self.buffered = buffered
        self.index = (self.directory / 'index.jsonl').open('xb'); self.index_hash = sha256(); self.index_bytes = 0; self.index_chain = ZERO
        self.file = None; self.chunk_hash = None; self.chunk_decoded_hash = None
        self.chunk_bytes = self.chunk_records = self.chunk_decoded_bytes = self.chunk_frames = 0
        self.sealed_chunks = self.sealed_bytes = self.sealed_decoded_bytes = self.records = self.frames = 0
        self.closed = self.failed = False; self.final = None; self.buffer = bytearray(); self.buffer_records = 0
        self.work = dict.fromkeys(WORK, 0); self.codec = dict.fromkeys(CODEC, 0)
        self._codec(65536) # fixed schema/index/manifest/control allowance, including empty streams

    def _reserve(self, n):
        self.work['encoded_bytes_reserved'] += n
        if self.charge is not None: self.charge(n)

    def _codec(self, n):
        self.codec['codec_reserved_units'] += n
        if self.codec_charge is not None: self.codec_charge(n)

    def _entry(self, sealed=False):
        e = dict(chunk=self.sealed_chunks + 1, file=chunk(self.sealed_chunks + 1), bytes=self.chunk_bytes,
                 records=self.chunk_records, first_sequence=self.start_record+self.records-self.chunk_records+1,
                 last_sequence=self.start_record+self.records, sha256=self.chunk_hash.hexdigest(),
                 decoded_bytes=self.chunk_decoded_bytes, decoded_sha256=self.chunk_decoded_hash.hexdigest(),
                 frames=self.chunk_frames, first_frame=self.frames-self.chunk_frames+1, last_frame=self.frames)
        if sealed:
            e.update(format=INDEX, previous_index_chain=self.index_chain)
            e['index_chain'] = sha256((self.index_chain+raw(e).decode()).encode()).hexdigest()
        return e

    def _seal(self):
        if self.file is None: return
        e = self._entry(True); data = raw(e)+b'\n'
        if (len(data)>4096 or self.index_bytes+len(data)>self.policy.max_index_bytes or
            self.work['bytes_published']+len(data)>self.maximum_bytes): raise ValueError('compact sealed index quota')
        self._reserve(len(data)); self.file.flush(); _io_fsync(self.file.fileno()); self.file.close(); self.file = None
        self.index.write(data); self.index.flush(); _io_fsync(self.index.fileno())
        self.index_hash.update(data); self.index_bytes += len(data); self.index_chain = e['index_chain']
        self.sealed_chunks += 1; self.sealed_bytes += self.chunk_bytes; self.sealed_decoded_bytes += self.chunk_decoded_bytes
        self.work['bytes_published'] += len(data); self.work['index_records'] += 1

    def flush(self):
        if not self.buffer: return None
        decoded = bytes(self.buffer); count = self.buffer_records
        self.codec['encode_attempts'] += 1; self._codec(8*len(decoded)+8192)
        encoded = zlib.compress(decoded, self.profile.compression_level)
        if len(encoded)>self.profile.maximum_encoded_frame_bytes or len(decoded)>len(encoded)*self.profile.maximum_expansion_ratio:
            raise ValueError('compact compression bounds')
        number = self.frames+1; first = self.start_record+self.records+1
        data = FRAME.pack(MAGIC, number, first, count, len(decoded), len(encoded), sha256(decoded).digest(), sha256(encoded).digest())+encoded
        if self.work['bytes_published']+len(data)+4096>self.maximum_bytes: raise ValueError('compact prospective stream quota')
        if self.file is not None and self.chunk_bytes+len(data)>self.policy.chunk_bytes: self._seal()
        if self.file is None:
            _register_producer_file(self.directory/chunk(self.sealed_chunks+1))
            self.file = (self.directory/chunk(self.sealed_chunks+1)).open('xb')
            self.chunk_hash = sha256(); self.chunk_decoded_hash = sha256()
            self.chunk_bytes = self.chunk_records = self.chunk_decoded_bytes = self.chunk_frames = 0
        offset = self.chunk_bytes; self._reserve(len(data)); self.file.write(data); self.file.flush()
        self.chunk_hash.update(data); self.chunk_decoded_hash.update(decoded)
        self.chunk_bytes += len(data); self.chunk_records += count; self.chunk_decoded_bytes += len(decoded); self.chunk_frames += 1
        self.records += count; self.frames += 1; self.work['records_completed'] += count; self.work['bytes_published'] += len(data)
        self.codec['frames_completed'] += 1; self.codec['decoded_bytes_completed'] += len(decoded)
        self.buffer.clear(); self.buffer_records = 0
        return dict(file=chunk(self.sealed_chunks+1), chunk=self.sealed_chunks+1, offset=offset, bytes=len(data),
                    sha256=sha256(data).hexdigest(), sequence=self.start_record+self.records)

    def append(self, payload):
        if self.closed or self.failed: raise ValueError('closed/failed compact stream')
        self.work['record_attempts'] += 1
        try:
            self._codec(2*self.policy.max_record_bytes)
            self.codec['decoded_bytes_reserved'] += self.policy.max_record_bytes
            data = raw(payload)+b'\n'
            if len(data)>min(self.policy.max_record_bytes,self.profile.maximum_decoded_frame_bytes): raise ValueError('compact record byte cap')
            if self.buffer and (len(self.buffer)+len(data)>self.profile.maximum_decoded_frame_bytes or self.buffer_records>=self.profile.maximum_frame_records): self.flush()
            self.buffer.extend(data); self.buffer_records += 1
            if not self.buffered: return self.flush()
            return None
        except BaseException:
            self.failed = True
            raise

    def snapshot(self):
        self.flush()
        if self.file is not None: self.file.flush(); _io_fsync(self.file.fileno())
        self.index.flush(); _io_fsync(self.index.fileno())
        return dict(format=FRONTIER, profile=asdict(self.profile), profile_identity=self.profile.identity,
                    policy=asdict(self.policy), policy_identity=self.policy.identity, maximum_bytes=self.maximum_bytes,
                    start_record=self.start_record, end_record=self.start_record+self.records, records=self.records,
                    sealed_chunks=self.sealed_chunks, sealed_bytes=self.sealed_bytes, sealed_decoded_bytes=self.sealed_decoded_bytes,
                    index_bytes=self.index_bytes, index_sha256=self.index_hash.hexdigest(), index_chain=self.index_chain,
                    current=None if self.file is None else self._entry(), writer_failed=self.failed,
                    work=dict(self.work), codec=dict(self.codec))

    def finish(self):
        if self.final is not None: return self.final
        if self.closed: raise ValueError('compact closed without manifest')
        try:
            self.flush(); self._seal(); self.final = self.snapshot(); data = raw(self.final)
            self._reserve(len(data))
            _register_producer_file(self.directory/'manifest.json')
            with (self.directory/'manifest.json').open('xb') as f: f.write(data); f.flush(); _io_fsync(f.fileno())
            return self.final
        except BaseException:
            self.failed = True
            raise
        finally: self.close()

    def close(self):
        if self.file is not None: self.file.close(); self.file = None
        if not self.index.closed: self.index.close()
        self.closed = True

ENTRY = ('chunk','file','bytes','records','first_sequence','last_sequence','sha256','decoded_bytes','decoded_sha256','frames','first_frame','last_frame')

def admit_frontier(value, policy=None, profile=None):
    from .lifecycle_stream import LifecycleStreamPolicy
    fields(value, ('format','profile','profile_identity','policy','policy_identity','maximum_bytes','start_record','end_record','records',
                   'sealed_chunks','sealed_bytes','sealed_decoded_bytes','index_bytes','index_sha256','index_chain','current','writer_failed','work','codec'))
    p = LifecycleStreamPolicy(**value['policy']); c = admit_profile(value['profile'],value['profile_identity'])
    if value['format']!=FRONTIER or p.identity!=value['policy_identity'] or policy is not None and p!=policy or profile is not None and c!=profile: raise ValueError('compact frontier profile/policy binding')
    for n in ('maximum_bytes','start_record','end_record','records','sealed_chunks','sealed_bytes','sealed_decoded_bytes','index_bytes'): integer(value[n])
    integer(value['maximum_bytes'],1024,2**30)
    if p.max_record_bytes>c.maximum_decoded_frame_bytes or p.chunk_bytes<c.maximum_encoded_frame_bytes+FRAME.size:raise ValueError('compact frontier policy/frame compatibility')
    for n in ('index_sha256','index_chain'): digest(value[n])
    fields(value['work'],WORK); fields(value['codec'],CODEC)
    for v in (*value['work'].values(),*value['codec'].values()): integer(v)
    w=value['work']; a=value['codec']
    if (type(value['writer_failed']) is not bool or value['end_record']!=value['start_record']+value['records'] or
        value['index_bytes']>p.max_index_bytes or w['records_completed']!=value['records'] or w['record_attempts']<value['records'] or
        w['index_records']!=value['sealed_chunks'] or w['bytes_published']>value['maximum_bytes'] or w['encoded_bytes_reserved']<w['bytes_published'] or
        a['frames_completed']>a['encode_attempts'] or a['decoded_bytes_completed']>a['decoded_bytes_reserved'] or
        a['decoded_bytes_reserved']!=w['record_attempts']*p.max_record_bytes or
        a['codec_reserved_units']<65536+2*a['decoded_bytes_reserved']+8*a['decoded_bytes_completed']+8192*a['encode_attempts'] or
        not value['writer_failed'] and (w['record_attempts']!=w['records_completed'] or a['encode_attempts']!=a['frames_completed'])): raise ValueError('compact frontier work balance')
    if not value['writer_failed'] and (a['codec_reserved_units']!=65536+2*a['decoded_bytes_reserved']+8*a['decoded_bytes_completed']+8192*a['frames_completed'] or w['encoded_bytes_reserved']!=w['bytes_published']):raise ValueError('exact completed compact reservation balance')
    from .lifecycle_stream import _admit_inventory_counts
    _admit_inventory_counts(value,p)
    if value['current'] is not None: _entry(value['current'],p,c)
    return p

def _entry(e,p,c):
    fields(e,ENTRY)
    for n in set(ENTRY)-{'file','sha256','decoded_sha256'}: integer(e[n],1)
    digest(e['sha256']); digest(e['decoded_sha256'])
    if (e['file']!=chunk(e['chunk']) or e['bytes']>p.chunk_bytes or e['last_sequence']-e['first_sequence']+1!=e['records'] or
        e['last_frame']-e['first_frame']+1!=e['frames'] or e['decoded_bytes']>e['frames']*c.maximum_decoded_frame_bytes): raise ValueError('compact entry bounds')

def _read_chunk(directory,e,p,c,prefix=False):
    _entry(e,p,c); path=folder(directory/e['file']); size=path.stat().st_size
    if size<e['bytes'] or not prefix and size!=e['bytes']: raise ValueError('compact chunk size')
    remaining=e['bytes']; eh=sha256(); dh=sha256(); count=decoded=frames=0
    with path.open('rb') as f:
        while remaining:
            header=f.read(FRAME.size)
            if len(header)!=FRAME.size or remaining<FRAME.size: raise ValueError('compact incomplete header')
            values=FRAME.unpack(header); encoded=values[5]
            integer(encoded,1,c.maximum_encoded_frame_bytes)
            if FRAME.size+encoded>remaining: raise ValueError('compact incomplete payload')
            data=header+f.read(encoded)
            records, original=decode_frame(data,c,expected_frame=e['first_frame']+frames,expected_sequence=e['first_sequence']+count)
            eh.update(data); dh.update(original); remaining-=len(data); count+=len(records); decoded+=len(original); frames+=1
            yield from records
    if (eh.hexdigest()!=e['sha256'] or dh.hexdigest()!=e['decoded_sha256'] or count!=e['records'] or
        decoded!=e['decoded_bytes'] or frames!=e['frames']): raise ValueError('compact dual hash/population')

def iter_records(directory,frontier,policy=None):
    directory=folder(directory); p=admit_frontier(frontier,policy); c=admit_profile(frontier['profile'],frontier['profile_identity'])
    path=directory/'index.jsonl'
    if path.stat().st_size<frontier['index_bytes']: raise ValueError('compact index prefix size')
    remaining=frontier['index_bytes']; ih=sha256(); chain=ZERO; count=encoded=decoded=ordinal=frames=0; next_sequence=frontier['start_record']+1
    with path.open('rb') as f:
        while remaining:
            data=f.readline(min(remaining,4096)+1)
            if not data.endswith(b'\n') or len(data)>min(remaining,4096): raise ValueError('compact index tail')
            remaining-=len(data); ih.update(data); e=parse(data[:-1]); fields(e,(*ENTRY,'format','previous_index_chain','index_chain'))
            content={k:v for k,v in e.items() if k!='index_chain'}; ordinal+=1
            if (raw(e)+b'\n'!=data or e['format']!=INDEX or e['chunk']!=ordinal or e['first_sequence']!=next_sequence or
                e['first_frame']!=frames+1 or e['previous_index_chain']!=chain or sha256((chain+raw(content).decode()).encode()).hexdigest()!=e['index_chain']): raise ValueError('compact index chain/order')
            item={k:e[k] for k in ENTRY}; yield from _read_chunk(directory,item,p,c)
            chain=e['index_chain']; count+=e['records']; encoded+=e['bytes']; decoded+=e['decoded_bytes']; frames+=e['frames']; next_sequence=e['last_sequence']+1
    if (ordinal!=frontier['sealed_chunks'] or encoded!=frontier['sealed_bytes'] or decoded!=frontier['sealed_decoded_bytes'] or
        ih.hexdigest()!=frontier['index_sha256'] or chain!=frontier['index_chain']): raise ValueError('compact index frontier')
    e=frontier['current']
    if e is not None:
        if e['chunk']!=ordinal+1 or e['first_sequence']!=next_sequence or e['first_frame']!=frames+1: raise ValueError('compact current sequence')
        yield from _read_chunk(directory,e,p,c,True)
        count+=e['records']; encoded+=e['bytes']; decoded+=e['decoded_bytes']; frames+=e['frames']
    if (count!=frontier['records'] or encoded+frontier['index_bytes']!=frontier['work']['bytes_published'] or
        decoded!=frontier['codec']['decoded_bytes_completed'] or frames!=frontier['codec']['frames_completed']): raise ValueError('compact stream conservation')

class IncrementalCompactReader:
    def __init__(self,directory,policy,maximum_bytes,profile,read_charge=None):
        self.directory=folder(directory); self.policy=policy; self.maximum_bytes=maximum_bytes; self.profile=profile
        self.chunk=1; self.offset=0; self.bytes=0; self.tail=b''; self.records=0; self.frames=0
        self.read_charge=read_charge
    def read(self):
        # Bound the DECODED live batch as well as each member. Compression must
        # not turn four encoded chunks into a mission-sized result array.
        result=[]; decoded_bytes=0; visited=0; self.has_complete_backlog=False; self.needs_another_poll=False
        while visited<4:
            path=self.directory/chunk(self.chunk)
            if not path.exists():break
            size=path.stat().st_size
            if size>self.policy.chunk_bytes or self.offset>size:raise ValueError('live compact chunk cap/rewind')
            remaining=size-self.offset
            if remaining==0:
                if (self.directory/chunk(self.chunk+1)).exists():
                    self.chunk+=1;self.offset=0;visited+=1;continue
                break
            with path.open('rb') as stream:
                stream.seek(self.offset)
                if self.read_charge is not None:self.read_charge(65536) # header/control before read
                header=stream.read(min(FRAME.size,remaining))
                if len(header)<FRAME.size:
                    self.tail=header
                    if (self.directory/chunk(self.chunk+1)).exists():raise ValueError('compact torn header before next chunk')
                    break
                values=FRAME.unpack(header);integer(values[4],1,self.profile.maximum_decoded_frame_bytes);integer(values[5],1,self.profile.maximum_encoded_frame_bytes);integer(values[3],1,self.profile.maximum_frame_records)
                length=FRAME.size+values[5]
                if length>remaining:
                    if self.read_charge is not None:self.read_charge(remaining)
                    self.tail=header+stream.read(remaining-FRAME.size)
                    if (self.directory/chunk(self.chunk+1)).exists():raise ValueError('compact torn payload before next chunk')
                    break
                if decoded_bytes+values[4]>2**20 or len(result)+values[3]>1024:
                    self.has_complete_backlog=True;self.tail=b'';break
                if self.bytes+length>self.maximum_bytes:raise ValueError('live compact stream cap')
                if self.read_charge is not None:self.read_charge(4*values[4]+length)
                data=header+stream.read(values[5])
            records,_=decode_frame(data,self.profile,expected_frame=self.frames+1,expected_sequence=self.records+1)
            self.offset+=length;self.bytes+=length;decoded_bytes+=values[4];self.frames+=1;self.records+=len(records);result.extend(records);self.tail=b''
        # A chunk-hop bound is also a batching boundary. Do not mistake an
        # unexamined fifth chunk for EOF when the child has already finished.
        next_path=self.directory/chunk(self.chunk)
        self.needs_another_poll=self.has_complete_backlog or (visited>=4 and next_path.exists() and next_path.stat().st_size>self.offset)
        return result

class CompactStatus:
    def __init__(self,directory,policy,*,charge=None,profile=None,codec_charge=None):
        self.directory=folder(directory); self.policy=policy; self.charge=charge
        self.writer=CompactStreamWriter(self.directory/'records',policy,policy.status_total_bytes,charge=charge,profile=profile,codec_charge=codec_charge)
        _register_producer_file(self.directory/'heads.bin')
        self.head=(self.directory/'heads.bin').open('xb'); self.head_bytes=0
    def publish(self,status,*,terminal=False):
        if type(terminal) is not bool: raise TypeError('exact terminal flag')
        # Worst-case independent zlib frame + header + index, not last observed size.
        reserve=2*(self.writer.profile.maximum_encoded_frame_bytes+FRAME.size)+4096
        if not terminal and (self.writer.work['bytes_published']+reserve>self.policy.status_total_bytes or self.head_bytes+9*HEAD.size>self.policy.max_index_bytes): raise ValueError('compact status terminal reserve')
        if self.head_bytes+HEAD.size>self.policy.max_index_bytes: raise ValueError('compact status head cap')
        if self.charge is not None: self.charge(HEAD.size)
        receipt=self.writer.append(status); self.writer.snapshot()
        data=HEAD.pack(STATUS_MAGIC,receipt['sequence'],receipt['chunk'],receipt['offset'],receipt['bytes'],bytes.fromhex(receipt['sha256']))
        self.head.write(data); self.head.flush(); _io_fsync(self.head.fileno()); self.head_bytes+=len(data)
        return receipt['sequence']
    def close(self):
        try:
            if not self.writer.closed: self.writer.finish()
        finally: self.head.close()

def read_status(directory,policy,profile):
    directory=folder(directory); path=directory/'heads.bin'; size=path.stat().st_size
    if not HEAD.size<=size<=policy.max_index_bytes: raise ValueError('compact status head bound')
    complete,tail=divmod(size,HEAD.size)
    with path.open('rb') as f: f.seek((complete-1)*HEAD.size); magic,seq,n,offset,length,expected=HEAD.unpack(f.read(HEAD.size))
    integer(n,1); integer(offset); integer(length,FRAME.size+1,profile.maximum_encoded_frame_bytes+FRAME.size)
    if magic!=STATUS_MAGIC or seq!=complete or offset+length>policy.chunk_bytes: raise ValueError('compact status head authority')
    p=folder(directory/'records'/chunk(n))
    if p.stat().st_size<offset+length: raise ValueError('compact status incomplete frame')
    with p.open('rb') as f: f.seek(offset); data=f.read(length)
    if sha256(data).digest()!=expected: raise ValueError('compact status transport hash')
    records,_=decode_frame(data,profile,expected_frame=seq,expected_sequence=seq)
    if len(records)!=1: raise ValueError('status single record frame')
    return records[0],dict(sequence=seq,incomplete_head_tail_bytes=tail,read_validation_reserved_units=65536+4*FRAME.unpack(data[:FRAME.size])[4]+len(data),scope='READ_ONLY_LAST_COMPLETE_STATUS_HEAD_NOT_PROCESS_OWNERSHIP')
