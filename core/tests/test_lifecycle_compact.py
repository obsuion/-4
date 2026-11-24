"""Independent transport adversaries; no spacecraft calculation."""
from copy import deepcopy
from hashlib import sha256
import json, struct, zlib
import pytest
from ops_sim.v5.lifecycle_compact import (PublicationProfile,CompactStreamWriter,FRAME,MAGIC,
    FRONTIER,decode_frame,raw,admit_frontier,IncrementalCompactReader,CompactStatus,read_status)
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy,iter_stream_records,verify_stream,ChunkedStreamWriter

P=PublicationProfile(); S=LifecycleStreamPolicy()

def make(tmp_path,buffered=True,n=600):
    w=CompactStreamWriter(tmp_path/'frames',S,2**20,profile=P,buffered=buffered)
    original=[dict(index=i,clock=128+i//3,reason='refused' if i%7==0 else None,solar={'unchanged':'x'*800},bits=i%11) for i in range(n)]
    for r in original:w.append(r)
    f=w.finish()
    return w,f,original

def test_full_canonical_roundtrip_dual_hashes_and_wrapper_charge(tmp_path):
    w,f,rows=make(tmp_path)
    result=list(iter_stream_records(tmp_path/'frames'))
    assert b''.join(raw(r)+b'\n' for r in result)==b''.join(raw(r)+b'\n' for r in rows)
    assert f['codec']['frames_completed']<len(rows)
    assert f['codec']['codec_reserved_units']==65536+2*S.max_record_bytes*len(rows)+8*f['codec']['decoded_bytes_completed']+8192*f['codec']['frames_completed']
    assert f['work']['bytes_published']<f['codec']['decoded_bytes_completed']//5
    assert w.work['encoded_bytes_reserved']==f['work']['encoded_bytes_reserved']+len((tmp_path/'frames/manifest.json').read_bytes())

def test_raw_reader_remains_distinct(tmp_path):
    w=ChunkedStreamWriter(tmp_path/'raw',S,2**20);w.append({'index':1});f=w.finish()
    assert f['format']!=FRONTIER and list(iter_stream_records(tmp_path/'raw'))==[{'index':1}]

def test_checkpoint_flushes_current_block_and_later_suffix_is_not_authority(tmp_path):
    w=CompactStreamWriter(tmp_path/'frames',S,2**20,profile=P,buffered=True)
    w.append({'index':0});f=w.snapshot();assert f['records']==1 and f['current']
    w.append({'index':1});w.flush()
    assert list(iter_stream_records(tmp_path/'frames',f))==[{'index':0}]
    w.finish();assert len(list(iter_stream_records(tmp_path/'frames')))==2

@pytest.mark.parametrize('change',['encoded','decoded','trailing','truncated','size','expansion','magic','sequence','records','duplicate_key','noncanonical'])
def test_frame_adversaries_rejected(change):
    original=b'{"x":1}\n';enc=zlib.compress(original);values=[MAGIC,1,1,1,len(original),len(enc),sha256(original).digest(),sha256(enc).digest()]
    if change=='encoded':enc=enc[:-1]+bytes([enc[-1]^1])
    elif change=='decoded':values[6]=bytes(32)
    elif change=='trailing':enc+=b'trailing';values[5]=len(enc);values[7]=sha256(enc).digest()
    elif change=='truncated':enc=enc[:-1]
    elif change=='size':values[4]=P.maximum_decoded_frame_bytes+1
    elif change=='expansion':values[4]=65536;values[5]=1;enc=b'x';values[7]=sha256(enc).digest()
    elif change=='magic':values[0]=b'BADMAGIC'
    elif change=='sequence':values[1]=2
    elif change=='records':values[3]=2
    elif change in ('duplicate_key','noncanonical'):
        original=b'{"x":1,"x":1}\n' if change=='duplicate_key' else b'{ "x": 1 }\n'
        enc=zlib.compress(original);values[4:8]=[len(original),len(enc),sha256(original).digest(),sha256(enc).digest()]
    data=FRAME.pack(*values)+enc
    with pytest.raises((ValueError,zlib.error)):decode_frame(data,P,expected_frame=1,expected_sequence=1)

@pytest.mark.parametrize('field,value',[('format','unknown'),('records',True),('end_record',99),('index_sha256','f'*64),('policy_identity','a'*64),('profile_identity','b'*64)])
def test_frontier_tampering(tmp_path,field,value):
    _,f,_=make(tmp_path,n=2);bad=deepcopy(f);bad[field]=value
    with pytest.raises(ValueError):list(iter_stream_records(tmp_path/'frames',bad))

@pytest.mark.parametrize('path',['../evil','/absolute','C:/absolute','chunk-00000001.jsonl','chunk-00000001.ZFRAMES'])
def test_exact_paths_not_user_authority(tmp_path,path):
    w=CompactStreamWriter(tmp_path/'frames',S,2**20,profile=P);w.append({'x':1});f=w.snapshot();f['current']['file']=path
    with pytest.raises(ValueError):list(iter_stream_records(tmp_path/'frames',f))
    w.close()

def test_live_torn_tail_is_explicit_and_never_a_record(tmp_path):
    w=CompactStreamWriter(tmp_path/'frames',S,2**20,profile=P);w.append({'x':1});w.snapshot()
    reader=IncrementalCompactReader(tmp_path/'frames',S,2**20,P)
    assert reader.read()==[{'x':1}]
    with (tmp_path/'frames/chunk-00000001.zframes').open('ab') as f:f.write(b'B57')
    assert reader.read()==[] and reader.tail==b'B57'
    w.close()

def test_extra_final_chunk_and_index_tail_rejected(tmp_path):
    _,f,_=make(tmp_path,n=2)
    extra=tmp_path/'frames/chunk-00000002.zframes';extra.write_bytes(b'not authority')
    with pytest.raises(ValueError):verify_stream(tmp_path/'frames')

def test_status_random_access_complete_record_and_tail(tmp_path):
    w=CompactStatus(tmp_path/'status',S,profile=P)
    w.publish({'sequence':1});w.publish({'sequence':2},terminal=True);w.close()
    value,proof=read_status(tmp_path/'status',S,P)
    assert value=={'sequence':2} and proof['sequence']==2
    with (tmp_path/'status/heads.bin').open('ab') as f:f.write(b'partial')
    assert read_status(tmp_path/'status',S,P)[1]['incomplete_head_tail_bytes']==7

@pytest.mark.parametrize('key,value',[('compression_level',True),('compression_level',9),('maximum_decoded_frame_bytes',2**30),('method','other')])
def test_fixed_profile_not_arbitrary_decompress_policy(key,value):
    with pytest.raises((TypeError,ValueError)):PublicationProfile(**{key:value})

def test_decoded_live_batch_bound_and_complete_backlog_are_lossless(tmp_path):
    w=CompactStreamWriter(tmp_path/'bounded',S,2**20,profile=P)
    expected=sha256()
    for i in range(600):
        v=dict(index=i,repeat='x'*8192);expected.update(raw(v)+b'\n');w.append(v)
    w.finish();reader=IncrementalCompactReader(tmp_path/'bounded',S,2**20,P)
    actual=sha256();n=0;batches=0
    while True:
        values=reader.read()
        if not values:break
        assert sum(len(raw(v))+1 for v in values)<=2**20 and len(values)<=1024
        assert reader.tail==b'' # a complete backlog is not a torn frame
        for value in values:actual.update(raw(value)+b'\n');n+=1
        batches+=1
    assert n==600 and batches>1 and actual.digest()==expected.digest()

@pytest.mark.parametrize('field',['codec_reserved_units','encoded_bytes_reserved','maximum_bytes'])
def test_completed_frontier_reservations_are_exact_not_inflatable(tmp_path,field):
    _,f,_=make(tmp_path,n=2);bad=deepcopy(f)
    if field=='maximum_bytes':bad[field]=0
    elif field=='codec_reserved_units':bad['codec'][field]+=1
    else:bad['work'][field]+=1
    with pytest.raises(ValueError):admit_frontier(bad,S)

def test_chunk_hop_bound_is_not_false_eof(tmp_path):
    from dataclasses import replace
    from hashlib import shake_256
    policy=replace(S,chunk_bytes=131184)
    w=CompactStreamWriter(tmp_path/'many-chunks',policy,2**20,profile=P)
    expected=sha256()
    for i in range(600):
        value=dict(index=i,text=shake_256(str(i).encode()).hexdigest(900))
        expected.update(raw(value)+b'\n');w.append(value)
    w.finish();reader=IncrementalCompactReader(tmp_path/'many-chunks',policy,2**20,P)
    values=reader.read()
    assert len(values)<600 and reader.needs_another_poll and reader.tail==b''
    actual=sha256();n=0
    while True:
        for value in values:actual.update(raw(value)+b'\n');n+=1
        values=reader.read()
        if not values:break
    assert n==600 and actual.digest()==expected.digest()

def test_random_access_status_rejects_wrong_frame_ordinal_even_with_new_transport_hash(tmp_path):
    from ops_sim.v5.lifecycle_compact import HEAD
    w=CompactStatus(tmp_path/'status-counter',S,profile=P);w.publish({'sequence':1});w.close()
    p=tmp_path/'status-counter/records/chunk-00000001.zframes';data=p.read_bytes();values=list(FRAME.unpack(data[:FRAME.size]));values[1]=2
    changed=FRAME.pack(*values)+data[FRAME.size:];p.write_bytes(changed)
    hp=tmp_path/'status-counter/heads.bin';h=list(HEAD.unpack(hp.read_bytes()));h[-1]=sha256(changed).digest();hp.write_bytes(HEAD.pack(*h))
    with pytest.raises(ValueError):read_status(tmp_path/'status-counter',S,P)
