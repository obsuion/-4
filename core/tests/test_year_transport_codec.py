"""Transport bounds on synthetic canonical checkpoint bytes, independent of models."""
from hashlib import sha256
import json,zlib
import pytest
from ops_sim.v5 import checkpoint_transport as cp
B=dict(root_identity='a'*64,source_identity='b'*64,runtime={'python':'declared-runtime'})
def packet(codec=cp.ZLIB3):
    raw=cp._raw({'format':'SYNTHETIC_CHECKPOINT_V1','value':'x'*20000})
    encoded,receipt=cp.encode_checkpoint(raw,B,'FINAL',codec=codec)
    return raw,encoded,receipt
def rebuild(encoded,change,payload=None):
    start=len(cp.MAGIC)+cp.PREFIX.size;length=cp.PREFIX.unpack_from(encoded,len(cp.MAGIC))[0]
    header=json.loads(encoded[start:start+length]);original=encoded[start+length:]
    if payload is None:payload=original
    change(header)
    header['payload_bytes']=len(payload);header['payload_sha256']=sha256(payload).hexdigest()
    h=cp._raw(header)
    return cp.MAGIC+cp.PREFIX.pack(len(h))+h+payload
@pytest.mark.parametrize('codec',cp.CODECS)
def test_independent_codec_exact_roundtrip_and_bound(codec):
    if codec==cp.ZSTD:pytest.importorskip('compression.zstd')
    raw,encoded,receipt=packet(codec)
    decoded,actual=cp.decode_checkpoint(encoded,sha256(raw).hexdigest(),B,expected_role='FINAL')
    assert decoded==raw and actual==receipt
    assert len(encoded)<=len(raw)+cp.MAX_FRAMING_BYTES
    assert cp.decode_checkpoint(raw,sha256(raw).hexdigest(),B)[0]==raw

def test_raw_fallback_remains_bounded_and_exact():
    raw=b'{"format":"T"}';encoded,receipt=cp.encode_checkpoint(raw,B,'WORKING')
    assert receipt['codec']==cp.RAW
    assert cp.decode_checkpoint(encoded,sha256(raw).hexdigest(),B)[0]==raw
@pytest.mark.parametrize('fault',('version_bool','codec','role','binding','extra','decoded_length','decoded_maximum','format'))
def test_header_faults_cannot_grant_decoding(fault):
    raw,encoded,_=packet()
    changes={'version_bool':lambda h:h.update(version=True),'codec':lambda h:h.update(codec='UNKNOWN'),
      'role':lambda h:h.update(role='WORKING'),'binding':lambda h:h['bindings'].update(root_identity='c'*64),
      'extra':lambda h:h.update(unknown=True),'decoded_length':lambda h:h.update(decoded_bytes=len(raw)-1),
      'decoded_maximum':lambda h:h.update(decoded_maximum_bytes=True),'format':lambda h:h.update(checkpoint_format='OTHER')}
    bad=rebuild(encoded,changes[fault])
    with pytest.raises((ValueError,TypeError)):cp.decode_checkpoint(bad,sha256(raw).hexdigest(),B,expected_role='FINAL')
@pytest.mark.parametrize('codec', (cp.ZLIB3,cp.ZSTD))
def test_concatenated_frame_and_truncated_frame_refuse(codec):
    if codec==cp.ZSTD:pytest.importorskip('compression.zstd')
    raw,encoded,_=packet(codec);start=len(cp.MAGIC)+cp.PREFIX.size;length=cp.PREFIX.unpack_from(encoded,len(cp.MAGIC))[0]
    payload=encoded[start+length:]
    for data in (payload+payload,payload[:-1]):
        bad=rebuild(encoded,lambda h:None,payload=data)
        with pytest.raises(ValueError):cp.decode_checkpoint(bad,sha256(raw).hexdigest(),B)
@pytest.mark.parametrize('length',(0,1,8,9,12,30))
def test_incomplete_outer_frame_refuses(length):
    raw,encoded,_=packet()
    with pytest.raises(ValueError):cp.decode_checkpoint(encoded[:length],sha256(raw).hexdigest(),B)

def test_output_cap_is_checked_before_compressed_expansion():
    raw,encoded,_=packet()
    with pytest.raises(ValueError):cp.decode_checkpoint(encoded,sha256(raw).hexdigest(),B,maximum_decoded_bytes=1000)
