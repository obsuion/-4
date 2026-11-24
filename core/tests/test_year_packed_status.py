"""Packed DATA uses actual temporary files; no numerical model is evaluated."""
from copy import deepcopy
from hashlib import sha256
import json
import os
import sqlite3
import zlib

import pytest

from ops_sim.v5 import lifetime_packed_status as packed
from ops_sim.v5 import lifetime_status as status
from ops_sim.v5.lifecycle_stream import LifecycleStreamPolicy


def job():
    return dict(format='B59_FINITE_OWNED_LIFECYCLE_JOB_V1',job_id='1'*32,
        intent=dict(root_identity='2'*64,idempotency_key='3'*32,parent_job_id=None,
                    mode='NORMAL',maximum_output_bytes=128*2**20),
        root_identity='2'*64,source_identity='4'*64,
        runtime=dict(implementation='CPython',version=[3,14,7]),input_sha256='5'*64,
        resume=None,publication_sequence=0,status='QUEUED',reason=None,progress=None,
        checkpoints=[],result=None,launch=None,ownership_valid=None,
        created_utc='2026-10-24T00:00:00Z',worker_artifact_bytes=None)


def binding():
    return status.make_binding(job(),'6'*64,None,'7'*64)


def field(number=0,size=800):
    decoded=packed.raw(dict(number=number,text='x'*size))
    return 'objects/'+sha256(decoded).hexdigest()+'.zjson',zlib.compress(decoded,6)


def details(number=0):
    data=packed.raw(dict(number=number))
    return 'details/'+str(number+1).zfill(8)+'-'+sha256(data).hexdigest()+'.json',data


@pytest.fixture(autouse=True)
def no_unrelated_physical_owner(monkeypatch):
    # The physical producer owner is checked separately. These tests isolate
    # frame/index corruption and do not invent any physical allocation credit.
    monkeypatch.setattr(packed,'_claim',lambda path:None)


def test_roundtrip_seal_reopen_and_duplicate_is_content_checked(tmp_path):
    key,data=field();other,payload=details()
    with packed.PackedStatus(tmp_path,binding(),create=True)as store:
        assert store.put(key,data,role='FIELD')['sequence']==1
        assert store.put(key,data,role='FIELD')==dict(existing=True,published_bytes=0)
        store.put(other,payload,role='DETAILS')
        assert store.read(key)==data and store.read(other)==payload
        assert store.snapshot()['logical_objects']==2
    with packed.PackedStatus(tmp_path,binding())as store:
        assert store.read(key,expected_sha256=sha256(data).hexdigest(),expected_bytes=len(data))==data
        assert store.verify_import()['objects']==2
    assert not(tmp_path/'objects').exists() and not(tmp_path/'details').exists()
    assert len(list((tmp_path/'packed-v1').glob('block-*.bin')))==1


def test_frame_binds_encoded_and_decoded_identity_source_role_and_sequence(tmp_path):
    key,data=field()
    with packed.PackedStatus(tmp_path,binding(),create=True)as store:
        store.put(key,data,role='FIELD')
        row=store._row(key);block=store._block_path(row[0]).read_bytes()
        count=packed.PREFIX.unpack(block[:4])[0]
        header=json.loads(block[4:4+count])
        assert header['role']=='FIELD' and header['sequence']==1
        assert header['encoded_sha256']==sha256(data).hexdigest()
        assert header['decoded_sha256']==key[8:-6]
        assert header['decoded_bytes']==len(zlib.decompress(data))
        assert header['context_sha256']==sha256(packed.raw(binding())).hexdigest()


@pytest.mark.parametrize('damage',('payload','truncate','offset','digest','role'))
def test_corrupt_consumed_range_is_refused(tmp_path,damage):
    key,data=field()
    with packed.PackedStatus(tmp_path,binding(),create=True)as store:store.put(key,data,role='FIELD')
    database=tmp_path/'packed-v1'/'index.sqlite3'
    block=next((tmp_path/'packed-v1').glob('block-*.bin'))
    if damage in('payload','truncate'):
        content=block.read_bytes();block.write_bytes(content[:-1]if damage=='truncate'else content[:-1]+bytes([content[-1]^1]))
    else:
        with sqlite3.connect(database)as db:
            if damage=='offset':db.execute('UPDATE objects SET offset=offset+1')
            elif damage=='digest':db.execute('UPDATE objects SET sha=?',(bytes(32),))
            else:db.execute('UPDATE objects SET role=1')
    with packed.PackedStatus(tmp_path,binding())as store:
        with pytest.raises((ValueError,zlib.error,json.JSONDecodeError)):store.read(key)


def test_context_change_and_noncanonical_payload_refused_before_append(tmp_path):
    original=binding()
    with packed.PackedStatus(tmp_path,original,create=True)as store:
        before=store.snapshot()
        data=zlib.compress(b'{"x": 1}')
        key='objects/'+sha256(b'{"x": 1}').hexdigest()+'.zjson'
        with pytest.raises(ValueError,match='canonical'):store.put(key,data,role='FIELD')
        assert store.snapshot()['logical_objects']==before['logical_objects']==0
    wrong=deepcopy(original);wrong['source_identity']='a'*64
    with pytest.raises(ValueError,match='binding'):packed.PackedStatus(tmp_path,wrong)


@pytest.mark.parametrize('mode',('tail','wrongkey','wrongrole','boolterminal'))
def test_bad_codec_key_role_and_exact_flag_do_not_publish(tmp_path,mode):
    key,data=field();role='FIELD';terminal=False
    if mode=='tail':data+=b'extra'
    elif mode=='wrongkey':key='objects/'+'0'*64+'.zjson'
    elif mode=='wrongrole':role='DETAILS'
    else:terminal=1
    with packed.PackedStatus(tmp_path,binding(),create=True)as store:
        with pytest.raises(ValueError):store.put(key,data,role=role,terminal=terminal)
        assert store.snapshot()['logical_objects']==0
        assert not list(store.directory.glob('block-*.bin'))


def test_terminal_object_escrow_refuses_ordinary_before_body_but_allows_terminal(tmp_path,monkeypatch):
    monkeypatch.setattr(packed,'MAX_OBJECTS',4)
    monkeypatch.setattr(packed,'TERMINAL_OBJECTS',2)
    with packed.PackedStatus(tmp_path,binding(),create=True)as store:
        for number in range(2):
            key,data=field(number);store.put(key,data,role='FIELD')
        old=store.snapshot()['block_bytes'];key,data=field(2)
        with pytest.raises(ValueError,match='terminal logical'):store.put(key,data,role='FIELD')
        assert store.snapshot()['block_bytes']==old
        assert store.put(key,data,role='FIELD',terminal=True)['sequence']==3


def test_index_commit_failure_keeps_old_range_and_quarantines_unknown_tail(tmp_path,monkeypatch):
    store=packed.PackedStatus(tmp_path,binding(),create=True);key,data=field()
    store.put(key,data,role='FIELD');nextkey,nextdata=field(1)
    def fail():raise OSError('injected index commit failure')
    monkeypatch.setattr(store,'_commit',fail)
    with pytest.raises(OSError,match='injected'):store.put(nextkey,nextdata,role='FIELD')
    assert store.failed
    with pytest.raises(ValueError,match='quarantined'):store.put(*field(2),role='FIELD')
    store.close()
    with packed.PackedStatus(tmp_path,binding())as reader:
        assert reader.read(key)==data
        with pytest.raises(ValueError,match='not committed'):reader.read(nextkey)
        with pytest.raises(ValueError):reader.verify_import()


def test_ordinary_append_never_reads_previous_sealed_blocks(tmp_path,monkeypatch):
    monkeypatch.setattr(packed,'BLOCK_BYTES',1800)
    monkeypatch.setattr(packed,'MAX_BYTES',1800*128)
    monkeypatch.setattr(packed,'TERMINAL_BYTES',3600)
    with packed.PackedStatus(tmp_path,binding(),create=True)as store:
        for number in range(9):
            key,data=field(number);store.put(key,data,role='FIELD')
        assert store.snapshot()['blocks']>=3
        assert store.snapshot()['old_prefix_bytes_read_on_put']==0
        assert store.snapshot()['old_prefix_counter_scope'].startswith('PREVIOUSLY_SEALED')


def test_publisher_consumes_packed_store_and_hydrates_exact_full_job(tmp_path):
    from types import SimpleNamespace
    class Writer:
        def __init__(self,*args,**kwargs):self.sequence=0;self.head=SimpleNamespace(closed=False)
        def publish(self,value,*,terminal=False):self.sequence+=1;return self.sequence
        def close(self):self.head.closed=True
    value=job();value['progress']=dict(payload='x'*70000)
    plan=status.preflight(value,binding(),packed_store=True)
    assert plan.envelope['format']==status.STORAGE_PACKED
    writer=status.Publisher(tmp_path/'status63',binding(),LifecycleStreamPolicy(),writer_factory=Writer,packed_store=True)
    try:
        assert writer.publish(plan)==1
        assert status.hydrate(writer.directory,plan.envelope,binding())==dict(value,publication_sequence=1)
        assert writer.packed.snapshot()['logical_objects']>0
    finally:writer.close()


def test_explicit_full_import_rejects_unused_corrupt_sealed_block(tmp_path):
    key,data=field()
    with packed.PackedStatus(tmp_path,binding(),create=True)as store:store.put(key,data,role='FIELD')
    block=next((tmp_path/'packed-v1').glob('block-*.bin'));content=block.read_bytes()
    block.write_bytes(bytes([content[0]^1])+content[1:])
    with packed.PackedStatus(tmp_path,binding())as store:
        with pytest.raises(ValueError,match='block hash'):store.verify_import()


def test_head_failure_never_publishes_a_tip_ahead_of_missing_object(tmp_path):
    from types import SimpleNamespace
    class FailingHead:
        def __init__(self,*args,**kwargs):self.head=SimpleNamespace(closed=False)
        def publish(self,*args,**kwargs):raise OSError('injected head publication refusal')
        def close(self):self.head.closed=True
    value=job();value['progress']=dict(payload='x'*70000)
    plan=status.preflight(value,binding(),packed_store=True)
    writer=status.Publisher(tmp_path/'status63',binding(),LifecycleStreamPolicy(),writer_factory=FailingHead,packed_store=True)
    try:
        with pytest.raises(OSError,match='head publication'):writer.publish(plan)
        assert writer.sequence==0
        # Durable administrative objects may precede an absent head; a head
        # never precedes its objects. This is not a scientific checkpoint.
        assert status.hydrate(writer.directory,plan.envelope,binding())==dict(value,publication_sequence=1)
    finally:writer.close()


@pytest.mark.skipif(not hasattr(os,'link'),reason='hardlink API unavailable')
def test_block_hardlink_is_not_independent_owned_storage(tmp_path):
    key,data=field()
    with packed.PackedStatus(tmp_path,binding(),create=True)as store:store.put(key,data,role='FIELD')
    block=next((tmp_path/'packed-v1').glob('block-*.bin'))
    try:os.link(block,tmp_path/'alias')
    except OSError as error:pytest.skip('filesystem does not permit test hardlink: '+str(error))
    with packed.PackedStatus(tmp_path,binding())as store:
        with pytest.raises(ValueError,match='single-link'):store.read(key)
